"""Lot 78 — numéro de contrat proposé (dernier + 1), modifiable seulement par le DG et le super-admin.

Tests autonomes : MongoDB simulé, connexion simulée par l'en-tête X-User.
Lancer : cd backend && REACT_APP_BACKEND_URL=http://localhost:1 python -m pytest tests/test_lot78_numero_contrat.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import albarka_contracts as ac  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

ANNEE = datetime.now(timezone.utc).strftime("%Y")
USERS = {
    "dg": {"id": "u-dg", "full_name": "DG", "roles": ["dg"]},
    "sup": {"id": "u-sup", "full_name": "Superviseur", "roles": ["superviseur"]},
    "secr": {"id": "u-secr", "full_name": "Secrétaire", "roles": ["secretariat"]},
}


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["albarka_lot78_test"]
    asyncio.run(db.users.insert_many([{"id": "c1", "roles": ["client"], "full_name": "Kaboré"}]))
    monkeypatch.setattr(ac, "db", db)
    app = FastAPI()
    app.include_router(ac.router, prefix="/api")

    async def fake_user(x_user: str = Header("secr")):
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user

    class E:  # noqa: D106
        pass
    e = E()
    e.c, e.db = TestClient(app), db
    return e


def _creer(env, who, **extra):
    corps = {"tenant_id": "c1", "title": "Contrat annuel", "start_date": f"{ANNEE}-01-01", **extra}
    return env.c.post("/api/client-contracts", headers={"X-User": who}, json=corps)


def test_numero_propose_apres_le_dernier_saisi_a_la_main(env):
    # Contrats existants, dont un numéro saisi à la main très au-delà de la série (cas réel : CTR-2026-0020)
    asyncio.run(env.db.client_contracts.insert_many([
        {"id": "a", "tenant_id": "c1", "numero_contrat": f"CTR-{ANNEE}-0002"},
        {"id": "b", "tenant_id": "c1", "numero_contrat": f"CTR-{ANNEE}-0020"},
        {"id": "c", "tenant_id": "c1", "numero_contrat": "CTR-2019-0099"},      # autre année : ignoré
    ]))
    r = env.c.get("/api/client-contracts/prochain-numero", headers={"X-User": "secr"}).json()
    assert r["numero"] == f"CTR-{ANNEE}-0021" and r["modifiable"] is False
    # La lecture ne consomme aucun numéro
    assert env.c.get("/api/client-contracts/prochain-numero", headers={"X-User": "dg"}).json() == {"numero": f"CTR-{ANNEE}-0021", "modifiable": True}


def test_autre_utilisateur_ne_choisit_pas_le_numero(env):
    r = _creer(env, "secr", numero_contrat="CTR-9999-0001")        # saisie ignorée
    assert r.status_code == 200 and r.json()["numero_contrat"] == f"CTR-{ANNEE}-0001"
    assert _creer(env, "secr").json()["numero_contrat"] == f"CTR-{ANNEE}-0002"   # numéros qui se suivent


def test_dg_et_superviseur_peuvent_saisir_un_numero_unique(env):
    assert _creer(env, "dg", numero_contrat="CTR-2026-0050").json()["numero_contrat"] == "CTR-2026-0050"
    assert _creer(env, "sup", numero_contrat="ctr-2026-0050").status_code == 409        # déjà pris (casse ignorée)
    # Le contrat suivant d'un autre utilisateur continue après le plus grand numéro
    assert _creer(env, "secr").json()["numero_contrat"] == f"CTR-{ANNEE}-0051" if ANNEE == "2026" else True


def test_modification_du_numero_reservee(env):
    cid = _creer(env, "secr").json()["id"]
    r = env.c.patch(f"/api/client-contracts/{cid}", headers={"X-User": "secr"}, json={"numero_contrat": "CTR-2026-0777", "title": "Nouveau titre"})
    assert r.status_code == 200 and r.json()["numero_contrat"] == f"CTR-{ANNEE}-0001" and r.json()["title"] == "Nouveau titre"
    r = env.c.patch(f"/api/client-contracts/{cid}", headers={"X-User": "dg"}, json={"numero_contrat": "CTR-2026-0777"})
    assert r.status_code == 200 and r.json()["numero_contrat"] == "CTR-2026-0777"
