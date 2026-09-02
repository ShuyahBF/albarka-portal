"""Pièces client : téléversement, stockage R2, analyse IA, consultation.

Un client ne voit et ne téléverse que dans son propre espace (`tenant_id` =
son `user_id`). Le staff cabinet (tout rôle sauf `client`) peut téléverser
pour le compte d'un client et consulter les pièces de n'importe quel client
— la restriction fine par rôle (ex. RH ne voit que les pièces RH) est prévue
pour une itération ultérieure ; le pilote ouvre l'accès à tout le staff.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from albarka_ai import extract_and_synthesize
from albarka_auth import get_current_user
from albarka_models import DOCUMENT_KINDS, is_client, tenant_id_of
from db import db, serialize, serialize_many
import storage_r2

logger = logging.getLogger("albarka.documents")

router = APIRouter(prefix="/documents", tags=["Pièces client"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "doc", "docx", "xls", "xlsx"}


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def _resolve_tenant_id(user: dict, requested_tenant_id: Optional[str]) -> str:
    """Clients are always scoped to themselves. Staff may target any tenant
    (defaults to their own id, which is meaningless for staff but harmless)."""
    if is_client(user):
        return tenant_id_of(user)
    if not requested_tenant_id:
        raise HTTPException(status_code=400, detail="tenant_id requis pour un compte cabinet")
    return requested_tenant_id


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form("piece_comptable"),
    tenant_id: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    if kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind invalide (attendu : {DOCUMENT_KINDS})")
    ext = _ext_of(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extension non autorisée : .{ext}")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 20 Mo)")

    resolved_tenant_id = _resolve_tenant_id(user, tenant_id)
    content_type = storage_r2.guess_content_type(ext, file.content_type or "application/octet-stream")

    stored = await storage_r2.save_and_log(
        db,
        data=data,
        kind=kind,
        tenant_id=resolved_tenant_id,
        ext=ext,
        content_type=content_type,
        original_filename=file.filename,
        user_id=user["id"],
    )

    doc = {
        "id": stored["id"],
        "tenant_id": resolved_tenant_id,
        "uploaded_by": user["id"],
        "kind": kind,
        "storage_path": stored["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": stored["size"],
        "status": "en_analyse",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.documents.insert_one(doc.copy())

    # Analyse IA en tâche de fond : l'upload répond tout de suite, la
    # synthèse apparaît dès qu'elle est prête (le client peut déjà voir sa
    # pièce listée avec le statut "en_analyse").
    asyncio.create_task(_analyze_and_store(doc["id"], data, content_type, file.filename or "", resolved_tenant_id))

    return serialize(doc.copy())


async def _analyze_and_store(document_id: str, data: bytes, content_type: str, filename: str, tenant_id: str) -> None:
    try:
        result = await asyncio.to_thread(extract_and_synthesize, data, content_type, filename)
        synthesis = {
            "id": document_id,  # 1 synthèse par document : id partagé, simple à requêter
            "document_id": document_id,
            "tenant_id": tenant_id,
            "summary": result.get("summary", ""),
            "extracted_fields": result.get("extracted_fields", {}),
            "document_type_guess": result.get("document_type"),
            "flags": result.get("flags", []),
            "model": result.get("model"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.document_syntheses.update_one(
            {"id": document_id}, {"$set": synthesis}, upsert=True,
        )
        new_status = "erreur_analyse" if result.get("error") else "analyse"
        await db.documents.update_one({"id": document_id}, {"$set": {"status": new_status}})
    except Exception:
        logger.exception("Échec de l'analyse IA pour le document %s", document_id)
        await db.documents.update_one({"id": document_id}, {"$set": {"status": "erreur_analyse"}})


@router.get("")
async def list_documents(tenant_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: dict = {}
    if is_client(user):
        query["tenant_id"] = tenant_id_of(user)
    elif tenant_id:
        query["tenant_id"] = tenant_id
    docs = await db.documents.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(docs)


async def _get_owned_document(document_id: str, user: dict) -> dict:
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if is_client(user) and doc["tenant_id"] != tenant_id_of(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return doc


@router.get("/{document_id}")
async def get_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    synthesis = await db.document_syntheses.find_one({"document_id": document_id}, {"_id": 0})
    doc["synthesis"] = synthesis
    return doc


@router.get("/{document_id}/download-url")
async def get_download_url(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    url = await storage_r2.presigned_url(doc["storage_path"], expires_in=300)
    return {"url": url, "expires_in": 300}
