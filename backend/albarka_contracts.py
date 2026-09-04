"""Contrats clients — feature 14.

Un compte client ne peut se connecter que s'il a au moins un contrat en statut
`active` et dans la fenêtre [start_date, end_date]. Les collaborateurs
cabinet gèrent le CRUD via /api/client-contracts.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, date, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from albarka_auth import require_staff
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.contracts")

router = APIRouter(prefix="/client-contracts", tags=["Contrats clients"])

CONTRACT_STATUSES = ["en_cours", "suspendu", "termine", "annule"]
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
    return serialize_many(items)


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
    return serialize(doc)


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
    return serialize(doc)


@router.delete("/{contract_id}")
async def delete_contract(contract_id: str, user: dict = Depends(require_staff())):
    res = await db.client_contracts.delete_one({"id": contract_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Contrat introuvable")
    return {"ok": True, "id": contract_id}


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
