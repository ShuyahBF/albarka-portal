"""Branding cabinet — logo, papier à entête, signature DG, filigrane.

Ces éléments sont uploadés dans le stockage (R2 ou local) et référencés
depuis la collection `settings` (`branding` dict). Ils sont appliqués aux
rapports PDF générés (voir `albarka_reports.py`).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from albarka_auth import require_roles
from albarka_storage import delete_object, get_object, put_object
from db import db

logger = logging.getLogger("albarka.branding")

router = APIRouter(prefix="/admin/branding", tags=["Branding cabinet"])

_ADMIN_ROLES = ["superviseur", "direction", "administrateur"]
BRANDING_KINDS = {"logo", "letterhead", "dg_signature", "watermark"}
ALLOWED_MIMES = {"image/png", "image/jpeg", "image/webp"}
MAX_SIZE = 5 * 1024 * 1024  # 5 MB


def _ext_from(filename: str, content_type: str) -> str:
    name = (filename or "").lower()
    for ext in ("png", "jpg", "jpeg", "webp"):
        if name.endswith("." + ext):
            return "jpg" if ext == "jpeg" else ext
    if content_type == "image/png":
        return "png"
    if content_type == "image/webp":
        return "webp"
    return "jpg"


@router.get("")
async def get_branding(user: dict = Depends(require_roles(_ADMIN_ROLES))):
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    return settings.get("branding") or {}


@router.get("/{kind}/preview")
async def preview_branding(kind: str, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    """Return the raw image bytes for authenticated preview."""
    from fastapi.responses import Response
    if kind not in BRANDING_KINDS:
        raise HTTPException(status_code=400, detail=f"kind attendu : {sorted(BRANDING_KINDS)}")
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    entry = (settings.get("branding") or {}).get(kind)
    if not entry or not entry.get("path"):
        raise HTTPException(status_code=404, detail="Aucune image chargée pour ce type")
    data, ct = await get_object(entry["path"])
    return Response(content=data, media_type=ct or entry.get("content_type") or "image/png")


@router.post("/{kind}")
async def upload_branding(
    kind: str,
    file: UploadFile = File(...),
    user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    if kind not in BRANDING_KINDS:
        raise HTTPException(status_code=400, detail=f"kind attendu : {sorted(BRANDING_KINDS)}")
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(status_code=400, detail=f"Format non supporté ({file.content_type}). PNG / JPG / WEBP.")
    data = await file.read()
    if len(data) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (5 Mo max)")
    ext = _ext_from(file.filename or "", file.content_type or "")
    path = f"albarka/cabinet/branding/{kind}.{ext}"

    # Remove previous file if any (different extension).
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    branding = dict(settings.get("branding") or {})
    prev = branding.get(kind)
    if prev and prev.get("path") and prev["path"] != path:
        try:
            await delete_object(prev["path"])
        except Exception:
            logger.exception("Suppression ancien %s échouée (poursuite)", kind)

    await put_object(path, data, file.content_type)
    branding[kind] = {
        "path": path,
        "content_type": file.content_type,
        "size": len(data),
        "uploaded_by": user["id"],
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "original_filename": file.filename,
    }
    # Preserve toggle settings if present
    branding.setdefault("apply_watermark", True)
    branding.setdefault("apply_letterhead", False)
    branding.setdefault("apply_dg_signature", True)
    branding.setdefault("apply_logo", True)

    await db.settings.update_one(
        {"_id": "global"}, {"$set": {"branding": branding}}, upsert=True,
    )
    return branding


class BrandingToggles:
    keys = ("apply_watermark", "apply_letterhead", "apply_dg_signature", "apply_logo")


@router.put("/toggles")
async def update_toggles(
    payload: dict,
    user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    changes = {k: bool(payload.get(k)) for k in BrandingToggles.keys if k in payload}
    if not changes:
        raise HTTPException(status_code=400, detail="Aucun toggle fourni")
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    branding = dict(settings.get("branding") or {})
    branding.update(changes)
    await db.settings.update_one(
        {"_id": "global"}, {"$set": {"branding": branding}}, upsert=True,
    )
    return branding


@router.delete("/{kind}")
async def delete_branding(kind: str, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    if kind not in BRANDING_KINDS:
        raise HTTPException(status_code=400, detail=f"kind attendu : {sorted(BRANDING_KINDS)}")
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    branding = dict(settings.get("branding") or {})
    if kind in branding:
        prev = branding.pop(kind)
        if prev and prev.get("path"):
            try:
                await delete_object(prev["path"])
            except Exception:
                logger.exception("Suppression fichier branding échouée (poursuite)")
        await db.settings.update_one(
            {"_id": "global"}, {"$set": {"branding": branding}},
        )
    return branding


async def load_branding_images() -> dict:
    """Return dict {kind: (bytes, content_type)} for each configured branding image."""
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "branding": 1}) or {}
    branding = settings.get("branding") or {}
    result = {"toggles": {k: branding.get(k, True) for k in BrandingToggles.keys}}
    for kind in BRANDING_KINDS:
        entry = branding.get(kind)
        if not entry or not entry.get("path"):
            continue
        try:
            data, ct = await get_object(entry["path"])
            result[kind] = {"bytes": data, "content_type": ct or entry.get("content_type")}
        except Exception:
            logger.exception("Chargement branding %s échoué", kind)
    return result
