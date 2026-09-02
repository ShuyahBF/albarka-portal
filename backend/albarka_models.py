"""Modèles de données spécifiques au portail ALBARKA (cabinet fiscal et comptable).

Remplace le modèle de rôle unique de Sawali (`role: str`) par une liste de
rôles cumulables, propre à un cabinet fiscal/comptable :

    superviseur   — accès total + tous les paramètres du site
    direction     — vue d'ensemble, validation des rapports de mission
    secretariat   — coordination, ordres de mission, rapports de mission, contacts
    fiscaliste    — tableaux de bord fiscaux, déclarations, contrats de bail
    comptable     — saisie comptable, pièces, rapports comptables
    aide_comptable— saisie comptable limitée, soumise à validation du comptable
    rh            — paie, indemnités/retenues, CNSS/IUTS, historique paie
    client        — espace client uniquement (documents, KYC, suivi, messagerie)

Un utilisateur interne peut cumuler plusieurs rôles (ex. comptable + rh).
Le rôle `client` est toujours exclusif aux autres (un compte client ne
cumule pas de rôle cabinet).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

ALBARKA_ROLES = [
    "superviseur",
    "direction",
    "secretariat",
    "fiscaliste",
    "comptable",
    "aide_comptable",
    "rh",
    "client",
]

STAFF_ROLES = [r for r in ALBARKA_ROLES if r != "client"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------
class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    full_name: str = Field(..., min_length=1, max_length=200)
    roles: List[str] = Field(..., min_length=1)
    company: Optional[str] = Field(None, max_length=200)

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
    is_active: bool = True
    created_at: str = Field(default_factory=_now_iso)
    last_login: Optional[str] = None


def is_client(user: dict) -> bool:
    return "client" in (user.get("roles") or [])


def is_superviseur(user: dict) -> bool:
    return "superviseur" in (user.get("roles") or [])


def has_any_role(user: dict, allowed: List[str]) -> bool:
    """True if the user has 'superviseur' (always allowed) or any role in `allowed`."""
    roles = set(user.get("roles") or [])
    if "superviseur" in roles:
        return True
    return bool(roles & set(allowed))


def tenant_id_of(user: dict) -> str:
    """The client's own id is its tenant scope (documents, KYC, missions...)."""
    return user["id"]


# ---------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    needs_otp: bool = True
    session_token: str
    message: str
    dev_otp: Optional[str] = None  # only populated when email sending fails (dev/demo)


class OtpVerifyRequest(BaseModel):
    session_token: str
    code: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: User


# ---------------------------------------------------------------------
# Documents (pièces client) + synthèse IA
# ---------------------------------------------------------------------
DOCUMENT_KINDS = ["piece_comptable", "declaration", "kyc", "autre"]
DOCUMENT_STATUSES = ["recu", "en_analyse", "analyse", "erreur_analyse"]


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


class DocumentSynthesis(BaseModel):
    model_config = ConfigDict(extra="ignore")
    id: str = Field(default_factory=_uuid)
    document_id: str
    tenant_id: str
    summary: str
    extracted_fields: dict = Field(default_factory=dict)
    document_type_guess: Optional[str] = None
    model: str
    created_at: str = Field(default_factory=_now_iso)
