"""Lot 89 — Connexion par empreinte digitale (« passkeys » / WebAuthn) sur le portail ALBARKA.

POURQUOI WEBAUTHN
   Un site web ne peut pas lire un lecteur d'empreintes. Le standard des navigateurs (WebAuthn) vérifie l'empreinte
   LOCALEMENT (téléphone, Windows Hello, clé de sécurité) ; le serveur ne reçoit JAMAIS l'empreinte, seulement une
   signature qu'il vérifie avec la CLÉ PUBLIQUE enregistrée à l'enrôlement.

QUI FAIT QUOI (demande du propriétaire, 13/11/2026)
   - Le SUPER-ADMIN (rôle « superviseur ») ACTIVE ou désactive la fonction (réglage `empreinte_activee`, FAUX par défaut,
     dans Paramètres). Il ne gère aucun enrôlement.
   - Le DG (rôle « dg ») est le SEUL à gérer les enrôlements, et seulement si la fonction est activée :
     il génère un code d'enrôlement pour une personne, la personne l'utilise sur son appareil depuis la page de
     connexion, puis le DG peut retirer les empreintes d'un compte (appareil perdu, départ).
   - Tout le monde peut ensuite se connecter par empreinte depuis la page de connexion ; le mot de passe + code reste
     toujours possible (secours).

ROUTES (sous /api)
   GET    /auth/passkeys/config                 — public : la fonction est-elle activée ?
   POST   /auth/passkeys/login/options          — public : défi à signer
   POST   /auth/passkeys/login/verify           — public : signature → mêmes contrôles qu'une connexion → jeton
   POST   /auth/passkeys/enroll/options         — public : code d'enrôlement valide → défi d'enregistrement
   POST   /auth/passkeys/enroll/verify          — public : enregistre la clé publique (consomme le code)
   GET    /admin/passkeys                       — DG : état, comptes qui ont une empreinte, personnes enrôlables
   POST   /admin/passkeys/invitations           — DG : code d'enrôlement pour une personne (15 min, usage unique)
   DELETE /admin/passkeys/user/{user_id}        — DG : retire toutes les empreintes d'un compte

DÉCISIONS
   - AUCUNE nouvelle collection : clés publiques dans le champ `passkeys` de `users`, défis et codes d'enrôlement dans
     `otps` (types « passkey_challenge » et « passkey_invite », usage unique, expiration).
   - L'empreinte remplace le mot de passe ET le code (« quelque chose que l'on possède » + « que l'on est »).
   - Mêmes refus que la connexion normale : compte inactif, maintenance, liste blanche du personnel, contrat (si le
     super-admin interdit les clients sans contrat).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from albarka_auth import (
    User,
    AuthTokenResponse,
    clients_sans_contrat_interdits,
    create_access_token,
    get_current_user,
)
from db import db

logger = logging.getLogger("albarka.passkeys")

router = APIRouter(tags=["Empreinte digitale"])

TYPE_DEFI = "passkey_challenge"      # défi éphémère (collection `otps`)
TYPE_INVITATION = "passkey_invite"   # code d'enrôlement créé par le DG (collection `otps`)
DUREE_DEFI_S = 180                   # un défi vaut 3 minutes, une seule fois
DUREE_INVITATION_MIN = 15            # un code d'enrôlement vaut 15 minutes, une seule fois
MAX_PAR_COMPTE = 8                   # empreintes (appareils) au plus par compte
LIMITE_DEMANDES = 30                 # demandes publiques par adresse IP et par minute (pas de remplissage de la base)
FENETRE_LIMITE_S = 60
NOM_PLATEFORME = "ALBARKA"
_RP_VALIDE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
_ALPHABET_CODE = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # sans I, O, 0, 1 : lisible à voix haute
_demandes: Dict[str, List[float]] = {}                # adresse IP -> instants des demandes (mémoire du serveur)


# ---------------------------------------------------------------- modèles de corps
class DefiReponse(BaseModel):
    """Corps de /auth/passkeys/login/verify : le défi et la réponse signée du navigateur."""
    challenge_id: str
    credential: Dict[str, Any]
    device_id: Optional[str] = None       # liste blanche du personnel (comme /auth/verify-otp)
    access_code: Optional[str] = None


class EnrolementOptions(BaseModel):
    """Corps de /auth/passkeys/enroll/options : le code remis par le DG."""
    code: str = Field(..., min_length=4, max_length=20)


class EnrolementVerif(BaseModel):
    """Corps de /auth/passkeys/enroll/verify : code, défi, réponse du navigateur et nom de l'appareil."""
    code: str = Field(..., min_length=4, max_length=20)
    challenge_id: str
    credential: Dict[str, Any]
    nom: str = Field(default="", max_length=60)


class InvitationCorps(BaseModel):
    user_id: str


# ---------------------------------------------------------------- utilitaires
def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _iso(d: datetime) -> str:
    return d.isoformat()


def _hash_code(code: str) -> str:
    """Le code d'enrôlement n'est jamais gardé en clair en base."""
    return hashlib.sha256((code or "").strip().upper().replace("-", "").encode()).hexdigest()


def _vue(p: dict) -> dict:
    """Une empreinte telle qu'affichée : jamais la clé publique ni le compteur."""
    return {"id": p.get("id"), "nom": p.get("nom") or "Appareil", "cree_le": p.get("cree_le"), "dernier_usage": p.get("dernier_usage")}


def _limiter(request: Request) -> None:
    """429 au-delà de LIMITE_DEMANDES par minute et par adresse IP (les routes publiques écrivent en base)."""
    from albarka_access import client_ip
    ip = client_ip(request) or "?"
    t = time.monotonic()
    recentes = [x for x in _demandes.get(ip, []) if t - x < FENETRE_LIMITE_S]
    if len(recentes) >= LIMITE_DEMANDES:
        _demandes[ip] = recentes
        raise HTTPException(status_code=429, detail="Trop de tentatives : patientez une minute")
    recentes.append(t)
    _demandes[ip] = recentes
    if len(_demandes) > 5000:   # ménage des adresses sans demande récente
        for cle in [k for k, v in _demandes.items() if not v or t - v[-1] >= FENETRE_LIMITE_S]:
            _demandes.pop(cle, None)


def origine_et_domaine(entete_origine: str, rp_reglage: Optional[str]) -> Tuple[str, str]:
    """Origine de la page et domaine WebAuthn (RP ID), validés. HTTPS exigé (sauf localhost) ; le domaine doit couvrir
    l'hôte de la page. Sans réglage : variable WEBAUTHN_RP_ID, sinon le nom d'hôte de la page."""
    origine = (entete_origine or "").strip().rstrip("/")
    p = urlparse(origine)
    if p.scheme not in ("https", "http") or not p.hostname:
        raise HTTPException(status_code=400, detail="Adresse de la page absente ou invalide")
    hote = p.hostname.lower()
    if p.scheme == "http" and hote not in ("localhost", "127.0.0.1"):
        raise HTTPException(status_code=400, detail="La connexion par empreinte exige une page en HTTPS")
    rp = (rp_reglage or os.environ.get("WEBAUTHN_RP_ID") or "").strip().lower() or hote
    if not (hote == rp or hote.endswith("." + rp)):
        raise HTTPException(status_code=400, detail="Cette adresse ne correspond pas au domaine réglé pour l'empreinte")
    return f"{p.scheme}://{p.netloc}", rp


async def _reglages() -> Dict[str, Any]:
    """Réglages de la fonction (document `settings` global) : activée ? domaine imposé ?"""
    s = await db.settings.find_one({"_id": "global"}, {"empreinte_activee": 1, "empreinte_rp_id": 1}) or {}
    return {"enabled": bool(s.get("empreinte_activee")), "rp_id": (s.get("empreinte_rp_id") or "").strip().lower() or None}


async def _exiger_active() -> Dict[str, Any]:
    r = await _reglages()
    if not r["enabled"]:
        raise HTTPException(status_code=403, detail="La connexion par empreinte n'est pas activée")
    return r


def _exiger_dg(user: dict) -> None:
    """Gestion des enrôlements : le DG UNIQUEMENT (ni le super-admin, ni la Direction)."""
    if "dg" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Seul le DG gère les empreintes digitales")


async def _creer_defi(objet: str, user_id: Optional[str], defi: bytes) -> str:
    """Garde le défi (usage unique, 3 min) dans `otps` ; nettoie les défis expirés au passage."""
    now = _maintenant()
    await db.otps.delete_many({"type": {"$in": [TYPE_DEFI, TYPE_INVITATION]}, "expires_at": {"$lt": _iso(now)}})
    identifiant = secrets.token_urlsafe(12)
    await db.otps.insert_one({
        "id": identifiant, "type": TYPE_DEFI, "objet": objet, "user_id": user_id, "used": False,
        "challenge": bytes_to_base64url(defi), "created_at": _iso(now), "expires_at": _iso(now + timedelta(seconds=DUREE_DEFI_S)),
    })
    return identifiant


async def _consommer_defi(identifiant: str, objet: str, user_id: Optional[str] = None) -> bytes:
    """Marque le défi utilisé (atomique) et le renvoie ; refuse un défi inconnu, expiré ou d'un autre compte."""
    doc = await db.otps.find_one_and_update({"id": identifiant, "type": TYPE_DEFI, "objet": objet, "used": False}, {"$set": {"used": True}})
    if not doc or doc.get("expires_at", "") < _iso(_maintenant()) or (user_id is not None and doc.get("user_id") != user_id):
        raise HTTPException(status_code=400, detail="Défi expiré ou invalide : recommencez")
    return base64url_to_bytes(doc["challenge"])


async def _invitation_valide(code: str) -> dict:
    """Retrouve l'invitation (code non utilisé et non expiré) ; sinon 400 neutre."""
    inv = await db.otps.find_one({"type": TYPE_INVITATION, "code_hash": _hash_code(code), "used": False})
    if not inv or inv.get("expires_at", "") < _iso(_maintenant()):
        raise HTTPException(status_code=400, detail="Code d'enrôlement inconnu ou expiré : demandez-en un nouveau au DG")
    return inv


# ---------------------------------------------------------------- public
@router.get("/auth/passkeys/config")
async def passkeys_config():
    """La page de connexion n'affiche le bouton « Se connecter avec mon empreinte » que si c'est activé."""
    return {"enabled": (await _reglages())["enabled"]}


@router.post("/auth/passkeys/login/options")
async def passkeys_login_options(request: Request):
    """Défi à signer. Aucun compte nommé : la passkey « découvrable » identifie la personne."""
    _limiter(request)
    r = await _exiger_active()
    _, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
    options = generate_authentication_options(rp_id=rp, user_verification=UserVerificationRequirement.REQUIRED)
    return {"challenge_id": await _creer_defi("connexion", None, options.challenge), "options": json.loads(options_to_json(options))}


@router.post("/auth/passkeys/login/verify", response_model=AuthTokenResponse)
async def passkeys_login_verify(payload: DefiReponse, request: Request):
    """Vérifie la signature puis applique les mêmes refus qu'une connexion par mot de passe + code."""
    _limiter(request)
    r = await _exiger_active()
    origine, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
    defi = await _consommer_defi(payload.challenge_id, "connexion")
    identifiant = payload.credential.get("id")
    if not isinstance(identifiant, str) or not identifiant:
        raise HTTPException(status_code=400, detail="Réponse du navigateur invalide")
    user = await db.users.find_one({"passkeys.id": identifiant})
    if not user:
        raise HTTPException(status_code=401, detail="Empreinte inconnue ou retirée : connectez-vous avec votre mot de passe")
    entree = next(p for p in user["passkeys"] if p.get("id") == identifiant)
    try:
        verifiee = verify_authentication_response(
            credential=payload.credential, expected_challenge=defi, expected_rp_id=rp, expected_origin=origine,
            credential_public_key=base64url_to_bytes(entree["public_key"]),
            credential_current_sign_count=int(entree.get("sign_count") or 0), require_user_verification=True)
        handle = (payload.credential.get("response") or {}).get("userHandle")
        if handle and base64url_to_bytes(handle) != str(user["id"]).encode():
            raise ValueError("identifiant de compte incohérent")
    except Exception as exc:  # noqa: BLE001 — toute anomalie = refus, jamais d'indice sur la cause
        logger.info("[empreinte] connexion refusée : %s", exc)
        raise HTTPException(status_code=401, detail="Empreinte non vérifiée : réessayez ou utilisez votre mot de passe")
    # Mêmes contrôles que /auth/verify-otp
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")
    from albarka_maintenance import refuser_connexion_si_maintenance
    await refuser_connexion_si_maintenance(user)
    from albarka_access import check_staff_access
    access_until = await check_staff_access(user, request=request, device_id=payload.device_id, access_code=payload.access_code)
    roles = set(user.get("roles") or [])
    if "client" in roles and len(roles) == 1 and await clients_sans_contrat_interdits():
        from albarka_contracts import has_active_contract
        if not await has_active_contract(user["id"]):
            raise HTTPException(status_code=403, detail="Aucun contrat actif — veuillez contacter votre cabinet ALBARKA pour activer votre accès.")
    maintenant = _iso(_maintenant())
    await db.users.update_one({"id": user["id"], "passkeys.id": identifiant}, {"$set": {
        "passkeys.$.sign_count": verifiee.new_sign_count, "passkeys.$.dernier_usage": maintenant, "last_login": maintenant}})
    user.pop("password_hash", None)
    user.pop("_id", None)
    return AuthTokenResponse(access_token=create_access_token(user["id"], not_after=access_until), user=User(**user))


@router.post("/auth/passkeys/enroll/options")
async def passkeys_enroll_options(payload: EnrolementOptions, request: Request):
    """Défi d'enregistrement pour la personne à qui le DG a remis un code (le code n'est pas encore consommé)."""
    _limiter(request)
    r = await _exiger_active()
    _, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
    inv = await _invitation_valide(payload.code)
    user = await db.users.find_one({"id": inv["user_id"]}, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "passkeys": 1, "is_active": 1})
    if not user or not user.get("is_active", True):
        raise HTTPException(status_code=400, detail="Compte introuvable ou désactivé")
    existantes = user.get("passkeys") or []
    if len(existantes) >= MAX_PAR_COMPTE:
        raise HTTPException(status_code=400, detail=f"{MAX_PAR_COMPTE} appareils au plus par compte : le DG doit en retirer")
    options = generate_registration_options(
        rp_id=rp, rp_name=NOM_PLATEFORME, user_id=str(user["id"]).encode(), user_name=user["email"],
        user_display_name=user.get("full_name") or user["email"],
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED, user_verification=UserVerificationRequirement.REQUIRED),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=base64url_to_bytes(p["id"])) for p in existantes])
    return {"challenge_id": await _creer_defi("enregistrement", user["id"], options.challenge), "options": json.loads(options_to_json(options)),
            "nom": user.get("full_name") or user["email"]}


@router.post("/auth/passkeys/enroll/verify")
async def passkeys_enroll_verify(payload: EnrolementVerif, request: Request):
    """Enregistre la clé publique et consomme le code d'enrôlement (usage unique)."""
    _limiter(request)
    r = await _exiger_active()
    origine, rp = origine_et_domaine(request.headers.get("origin", ""), r["rp_id"])
    inv = await _invitation_valide(payload.code)
    defi = await _consommer_defi(payload.challenge_id, "enregistrement", inv["user_id"])
    try:
        verifiee = verify_registration_response(
            credential=payload.credential, expected_challenge=defi, expected_rp_id=rp, expected_origin=origine, require_user_verification=True)
    except Exception as exc:  # noqa: BLE001
        logger.info("[empreinte] enrôlement refusé : %s", exc)
        raise HTTPException(status_code=400, detail="Enrôlement refusé : l'empreinte n'a pas pu être vérifiée")
    identifiant = bytes_to_base64url(verifiee.credential_id)
    if await db.users.find_one({"passkeys.id": identifiant}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=409, detail="Cet appareil est déjà enregistré")
    nom = re.sub(r"\s+", " ", payload.nom or "").strip() or "Mon appareil"
    entree = {"id": identifiant, "public_key": bytes_to_base64url(verifiee.credential_public_key), "sign_count": verifiee.sign_count,
              "nom": nom, "cree_le": _iso(_maintenant()), "dernier_usage": None, "enrole_par": inv.get("cree_par")}
    # Limite vérifiée dans la requête elle-même : jamais plus de MAX_PAR_COMPTE, même en simultané
    res = await db.users.update_one({"id": inv["user_id"], f"passkeys.{MAX_PAR_COMPTE - 1}": {"$exists": False}}, {"$push": {"passkeys": entree}})
    if res.modified_count == 0:
        raise HTTPException(status_code=400, detail=f"{MAX_PAR_COMPTE} appareils au plus par compte")
    await db.otps.update_one({"id": inv["id"]}, {"$set": {"used": True}})
    logger.info("[empreinte] appareil enrôlé pour %s (code du DG %s)", inv["user_id"], inv.get("cree_par"))
    return {"ok": True}


# ---------------------------------------------------------------- DG
@router.get("/admin/passkeys")
async def admin_passkeys(user: dict = Depends(get_current_user)):
    """Réservé au DG : état de la fonction, personnes enrôlables et comptes qui ont déjà une empreinte (jamais leurs clés)."""
    _exiger_dg(user)
    r = await _reglages()
    comptes: List[dict] = []
    async for u in db.users.find({"is_active": {"$ne": False}}, {"_id": 0, "id": 1, "email": 1, "full_name": 1, "roles": 1, "passkeys": 1}).limit(1000):
        pk = u.get("passkeys") or []
        comptes.append({"user_id": u["id"], "nom": u.get("full_name"), "email": u.get("email"), "roles": u.get("roles") or [],
                        "nb": len(pk), "appareils": [_vue(p) for p in pk]})
    comptes.sort(key=lambda c: (c["nb"] == 0, (c["nom"] or "").lower()))
    return {"enabled": r["enabled"], "max_par_compte": MAX_PAR_COMPTE, "comptes": comptes}


@router.post("/admin/passkeys/invitations")
async def admin_invitation(payload: InvitationCorps, user: dict = Depends(get_current_user)):
    """Réservé au DG : code d'enrôlement (15 min, usage unique) à remettre à la personne. Le code n'est montré qu'ici."""
    _exiger_dg(user)
    await _exiger_active()
    cible = await db.users.find_one({"id": payload.user_id}, {"_id": 0, "id": 1, "full_name": 1, "is_active": 1})
    if not cible or not cible.get("is_active", True):
        raise HTTPException(status_code=404, detail="Compte introuvable ou désactivé")
    code = "".join(secrets.choice(_ALPHABET_CODE) for _ in range(8))
    now = _maintenant()
    # Une seule invitation en cours par personne : la nouvelle annule l'ancienne
    await db.otps.delete_many({"type": TYPE_INVITATION, "user_id": cible["id"], "used": False})
    await db.otps.insert_one({
        "id": secrets.token_urlsafe(12), "type": TYPE_INVITATION, "user_id": cible["id"], "code_hash": _hash_code(code), "used": False,
        "cree_par": user["id"], "created_at": _iso(now), "expires_at": _iso(now + timedelta(minutes=DUREE_INVITATION_MIN))})
    return {"code": f"{code[:4]}-{code[4:]}", "valable_minutes": DUREE_INVITATION_MIN, "nom": cible.get("full_name")}


@router.delete("/admin/passkeys/user/{user_id}")
async def admin_revoquer(user_id: str, user: dict = Depends(get_current_user)):
    """Réservé au DG : retire TOUTES les empreintes d'un compte (appareil perdu, départ d'une personne)."""
    _exiger_dg(user)
    res = await db.users.update_one({"id": user_id, "passkeys.0": {"$exists": True}}, {"$set": {"passkeys": []}})
    if res.modified_count == 0:
        raise HTTPException(status_code=404, detail="Ce compte n'a aucune empreinte")
    logger.info("[empreinte] empreintes du compte %s retirées par le DG %s", user_id, user.get("id"))
    return {"ok": True}
