"""Lot 93.1 — Services Web : consultation réglable par le super-admin (lecture seule), mise à jour des paiements réservée au super-admin."""
import os
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
from fastapi import APIRouter, FastAPI, Header, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_services_web as sw  # noqa: E402
import db as db_module  # noqa: E402

USERS = {"sup": {"id": "u1", "email": "s@a.bf", "full_name": "Super", "roles": ["superviseur"]},
         "dg": {"id": "u2", "email": "dg@a.bf", "full_name": "DG", "roles": ["dg"]},
         "dir": {"id": "u3", "email": "d@a.bf", "full_name": "Direction", "roles": ["direction"]},
         "compta": {"id": "u4", "email": "c@a.bf", "full_name": "Comptable", "roles": ["comptable"]}}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot93c"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    app, api = FastAPI(), APIRouter(prefix="/api")
    api.include_router(sw.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[sw.get_current_user] = fake_user
    return TestClient(app)


def h(x):
    return {"X-User": x}


def test_par_defaut_seul_le_dg_consulte(env):
    assert env.get("/api/me/services-web", headers=h("dg")).status_code == 200
    for r in ("dir", "compta", "sup"):
        assert env.get("/api/me/services-web", headers=h(r)).status_code == 403
    assert env.get("/api/me/services-web/acces", headers=h("dg")).json() == {"consultation": True, "rappels": True}
    assert env.get("/api/me/services-web/acces", headers=h("dir")).json() == {"consultation": False, "rappels": False}


def test_le_super_admin_autorise_la_consultation_sans_les_rappels(env):
    assert env.put("/api/admin/services-web/consultation", json={"roles": ["direction"]}, headers=h("sup")).json() == {"roles": ["direction"]}
    assert env.get("/api/me/services-web", headers=h("dir")).status_code == 200                        # la Direction consulte
    assert env.get("/api/me/services-web", headers=h("compta")).status_code == 403                     # pas le comptable
    assert env.get("/api/me/services-web/acces", headers=h("dir")).json() == {"consultation": True, "rappels": False}
    assert env.get("/api/me/services-web/rappels", headers=h("dir")).status_code == 403                # les rappels restent au DG
    assert env.post("/api/me/services-web/rappels/ack", json={"cles": ["x"]}, headers=h("dir")).status_code == 403


def test_seul_le_super_admin_modifie(env):
    s = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 8}, headers=h("sup")).json()
    env.put("/api/admin/services-web/consultation", json={"roles": ["direction", "comptable"]}, headers=h("sup"))
    for r in ("dg", "dir", "compta"):                                                                  # ni le DG ni les rôles de lecture ne modifient
        assert env.post("/api/admin/services-web", json={"service": "X", "montant": 1, "jour_du_mois": 1}, headers=h(r)).status_code == 403
        assert env.post(f"/api/admin/services-web/{s['id']}/paiement", json={"paye_le": "2026-11-12T14:30", "montant": 1, "reference": "R"}, headers=h(r)).status_code == 403
        assert env.put("/api/admin/services-web/consultation", json={"roles": []}, headers=h(r)).status_code == 403
        assert env.get("/api/admin/services-web/paiements-sms", headers=h(r)).status_code == 403
    assert env.post(f"/api/admin/services-web/{s['id']}/paiement", json={"paye_le": "2026-11-12T14:30", "montant": 25000, "reference": "R1"}, headers=h("sup")).status_code == 200


def test_roles_inconnus_refuses(env):
    r = env.put("/api/admin/services-web/consultation", json={"roles": ["dg", "pirate"]}, headers=h("sup"))
    assert r.status_code == 422
    assert env.get("/api/admin/services-web/consultation", headers=h("sup")).json()["roles"] == []
