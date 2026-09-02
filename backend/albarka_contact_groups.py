"""Groupes de contacts — envoi groupé de rapports/notifications.

Un groupe appartient soit à un client (`scope="client"`, tenant_id=<id client>)
soit au cabinet (`scope="cabinet"`, tenant_id="cabinet"). Il rassemble un ensemble
de contact_ids et peut être utilisé comme destinataire d'un rapport.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from albarka_auth import get_current_user, require_staff
from albarka_contacts import CONTACT_SCOPES
from albarka_models import is_client, tenant_id_of
from db import db, serialize, serialize_many

router = APIRouter(prefix="/contact-groups", tags=["Groupes de contacts"])


class GroupCreate(BaseModel):
    scope: str = Field(..., description="'client' ou 'cabinet'")
    tenant_id: Optional[str] = None
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    contact_ids: List[str] = Field(default_factory=list)

    @field_validator("scope")
    @classmethod
    def _scope(cls, v):
        if v not in CONTACT_SCOPES:
            raise ValueError(f"scope invalide : {v}")
        return v


class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=120)
    description: Optional[str] = None
    contact_ids: Optional[List[str]] = None


def _resolve_scope(user: dict, scope: Optional[str], tenant_id: Optional[str]):
    if is_client(user):
        return "client", tenant_id_of(user)
    scope = scope or "client"
    if scope == "cabinet":
        return "cabinet", "cabinet"
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id requis pour scope=client")
    return "client", tenant_id


async def _validate_contact_ids(scope: str, tenant_id: str, contact_ids: List[str]) -> List[str]:
    if not contact_ids:
        return []
    found = await db.contacts.find(
        {"id": {"$in": contact_ids}, "scope": scope, "tenant_id": tenant_id},
        {"_id": 0, "id": 1},
    ).to_list(500)
    ok_ids = {c["id"] for c in found}
    unknown = [cid for cid in contact_ids if cid not in ok_ids]
    if unknown:
        raise HTTPException(status_code=400, detail=f"Contacts inconnus / hors périmètre : {unknown}")
    return list(ok_ids)


@router.get("")
async def list_groups(
    scope: Optional[str] = Query(None),
    tenant_id: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
):
    if is_client(user):
        query = {"scope": "client", "tenant_id": tenant_id_of(user)}
    else:
        query = {}
        if scope: query["scope"] = scope
        if tenant_id: query["tenant_id"] = tenant_id
    items = await db.contact_groups.find(query, {"_id": 0}).sort("name", 1).to_list(500)
    return serialize_many(items)


@router.post("")
async def create_group(payload: GroupCreate, user: dict = Depends(require_staff())):
    scope, tenant_id = _resolve_scope(user, payload.scope, payload.tenant_id)
    ids = await _validate_contact_ids(scope, tenant_id, payload.contact_ids)
    doc = {
        "id": secrets.token_urlsafe(12),
        "scope": scope,
        "tenant_id": tenant_id,
        "name": payload.name.strip(),
        "description": (payload.description or "").strip() or None,
        "contact_ids": ids,
        "created_by": user["id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.contact_groups.insert_one(doc.copy())
    return serialize(doc)


async def _get_owned(group_id: str, user: dict) -> dict:
    g = await db.contact_groups.find_one({"id": group_id}, {"_id": 0})
    if not g:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    if is_client(user) and (g["scope"] != "client" or g["tenant_id"] != tenant_id_of(user)):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return g


@router.patch("/{group_id}")
async def update_group(group_id: str, payload: GroupUpdate, user: dict = Depends(require_staff())):
    g = await _get_owned(group_id, user)
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not changes:
        return g
    if "contact_ids" in changes:
        changes["contact_ids"] = await _validate_contact_ids(g["scope"], g["tenant_id"], changes["contact_ids"])
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.contact_groups.update_one({"id": group_id}, {"$set": changes})
    updated = await db.contact_groups.find_one({"id": group_id}, {"_id": 0})
    return serialize(updated)


@router.delete("/{group_id}")
async def delete_group(group_id: str, user: dict = Depends(require_staff())):
    g = await _get_owned(group_id, user)
    await db.contact_groups.delete_one({"id": group_id})
    return {"ok": True, "id": group_id}


async def emails_of_group(group_id: str) -> List[str]:
    g = await db.contact_groups.find_one({"id": group_id}, {"_id": 0})
    if not g:
        return []
    contacts = await db.contacts.find(
        {"id": {"$in": g.get("contact_ids", [])}, "is_active": True},
        {"_id": 0, "email": 1, "can_receive_notifications": 1, "channels": 1},
    ).to_list(500)
    return sorted({
        c["email"] for c in contacts
        if c.get("email") and c.get("can_receive_notifications", True)
        and "email" in (c.get("channels") or ["email"])
    })
