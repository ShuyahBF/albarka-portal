"""Modèles ALBARKA — pilote cabinet fiscal et comptable."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

# Rôles cumulables (sauf `client` qui est exclusif).
ALBARKA_ROLES = [
    "superviseur",
    "direction",
    "administrateur",
    "secretariat",
    "fiscaliste",
    "comptable",
    "aide_comptable",
    "rh",
    "communication",
    "client",
]
STAFF_ROLES = [r for r in ALBARKA_ROLES if r != "client"]

MISSION_TYPES = [
    "tenue_comptable",
    "declaration_fiscale",
    "paie_rh",
    "audit",
    "conseil",
    "creation_entreprise",
    "autre",
]
MISSION_STATUSES = ["en_attente", "en_cours", "en_revue", "terminee", "archivee"]

DOCUMENT_KINDS = ["piece_comptable", "declaration", "kyc", "paie", "contrat", "autre"]
DOCUMENT_STATUSES = ["recu", "en_analyse", "analyse", "erreur_analyse"]

ECHEANCE_TYPES = [
    "tva",
    "is",
    "irpp",
    "cnss",
    "iuts",
    "bilan_annuel",
    "declaration_annuelle",
    "autre",
]
ECHEANCE_STATUSES = ["a_venir", "en_cours", "traitee", "en_retard"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------
# Users & auth
# ---------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=200)
    roles: List[str] = Field(..., min_length=1)
    company: Optional[str] = Field(None, max_length=200)
    phone: Optional[str] = Field(None, max_length=40)

    @field_validator("roles")
    @classmethod
    def _valid_roles(cls, v: List[str]) -> List[str]:
        unknown = set(v) - set(ALBARKA_ROLES)
        if unknown:
            raise ValueError(f"Rôle(s) invalide(s) : {sorted(unknown)}")
        if "client" in v and len(v) > 1:
            raise ValueError("Le rôle 'client' ne peut pas être cumulé avec un rôle cabinet")
        return v


class User(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    email: str
    full_name: str
    roles: List[str] = Field(default_factory=lambda: ["client"])
    company: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool = True
    created_at: str = Field(default_factory=_now_iso)
    last_login: Optional[str] = None


def is_client(user: dict) -> bool:
    return "client" in (user.get("roles") or [])


def is_superviseur(user: dict) -> bool:
    return "superviseur" in (user.get("roles") or [])


def is_staff(user: dict) -> bool:
    return bool(set(user.get("roles") or []) & set(STAFF_ROLES))


def has_any_role(user: dict, allowed: List[str]) -> bool:
    roles = set(user.get("roles") or [])
    if "superviseur" in roles:
        return True
    return bool(roles & set(allowed))


def tenant_id_of(user: dict) -> str:
    return user["id"]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    needs_otp: bool = True
    session_token: str
    message: str
    dev_otp: Optional[str] = None


class OtpVerifyRequest(BaseModel):
    session_token: str
    code: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


# ---------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------
class DocumentOut(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str
    tenant_id: str
    uploaded_by: str
    kind: str
    original_filename: str
    content_type: str
    size: int
    status: str = "recu"
    created_at: str = Field(default_factory=_now_iso)


# ---------------------------------------------------------------------
# Missions
# ---------------------------------------------------------------------
class MissionCreate(BaseModel):
    tenant_id: str
    title: str = Field(..., min_length=1, max_length=200)
    type: str = "tenue_comptable"
    description: Optional[str] = None
    assigned_to: Optional[List[str]] = None  # user ids (staff)
    due_date: Optional[str] = None  # ISO
    status: str = "en_attente"

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in MISSION_TYPES:
            raise ValueError(f"Type invalide : {v}")
        return v

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in MISSION_STATUSES:
            raise ValueError(f"Statut invalide : {v}")
        return v


class MissionUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    assigned_to: Optional[List[str]] = None
    due_date: Optional[str] = None
    status: Optional[str] = None


# ---------------------------------------------------------------------
# Échéances fiscales
# ---------------------------------------------------------------------
class EcheanceCreate(BaseModel):
    tenant_id: str
    title: str = Field(..., min_length=1, max_length=200)
    type: str = "tva"
    due_date: str  # ISO date
    amount: Optional[float] = None
    period: Optional[str] = None  # ex "2026-Q1"
    notes: Optional[str] = None
    status: str = "a_venir"

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in ECHEANCE_TYPES:
            raise ValueError(f"Type d'échéance invalide : {v}")
        return v

    @field_validator("status")
    @classmethod
    def _valid_status(cls, v: str) -> str:
        if v not in ECHEANCE_STATUSES:
            raise ValueError(f"Statut invalide : {v}")
        return v


class EcheanceUpdate(BaseModel):
    title: Optional[str] = None
    type: Optional[str] = None
    due_date: Optional[str] = None
    amount: Optional[float] = None
    period: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[str] = None
