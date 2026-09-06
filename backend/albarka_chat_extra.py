"""Partie 1 — Extensions du chat interne (transcribe, search, pièce jointe).

Le module `albarka_phase_c.chat_router` reste le socle. Ce fichier ajoute
trois endpoints supplémentaires (POST /chat/transcribe, GET /chat/search,
POST /chat/messages/file) et une fonction publique `transcribe_audio_bytes`
réutilisée aussi par le webhook WhatsApp entrant (Partie 2.D).

Chat interne = collaborateurs uniquement (voir albarka_phase_c.py) : tous
les endpoints ici sont donc protégés par `require_staff()`, jamais par
`get_current_user` seul.
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
from albarka_phase_c import _get_thread_or_404
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.chat_extra")

# Extensions/MIMES tolérés — mêmes contraintes que la référence Liluvine.
ALLOWED_AUDIO_EXT = {".mp3", ".mp4", ".mpeg", ".mpga", ".m4a", ".wav", ".webm", ".ogg"}
AUDIO_SIZE_CAP = 25 * 1024 * 1024  # 25 Mo

# Pièces jointes du chat interne : un collaborateur en déplacement doit
# pouvoir envoyer un dossier zippé ou des pièces collectées chez un client
# (PDF, scans, tableurs), pas seulement des photos.
ALLOWED_IMAGE_MIME = {"image/jpeg", "image/jpg", "image/png", "image/webp", "image/heic", "image/heif"}
ALLOWED_DOC_MIME = {
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/zip",
    "application/x-zip-compressed",
}
ALLOWED_ATTACHMENT_MIME = ALLOWED_IMAGE_MIME | ALLOWED_DOC_MIME
ATTACHMENT_SIZE_CAP = 10 * 1024 * 1024  # 10 Mo — y compris pour les zips

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
    user: dict = Depends(require_staff()),
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
    user: dict = Depends(require_staff()),
):
    if not q or not q.strip():
        raise HTTPException(status_code=400, detail="Terme de recherche requis")
    query: dict = {"body": {"$regex": q.strip(), "$options": "i"}}
    if thread_id:
        await _get_thread_or_404(thread_id, user)
        query["thread_id"] = thread_id
    else:
        # Une recherche globale (sans thread_id) ne doit jamais faire
        # remonter le contenu d'une discussion directe dont l'utilisateur
        # n'est pas participant — les fils de groupe, eux, restent
        # cherchables par tout collaborateur, comme avant.
        foreign_dms = await db.chat_threads.find(
            {"kind": "dm", "participants": {"$ne": user["id"]}}, {"_id": 0, "id": 1},
        ).to_list(5000)
        foreign_ids = [d["id"] for d in foreign_dms]
        if foreign_ids:
            query["thread_id"] = {"$nin": foreign_ids}
    items = await db.chat_messages.find(query, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 100))
    return serialize_many(items)


# =====================================================================
# Partie 1.D — Pièce jointe (upload R2) : photo ou document (PDF, Word,
# Excel, zip) — un collaborateur en déplacement doit pouvoir transmettre
# n'importe quelle pièce collectée chez un client, pas seulement des photos.
# =====================================================================
_EXT_BY_MIME = {
    "image/png": ".png", "image/webp": ".webp",
    "image/heic": ".heic", "image/heif": ".heif",
    "application/pdf": ".pdf",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.ms-excel": ".xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
}


@router.post("/messages/file")
async def post_file_message(
    thread_id: str = Form(...),
    caption: str = Form(""),
    file: UploadFile = File(...),
    user: dict = Depends(require_staff()),
):
    await _get_thread_or_404(thread_id, user)
    mime = (file.content_type or "").lower()
    if mime not in ALLOWED_ATTACHMENT_MIME:
        raise HTTPException(status_code=400, detail=f"Type de fichier non pris en charge : {mime or 'inconnu'}")
    blob = await file.read()
    if not blob:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(blob) > ATTACHMENT_SIZE_CAP:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 10 Mo)")
    # Storage R2 (module existant)
    from storage_r2 import put_object
    ext = _EXT_BY_MIME.get(mime, ".jpg")
    original_name = file.filename or f"fichier{ext}"
    storage_path = f"albarka/chat/{thread_id}/{secrets.token_urlsafe(10)}{ext}"
    await put_object(storage_path, blob, mime)
    doc = {
        "id": secrets.token_urlsafe(12),
        "thread_id": thread_id,
        "body": caption[:2000],
        "author_id": user["id"],
        "author_name": user.get("full_name") or user.get("email"),
        "media_kind": "image" if mime in ALLOWED_IMAGE_MIME else "file",
        "media_mime": mime,
        "media_size": len(blob),
        "media_filename": original_name,
        "media_url": f"/api/chat/media/{storage_path}",
        "media_storage_path": storage_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(dict(doc))
    return serialize(doc)


@router.get("/media/{path:path}")
async def get_chat_media(path: str, user: dict = Depends(require_staff())):
    """Sert un media chat depuis R2 — chat interne = staff uniquement.

    Le chemin de stockage embarque le thread_id ("albarka/chat/{thread_id}/…")
    — on le retrouve pour appliquer la même restriction de participation
    qu'ailleurs sur une discussion directe (kind="dm") : impossible de
    contourner la confidentialité d'une pièce jointe en devinant/observant
    son URL."""
    from fastapi.responses import Response
    from storage_r2 import get_object
    parts = path.split("/")
    if len(parts) >= 3 and parts[0] == "albarka" and parts[1] == "chat":
        await _get_thread_or_404(parts[2], user)
    try:
        blob, mime = await get_object(path)
    except Exception:
        raise HTTPException(status_code=404, detail="Media introuvable")
    return Response(content=blob, media_type=mime or "application/octet-stream")
