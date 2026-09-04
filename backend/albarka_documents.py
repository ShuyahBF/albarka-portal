"""Documents (pièces client) — upload, listing, download, analyse IA."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from albarka_ai import analyze_document
from albarka_auth import get_current_user
from albarka_models import DOCUMENT_KINDS, is_client, tenant_id_of
from albarka_notifications import notify_upload
from albarka_storage import get_object, guess_content_type, presigned_url, save_and_log, storage_mode
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.documents")

router = APIRouter(prefix="/documents", tags=["Pièces client"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "doc", "docx", "xls", "xlsx", "txt", "csv"}


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def _resolve_tenant_id(user: dict, requested: Optional[str]) -> str:
    if is_client(user):
        return tenant_id_of(user)
    if not requested:
        raise HTTPException(status_code=400, detail="tenant_id requis pour un compte cabinet")
    return requested


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
    content_type = guess_content_type(ext, file.content_type or "application/octet-stream")

    stored = await save_and_log(
        db, data=data, kind=kind, tenant_id=resolved_tenant_id,
        ext=ext, content_type=content_type,
        original_filename=file.filename, user_id=user["id"],
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

    # Point 2 — capture automatique dans la bibliothèque d'archives.
    try:
        from albarka_phase_c import _auto_archive
        await _auto_archive(
            title=f"Pièce {kind} — {file.filename or doc['id']}",
            category="pieces_client",
            tags=[kind, resolved_tenant_id],
            source={"kind": "document", "id": doc["id"],
                    "tenant_id": resolved_tenant_id,
                    "storage_path": stored["path"]},
            user=user,
        )
    except Exception:  # noqa: BLE001
        pass  # best-effort

    # Notify staff (fire-and-forget) whenever a **client** deposits a piece.
    if is_client(user):
        tenant = await db.users.find_one({"id": resolved_tenant_id}, {"_id": 0, "password_hash": 0})
        if tenant:
            asyncio.create_task(notify_upload(db, document=doc, tenant=tenant))

    asyncio.create_task(_analyze_and_store(doc["id"], data, content_type, file.filename or "", resolved_tenant_id))
    return serialize(doc.copy())


async def _analyze_and_store(document_id: str, data: bytes, content_type: str, filename: str, tenant_id: str) -> None:
    try:
        result = await analyze_document(data, content_type, filename)
        synthesis = {
            "id": document_id,
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
        new_status = "erreur_analyse" if result.get("error") or (result.get("flags") and not result.get("summary")) else "analyse"
        await db.documents.update_one({"id": document_id}, {"$set": {"status": new_status}})
    except Exception:
        logger.exception("Échec analyse IA pour %s", document_id)
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
    url = await presigned_url(doc["storage_path"], expires_in=300)
    if url:
        return {"url": url, "expires_in": 300, "mode": "r2"}
    # Local mode: caller should hit /documents/{id}/download
    return {"url": None, "mode": "local"}


@router.get("/{document_id}/download")
async def download_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    data, ct = await get_object(doc["storage_path"])
    filename = doc.get("original_filename") or "document"
    return Response(
        content=data,
        media_type=ct or doc.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{document_id}")
async def delete_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    await db.documents.delete_one({"id": document_id})
    await db.document_syntheses.delete_one({"document_id": document_id})
    return {"ok": True, "id": document_id}


@router.get("/_meta/storage-mode")
async def _meta_storage_mode(user: dict = Depends(get_current_user)):
    return {"mode": storage_mode()}
