"""Contrats clients — feature 14.

Un compte client ne peut se connecter que s'il a au moins un contrat en statut
`active` et dans la fenêtre [start_date, end_date]. Les collaborateurs
cabinet gèrent le CRUD via /api/client-contracts.
"""
from __future__ import annotations

import logging
import re
import secrets
import unicodedata
from urllib.parse import quote
from datetime import datetime, date, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

import albarka_storage
from albarka_auth import get_current_user, require_roles, require_staff
from albarka_models import CLIENT_MANAGE_ROLES
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.contracts")

router = APIRouter(prefix="/client-contracts", tags=["Contrats clients"])

CONTRACT_STATUSES = ["en_cours", "suspendu", "termine", "annule"]

# Lot 66 — document du contrat (Word, PDF ou image) téléversé et rattaché au contrat.
# Réservé aux rôles qui gèrent les contrats (Superviseur, Direction, DG, Administrateur, Secrétariat).
DOC_EXTENSIONS = {"pdf", "doc", "docx", "jpg", "jpeg", "png", "webp"}
DOC_MAX_BYTES = 20 * 1024 * 1024          # 20 Mo, comme les autres pièces du portail
# Début de fichier attendu pour chaque format : refuse un fichier renommé (un .exe nommé « contrat.pdf »…)
_SIGNATURES = {
    "pdf": (b"%PDF",), "doc": (b"\xd0\xcf\x11\xe0",), "docx": (b"PK\x03\x04",),
    "jpg": (b"\xff\xd8\xff",), "jpeg": (b"\xff\xd8\xff",), "png": (b"\x89PNG",), "webp": (b"RIFF",),
}
_gestion_contrats = require_roles(CLIENT_MANAGE_ROLES)


def _public(doc: dict) -> dict:
    """Contrat prêt à être renvoyé à l'écran : le chemin interne de stockage n'est jamais exposé."""
    out = dict(doc)
    if isinstance(out.get("document"), dict):
        out["document"] = {k: v for k, v in out["document"].items() if k not in ("storage_path", "storage_id")}
    return out
# Compatibilité rétro : certains contrats seedés en anglais restent tolérés
# comme équivalents (mapping lecture uniquement) — la migration convertit tout
# en français, mais garder un fallback évite un 500 sur un client legacy.
_LEGACY_STATUS_MAP = {
    "active": "en_cours", "suspended": "suspendu",
    "terminated": "termine", "expired": "annule",
}


def _normalize_status(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    return _LEGACY_STATUS_MAP.get(v, v)


def _parse_iso_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except ValueError:
        return None


async def has_active_contract(tenant_id: str) -> bool:
    """Return True when the client has at least one active, in-window contract."""
    today = date.today().isoformat()
    contract = await db.client_contracts.find_one({
        "tenant_id": tenant_id,
        "status": {"$in": ["en_cours", "active"]},  # rétro-compat legacy
        "start_date": {"$lte": today},
        "$or": [{"end_date": None}, {"end_date": {"$gte": today}}],
    })
    return contract is not None


class ContractCreate(BaseModel):
    tenant_id: str
    numero_contrat: Optional[str] = None
    title: str = Field(..., min_length=2, max_length=200)
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "XOF"
    status: str = "en_cours"
    date_dernier_paiement: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("start_date", "end_date", "date_dernier_paiement")
    @classmethod
    def _valid_date(cls, v):
        if v is None:
            return v
        if _parse_iso_date(v) is None:
            raise ValueError("Date invalide (format attendu YYYY-MM-DD)")
        return v[:10]

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        v = _normalize_status(v)
        if v not in CONTRACT_STATUSES:
            raise ValueError(f"Statut invalide : {v}")
        return v


class ContractUpdate(BaseModel):
    numero_contrat: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    date_dernier_paiement: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        if v is None:
            return v
        v = _normalize_status(v)
        if v not in CONTRACT_STATUSES:
            raise ValueError(f"Statut invalide : {v}")
        return v


@router.get("")
async def list_contracts(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    q = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    if status:
        q["status"] = status
    items = await db.client_contracts.find(q, {"_id": 0}).sort("start_date", -1).to_list(500)
    return serialize_many([_public(c) for c in items])


@router.post("")
async def create_contract(payload: ContractCreate, user: dict = Depends(require_staff())):
    # Ensure the tenant is an existing client
    client = await db.users.find_one({"id": payload.tenant_id, "roles": "client"}, {"_id": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    # Auto-generate numero_contrat if not provided : CTR-YYYY-NNNN
    numero = payload.numero_contrat
    if not numero:
        year = datetime.now(timezone.utc).strftime("%Y")
        seq_doc = await db.report_series.find_one_and_update(
            {"key": f"contract:{year}"},
            {"$inc": {"seq": 1}, "$setOnInsert": {"kind": "contract", "year": year}},
            upsert=True, return_document=True,
        )
        numero = f"CTR-{year}-{int(seq_doc.get('seq') or 1):04d}"
    doc = {
        "id": secrets.token_urlsafe(12),
        "tenant_id": payload.tenant_id,
        "numero_contrat": numero,
        "title": payload.title,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "amount": payload.amount,
        "currency": payload.currency,
        "status": payload.status,
        "date_dernier_paiement": payload.date_dernier_paiement,
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.client_contracts.insert_one(doc.copy())
    return serialize(doc)


@router.get("/{contract_id}")
async def get_contract(contract_id: str, user: dict = Depends(require_staff())):
    doc = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return serialize(_public(doc))


@router.patch("/{contract_id}")
async def update_contract(
    contract_id: str, payload: ContractUpdate, user: dict = Depends(require_staff()),
):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    update["updated_by"] = user["id"]
    res = await db.client_contracts.update_one({"id": contract_id}, {"$set": update})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    doc = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0})
    return serialize(_public(doc))


@router.delete("/{contract_id}")
async def delete_contract(contract_id: str, user: dict = Depends(require_staff())):
    contrat = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0, "document": 1})
    res = await db.client_contracts.delete_one({"id": contract_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    await _effacer_fichier((contrat or {}).get("document"))      # lot 66 : le document attaché disparaît avec le contrat
    return {"ok": True, "id": contract_id}


# ---------------------------------------------------------------- lot 66 : document du contrat
async def _effacer_fichier(document: Optional[dict]) -> None:
    """Supprime le fichier stocké d'un document de contrat (sans jamais faire échouer l'opération appelante)."""
    if not document:
        return
    try:
        if document.get("storage_path"):
            await albarka_storage.delete_object(document["storage_path"])
        if document.get("storage_id"):
            await db.stored_objects.update_one({"id": document["storage_id"]}, {"$set": {"is_deleted": True}})
    except Exception:  # noqa: BLE001
        logger.warning("[contrats] fichier du contrat non supprimé du stockage", exc_info=True)


@router.post("/{contract_id}/document")
async def attach_document(contract_id: str, file: UploadFile = File(...), user: dict = Depends(_gestion_contrats)):
    """Attache (ou REMPLACE) le document du contrat : Word, PDF ou image, 20 Mo au plus."""
    contrat = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0})
    if not contrat:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    name = file.filename or "contrat"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in DOC_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Format non accepté (.{ext or '?'}) : Word (.doc, .docx), PDF ou image (.jpg, .png, .webp)")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(data) > DOC_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Le fichier dépasse 20 Mo")
    if not any(data.startswith(sig) for sig in _SIGNATURES[ext]):
        raise HTTPException(status_code=400, detail=f"Le contenu du fichier ne correspond pas au format .{ext}")
    stored = await albarka_storage.save_and_log(
        db, data=data, kind="contrat", tenant_id=contrat["tenant_id"], ext=ext,
        content_type=albarka_storage.guess_content_type(ext, file.content_type or "application/octet-stream"),
        original_filename=name, user_id=user["id"])
    nouveau = {"storage_id": stored["id"], "storage_path": stored["path"], "filename": re.sub(r"[\r\n\"]", "_", name)[:200],
               "content_type": stored["content_type"], "size": stored["size"],
               "uploaded_at": datetime.now(timezone.utc).isoformat(), "uploaded_by": user["id"],
               "uploaded_by_name": user.get("full_name") or user.get("email")}
    await db.client_contracts.update_one({"id": contract_id}, {"$set": {"document": nouveau}})
    await _effacer_fichier(contrat.get("document"))               # remplacement : l'ancien fichier est retiré
    return {"ok": True, "document": _public({"document": nouveau})["document"]}


async def _reponse_document(d: Optional[dict], download: bool) -> Response:
    """Fichier du contrat prêt à être renvoyé (utilisé par le cabinet ET par le client propriétaire du contrat)."""
    if not d:
        raise HTTPException(status_code=404, detail="Aucun document attaché à ce contrat")
    data, ct = await albarka_storage.get_object(d["storage_path"])
    nom = d.get("filename") or "contrat"
    # En-tête HTTP : nom ASCII de repli + nom complet (accents) encodé selon la RFC 5987
    ascii_nom = re.sub(r"[^A-Za-z0-9.\- ]", "_", unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode() or "contrat")
    return Response(content=data, media_type=d.get("content_type") or ct or "application/octet-stream",
                    headers={"Content-Disposition":
                             f'{"attachment" if download else "inline"}; filename="{ascii_nom}"; filename*=UTF-8\'\'{quote(nom)}'})


@router.get("/{contract_id}/document")
async def get_document(contract_id: str, download: bool = False, user: dict = Depends(_gestion_contrats)):
    """Renvoie le document attaché (affiché dans le navigateur, ou téléchargé avec ?download=true)."""
    contrat = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0, "document": 1})
    return await _reponse_document((contrat or {}).get("document"), download)


# ---------------------------------------------------------------- lot 67 : le client voit ses contrats
me_router = APIRouter(prefix="/me/contracts", tags=["Contrats — espace client"])


def _exiger_client(user: dict) -> None:
    if "client" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé aux clients")


@me_router.get("")
async def my_contracts(user: dict = Depends(get_current_user)):
    """Contrats DU client connecté (jamais ceux d'un autre), avec le document attaché s'il y en a un.
    Aucune information interne (notes, auteur, chemin de stockage)."""
    _exiger_client(user)
    items = await db.client_contracts.find({"tenant_id": user["id"]}, {"_id": 0}).sort("start_date", -1).to_list(200)
    champs = ("id", "numero_contrat", "title", "start_date", "end_date", "amount", "currency", "status", "date_dernier_paiement")
    out = []
    for c in items:
        pub = {k: c.get(k) for k in champs}
        d = c.get("document")
        pub["document"] = ({"filename": d.get("filename"), "size": d.get("size"), "content_type": d.get("content_type"),
                            "uploaded_at": d.get("uploaded_at")} if d else None)
        out.append(pub)
    return {"items": serialize_many(out)}


@me_router.get("/{contract_id}/document")
async def my_contract_document(contract_id: str, download: bool = False, user: dict = Depends(get_current_user)):
    """Ouvre / télécharge le document de SON contrat ; un contrat d'un autre client répond « introuvable »."""
    _exiger_client(user)
    contrat = await db.client_contracts.find_one({"id": contract_id, "tenant_id": user["id"]}, {"_id": 0, "document": 1})
    return await _reponse_document((contrat or {}).get("document"), download)


@router.delete("/{contract_id}/document")
async def detach_document(contract_id: str, user: dict = Depends(_gestion_contrats)):
    """Retire le document attaché (le contrat reste)."""
    contrat = await db.client_contracts.find_one({"id": contract_id}, {"_id": 0, "document": 1})
    if not contrat:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    if not contrat.get("document"):
        raise HTTPException(status_code=404, detail="Aucun document attaché à ce contrat")
    await db.client_contracts.update_one({"id": contract_id}, {"$unset": {"document": ""}})
    await _effacer_fichier(contrat["document"])
    return {"ok": True}


async def migrate_contract_statuses_and_numbers() -> dict:
    """Migre les contrats existants vers les nouveaux statuts FR + génère un
    numéro pour les contrats sans `numero_contrat`. Idempotent.
    """
    stats = {"status_migrated": 0, "number_generated": 0}
    # 1) Statuts EN → FR
    for old, new in _LEGACY_STATUS_MAP.items():
        res = await db.client_contracts.update_many(
            {"status": old}, {"$set": {"status": new}},
        )
        stats["status_migrated"] += res.modified_count
    # 2) Numéros manquants
    year = datetime.now(timezone.utc).strftime("%Y")
    async for c in db.client_contracts.find(
        {"$or": [{"numero_contrat": {"$exists": False}}, {"numero_contrat": None}]},
        {"_id": 0, "id": 1},
    ):
        seq_doc = await db.report_series.find_one_and_update(
            {"key": f"contract:{year}"},
            {"$inc": {"seq": 1}, "$setOnInsert": {"kind": "contract", "year": year}},
            upsert=True, return_document=True,
        )
        numero = f"CTR-{year}-{int(seq_doc.get('seq') or 1):04d}"
        await db.client_contracts.update_one(
            {"id": c["id"]}, {"$set": {"numero_contrat": numero}},
        )
        stats["number_generated"] += 1
    return stats


@router.post("/_migrate")
async def run_migration(user: dict = Depends(require_staff())):
    return await migrate_contract_statuses_and_numbers()
