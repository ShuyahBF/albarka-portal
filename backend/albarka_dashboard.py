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
