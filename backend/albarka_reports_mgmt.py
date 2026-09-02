"""Numérotation, stockage et envoi de rapports client.

Séquence : `{prefix}-{CLIENT_SLUG}-{TYPE}-{YYYYMM}-NNNN` (compteur spécifique à
la triplette client+type+mois). Ex : `RAP-SAWADOG-MENSUEL-202602-0001`.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_staff
from albarka_models import is_client, tenant_id_of
from albarka_notifications import send_email
from albarka_reports import build_client_report_pdf
from albarka_storage import get_object, put_object, presigned_url, guess_content_type
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.reports_mgmt")

router = APIRouter(prefix="/reports", tags=["Rapports client"])

REPORT_TYPES = {
    "mensuel": "Rapport mensuel",
    "trimestriel": "Rapport trimestriel",
    "annuel": "Rapport annuel",
    "audit": "Rapport d'audit",
    "conseil": "Note de conseil",
    "ponctuel": "Rapport ponctuel",
}


def _client_slug(full_name: str, tenant_id: str) -> str:
    """Deterministic per-client slug: 7 first alpha chars + 4-char discriminator
    derived from the tenant_id. Guarantees uniqueness even when full_names collide."""
    import hashlib
    letters = re.sub(r"[^A-Za-z]", "", (full_name or "").upper())[:7] or "CLIENT"
    disc = hashlib.sha1((tenant_id or "").encode("utf-8")).hexdigest()[:4].upper()
    return f"{letters}{disc}"


async def _next_number(*, tenant_id: str, kind: str, month_key: str) -> int:
    """Atomically increments the (tenant, type, month) counter and returns the new value."""
    key = f"{tenant_id}:{kind}:{month_key}"
    res = await db.report_series.find_one_and_update(
        {"key": key},
        {"$inc": {"seq": 1},
         "$setOnInsert": {"tenant_id": tenant_id, "kind": kind, "month_key": month_key,
                          "created_at": datetime.now(timezone.utc).isoformat()}},
        upsert=True, return_document=True,
    )
    return int(res.get("seq") or 1)


class GenerateReportPayload(BaseModel):
    kind: str = Field(..., description="Type de rapport : mensuel/trimestriel/…")
    period_month: Optional[str] = Field(None, description="YYYY-MM ; défaut = mois courant")

    def resolved_kind(self) -> str:
        if self.kind not in REPORT_TYPES:
            raise ValueError(f"Type inconnu : {self.kind}. Attendu : {list(REPORT_TYPES)}")
        return self.kind


async def _load_report_data(tenant_id: str):
    client = await db.users.find_one({"id": tenant_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    missions = await db.missions.find({"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    echeances = await db.echeances.find({"tenant_id": tenant_id}, {"_id": 0}).sort("due_date", 1).to_list(500)
    documents = await db.documents.find({"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    syntheses = await db.document_syntheses.find(
        {"document_id": {"$in": [d["id"] for d in documents]}}, {"_id": 0},
    ).to_list(500)
    return client, missions, echeances, documents, {s["document_id"]: s for s in syntheses}


@router.post("/client/{tenant_id}/generate")
async def generate_report(
    tenant_id: str, payload: GenerateReportPayload, user: dict = Depends(require_staff()),
):
    """Génère un rapport PDF, l'archive sur R2 (ou local) et enregistre la trace."""
    try:
        kind = payload.resolved_kind()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    now = datetime.now(timezone.utc)
    month_key = payload.period_month or now.strftime("%Y-%m")
    if not re.match(r"^\d{4}-\d{2}$", month_key):
        raise HTTPException(status_code=400, detail="period_month attendu au format YYYY-MM")

    client, missions, echeances, documents, syntheses = await _load_report_data(tenant_id)
    settings = await get_settings_doc()

    seq = await _next_number(tenant_id=tenant_id, kind=kind, month_key=month_key)
    prefix = (settings.get("report_prefix") or "RAP").strip() or "RAP"
    number = f"{prefix}-{_client_slug(client.get('full_name'), tenant_id)}-{kind.upper()}-{month_key.replace('-', '')}-{seq:04d}"

    pdf_bytes = build_client_report_pdf(
        client=client, missions=missions, echeances=echeances,
        documents=documents, syntheses_by_doc=syntheses,
        header_number=number, report_kind_label=REPORT_TYPES[kind], month_key=month_key,
    )

    storage_path = f"albarka/{tenant_id}/reports/{month_key}/{number}.pdf"
    await put_object(storage_path, pdf_bytes, "application/pdf")

    report_id = secrets.token_urlsafe(12)
    doc = {
        "id": report_id,
        "number": number,
        "tenant_id": tenant_id,
        "kind": kind,
        "kind_label": REPORT_TYPES[kind],
        "month_key": month_key,
        "storage_path": storage_path,
        "size": len(pdf_bytes),
        "generated_by": user["id"],
        "generated_at": now.isoformat(),
        "signed": False,
        "signed_at": None,
        "signed_by": None,
        "email_sent_at": None,
        "email_sent_to": None,
    }
    await db.client_reports.insert_one(doc.copy())
    return serialize(doc)


@router.get("/client/{tenant_id}/list")
async def list_reports(
    tenant_id: str,
    month_key: Optional[str] = None,
    kind: Optional[str] = None,
    user: dict = Depends(get_current_user),
):
    if is_client(user) and tenant_id_of(user) != tenant_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    query = {"tenant_id": tenant_id}
    if month_key: query["month_key"] = month_key
    if kind: query["kind"] = kind
    items = await db.client_reports.find(query, {"_id": 0}).sort("generated_at", -1).to_list(500)
    return serialize_many(items)


async def _fetch_report(report_id: str, user: dict) -> dict:
    r = await db.client_reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    if is_client(user) and r["tenant_id"] != tenant_id_of(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return r


@router.get("/{report_id}/download")
async def download_report(report_id: str, user: dict = Depends(get_current_user)):
    from fastapi.responses import Response
    r = await _fetch_report(report_id, user)
    data, _ = await get_object(r["storage_path"])
    filename = f"{r['number']}.pdf"
    return Response(
        content=data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class SendReportPayload(BaseModel):
    to: Optional[str] = None  # override recipient; default = client email
    subject: Optional[str] = None
    message: Optional[str] = None


@router.post("/{report_id}/send")
async def send_report_email(
    report_id: str, payload: SendReportPayload, user: dict = Depends(require_staff()),
):
    """Envoie le rapport PDF au client par email (avec pièce jointe base64)."""
    r = await _fetch_report(report_id, user)
    client = await db.users.find_one({"id": r["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    if client.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Compte client inactif")

    to = (payload.to or client.get("email") or "").strip()
    if not to:
        raise HTTPException(status_code=400, detail="Aucun email de destination")

    settings = await get_settings_doc()
    cabinet_name = (settings.get("cabinet_name") or "Cabinet ALBARKA").strip()
    subject = payload.subject or f"{r['kind_label']} — {r['number']}"
    body_text = payload.message or (
        f"Bonjour {client.get('full_name', '')},\n\n"
        f"Veuillez trouver ci-joint votre {r['kind_label'].lower()} référencé {r['number']} "
        f"pour la période {r['month_key']}.\n\nCordialement,\n{cabinet_name}"
    )
    body_html = f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;padding:16px;">
  <p>Bonjour {escape(client.get('full_name', ''))},</p>
  <p>Veuillez trouver ci-joint votre <strong>{escape(r['kind_label'].lower())}</strong>
     référencé <strong>{escape(r['number'])}</strong> pour la période
     <strong>{escape(r['month_key'])}</strong>.</p>
  <p>Ce document est archivé dans votre espace client sur le portail
     {escape(cabinet_name)}.</p>
  <p style="margin-top:20px;">Cordialement,<br/>{escape(cabinet_name)}</p>
</div>
"""

    # Send via Emergent Resend proxy with attachment.
    import base64
    import os
    import httpx
    email_key = os.environ.get("EMERGENT_EMAIL_KEY", "")
    if not email_key:
        raise HTTPException(status_code=500, detail="EMERGENT_EMAIL_KEY absent")

    pdf_bytes, _ = await get_object(r["storage_path"])
    attachment_payload = {
        "filename": f"{r['number']}.pdf",
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
        "content_type": "application/pdf",
    }
    payload_json = {
        "to": [to],
        "subject": subject,
        "html": body_html,
        "text": body_text,
        "from_name": cabinet_name,
        "attachments": [attachment_payload],
    }
    try:
        async with httpx.AsyncClient(timeout=45) as http:
            resp = await http.post(
                "https://integrations.emergentagent.com/api/v1/email/send",
                headers={"X-Email-Key": email_key},
                json=payload_json,
            )
        resp.raise_for_status()
        message_id = resp.json().get("id")
    except httpx.HTTPStatusError as exc:
        detail = f"{exc.response.status_code} — {exc.response.text[:300]}"
        raise HTTPException(status_code=502, detail=f"Proxy email : {detail}")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur d'envoi : {exc}")

    await db.client_reports.update_one(
        {"id": report_id},
        {"$set": {
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_to": to,
            "email_message_id": message_id,
            "email_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": message_id, "to": to}


class SignReportPayload(BaseModel):
    signature_name: str = Field(..., min_length=2, max_length=200)
    signature_provider: Optional[str] = Field(None, max_length=100)  # ex "docusign", "dropbox_sign", "cabinet_seal"
    signature_reference: Optional[str] = Field(None, max_length=200)  # id externe


@router.post("/{report_id}/sign")
async def sign_report(
    report_id: str, payload: SignReportPayload, user: dict = Depends(require_staff()),
):
    """Marque le rapport comme signé. Câblage : conserve la référence du service
    de signature (déjà implémenté côté cabinet — à connecter au moment voulu)."""
    r = await _fetch_report(report_id, user)
    if r.get("signed"):
        raise HTTPException(status_code=400, detail="Rapport déjà signé")
    await db.client_reports.update_one(
        {"id": report_id},
        {"$set": {
            "signed": True,
            "signed_at": datetime.now(timezone.utc).isoformat(),
            "signed_by": user["id"],
            "signature_name": payload.signature_name,
            "signature_provider": payload.signature_provider,
            "signature_reference": payload.signature_reference,
        }},
    )
    updated = await db.client_reports.find_one({"id": report_id}, {"_id": 0})
    return serialize(updated)


@router.delete("/{report_id}")
async def delete_report(report_id: str, user: dict = Depends(require_staff())):
    r = await db.client_reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    if r.get("signed"):
        raise HTTPException(status_code=400, detail="Impossible de supprimer un rapport signé")
    # Best-effort: remove the archived PDF from storage.
    from albarka_storage import delete_object
    try:
        await delete_object(r["storage_path"])
    except Exception:
        logger.exception("Suppression du fichier %s échouée (poursuite)", r.get("storage_path"))
    await db.client_reports.delete_one({"id": report_id})
    return {"ok": True, "id": report_id}
