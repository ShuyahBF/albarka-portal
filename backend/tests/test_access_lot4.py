"""Lot 4 — liste blanche du personnel (appareils + IP), jetons d'accès
temporaires, derniers clients connectés.

Tests autonomes : MongoDB simulé (mongomock-motor), envois simulés.
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient
from jose import jwt

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_access  # noqa: E402
import albarka_admin_settings  # noqa: E402
import albarka_auth  # noqa: E402
import albarka_notifications  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_presence  # noqa: E402

USERS = {
    "admin": {"id": "u-admin", "email": "admin@sawalismartsystems.com", "full_name": "Admin", "roles": ["superviseur", "direction"]},
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"]},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg", "direction"]},
    "secr": {"id": "u-secr", "email": "secr@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"]},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "phone": "+22670000009"},
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "SARL Kaboré", "company": "Kaboré", "roles": ["client"]},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_access_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([{**u, "is_active": True} for u in USERS.values()]))
    sent, logs = {"email": [], "wa": []}, []

    async def fake_email(*, to, subject, html, **kw):
        albarka_notifications._assert_safe_email(subject, html)  # vrais garde-fous
        sent["email"].append({"to": to, "html": html})
        return "m1"

    async def fake_wa(*, to_phone, message):
        sent["wa"].append({"to": to_phone, "text": message})
        return {"ok": True}

    async def fake_log(**kw):
        logs.append(kw["action"])
    monkeypatch.setattr(albarka_notifications, "send_email", fake_email)
    monkeypatch.setattr(albarka_notifications, "send_whatsapp", fake_wa)
    monkeypatch.setattr(albarka_phase_c, "_log_platform_event", fake_log)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_auth.router, albarka_access.router, albarka_admin_settings.router, albarka_presence.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[albarka_auth.get_current_user] = fake_user
    with TestClient(app, headers={"Origin": "https://albarka-bf.com"}) as client:
        yield type("Env", (), {"c": client, "db": mock_db, "sent": sent, "logs": logs})


def _h(u):
    return {"X-User": u}


def _login(env, who, device_id=None, access_code=None, ip="197.239.10.10"):
    """Simule mot de passe OK puis envoi du code OTP (étape verify-otp)."""
    tok = f"s-{who}-{len(env.logs)}-{device_id}-{access_code}"
    asyncio.run(env.db.otps.insert_one({"id": tok, "user_id": USERS[who]["id"], "session_token": tok, "code": "123456",
                                        "used": False, "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()}))
    return env.c.post("/api/auth/verify-otp", headers={"X-Forwarded-For": ip},
                      json={"session_token": tok, "code": "123456", "device_id": device_id, "access_code": access_code})


def _enable(env, **extra):
    r = env.c.put("/api/admin/settings", headers=_h("sup"), json={"staff_whitelist_enabled": True, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def test_whitelist_off_by_default_then_fake_404(env):
    assert _login(env, "compta", device_id="dev-inconnu").status_code == 200  # désactivée : rien ne change
    _enable(env)
    r = _login(env, "compta", device_id="dev-inconnu")
    assert r.status_code == 404 and r.json()["detail"] == "ERREUR 404"
    assert "login.blocked_whitelist" in env.logs
    # Demande d'appareil créée pour le superviseur
    reqs = env.c.get("/api/access/devices", headers=_h("sup")).json()["requests"]
    assert reqs[0]["user_email"] == "c@albarka.bf" and reqs[0]["device_id"] == "dev-inconnu"
    # Exemptés : admin, superviseur, clients (contrat non requis pour ce test côté staff)
    assert _login(env, "admin", device_id="x").status_code == 200
    assert _login(env, "sup", device_id="x").status_code == 200


def test_ip_and_device_whitelist(env):
    s = _enable(env, staff_ip_whitelist=["41.207.12.0/24", " 102.180.5.7 "])
    assert s["staff_ip_whitelist"] == ["41.207.12.0/24", "102.180.5.7/32"]
    assert env.c.put("/api/admin/settings", headers=_h("sup"), json={"staff_ip_whitelist": ["pas-une-ip"]}).status_code == 400
    assert _login(env, "compta", ip="41.207.12.55").status_code == 200    # réseau du bureau
    assert _login(env, "compta", ip="41.207.13.1").status_code == 404
    # Approbation de la demande → l'appareil passe
    _login(env, "compta", device_id="pc-compta")
    req = env.c.get("/api/access/devices", headers=_h("sup")).json()["requests"][0]
    assert env.c.post(f"/api/access/requests/{req['id']}/approve", headers=_h("dg"), json={}).status_code == 403
    env.c.post(f"/api/access/requests/{req['id']}/approve", headers=_h("sup"), json={})
    assert _login(env, "compta", device_id="pc-compta").status_code == 200
    assert _login(env, "secr", device_id="pc-compta").status_code == 404       # appareil propre au comptable
    # Poste partagé du cabinet (« cet appareil ») : tout collaborateur
    env.c.post("/api/access/devices", headers=_h("sup"), json={"device_id": "poste-accueil", "label": "Accueil", "current": True})
    assert _login(env, "secr", device_id="poste-accueil").status_code == 200
    dev = next(d for d in env.c.get("/api/access/devices", headers=_h("sup")).json()["devices"] if d["device_id"] == "poste-accueil")
    env.c.delete(f"/api/access/devices/{dev['id']}", headers=_h("sup"))
    assert _login(env, "secr", device_id="poste-accueil").status_code == 404


def test_temporary_access_token(env):
    _enable(env)
    # Seul admin, ou une adresse désignée par admin, crée des jetons
    assert env.c.post("/api/access/tokens", headers=_h("dg"), json={"user_id": "u-compta", "hours": 4}).status_code == 403
    assert env.c.put("/api/admin/settings", headers=_h("sup"), json={"access_token_issuer_emails": ["dg@albarka.bf"]}).status_code == 403
    assert env.c.put("/api/admin/settings", headers=_h("admin"), json={"access_token_issuer_emails": ["DG@albarka.bf"]}).json()["access_token_issuer_emails"] == ["dg@albarka.bf"]
    assert env.c.get("/api/access/me", headers=_h("dg")).json()["can_issue_tokens"] is True
    r = env.c.post("/api/access/tokens", headers=_h("dg"), json={"user_id": "u-compta", "hours": 4, "note": "Clôture annuelle"}).json()
    assert len(r["code"]) == 10 and r["link"] == f"https://albarka-bf.com/login?acces={r['code']}"
    assert r["delivery"] == {"email": {"ok": True}, "whatsapp": {"ok": True, "error": None}}
    assert r["code"] in env.sent["wa"][0]["text"] and env.sent["email"][0]["to"] == "c@albarka.bf"
    assert env.c.post("/api/access/tokens", headers=_h("dg"), json={"user_id": "c1"}).status_code == 404   # pas un client
    assert env.c.post("/api/access/tokens", headers=_h("dg"), json={"user_id": "u-compta", "hours": 500}).status_code == 400
    # Connexion depuis n'importe où avec le code ; session bornée à la fin du jeton
    ok = _login(env, "compta", device_id="tel-perso", access_code=r["code"].lower())
    assert ok.status_code == 200
    exp = jwt.get_unverified_claims(ok.json()["access_token"])["exp"]
    assert exp <= datetime.fromisoformat(r["expires_at"]).timestamp() + 1
    assert _login(env, "secr", device_id="tel-perso", access_code=r["code"]).status_code == 404   # lié au comptable
    # Révocation
    env.c.delete(f"/api/access/tokens/{r['id']}", headers=_h("dg"))
    assert _login(env, "compta", device_id="tel-perso", access_code=r["code"]).status_code == 404
    items = env.c.get("/api/access/tokens", headers=_h("sup")).json()["items"]
    assert items[0]["active"] is False and "code_hash" not in items[0] and len(items[0]["uses"]) == 1


def test_recent_clients_with_activity_duration(env):
    now_ms = datetime.now(timezone.utc).timestamp() * 1000
    env.c.post("/api/presence/heartbeat", headers=_h("c1"), json={"visible": True, "last_activity": now_ms})
    doc = asyncio.run(env.db.presence.find_one({"_id": "c1"}))
    # Session commencée il y a 20 min, dernière activité il y a 5 min
    start = datetime.now(timezone.utc) - timedelta(minutes=20)
    asyncio.run(env.db.presence.update_one({"_id": "c1"}, {"$set": {"session_started_at": start.isoformat()}}))
    env.c.post("/api/presence/heartbeat", headers=_h("c1"), json={"visible": True, "last_activity": now_ms - 5 * 60000})
    assert doc["session_started_at"]
    for who in ("dg", "secr", "admin"):
        items = env.c.get("/api/presence/recent-clients", headers=_h(who)).json()["items"]
        assert items[0]["name"] == "SARL Kaboré" and 14 * 60 <= items[0]["duration_seconds"] <= 16 * 60
    assert env.c.get("/api/presence/recent-clients", headers=_h("compta")).status_code == 403
