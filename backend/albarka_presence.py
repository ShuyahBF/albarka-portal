"""Présence en temps réel (keep-alive) — qui est connecté au portail.

Chaque page ouverte du portail (espace client comme cabinet) envoie un
« battement » toutes les 25 s (POST /presence/heartbeat), et un signal
« hors ligne » à la déconnexion ou à la fermeture de l'onglet
(POST /presence/offline). Le cabinet lit l'état de tous les comptes
(GET /presence) pour les listes Clients / Personnels et les fenêtres de
communication (chat interne, WhatsApp).

États :
  - online  : battement reçu il y a moins de ONLINE_WINDOW s, onglet visible ;
  - away    : battement récent mais onglet en arrière-plan ;
  - offline : plus de battement depuis ONLINE_WINDOW s, ou signal de sortie.

Collection `presence` : un document par compte (_id = user_id). Pas de
WebSocket dans l'application : même principe de sondage que le chat.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Body, Depends, Query

from albarka_auth import get_current_user, require_staff
from albarka_models import hide_test_accounts_filter, is_client
from db import db

router = APIRouter(prefix="/presence", tags=["Présence"])

HEARTBEAT_SECONDS = 25          # fréquence des battements côté navigateur
ONLINE_WINDOW = 70              # au-delà (≈ 2 battements manqués) : hors ligne


def _now() -> datetime:
    return datetime.now(timezone.utc)


def status_of(doc: Optional[Dict], now: Optional[datetime] = None) -> Dict:
    """État lisible d'un document de présence : {status, last_seen, page}."""
    if not doc or not doc.get("last_seen"):
        return {"status": "offline", "last_seen": None, "page": None}
    now = now or _now()
    last = datetime.fromisoformat(doc["last_seen"])
    fresh = (now - last) <= timedelta(seconds=ONLINE_WINDOW)
    if doc.get("offline") or not fresh:
        status = "offline"
    else:
        status = "online" if doc.get("visible", True) else "away"
    return {"status": status, "last_seen": doc["last_seen"], "page": doc.get("page") if status != "offline" else None}


@router.post("/heartbeat")
async def heartbeat(payload: Dict = Body(default={}), user: dict = Depends(get_current_user)):
    """Battement : « je suis là » (+ onglet visible ou non, page ouverte,
    heure de la dernière activité réelle : clavier, souris, défilement)."""
    now = _now()
    doc = await db.presence.find_one({"_id": user["id"]}) or {}
    # Nouvelle session si jamais vu, sorti explicitement, ou silencieux depuis 70 s
    new_session = (not doc.get("last_seen") or doc.get("offline")
                   or now - datetime.fromisoformat(doc["last_seen"]) > timedelta(seconds=ONLINE_WINDOW))
    started = now if new_session else datetime.fromisoformat(doc.get("session_started_at") or doc["last_seen"])
    # Dernière activité réelle signalée par le navigateur (bornée à la session)
    last_act = doc.get("last_activity_at") if not new_session else None
    try:
        ms = float(payload.get("last_activity")) if payload.get("last_activity") is not None else None
    except (TypeError, ValueError):
        ms = None
    if ms:
        act = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
        act = min(max(act, started), now)
        last_act = act.isoformat()
    await db.presence.update_one({"_id": user["id"]}, {"$set": {
        "user_id": user["id"], "last_seen": now.isoformat(), "offline": False,
        "visible": bool(payload.get("visible", True)),
        "page": str(payload.get("page") or "")[:120] or None,
        "kind": "client" if is_client(user) else "staff",
        "session_started_at": started.isoformat(),
        "last_activity_at": last_act or started.isoformat(),
    }}, upsert=True)
    return {"ok": True, "interval": HEARTBEAT_SECONDS}


@router.post("/offline")
async def offline(user: dict = Depends(get_current_user)):
    """Sortie explicite (déconnexion, fermeture de l'onglet) : hors ligne tout de suite."""
    await db.presence.update_one({"_id": user["id"]}, {"$set": {
        "user_id": user["id"], "offline": True, "last_seen": _now().isoformat()}}, upsert=True)
    return {"ok": True}


@router.get("")
async def presence_all(user: dict = Depends(require_staff())):
    """État de présence de tous les comptes (cabinet uniquement) + compteurs."""
    now = _now()
    hide = hide_test_accounts_filter(user)
    # Comptes visibles par ce collaborateur (les comptes de test : superviseur seul)
    users = await db.users.find(hide, {"_id": 0, "id": 1, "roles": 1}).to_list(5000)
    kinds = {u["id"]: ("client" if "client" in (u.get("roles") or []) else "staff") for u in users}
    docs = await db.presence.find({"_id": {"$in": list(kinds)}}).to_list(5000)
    items = {d["_id"]: status_of(d, now) for d in docs}
    counts = {"staff_online": 0, "client_online": 0}
    for uid, st in items.items():
        if st["status"] != "offline":
            counts[f"{kinds.get(uid, 'staff')}_online"] += 1
    return {"items": items, "counts": counts, "online_window": ONLINE_WINDOW, "server_time": now.isoformat()}


@router.get("/by-phone")
async def presence_by_phone(phones: List[str] = Query(default=[]), user: dict = Depends(require_staff())):
    """Présence portail des clients dont le cabinet connaît déjà le numéro
    (messagerie WhatsApp) : ne renvoie que l'état, jamais d'autre donnée."""
    phones = [p for p in phones if p][:200]
    if not phones:
        return {"items": {}}
    clients = await db.users.find(
        {"roles": "client", "$or": [{"phone": {"$in": phones}}, {"whatsapp_number": {"$in": phones}}],
         **hide_test_accounts_filter(user)},
        {"_id": 0, "id": 1, "phone": 1, "whatsapp_number": 1}).to_list(500)
    docs = {d["_id"]: d for d in await db.presence.find({"_id": {"$in": [c["id"] for c in clients]}}).to_list(500)}
    now = _now()
    out: Dict[str, Dict] = {}
    for c in clients:
        st = status_of(docs.get(c["id"]), now)
        for p in (c.get("phone"), c.get("whatsapp_number")):
            if p in phones:
                out[p] = st
    return {"items": out}


# Tableau de bord : Direction, Secrétariat, Superviseur et admin
_RECENT_CLIENTS_ROLES = {"direction", "secretariat", "superviseur"}


@router.get("/recent-clients")
async def recent_clients(limit: int = 10, user: dict = Depends(require_staff())):
    """Les derniers clients connectés : début de session, dernière activité
    réelle et durée jusqu'à la fin de toute activité détectée."""
    from albarka_models import is_admin_account
    from fastapi import HTTPException
    if not (set(user.get("roles") or []) & _RECENT_CLIENTS_ROLES or is_admin_account(user)):
        raise HTTPException(status_code=403, detail="Réservé à la Direction, au Secrétariat et à admin")
    limit = max(1, min(int(limit or 10), 50))
    hide = hide_test_accounts_filter(user)
    docs = await db.presence.find({"kind": "client", "session_started_at": {"$exists": True}}).sort(
        "session_started_at", -1).to_list(200)
    users = {u["id"]: u for u in await db.users.find(
        {"id": {"$in": [d["_id"] for d in docs]}, "roles": "client", **hide},
        {"_id": 0, "id": 1, "full_name": 1, "company": 1}).to_list(200)}
    now = _now()
    items = []
    for d in docs:
        u = users.get(d["_id"])
        if not u:
            continue
        start = datetime.fromisoformat(d["session_started_at"])
        last = datetime.fromisoformat(d.get("last_activity_at") or d["session_started_at"])
        items.append({"user_id": u["id"], "name": u.get("full_name"), "company": u.get("company"),
                      "session_started_at": d["session_started_at"], "last_activity_at": last.isoformat(),
                      "duration_seconds": max(0, int((last - start).total_seconds())),
                      **{k: v for k, v in status_of(d, now).items() if k in ("status", "last_seen")}})
        if len(items) >= limit:
            break
    return {"items": items}


async def ensure_presence_indexes() -> None:
    await db.presence.create_index("last_seen")
    await db.presence.create_index([("kind", 1), ("session_started_at", -1)])
