"""Gestion des clients (staff only)."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from albarka_auth import get_current_user, hash_password, require_staff
from albarka_models import ALBARKA_ROLES, User
from db import db, serialize, serialize_many

router = APIRouter(prefix="/clients", tags=["Clients"])


class ClientCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=200)
    company: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=8)


class StaffCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=1, max_length=200)
    roles: List[str] = Field(..., min_length=1)
    company: Optional[str] = None
    phone: Optional[str] = None
    password: str = Field(..., min_length=8)

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
    is_active: Optional[bool] = None


def _public(user: dict) -> dict:
    user.pop("password_hash", None)
    return serialize(user)


@router.get("")
async def list_clients(user: dict = Depends(require_staff())):
    docs = await db.users.find(
        {"roles": "client"}, {"_id": 0, "password_hash": 0}
    ).sort("created_at", -1).to_list(1000)
    return serialize_many(docs)


@router.get("/staff")
async def list_staff(user: dict = Depends(require_staff())):
    docs = await db.users.find(
        {"roles": {"$nin": ["client"]}}, {"_id": 0, "password_hash": 0}
    ).sort("created_at", -1).to_list(1000)
    return serialize_many(docs)


@router.post("")
async def create_client(payload: ClientCreate, user: dict = Depends(require_staff())):
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
        "is_active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
    }
    await db.users.insert_one(user_doc.copy())
    return _public(user_doc)


@router.post("/staff")
async def create_staff(payload: StaffCreate, user: dict = Depends(require_staff())):
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
        "created_at": datetime.now(timezone.utc).isoformat(),
        "last_login": None,
    }
    await db.users.insert_one(user_doc.copy())
    return _public(user_doc)


@router.get("/{user_id}")
async def get_client(user_id: str, user: dict = Depends(require_staff())):
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return serialize(doc)


@router.patch("/{user_id}")
async def update_client(user_id: str, payload: UserUpdate, user: dict = Depends(require_staff())):
    update = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if not update:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    res = await db.users.update_one({"id": user_id}, {"$set": update})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    doc = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    return serialize(doc)


@router.delete("/{user_id}")
async def delete_client(user_id: str, user: dict = Depends(require_staff())):
    if user_id == user["id"]:
        raise HTTPException(status_code=400, detail="Impossible de supprimer votre propre compte")
    res = await db.users.delete_one({"id": user_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return {"ok": True, "id": user_id}
