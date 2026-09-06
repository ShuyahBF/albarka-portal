"""Documents (pièces client) — upload, listing, download, analyse IA."""
from __future__ import annotations

import asyncio
import base64
import logging
from datetime import datetime, timezone
from html import escape as _esc
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from albarka_ai import analyze_document
from albarka_auth import get_current_user, require_staff
from albarka_models import (
    DOCS_DELETE_ROLES,
    DOCS_PRIVILEGED_ROLES,
    DOCUMENT_KINDS,
    is_client,
    is_whatsapp_verified,
    tenant_id_of,
    whatsapp_number_of,
)
from albarka_notifications import notify_upload, send_email
from albarka_storage import get_object, guess_content_type, presigned_url, save_and_log, storage_mode
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.documents")

router = APIRouter(prefix="/documents", tags=["Pièces client"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "doc", "docx", "xls", "xlsx", "txt", "csv"}

# Rôle "telechargement" : cumulable, accordé en plus du métier principal pour
# autoriser le téléchargement des pièces sans dépendre du rôle hiérarchique.
# DOCS_PRIVILEGED_ROLES/DOCS_DELETE_ROLES (albarka_models.py) sont partagés
# avec le Chat interne et le module Clients — ne pas dupliquer ces listes.
DOWNLOAD_ROLES = [*DOCS_PRIVILEGED_ROLES, "telechargement"]


def _has_download_access(user: dict) -> bool:
    return bool(set(user.get("roles") or []) & set(DOWNLOAD_ROLES))


def _require_download_access(user: dict) -> None:
    """Le client garde toujours accès à ses propres pièces ; côté staff,
    seuls DOWNLOAD_ROLES peuvent télécharger celles des clients."""
    if is_client(user):
        return
    if not _has_download_access(user):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")


def _require_delete_access(user: dict) -> None:
    """Suppression plus sensible que le téléchargement : jamais le rôle
    "telechargement" seul, jamais "secretariat" seul — voir DOCS_DELETE_ROLES."""
    if is_client(user):
        return
    if not set(user.get("roles") or []) & set(DOCS_DELETE_ROLES):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")


def _can_send_whatsapp(user: dict, owner: dict) -> bool:
    """Un collaborateur privilégié (DOCS_PRIVILEGED_ROLES) peut toujours
    envoyer. Les autres ne le peuvent que s'ils portent le rôle
    "communication" ET que le numéro WhatsApp du client est attesté
    "vérifié" — voir albarka_clients.py pour l'endpoint qui pose ce statut,
    et is_whatsapp_verified() dans albarka_models.py pour le repli sur
    phone_verified quand aucun numéro WhatsApp distinct n'est renseigné."""
    roles = set(user.get("roles") or [])
    if roles & set(DOCS_PRIVILEGED_ROLES):
        return True
    return "communication" in roles and is_whatsapp_verified(owner)


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
    docs = serialize_many(docs)

    # Vue staff : résout le propriétaire (client) de chaque pièce en une seule
    # requête groupée, pour affichage dans la colonne "Entreprise" du tableau
    # et pour déterminer si l'action WhatsApp est proposée (numéro vérifié).
    if not is_client(user) and docs:
        tenant_ids = sorted({d["tenant_id"] for d in docs if d.get("tenant_id")})
        clients = await db.users.find(
            {"id": {"$in": tenant_ids}},
            {"_id": 0, "id": 1, "full_name": 1, "company": 1, "phone_verified": 1,
             "whatsapp_number": 1, "whatsapp_verified": 1},
        ).to_list(len(tenant_ids))
        by_id = {c["id"]: c for c in clients}
        for d in docs:
            c = by_id.get(d.get("tenant_id"))
            d["client_name"] = (c or {}).get("full_name")
            d["client_company"] = (c or {}).get("company")
            d["client_whatsapp_verified"] = is_whatsapp_verified(c or {})

    return docs


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
    _require_download_access(user)
    url = await presigned_url(doc["storage_path"], expires_in=300)
    if url:
        return {"url": url, "expires_in": 300, "mode": "r2"}
    # Local mode: caller should hit /documents/{id}/download
    return {"url": None, "mode": "local"}


@router.get("/{document_id}/download")
async def download_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    _require_download_access(user)
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
    _require_delete_access(user)
    await db.documents.delete_one({"id": document_id})
    await db.document_syntheses.delete_one({"document_id": document_id})
    return {"ok": True, "id": document_id}


@router.get("/_meta/storage-mode")
async def _meta_storage_mode(user: dict = Depends(get_current_user)):
    return {"mode": storage_mode()}


class SendDocumentEmailPayload(BaseModel):
    to: Optional[str] = None
    subject: Optional[str] = None
    message: Optional[str] = None


class SendDocumentWhatsAppPayload(BaseModel):
    to: Optional[str] = None
    message: Optional[str] = None


async def _fetch_document_and_owner(document_id: str) -> tuple[dict, dict]:
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    owner = await db.users.find_one({"id": doc["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not owner:
        raise HTTPException(status_code=404, detail="Client propriétaire introuvable")
    return doc, owner


@router.post("/{document_id}/send-email")
async def send_document_email(
    document_id: str, payload: SendDocumentEmailPayload, user: dict = Depends(require_staff()),
):
    """Envoie la pièce brute (pas un rapport signé) par email, en réutilisant
    `send_email` comme déjà fait pour les rapports dans albarka_reports_mgmt.py."""
    doc, owner = await _fetch_document_and_owner(document_id)
    recipient = (payload.to or owner.get("email") or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="Aucune adresse email destinataire disponible")

    subject = payload.subject or f"Pièce — {doc.get('original_filename') or doc['id']}"
    owner_label = _esc(owner.get("company") or owner.get("full_name", ""))
    msg_body = payload.message or ""
    html = f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;padding:16px;">
  <p>Bonjour,</p>
  <p>Veuillez trouver ci-joint la pièce <strong>{_esc(doc.get('original_filename') or '')}</strong>
     concernant <strong>{owner_label}</strong>.</p>
  {"<p>" + _esc(msg_body).replace(chr(10), '<br/>') + "</p>" if msg_body else ""}
</div>
"""
    data, ct = await get_object(doc["storage_path"])
    attachment = {
        "filename": doc.get("original_filename") or "document",
        "content": base64.b64encode(data).decode("ascii"),
        "content_type": ct or doc.get("content_type", "application/octet-stream"),
    }
    message_id = await send_email(to=[recipient], subject=subject, html=html, attachments=[attachment])
    if not message_id:
        raise HTTPException(status_code=502, detail="Échec envoi email (proxy indisponible ou rejeté)")

    await db.documents.update_one(
        {"id": document_id},
        {"$set": {
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_to": recipient,
            "email_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": message_id, "to": recipient}


@router.post("/{document_id}/send-whatsapp")
async def send_document_whatsapp(
    document_id: str, payload: SendDocumentWhatsAppPayload, user: dict = Depends(require_staff()),
):
    """Envoie la pièce brute par WhatsApp, en réutilisant l'upload média Meta
    et `send_whatsapp_document` comme déjà fait pour les rapports."""
    from albarka_admin_settings import get_settings_doc
    from albarka_notifications import (
        _wa_upload_media, send_whatsapp, send_whatsapp_document, send_whatsapp_image,
    )

    doc, owner = await _fetch_document_and_owner(document_id)
    if not _can_send_whatsapp(user, owner):
        raise HTTPException(
            status_code=403,
            detail="Envoi WhatsApp réservé au rôle Communication sur un numéro attesté vérifié "
                   "(ou aux rôles superviseur/direction/DG/administrateur/secrétariat)",
        )
    phone = (payload.to or whatsapp_number_of(owner) or "").strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp éligible (format +226…)")

    settings = await get_settings_doc()
    if not settings.get("wa_enabled"):
        raise HTTPException(status_code=400, detail="WhatsApp désactivé dans les paramètres")

    filename = doc.get("original_filename") or "document"
    caption = (payload.message or "").strip() or f"Pièce — {filename}"
    data, _ct = await get_object(doc["storage_path"])
    content_type = doc.get("content_type") or "application/octet-stream"
    is_image = content_type.startswith("image/")

    result: dict = {}
    media_id = await _wa_upload_media(pdf_bytes=data, filename=filename, content_type=content_type)
    if media_id:
        if is_image:
            result = await send_whatsapp_image(to_phone=phone, media_id=media_id, caption=caption)
        else:
            result = await send_whatsapp_document(to_phone=phone, media_id=media_id, filename=filename, caption=caption)
    if not result.get("ok"):
        url = await presigned_url(doc["storage_path"], expires_in=604800)
        if url:
            fallback_msg = f"{caption}\n\nTéléchargement (lien sécurisé, 7 jours) :\n{url}"
            result = await send_whatsapp(to_phone=phone, message=fallback_msg)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp ({result.get('error') or result.get('kind') or 'inconnu'})")

    await db.documents.update_one(
        {"id": document_id},
        {"$set": {
            "wa_sent_at": datetime.now(timezone.utc).isoformat(),
            "wa_sent_to": phone,
            "wa_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": result.get("message_id"), "to": phone}
