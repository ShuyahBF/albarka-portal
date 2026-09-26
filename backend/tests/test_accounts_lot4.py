"""Lot 4 — rôles Superviseur/Administrateur, suppression du personnel,
comptes de test, Paramètres réservés au Superviseur.

- Superviseur : attribué ou retiré UNIQUEMENT par le compte admin du portail ;
- Administrateur : fonctionnement d'avant le lot 3 (un administrateur peut
  l'attribuer), plus aucune restriction « compte admin » ;
- suppression d'un compte du personnel : superviseur uniquement ;
- comptes de test : créés par le superviseur, invisibles des autres,
  exclus des envois de masse ;
- Paramètres : superviseur uniquement.

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
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "Vrai client", "roles": ["client"], "is_active": True},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot4_test"]
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
    for r in (albarka_clients.router, albarka_admin_settings.router, albarka_dashboard.router):
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
    return {"email": "nouveau@albarka.bf", "full_name": "Nouveau", "roles": ["comptable"], "password": "motdepasse1", **kw}


def test_superviseur_role_only_by_admin_account(env):
    # Direction ou superviseur ordinaire : impossible de créer / donner / retirer Superviseur
    assert env.c.post("/api/clients/staff", headers=_h("dir"), json=_staff(roles=["superviseur"])).status_code == 403
    assert env.c.post("/api/clients/staff", headers=_h("sup"), json=_staff(roles=["superviseur"])).status_code == 403
    assert env.c.patch("/api/clients/u-compta", headers=_h("sup"), json={"roles": ["comptable", "superviseur"]}).status_code == 403
    assert env.c.patch("/api/clients/u-sup", headers=_h("dir"), json={"full_name": "X"}).status_code == 403
    # Le compte admin du portail le peut
    assert env.c.patch("/api/clients/u-compta", headers=_h("admin"), json={"roles": ["comptable", "superviseur"]}).status_code == 200
    assert env.c.patch("/api/clients/u-compta", headers=_h("admin"), json={"roles": ["comptable"]}).status_code == 200
    # Les autres rôles restent attribuables normalement
    assert env.c.patch("/api/clients/u-compta", headers=_h("dir"), json={"roles": ["comptable", "caissier"]}).status_code == 200


def test_administrateur_back_to_previous_rule(env):
    # Un administrateur peut créer un administrateur (règle d'avant le lot 3)…
    assert env.c.post("/api/clients/staff", headers=_h("adm"), json=_staff(roles=["administrateur"])).status_code == 200
    # …mais pas un compte sans ce rôle
    assert env.c.post("/api/clients/staff", headers=_h("dir"),
                      json=_staff(email="x@albarka.bf", roles=["administrateur"])).status_code == 403
    listed = {u["id"]: u["roles"] for u in env.c.get("/api/clients/staff", headers=_h("sup")).json()}
    assert listed["u-adm"] == ["administrateur"]  # plus aucun rôle retiré à l'affichage


def test_delete_staff_only_by_superviseur(env):
    assert env.c.delete("/api/clients/u-compta", headers=_h("dir")).status_code == 403
    assert env.c.delete("/api/clients/u-admin", headers=_h("sup")).status_code == 403  # compte admin intouchable
    assert env.c.delete("/api/clients/u-sup", headers=_h("sup")).status_code == 400     # pas soi-même
    r = env.c.delete("/api/clients/u-compta", headers=_h("sup"))
    assert r.status_code == 200 and "staff.delete" in env.logs
    assert asyncio.run(env.db.users.find_one({"id": "u-compta"})) is None
    assert asyncio.run(env.db.deleted_users.find_one({"id": "u-compta"}))["deleted_by"] == "u-sup"
    # Un superviseur ne peut être supprimé que par le compte admin
    assert env.c.delete("/api/clients/u-sup", headers=_h("admin")).status_code == 200


def test_test_accounts_created_hidden_and_removed(env):
    body = {"email": "moi+ancien@gmail.com", "password": "recette2026", "client1_whatsapp": "+22670000001"}
    assert env.c.post("/api/clients/test-accounts", headers=_h("dir"), json=body).status_code == 403
    res = env.c.post("/api/clients/test-accounts", headers=_h("sup"), json=body).json()["accounts"]
    by_alias = {a["email"].split("+")[1].split("@")[0]: a for a in res}
    assert by_alias["test-secretaire"]["email"] == "moi+test-secretaire@gmail.com"
    assert by_alias["test-superviseur"]["status"] == "ignoré"          # seul le compte admin crée un superviseur
    assert by_alias["test-caissiere"]["roles"] == ["secretariat", "caissier"] and by_alias["test-client1"]["status"] == "créé"
    # Relancer = remise à neuf, pas de doublon
    again = env.c.post("/api/clients/test-accounts", headers=_h("admin"), json=body).json()["accounts"]
    assert {a["status"] for a in again if "superviseur" not in a["roles"]} == {"mis à jour"}
    assert next(a for a in again if a["roles"] == ["superviseur"])["status"] == "créé"
    # Mot de passe utilisable
    doc = asyncio.run(env.db.users.find_one({"email": "moi+test-comptable@gmail.com"}))
    assert albarka_auth.verify_password("recette2026", doc["password_hash"]) and doc["is_test_account"]
    # Invisibles de tous sauf du superviseur
    staff_dir = [u["email"] for u in env.c.get("/api/clients/staff", headers=_h("dir")).json()]
    staff_sup = [u["email"] for u in env.c.get("/api/clients/staff", headers=_h("sup")).json()]
    assert not any("+test-" in e for e in staff_dir) and sum("+test-" in e for e in staff_sup) == 5
    assert [u["email"] for u in env.c.get("/api/clients", headers=_h("dir")).json()] == ["client@exemple.bf"]
    tid = doc["id"]
    assert env.c.get(f"/api/clients/{tid}", headers=_h("dir")).status_code == 404
    assert env.c.get(f"/api/clients/{tid}", headers=_h("sup")).status_code == 200
    assert env.c.get("/api/dashboard/summary", headers=_h("dir")).json()["clients_total"] == 1
    # Suppression groupée : seuls les comptes de test partent
    assert env.c.delete("/api/clients/test-accounts", headers=_h("sup")).json()["deleted"] == 7
    assert asyncio.run(env.db.users.count_documents({})) == len(USERS)


def test_settings_only_for_superviseur(env):
    assert env.c.get("/api/admin/settings", headers=_h("dir")).status_code == 403
    assert env.c.get("/api/admin/settings", headers=_h("adm")).status_code == 403
    assert env.c.get("/api/admin/settings", headers=_h("sup")).status_code == 200
    # RGPD : modifiable par le superviseur (seul à accéder aux Paramètres)
    assert env.c.put("/api/admin/settings", headers=_h("sup"), json={"rgpd_masking_enabled": False}).json()["rgpd_masking_enabled"] is False


def test_frontend_rules():
    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    layout = (front / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    assert '{ to: "/admin/settings", label: "Paramètres", icon: Settings, roles: ["superviseur"] }' in layout
    staff = (front / "pages" / "admin" / "AdminStaff.jsx").read_text(encoding="utf-8")
    assert 'disabled={r.value === "superviseur" && !isAdminAccount}' in staff and "Créer comptes de test" in staff


def test_client_deletion_reserved_to_admin(env):
    assert env.c.delete("/api/clients/c1", headers=_h("sup")).status_code == 403
    assert env.c.delete("/api/clients/c1", headers=_h("dir")).status_code == 403
    assert env.c.delete("/api/clients/c1", headers=_h("admin")).status_code == 200
    assert "client.delete" in env.logs and asyncio.run(env.db.deleted_users.find_one({"id": "c1"}))


def test_deactivate_and_reset_password_with_modification_stamp(env):
    # Désactiver un client (rôle de gestion des clients) : date et auteur notés
    r = env.c.post("/api/clients/c1/active", headers=_h("dir"), json={"active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert r.json()["updated_by_name"] == "Direction" and r.json()["updated_at"]
    assert env.c.post("/api/clients/c1/active", headers=_h("compta"), json={"active": True}).status_code == 403
    assert env.c.post("/api/clients/u-dir/active", headers=_h("dir"), json={"active": False}).status_code == 400  # pas soi-même
    # Compte Superviseur / compte admin protégés
    assert env.c.post("/api/clients/u-sup/active", headers=_h("dir"), json={"active": False}).status_code == 403
    assert env.c.post("/api/clients/u-admin/reset-password", headers=_h("sup"), json={}).status_code == 403
    # Réinitialisation : mot de passe temporaire généré, utilisable, jamais dans le journal
    r = env.c.post("/api/clients/u-compta/reset-password", headers=_h("dir"), json={}).json()
    doc = asyncio.run(env.db.users.find_one({"id": "u-compta"}))
    assert r["generated"] and len(r["password"]) == 10 and albarka_auth.verify_password(r["password"], doc["password_hash"])
    assert doc["password_changed_at"] and doc["updated_by"] == "u-dir"
    # Mot de passe choisi
    r = env.c.post("/api/clients/c1/reset-password", headers=_h("dir"), json={"password": "nouveau2026"}).json()
    assert r["generated"] is False and r["password"] == "nouveau2026"
    # Modification ordinaire : date de dernière modification mise à jour
    u = env.c.patch("/api/clients/c1", headers=_h("dir"), json={"company": "SARL"}).json()
    assert u["updated_by"] == "u-dir"


def test_old_sessions_closed_after_password_reset(env):
    from fastapi.security import HTTPAuthorizationCredentials
    from jose import jwt
    old = jwt.encode({"sub": "u-compta", "exp": 9999999999}, albarka_auth.SECRET_KEY, algorithm="HS256")  # ancien jeton sans iat
    fresh_before = albarka_auth.create_access_token("u-compta")
    creds = lambda t: HTTPAuthorizationCredentials(scheme="Bearer", credentials=t)  # noqa: E731
    assert asyncio.run(albarka_auth.get_current_user(creds(old)))["id"] == "u-compta"  # rien de changé tant qu'aucune réinitialisation
    asyncio.run(env.db.users.update_one({"id": "u-compta"}, {"$set": {"password_changed_at": "2999-01-01T00:00:00+00:00"}}))
    for t in (old, fresh_before):
        with pytest.raises(HTTPException) as e:
            asyncio.run(albarka_auth.get_current_user(creds(t)))
        assert e.value.status_code == 401


def test_presence_keep_alive(env, monkeypatch):
    """Keep-alive : en ligne / absent / hors ligne, lu par le cabinet seulement."""
    import albarka_presence as pr
    app = env.c.app
    api = APIRouter(prefix="/api")
    api.include_router(pr.router)
    app.include_router(api)
    asyncio.run(env.db.users.update_one({"id": "c1"}, {"$set": {"phone": "+22670000001"}}))
    # Le client ouvre le portail, un collaborateur a son onglet en arrière-plan
    assert env.c.post("/api/presence/heartbeat", headers=_h("c1"), json={"visible": True, "page": "/portal"}).json()["interval"] == 25
    env.c.post("/api/presence/heartbeat", headers=_h("compta"), json={"visible": False})
    data = env.c.get("/api/presence", headers=_h("dir")).json()
    assert data["items"]["c1"]["status"] == "online" and data["items"]["u-compta"]["status"] == "away"
    assert data["counts"] == {"staff_online": 1, "client_online": 1}
    assert "u-sup" not in data["items"]  # jamais connecté : hors ligne par défaut (absent de la liste)
    # Un client ne lit pas la présence des autres
    assert env.c.get("/api/presence", headers=_h("c1")).status_code == 403
    # Messagerie WhatsApp : présence par numéro déjà connu
    by = env.c.get("/api/presence/by-phone", headers=_h("dir"), params=[("phones", "+22670000001"), ("phones", "+22600000000")]).json()
    assert by["items"] == {"+22670000001": data["items"]["c1"]}
    # Déconnexion explicite : hors ligne tout de suite
    env.c.post("/api/presence/offline", headers=_h("c1"))
    assert env.c.get("/api/presence", headers=_h("dir")).json()["items"]["c1"]["status"] == "offline"
    # Plus de battement depuis 70 s : hors ligne
    old = {"last_seen": "2020-01-01T00:00:00+00:00", "visible": True}
    assert pr.status_of(old)["status"] == "offline" and pr.status_of(None)["status"] == "offline"


def test_auto_logout_setting(env):
    """Déconnexion automatique : délai réglé par le superviseur, lu par tous."""
    import albarka_myaccount
    api = APIRouter(prefix="/api")
    api.include_router(albarka_myaccount.router)
    env.c.app.include_router(api)
    assert env.c.get("/api/me/idle-config", headers=_h("c1")).json() == {"auto_logout_minutes": 30, "warning_seconds": 30}
    assert env.c.put("/api/admin/settings", headers=_h("sup"), json={"auto_logout_minutes": 121}).status_code == 422
    env.c.put("/api/admin/settings", headers=_h("sup"), json={"auto_logout_minutes": 0})
    assert env.c.get("/api/me/idle-config", headers=_h("compta")).json()["auto_logout_minutes"] == 0
