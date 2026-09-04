"""Paramètres administrateur (settings globaux) — WABA config, notifications, etc.

Document unique en base : `settings` avec `_id="global"` (compatible avec le
pattern du repo d'origine). Seul un utilisateur ayant l'un des rôles
`superviseur`, `direction` ou `administrateur` peut lire/écrire les paramètres.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import re
from albarka_auth import get_current_user, require_roles
from db import db

logger = logging.getLogger("albarka.admin_settings")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/admin", tags=["Admin"])

_ADMIN_ROLES = ["superviseur", "direction", "administrateur"]

# Champs sensibles : masqués sur lecture (******** = présent).
SENSITIVE_FIELDS = {"wa_access_token"}

# Valeurs par défaut.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "cabinet_name": "Cabinet ALBARKA",
    "cabinet_email": "contact@albarka-bf.com",
    "cabinet_phone": "",
    "cabinet_address": "Ouagadougou, Burkina Faso",
    # Email — expéditeur & domaine
    "email_from_address": "",   # ex noreply@albarka-bf.com — nécessite domaine vérifié Resend
    "email_reply_to": "",
    # WhatsApp Business Cloud API (Meta Graph)
    "wa_enabled": False,
    "wa_access_token": "",
    "wa_phone_number_id": "",
    "wa_business_account_id": "",
    "wa_graph_version": "v22.0",
    # Notifications
    "notif_reminder_days": [7, 1],
    "notif_overdue": True,
    "notif_upload_enabled": True,
    "notif_upload_wa": True,   # notifier aussi les collaborateurs par WA
    # Report numbering
    "report_prefix": "RAP",
}


async def _load_settings() -> Dict[str, Any]:
    doc = await db.settings.find_one({"_id": "global"})
    if not doc:
        doc = {"_id": "global", **DEFAULT_SETTINGS,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "updated_at": datetime.now(timezone.utc).isoformat()}
        await db.settings.insert_one(doc)
    # Ensure every default key is present (forward-compat).
    changed = False
    for k, v in DEFAULT_SETTINGS.items():
        if k not in doc:
            doc[k] = v
            changed = True
    if changed:
        await db.settings.update_one(
            {"_id": "global"}, {"$set": {k: doc[k] for k in DEFAULT_SETTINGS}},
        )
    doc.pop("_id", None)
    return doc


async def get_settings_doc() -> Dict[str, Any]:
    """Used internally by other modules (no masking)."""
    return await _load_settings()


def _mask(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    for k in SENSITIVE_FIELDS:
        if out.get(k):
            out[k] = "********"
    return out


class SettingsUpdate(BaseModel):
    # Cabinet
    cabinet_name: Optional[str] = None
    cabinet_email: Optional[str] = None
    cabinet_phone: Optional[str] = None
    cabinet_address: Optional[str] = None
    # Email
    email_from_address: Optional[str] = None
    email_reply_to: Optional[str] = None
    # WA
    wa_enabled: Optional[bool] = None
    wa_access_token: Optional[str] = None
    wa_phone_number_id: Optional[str] = None
    wa_business_account_id: Optional[str] = None
    wa_graph_version: Optional[str] = None
    # Notifs
    notif_reminder_days: Optional[list[int]] = None
    notif_overdue: Optional[bool] = None
    notif_upload_enabled: Optional[bool] = None
    notif_upload_wa: Optional[bool] = None
    # Reports
    report_prefix: Optional[str] = Field(None, max_length=10)


@router.get("/settings")
async def get_settings(user: dict = Depends(require_roles(_ADMIN_ROLES))):
    return _mask(await _load_settings())


@router.put("/settings")
async def update_settings(payload: SettingsUpdate, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    # Never persist the masked sentinel back.
    for k in SENSITIVE_FIELDS:
        if changes.get(k) == "********":
            changes.pop(k, None)
    # Validate email address fields; empty string clears the setting.
    for k in ("email_from_address", "email_reply_to"):
        if k in changes:
            val = (changes[k] or "").strip()
            if val and not _EMAIL_RE.match(val):
                raise HTTPException(status_code=400, detail=f"{k} : adresse email invalide")
            changes[k] = val
    if not changes:
        return _mask(await _load_settings())
    await _load_settings()
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    changes["updated_by"] = user["id"]
    await db.settings.update_one({"_id": "global"}, {"$set": changes})
    return _mask(await _load_settings())


@router.post("/settings/wa/test")
async def wa_test_send(
    payload: Dict[str, str],  # {"to": "+226..."} or {"to": "+226...", "message": "..."}
    user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    """Envoie un message WhatsApp de test aux paramètres courants."""
    from albarka_notifications import send_whatsapp
    to = (payload.get("to") or "").strip()
    msg = payload.get("message") or "Test — Cabinet ALBARKA. Configuration WhatsApp opérationnelle."
    if not to.startswith("+"):
        raise HTTPException(status_code=400, detail="Numéro attendu au format international (+226…)")
    settings = await _load_settings()
    if not settings.get("wa_enabled"):
        return {"ok": False, "message_id": None, "diagnostic": "WhatsApp désactivé dans les paramètres (wa_enabled=false)"}
    if not settings.get("wa_access_token") or not settings.get("wa_phone_number_id"):
        return {"ok": False, "message_id": None, "diagnostic": "wa_access_token ou wa_phone_number_id manquant"}
    result = await send_whatsapp(to_phone=to, message=msg)
    if result:
        return {"ok": True, "message_id": result, "diagnostic": "Message envoyé avec succès"}
    return {"ok": False, "message_id": None, "diagnostic": "Meta a rejeté l'envoi — consulter les logs serveur"}
