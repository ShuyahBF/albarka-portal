"""Missions / interventions."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from albarka_auth import get_current_user, require_staff
from albarka_models import MissionCreate, MissionUpdate, is_client, tenant_id_of
from db import db, serialize, serialize_many

router = APIRouter(prefix="/missions", tags=["Missions"])


@router.get("")
async def list_missions(tenant_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: dict = {}
    if is_client(user):
        query["tenant_id"] = tenant_id_of(user)
    elif tenant_id:
        query["tenant_id"] = tenant_id
    docs = await db.missions.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(docs)


@router.post("")
async def create_mission(payload: MissionCreate, user: dict = Depends(require_staff())):
    doc = {
        "id": secrets.token_urlsafe(12),
        "tenant_id": payload.tenant_id,
        "title": payload.title,
        "type": payload.type,
        "description": payload.description,
        "assigned_to": payload.assigned_to or [],
        "due_date": payload.due_date,
        "status": payload.status,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.missions.insert_one(doc.copy())
    return serialize(doc)


@router.get("/{mission_id}")
async def get_mission(mission_id: str, user: dict = Depends(get_current_user)):
    doc = await db.missions.find_one({"id": mission_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    if is_client(user) and doc["tenant_id"] != tenant_id_of(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return serialize(doc)


@router.patch("/{mission_id}")
async def update_mission(mission_id: str, payload: MissionUpdate, user: dict = Depends(require_staff())):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.missions.update_one({"id": mission_id}, {"$set": update})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    doc = await db.missions.find_one({"id": mission_id}, {"_id": 0})
    return serialize(doc)


@router.delete("/{mission_id}")
async def delete_mission(mission_id: str, user: dict = Depends(require_staff())):
    res = await db.missions.delete_one({"id": mission_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Mission introuvable")
    return {"ok": True, "id": mission_id}
