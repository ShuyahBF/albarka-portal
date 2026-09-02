"""Endpoints pour rapports PDF client + notifications manuelles + cron webhook."""
from __future__ import annotations

import hmac
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Response

from albarka_auth import get_current_user, require_staff
from albarka_models import is_client, tenant_id_of
from albarka_notifications import notify_echeance
from albarka_reports import build_client_report_pdf
from db import db

logger = logging.getLogger("albarka.reports_router")

router = APIRouter(tags=["Rapports & notifications"])
WEBHOOK_SECRET = os.environ.get("WEBHOOK_CRON_SECRET", "")


async def _load_client_report_data(tenant_id: str):
    client = await db.users.find_one({"id": tenant_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    missions = await db.missions.find({"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    echeances = await db.echeances.find({"tenant_id": tenant_id}, {"_id": 0}).sort("due_date", 1).to_list(500)
    documents = await db.documents.find({"tenant_id": tenant_id}, {"_id": 0}).sort("created_at", -1).to_list(500)
    syntheses = await db.document_syntheses.find(
        {"document_id": {"$in": [d["id"] for d in documents]}}, {"_id": 0},
    ).to_list(500)
    syntheses_by_doc = {s["document_id"]: s for s in syntheses}
    return client, missions, echeances, documents, syntheses_by_doc


@router.get("/reports/client/{tenant_id}")
async def report_client_pdf(tenant_id: str, user: dict = Depends(get_current_user)):
    # Clients can download their own report; staff can download any.
    if is_client(user) and tenant_id_of(user) != tenant_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    client, missions, echeances, documents, syntheses = await _load_client_report_data(tenant_id)
    pdf = build_client_report_pdf(
        client=client, missions=missions, echeances=echeances,
        documents=documents, syntheses_by_doc=syntheses,
    )
    safe_name = (client.get("full_name") or "client").replace(" ", "_")
    filename = f"rapport-albarka-{safe_name}-{datetime.now(timezone.utc).strftime('%Y%m%d')}.pdf"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------- Manual test notification (staff-only, one shot) --------------
@router.post("/echeances/{echeance_id}/notify")
async def notify_echeance_manual(
    echeance_id: str, background: BackgroundTasks, user: dict = Depends(require_staff()),
):
    e = await db.echeances.find_one({"id": echeance_id}, {"_id": 0})
    if not e:
        raise HTTPException(status_code=404, detail="Échéance introuvable")
    client = await db.users.find_one({"id": e["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client de l'échéance introuvable")
    try:
        due = datetime.fromisoformat(e["due_date"])
    except Exception:
        due = datetime.now(timezone.utc)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    days_left = (due.date() - datetime.now(timezone.utc).date()).days
    background.add_task(notify_echeance, client, e, days_left)
    return {"ok": True, "queued": True, "days_left": days_left}


# ---------- Scheduled cron webhook ---------------------------------------
async def _run_daily_notifications() -> dict:
    """Envoie les rappels d'échéances J-7 et J-1 (email + WA)."""
    today = datetime.now(timezone.utc).date()
    targets = [(7, today + timedelta(days=7)), (1, today + timedelta(days=1))]
    stats = {"processed": 0, "email_sent": 0, "wa_sent": 0}
    for days_left, target_date in targets:
        target_str = target_date.isoformat()
        # Match échéances due exactly that day, still to be handled.
        query = {
            "due_date": {"$regex": f"^{target_str}"},
            "status": {"$in": ["a_venir", "en_cours", "en_retard"]},
        }
        echeances = await db.echeances.find(query, {"_id": 0}).to_list(1000)
        for e in echeances:
            client = await db.users.find_one({"id": e["tenant_id"]}, {"_id": 0, "password_hash": 0})
            if not client or not client.get("email"):
                continue
            # Dedup: skip if we already successfully sent for this echeance + days_left today
            dedup_key = f"{e['id']}:{days_left}:{today.isoformat()}"
            existing = await db.notification_log.find_one({"key": dedup_key})
            if existing:
                continue
            result = await notify_echeance(client, e, days_left)
            # Only write dedup row when at least one channel actually delivered,
            # so a transient email/proxy failure doesn't silently suppress the
            # reminder for the whole day (allowing next-tick retry).
            if result.get("sent_email") or result.get("sent_wa"):
                await db.notification_log.insert_one({
                    "key": dedup_key,
                    "tenant_id": e["tenant_id"],
                    "echeance_id": e["id"],
                    "days_left": days_left,
                    "email_id": result.get("email_id"),
                    "wa_sid": result.get("wa_sid"),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
            stats["processed"] += 1
            if result.get("sent_email"): stats["email_sent"] += 1
            if result.get("sent_wa"): stats["wa_sent"] += 1
    return stats


def _verify_cron_auth(authorization: Optional[str]) -> None:
    if not WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="WEBHOOK_CRON_SECRET absent")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Auth manquante")
    token = authorization[len("Bearer "):]
    if not hmac.compare_digest(token, WEBHOOK_SECRET):
        raise HTTPException(status_code=401, detail="Auth invalide")


@router.post("/cron/notify-echeances")
async def cron_notify_echeances(
    background: BackgroundTasks,
    authorization: Optional[str] = Header(None),
    x_webhook_id: Optional[str] = Header(None),
):
    # Cron endpoints must ack 2xx immediately; enqueue/background the actual work.
    _verify_cron_auth(authorization)
    if x_webhook_id:
        already = await db.cron_runs.find_one({"run_id": x_webhook_id})
        if already:
            return {"ok": True, "duplicate": True}
        await db.cron_runs.insert_one({
            "run_id": x_webhook_id,
            "job": "notify-echeances",
            "received_at": datetime.now(timezone.utc).isoformat(),
        })
    background.add_task(_run_daily_notifications)
    return {"ok": True, "queued": True}


# Manual trigger for testing (superviseur only via require_staff — endpoint helps QA)
@router.post("/cron/notify-echeances/_trigger")
async def cron_trigger_now(user: dict = Depends(require_staff())):
    stats = await _run_daily_notifications()
    return {"ok": True, "stats": stats}
