"""Stockage de pièces — Cloudflare R2 si configuré, sinon local fallback.

Env vars requises pour R2 (mode production) :
    R2_ENDPOINT, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME

Sans ces variables, on stocke localement dans `UPLOAD_DIR` (défaut :
`/app/backend/uploads`) et on sert les téléchargements via un endpoint FastAPI.
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("albarka.storage")

APP_PREFIX = "albarka"
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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


def build_path(kind: str, tenant_id: str, ext: str = "bin") -> str:
    safe_tenant = (tenant_id or "_global").replace("/", "_")
    safe_kind = (kind or "misc").replace("/", "_")
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    ext = (ext or "bin").lstrip(".").lower() or "bin"
    uid = uuid.uuid4().hex[:16]
    return f"{APP_PREFIX}/{safe_tenant}/{safe_kind}/{ym}/{uid}.{ext}"


def _r2_configured() -> bool:
    return all(os.environ.get(k) for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"))


_r2_client = None


def _get_r2_client():
    global _r2_client
    if _r2_client is not None:
        return _r2_client
    import boto3
    from botocore.client import Config
    _r2_client = boto3.client(
        "s3",
        endpoint_url=os.environ["R2_ENDPOINT"],
        aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )
    return _r2_client


# ---------- R2 sync helpers wrapped for async callers ----------
def _r2_put_sync(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    _get_r2_client().put_object(
        Bucket=os.environ["R2_BUCKET_NAME"], Key=path, Body=data, ContentType=content_type,
    )
    return {"path": path, "size": len(data)}


def _r2_get_sync(path: str) -> Tuple[bytes, str]:
    obj = _get_r2_client().get_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=path)
    return obj["Body"].read(), obj.get("ContentType", "application/octet-stream")


def _r2_presign_sync(path: str, expires_in: int) -> str:
    return _get_r2_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": os.environ["R2_BUCKET_NAME"], "Key": path},
        ExpiresIn=expires_in,
    )


# ---------- Local storage ----------
def _local_put_sync(path: str, data: bytes) -> Dict[str, Any]:
    full = UPLOAD_DIR / path
    full.parent.mkdir(parents=True, exist_ok=True)
    with open(full, "wb") as f:
        f.write(data)
    return {"path": path, "size": len(data)}


def _local_get_sync(path: str) -> bytes:
    full = UPLOAD_DIR / path
    if not full.exists():
        raise FileNotFoundError(f"Fichier introuvable : {path}")
    with open(full, "rb") as f:
        return f.read()


# ---------- Public async API ----------
async def put_object(path: str, data: bytes, content_type: str) -> Dict[str, Any]:
    if _r2_configured():
        return await asyncio.to_thread(_r2_put_sync, path, data, content_type)
    return await asyncio.to_thread(_local_put_sync, path, data)


async def get_object(path: str) -> Tuple[bytes, str]:
    if _r2_configured():
        return await asyncio.to_thread(_r2_get_sync, path)
    data = await asyncio.to_thread(_local_get_sync, path)
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return data, guess_content_type(ext)


async def presigned_url(path: str, expires_in: int = 300) -> Optional[str]:
    """Returns a signed URL when using R2; None when local (caller falls back to
    an authenticated download endpoint)."""
    if _r2_configured():
        return await asyncio.to_thread(_r2_presign_sync, path, expires_in)
    return None


def _r2_delete_sync(path: str) -> None:
    _get_r2_client().delete_object(Bucket=os.environ["R2_BUCKET_NAME"], Key=path)


def _local_delete_sync(path: str) -> None:
    full = UPLOAD_DIR / path
    if full.exists():
        full.unlink()


async def delete_object(path: str) -> None:
    if _r2_configured():
        await asyncio.to_thread(_r2_delete_sync, path)
    else:
        await asyncio.to_thread(_local_delete_sync, path)


def storage_mode() -> str:
    return "r2" if _r2_configured() else "local"


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
) -> Dict[str, Any]:
    ct = content_type or guess_content_type(original_filename or ext)
    path = build_path(kind, tenant_id, ext)
    await put_object(path, data, ct)
    rec_id = secrets.token_urlsafe(12)
    doc = {
        "id": rec_id,
        "storage_path": path,
        "storage_mode": storage_mode(),
        "kind": kind,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "original_filename": original_filename,
        "content_type": ct,
        "size": len(data),
        "is_deleted": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.stored_objects.insert_one(doc.copy())
    return {"id": rec_id, "path": path, "size": len(data), "content_type": ct}
