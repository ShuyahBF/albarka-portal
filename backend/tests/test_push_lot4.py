"""Lot 4 — notifications push (Web Push) et adresse IP dans le Journal.

- chiffrement RFC 8291 vérifié par déchiffrement (bibliothèque de référence
  http_ece si disponible, sinon structure de l'en-tête) ;
- abonnement / désabonnement, envoi, abonnements expirés supprimés ;
- documents mis à disposition : push en plus de WhatsApp ;
- Journal plateforme : IP et navigateur de la requête enregistrés.
Tests autonomes : MongoDB simulé, service de push simulé (aucun réseau).
"""
from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_client_space as cs  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_push as ap  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "SARL Kaboré", "roles": ["client"], "is_active": True},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
}


def _browser_keys():
    """Clés d'abonnement comme les fournit un navigateur (p256dh + auth)."""
    ua = ec.generate_private_key(ec.SECP256R1())
    pub = ua.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    return ua, auth, {"p256dh": ap.b64u(pub), "auth": ap.b64u(auth)}


def test_encryption_rfc8291():
    ua, auth, keys = _browser_keys()
    msg = json.dumps({"title": "Facture disponible", "body": "Honoraires — 118 000 FCFA"}, ensure_ascii=False).encode()
    body = ap.encrypt_payload(msg, keys["p256dh"], keys["auth"])
    # En-tête aes128gcm : sel (16) + taille de bloc (4) + longueur de clé (1) + clé serveur (65)
    assert struct.unpack("!L", body[16:20])[0] == 4096 and body[20] == 65 and body[21] == 4
    try:
        sys.path.insert(0, "/tmp/hece/http_ece-1.2.1")
        import http_ece  # bibliothèque de référence (implémentation indépendante)
    except ImportError:
        pytest.skip("http_ece absent : seule la structure est vérifiée")
    assert http_ece.decrypt(body, private_key=ua, auth_secret=auth, version="aes128gcm") == msg


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_push_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    pushed, state = [], {"status": 201}

    async def fake_send(sub, body, key, subject):
        pushed.append({"endpoint": sub["endpoint"], "size": len(body), "subject": subject,
                       "auth": ap.vapid_authorization(key, sub["endpoint"], subject)})
        return {"ok": state["status"] < 300, "status": state["status"], "error": None}
    monkeypatch.setattr(ap, "_send_one", fake_send)

    async def fake_wa(*, to_phone, message):
        return {"ok": True}

    async def open_window(phone):
        return True
    monkeypatch.setattr(cs, "send_whatsapp", fake_wa)
    monkeypatch.setattr(cs, "wa_window_state", open_window)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (ap.router, albarka_phase_c.logs_router):
        api.include_router(r)
    app.include_router(api)

    @app.middleware("http")
    async def ip_mw(request, call_next):  # même principe que server.py
        from albarka_request_ctx import set_request_info
        fwd = request.headers.get("x-forwarded-for") or ""
        set_request_info(fwd.split(",")[0].strip(), request.headers.get("user-agent") or "")
        return await call_next(request)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db, "pushed": pushed, "state": state})


def _h(u, **extra):
    return {"X-User": u, **extra}


def test_subscribe_send_and_expired(env):
    pk = env.c.get("/api/push/public-key", headers=_h("c1")).json()["public_key"]
    assert len(ap.b64u_dec(pk)) == 65  # clé P-256 non compressée, stable ensuite
    assert env.c.get("/api/push/public-key", headers=_h("compta")).json()["public_key"] == pk
    _, _, keys = _browser_keys()
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": keys}
    assert env.c.post("/api/push/subscribe", headers=_h("c1"), json={"subscription": {"endpoint": "http://x", "keys": keys}}).status_code == 400
    assert env.c.post("/api/push/subscribe", headers=_h("c1"), json={"subscription": sub}).json() == {"ok": True}
    env.c.post("/api/push/subscribe", headers=_h("c1"), json={"subscription": sub})  # même appareil : pas de doublon
    assert asyncio.run(env.db.push_subscriptions.count_documents({})) == 1
    r = env.c.post("/api/push/test", headers=_h("c1")).json()
    assert r == {"sent": 1, "failed": 0, "devices": 1}
    assert env.pushed[0]["auth"].startswith("vapid t=") and f"k={pk}" in env.pushed[0]["auth"]
    assert env.c.post("/api/push/test", headers=_h("compta")).status_code == 404  # aucun appareil abonné
    # Abonnement expiré côté service de push (410) : supprimé
    env.state["status"] = 410
    env.c.post("/api/push/test", headers=_h("c1"))
    assert asyncio.run(env.db.push_subscriptions.count_documents({})) == 0


def test_client_documents_trigger_push(env):
    _, _, keys = _browser_keys()
    env.c.post("/api/push/subscribe", headers=_h("c1"), json={"subscription": {"endpoint": "https://push.example/1", "keys": keys}})
    items = [{"category": "facture", "title": "Honoraires", "reference": "FAC-1", "amount": 118000}]
    client = dict(USERS["c1"], phone="+22670000001")
    res = asyncio.run(cs.notify_client(client, items, link="https://albarka-bf.com/portal/documents-cabinet"))
    assert res["ok"] and res["channel"] == "whatsapp" and res["push"] == 1 and len(env.pushed) == 1
    # Push désactivé dans les paramètres : WhatsApp seul
    asyncio.run(env.db.settings.update_one({"_id": "global"}, {"$set": {"client_docs_push_enabled": False}}))
    res = asyncio.run(cs.notify_client(client, items, link="https://albarka-bf.com/portal/documents-cabinet"))
    assert res["push"] == 0 and len(env.pushed) == 1


def test_platform_log_records_ip(env):
    _, _, keys = _browser_keys()
    # Une action tracée pendant une requête : l'IP de la requête est enregistrée
    import albarka_push as ap2

    async def log_during_request():
        from albarka_request_ctx import set_request_info
        set_request_info("197.239.10.42", "Mozilla/5.0 Test")
        await albarka_phase_c._log_platform_event(user=USERS["compta"], action="test.action", entity_type="x")
    asyncio.run(log_during_request())
    data = env.c.get("/api/platform-logs", headers=_h("sup")).json()
    logs = data if isinstance(data, list) else data.get("items", [])
    entry = next(l for l in logs if l["action"] == "test.action")
    assert entry["ip"] == "197.239.10.42" and entry["user_agent"] == "Mozilla/5.0 Test"
    assert ap2  # module chargé
