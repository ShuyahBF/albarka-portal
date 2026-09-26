"""Lot 5 — corrections de droits relevées par la recette complète.

- créer / modifier un compte du personnel : Direction, DG, Administrateur ou
  Superviseur seulement (plus possible pour un Comptable, même par l'API) ;
- rôle Administrateur : aussi attribuable par le Superviseur et le compte admin ;
- comptes de test : le client de test reçoit un contrat « En cours » (il peut
  se connecter) et les comptes de test se voient entre eux ;
- Caisse : réservée aux rôles du lien « Caisse » ;
- tableau de bord client : rien des modules fermés par le cabinet.
Tests autonomes : MongoDB simulé (mongomock-motor), aucun réseau.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_admin_settings  # noqa: E402
import albarka_auth  # noqa: E402
import albarka_clients  # noqa: E402
import albarka_dashboard  # noqa: E402
import albarka_phase_c  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "admin": {"id": "u-admin", "email": "admin@sawalismartsystems.com", "full_name": "Admin", "roles": ["superviseur", "direction"], "is_active": True},
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dg@albarka.bf", "full_name": "Direction", "roles": ["direction", "secretariat"], "is_active": True},
    "adm": {"id": "u-adm", "email": "adm@albarka.bf", "full_name": "Administrateur", "roles": ["administrateur"], "is_active": True},
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "dgonly": {"id": "u-dg", "email": "dgonly@albarka.bf", "full_name": "DG", "roles": ["dg"], "is_active": True},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "Vrai client", "roles": ["client"], "is_active": True},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot5_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    logs = []

    async def fake_log(**kw):
        logs.append(kw["action"])
    monkeypatch.setattr(albarka_phase_c, "_log_platform_event", fake_log)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_clients.router, albarka_admin_settings.router, albarka_dashboard.router, albarka_phase_c.billing_router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db, "logs": logs})


def _h(u):
    return {"X-User": u}


def _staff(**kw):
    base = {"email": "nouveau@albarka.bf", "full_name": "Nouveau", "password": "motdepasse1", "roles": ["comptable"]}
    base.update(kw)
    return base


def test_staff_management_restricted(env):
    # Un comptable ne peut ni créer un collaborateur ni se donner le rôle Direction
    assert env.c.post("/api/clients/staff", headers=_h("compta"), json=_staff(roles=["direction"])).status_code == 403
    assert env.c.patch("/api/clients/u-compta", headers=_h("compta"), json={"roles": ["comptable", "direction"]}).status_code == 403
    assert env.c.patch("/api/clients/u-rh", headers=_h("compta"), json={"full_name": "Pirate"}).status_code == 403
    # Direction, DG et Administrateur le peuvent
    assert env.c.post("/api/clients/staff", headers=_h("dir"), json=_staff()).status_code == 200
    assert env.c.patch("/api/clients/u-rh", headers=_h("dgonly"), json={"roles": ["rh", "communication"]}).status_code == 200
    assert env.c.post("/api/clients/staff", headers=_h("adm"), json=_staff(email="b@albarka.bf")).status_code == 200
    # Désactiver un collaborateur : même règle
    assert env.c.post("/api/clients/u-rh/active", headers=_h("compta"), json={"active": False}).status_code == 403
    assert env.c.post("/api/clients/u-rh/active", headers=_h("dgonly"), json={"active": False}).status_code == 200


def test_administrateur_role_by_superviseur_and_admin(env):
    assert env.c.post("/api/clients/staff", headers=_h("sup"), json=_staff(roles=["administrateur"])).status_code == 200
    assert env.c.patch("/api/clients/u-compta", headers=_h("admin"), json={"roles": ["comptable", "administrateur"]}).status_code == 200
    # La Direction seule ne le peut toujours pas
    assert env.c.patch("/api/clients/u-rh", headers=_h("dir"), json={"roles": ["rh", "administrateur"]}).status_code == 403


def test_test_accounts_contract_and_mutual_visibility(env):
    r = env.c.post("/api/clients/test-accounts", headers=_h("sup"), json={"email": "moi@gmail.com", "password": "motdepasse1"})
    assert r.status_code == 200
    import albarka_contracts
    clients = asyncio.run(env.db.users.find({"is_test_account": True, "roles": "client"}, {"_id": 0}).to_list(10))
    assert len(clients) == 2
    for c in clients:  # contrat « En cours » : connexion possible
        assert asyncio.run(albarka_contracts.has_active_contract(c["id"]))
    # Remise à neuf : pas de contrat en double
    env.c.post("/api/clients/test-accounts", headers=_h("sup"), json={"email": "moi@gmail.com", "password": "motdepasse1"})
    assert asyncio.run(env.db.client_contracts.count_documents({"is_test_contract": True})) == 2
    # La secrétaire de test voit les clients de test ; un vrai compte non
    secr = asyncio.run(env.db.users.find_one({"email": "moi+test-secretaire@gmail.com"}, {"_id": 0}))
    USERS["tsecr"] = secr
    try:
        names = {u["full_name"] for u in env.c.get("/api/clients", headers=_h("tsecr")).json()}
        assert {"TEST Client 1", "TEST Client 2", "Vrai client"} <= names
        names = {u["full_name"] for u in env.c.get("/api/clients", headers=_h("dir")).json()}
        assert "TEST Client 1" not in names
    finally:
        USERS.pop("tsecr")
    # Suppression des comptes de test : leurs contrats partent avec eux
    env.c.delete("/api/clients/test-accounts", headers=_h("sup"))
    assert asyncio.run(env.db.client_contracts.count_documents({"is_test_contract": True})) == 0


def test_billing_reserved_to_caisse_roles(env):
    assert env.c.get("/api/billing/invoices", headers=_h("rh")).status_code == 403
    assert env.c.get("/api/billing/invoices", headers=_h("compta")).status_code == 200
    assert env.c.get("/api/billing/invoices", headers=_h("dgonly")).status_code == 200


def test_client_dashboard_hides_closed_modules(env):
    asyncio.run(env.db.missions.insert_one({"id": "m1", "tenant_id": "c1", "status": "en_cours", "created_at": "2026-09-01"}))
    asyncio.run(env.db.documents.insert_one({"id": "d1", "tenant_id": "c1", "status": "en_analyse", "created_at": "2026-09-01"}))
    assert env.c.get("/api/dashboard/summary", headers=_h("c1")).json()["missions_active"] == 1
    asyncio.run(env.db.users.update_one({"id": "c1"}, {"$set": {"portal_modules": ["documents"]}}))
    s = env.c.get("/api/dashboard/summary", headers=_h("c1")).json()
    assert s["missions_active"] == 0 and s["documents_total"] == 1
    act = env.c.get("/api/dashboard/activity", headers=_h("c1")).json()
    assert act["missions"] == [] and len(act["documents"]) == 1


def test_frontend_menu_fixes():
    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    layout = (front / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    assert 'roles.includes("dg") ? [...roles, "direction"]' in layout          # DG = liens de la Direction
    assert 'label: "Rapports client", icon: ClipboardList, end: true' in layout  # un seul lien surligné
    assert 'canIssueTokens && l.to === "/admin/staff"' in layout                # adresse désignée → Personnels
