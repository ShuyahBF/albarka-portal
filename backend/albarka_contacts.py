"""Carnet d'adresses / Contacts du cabinet.

Un `contact` appartient soit à un client (`scope="client"`, `tenant_id=<id
client>`) — ex : DG, DAF, RH, comptable interne — soit au cabinet lui-même
(`scope="cabinet"`, `tenant_id="cabinet"`) — banques, impôts, partenaires…

Règles :
- Un seul contact `is_primary=true` par (scope, tenant_id).
- Un client ne peut voir/gérer que les contacts de son propre `tenant_id`.
- Le staff peut tout voir/gérer.
- Les contacts inactifs ou non autorisés ne reçoivent pas les notifications.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field, field_validator

from albarka_auth import get_current_user, require_staff
from albarka_models import is_client, tenant_id_of
from db import db, serialize, serialize_many

router = APIRouter(prefix="/contacts", tags=["Contacts"])

CONTACT_SCOPES = ["client", "cabinet"]
CONTACT_FUNCTIONS = [
    "dg", "daf", "dfc", "comptable_interne", "assistant", "rh",
    "juridique", "banque", "impots", "cnss", "auditeur", "avocat",
    "commissaire_aux_comptes", "notaire", "autre",
]
CONTACT_CATEGORIES = [
    "principal", "facturation", "recouvrement", "reporting",
    "confidentiel", "operationnel",
]


class ContactCreate(BaseModel):
    scope: str = Field(..., description="'client' ou 'cabinet'")
    tenant_id: Optional[str] = Field(None, description="Requis si scope=client")
    full_name: str = Field(..., min_length=1, max_length=200)
    function: str = Field("autre")
    organization: Optional[str] = Field(None, max_length=200)
    email: Optional[EmailStr] = None
    phone: Optional[str] = Field(None, max_length=40)
    is_primary: bool = False
    can_receive_notifications: bool = True
    channels: List[str] = Field(default_factory=lambda: ["email"], description="email et/ou whatsapp")
    categories: List[str] = Field(default_factory=list)
    notes: Optional[str] = None

    @field_validator("scope")
    @classmethod
    def _scope(cls, v):
        if v not in CONTACT_SCOPES:
            raise ValueError(f"scope invalide : {v}")
        return v

    @field_validator("function")
    @classmethod
    def _function(cls, v):
        if v not in CONTACT_FUNCTIONS:
            raise ValueError(f"function invalide : {v}")
        return v

    @field_validator("channels")
    @classmethod
    def _channels(cls, v):
        allowed = {"email", "whatsapp"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"channels invalides : {sorted(bad)}")
        return v

    @field_validator("categories")
    @classmethod
    def _categories(cls, v):
        bad = set(v) - set(CONTACT_CATEGORIES)
        if bad:
            raise ValueError(f"categories invalides : {sorted(bad)}")
        return v


class ContactUpdate(BaseModel):
    full_name: Optional[str] = None
    function: Optional[str] = None
    organization: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    is_primary: Optional[bool] = None
    is_active: Optional[bool] = None
    can_receive_notifications: Optional[bool] = None
    channels: Optional[List[str]] = None
    categories: Optional[List[str]] = None
    notes: Optional[str] = None

    @field_validator("function")
    @classmethod
    def _function(cls, v):
        if v is not None and v not in CONTACT_FUNCTIONS:
            raise ValueError(f"function invalide : {v}")
        return v

    @field_validator("channels")
    @classmethod
    def _channels(cls, v):
        if v is None: return v
        allowed = {"email", "whatsapp"}
        bad = set(v) - allowed
        if bad:
            raise ValueError(f"channels invalides : {sorted(bad)}")
        return v

    @field_validator("categories")
    @classmethod
    def _categories(cls, v):
        if v is None: return v
        bad = set(v) - set(CONTACT_CATEGORIES)
        if bad:
            raise ValueError(f"categories invalides : {sorted(bad)}")
        return v


def _resolve_scope(user: dict, scope: Optional[str], tenant_id: Optional[str]):
    """Return (scope, tenant_id) respecting client isolation."""
    if is_client(user):
        # Clients only ever see their own contacts.
        return "client", tenant_id_of(user)
    scope = scope or "client"
    if scope == "cabinet":
        return "cabinet", "cabinet"
    if not tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id requis pour scope=client")
    return "client", tenant_id


async def _demote_other_primaries(scope: str, tenant_id: str, keep_id: Optional[str] = None):
    query = {"scope": scope, "tenant_id": tenant_id, "is_primary": True}
    if keep_id:
        query["id"] = {"$ne": keep_id}
    await db.contacts.update_many(query, {"$set": {"is_primary": False}})


@router.get("")
async def list_contacts(
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
    items = await db.contacts.find(query, {"_id": 0}).sort([("is_primary", -1), ("full_name", 1)]).to_list(1000)
    return serialize_many(items)


@router.post("")
async def create_contact(payload: ContactCreate, user: dict = Depends(require_staff())):
    scope, tenant_id = _resolve_scope(user, payload.scope, payload.tenant_id)
    if scope == "client":
        exists = await db.users.find_one({"id": tenant_id, "roles": "client"}, {"_id": 0, "id": 1})
        if not exists:
            raise HTTPException(status_code=404, detail="Client introuvable")
    if not payload.email and not payload.phone:
        raise HTTPException(status_code=400, detail="Au moins un email ou un téléphone est requis")

    contact = {
        "id": secrets.token_urlsafe(12),
        "scope": scope,
        "tenant_id": tenant_id,
        "full_name": payload.full_name.strip(),
        "function": payload.function,
        "organization": (payload.organization or "").strip() or None,
        "email": (payload.email or "").lower() or None,
        "phone": (payload.phone or "").strip() or None,
        "is_primary": bool(payload.is_primary),
        "is_active": True,
        "can_receive_notifications": bool(payload.can_receive_notifications),
        "channels": payload.channels or ["email"],
        "categories": payload.categories or [],
        "notes": payload.notes or None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if contact["is_primary"]:
        await _demote_other_primaries(scope, tenant_id)
    await db.contacts.insert_one(contact.copy())
    return serialize(contact)


async def _get_owned(contact_id: str, user: dict) -> dict:
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Contact introuvable")
    if is_client(user) and (c["scope"] != "client" or c["tenant_id"] != tenant_id_of(user)):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return c


@router.patch("/{contact_id}")
async def update_contact(contact_id: str, payload: ContactUpdate, user: dict = Depends(require_staff())):
    c = await _get_owned(contact_id, user)
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not changes:
        return c
    if changes.get("is_primary") is True:
        await _demote_other_primaries(c["scope"], c["tenant_id"], keep_id=contact_id)
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.contacts.update_one({"id": contact_id}, {"$set": changes})
    updated = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    return serialize(updated)


@router.delete("/{contact_id}")
async def delete_contact(contact_id: str, user: dict = Depends(require_staff())):
    c = await _get_owned(contact_id, user)
    await db.contacts.delete_one({"id": contact_id})
    return {"ok": True, "id": contact_id}


# ---- Helper for notifications routing -----------------------------------
async def notifiable_contacts_for(tenant_id: str, channel: str = "email") -> List[dict]:
    """Returns active contacts of a tenant who accept `channel` notifications."""
    if channel not in ("email", "whatsapp"):
        return []
    query = {
        "scope": "client",
        "tenant_id": tenant_id,
        "is_active": True,
        "$or": [
            {"can_receive_notifications": {"$exists": False}},
            {"can_receive_notifications": True},
        ],
        "channels": channel,
    }
    if channel == "email":
        query["email"] = {"$nin": [None, ""]}
    else:
        query["phone"] = {"$nin": [None, ""]}
    return await db.contacts.find(query, {"_id": 0}).sort([("is_primary", -1)]).to_list(200)
