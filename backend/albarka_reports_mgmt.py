"""Numérotation, stockage et envoi de rapports client.

Séquence : `{prefix}-{CLIENT_SLUG}-{TYPE}-{YYYYMM}-NNNN` (compteur spécifique à
la triplette client+type+mois). Ex : `RAP-SAWADOG-MENSUEL-202602-0001`.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_staff
from albarka_branding import load_branding_images as _load_branding
from albarka_models import is_client, tenant_id_of
from albarka_notifications import send_email
from albarka_report_templates import get_template
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
    template_id: Optional[str] = None

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


@router.post("/client/{tenant_id}/preview")
async def preview_report(
    tenant_id: str, payload: GenerateReportPayload,
    user: dict = Depends(require_staff()),
):
    """Génère un rapport PDF SANS le persister et renvoie la 1re page en PNG.

    Utile pour visualiser l'effet d'un modèle avant génération réelle.
    """
    from fastapi.responses import Response
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
    prefix = (settings.get("report_prefix") or "RAP").strip() or "RAP"
    number = f"{prefix}-PREVIEW-{kind.upper()}-{month_key.replace('-', '')}-XXXX"
    pdf_bytes = build_client_report_pdf(
        client=client, missions=missions, echeances=echeances,
        documents=documents, syntheses_by_doc=syntheses,
        header_number=number, report_kind_label=REPORT_TYPES[kind], month_key=month_key,
        template=await get_template(payload.template_id),
        branding=await _load_branding(),
    )
    # Render page 0 as PNG (~150 dpi keeps the preview crisp yet under ~200KB)
    import io as _io
    import fitz  # PyMuPDF
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        pix = doc[0].get_pixmap(dpi=140)
        png_bytes = pix.tobytes("png")
    finally:
        doc.close()
    return Response(
        content=png_bytes, media_type="image/png",
        headers={"X-Report-Preview": "1", "Cache-Control": "no-store"},
    )


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
        template=await get_template(payload.template_id),
        branding=await _load_branding(),
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
    to: Optional[str] = None
    to_contacts: Optional[list[str]] = None
    to_groups: Optional[list[str]] = None
    subject: Optional[str] = None
    message: Optional[str] = None


class SendReportWhatsAppPayload(BaseModel):
    to: Optional[str] = None
    to_contacts: Optional[list[str]] = None
    to_groups: Optional[list[str]] = None
    all_whatsapp_contacts: bool = False
    message: Optional[str] = None
    scheduled_at: Optional[str] = None  # ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`)


def _make_share_token(report_id: str, ttl_seconds: int = 604800) -> str:
    """Sign a short-lived JWT to download a report without authentication."""
    from jose import jwt as _jwt
    payload = {
        "sub": f"report:{report_id}",
        "exp": datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
    }
    return _jwt.encode(payload, os.environ["JWT_SECRET_KEY"], algorithm="HS256")


@router.get("/download/shared/{token}")
async def download_report_shared(token: str):
    """Public authenticated-by-token download (used in WhatsApp fallback links)."""
    from fastapi.responses import Response
    from jose import JWTError, jwt as _jwt
    try:
        payload = _jwt.decode(token, os.environ["JWT_SECRET_KEY"], algorithms=["HS256"])
        subj = payload.get("sub") or ""
        if not subj.startswith("report:"):
            raise ValueError("bad-subject")
        report_id = subj.split(":", 1)[1]
    except (JWTError, ValueError):
        raise HTTPException(status_code=403, detail="Lien invalide ou expiré")
    r = await db.client_reports.find_one({"id": report_id}, {"_id": 0})
    if not r:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    data, _ = await get_object(r["storage_path"])
    filename = f"{r['number']}.pdf"
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{report_id}/send")
async def send_report_email(
    report_id: str, payload: SendReportPayload, user: dict = Depends(require_staff()),
):
    """Envoie le rapport PDF au client par email (via `send_email` avec guardrails).

    Routing:
      - `to` fourni  → destinataire unique
      - `to_contacts` fourni → destinataires = contacts avec `can_receive_notifications`
      - Sinon → email du compte client
    """
    import base64
    r = await _fetch_report(report_id, user)
    client = await db.users.find_one({"id": r["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    if client.get("is_active") is False:
        raise HTTPException(status_code=400, detail="Compte client inactif")

    recipients: list[str] = []
    if payload.to:
        recipients = [payload.to.strip()]
    elif payload.to_contacts or payload.to_groups:
        from albarka_contact_groups import emails_of_group
        collected: set[str] = set()
        if payload.to_contacts:
            contacts = await db.contacts.find(
                {"id": {"$in": payload.to_contacts}, "tenant_id": r["tenant_id"], "is_active": True},
                {"_id": 0},
            ).to_list(200)
            for c in contacts:
                if c.get("email") and c.get("can_receive_notifications", True) \
                        and "email" in (c.get("channels") or ["email"]):
                    collected.add(c["email"])
        if payload.to_groups:
            groups = await db.contact_groups.find(
                {"id": {"$in": payload.to_groups}, "tenant_id": r["tenant_id"]},
                {"_id": 0, "id": 1},
            ).to_list(50)
            for g in groups:
                for e in await emails_of_group(g["id"]):
                    collected.add(e)
        recipients = sorted(collected)
    else:
        if client.get("email"):
            recipients = [client["email"]]
    if not recipients:
        raise HTTPException(status_code=400, detail="Aucun destinataire éligible")

    settings = await get_settings_doc()
    cabinet_name = (settings.get("cabinet_name") or "Cabinet ALBARKA").strip()
    subject = payload.subject or f"{r['kind_label']} — {r['number']}"
    msg_body = payload.message or ""
    from html import escape as _esc
    client_label = _esc(client.get('company') or client.get('full_name', ''))
    html = f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;padding:16px;">
  <p>Bonjour,</p>
  <p>Veuillez trouver ci-joint le <strong>{_esc(r['kind_label'].lower())}</strong>
     référencé <strong>{_esc(r['number'])}</strong> pour la période
     <strong>{_esc(r['month_key'])}</strong> — client
     <strong>{client_label}</strong>.</p>
  {"<p>" + _esc(msg_body).replace(chr(10), '<br/>') + "</p>" if msg_body else ""}
  <p style="margin-top:20px;">Cordialement,<br/>{_esc(cabinet_name)}</p>
</div>
"""
    pdf_bytes, _ = await get_object(r["storage_path"])
    attachment = {
        "filename": f"{r['number']}.pdf",
        "content": base64.b64encode(pdf_bytes).decode("ascii"),
        "content_type": "application/pdf",
    }
    message_id = await send_email(
        to=recipients, subject=subject, html=html,
        attachments=[attachment],
    )
    if not message_id:
        raise HTTPException(status_code=502, detail="Échec envoi email (proxy indisponible ou rejeté)")

    await db.client_reports.update_one(
        {"id": report_id},
        {"$set": {
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_to": ", ".join(recipients),
            "email_message_id": message_id,
            "email_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": message_id, "to": recipients}


@router.post("/{report_id}/send-whatsapp")
async def send_report_whatsapp(
    report_id: str, payload: SendReportWhatsAppPayload,
    user: dict = Depends(require_staff()),
):
    """Envoie le rapport PDF par WhatsApp.

    Si `scheduled_at` est fourni (ISO UTC futur), la demande est enregistrée dans
    `scheduled_wa_sends` — le job cron `/cron/dispatch-scheduled-wa` la traitera.
    Sinon, envoie immédiatement.

    Stratégie d'envoi immédiat : upload PDF via Meta Media API + envoi comme
    document. Fallback → texte + lien signé 7 jours en cas d'échec.
    """
    r = await _fetch_report(report_id, user)

    # -------- Schedule for later --------
    if payload.scheduled_at:
        try:
            when = _parse_scheduled_at(payload.scheduled_at)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        entry = {
            "id": secrets.token_urlsafe(12),
            "report_id": report_id,
            "report_number": r["number"],
            "tenant_id": r["tenant_id"],
            "scheduled_at": when.isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": user["id"],
            "created_by_name": user.get("full_name") or user.get("email"),
            "status": "pending",
            "payload": payload.model_dump(exclude={"scheduled_at"}),
        }
        await db.scheduled_wa_sends.insert_one(dict(entry))
        return {"ok": True, "scheduled": True, "scheduled_at": when.isoformat(), "id": entry["id"]}

    # -------- Immediate send --------
    result = await _perform_wa_send(report=r, payload=payload, user=user)
    return result


def _parse_scheduled_at(raw: str) -> datetime:
    """Accept ISO 8601 strings (with or without `Z`) and reject past values."""
    s = raw.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError("Format attendu ISO 8601 UTC (ex. 2026-02-15T09:30:00Z)")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if dt <= now + timedelta(seconds=30):
        raise ValueError("La date planifiée doit être dans le futur (> 30s)")
    if dt > now + timedelta(days=365):
        raise ValueError("Planification maximum : 12 mois à l'avance")
    return dt


async def _perform_wa_send(*, report: dict, payload: SendReportWhatsAppPayload, user: dict):
    """Core send logic — extracted so the cron worker can reuse it."""
    client = await db.users.find_one({"id": report["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    phones: set[str] = set()
    if payload.to:
        phones.add(payload.to.strip())
    if payload.to_contacts:
        contacts = await db.contacts.find(
            {"id": {"$in": payload.to_contacts}, "tenant_id": report["tenant_id"], "is_active": True},
            {"_id": 0},
        ).to_list(200)
        for c in contacts:
            if c.get("phone") and c.get("can_receive_notifications", True) \
                    and "whatsapp" in (c.get("channels") or ["email"]):
                phones.add(c["phone"])
    if payload.to_groups:
        groups = await db.contact_groups.find(
            {"id": {"$in": payload.to_groups}, "tenant_id": report["tenant_id"]},
            {"_id": 0, "id": 1, "contact_ids": 1},
        ).to_list(50)
        member_ids: set[str] = set()
        for g in groups:
            for cid in (g.get("contact_ids") or []):
                member_ids.add(cid)
        if member_ids:
            contacts = await db.contacts.find(
                {"id": {"$in": list(member_ids)}, "is_active": True}, {"_id": 0},
            ).to_list(500)
            for c in contacts:
                if c.get("phone") and c.get("can_receive_notifications", True) \
                        and "whatsapp" in (c.get("channels") or ["email"]):
                    phones.add(c["phone"])
    if payload.all_whatsapp_contacts:
        all_contacts = await db.contacts.find(
            {"tenant_id": report["tenant_id"], "is_active": True},
            {"_id": 0, "phone": 1, "can_receive_notifications": 1, "channels": 1},
        ).to_list(1000)
        for c in all_contacts:
            if c.get("phone") and c.get("can_receive_notifications", True) \
                    and "whatsapp" in (c.get("channels") or ["email"]):
                phones.add(c["phone"])
    if not phones and client.get("phone"):
        phones.add(client["phone"])
    phones = {p for p in phones if p and p.startswith("+")}
    if not phones:
        raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp éligible (format +226…)")

    settings = await get_settings_doc()
    if not settings.get("wa_enabled"):
        raise HTTPException(status_code=400, detail="WhatsApp désactivé dans les paramètres")

    from albarka_notifications import (
        _wa_upload_media, send_whatsapp, send_whatsapp_document,
    )
    pdf_bytes, _ = await get_object(report["storage_path"])
    filename = f"{report['number']}.pdf"
    cabinet_name = (settings.get("cabinet_name") or "Cabinet ALBARKA").strip()
    caption_msg = (payload.message or "").strip() or (
        f"{report['kind_label']} — {report['number']}\nRéférence : {report['month_key']}\n\nCordialement, {cabinet_name}"
    )

    media_id = await _wa_upload_media(pdf_bytes=pdf_bytes, filename=filename)
    share_token = _make_share_token(report["id"])
    base_url = (os.environ.get("REACT_APP_BACKEND_URL") or "").rstrip("/")
    share_url = f"{base_url}/api/reports/download/shared/{share_token}"

    delivery = []
    for phone in sorted(phones):
        message_id = None
        strategy = None
        if media_id:
            message_id = await send_whatsapp_document(
                to_phone=phone, media_id=media_id, filename=filename, caption=caption_msg,
            )
            if message_id: strategy = "document"
        if not message_id:
            fallback_msg = f"{caption_msg}\n\nTéléchargement (lien sécurisé, 7 jours) :\n{share_url}"
            message_id = await send_whatsapp(to_phone=phone, message=fallback_msg)
            if message_id: strategy = "link"
        delivery.append({"phone": phone, "message_id": message_id, "strategy": strategy})

    delivered = [d for d in delivery if d["message_id"]]
    if not delivered:
        raise HTTPException(status_code=502, detail="Aucun message WhatsApp délivré — vérifier la config Meta")

    now_iso = datetime.now(timezone.utc).isoformat()
    log_docs = [
        {
            "id": secrets.token_urlsafe(12), "report_id": report["id"],
            "report_number": report["number"], "tenant_id": report["tenant_id"],
            "phone": d["phone"], "strategy": d["strategy"] or "unknown",
            "message_id": d["message_id"], "sent_at": now_iso,
            "sent_by": user["id"], "sent_by_name": user.get("full_name") or user.get("email"),
            "success": True,
        }
        for d in delivered
    ] + [
        {
            "id": secrets.token_urlsafe(12), "report_id": report["id"],
            "report_number": report["number"], "tenant_id": report["tenant_id"],
            "phone": d["phone"], "strategy": None, "message_id": None,
            "sent_at": now_iso, "sent_by": user["id"],
            "sent_by_name": user.get("full_name") or user.get("email"),
            "success": False,
        }
        for d in delivery if not d["message_id"]
    ]
    if log_docs:
        await db.wa_send_log.insert_many([dict(x) for x in log_docs])
    await db.client_reports.update_one(
        {"id": report["id"]},
        {"$set": {
            "wa_sent_at": now_iso,
            "wa_sent_to": ", ".join([d["phone"] for d in delivered]),
            "wa_sent_by": user["id"],
        }},
    )
    return {
        "ok": True,
        "sent": delivered,
        "failed": [d for d in delivery if not d["message_id"]],
    }


@router.get("/whatsapp/scheduled")
async def list_scheduled_wa(
    status: Optional[str] = None,
    tenant_id: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    q = {}
    if status: q["status"] = status
    if tenant_id: q["tenant_id"] = tenant_id
    items = await db.scheduled_wa_sends.find(q, {"_id": 0}).sort("scheduled_at", 1).to_list(500)
    return serialize_many(items)


@router.delete("/whatsapp/scheduled/{scheduled_id}")
async def cancel_scheduled_wa(scheduled_id: str, user: dict = Depends(require_staff())):
    entry = await db.scheduled_wa_sends.find_one({"id": scheduled_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Programmation introuvable")
    if entry["status"] != "pending":
        raise HTTPException(status_code=400, detail=f"Impossible d'annuler un envoi {entry['status']}")
    await db.scheduled_wa_sends.update_one(
        {"id": scheduled_id},
        {"$set": {
            "status": "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
            "cancelled_by": user["id"],
        }},
    )
    return {"ok": True, "id": scheduled_id}


@router.post("/cron/dispatch-scheduled-wa")
async def cron_dispatch_scheduled_wa(
    authorization: Optional[str] = Header(None),
    x_webhook_id: Optional[str] = Header(None),
):
    """Cron worker: exécute les envois WhatsApp planifiés dont l'heure est arrivée."""
    from albarka_reports_router import _verify_cron_auth
    _verify_cron_auth(authorization)
    if x_webhook_id:
        already = await db.cron_runs.find_one({"run_id": x_webhook_id})
        if already:
            return {"ok": True, "duplicate": True}
        await db.cron_runs.insert_one({
            "run_id": x_webhook_id,
            "job": "dispatch-scheduled-wa",
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
    now = datetime.now(timezone.utc).isoformat()
    pending = await db.scheduled_wa_sends.find(
        {"status": "pending", "scheduled_at": {"$lte": now}}, {"_id": 0},
    ).to_list(100)
    results = []
    for entry in pending:
        report = await db.client_reports.find_one({"id": entry["report_id"]}, {"_id": 0})
        if not report:
            await db.scheduled_wa_sends.update_one(
                {"id": entry["id"]},
                {"$set": {"status": "failed", "executed_at": now, "error": "Rapport introuvable"}},
            )
            results.append({"id": entry["id"], "status": "failed", "error": "report-missing"})
            continue
        creator = await db.users.find_one({"id": entry["created_by"]}, {"_id": 0, "password_hash": 0})
        if not creator:
            creator = {"id": entry["created_by"], "email": "cron@albarka", "full_name": "Cron worker"}
        payload = SendReportWhatsAppPayload(**(entry.get("payload") or {}))
        try:
            outcome = await _perform_wa_send(report=report, payload=payload, user=creator)
            await db.scheduled_wa_sends.update_one(
                {"id": entry["id"]},
                {"$set": {
                    "status": "sent",
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "result": {
                        "delivered": len(outcome.get("sent") or []),
                        "failed": len(outcome.get("failed") or []),
                    },
                }},
            )
            results.append({"id": entry["id"], "status": "sent",
                            "delivered": len(outcome.get("sent") or [])})
        except HTTPException as exc:
            await db.scheduled_wa_sends.update_one(
                {"id": entry["id"]},
                {"$set": {
                    "status": "failed",
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "error": f"{exc.status_code}: {exc.detail}",
                }},
            )
            results.append({"id": entry["id"], "status": "failed", "error": str(exc.detail)})
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cron WA dispatch error on %s", entry["id"])
            await db.scheduled_wa_sends.update_one(
                {"id": entry["id"]},
                {"$set": {
                    "status": "failed",
                    "executed_at": datetime.now(timezone.utc).isoformat(),
                    "error": str(exc)[:400],
                }},
            )
            results.append({"id": entry["id"], "status": "failed", "error": "internal"})
    return {"ok": True, "processed": len(results), "results": results}


# =====================================================================


@router.get("/whatsapp/log")
async def whatsapp_audit_log(
    tenant_id: Optional[str] = None,
    report_id: Optional[str] = None,
    success: Optional[bool] = None,
    limit: int = 200,
    user: dict = Depends(require_staff()),
):
    """Journal d'audit des envois WhatsApp — filtres client/rapport/statut."""
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if report_id: q["report_id"] = report_id
    if success is not None: q["success"] = success
    items = await db.wa_send_log.find(q, {"_id": 0}).sort("sent_at", -1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


# ===================================================================
# Point 4 — Export PDF Journal signatures + WhatsApp (archivage papier
# interne du cabinet, pas destiné au client final).
# ===================================================================
@router.get("/journal/export-pdf")
async def export_journal_pdf(
    start: Optional[str] = None,
    end: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    """Retourne un PDF tabulaire agrégeant signature_log + wa_send_log sur
    la période [start, end] (dates ISO YYYY-MM-DD). Sans borne, prend
    les 500 derniers événements de chaque source.
    """
    from fastapi.responses import Response
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    import io as _io

    def _range_q(field: str) -> dict:
        q: dict = {}
        if start or end:
            rng: dict = {}
            if start: rng["$gte"] = start
            if end:   rng["$lte"] = end + "T23:59:59Z"
            q[field] = rng
        return q

    sig_docs = await db.signature_log.find(
        _range_q("signed_at"), {"_id": 0},
    ).sort("signed_at", -1).to_list(500)
    wa_docs = await db.wa_send_log.find(
        _range_q("sent_at"), {"_id": 0},
    ).sort("sent_at", -1).to_list(500)

    rows_sig = [[
        (d.get("signed_at") or "")[:19].replace("T", " "),
        d.get("report_number") or "",
        d.get("tenant_id", "")[:10] + "…",
        "SIGNATURE",
        "signé",
        d.get("signed_by_name") or d.get("signed_by") or "—",
    ] for d in sig_docs]
    rows_wa = [[
        (d.get("sent_at") or "")[:19].replace("T", " "),
        d.get("report_number") or "",
        (d.get("tenant_id") or "")[:10] + "…",
        f"WHATSAPP {d.get('strategy','').upper() or ''}".strip(),
        "OK" if d.get("success") else "ECHEC",
        d.get("sent_by_name") or d.get("sent_by") or "—",
    ] for d in wa_docs]
    all_rows = sorted(rows_sig + rows_wa, key=lambda r: r[0], reverse=True)
    header = ["Date", "Rapport", "Client", "Action", "Statut", "Agent"]

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    end_label = end or "aujourd'hui"
    period_txt = f"{start or 'origine'} → {end_label}"
    story = [
        Paragraph("<b>Journal signatures &amp; WhatsApp</b>", styles["Title"]),
        Paragraph(
            f"Période : {period_txt} · "
            f"{len(rows_sig)} signatures + {len(rows_wa)} envois WhatsApp",
            styles["BodyText"],
        ),
        Spacer(1, 10),
    ]
    if not all_rows:
        story.append(Paragraph("<i>Aucun événement sur la période.</i>", styles["BodyText"]))
    else:
        t = Table([header] + all_rows, repeatRows=1,
                  colWidths=[110, 120, 90, 120, 60, 150])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B4A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
            ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.lightgrey),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.whitesmoke, colors.white]),
        ]))
        story.append(t)
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        f"<font size=7 color='#888'>Extrait le {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')} — {(user.get('full_name') or user.get('email'))}</font>",
        styles["BodyText"],
    ))
    doc.build(story)
    pdf = buf.getvalue()
    fname = f"journal_signatures_wa_{start or 'debut'}_{end or 'fin'}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


# ===================================================================
# Feature 1 (Phase B) — WhatsApp retry
# ===================================================================
@router.post("/whatsapp/retry/{log_id}")
async def whatsapp_retry(log_id: str, user: dict = Depends(require_staff())):
    """Re-tente l'envoi WhatsApp d'une entrée de journal en échec.

    Utilise la même stratégie que `_perform_wa_send` mais ciblée sur un
    unique numéro (celui du log d'origine).
    """
    entry = await db.wa_send_log.find_one({"id": log_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Entrée de journal introuvable")
    if entry.get("success"):
        raise HTTPException(status_code=400, detail="Cette entrée a déjà été envoyée avec succès")
    phone = entry.get("phone")
    if not phone or not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Numéro invalide dans l'entrée d'origine")
    report = await db.client_reports.find_one({"id": entry["report_id"]}, {"_id": 0})
    if not report:
        raise HTTPException(status_code=404, detail="Rapport introuvable")
    payload = SendReportWhatsAppPayload(to=phone)
    result = await _perform_wa_send(report=report, payload=payload, user=user)
    return {
        "ok": bool(result.get("sent")),
        "retried_log_id": log_id,
        "result": result,
    }


# ===================================================================
# Feature 2 (Phase B) — Bulk generate monthly reports
# ===================================================================
class BulkGeneratePayload(BaseModel):
    kind: str = Field("mensuel", description="Type — mensuel/trimestriel/annuel/…")
    period_month: Optional[str] = Field(None, description="YYYY-MM (mensuel/audit/…)")
    period_quarter: Optional[str] = Field(None, description="YYYY-Qn (trimestriel)")
    tenant_ids: Optional[list[str]] = Field(None, description="Sous-ensemble ; défaut = tous")
    template_id: Optional[str] = None


@router.post("/bulk-generate")
async def bulk_generate_reports(
    payload: BulkGeneratePayload, user: dict = Depends(require_staff()),
):
    """Génère un rapport pour chaque client (ou pour la liste fournie).

    Chaque échec est capturé et rapporté ; le job continue.
    """
    if payload.kind not in REPORT_TYPES:
        raise HTTPException(status_code=400, detail=f"Type inconnu : {payload.kind}")
    if payload.tenant_ids:
        clients = await db.users.find(
            {"id": {"$in": payload.tenant_ids}, "roles": "client"},
            {"_id": 0, "id": 1, "full_name": 1},
        ).to_list(500)
    else:
        clients = await db.users.find(
            {"roles": "client", "is_active": {"$ne": False}},
            {"_id": 0, "id": 1, "full_name": 1},
        ).to_list(500)
    generated: list[dict] = []
    failed: list[dict] = []
    for c in clients:
        try:
            gen_payload = GenerateReportPayload(
                kind=payload.kind,
                period_month=payload.period_month,
                template_id=payload.template_id,
            )
            report = await generate_report(
                tenant_id=c["id"], payload=gen_payload, user=user,
            )
            generated.append({
                "tenant_id": c["id"], "name": c.get("full_name"),
                "report_id": report["id"], "number": report["number"],
            })
        except HTTPException as exc:
            failed.append({
                "tenant_id": c["id"], "name": c.get("full_name"),
                "error": f"{exc.status_code}: {exc.detail}",
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bulk-generate error for %s", c.get("id"))
            failed.append({
                "tenant_id": c["id"], "name": c.get("full_name"),
                "error": str(exc)[:400],
            })
    return {
        "ok": True,
        "generated_count": len(generated),
        "failed_count": len(failed),
        "generated": generated,
        "failed": failed,
    }


# ===================================================================
# Feature 4 (Phase B) — Quarterly report export
# ===================================================================
class QuarterlyGeneratePayload(BaseModel):
    period_quarter: str = Field(..., description="YYYY-Qn (ex. 2026-Q1)")
    template_id: Optional[str] = None


def _quarter_months(period_quarter: str) -> list[str]:
    """`2026-Q1` -> ['2026-01', '2026-02', '2026-03']."""
    m = re.match(r"^(\d{4})-Q([1-4])$", period_quarter.strip())
    if not m:
        raise ValueError("period_quarter attendu au format YYYY-Qn (ex. 2026-Q1)")
    year = int(m.group(1))
    q = int(m.group(2))
    start = (q - 1) * 3 + 1
    return [f"{year:04d}-{start + i:02d}" for i in range(3)]


@router.post("/client/{tenant_id}/generate-quarterly")
async def generate_quarterly_report(
    tenant_id: str, payload: QuarterlyGeneratePayload,
    user: dict = Depends(require_staff()),
):
    """Génère un rapport trimestriel agrégeant les 3 mois du trimestre.

    Le PDF conserve la structure du rapport standard mais tape sur les
    données du trimestre entier. Le numéro utilise `Q1`/`Q2`/`Q3`/`Q4` comme
    clé de période.
    """
    try:
        months = _quarter_months(payload.period_quarter)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    client, missions, echeances, documents, syntheses = await _load_report_data(tenant_id)
    # Filtre trimestre : on garde les documents/missions/écheances dont
    # created_at (ou due_date) tombe dans les 3 mois du trimestre.
    prefix_set = tuple(months)  # (YYYY-MM, YYYY-MM, YYYY-MM)

    def _in_q(iso_or_date: Optional[str]) -> bool:
        if not iso_or_date:
            return False
        return str(iso_or_date)[:7] in prefix_set

    q_documents = [d for d in documents if _in_q(d.get("created_at"))]
    q_missions = [m for m in missions if _in_q(m.get("created_at")) or _in_q(m.get("due_date"))]
    q_echeances = [e for e in echeances if _in_q(e.get("due_date"))]

    settings = await get_settings_doc()
    period_key = payload.period_quarter.strip().upper()  # 2026-Q1
    month_key_for_series = period_key.replace("-Q", "-Q")  # keep same
    seq = await _next_number(tenant_id=tenant_id, kind="trimestriel", month_key=period_key)
    prefix = (settings.get("report_prefix") or "RAP").strip() or "RAP"
    number = f"{prefix}-{_client_slug(client.get('full_name'), tenant_id)}-TRIMESTRIEL-{period_key.replace('-', '')}-{seq:04d}"

    pdf_bytes = build_client_report_pdf(
        client=client, missions=q_missions, echeances=q_echeances,
        documents=q_documents, syntheses_by_doc=syntheses,
        header_number=number,
        report_kind_label=f"Rapport trimestriel — {period_key}",
        month_key=period_key,
        template=await get_template(payload.template_id),
        branding=await _load_branding(),
    )
    storage_path = f"albarka/{tenant_id}/reports/{period_key}/{number}.pdf"
    await put_object(storage_path, pdf_bytes, "application/pdf")
    report_id = secrets.token_urlsafe(12)
    doc = {
        "id": report_id, "number": number, "tenant_id": tenant_id,
        "kind": "trimestriel", "kind_label": f"Rapport trimestriel — {period_key}",
        "month_key": period_key, "period_quarter": period_key,
        "storage_path": storage_path, "size": len(pdf_bytes),
        "generated_by": user["id"],
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signed": False, "signed_at": None, "signed_by": None,
        "email_sent_at": None, "email_sent_to": None,
    }
    await db.client_reports.insert_one(doc.copy())
    return serialize(doc)


class SignReportPayload(BaseModel):
    signature_name: str = Field(..., min_length=2, max_length=200)
    signature_provider: Optional[str] = Field(None, max_length=100)
    signature_reference: Optional[str] = Field(None, max_length=200)


@router.post("/{report_id}/sign")
async def sign_report(
    report_id: str, payload: SignReportPayload, user: dict = Depends(require_staff()),
):
    """Signe le rapport (PAdES-B via pyHanko + sceau du cabinet).

    Config attendue dans `settings.cabinet_certificate` :
      { p12_path, passphrase_env, common_name, ... }
    Sinon retour d'erreur 400 avec instructions.
    """
    r = await _fetch_report(report_id, user)
    if r.get("signed"):
        raise HTTPException(status_code=400, detail="Rapport déjà signé")

    settings = await get_settings_doc()
    cert = settings.get("cabinet_certificate")
    from albarka_signing import resolve_passphrase, load_signer, sign_pdf_bytes
    passphrase = None
    if cert and cert.get("id"):
        passphrase = await resolve_passphrase(cert["id"])
    if cert and cert.get("p12_path") and passphrase:
        # --- Real cryptographic signing ---
        try:
            signer = load_signer(cert["p12_path"], passphrase)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Chargement certificat impossible : {exc}")
        pdf_bytes, _ = await get_object(r["storage_path"])
        # Load DG signature image (optional) for visible stamp
        branding = await _load_branding()
        dg_image_bytes = None
        if branding.get("dg_signature") and (branding.get("toggles") or {}).get("apply_dg_signature", True):
            dg_image_bytes = branding["dg_signature"]["bytes"]
        signed_at_iso = datetime.now(timezone.utc).isoformat()
        visible_stamp = {
            "cabinet_name": (settings.get("cabinet_name") or "Cabinet ALBARKA"),
            "signature_number": r["number"],
            "signer_name": payload.signature_name,
            "cert_common_name": cert.get("common_name") or "",
            "cert_serial": cert.get("serial_number") or "",
            "signed_at": signed_at_iso.replace("T", " ")[:19] + " UTC",
            "dg_image_bytes": dg_image_bytes,
        }
        try:
            import asyncio as _aio
            signed_bytes = await _aio.to_thread(
                sign_pdf_bytes, pdf_bytes,
                signer=signer,
                signature_name=payload.signature_name,
                reason=f"Sceau du cabinet — {r['number']}",
                location=settings.get("cabinet_address") or "",
                visible_stamp=visible_stamp,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"Signature PDF échouée : {exc}")
        # Overwrite storage path with signed bytes
        from albarka_storage import put_object
        await put_object(r["storage_path"], signed_bytes, "application/pdf")
        signature_meta = {
            "signature_provider": payload.signature_provider or "pyhanko_self_signed",
            "signature_reference": payload.signature_reference or cert.get("id"),
            "certificate_id": cert.get("id"),
            "certificate_serial": cert.get("serial_number"),
        }
    else:
        # --- Metadata-only signing (no cert configured) ---
        if payload.signature_provider is None:
            raise HTTPException(
                status_code=400,
                detail=("Aucun certificat cabinet configuré. Créez-en un via "
                        "POST /api/admin/settings/certificate ou fournissez un "
                        "signature_provider externe (docusign, cabinet_seal…)."),
            )
        signature_meta = {
            "signature_provider": payload.signature_provider,
            "signature_reference": payload.signature_reference,
        }

    await db.client_reports.update_one(
        {"id": report_id},
        {"$set": {
            "signed": True,
            "signed_at": datetime.now(timezone.utc).isoformat(),
            "signed_by": user["id"],
            "signature_name": payload.signature_name,
            **signature_meta,
        }},
    )
    # -------- Append audit log entry --------
    signed_at_log = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "id": secrets.token_urlsafe(12),
        "report_id": report_id,
        "report_number": r["number"],
        "tenant_id": r["tenant_id"],
        "signed_at": signed_at_log,
        "signed_by": user["id"],
        "signed_by_name": user.get("full_name") or user.get("email"),
        "signature_name": payload.signature_name,
        "signature_provider": signature_meta.get("signature_provider"),
        "certificate_id": signature_meta.get("certificate_id"),
        "certificate_serial": signature_meta.get("certificate_serial"),
    }
    await db.signature_log.insert_one(log_entry.copy())

    # Feature 3 (Phase B) — Auto WhatsApp send J+N after signing
    # `auto_wa_after_sign_days` est un nombre de jours entiers (24h chacun).
    if settings.get("auto_wa_after_sign_enabled"):
        try:
            days = int(settings.get("auto_wa_after_sign_days") or 1)
        except (TypeError, ValueError):
            days = 1
        if days > 0:
            # timedelta(days=1) == 24h pile — c'est bien "le lendemain de la signature".
            scheduled_at = datetime.now(timezone.utc) + timedelta(days=days)
            auto_entry = {
                "id": secrets.token_urlsafe(12),
                "report_id": report_id,
                "report_number": r["number"],
                "tenant_id": r["tenant_id"],
                "scheduled_at": scheduled_at.isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": user["id"],
                "created_by_name": user.get("full_name") or user.get("email"),
                "status": "pending",
                "payload": {"all_whatsapp_contacts": True},
                "auto": True,
                "auto_reason": f"J+{days} après signature",
            }
            await db.scheduled_wa_sends.insert_one(dict(auto_entry))
            logger.info(
                "Auto-WA planifié pour rapport %s à %s",
                r["number"], scheduled_at.isoformat(),
            )

    updated = await db.client_reports.find_one({"id": report_id}, {"_id": 0})
    # Point 2 — auto-archive du rapport signé.
    try:
        from albarka_phase_c import _auto_archive as _phase_c_archive
        await _phase_c_archive(
            title=f"Rapport signé {updated.get('number')} — {updated.get('kind_label') or updated.get('kind')}",
            category="rapports_signes",
            tags=[updated.get("kind"), updated.get("month_key") or "", "signe"],
            source={"kind": "signed_report", "id": report_id,
                    "tenant_id": updated["tenant_id"],
                    "storage_path": updated.get("storage_path_signed") or updated.get("storage_path")},
            user=user,
        )
    except Exception:  # noqa: BLE001
        pass  # best-effort
    return serialize(updated)


@router.get("/signatures/log")
async def signatures_audit_log(
    tenant_id: Optional[str] = None,
    certificate_id: Optional[str] = None,
    signed_by: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_staff()),
):
    """Journal d'audit des signatures — filtres client/certificat/agent."""
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if certificate_id: q["certificate_id"] = certificate_id
    if signed_by: q["signed_by"] = signed_by
    items = await db.signature_log.find(q, {"_id": 0}).sort("signed_at", -1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


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
