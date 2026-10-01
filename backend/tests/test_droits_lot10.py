"""Lot 10 — cohérence des droits relevée par la recette complète (v2026.8).

1. Tableau de bord du cabinet (/admin) : ni l'Administrateur seul ni le
   Caissier seul n'y ont accès (l'API /dashboard/* répond 403) ; les rôles du
   lien « Tableau de bord », la DG et le client gardent l'accès ;
2. module « Mes pièces » fermé pour un client : liste vide et pièce isolée
   refusée (403), tableau de bord sans pièces ;
3. la DG a les mêmes droits que la Direction sur chaque lien de son menu
   (Paie & RH, Comptabilité OHADA, Diffusion, WhatsApp, Journal plateforme,
   « Derniers clients connectés », badges).
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
import albarka_badges  # noqa: E402
import albarka_dashboard  # noqa: E402
import albarka_documents  # noqa: E402
import albarka_ohada  # noqa: E402
import albarka_paie  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_presence  # noqa: E402
import albarka_wa_extras  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"], "is_active": True},
    "adm": {"id": "u-adm", "email": "adm@albarka.bf", "full_name": "Administrateur", "roles": ["administrateur"], "is_active": True},
    "caisse": {"id": "u-caisse", "email": "caisse@albarka.bf", "full_name": "Caissier", "roles": ["caissier"], "is_active": True},
    "admcompta": {"id": "u-ac", "email": "ac@albarka.bf", "full_name": "Admin comptable", "roles": ["administrateur", "comptable"], "is_active": True},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "Client", "roles": ["client"], "is_active": True},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot10_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    asyncio.run(mock_db.documents.insert_one({
        "id": "d1", "tenant_id": "c1", "status": "analyse", "original_filename": "facture.pdf",
        "kind": "piece_comptable", "storage_path": "x/facture.pdf", "created_at": "2026-09-01",
    }))

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_dashboard.router, albarka_documents.router, albarka_phase_c.hr_router,
              albarka_phase_c.logs_router, albarka_phase_c.messaging_router, albarka_paie.router,
              albarka_ohada.router, albarka_wa_extras.router, albarka_badges.router,
              albarka_presence.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _h(u):
    return {"X-User": u}


DASHBOARD = ("/api/dashboard/summary", "/api/dashboard/activity", "/api/dashboard/dispatches")


# --- 1. Tableau de bord du cabinet ------------------------------------------
def test_dashboard_refused_to_administrateur_or_caissier_alone(env):
    for who in ("adm", "caisse"):
        for path in DASHBOARD:
            assert env.c.get(path, headers=_h(who)).status_code == 403, (who, path)


def test_dashboard_open_to_dashboard_roles_dg_and_client(env):
    for who in ("sup", "dir", "dg", "compta", "rh", "admcompta", "c1"):
        for path in DASHBOARD:
            assert env.c.get(path, headers=_h(who)).status_code == 200, (who, path)
    # Le cabinet voit les compteurs globaux, le client jamais
    assert env.c.get("/api/dashboard/summary", headers=_h("dg")).json()["clients_total"] == 1
    assert env.c.get("/api/dashboard/summary", headers=_h("c1")).json()["clients_total"] is None


# --- 2. Module « Mes pièces » fermé côté client ------------------------------
def test_closed_documents_module_hides_everything(env):
    # Module ouvert (aucun réglage) : la pièce est visible
    assert len(env.c.get("/api/documents", headers=_h("c1")).json()) == 1
    assert env.c.get("/api/documents/d1", headers=_h("c1")).status_code == 200
    assert env.c.get("/api/dashboard/summary", headers=_h("c1")).json()["documents_total"] == 1

    asyncio.run(env.db.users.update_one({"id": "c1"}, {"$set": {"portal_modules": ["missions"]}}))
    assert env.c.get("/api/documents", headers=_h("c1")).json() == []
    for path in ("/api/documents/d1", "/api/documents/d1/download-url", "/api/documents/d1/download"):
        assert env.c.get(path, headers=_h("c1")).status_code == 403, path
    assert env.c.delete("/api/documents/d1", headers=_h("c1")).status_code == 403
    assert asyncio.run(env.db.documents.count_documents({"id": "d1"})) == 1
    assert env.c.get("/api/dashboard/summary", headers=_h("c1")).json()["documents_total"] == 0
    assert env.c.get("/api/dashboard/activity", headers=_h("c1")).json()["documents"] == []
    # Le cabinet, lui, voit toujours la pièce
    assert env.c.get("/api/documents/d1", headers=_h("dir")).status_code == 200


# --- 3. La DG = la Direction, lien par lien ----------------------------------
DG_LINKS = (
    "/api/hr/employees",                     # Paie & RH
    "/api/hr/paie/modeles",                  # Paie & RH — bulletins
    "/api/accounting/accounts?tenant_id=c1",  # Comptabilité OHADA
    "/api/messaging/broadcasts",             # Diffusion
    "/api/whatsapp/quick-replies",           # WhatsApp
    "/api/platform-logs",                    # Journal plateforme
    "/api/presence/recent-clients",          # Tableau de bord — derniers clients connectés
)


def test_dg_has_direction_rights_on_each_menu_link(env):
    for path in DG_LINKS:
        assert env.c.get(path, headers=_h("dir")).status_code == 200, ("dir", path)
        assert env.c.get(path, headers=_h("dg")).status_code == 200, ("dg", path)
    # Toujours refusé à un rôle sans ce lien (ex. Comptable sur la Diffusion)
    assert env.c.get("/api/messaging/broadcasts", headers=_h("compta")).status_code == 403
    assert env.c.get("/api/platform-logs", headers=_h("compta")).status_code == 403


def test_dg_badges_counted(env):
    asyncio.run(env.db.wa_messages.insert_one({"id": "w1", "direction": "inbound", "read_by_staff_at": None}))
    assert env.c.get("/api/me/badges", headers=_h("dg")).json()["wa_unread"] == 1
    assert env.c.get("/api/me/badges", headers=_h("compta")).json()["wa_unread"] == 0


def test_frontend_lot10():
    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    layout = (front / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    # Lien « Tableau de bord » : plus l'Administrateur (identique à DASHBOARD_ROLES)
    assert 'roles: ["superviseur", "direction", "secretariat", "fiscaliste", "comptable", "aide_comptable", "rh"] },' in layout
    assert '{!leaveDashboard && !closedModulePage && <Outlet />}' in layout
    assert 'l.to === "/admin/staff" && allowedFor(l, roles, user?.email)' in layout
    dashboard = (front / "pages" / "portal" / "Dashboard.jsx").read_text(encoding="utf-8")
    assert '{showDocs && (' in dashboard and 'moduleOpen(user, "documents", admin)' in dashboard
    history = (front / "pages" / "portal" / "Historique.jsx").read_text(encoding="utf-8")
    assert "moduleOpen(user, m)" in history
    # Version au moins égale à celle du lot 10 (les lots suivants l'augmentent)
    import re
    found = re.search(r'APP_VERSION = "v2026\.(\d+)"', (front / "version.js").read_text(encoding="utf-8"))
    assert found and int(found.group(1)) >= 10
