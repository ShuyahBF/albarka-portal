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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_roles
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.wa_inbox")

# Rôles autorisés côté cabinet à voir et répondre (la DG comme la Direction, lot 10).
_INBOX_ROLES = ["superviseur", "direction", "dg", "administrateur", "communication"]

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


# Lot 50 — fichiers REÇUS (images, documents) conservés dans le stockage du portail pour être affichés dans le fil.
# Les vidéos et les notes vocales ne sont pas conservées ici. 10 Mo au plus.
EXT_PAR_MIME = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif", "application/pdf": "pdf",
                "application/msword": "doc",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
                "application/vnd.ms-excel": "xls",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx", "text/plain": "txt"}
TAILLE_MAX_RECU = 10 * 1024 * 1024


async def conserver_fichier_recu(doc_id: str, octets: Optional[bytes], mime: Optional[str], nom: Optional[str]) -> bool:
    """Copie un fichier reçu dans le stockage et le rattache au message `doc_id`. Ne lève jamais d'exception."""
    try:
        mime = (mime or "").split(";")[0].strip().lower()
        if not octets or len(octets) > TAILLE_MAX_RECU or mime not in EXT_PAR_MIME:
            return False
        from albarka_storage import build_path, put_object
        chemin = build_path("whatsapp-recu", "cabinet", EXT_PAR_MIME[mime])
        await put_object(chemin, octets, mime)
        maj = {"media_path": chemin, "media_mime": mime}
        if nom:
            maj["media_filename"] = nom[:120]
        await db.wa_messages.update_one({"id": doc_id}, {"$set": maj})
        return True
    except Exception:  # noqa: BLE001 — le message reste affiché sans aperçu
        logger.warning("Fichier reçu non conservé (message %s)", doc_id, exc_info=True)
        return False


async def rapatrier_media_meta(doc_id: str, media_id: str, nom: Optional[str]) -> None:
    """Arrière-plan : télécharge le média chez Meta (l'adresse expire vite) puis le conserve."""
    octets, mime = await _download_wa_media(media_id)
    await conserver_fichier_recu(doc_id, octets, mime, nom)


async def rapatrier_media_url(doc_id: str, url: str, mime: Optional[str], nom: Optional[str]) -> None:
    """Arrière-plan : télécharge le fichier d'une réponse relayée par la Transmission universelle (lien temporaire de SAWALI)."""
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            r = await client.get(url)
        if r.status_code < 300:
            await conserver_fichier_recu(doc_id, r.content, mime or r.headers.get("content-type"), nom)
    except httpx.HTTPError:
        logger.warning("Fichier relayé non téléchargé (message %s)", doc_id)


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
                # Lot 62 : l'équipe abonnée est prévenue par notification push, en arrière-plan (jamais dans la réponse à Meta)
                import asyncio as _asyncio
                from albarka_push import prevenir_equipe_message_wa
                _asyncio.create_task(prevenir_equipe_message_wa(
                    phone, doc.get("contact_name"), doc.get("body") or doc.get("voice_note_transcript") or f"[{mtype}]"))
                # Lot 50 : image ou document reçu → copie conservée en arrière-plan (la réponse à Meta n'attend pas)
                if mtype in ("image", "document") and (msg.get(mtype) or {}).get("id"):
                    import asyncio
                    asyncio.create_task(rapatrier_media_meta(doc["id"], msg[mtype]["id"], (msg.get(mtype) or {}).get("filename")))

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
    for m in items:                               # lot 45 : le chemin de stockage reste interne ; l'écran sait juste qu'un fichier existe
        m["fichier_disponible"] = bool(m.pop("media_path", None))
    return serialize_many(items)


class ReplyPayload(BaseModel):
    body: str = Field(..., min_length=1, max_length=8000)
    # Lot 38 : « Répondre » à un message précis de la conversation (identifiant du message dans la boîte, pas celui de Meta)
    reply_to_id: Optional[str] = Field(None, max_length=64)
    # Lot 39 : le cabinet a accepté d'envoyer hors fenêtre de 24 h (modèle Meta facturé)
    confirmer_modele: bool = False


async def _fenetre_24h_ouverte(phone: str) -> bool:
    """Lot 39 : vrai si le contact a écrit au cabinet il y a moins de 24 h (réponse libre gratuite)."""
    dernier = await db.wa_messages.find_one(
        {"phone": phone, "direction": "inbound"}, {"_id": 0, "created_at": 1}, sort=[("created_at", -1)])
    if not dernier or not dernier.get("created_at"):
        return False
    try:
        quand = datetime.fromisoformat(str(dernier["created_at"]).replace("Z", "+00:00"))
        if quand.tzinfo is None:
            quand = quand.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    return datetime.now(timezone.utc) - quand < timedelta(hours=24)


async def refus_hors_fenetre(phone: str, confirme: bool) -> None:
    """Lot 40 : lève HTTP 409 « hors_fenetre_24h » si le contact n'a pas écrit depuis 24 h et que le
    cabinet n'a pas confirmé (l'envoi passerait par un modèle Meta facturé). Commun à tous les envois."""
    # Mode test du super-admin : l'envoi part vers son numéro de test, c'est donc la fenêtre de CE numéro qui compte
    from albarka_envoi_test import numero_effectif
    reel, erreur = await numero_effectif(phone)
    if erreur:
        raise HTTPException(status_code=400, detail=erreur)
    if not confirme and not await _fenetre_24h_ouverte(reel):
        raise HTTPException(status_code=409, detail={
            "code": "hors_fenetre_24h",
            "message": "Ce contact ne vous a pas écrit depuis plus de 24 h : le message sera envoyé avec un "
                       "modèle Meta, facturé au cabinet.",
        })


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
    await refus_hors_fenetre(phone, payload.confirmer_modele)   # lot 39/40 : accord du cabinet hors fenêtre de 24 h
    # Lot 38 : message cité (même conversation) → identifiant WhatsApp réel + aperçu gardé avec le message envoyé
    cite, cite_wa_id = None, None
    if payload.reply_to_id:
        origine = await db.wa_messages.find_one({"id": payload.reply_to_id, "phone": phone}, {"_id": 0})
        if origine:
            wa_id = origine.get("wa_real_id") or origine.get("wa_message_id") or ""
            cite_wa_id = wa_id if wa_id and not wa_id.startswith("liluvine:") else None   # « liluvine:… » = pas un identifiant Meta
            cite = {"id": origine["id"], "direction": origine.get("direction"),
                    "auteur": (origine.get("contact_name") or origine.get("profile_name") or origine.get("sent_by_name") or phone)
                    if origine.get("direction") == "inbound" else (origine.get("sent_by_name") or "Cabinet"),
                    "texte": (origine.get("body") or origine.get("voice_note_transcript") or f"[{origine.get('message_type') or 'message'}]")[:200]}
    from albarka_notifications import send_whatsapp
    result = await send_whatsapp(to_phone=phone, message=payload.body, reply_to=cite_wa_id)
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
        "reply_to": cite,                                  # lot 38 : aperçu du message cité (affiché au-dessus de la réponse)
    }
    await db.wa_messages.insert_one(dict(doc))
    return {"ok": bool(result.get("ok")), "message": serialize(doc), "result": result}



# =====================================================================
# Lots 45 / 47 / 49 — documents ET images joints à une conversation : TOUJOURS issus de la bibliothèque (Archives cabinet),
# marqués « partageable ». Aucun fichier n'est envoyé directement depuis l'appareil. Pas de vidéo.
# =====================================================================
class ArchiveSendPayload(BaseModel):
    archive_id: str = Field(..., max_length=64)
    legende: str = Field("", max_length=1000)
    confirmer_modele: bool = False


@router.post("/conversations/{phone}/send-archive")
async def send_archive(phone: str, payload: ArchiveSendPayload, user: dict = Depends(require_roles(_INBOX_ROLES))):
    """Lot 47 / 50 — envoie un document ou une image de la BIBLIOTHÈQUE (PDF, Word, JPEG, PNG) marqué « partageable » au contact.
    Mêmes règles que le texte : contact connu, accord du cabinet hors fenêtre de 24 h (409), mode test du super-admin."""
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Numéro attendu au format international (+226…)")
    a = await db.archives.find_one({"id": payload.archive_id}, {"_id": 0})
    if not a or not a.get("storage_path"):
        raise HTTPException(status_code=404, detail="Document introuvable dans la bibliothèque")
    if not a.get("partageable"):
        raise HTTPException(status_code=403, detail="Ce document n'est pas marqué « partageable » dans la bibliothèque")
    contact_id, contact_name = await _resolve_contact(phone)
    if not contact_id:
        raise HTTPException(status_code=404, detail="Ce numéro ne correspond à aucun contact ni client enregistré — "
                                                    "ajoutez-le d'abord dans le module Contacts avant de lui écrire.")
    await refus_hors_fenetre(phone, payload.confirmer_modele)
    from albarka_notifications import send_whatsapp_fichier
    from albarka_storage import get_object
    donnees, ct = await get_object(a["storage_path"])
    nom = a.get("original_filename") or f"{a.get('title') or 'document'}.pdf"
    mime = a.get("content_type") or ct or "application/octet-stream"
    legende = payload.legende.strip()
    famille = "image" if mime.startswith("image/") else "document"          # lot 50 : la bibliothèque contient aussi des images
    result = await send_whatsapp_fichier(to_phone=phone, data=donnees, filename=nom, content_type=mime, caption=legende)
    doc = {
        "id": secrets.token_urlsafe(12), "direction": "outbound", "phone": phone,
        "wa_message_id": result.get("message_id"), "message_type": famille, "body": legende,
        "media_url": None, "media_mime": mime, "media_kind": famille, "media_filename": nom,
        "media_path": a["storage_path"], "archive_id": a["id"],      # le fichier reste celui de la bibliothèque
        "voice_note_transcript": None, "contact_id": contact_id, "contact_name": contact_name,
        "created_at": datetime.now(timezone.utc).isoformat(), "read_by_staff_at": datetime.now(timezone.utc).isoformat(),
        "sent_by": user["id"], "sent_by_name": user.get("full_name") or user.get("email"),
        "wa_kind": result.get("kind"), "wa_error": result.get("error"), "outside_24h_window": result.get("outside_24h_window"),
        "reply_to": None,
    }
    await db.wa_messages.insert_one(dict(doc))
    doc.pop("media_path", None)
    return {"ok": bool(result.get("ok")), "message": serialize(doc), "result": result}


@router.get("/messages/{message_id}/fichier")
async def fichier_du_message(message_id: str, user: dict = Depends(require_roles(_INBOX_ROLES))):
    """Fichier (document ou image) envoyé depuis la conversation — pour l'aperçu et l'ouverture."""
    m = await db.wa_messages.find_one({"id": message_id}, {"_id": 0, "media_path": 1, "media_mime": 1, "media_filename": 1})
    if not m or not m.get("media_path"):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    from albarka_storage import get_object
    donnees, ct = await get_object(m["media_path"])
    nom = (m.get("media_filename") or "fichier").replace('"', "")
    return Response(donnees, media_type=m.get("media_mime") or ct or "application/octet-stream",
                    headers={"Content-Disposition": f'inline; filename="{nom}"'})


# =====================================================================
# Lot 34 — numéro WhatsApp du cabinet (en-tête du portail) et remise à zéro des conversations (super-admin)
# =====================================================================
@router.get("/numero-cabinet")
async def numero_cabinet(user: dict = Depends(get_current_user)):
    """Numéro WhatsApp du cabinet, affiché sous son nom dans l'en-tête du portail (chaîne vide = rien à afficher)."""
    s = await get_settings_doc()
    return {"numero": (s.get("cabinet_whatsapp_number") or "").strip()}


class PurgePayload(BaseModel):
    confirmation: str = Field("", max_length=20)


async def _super_admin(user: dict = Depends(get_current_user)) -> dict:
    """Compte super-admin du portail uniquement (mêmes règles que les autres outils d'administration)."""
    from albarka_models import is_admin_account
    if not is_admin_account(user):
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur du portail")
    return user


@router.post("/conversations/purge")
async def purger_conversations(payload: PurgePayload, user: dict = Depends(_super_admin)):
    """Vide TOUTES les conversations WhatsApp du portail (messages et étiquettes), pour repartir à zéro après des tests.
    Réservé au compte super-admin ; il faut renvoyer la confirmation « SUPPRIMER ». Ne touche ni aux contacts, ni aux
    réponses rapides, ni au journal de transmission de SAWALI, ni aux messages déjà reçus sur les téléphones.
    Lot 59 : vide aussi les messages du support SAWALI de cette plateforme (appel signé, au mieux)."""
    if (payload.confirmation or "").strip().upper() != "SUPPRIMER":
        raise HTTPException(status_code=422, detail="Tapez SUPPRIMER pour confirmer la remise à zéro des conversations")
    messages = await db.wa_messages.delete_many({})
    etiquettes = await db.wa_conversation_labels.delete_many({})
    logger.warning("[wa_inbox] conversations vidées par %s : %s messages, %s étiquettes",
                   user.get("email"), messages.deleted_count, etiquettes.deleted_count)
    # Lot 59 : le même bouton vide aussi la discussion avec le support SAWALI (espace « ALBARKA - Support » chez SAWALI).
    # Au mieux : si SAWALI est injoignable ou pas encore à jour, la remise à zéro locale reste faite et on l'indique.
    support: dict = {"vide": False, "erreur": None}
    from albarka_support_sawali import appeler_sawali, configure as support_configure
    if support_configure():
        try:
            r = await appeler_sawali("/support-plateforme/purge", {"confirmation": "SUPPRIMER"})
            support = {"vide": True, "erreur": None, "messages_supprimes": r.get("messages_supprimes", 0),
                       "fichiers_supprimes": r.get("fichiers_supprimes", 0)}
        except HTTPException as exc:
            support = {"vide": False, "erreur": str(exc.detail)}
        except Exception:  # noqa: BLE001
            logger.exception("[wa_inbox] purge du support SAWALI en erreur")
            support = {"vide": False, "erreur": "Support SAWALI : erreur inattendue"}
    return {"ok": True, "messages_supprimes": messages.deleted_count, "etiquettes_supprimees": etiquettes.deleted_count,
            "support": support}
