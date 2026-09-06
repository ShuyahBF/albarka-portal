"""Mon compte — paramètres du compte connecté (tous rôles) + fiche KYC
(comptes clients uniquement).

La partie "paramètres du compte" (nom, téléphone/WhatsApp, mot de passe,
notifications) est accessible à TOUT utilisateur connecté, staff comme
client — contrairement au reste de l'admin, réservé au cabinet.

La fiche KYC (raison sociale, IFU, RCCM, adresse, coordonnées bancaires +
upload photo/pièce d'identité/papier à en-tête) porte l'identité fiscale du
CLIENT — elle n'a pas de sens pour un compte collaborateur, d'où la
restriction is_client() sur ses propres endpoints.

Amélioration ALBARKA par rapport à la référence (ShuyahBF/Emergent,
routes/tenant_kyc.py, qui n'offre que la saisie manuelle) : les pièces
d'identité/registre du commerce téléversées ici sont analysées par l'IA
(albarka_ai.analyze_document, déjà utilisée pour les pièces comptables) —
les champs texte reconnus (raison sociale, IFU, RCCM, adresse) sont
préremplis automatiquement, sans jamais écraser une valeur déjà saisie
manuellement par le client.
"""
from __future__ import annotations

import logging
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from albarka_ai import analyze_document
from albarka_auth import get_current_user, hash_password, verify_password
from albarka_models import is_client
from albarka_storage import guess_content_type, presigned_url, save_and_log
from db import db, serialize

logger = logging.getLogger("albarka.myaccount")

router = APIRouter(prefix="/me", tags=["Mon compte"])

KYC_DOC_TYPES = {"id_photo", "id_card", "letterhead"}
ALLOWED_KYC_EXT = {"jpg", "jpeg", "png", "webp", "pdf"}
MAX_KYC_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 Mo


# ---------------------------------------------------------------------
# Paramètres du compte
# ---------------------------------------------------------------------
class AccountUpdate(BaseModel):
    full_name: Optional[str] = Field(None, min_length=1, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)
    whatsapp_number: Optional[str] = Field(None, max_length=40)
    can_receive_notifications: Optional[bool] = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8)


@router.get("/account")
async def get_my_account(user: dict = Depends(get_current_user)):
    return serialize(user)


@router.patch("/account")
async def update_my_account(payload: AccountUpdate, user: dict = Depends(get_current_user)):
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not changes:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    await db.users.update_one({"id": user["id"]}, {"$set": changes})
    doc = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 0})
    return serialize(doc)


@router.post("/account/change-password")
async def change_my_password(payload: PasswordChange, user: dict = Depends(get_current_user)):
    full = await db.users.find_one({"id": user["id"]}, {"_id": 0, "password_hash": 1})
    if not full or not verify_password(payload.current_password, full["password_hash"]):
        raise HTTPException(status_code=400, detail="Mot de passe actuel incorrect")
    await db.users.update_one(
        {"id": user["id"]}, {"$set": {"password_hash": hash_password(payload.new_password)}},
    )
    return {"ok": True}


# ---------------------------------------------------------------------
# Fiche KYC (clients uniquement)
# ---------------------------------------------------------------------
class KycUpdate(BaseModel):
    business_name: Optional[str] = Field(None, max_length=200)
    ifu: Optional[str] = Field(None, max_length=50)
    rccm: Optional[str] = Field(None, max_length=50)
    address: Optional[str] = Field(None, max_length=300)
    bank_details: Optional[str] = Field(None, max_length=500)


def _require_client(user: dict) -> None:
    if not is_client(user):
        raise HTTPException(status_code=403, detail="Fiche KYC réservée aux comptes clients")


def _empty_kyc(tenant_id: str) -> dict:
    return {
        "tenant_id": tenant_id, "business_name": "", "ifu": "", "rccm": "",
        "address": "", "bank_details": "",
        "id_photo_path": None, "id_card_path": None, "letterhead_path": None,
        "ai_prefilled_fields": [], "updated_at": None,
    }


async def _kyc_with_urls(tenant_id: str) -> dict:
    doc = await db.client_kyc.find_one({"tenant_id": tenant_id}, {"_id": 0}) or _empty_kyc(tenant_id)
    out = dict(doc)
    for key in ("id_photo_path", "id_card_path", "letterhead_path"):
        path = doc.get(key)
        out[key.replace("_path", "_url")] = await presigned_url(path, expires_in=600) if path else None
    return out


@router.get("/kyc")
async def get_my_kyc(user: dict = Depends(get_current_user)):
    _require_client(user)
    return await _kyc_with_urls(user["id"])


@router.put("/kyc")
async def update_my_kyc(payload: KycUpdate, user: dict = Depends(get_current_user)):
    _require_client(user)
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    changes["tenant_id"] = user["id"]
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.client_kyc.update_one({"tenant_id": user["id"]}, {"$set": changes}, upsert=True)
    return await _kyc_with_urls(user["id"])


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in (filename or "") else "").lower()


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower().strip()


# L'IA (albarka_ai.py) ne contraint pas le nommage de extracted_fields — son
# prompt système cite "IFU/RCCM, noms..." à titre d'exemple. On matche donc
# plusieurs formulations plausibles plutôt qu'une seule clé figée.
_AI_FIELD_ALIASES = {
    "business_name": ["raison_sociale", "raison sociale", "nom_entreprise", "entreprise", "business_name", "societe", "nom"],
    "ifu": ["ifu", "n_ifu", "numero_ifu", "identifiant fiscal", "identifiant_fiscal"],
    "rccm": ["rccm", "n_rccm", "registre du commerce", "registre_du_commerce"],
    "address": ["adresse", "address", "adresse geographique", "adresse_geographique"],
}


def _map_ai_fields(extracted: dict) -> dict:
    norm_extracted = {_norm(k): v for k, v in (extracted or {}).items() if isinstance(v, (str, int, float))}
    mapped = {}
    for field, aliases in _AI_FIELD_ALIASES.items():
        for alias in aliases:
            v = norm_extracted.get(_norm(alias))
            if v not in (None, ""):
                mapped[field] = str(v).strip()
                break
    return mapped


@router.post("/kyc/upload/{doc_type}")
async def upload_kyc_document(
    doc_type: str, file: UploadFile = File(...), user: dict = Depends(get_current_user),
):
    _require_client(user)
    if doc_type not in KYC_DOC_TYPES:
        raise HTTPException(status_code=400, detail=f"Type de document invalide (attendu : {sorted(KYC_DOC_TYPES)})")
    ext = _ext_of(file.filename or "")
    if ext not in ALLOWED_KYC_EXT:
        raise HTTPException(status_code=400, detail=f"Extension non autorisée : .{ext}")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(data) > MAX_KYC_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 8 Mo)")
    content_type = guess_content_type(ext, file.content_type or "application/octet-stream")

    stored = await save_and_log(
        db, data=data, kind=f"kyc_{doc_type}", tenant_id=user["id"],
        ext=ext, content_type=content_type, original_filename=file.filename, user_id=user["id"],
    )

    update: dict = {
        f"{doc_type}_path": stored["path"], "tenant_id": user["id"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    ai_prefilled: list[str] = []
    # id_card/letterhead portent en général la raison sociale/IFU/RCCM/adresse
    # (id_photo est un simple portrait, rien à en extraire).
    if doc_type in ("id_card", "letterhead"):
        try:
            result = await analyze_document(data, content_type, file.filename or "")
            mapped = _map_ai_fields(result.get("extracted_fields") or {})
            existing = await db.client_kyc.find_one({"tenant_id": user["id"]}, {"_id": 0}) or {}
            for field, value in mapped.items():
                if not (existing.get(field) or "").strip():
                    update[field] = value
                    ai_prefilled.append(field)
        except Exception:
            logger.exception("Analyse IA KYC échouée (doc_type=%s)", doc_type)

    if ai_prefilled:
        update["ai_prefilled_fields"] = ai_prefilled
    await db.client_kyc.update_one({"tenant_id": user["id"]}, {"$set": update}, upsert=True)
    url = await presigned_url(stored["path"], expires_in=600)
    return {"ok": True, "url": url, "size": stored["size"], "ai_prefilled_fields": ai_prefilled}
