"""Cloudflare R2 object storage for ALBARKA.

R2 exposes an S3-compatible API, so we talk to it with boto3's "s3" client
pointed at the R2 endpoint — no Cloudflare-specific SDK needed.

Env vars required:
    R2_ENDPOINT            https://<account_id>.r2.cloudflarestorage.com
    R2_ACCESS_KEY_ID
    R2_SECRET_ACCESS_KEY
    R2_BUCKET_NAME

Public API (mirrors the shape used across the codebase so callers stay
familiar):
    put_object(path, data, content_type)      -> {"path", "size", "etag"}
    get_object(path)                          -> (bytes, content_type)
    save_and_log(db, ...)                     -> upload + record in `stored_objects`
    soft_delete(db, storage_path)             -> mark a stored_objects row deleted
    presigned_url(path, expires_in=300)       -> temporary signed download URL
    build_path(kind, tenant_id, ext, hint)    -> collision-proof storage key
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

logger = logging.getLogger("albarka.storage_r2")

APP_PREFIX = "albarka"

_client = None


def _get_client():
    global _client
    if _client is not None:
        return _client
    endpoint = os.environ["R2_ENDPOINT"]
    access_key = os.environ["R2_ACCESS_KEY_ID"]
    secret_key = os.environ["R2_SECRET_ACCESS_KEY"]
    _client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _client


def _bucket() -> str:
    return os.environ["R2_BUCKET_NAME"]


# ============================================================
# Path / MIME helpers
# ============================================================
MIME_FROM_EXT = {
    "jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
    "gif": "image/gif", "webp": "image/webp",
    "pdf": "application/pdf", "json": "application/json",
    "csv": "text/csv", "txt": "text/plain",
    "doc": "application/msword",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "xls": "application/vnd.ms-excel",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def guess_content_type(filename_or_ext: str, fallback: str = "application/octet-stream") -> str:
    s = (filename_or_ext or "").strip().lower()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    return MIME_FROM_EXT.get(s, fallback)


def build_path(kind: str, tenant_id: str, ext: str = "bin", filename_hint: Optional[str] = None) -> str:
    """Builds a collision-proof key: albarka/{tenant_id}/{kind}/{YYYY-MM}/{uuid}.{ext}

    `kind` groups objects by purpose (e.g. client_documents, kyc, payslips).
    `tenant_id` isolates each client's files from every other client's.
    """
    safe_tenant = (tenant_id or "_global").replace("/", "_")
    safe_kind = (kind or "misc").replace("/", "_")
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    ext = (ext or "bin").lstrip(".").lower() or "bin"
    uid = uuid.uuid4().hex[:16]
    return f"{APP_PREFIX}/{safe_tenant}/{safe_kind}/{ym}/{uid}.{ext}"


# ============================================================
# Put / Get (sync boto3 calls wrapped for async callers)
# ============================================================
def _put_sync(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    client = _get_client()
    client.put_object(Bucket=_bucket(), Key=path, Body=data, ContentType=content_type)
    return {"path": path, "size": len(data), "etag": ""}


def _get_sync(path: str) -> Tuple[bytes, str]:
    client = _get_client()
    try:
        obj = client.get_object(Bucket=_bucket(), Key=path)
    except ClientError as exc:
        raise FileNotFoundError(f"Objet introuvable sur R2 : {path}") from exc
    data = obj["Body"].read()
    content_type = obj.get("ContentType", "application/octet-stream")
    return data, content_type


def _delete_sync(path: str) -> None:
    client = _get_client()
    client.delete_object(Bucket=_bucket(), Key=path)


def _presigned_url_sync(path: str, expires_in: int) -> str:
    client = _get_client()
    return client.generate_presigned_url(
        "get_object",
        Params={"Bucket": _bucket(), "Key": path},
        ExpiresIn=expires_in,
    )


async def put_object(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    return await asyncio.to_thread(_put_sync, path, data, content_type)


async def get_object(path: str) -> Tuple[bytes, str]:
    return await asyncio.to_thread(_get_sync, path)


async def delete_object(path: str) -> None:
    await asyncio.to_thread(_delete_sync, path)


async def presigned_url(path: str, expires_in: int = 300) -> str:
    """Short-lived signed URL for secure direct download (default 5 min)."""
    return await asyncio.to_thread(_presigned_url_sync, path, expires_in)


# ============================================================
# DB-backed save (logs every upload so we can list / soft-delete / audit)
# ============================================================
async def save_and_log(
    db,
    *,
    data: bytes,
    kind: str,
    tenant_id: str,
    ext: str,
    content_type: Optional[str] = None,
    original_filename: Optional[str] = None,
    user_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Uploads `data` to R2 and logs the reference in `stored_objects`.

    Returns {"id", "path", "size", "content_type"} — no public `url` is
    returned since ALBARKA documents are sensitive: callers must go through
    `presigned_url()` (or a dedicated download-approval flow) to read them.
    """
    ct = content_type or guess_content_type(original_filename or ext)
    path = build_path(kind, tenant_id, ext, original_filename)
    result = await put_object(path, data, ct)
    rec_id = secrets.token_urlsafe(12)
    doc = {
        "id": rec_id,
        "storage_path": result["path"],
        "kind": kind,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "original_filename": original_filename,
        "content_type": ct,
        "size": result.get("size") or len(data),
        "metadata": metadata or {},
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.stored_objects.insert_one(doc.copy())
    return {
        "id": rec_id,
        "path": result["path"],
        "size": doc["size"],
        "content_type": ct,
    }


async def soft_delete(db, storage_path: str) -> bool:
    res = await db.stored_objects.update_one(
        {"storage_path": storage_path},
        {"$set": {"is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat()}},
    )
    return bool(res.modified_count)
