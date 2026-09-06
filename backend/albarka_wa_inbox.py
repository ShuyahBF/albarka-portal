"""Partie 2.D — Webhook WhatsApp entrant + Centre de conversations.

Reçoit les messages entrants depuis Meta Cloud API, les persiste dans
`wa_messages` (dédupliqués par `wa_message_id`), les rattache à un
contact ou à un client cabinet, transcrit automatiquement les notes vocales
via l'endpoint Whisper interne, et expose un centre de conversations pour
que les collaborateurs répondent en texte libre depuis le portail.
"""
from __future__ import annotations

import io
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from albarka_admin_settings import get_settings_doc
from albarka_auth import require_roles
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.wa_inbox")

# Rôles autorisés côté cabinet à voir et répondre.
_INBOX_ROLES = ["superviseur", "direction", "administrateur", "communication"]

router = APIRouter(prefix="/whatsapp", tags=["Conversations WhatsApp"])


# =====================================================================
# Webhook Meta — GET (vérification) + POST (réception)
# =====================================================================
@router.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(
    hub_mode: Optional[str] = Query(None, alias="hub.mode"),
    hub_verify_token: Optional[str] = Query(None, alias="hub.verify_token"),
    hub_challenge: Optional[str] = Query(None, alias="hub.challenge"),
):
    """Vérification du webhook par Meta (setup one-shot)."""
    settings = await get_settings_doc()
    expected = (settings.get("wa_webhook_verify_token") or "").strip()
    if hub_mode == "subscribe" and hub_verify_token and hub_verify_token == expected:
        return PlainTextResponse(hub_challenge or "")
    raise HTTPException(status_code=403, detail="Vérification refusée")


async def _resolve_contact(phone: str) -> tuple[Optional[str], Optional[str]]:
    """Rattache un numéro à un contact existant (annuaire ou compte client).
    Renvoie (contact_id, contact_name) — les deux à None si aucune correspondance.
    """
    # Annuaire de contacts (Partie 2 précédente)
    c = await db.contacts.find_one({"phone": phone}, {"_id": 0, "id": 1, "full_name": 1})
    if c:
        return c.get("id"), c.get("full_name")
    # Compte client cabinet
    u = await db.users.find_one({"phone": phone, "roles": "client"}, {"_id": 0, "id": 1, "full_name": 1})
    if u:
        return u.get("id"), u.get("full_name")
    return None, None


async def _download_wa_media(media_id: str) -> tuple[Optional[bytes], Optional[str]]:
    """Télécharge un média WhatsApp via l'API Meta (2 étapes : URL puis blob).
    Renvoie (bytes, mime) ou (None, None) si échec.
    """
    settings = await get_settings_doc()
    token = settings.get("wa_access_token") or ""
    graph = f"v{settings.get('wa_graph_version') or '19.0'}"
    if not token:
        return None, None
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r1 = await client.get(
                f"https://graph.facebook.com/{graph}/{media_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
            if r1.status_code >= 300:
                return None, None
            info = r1.json()
            url = info.get("url")
            mime = info.get("mime_type")
            if not url:
                return None, None
            r2 = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            if r2.status_code >= 300:
                return None, None
            return r2.content, mime
    except httpx.HTTPError:
        logger.exception("Téléchargement média WA %s échoué", media_id)
        return None, None


async def _transcribe_wa_audio(audio_bytes: bytes, mime: Optional[str]) -> Optional[str]:
    """Transcription silencieuse d'une note vocale entrante (best-effort).

    Réutilise le pipeline Whisper de Partie 1.A. Ne bloque jamais le webhook.
    """
    try:
        from albarka_chat_extra import transcribe_audio_bytes
        return await transcribe_audio_bytes(audio_bytes, mime=mime or "audio/ogg", language="fr")
    except Exception:  # noqa: BLE001
        logger.exception("Transcription WA échouée")
        return None


@router.post("/webhook")
async def receive_webhook(request: Request):
    """Réception des évènements WhatsApp — Meta appelle sans authentification.

    Traite uniquement les messages entrants (types text/image/audio/document/
    video/location/etc). Déduplique par `wa_message_id`. Pour les audios,
    lance une transcription en background (contrôlée par le flag
    `settings.wa_voice_transcribe_enabled`).
    """
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return {"ok": False}
    settings = await get_settings_doc()
    transcribe_audio = bool(settings.get("wa_voice_transcribe_enabled", True))

    inserted = 0
    for entry in (body.get("entry") or []):
        for change in (entry.get("changes") or []):
            value = change.get("value") or {}
            contacts = value.get("contacts") or []
            profile_name = None
            if contacts:
                profile_name = (contacts[0].get("profile") or {}).get("name")
            for msg in (value.get("messages") or []):
                wa_mid = msg.get("id")
                if not wa_mid:
                    continue
                # Déduplication stricte (Meta rejoue parfois le même webhook)
                existing = await db.wa_messages.find_one({"wa_message_id": wa_mid}, {"_id": 0, "id": 1})
                if existing:
                    continue
                from_num = (msg.get("from") or "").strip()
                phone = f"+{from_num}" if from_num and not from_num.startswith("+") else from_num
                mtype = msg.get("type") or "unknown"
                doc: dict = {
                    "id": secrets.token_urlsafe(12),
                    "direction": "inbound",
                    "phone": phone,
                    "wa_message_id": wa_mid,
                    "message_type": mtype,
                    "body": "",
                    "media_url": None,
                    "media_mime": None,
                    "media_kind": None,
                    "voice_note_transcript": None,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "read_by_staff_at": None,
                    "profile_name": profile_name,
                }
                # Parsing par type
                if mtype == "text":
                    doc["body"] = (msg.get("text") or {}).get("body") or ""
                elif mtype in ("image", "audio", "video", "document"):
                    media = msg.get(mtype) or {}
                    doc["media_kind"] = mtype
                    doc["media_mime"] = media.get("mime_type")
                    doc["body"] = media.get("caption") or ""
                    media_id = media.get("id")
                    if media_id and mtype == "audio" and transcribe_audio:
                        audio_bytes, mime = await _download_wa_media(media_id)
                        if audio_bytes:
                            transcript = await _transcribe_wa_audio(audio_bytes, mime)
                            if transcript:
                                doc["voice_note_transcript"] = transcript
                elif mtype == "location":
                    loc = msg.get("location") or {}
                    doc["body"] = f"[location] lat={loc.get('latitude')} lng={loc.get('longitude')}"
                else:
                    doc["body"] = f"[{mtype}]"

                # Rattachement contact/client
                contact_id, contact_name = await _resolve_contact(phone)
                doc["contact_id"] = contact_id
                doc["contact_name"] = contact_name or profile_name

                await db.wa_messages.insert_one(dict(doc))
                inserted += 1

                # Auto-étiquette : si la conversation était "resolved",
                # la remettre à "todo" pour que le staff la retraite.
                # (les conversations "waiting" restent en attente ;
                # les conversations "todo" ou sans label ne sont pas touchées)
                existing_label = await db.wa_conversation_labels.find_one(
                    {"phone": phone}, {"_id": 0, "label": 1},
                )
                if existing_label and existing_label.get("label") == "resolved":
                    await db.wa_conversation_labels.update_one(
                        {"phone": phone},
                        {"$set": {
                            "phone": phone, "label": "todo",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                            "updated_by": "system:auto_reopen",
                            "updated_by_name": "Réouverture automatique",
                        }},
                        upsert=True,
                    )
    return {"ok": True, "inserted": inserted}


# =====================================================================
# Centre de conversations — endpoints staff
# =====================================================================
@router.get("/conversations")
async def list_conversations(user: dict = Depends(require_roles(_INBOX_ROLES))):
    """Liste groupée par numéro : dernier message + non lus."""
    pipeline = [
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$phone",
            "last_at": {"$first": "$created_at"},
            "last_body": {"$first": "$body"},
            "last_direction": {"$first": "$direction"},
            "last_type": {"$first": "$message_type"},
            "contact_name": {"$first": "$contact_name"},
            "profile_name": {"$first": "$profile_name"},
            "count": {"$sum": 1},
            "unread": {"$sum": {
                "$cond": [
                    {"$and": [
                        {"$eq": ["$direction", "inbound"]},
                        {"$eq": ["$read_by_staff_at", None]},
                    ]},
                    1, 0,
                ]
            }},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 300},
    ]
    rows = await db.wa_messages.aggregate(pipeline).to_list(300)
    # Joindre les labels de conversation (Partie 2.E)
    label_rows = await db.wa_conversation_labels.find({}, {"_id": 0, "phone": 1, "label": 1}).to_list(2000)
    label_map = {r["phone"]: r["label"] for r in label_rows if r.get("phone")}
    return [{
        "phone": r["_id"], "last_at": r["last_at"], "last_body": r["last_body"][:200],
        "last_direction": r["last_direction"], "last_type": r["last_type"],
        "contact_name": r.get("contact_name") or r.get("profile_name") or None,
        "count": r["count"], "unread": r["unread"],
        "label": label_map.get(r["_id"]),
    } for r in rows]


@router.get("/conversations/{phone}/messages")
async def conversation_messages(
    phone: str, limit: int = 200,
    user: dict = Depends(require_roles(_INBOX_ROLES)),
):
    items = await db.wa_messages.find(
        {"phone": phone}, {"_id": 0},
    ).sort("created_at", 1).to_list(min(max(limit, 1), 500))
    # Marquer les entrants comme lus (best-effort — un seul $set groupé)
    await db.wa_messages.update_many(
        {"phone": phone, "direction": "inbound", "read_by_staff_at": None},
        {"$set": {"read_by_staff_at": datetime.now(timezone.utc).isoformat()}},
    )
    return serialize_many(items)


class ReplyPayload(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)


@router.post("/conversations/{phone}/reply")
async def send_reply(
    phone: str, payload: ReplyPayload,
    user: dict = Depends(require_roles(_INBOX_ROLES)),
):
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Numéro attendu au format international (+226…)")
    contact_id, contact_name = await _resolve_contact(phone)
    if not contact_id:
        raise HTTPException(
            status_code=404,
            detail="Ce numéro ne correspond à aucun contact ni client enregistré — "
                   "ajoutez-le d'abord dans le module Contacts avant de lui écrire.",
        )
    from albarka_notifications import send_whatsapp
    result = await send_whatsapp(to_phone=phone, message=payload.body)
    doc = {
        "id": secrets.token_urlsafe(12),
        "direction": "outbound",
        "phone": phone,
        "wa_message_id": result.get("message_id"),
        "message_type": "text",
        "body": payload.body,
        "media_url": None, "media_mime": None, "media_kind": None,
        "voice_note_transcript": None,
        "contact_id": contact_id, "contact_name": contact_name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "read_by_staff_at": datetime.now(timezone.utc).isoformat(),
        "sent_by": user["id"],
        "sent_by_name": user.get("full_name") or user.get("email"),
        "wa_kind": result.get("kind"),
        "wa_error": result.get("error"),
        "outside_24h_window": result.get("outside_24h_window"),
    }
    await db.wa_messages.insert_one(dict(doc))
    return {"ok": bool(result.get("ok")), "message": serialize(doc), "result": result}
