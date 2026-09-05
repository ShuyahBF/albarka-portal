"""Partie 1 — Extensions du chat interne (transcribe, search, photo).

Le module `albarka_phase_c.chat_router` reste le socle. Ce fichier ajoute
trois endpoints supplémentaires (POST /chat/transcribe, GET /chat/search,
POST /chat/messages/photo) et une fonction publique `transcribe_audio_bytes`
réutilisée aussi par le webhook WhatsApp entrant (Partie 2.D).
"""
from __future__ import annotations

import io
import logging
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import (
    APIRouter, Depends, File, Form, HTTPException, UploadFile,
)

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_staff
from albarka_models import is_client, tenant_id_of
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.chat_extra")

# Extensions/MIMES tolérés — mêmes contraintes que la référence Liluvine.
ALLOWED_AUDIO_EXT = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
AUDIO_SIZE_CAP = 25 * 1024 * 1024  # 25 Mo

ALLOWED_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
IMAGE_SIZE_CAP = 10 * 1024 * 1024  # 10 Mo

router = APIRouter(prefix="/chat", tags=["Chat interne"])


# =====================================================================
# Whisper — endpoint dédié + fonction utilitaire réutilisée par le webhook WA
# =====================================================================
async def transcribe_audio_bytes(
    data: bytes, *, mime: str = "audio/ogg", language: str = "fr",
) -> Optional[str]:
    """Transcrit un blob audio via OpenAI Whisper (Emergent LLM Key).

    Écrit un fichier temporaire (nettoyé dans `finally`), appelle le SDK
    `emergentintegrations.llm.openai.OpenAISpeechToText`. Renvoie le texte
    transcrit ou None en cas d'échec.
    """
    # Décision "on / off" via le flag settings.
    settings = await get_settings_doc()
    if not settings.get("voice_notes_enabled", True):
        return None
    key = os.environ.get("EMERGENT_LLM_KEY")
    if not key:
        logger.warning("EMERGENT_LLM_KEY absent — transcription impossible")
        return None
    # Choisir une extension cohérente avec le MIME reçu.
    ext = ".ogg"
    if mime and "webm" in mime: ext = ".webm"
    elif mime and "mp4" in mime: ext = ".m4a"
    elif mime and "mpeg" in mime: ext = ".mp3"
    elif mime and "wav" in mime: ext = ".wav"
    tmp: Optional[str] = None
    try:
        fd, tmp = tempfile.mkstemp(suffix=ext, prefix="wa_audio_")
        os.write(fd, data)
        os.close(fd)
        from emergentintegrations.llm.openai import OpenAISpeechToText  # type: ignore
        stt = OpenAISpeechToText(api_key=key)
        text = await stt.speech_to_text(
            file_path=Path(tmp), model="whisper-1", language=language,
            response_format="text", temperature=0,
        )
        return (text or "").strip() or None
    except Exception:  # noqa: BLE001
        logger.exception("Whisper transcription failure")
        return None
    finally:
        if tmp:
            try: os.remove(tmp)
            except OSError: pass


@router.post("/transcribe")
async def transcribe_endpoint(
    audio: UploadFile = File(...),
    language: str = Form("fr"),
    user: dict = Depends(get_current_user),
):
    """Partie 1.A — transcription note vocale (audio uniquement, jeté après).

    Le fichier n'est jamais conservé : ni sur disque (nettoyé en finally),
    ni en base (le texte transcrit est retourné au client pour relecture,
    puis l'utilisateur clique Envoyer comme un message normal).
    """
    settings = await get_settings_doc()
    if not settings.get("voice_notes_enabled", True):
        raise HTTPException(status_code=403, detail="Notes vocales désactivées par l'administrateur")
    fname = audio.filename or "audio.ogg"
    ext = Path(fname).suffix.lower()
    if ext not in ALLOWED_AUDIO_EXT:
        raise HTTPException(status_code=400, detail=f"Extension {ext} non prise en charge")
    blob = await audio.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Fichier audio vide")
    if len(blob) > AUDIO_SIZE_CAP:
        raise HTTPException(status_code=413, detail="Audio trop volumineux (max 25 Mo)")
    text = await transcribe_audio_bytes(blob, mime=audio.content_type or "audio/ogg", language=language)
    if text is None:
        raise HTTPException(status_code=502, detail="La transcription a échoué — réessayez")
    return {"ok": True, "text": text}


# =====================================================================
# Partie 1.B — Recherche plein texte
# =====================================================================
@router.get("/search")
async def chat_search(
    q: str,
    thread_id: Optional[str] = None,
    limit: int = 30,
    user: dict = Depends(get_current_user),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Terme de recherche requis")
    query: dict = {"body": {"$regex": q.strip(), "$options": "i"}}
    # Cloisonnement client : uniquement son propre thread
    if is_client(user):
        my_thread = f"client:{tenant_id_of(user)}"
        query["thread_id"] = my_thread
    elif thread_id:
        query["thread_id"] = thread_id
    items = await db.chat_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 100))
    return serialize_many(items)


# =====================================================================
# Partie 1.D — Pièce jointe photo (upload R2)
# =====================================================================
@router.post("/messages/photo")
async def post_photo_message(
    thread_id: str = Form(...),
    caption: str = Form(""),
    photo: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    # Cloisonnement client
    if is_client(user):
        my_thread = f"client:{tenant_id_of(user)}"
        if thread_id != my_thread:
            raise HTTPException(status_code=403, detail="Accès refusé")
    mime = (photo.content_type or "").lower()
    if mime not in ALLOWED_IMAGE_MIME:
        raise HTTPException(status_code=400, detail=f"Type d'image non pris en charge : {mime or 'inconnu'}")
    blob = await photo.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Image vide")
    if len(blob) > IMAGE_SIZE_CAP:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")
    # Storage R2 (module existant)
    from storage_r2 import put_object
    ext = ".jpg"
    if "png" in mime: ext = ".png"
    elif "webp" in mime: ext = ".webp"
    elif "heic" in mime or "heif" in mime: ext = ".heic"
    storage_path = f"albarka/chat/{thread_id}/{secrets.token_urlsafe(10)}{ext}"
    await put_object(storage_path, blob, mime)
    # URL de service via endpoint dédié
    doc = {
        "id": secrets.token_urlsafe(12),
        "thread_id": thread_id,
        "body": caption[:2000],
        "author_id": user["id"],
        "author_name": user.get("full_name") or user.get("email"),
        "author_is_client": is_client(user),
        "media_kind": "image",
        "media_mime": mime,
        "media_size": len(blob),
        "media_url": f"/api/chat/media/{storage_path}",
        "media_storage_path": storage_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(dict(doc))
    return serialize(doc)


@router.get("/media/{path:path}")
async def get_chat_media(path: str, user: dict = Depends(get_current_user)):
    """Sert un media chat depuis R2 avec ACL : client → uniquement médias de son thread."""
    from fastapi.responses import Response
    from storage_r2 import get_object
    # Autorisation
    if is_client(user) and f"/{tenant_id_of(user)}/" not in f"/{path}/" and not path.startswith(f"albarka/chat/client:{tenant_id_of(user)}/"):
        raise HTTPException(status_code=403, detail="Accès refusé")
    try:
        blob, mime = await get_object(path)
    except Exception:
        raise HTTPException(status_code=404, detail="Media introuvable")
    return Response(content=blob, media_type=mime or "application/octet-stream")
