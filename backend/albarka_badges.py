"""Badges de compteurs non lus pour la sidebar (WhatsApp, Diffusion) —
actualisés par polling côté frontend (voir PortalLayout.jsx), sans
infrastructure temps réel dédiée (ni WebSocket ni SSE ailleurs dans
l'application — convention déjà en place pour ChatBubble/Documents)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from albarka_auth import get_current_user
from db import db

router = APIRouter(prefix="/me/badges", tags=["Badges"])

# Mêmes rôles que le centre WhatsApp (albarka_wa_inbox._INBOX_ROLES) et la
# Diffusion (albarka_phase_c.messaging_router) — dupliqués ici pour éviter
# d'importer des symboles privés entre modules.
_WA_ROLES = ["superviseur", "direction", "administrateur", "communication"]
_DIFFUSION_ROLES = ["superviseur", "direction", "administrateur", "communication"]


def _has_any(user: dict, roles: list) -> bool:
    user_roles = set(user.get("roles") or [])
    return "superviseur" in user_roles or bool(user_roles & set(roles))


@router.get("")
async def get_badge_counts(user: dict = Depends(get_current_user)):
    wa_unread = 0
    diffusion_new = 0

    if _has_any(user, _WA_ROLES):
        agg = await db.wa_messages.aggregate([
            {"$match": {"direction": "inbound", "read_by_staff_at": None}},
            {"$count": "n"},
        ]).to_list(1)
        wa_unread = agg[0]["n"] if agg else 0

    if _has_any(user, _DIFFUSION_ROLES):
        mark = await db.user_view_marks.find_one(
            {"user_id": user["id"], "page": "diffusion"}, {"_id": 0, "seen_at": 1},
        )
        q = {}
        if mark and mark.get("seen_at"):
            q["created_at"] = {"$gt": mark["seen_at"]}
        diffusion_new = await db.broadcasts.count_documents(q)

    return {"wa_unread": wa_unread, "diffusion_new": diffusion_new}


class MarkSeenPayload(BaseModel):
    page: str  # "diffusion" (WhatsApp se marque lu message par message, voir albarka_wa_inbox)


@router.post("/mark-seen")
async def mark_badge_seen(payload: MarkSeenPayload, user: dict = Depends(get_current_user)):
    await db.user_view_marks.update_one(
        {"user_id": user["id"], "page": payload.page},
        {"$set": {
            "user_id": user["id"], "page": payload.page,
            "seen_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    return {"ok": True}
