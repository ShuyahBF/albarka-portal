"""Gestion des clients (staff only)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from albarka_auth import get_current_user, hash_password, require_roles, require_staff
from albarka_admin_settings import get_settings_doc
from albarka_models import (
    ALBARKA_ROLES, CLIENT_MANAGE_ROLES, VERIFY_PHONE_ROLES, User, hide_test_accounts_filter,
    is_admin_account, is_client, is_test_account, modification_stamp,
)
from db import db, serialize, serialize_many

router = APIRouter(prefix="/clients", tags=["Clients"])


def _mask_phone(phone: Optional[str]) -> Optional[str]:
    """RGPD : ne laisse apparaître que l'indicatif et les 2 derniers chiffres."""
    if not phone or len(phone) < 5:
        return phone
    return phone[:4] + "••••" + phone[-2:]


async def _apply_rgpd_masking(docs: List[dict], viewer: dict) -> List[dict]:
    if set(viewer.get("roles") or []) & set(CLIENT_MANAGE_ROLES):
        return docs
    settings = await get_settings_doc()
    if not settings.get("rgpd_masking_enabled", True):
        return docs
    for d in docs:
        d["phone"] = _mask_phone(d.get("phone"))
        d["whatsapp_number"] = _mask_phone(d.get("whatsapp_number"))
    return docs


class ClientCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=200)
    company: Optional[str] = None
    phone: Optional[str] = None
    # Numéro WhatsApp distinct du téléphone — facultatif, laisser vide si
    # identique (voir is_whatsapp_verified()/whatsapp_number_of() dans
    # albarka_models.py pour la logique de repli).
    whatsapp_number: Optional[str] = None
    password: str = Field(..., min_length=8)
    can_receive_notifications: bool = True


class StaffCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=200)
    roles: List[str] = Field(..., min_length=1)
    company: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=8)
    can_receive_notifications: bool = True

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, v: List[str]) -> List[str]:
        unknown = set(v) - set(ALBARKA_ROLES)
        if unknown:
            raise ValueError(f"Rôle(s) invalide(s) : {sorted(unknown)}")
        if "client" in v:
            raise ValueError("Utiliser /clients pour créer un compte client")
        return v


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    company: Optional[str] = None
    phone: Optional[str] = None
    whatsapp_number: Optional[str] = None
    is_active: Optional[bool] = None
    can_receive_notifications: Optional[bool] = None
    roles: Optional[List[str]] = None

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, v):
        if v is None:
            return v
        if len(v) == 0:
            raise ValueError("Au moins un rôle est requis")
        unknown = set(v) - set(ALBARKA_ROLES)
        if unknown:
            raise ValueError(f"Rôle(s) invalide(s) : {sorted(unknown)}")
        # `client` est exclusif : impossible à cumuler avec un rôle cabinet.
        if "client" in v and len(v) > 1:
            raise ValueError("Le rôle 'client' ne peut pas être cumulé avec un rôle cabinet")
        return v


def _public(user: dict) -> dict:
    user.pop("password_hash", None)
    return serialize(user)


@router.get("")
async def list_clients(user: dict = Depends(require_staff())):
    # Comptes de test : visibles du superviseur uniquement
    docs = await db.users.find(
        {"roles": "client", **hide_test_accounts_filter(user)}, {"_id": 0, "password_hash": 0}
    ).sort("created_at", -1).to_list(1000)
    return serialize_many(await _apply_rgpd_masking(docs, user))


@router.get("/staff")
async def list_staff(user: dict = Depends(require_staff())):
    # Comptes de test : visibles du superviseur uniquement
    docs = await db.users.find(
        {"roles": {"$nin": ["client"]}, **hide_test_accounts_filter(user)}, {"_id": 0, "password_hash": 0}
    ).sort("created_at", -1).to_list(1000)
    return serialize_many(docs)


@router.post("")
async def create_client(payload: ClientCreate, user: dict = Depends(require_roles(CLIENT_MANAGE_ROLES))):
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Un compte avec cet email existe déjà")
    user_doc = {
        "id": secrets.token_urlsafe(12),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "roles": ["client"],
        "company": payload.company,
        "phone": payload.phone,
        "phone_verified": False,
        "whatsapp_number": payload.whatsapp_number,
        "whatsapp_verified": False,
        "is_active": True,
        "can_receive_notifications": payload.can_receive_notifications,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **modification_stamp(user),
        "last_login": None,
    }
    await db.users.insert_one(user_doc.copy())
    return _public(user_doc)


def _is_admin(u: dict) -> bool:
    """Retourne True si l'utilisateur porte le rôle privilégié `administrateur`."""
    return "administrateur" in (u.get("roles") or [])


_SUPERVISEUR_RESERVED = "Le rôle Superviseur ne peut être attribué ou retiré que par le compte admin du portail"


@router.post("/staff")
async def create_staff(payload: StaffCreate, user: dict = Depends(require_staff())):
    # Rôle Superviseur (tous les droits) : seul le compte admin du portail le donne.
    if "superviseur" in payload.roles and not is_admin_account(user):
        raise HTTPException(status_code=403, detail=_SUPERVISEUR_RESERVED)
    # Point 10 — seul un `administrateur` peut créer un compte administrateur.
    if "administrateur" in payload.roles and not _is_admin(user):
        raise HTTPException(
            status_code=403,
            detail="Seul un compte Administrateur peut créer un autre Administrateur",
        )
    existing = await db.users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Un compte avec cet email existe déjà")
    user_doc = {
        "id": secrets.token_urlsafe(12),
        "email": payload.email.lower(),
        "password_hash": hash_password(payload.password),
        "full_name": payload.full_name,
        "roles": payload.roles,
        "company": payload.company,
        "phone": payload.phone,
        "is_active": True,
        "can_receive_notifications": payload.can_receive_notifications,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **modification_stamp(user),
        "last_login": None,
    }
    await db.users.insert_one(user_doc.copy())
    return _public(user_doc)


# ---------------------------------------------------------------- comptes de test
# Bouton « Créer comptes de test » (Personnels, superviseur uniquement).
# Chaque compte reçoit une adresse « +alias » de l'e-mail choisi, pour que
# TOUS les codes de connexion (OTP) arrivent dans la même boîte (Gmail et la
# plupart des messageries acceptent l'alias « +… »). Les comptes portent
# is_test_account=True : invisibles de tous sauf du superviseur, exclus des
# envois de masse.
TEST_ACCOUNTS = [
    # (alias, nom affiché, rôles, entreprise)
    ("test-superviseur", "TEST Superviseur", ["superviseur"], None),
    ("test-secretaire", "TEST Secrétaire A", ["secretariat"], None),
    ("test-caissiere", "TEST Secrétaire B (caissière)", ["secretariat", "caissier"], None),
    ("test-formulaires", "TEST Collaborateur Formulaires", ["comptable", "formulaires"], None),
    ("test-comptable", "TEST Comptable", ["comptable"], None),
    ("test-client1", "TEST Client 1", ["client"], "Client Test 1"),
    ("test-client2", "TEST Client 2", ["client"], "Client Test 2"),
]


class TestAccountsPayload(BaseModel):
    email: EmailStr                       # boîte qui recevra tous les codes de connexion
    password: str = Field(..., min_length=8)
    client1_whatsapp: Optional[str] = None  # +226… (a écrit au WhatsApp du cabinet < 24 h)
    client2_whatsapp: Optional[str] = None  # +226… (n'a pas écrit depuis 24 h)


def _alias_email(base: str, alias: str) -> str:
    local, domain = base.lower().split("@", 1)
    local = local.split("+", 1)[0]
    return f"{local}+{alias}@{domain}"


@router.post("/test-accounts")
async def create_test_accounts(payload: TestAccountsPayload, user: dict = Depends(require_roles(["superviseur"]))):
    """Crée (ou remet à neuf) les comptes de test de la recette. Le compte
    « TEST Superviseur » n'est créé que si le compte admin du portail lance
    l'opération (seul habilité à donner ce rôle)."""
    for w in (payload.client1_whatsapp, payload.client2_whatsapp):
        if w and not w.strip().startswith("+"):
            raise HTTPException(status_code=400, detail="Numéro WhatsApp attendu au format international (+226…)")
    now = datetime.now(timezone.utc).isoformat()
    phones = {"test-client1": payload.client1_whatsapp, "test-client2": payload.client2_whatsapp}
    results = []
    for alias, name, roles, company in TEST_ACCOUNTS:
        email = _alias_email(payload.email, alias)
        if "superviseur" in roles and not is_admin_account(user):
            results.append({"email": email, "name": name, "roles": roles, "status": "ignoré",
                            "detail": "Seul le compte admin du portail peut créer un superviseur"})
            continue
        fields = {
            "full_name": name, "roles": roles, "company": company, "is_active": True, "is_test_account": True,
            "password_hash": hash_password(payload.password), "can_receive_notifications": True,
            "phone": (phones.get(alias) or "").strip() or None,
            # Numéro de test fourni par le superviseur : considéré comme vérifié
            "phone_verified": bool(phones.get(alias)),
        }
        existing = await db.users.find_one({"email": email}, {"_id": 0, "id": 1, "is_test_account": 1})
        if existing and not existing.get("is_test_account"):
            results.append({"email": email, "name": name, "roles": roles, "status": "ignoré",
                            "detail": "Un vrai compte utilise déjà cette adresse"})
            continue
        if existing:
            await db.users.update_one({"id": existing["id"]}, {"$set": fields})
            status = "mis à jour"
        else:
            await db.users.insert_one({"id": secrets.token_urlsafe(12), "email": email, "created_at": now,
                                       "last_login": None, **fields})
            status = "créé"
        results.append({"email": email, "name": name, "roles": roles, "status": status})
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action="test_accounts.create", entity_type="user",
                              meta={"count": sum(r["status"] != "ignoré" for r in results)})
    return {"accounts": results}


@router.delete("/test-accounts")
async def delete_test_accounts(user: dict = Depends(require_roles(["superviseur"]))):
    """Supprime tous les comptes de test (un vrai compte n'est jamais touché)."""
    res = await db.users.delete_many({"is_test_account": True})
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action="test_accounts.delete", entity_type="user",
                              meta={"count": res.deleted_count})
    return {"deleted": res.deleted_count}


@router.get("/{user_id}")
async def get_client(user_id: str, user: dict = Depends(require_staff())):
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if is_test_account(doc) and hide_test_accounts_filter(user):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if is_client(doc):
        (await _apply_rgpd_masking([doc], user))
    return serialize(doc)


@router.patch("/{user_id}")
async def update_client(user_id: str, payload: UserUpdate, user: dict = Depends(require_staff())):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "roles": 1, "email": 1, "is_test_account": 1})
    if not target or (is_test_account(target) and hide_test_accounts_filter(user)):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    current = set(target.get("roles") or [])
    # Un compte Superviseur ne peut être modifié que par un superviseur ou le compte admin.
    if "superviseur" in current and not (is_admin_account(user) or "superviseur" in (user.get("roles") or [])):
        raise HTTPException(status_code=403, detail="Seul un superviseur peut modifier un compte Superviseur")
    # Rôle Superviseur : attribution ou retrait réservés au compte admin du portail.
    if "roles" in update and ("superviseur" in current) != ("superviseur" in set(update["roles"])) \
            and not is_admin_account(user):
        raise HTTPException(status_code=403, detail=_SUPERVISEUR_RESERVED)
    # La restriction "création/modification de clients" ne s'applique qu'aux
    # comptes clients — modifier un collaborateur reste géré séparément
    # (voir AdminStaff.jsx, qui limite déjà sa propre UI à admin/superviseur/direction).
    if is_client(target) and not set(user.get("roles") or []) & set(CLIENT_MANAGE_ROLES):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")
    # Point 10 — seul un `administrateur` peut attribuer/retirer le rôle `administrateur`.
    if "roles" in update:
        current_roles = set(target.get("roles") or [])
        new_roles = set(update["roles"])
        touches_admin = ("administrateur" in current_roles) != ("administrateur" in new_roles)
        if touches_admin and not _is_admin(user):
            raise HTTPException(
                status_code=403,
                detail="Seul un compte Administrateur peut attribuer ou retirer le rôle Administrateur",
            )
    update.update(modification_stamp(user))  # dernière modification : quand et par qui
    res = await db.users.update_one({"id": user_id}, {"$set": update})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return serialize(doc)


class VerifyPhonePayload(BaseModel):
    verified: bool = True


@router.patch("/{user_id}/verify-phone")
async def verify_client_phone(
    user_id: str, payload: VerifyPhonePayload, user: dict = Depends(require_roles(VERIFY_PHONE_ROLES)),
):
    """Atteste (ou révoque) qu'un numéro client est de confiance — condition
    d'accès à l'action "Envoyer par WhatsApp" pour le rôle Communication
    seul (voir _can_send_whatsapp dans albarka_documents.py)."""
    res = await db.users.update_one({"id": user_id}, {"$set": {"phone_verified": payload.verified, **modification_stamp(user)}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return serialize(doc)


@router.patch("/{user_id}/verify-whatsapp")
async def verify_client_whatsapp(
    user_id: str, payload: VerifyPhonePayload, user: dict = Depends(require_roles(VERIFY_PHONE_ROLES)),
):
    """Pendant de verify_client_phone pour le numéro WhatsApp dédié (voir
    is_whatsapp_verified() dans albarka_models.py)."""
    res = await db.users.update_one({"id": user_id}, {"$set": {"whatsapp_verified": payload.verified, **modification_stamp(user)}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return serialize(doc)


@router.delete("/{user_id}")
async def delete_client(user_id: str, user: dict = Depends(require_staff())):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Impossible de supprimer votre propre compte")
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not target or (is_test_account(target) and hide_test_accounts_filter(user)):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    # Compte client : suppression réservée à admin (super-utilisateur du portail).
    if is_client(target) and not is_admin_account(user):
        raise HTTPException(status_code=403, detail="Seul admin peut supprimer un compte client")
    # Compte du personnel : suppression réservée au superviseur ; le compte admin
    # du portail n'est jamais supprimable, un superviseur seulement par lui.
    if is_client(target):
        await db.deleted_users.insert_one({**target, "deleted_at": datetime.now(timezone.utc).isoformat(),
                                           "deleted_by": user["id"]})
        from albarka_phase_c import _log_platform_event  # import local : évite un cycle
        await _log_platform_event(user=user, action="client.delete", entity_type="user", entity_id=user_id,
                                  meta={"email": target.get("email"), "company": target.get("company")})
    else:
        if "superviseur" not in (user.get("roles") or []):
            raise HTTPException(status_code=403, detail="Seul le superviseur peut supprimer un compte du personnel")
        if is_admin_account(target):
            raise HTTPException(status_code=403, detail="Le compte admin du portail ne peut pas être supprimé")
        if "superviseur" in (target.get("roles") or []) and not is_admin_account(user):
            raise HTTPException(status_code=403, detail="Seul le compte admin du portail peut supprimer un superviseur")
        # Trace de la suppression (le compte lui-même est effacé)
        await db.deleted_users.insert_one({**target, "deleted_at": datetime.now(timezone.utc).isoformat(),
                                           "deleted_by": user["id"]})
        from albarka_phase_c import _log_platform_event  # import local : évite un cycle
        await _log_platform_event(user=user, action="staff.delete", entity_type="user", entity_id=user_id,
                                  meta={"email": target.get("email"), "roles": target.get("roles")})
    res = await db.users.delete_one({"id": user_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {"ok": True, "id": user_id}



# ---------------------------------------------------------------- actions sur un compte
# Désactiver / réactiver et réinitialiser le mot de passe, pour les clients
# (rôles de gestion des clients) et le personnel (superviseur, direction,
# administrateur). Un compte Superviseur : superviseur ou admin seulement ;
# le compte admin : lui seul.
_STAFF_ACCOUNT_ROLES = ["superviseur", "direction", "administrateur"]


async def _account_for_action(user_id: str, actor: dict) -> dict:
    target = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not target or (is_test_account(target) and hide_test_accounts_filter(actor)):
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    roles = set(actor.get("roles") or [])
    allowed = CLIENT_MANAGE_ROLES if is_client(target) else _STAFF_ACCOUNT_ROLES
    if not ("superviseur" in roles or roles & set(allowed) or is_admin_account(actor)):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")
    if is_admin_account(target) and not is_admin_account(actor):
        raise HTTPException(status_code=403, detail="Seul admin peut agir sur le compte admin")
    if "superviseur" in (target.get("roles") or []) and not ("superviseur" in roles or is_admin_account(actor)):
        raise HTTPException(status_code=403, detail="Seul un superviseur peut agir sur un compte Superviseur")
    return target


class ActivePayload(BaseModel):
    active: bool


@router.post("/{user_id}/active")
async def set_account_active(user_id: str, payload: ActivePayload, user: dict = Depends(require_staff())):
    """Désactive (plus aucune connexion possible, effet immédiat) ou réactive un compte."""
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Impossible de désactiver votre propre compte")
    target = await _account_for_action(user_id, user)
    await db.users.update_one({"id": user_id}, {"$set": {"is_active": payload.active, **modification_stamp(user)}})
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action="account.activate" if payload.active else "account.deactivate",
                              entity_type="user", entity_id=user_id, meta={"email": target.get("email")})
    return serialize(await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0}))


class ResetPasswordPayload(BaseModel):
    # Vide : un mot de passe temporaire est généré et affiché une seule fois.
    password: Optional[str] = Field(None, min_length=8, max_length=128)


def _temporary_password() -> str:
    """Mot de passe temporaire lisible (sans caractères ambigus 0/O, 1/l/I)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, payload: ResetPasswordPayload, user: dict = Depends(require_staff())):
    """Réinitialise le mot de passe d'un client ou d'un collaborateur. Les
    sessions ouvertes de ce compte sont fermées (reconnexion obligatoire)."""
    target = await _account_for_action(user_id, user)
    password = payload.password or _temporary_password()
    now = datetime.now(timezone.utc).isoformat()
    await db.users.update_one({"id": user_id}, {"$set": {
        "password_hash": hash_password(password), "password_changed_at": now, **modification_stamp(user)}})
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action="account.reset_password", entity_type="user", entity_id=user_id,
                              meta={"email": target.get("email")})  # jamais le mot de passe dans le journal
    return {"ok": True, "password": password, "generated": payload.password is None}
