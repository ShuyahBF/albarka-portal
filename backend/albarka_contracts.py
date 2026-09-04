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

CONTRACT_STATUSES = ["active", "suspended", "terminated", "expired"]


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
        "status": "active",
        "start_date": {"$lte": today},
        "$or": [{"end_date": None}, {"end_date": {"$gte": today}}],
    })
    return contract is not None


class ContractCreate(BaseModel):
    tenant_id: str
    title: str = Field(..., min_length=2, max_length=200)
    start_date: str = Field(..., description="ISO date YYYY-MM-DD")
    end_date: Optional[str] = None
    amount: Optional[float] = None
    currency: str = "XOF"
    status: str = "active"
    notes: Optional[str] = None

    @field_validator("start_date", "end_date")
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
        if v not in CONTRACT_STATUSES:
            raise ValueError(f"Statut invalide : {v}")
        return v


class ContractUpdate(BaseModel):
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    amount: Optional[float] = None
    currency: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v):
        if v is None:
            return v
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
    doc = {
        "id": secrets.token_urlsafe(12),
        "tenant_id": payload.tenant_id,
        "title": payload.title,
        "start_date": payload.start_date,
        "end_date": payload.end_date,
        "amount": payload.amount,
        "currency": payload.currency,
        "status": payload.status,
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
