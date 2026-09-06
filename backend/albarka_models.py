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
    "dg",
    "administrateur",
    "secretariat",
    "fiscaliste",
    "comptable",
    "aide_comptable",
    "rh",
    "communication",
    # Rôle transversal : accordé en plus du métier principal, donne le droit
    # de télécharger les pièces client quel que soit le profil (comptable,
    # communication, etc.) qui le porte.
    "telechargement",
    # Accès exclusif au module Paiements (liens de paiement mobile money) —
    # voir PAYMENTS_ROLES et albarka_payments.py.
    "caissier",
    "client",
]
STAFF_ROLES = [r for r in ALBARKA_ROLES if r != "client"]

# Groupes de rôles privilégiés utilisés par plusieurs modules — centralisés
# ici pour éviter que chacun maintienne sa propre liste (source de dérive).
# Chaque groupe correspond à une règle métier précise, volontairement pas
# identique aux autres (ex. la Caisse exclut "direction" et "secretariat").
DOCS_PRIVILEGED_ROLES = ["administrateur", "superviseur", "dg", "direction", "secretariat"]
DOCS_DELETE_ROLES = ["administrateur", "superviseur", "dg", "direction"]  # jamais secretariat
VERIFY_PHONE_ROLES = ["administrateur", "superviseur", "dg", "direction"]
CAISSE_DATE_RANGE_ROLES = ["administrateur", "dg", "superviseur"]
CLIENT_MANAGE_ROLES = DOCS_PRIVILEGED_ROLES
CHAT_THREAD_CREATE_ROLES = DOCS_PRIVILEGED_ROLES
# Module Paiements (liens PawaPay) — réservé au rôle "caissier" uniquement,
# à la demande explicite du client ("accessible seulement au nouveau rôle
# Collaborateur Caissier"). require_roles() conserve malgré tout le
# passe-droit "superviseur" déjà appliqué partout ailleurs dans l'app —
# cohérence avec le reste du portail plutôt qu'un cas particulier isolé.
PAYMENTS_ROLES = ["caissier"]

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
    # Attesté par un collaborateur habilité (voir albarka_clients.py).
    phone_verified: bool = False
    # Numéro WhatsApp distinct du téléphone (facultatif — laisser vide si
    # identique). Sa propre attestation "vérifié" conditionne l'accès à
    # l'action "Envoyer par WhatsApp" pour un collaborateur non-privilégié
    # du rôle "communication" — voir is_whatsapp_verified() ci-dessous pour
    # la logique de repli sur phone_verified quand ce champ est vide.
    whatsapp_number: Optional[str] = None
    whatsapp_verified: bool = False
    is_active: bool = True
    created_at: str = Field(default_factory=_now_iso)
    last_login: Optional[str] = None


def is_client(user: dict) -> bool:
    return "client" in (user.get("roles") or [])


def is_whatsapp_verified(user_doc: dict) -> bool:
    """Vrai si le numéro utilisé pour un envoi WhatsApp est attesté vérifié.

    Si un numéro WhatsApp distinct a été renseigné, sa propre vérification
    fait foi. Sinon (fiche créée avant la scission téléphone/WhatsApp, ou
    client n'ayant qu'un seul numéro pour les deux usages), on retombe sur
    `phone_verified`.
    """
    if user_doc.get("whatsapp_number"):
        return bool(user_doc.get("whatsapp_verified"))
    return bool(user_doc.get("phone_verified"))


def whatsapp_number_of(user_doc: dict) -> Optional[str]:
    """Numéro à utiliser pour un envoi WhatsApp : le numéro dédié s'il existe,
    sinon le téléphone (numéro unique historique servant aux deux usages)."""
    return user_doc.get("whatsapp_number") or user_doc.get("phone")


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
    # reCAPTCHA v2 (widget "je ne suis pas un robot") — optionnel : ignoré si
    # le captcha est désactivé côté paramètres admin, voir albarka_recaptcha.py.
    captcha_token: Optional[str] = None


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
