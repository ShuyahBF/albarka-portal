"""Lot 90 — « Mes Services Web » : le super-admin configure, le DG seul voit et est rappelé (7 j, 3 j, jour même, retard)."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import date, timedelta
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
import albarka_auth  # noqa: E402
import albarka_services_web as sw  # noqa: E402

USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Super", "roles": ["superviseur"]},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg", "direction"]},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"]},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot90"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(sw.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[sw.get_current_user] = fake_user
    client = TestClient(app)
    client.db = mock_db
    return client


def _jour_dans(n: int) -> int:
    """Jour du mois (1-28) d'une date située dans n jours : sert à fabriquer une échéance proche."""
    return min((date.today() + timedelta(days=n)).day, 28)


def _creer(c, nom="Hébergement Render", jours=7):
    """Crée un service dont l'échéance tombe dans `jours` jours (jour du mois de cette date)."""
    r = c.post("/api/admin/services-web", json={"service": nom, "montant": 25000, "jour_du_mois": (date.today() + timedelta(days=jours)).day}, headers={"X-User": "sup"})
    assert r.status_code == 200, r.text
    return r.json()


def test_droits_separes(env):
    s = _creer(env)
    assert env.post("/api/admin/services-web", json={"service": "x", "montant": 1, "jour_du_mois": 8}, headers={"X-User": "dg"}).status_code == 403
    for qui in ("sup", "dir"):
        assert env.get("/api/me/services-web", headers={"X-User": qui}).status_code == 403
        assert env.get("/api/me/services-web/rappels", headers={"X-User": qui}).status_code == 403
    r = env.get("/api/me/services-web", headers={"X-User": "dg"})
    assert r.status_code == 200 and r.json()["services"][0]["id"] == s["id"]
    assert "acquittements" not in r.text


def test_occurrences_mensuelles():
    assert sw.occurrence(2026, 2, 31) == date(2026, 2, 28)               # mois court : dernier jour
    assert sw.occurrence(2028, 2, 31) == date(2028, 2, 29)               # année bissextile
    assert sw.mois_suivant(date(2026, 12, 8), 8) == date(2027, 1, 8)
    assert sw.mois_suivant(date(2026, 1, 31), 31) == date(2026, 2, 28)
    assert sw.mois_suivant(date(2026, 2, 28), 31) == date(2026, 3, 31)   # le jour d'origine est retrouvé


@pytest.mark.parametrize("jours,palier,etat", [(10, None, "a_jour"), (7, "7", "bientot"), (4, "7", "bientot"), (3, "3", "bientot"),
                                                  (1, "3", "bientot"), (0, "0", "aujourdhui"), (-2, "retard", "en_retard")])
def test_paliers_et_etats(jours, palier, etat):
    doc = {"jour_du_mois": 1, "premiere_echeance": (date.today() + timedelta(days=jours)).isoformat()}
    p = sw.palier_courant(doc)
    assert (p.split("-")[0] if p else None) == palier
    assert sw.etat_service(doc)["etat"] == etat


def test_rappel_puis_acquittement_unique_par_palier(env):
    _creer(env, jours=3)
    rap = env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json()["rappels"]
    assert len(rap) == 1 and rap[0]["palier"] == "3"
    assert env.post("/api/me/services-web/rappels/ack", json={"cles": [rap[0]["cle"]]}, headers={"X-User": "dg"}).status_code == 200
    assert env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json()["rappels"] == []
    assert env.post("/api/me/services-web/rappels/ack", json={"cles": ["2099-01-01:7"]}, headers={"X-User": "dg"}).status_code == 200


def test_paiement_passe_au_mois_suivant_et_le_rappel_revient_chaque_mois(env):
    s = _creer(env, jours=0)                                        # échéance aujourd'hui
    assert len(env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json()["rappels"]) == 1
    corps = {"paye_le": "2026-11-12T14:30", "montant": 25000, "reference": "TX-8841"}
    assert env.post(f"/api/admin/services-web/{s['id']}/paiement", json=corps, headers={"X-User": "dg"}).status_code == 403
    r = env.post(f"/api/admin/services-web/{s['id']}/paiement", json=corps, headers={"X-User": "sup"})
    assert r.status_code == 200 and r.json()["dernier_paiement_reference"] == "TX-8841"
    vue = env.get("/api/me/services-web", headers={"X-User": "dg"}).json()["services"][0]
    # Le paiement règle l'échéance du jour : la suivante est le même jour le mois prochain, plus de rappel d'ici là
    assert vue["dernier_paiement_le"] == "2026-11-12T14:30" and vue["etat"] == "a_jour" and vue["jours_restants"] >= 28
    assert vue["payable_avant"] == sw.mois_suivant(date.today(), s["jour_du_mois"]).isoformat()
    assert env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json()["rappels"] == []


def test_impaye_reste_en_retard_et_rappele(env):
    asyncio.run(env.db.services_web.insert_one({
        "id": "s9", "service": "Domaine", "montant": 5000, "devise": "FCFA", "jour_du_mois": 8,
        "premiere_echeance": (date.today() - timedelta(days=3)).isoformat(), "echeance_payee": None, "acquittements": []}))
    v = env.get("/api/me/services-web", headers={"X-User": "dg"}).json()["services"][0]
    assert v["en_retard"] is True and v["jours_restants"] == -3
    assert env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json()["rappels"][0]["palier"].startswith("retard-")


def test_ancien_service_a_date_unique_reste_lisible(env):
    asyncio.run(env.db.services_web.insert_one({
        "id": "old", "service": "Ancien", "montant": 1, "devise": "FCFA", "payable_avant": (date.today() + timedelta(days=2)).isoformat(),
        "paye_echeance": False, "acquittements": []}))
    v = env.get("/api/me/services-web", headers={"X-User": "dg"}).json()["services"][0]
    assert v["jours_restants"] == 2 and v["jour_du_mois"] == (date.today() + timedelta(days=2)).day


def test_validations(env):
    assert env.post("/api/admin/services-web", json={"service": "x", "montant": 1, "jour_du_mois": 32}, headers={"X-User": "sup"}).status_code == 422
    assert env.post("/api/admin/services-web", json={"service": "x", "montant": 1, "jour_du_mois": 0}, headers={"X-User": "sup"}).status_code == 422
    s = _creer(env)
    assert env.post(f"/api/admin/services-web/{s['id']}/paiement", json={"paye_le": "hier", "montant": 1, "reference": "r"}, headers={"X-User": "sup"}).status_code == 422
    assert env.put(f"/api/admin/services-web/{s['id']}", json={"jour_du_mois": 15}, headers={"X-User": "sup"}).json()["jour_du_mois"] == 15
    assert env.delete(f"/api/admin/services-web/{s['id']}", headers={"X-User": "sup"}).status_code == 200
