"""Lot 94 — Services Web : montant UNIQUE réglé en plusieurs fois, paiements reçus par SMS sélectionnés (une seule utilisation), reste à payer."""
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

USERS = {"sup": {"id": "u1", "email": "s@a.bf", "full_name": "Super", "roles": ["superviseur"]},
         "dg": {"id": "u2", "email": "dg@a.bf", "full_name": "DG", "roles": ["dg"]}}


def sms(i, montant, jour, ref=None):
    return {"id": f"t{i}", "recu_le": f"2026-11-{jour:02d}T10:00:00+00:00", "montant": montant, "tiers": "Payeur", "numero": "+226 70 11 22 33", "reference": ref, "operateur": "Orange Money", "client": "Cabinet"}


TRANSACTIONS = [sms(1, 50000, 2, "PP1"), sms(2, 50000, 5, "PP2"), sms(3, 50000, 9), sms(4, 50000, 12, "PP4"), sms(5, 25000, 13, "PP5")]


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot94"]
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

    async def faux_sawali(chemin, corps, delai=15):
        return {"plateforme": "albarka", "total": len(TRANSACTIONS), "transactions": TRANSACTIONS}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    return TestClient(app)


H = {"X-User": "sup"}


def test_service_a_montant_unique_et_reste_a_payer(env):
    r = env.post("/api/admin/services-web", json={"service": "Création du site", "montant": 250000, "mode": "unique"}, headers=H)
    assert r.status_code == 200
    s = r.json()
    assert s["mode"] == "unique" and s["jour_du_mois"] is None and s["payable_avant"] is None and s["etat"] == "impaye" and s["reste_a_payer"] == 250000
    # 4 paiements de 50 000 F reçus par SMS : reste à payer 50 000 F
    r = env.post(f"/api/admin/services-web/{s['id']}/paiements-sms", json={"sms_ids": ["t1", "t2", "t3", "t4"]}, headers=H)
    assert r.status_code == 200
    v = r.json()
    assert v["total_paye"] == 200000 and v["reste_a_payer"] == 50000 and v["etat"] == "partiel" and len(v["paiements"]) == 4
    assert [p["reference"] for p in v["paiements"]][:2] == ["PP1", "PP2"] and v["paiements"][2]["reference"].startswith("SMS 2026-11-09")
    # un 5e paiement solde le service
    v = env.post(f"/api/admin/services-web/{s['id']}/paiements-sms", json={"sms_ids": ["t5"]}, headers=H).json()
    assert v["total_paye"] == 225000 and v["reste_a_payer"] == 25000
    # pas de rappel mensuel pour un montant unique
    assert env.get("/api/me/services-web/rappels", headers={"X-User": "dg"}).json() == {"rappels": []}
    assert env.post("/api/me/services-web/rappels/ack", json={"cles": ["x"]}, headers={"X-User": "dg"}).status_code == 200


def test_un_paiement_sms_ne_sert_qu_une_fois(env):
    a = env.post("/api/admin/services-web", json={"service": "Logo", "montant": 100000, "mode": "unique"}, headers=H).json()
    b = env.post("/api/admin/services-web", json={"service": "Domaine", "montant": 80000, "mode": "unique"}, headers=H).json()
    assert env.post(f"/api/admin/services-web/{a['id']}/paiements-sms", json={"sms_ids": ["t1", "t2"]}, headers=H).status_code == 200
    # déjà utilisé : refusé pour un autre service, et pour le même
    r = env.post(f"/api/admin/services-web/{b['id']}/paiements-sms", json={"sms_ids": ["t2", "t3"]}, headers=H)
    assert r.status_code == 409 and "Logo" in r.json()["detail"]
    assert env.post(f"/api/admin/services-web/{a['id']}/paiements-sms", json={"sms_ids": ["t1"]}, headers=H).status_code == 409
    assert env.post(f"/api/admin/services-web/{b['id']}/paiements-sms", json={"sms_ids": ["inconnu"]}, headers=H).status_code == 404
    # rien n'a été enregistré par la tentative refusée (t3 reste libre)
    liste = {t["id"]: t for t in env.get("/api/admin/services-web/paiements-sms", headers=H).json()["transactions"]}
    assert liste["t1"]["deja_utilise"] and liste["t1"]["utilise_par"] == "Logo" and not liste["t3"]["deja_utilise"]
    # annuler le paiement du service A libère le paiement SMS pour B
    pid = env.get("/api/admin/services-web", headers=H).json()["services"]
    pa = next(x for x in pid if x["id"] == a["id"])["paiements"][1]["id"]
    assert env.delete(f"/api/admin/services-web/{a['id']}/paiements/{pa}", headers=H).json()["total_paye"] == 50000
    assert env.post(f"/api/admin/services-web/{b['id']}/paiements-sms", json={"sms_ids": ["t2"]}, headers=H).status_code == 200


def test_service_mensuel_chaque_sms_regle_une_echeance(env):
    s = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 8}, headers=H).json()
    assert s["mode"] == "mensuel" and s["jour_du_mois"] == 8 and s["reste_a_payer"] is None
    avant = s["payable_avant"]
    v = env.post(f"/api/admin/services-web/{s['id']}/paiements-sms", json={"sms_ids": ["t1", "t2"]}, headers=H).json()
    assert v["payable_avant"] > avant and len(v["paiements"]) == 2                       # deux échéances réglées : l'échéance recule de deux mois
    d1 = v["payable_avant"]
    pid = v["paiements"][-1]["id"]
    assert env.delete(f"/api/admin/services-web/{s['id']}/paiements/{v['paiements'][0]['id']}", headers=H).status_code == 409     # seul le dernier s'annule
    v2 = env.delete(f"/api/admin/services-web/{s['id']}/paiements/{pid}", headers=H).json()
    assert v2["payable_avant"] < d1 and len(v2["paiements"]) == 1


def test_paiement_manuel_dans_l_historique_et_droits(env):
    u = env.post("/api/admin/services-web", json={"service": "Maquette", "montant": 60000, "mode": "unique"}, headers=H).json()
    v = env.post(f"/api/admin/services-web/{u['id']}/paiement", json={"paye_le": "2026-11-12T14:30", "montant": 20000, "reference": "ESP-1"}, headers=H).json()
    assert v["total_paye"] == 20000 and v["reste_a_payer"] == 40000 and v["paiements"][0]["source"] == "manuel"
    # validations et droits
    assert env.post("/api/admin/services-web", json={"service": "X", "montant": 1, "mode": "mensuel"}, headers=H).status_code == 422          # jour du mois requis
    assert env.post("/api/admin/services-web", json={"service": "X", "montant": 1, "mode": "autre"}, headers=H).status_code == 422
    for role in ("dg",):
        assert env.post(f"/api/admin/services-web/{u['id']}/paiements-sms", json={"sms_ids": ["t1"]}, headers={"X-User": role}).status_code == 403
        assert env.delete(f"/api/admin/services-web/{u['id']}/paiements/x", headers={"X-User": role}).status_code == 403
    # le DG (consultation) voit le reste à payer et l'historique, en lecture seule
    vue = env.get("/api/me/services-web", headers={"X-User": "dg"}).json()["services"][0]
    assert vue["reste_a_payer"] == 40000 and len(vue["paiements"]) == 1 and "echeance_avant" not in vue["paiements"][0]
