"""Partie 2.E — Extensions WhatsApp Inbox
- Quick replies (snippets réutilisables par le staff)
- Labels de conversation (à traiter / en attente / résolu)
- Statistiques mensuelles (volume, temps de réponse, top contacts)
"""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from typing import Optional, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import require_roles
from db import db, serialize_many

_INBOX_ROLES = ["superviseur", "direction", "administrateur", "communication"]
_STATS_ROLES = ["superviseur", "direction", "administrateur", "communication"]

LABELS_ALLOWED = {"todo", "waiting", "resolved"}

router = APIRouter(prefix="/whatsapp", tags=["Conversations WhatsApp — Extras"])


# =====================================================================
# Quick replies (snippets)
# =====================================================================
class QuickReplyIn(BaseModel):
    label: str = Field(..., min_length=1, max_length=80)
    body: str = Field(..., min_length=1, max_length=4000)
    sort_order: int = 0


class QuickReplyPatch(BaseModel):
    label: Optional[str] = Field(default=None, max_length=80)
    body: Optional[str] = Field(default=None, max_length=4000)
    sort_order: Optional[int] = None


@router.get("/quick-replies")
async def list_quick_replies(user: dict = Depends(require_roles(_INBOX_ROLES))):
    items = await db.wa_quick_replies.find(
        {}, {"_id": 0},
    ).sort([("sort_order", 1), ("created_at", -1)]).to_list(200)
    return serialize_many(items)


@router.post("/quick-replies")
async def create_quick_reply(payload: QuickReplyIn, user: dict = Depends(require_roles(_INBOX_ROLES))):
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": secrets.token_urlsafe(10),
        "label": payload.label.strip(),
        "body": payload.body.strip(),
        "sort_order": payload.sort_order,
        "created_at": now,
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "updated_at": now,
    }
    await db.wa_quick_replies.insert_one(dict(doc))
    return doc


@router.patch("/quick-replies/{qid}")
async def update_quick_reply(qid: str, payload: QuickReplyPatch, user: dict = Depends(require_roles(_INBOX_ROLES))):
    existing = await db.wa_quick_replies.find_one({"id": qid}, {"_id": 0})
    if not existing:
        raise HTTPException(404, "Réponse rapide introuvable")
    updates: dict = {"updated_at": datetime.now(timezone.utc).isoformat()}
    if payload.label is not None:
        updates["label"] = payload.label.strip()
    if payload.body is not None:
        updates["body"] = payload.body.strip()
    if payload.sort_order is not None:
        updates["sort_order"] = payload.sort_order
    await db.wa_quick_replies.update_one({"id": qid}, {"$set": updates})
    return {**existing, **updates}


@router.delete("/quick-replies/{qid}")
async def delete_quick_reply(qid: str, user: dict = Depends(require_roles(_INBOX_ROLES))):
    r = await db.wa_quick_replies.delete_one({"id": qid})
    if r.deleted_count == 0:
        raise HTTPException(404, "Réponse rapide introuvable")
    return {"ok": True}


# =====================================================================
# Labels de conversation (par numéro)
# =====================================================================
class LabelPayload(BaseModel):
    label: Optional[Literal["todo", "waiting", "resolved"]] = None


@router.patch("/conversations/{phone}/label")
async def set_conversation_label(
    phone: str, payload: LabelPayload,
    user: dict = Depends(require_roles(_INBOX_ROLES)),
):
    now = datetime.now(timezone.utc).isoformat()
    if payload.label is None:
        await db.wa_conversation_labels.delete_one({"phone": phone})
        return {"ok": True, "label": None}
    await db.wa_conversation_labels.update_one(
        {"phone": phone},
        {"$set": {
            "phone": phone,
            "label": payload.label,
            "updated_at": now,
            "updated_by": user["id"],
            "updated_by_name": user.get("full_name") or user.get("email"),
        }},
        upsert=True,
    )
    return {"ok": True, "label": payload.label, "updated_at": now}


@router.get("/conversations-labels")
async def list_conversation_labels(user: dict = Depends(require_roles(_INBOX_ROLES))):
    rows = await db.wa_conversation_labels.find({}, {"_id": 0}).to_list(2000)
    return {r["phone"]: r["label"] for r in rows if r.get("phone") and r.get("label")}


# =====================================================================
# Statistiques mensuelles
# =====================================================================
def _month_range(year_month: str) -> tuple[str, str]:
    """Retourne (start_iso, end_iso_exclusive) pour un YYYY-MM."""
    try:
        year, month = year_month.split("-")
        y, m = int(year), int(month)
    except Exception:
        raise HTTPException(400, "Paramètre year_month attendu au format YYYY-MM")
    start = datetime(y, m, 1, tzinfo=timezone.utc)
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = datetime(ny, nm, 1, tzinfo=timezone.utc)
    return start.isoformat(), end.isoformat()


@router.get("/stats")
async def wa_stats(
    year_month: str,
    user: dict = Depends(require_roles(_STATS_ROLES)),
):
    """Statistiques d'un mois : volume in/out, avg response time, top contacts."""
    start_iso, end_iso = _month_range(year_month)
    match = {"created_at": {"$gte": start_iso, "$lt": end_iso}}

    # Compteurs par direction/type
    dir_pipeline = [
        {"$match": match},
        {"$group": {"_id": "$direction", "n": {"$sum": 1}}},
    ]
    dir_rows = await db.wa_messages.aggregate(dir_pipeline).to_list(10)
    dir_counts = {r["_id"]: r["n"] for r in dir_rows}
    inbound = int(dir_counts.get("inbound", 0))
    outbound = int(dir_counts.get("outbound", 0))

    # Types de messages entrants
    type_pipeline = [
        {"$match": {**match, "direction": "inbound"}},
        {"$group": {"_id": "$message_type", "n": {"$sum": 1}}},
        {"$sort": {"n": -1}},
    ]
    type_rows = await db.wa_messages.aggregate(type_pipeline).to_list(20)
    types = [{"type": r["_id"] or "unknown", "n": r["n"]} for r in type_rows]

    # Top contacts (inbound uniquement)
    top_pipeline = [
        {"$match": {**match, "direction": "inbound"}},
        {"$group": {
            "_id": "$phone",
            "n": {"$sum": 1},
            "contact_name": {"$first": "$contact_name"},
            "profile_name": {"$first": "$profile_name"},
        }},
        {"$sort": {"n": -1}},
        {"$limit": 10},
    ]
    top_rows = await db.wa_messages.aggregate(top_pipeline).to_list(10)
    top_contacts = [{
        "phone": r["_id"],
        "count": r["n"],
        "name": r.get("contact_name") or r.get("profile_name") or None,
    } for r in top_rows]

    # Temps de réponse : pour chaque inbound, trouver la 1re outbound suivante
    # (même phone, direction=outbound, created_at > inbound.created_at).
    # On limite pour éviter les coûts : 500 inbound max sur le mois.
    inbounds = await db.wa_messages.find(
        {**match, "direction": "inbound"},
        {"_id": 0, "phone": 1, "created_at": 1},
    ).sort("created_at", 1).to_list(500)

    deltas: list[float] = []
    # Cache : pour chaque phone, on garde une liste triée d'outbound à parcourir
    outbounds_by_phone: dict[str, list[str]] = {}
    for phone in {i["phone"] for i in inbounds}:
        outs = await db.wa_messages.find(
            {"phone": phone, "direction": "outbound", "created_at": {"$gte": start_iso}},
            {"_id": 0, "created_at": 1},
        ).sort("created_at", 1).to_list(500)
        outbounds_by_phone[phone] = [o["created_at"] for o in outs]

    for inb in inbounds:
        outs = outbounds_by_phone.get(inb["phone"], [])
        for out_ts in outs:
            if out_ts > inb["created_at"]:
                try:
                    dt_in = datetime.fromisoformat(inb["created_at"].replace("Z", "+00:00"))
                    dt_out = datetime.fromisoformat(out_ts.replace("Z", "+00:00"))
                    delta = (dt_out - dt_in).total_seconds()
                    if 0 < delta < 7 * 86400:  # ignorer > 7 jours (anomalie)
                        deltas.append(delta)
                except Exception:
                    pass
                break

    avg_response_seconds = round(sum(deltas) / len(deltas)) if deltas else None
    median_response_seconds = None
    if deltas:
        s = sorted(deltas)
        median_response_seconds = round(s[len(s) // 2])

    # Séries journalières (volume in/out par jour)
    daily_pipeline = [
        {"$match": match},
        {"$project": {
            "direction": 1,
            "day": {"$substr": ["$created_at", 0, 10]},
        }},
        {"$group": {
            "_id": {"day": "$day", "direction": "$direction"},
            "n": {"$sum": 1},
        }},
        {"$sort": {"_id.day": 1}},
    ]
    daily_rows = await db.wa_messages.aggregate(daily_pipeline).to_list(200)
    daily_map: dict[str, dict[str, int]] = {}
    for r in daily_rows:
        d = r["_id"]["day"]
        daily_map.setdefault(d, {"inbound": 0, "outbound": 0})
        daily_map[d][r["_id"]["direction"]] = r["n"]
    daily = [{"day": d, **v} for d, v in sorted(daily_map.items())]

    return {
        "year_month": year_month,
        "inbound": inbound,
        "outbound": outbound,
        "total": inbound + outbound,
        "avg_response_seconds": avg_response_seconds,
        "median_response_seconds": median_response_seconds,
        "response_samples": len(deltas),
        "types": types,
        "top_contacts": top_contacts,
        "daily": daily,
    }
