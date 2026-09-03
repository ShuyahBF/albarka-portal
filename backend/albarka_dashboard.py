"""Dashboard & activité récente."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from albarka_auth import get_current_user
from albarka_models import is_client, tenant_id_of
from db import db, serialize_many

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/summary")
async def dashboard_summary(user: dict = Depends(get_current_user)):
    scope = {}
    if is_client(user):
        scope["tenant_id"] = tenant_id_of(user)

    documents_total = await db.documents.count_documents(scope)
    documents_pending = await db.documents.count_documents({**scope, "status": "en_analyse"})
    missions_active = await db.missions.count_documents({**scope, "status": {"$in": ["en_attente", "en_cours"]}})
    missions_done = await db.missions.count_documents({**scope, "status": "terminee"})
    echeances_upcoming = await db.echeances.count_documents({**scope, "status": {"$in": ["a_venir", "en_cours"]}})
    echeances_late = await db.echeances.count_documents({**scope, "status": "en_retard"})

    # Additional staff-only stats
    clients_total = None
    staff_total = None
    if not is_client(user):
        clients_total = await db.users.count_documents({"roles": "client"})
        staff_total = await db.users.count_documents({"roles": {"$nin": ["client"]}})

    return {
        "documents_total": documents_total,
        "documents_pending": documents_pending,
        "missions_active": missions_active,
        "missions_done": missions_done,
        "echeances_upcoming": echeances_upcoming,
        "echeances_late": echeances_late,
        "clients_total": clients_total,
        "staff_total": staff_total,
    }


@router.get("/activity")
async def dashboard_activity(limit: int = 15, user: dict = Depends(get_current_user)):
    """Aggregate recent items across documents, missions, échéances."""
    scope = {}
    if is_client(user):
        scope["tenant_id"] = tenant_id_of(user)

    docs = await db.documents.find(scope, {"_id": 0}).sort("created_at", -1).to_list(limit)
    missions = await db.missions.find(scope, {"_id": 0}).sort("created_at", -1).to_list(limit)
    echeances = await db.echeances.find(scope, {"_id": 0}).sort("due_date", 1).to_list(limit)

    return {
        "documents": serialize_many(docs),
        "missions": serialize_many(missions),
        "echeances": serialize_many(echeances),
    }


@router.get("/dispatches")
async def dashboard_dispatches(user: dict = Depends(get_current_user)):
    """Envois du mois courant : WA délivrés, WA échoués, emails, signatures, rapports.

    Filtre par tenant pour les utilisateurs client, agrège tout pour les staff.
    """
    from datetime import datetime, timezone
    scope = {}
    if is_client(user):
        scope["tenant_id"] = tenant_id_of(user)
    now = datetime.now(timezone.utc)
    month_prefix = now.strftime("%Y-%m")

    def _month_filter(field: str):
        # ISO strings are lexicographically sortable — a prefix match is enough.
        return {field: {"$regex": f"^{month_prefix}"}}

    wa_ok = await db.wa_send_log.count_documents({**scope, **_month_filter("sent_at"), "success": True})
    wa_ko = await db.wa_send_log.count_documents({**scope, **_month_filter("sent_at"), "success": False})
    signatures = await db.signature_log.count_documents({**scope, **_month_filter("signed_at")})
    emails_sent = await db.client_reports.count_documents({**scope, **_month_filter("email_sent_at")})
    reports_generated = await db.client_reports.count_documents({**scope, **_month_filter("generated_at")})
    return {
        "month": month_prefix,
        "wa_delivered": wa_ok,
        "wa_failed": wa_ko,
        "emails_sent": emails_sent,
        "signatures": signatures,
        "reports_generated": reports_generated,
    }

