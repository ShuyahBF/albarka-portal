"""Lot 93 — Services Web : paiements reçus par SMS (SAWALI → Transactions SMS) proposés au super-admin pour renseigner « dernier paiement »."""
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
import albarka_support_sawali  # noqa: E402
import db as db_module  # noqa: E402

USERS = {"sup": {"id": "u1", "email": "s@albarka.bf", "full_name": "Super", "roles": ["superviseur"]},
         "dg": {"id": "u2", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"]}}

TRANSACTIONS = [
    {"id": "a1", "recu_le": "2026-11-12T14:30:00+00:00", "montant": 25000, "tiers": "OUEDRAOGO Awa", "numero": "70112233", "reference": "MP261112.1430.55", "operateur": "Orange Money", "client": "Cabinet Dr BADINI"},
    {"id": "a2", "recu_le": "2026-10-08T09:05:00+00:00", "montant": 25000, "tiers": "OUEDRAOGO Awa", "numero": "70112233", "reference": None, "operateur": "Moov Money", "client": "Cabinet Dr BADINI"},
    {"id": "a3", "recu_le": None, "montant": 5},                                    # inutilisable : ignoré
]


def test_preparation_pure():
    services = [{"dernier_paiement_reference": "MP261112.1430.55"}]
    t = sw.preparer_transactions_sms(TRANSACTIONS, services)
    assert [x["id"] for x in t] == ["a1", "a2"]
    assert t[0]["deja_enregistre"] is True and t[0]["recu_le"] == "2026-11-12T14:30"
    assert t[1]["deja_enregistre"] is False and t[1]["reference_proposee"] == "SMS 2026-10-08T09:05 25000"      # pas de numéro de transaction : référence construite
    assert sw.preparer_transactions_sms(None, []) == []


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot93"]
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


def test_route_super_admin_seulement_et_relecture_signee(env, monkeypatch):
    appels = {}

    async def faux_sawali(chemin, corps, delai=15):
        appels["chemin"], appels["corps"] = chemin, corps
        return {"plateforme": "albarka", "total": 3, "transactions": TRANSACTIONS}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    assert env.get("/api/admin/services-web/paiements-sms", headers={"X-User": "dg"}).status_code == 403          # le DG ne voit pas ces transactions
    r = env.get("/api/admin/services-web/paiements-sms", headers={"X-User": "sup"})
    assert r.status_code == 200 and [t["id"] for t in r.json()["transactions"]] == ["a1", "a2"]
    assert appels["chemin"] == "/webhook/plateforme-paiements" and appels["corps"]["sens"] == "entree"
