"""Échéances fiscales et sociales."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from albarka_auth import get_current_user, require_staff
from albarka_models import EcheanceCreate, EcheanceUpdate, is_client, tenant_id_of
from db import db, serialize, serialize_many

router = APIRouter(prefix="/echeances", tags=["Échéances"])


@router.get("")
async def list_echeances(tenant_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: dict = {}
    if is_client(user):
        query["tenant_id"] = tenant_id_of(user)
    elif tenant_id:
        query["tenant_id"] = tenant_id
    docs = await db.echeances.find(query, {"_id": 0}).sort("due_date", 1).to_list(500)
    return serialize_many(docs)


@router.post("")
async def create_echeance(payload: EcheanceCreate, user: dict = Depends(require_staff())):
    doc = {
        "id": secrets.token_urlsafe(12),
        "tenant_id": payload.tenant_id,
        "title": payload.title,
        "type": payload.type,
        "due_date": payload.due_date,
        "amount": payload.amount,
        "period": payload.period,
        "notes": payload.notes,
        "status": payload.status,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.echeances.insert_one(doc.copy())
    return serialize(doc)


@router.patch("/{echeance_id}")
async def update_echeance(echeance_id: str, payload: EcheanceUpdate, user: dict = Depends(require_staff())):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.echeances.update_one({"id": echeance_id}, {"$set": update})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Échéance introuvable")
    doc = await db.echeances.find_one({"id": echeance_id}, {"_id": 0})
    return serialize(doc)


@router.delete("/{echeance_id}")
async def delete_echeance(echeance_id: str, user: dict = Depends(require_staff())):
    res = await db.echeances.delete_one({"id": echeance_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Échéance introuvable")
    return {"ok": True, "id": echeance_id}
