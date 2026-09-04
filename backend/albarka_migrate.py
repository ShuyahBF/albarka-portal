"""Réconciliation ponctuelle des bases MongoDB (Emergent-managée → Atlas).

Endpoint temporaire à exécuter DEPUIS le déploiement (qui a l'accès réseau à la
base source). Protégé par JWT superviseur + code de sécurité obligatoire.

À supprimer/désactiver une fois la réconciliation terminée.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorClient
from pydantic import BaseModel, Field

from albarka_auth import require_roles

logger = logging.getLogger("albarka.migrate")

router = APIRouter(prefix="/_admin/migrate-mongo", tags=["Migration Atlas (temporaire)"])

_ADMIN_ROLES = ["superviseur", "direction"]
_CONFIRM_TOKEN = os.environ.get("MIGRATE_CONFIRM_TOKEN", "MIGRATE-EMERGENT-TO-ATLAS-2026")
_PROTECT_EMAILS = {"admin@sawalismartsystems.com", "superviseur@albarka-demo.bf"}
_PROTECT_FIELDS = {"password_hash", "is_active"}
_REDACT_FIELDS_IN_BACKUP = {"password_hash"}
_EPHEMERAL_COLLECTIONS = {"otps", "cron_runs"}  # skipped by default (stale/regenerated)


def _serialize(doc):
    """Best-effort JSON serialisation of a Mongo document."""
    def _cast(v):
        if isinstance(v, ObjectId):
            return str(v)
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, list):
            return [_cast(x) for x in v]
        if isinstance(v, dict):
            return {k: _cast(vv) for k, vv in v.items()}
        return v
    return {k: _cast(v) for k, v in doc.items()}


class MigrateRequest(BaseModel):
    target_mongo_url: str = Field(..., min_length=20)
    target_db_name: str = Field(..., min_length=1)
    confirm_token: str = Field(..., min_length=5)
    dry_run: bool = False
    backup: bool = True
    backup_dir: Optional[str] = None
    only_collections: Optional[list[str]] = None
    skip_collections: Optional[list[str]] = None


@router.get("/inventory")
async def inventory_source(user: dict = Depends(require_roles(_ADMIN_ROLES))):
    """Inventaire de la base MongoDB actuellement connectée."""
    from db import db as _db, mongo_url as _mu
    import re as _re
    host_match = _re.search(r"@([^/?]+)", _mu)
    host = host_match.group(1) if host_match else "(unknown)"
    result = {"db_name": _db.name, "mongo_host": host, "collections": {}}
    for name in await _db.list_collection_names():
        count = await _db[name].estimated_document_count()
        result["collections"][name] = count
    # Detail users (email only, no secrets)
    users = await _db.users.find({}, {"_id": 0, "email": 1, "roles": 1, "is_active": 1,
                                       "full_name": 1}).to_list(500)
    result["users_preview"] = users
    return result


@router.post("")
async def migrate(payload: MigrateRequest,
                  user: dict = Depends(require_roles(_ADMIN_ROLES))):
    """Exécute la réconciliation (source = base actuelle, cible = payload)."""
    if payload.confirm_token != _CONFIRM_TOKEN:
        raise HTTPException(status_code=400, detail="confirm_token incorrect")
    from db import db as source_db, mongo_url as source_url
    if payload.target_mongo_url == source_url and payload.target_db_name == source_db.name:
        raise HTTPException(status_code=400, detail="La cible est identique à la source")

    started = time.time()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_dir = None
    if payload.backup and not payload.dry_run:
        # Default backup dir is /tmp (outside repo) — user can override via body
        backup_dir = Path(payload.backup_dir or f"/tmp/albarka-migrate-backups/mongo-{stamp}")
        backup_dir.mkdir(parents=True, exist_ok=True)

    target_client = AsyncIOMotorClient(payload.target_mongo_url, serverSelectionTimeoutMS=15000)
    try:
        # Verify target reachable
        try:
            await target_client.admin.command("ping")
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=502, detail=f"Cible injoignable : {exc}")
        target_db = target_client[payload.target_db_name]

        source_collections = sorted(await source_db.list_collection_names())
        if payload.only_collections:
            source_collections = [c for c in source_collections if c in payload.only_collections]
        else:
            # By default, skip ephemeral collections (OTPs, cron logs)
            source_collections = [c for c in source_collections if c not in _EPHEMERAL_COLLECTIONS]
        if payload.skip_collections:
            source_collections = [c for c in source_collections if c not in payload.skip_collections]
        report = {
            "started_at": datetime.now(timezone.utc).isoformat(),
            "source": {"db": source_db.name},
            "target": {"db": payload.target_db_name},
            "dry_run": payload.dry_run,
            "backup_dir": str(backup_dir) if backup_dir else None,
            "collections": {},
        }

        for name in source_collections:
            docs = await source_db[name].find({}).to_list(100_000)
            stats = {"total_source": len(docs), "inserted": 0, "updated": 0,
                     "skipped": 0, "protected_partial": 0, "errors": 0}

            # ---- Backup JSON dump (before touching target) ----
            if backup_dir:
                try:
                    dump = []
                    for d in docs:
                        s = _serialize(d)
                        # Redact sensitive fields in on-disk backups
                        for f in _REDACT_FIELDS_IN_BACKUP:
                            if f in s: s[f] = "[REDACTED]"
                        dump.append(s)
                    (backup_dir / f"{name}.json").write_text(
                        json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8",
                    )
                except Exception as exc:
                    logger.exception("Backup %s failed", name)
                    stats["backup_error"] = str(exc)[:200]

            if payload.dry_run:
                report["collections"][name] = stats
                continue

            # ---- Upsert into target ----
            for doc in docs:
                try:
                    doc.pop("_id", None)
                    if name == "users":
                        email = (doc.get("email") or "").strip().lower()
                        # Normalise email into a stable key
                        doc["email"] = email
                        existing = await target_db.users.find_one({"email": email}, {"_id": 0})
                        if email in _PROTECT_EMAILS and existing:
                            # Preserve corrected password_hash / is_active on target
                            preserved = {k: existing[k] for k in _PROTECT_FIELDS if k in existing}
                            merged = {**doc, **preserved}
                            res = await target_db.users.update_one(
                                {"email": email}, {"$set": merged},
                            )
                            stats["protected_partial"] += 1
                            if res.matched_count == 0:
                                stats["inserted"] += 1
                            elif res.modified_count:
                                stats["updated"] += 1
                            else:
                                stats["skipped"] += 1
                        else:
                            res = await target_db.users.update_one(
                                {"email": email}, {"$set": doc}, upsert=True,
                            )
                            if res.upserted_id:
                                stats["inserted"] += 1
                            elif res.modified_count:
                                stats["updated"] += 1
                            else:
                                stats["skipped"] += 1
                    else:
                        key_field = "id" if "id" in doc else None
                        if key_field:
                            res = await target_db[name].update_one(
                                {key_field: doc[key_field]}, {"$set": doc}, upsert=True,
                            )
                            if res.upserted_id: stats["inserted"] += 1
                            elif res.modified_count: stats["updated"] += 1
                            else: stats["skipped"] += 1
                        else:
                            # Fallback: full document uniqueness → skip if identical exists
                            if await target_db[name].find_one(doc):
                                stats["skipped"] += 1
                            else:
                                await target_db[name].insert_one(doc)
                                stats["inserted"] += 1
                except Exception as exc:
                    logger.exception("Migration doc failed in %s", name)
                    stats["errors"] += 1
                    stats.setdefault("error_samples", []).append(str(exc)[:200])
            report["collections"][name] = stats

        report["duration_seconds"] = round(time.time() - started, 2)
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        return report
    finally:
        target_client.close()
