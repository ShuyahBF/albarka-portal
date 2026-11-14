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


def test_service_mensuel_paiements_sms_echeance_un_mois_apres_le_dernier(env):
    s = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 8}, headers=H).json()
    assert s["mode"] == "mensuel" and s["jour_du_mois"] == 8 and s["reste_a_payer"] is None
    # deux paiements SMS (2 et 5 novembre) : l'échéance = 1 mois après le DERNIER (5/11 → 8/12), sur le jour 8
    v = env.post(f"/api/admin/services-web/{s['id']}/paiements-sms", json={"sms_ids": ["t1", "t2"]}, headers=H).json()
    assert v["payable_avant"] == "2026-12-08" and len(v["paiements"]) == 2
    # n'importe quel paiement s'annule ; l'échéance suit ceux qui restent
    v2 = env.delete(f"/api/admin/services-web/{s['id']}/paiements/{v['paiements'][0]['id']}", headers=H).json()
    assert len(v2["paiements"]) == 1 and v2["payable_avant"] == "2026-12-08"
    v3 = env.delete(f"/api/admin/services-web/{s['id']}/paiements/{v2['paiements'][0]['id']}", headers=H).json()
    assert v3["paiements"] == []


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


# ---------------------------------------------------------------- lot 96 : échéance = 1 mois après le dernier paiement constaté
from datetime import date  # noqa: E402


def test_prochaine_apres_paiement_pure():
    f = sw.prochaine_apres_paiement
    assert f(date(2026, 11, 20), 15) == date(2026, 12, 15)         # payé le 20/11 → cible 20/12 → 15/12
    assert f(date(2026, 11, 10), 15) == date(2026, 12, 15)         # payé le 10/11 (en avance) → 15/12
    assert f(date(2026, 11, 15), 15) == date(2026, 12, 15)         # payé à l'heure
    assert f(date(2026, 12, 1), 15) == date(2027, 1, 15)           # payé le 01/12 → cible 01/01 → 15/01 (le plus proche)
    assert f(date(2026, 12, 20), 15) == date(2027, 1, 15)          # passage d'année
    assert f(date(2026, 1, 31), 31) == date(2026, 2, 28)           # le 31 devient le dernier jour de février
    assert f(date(2026, 1, 15), 8) > date(2026, 1, 15)             # toujours après le paiement


def test_echeance_suit_le_dernier_paiement_constate(env):
    s = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 15}, headers=H).json()
    # nom modifiable
    assert env.put(f"/api/admin/services-web/{s['id']}", json={"service": "  Hébergement Render "}, headers=H).json()["service"] == "Hébergement Render"
    # paiements : l'échéance suit le paiement le plus RÉCENT (par date), même saisi avant un autre
    env.post(f"/api/admin/services-web/{s['id']}/paiement", json={"paye_le": "2026-11-20T10:00", "montant": 25000, "reference": "R2"}, headers=H)
    v = env.post(f"/api/admin/services-web/{s['id']}/paiement", json={"paye_le": "2026-10-18T10:00", "montant": 25000, "reference": "R1"}, headers=H).json()
    assert v["payable_avant"] == "2026-12-15" and v["jour_du_mois"] == 15
    # changer le jour du mois : recalcul sur le nouveau jour, d'après le dernier paiement
    assert env.put(f"/api/admin/services-web/{s['id']}", json={"jour_du_mois": 5}, headers=H).json()["payable_avant"] == "2026-12-05"
    env.put(f"/api/admin/services-web/{s['id']}", json={"jour_du_mois": 15}, headers=H)
    # annuler le paiement le plus récent (n'importe lequel peut l'être) : l'échéance suit celui qui reste (18/10 → 15/11)
    pid = next(p["id"] for p in v["paiements"] if p["reference"] == "R2")
    assert env.delete(f"/api/admin/services-web/{s['id']}/paiements/{pid}", headers=H).json()["payable_avant"] == "2026-11-15"
    # annuler le dernier restant : retour à l'état d'avant
    pid2 = env.get("/api/admin/services-web", headers=H).json()["services"][0]["paiements"][0]["id"]
    assert env.delete(f"/api/admin/services-web/{s['id']}/paiements/{pid2}", headers=H).json()["paiements"] == []


def test_recu_avec_prochaine_echeance_et_droits(env):
    m = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 15}, headers=H).json()
    v = env.post(f"/api/admin/services-web/{m['id']}/paiement", json={"paye_le": "2026-11-20T10:00", "montant": 25000, "reference": "R1"}, headers=H).json()
    pid = v["paiements"][0]["id"]
    r = env.get(f"/api/admin/services-web/{m['id']}/paiements/{pid}/recu", headers=H).json()
    assert r["numero"].startswith("RECU-SW-20261120-") and r["prochaine_echeance"] == "2026-12-15" and r["montant"] == 25000 and r["origine"] == "Saisi à la main"
    # montant unique : le reçu donne le payé cumulé et le reste à payer
    u = env.post("/api/admin/services-web", json={"service": "Création du site", "montant": 250000, "mode": "unique"}, headers=H).json()
    ids = [p["id"] for p in env.post(f"/api/admin/services-web/{u['id']}/paiements-sms", json={"sms_ids": ["t1", "t2", "t3"]}, headers=H).json()["paiements"]]
    r2 = env.get(f"/api/admin/services-web/{u['id']}/paiements/{ids[1]}/recu", headers=H).json()
    assert r2["total_paye_apres"] == 100000 and r2["reste_apres"] == 150000 and r2["prochaine_echeance"] is None and r2["origine"] == "SMS reçu"
    # droits : le DG lit (consultation), un autre rôle non ; reçu inexistant = 404
    assert env.get(f"/api/me/services-web/{m['id']}/paiements/{pid}/recu", headers={"X-User": "dg"}).status_code == 200
    assert env.get(f"/api/admin/services-web/{m['id']}/paiements/{pid}/recu", headers={"X-User": "dg"}).status_code == 403
    assert env.get(f"/api/admin/services-web/{m['id']}/paiements/inconnu/recu", headers=H).status_code == 404


def test_ancien_service_sans_historique_suit_son_dernier_paiement(env):
    """Cas de la capture du propriétaire : dernier paiement le 18/10, jour 15 → échéance le 15/11 (et non le 15/12), même pour un service créé avant le lot 94."""
    import asyncio
    base = db_module.db
    s = env.post("/api/admin/services-web", json={"service": "Frais META", "montant": 20000, "jour_du_mois": 15}, headers=H).json()
    asyncio.get_event_loop().run_until_complete(sw.db.services_web.update_one(
        {"id": s["id"]}, {"$set": {"dernier_paiement_le": "2026-10-18T19:54", "dernier_paiement_montant": 20000, "dernier_paiement_reference": "PP1", "prochaine_echeance": "2026-12-15", "echeance_payee": "2026-11-15"}}))
    v = env.get("/api/admin/services-web", headers=H).json()["services"][0]
    assert v["payable_avant"] == "2026-11-15" and v["jour_du_mois"] == 15


def test_nom_de_service_250_caracteres(env):
    long = "Hébergement de la plateforme et des bases de données — " * 4
    assert 120 < len(long) <= 250
    r = env.post("/api/admin/services-web", json={"service": long, "montant": 1000, "mode": "unique"}, headers=H)
    assert r.status_code == 200 and r.json()["service"] == long.strip()
    assert env.post("/api/admin/services-web", json={"service": "x" * 251, "montant": 1, "mode": "unique"}, headers=H).status_code == 422
    assert env.put(f"/api/admin/services-web/{r.json()['id']}", json={"service": "y" * 251}, headers=H).status_code == 422


def test_historique_des_impressions_de_recus(env):
    m = env.post("/api/admin/services-web", json={"service": "Hébergement", "montant": 25000, "jour_du_mois": 15}, headers=H).json()
    v = env.post(f"/api/admin/services-web/{m['id']}/paiement", json={"paye_le": "2026-11-20T10:00", "montant": 25000, "reference": "R1"}, headers=H).json()
    pid = v["paiements"][0]["id"]
    # impressions par le super-admin puis par le DG : chacune est enregistrée et le reçu est renvoyé
    r = env.post(f"/api/admin/services-web/{m['id']}/paiements/{pid}/recu/impression", headers=H)
    assert r.status_code == 200 and r.json()["numero"].startswith("RECU-SW-20261120-")
    assert env.post(f"/api/me/services-web/{m['id']}/paiements/{pid}/recu/impression", headers={"X-User": "dg"}).status_code == 200
    assert env.post(f"/api/admin/services-web/{m['id']}/paiements/inconnu/recu/impression", headers=H).status_code == 404
    assert env.post(f"/api/admin/services-web/{m['id']}/paiements/{pid}/recu/impression", headers={"X-User": "dg"}).status_code == 403      # le DG passe par sa route
    # le super-admin consulte l'historique (plus récent d'abord, avec l'auteur) ; le DG n'y a pas accès
    h = env.get("/api/admin/services-web/impressions", headers=H).json()
    assert h["total"] == 2 and h["impressions"][0]["par"] == "DG" and h["impressions"][1]["par"] == "Super" and h["impressions"][0]["service"] == "Hébergement"
    assert h["impressions"][0]["imprime_le"] >= h["impressions"][1]["imprime_le"] and h["impressions"][0]["montant"] == 25000
    assert env.get("/api/admin/services-web/impressions", headers={"X-User": "dg"}).status_code == 403
    # filtres : service et dates
    assert env.get("/api/admin/services-web/impressions", params={"service_id": "autre"}, headers=H).json()["total"] == 0
    assert env.get("/api/admin/services-web/impressions", params={"du": "2999-01-01"}, headers=H).json()["total"] == 0
    assert env.get("/api/admin/services-web/impressions", params={"du": "pas une date"}, headers=H).status_code == 422
    # l'historique n'apparaît pas dans la vue du service (jamais envoyé au DG)
    assert "impressions" not in env.get("/api/me/services-web", headers={"X-User": "dg"}).json()["services"][0]
