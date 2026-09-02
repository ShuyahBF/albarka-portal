"""Modèles de rapports — sélectionner sections et paramètres du PDF généré.

Un `report_template` a des toggles/params qui pilotent `build_client_report_pdf`.
Sinon, un template *par défaut* est appliqué (toutes sections).
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import require_staff
from db import db, serialize, serialize_many

router = APIRouter(prefix="/report-templates", tags=["Modèles de rapports"])

REPORT_KINDS_TPL = ["mensuel", "trimestriel", "annuel", "audit", "conseil", "ponctuel"]


class TemplateCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: Optional[str] = None
    default_kind: str = "mensuel"
    # Sections
    include_kpis: bool = True
    include_missions: bool = True
    include_echeances: bool = True
    include_documents: bool = True
    include_ai_syntheses: bool = True
    # Étendues
    only_status_open: bool = False  # missions/échéances : garder que celles ouvertes
    intro_paragraph: Optional[str] = None
    conclusion_paragraph: Optional[str] = None
    is_default: bool = False


class TemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    default_kind: Optional[str] = None
    include_kpis: Optional[bool] = None
    include_missions: Optional[bool] = None
    include_echeances: Optional[bool] = None
    include_documents: Optional[bool] = None
    include_ai_syntheses: Optional[bool] = None
    only_status_open: Optional[bool] = None
    intro_paragraph: Optional[str] = None
    conclusion_paragraph: Optional[str] = None
    is_default: Optional[bool] = None


async def _demote_other_defaults(keep_id: Optional[str] = None):
    q = {"is_default": True}
    if keep_id: q["id"] = {"$ne": keep_id}
    await db.report_templates.update_many(q, {"$set": {"is_default": False}})


@router.get("")
async def list_templates(user: dict = Depends(require_staff())):
    items = await db.report_templates.find({}, {"_id": 0}).sort([("is_default", -1), ("name", 1)]).to_list(200)
    return serialize_many(items)


@router.post("")
async def create_template(payload: TemplateCreate, user: dict = Depends(require_staff())):
    if payload.default_kind not in REPORT_KINDS_TPL:
        raise HTTPException(status_code=400, detail=f"default_kind invalide : {payload.default_kind}")
    doc = payload.model_dump()
    doc["id"] = secrets.token_urlsafe(12)
    doc["created_at"] = datetime.now(timezone.utc).isoformat()
    doc["updated_at"] = doc["created_at"]
    doc["created_by"] = user["id"]
    if doc["is_default"]:
        await _demote_other_defaults()
    await db.report_templates.insert_one(doc.copy())
    return serialize(doc)


@router.patch("/{template_id}")
async def update_template(template_id: str, payload: TemplateUpdate, user: dict = Depends(require_staff())):
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if "default_kind" in changes and changes["default_kind"] not in REPORT_KINDS_TPL:
        raise HTTPException(status_code=400, detail="default_kind invalide")
    if not changes:
        raise HTTPException(status_code=400, detail="Aucun champ à mettre à jour")
    if changes.get("is_default") is True:
        await _demote_other_defaults(keep_id=template_id)
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.report_templates.update_one({"id": template_id}, {"$set": changes})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    updated = await db.report_templates.find_one({"id": template_id}, {"_id": 0})
    return serialize(updated)


@router.delete("/{template_id}")
async def delete_template(template_id: str, user: dict = Depends(require_staff())):
    res = await db.report_templates.delete_one({"id": template_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return {"ok": True, "id": template_id}


async def get_template(template_id: Optional[str]) -> Optional[dict]:
    """Loads a specific template, or the default one if template_id is None."""
    if template_id:
        return await db.report_templates.find_one({"id": template_id}, {"_id": 0})
    return await db.report_templates.find_one({"is_default": True}, {"_id": 0})
