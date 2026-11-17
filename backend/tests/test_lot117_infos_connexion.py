"""Lot 117 — Informations du DG à sa connexion : nouveaux paiements reçus (SAWALI) et réponses de SAWALI à ses demandes, sans bloquer le portail."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
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
import albarka_infos_connexion as ic  # noqa: E402

USERS = {
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg", "direction"]},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"]},
}
MAINTENANT = datetime.now(timezone.utc)


def _il_y_a(heures: float) -> str:
    return (MAINTENANT - timedelta(hours=heures)).isoformat()


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot117"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setitem(ic._cache, "transactions", [])
    monkeypatch.setitem(ic._cache, "etat", "jamais")
    monkeypatch.setitem(ic._cache, "le", 0.0)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(ic.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[ic.get_current_user] = fake_user
    client = TestClient(app)
    client.db = mock_db
    return client


def _inserer(env, collection: str, doc: dict) -> None:
    """Les collections de test (mongomock_motor) sont asynchrones : l'insertion doit être attendue, sinon rien n'est écrit."""
    asyncio.run(getattr(env.db, collection).insert_one(doc))


# ---------------------------------------------------------------- logique pure
def test_lire_date_accepte_jour_seul_fuseau_et_refuse_le_reste():
    assert ic.lire_date("2026-11-17").isoformat().startswith("2026-11-17T00:00:00")
    assert ic.lire_date("2026-11-17T10:00:00+02:00").hour == 8          # converti en UTC
    assert ic.lire_date("n'importe quoi") is None and ic.lire_date(None) is None


def test_paiements_nouveaux_apres_la_derniere_lecture_seulement():
    depuis = MAINTENANT - timedelta(hours=5)
    t = [{"id": "a", "recu_le": _il_y_a(2), "montant": 50000, "tiers": "Awa", "operateur": "Orange", "texte": "SMS brut secret"},
         {"id": "b", "recu_le": _il_y_a(10), "montant": 20000},                  # avant la dernière lecture
         {"id": "c", "recu_le": _il_y_a(1), "montant": 0},                        # sans montant : ignoré
         {"id": "d", "recu_le": "pas une date", "montant": 100}]
    sortie = ic.paiements_nouveaux(t, depuis)
    assert [p["id"] for p in sortie] == ["a"] and "texte" not in sortie[0]       # jamais le texte du SMS


def test_demandes_repondues_apres_la_derniere_lecture_seulement():
    depuis = MAINTENANT - timedelta(hours=5)
    docs = [{"id": "1", "numero_sawali": "DEM-1", "statut": "realisee", "modifiee_sawali_le": _il_y_a(1), "texte": "x"},
            {"id": "2", "numero_sawali": "DEM-2", "statut": "remontee", "modifiee_sawali_le": _il_y_a(9)},
            {"id": "3", "statut": "a_remonter"}]
    assert [d["id"] for d in ic.demandes_repondues(docs, depuis)] == ["1"]


# ---------------------------------------------------------------- routes
def test_reserve_au_dg(env):
    assert env.get("/api/me/infos-connexion", headers={"X-User": "dir"}).status_code == 403
    assert env.get("/api/me/infos-connexion").status_code == 401
    assert env.post("/api/me/infos-connexion/ack", json={"jusqu_a": MAINTENANT.isoformat()}, headers={"X-User": "dir"}).status_code == 403


def test_demandes_repondues_puis_acquittees(env):
    _inserer(env, "demandes_sawali", {"id": "d1", "texte": "Corriger la facture", "statut": "realisee", "numero_sawali": "DEM-9",
                                      "modifiee_sawali_le": _il_y_a(1), "realisee_le": "2026-11-16"})
    r = env.get("/api/me/infos-connexion", headers={"X-User": "dg"}).json()
    assert [d["numero_sawali"] for d in r["demandes"]] == ["DEM-9"]
    assert env.post("/api/me/infos-connexion/ack", json={"jusqu_a": r["jusqu_a"]}, headers={"X-User": "dg"}).status_code == 200
    assert env.get("/api/me/infos-connexion", headers={"X-User": "dg"}).json()["demandes"] == []      # acquittée : plus répétée


def test_ouvrir_la_page_des_demandes_vaut_lecture(env):
    """Une réponse déjà vue en ouvrant « Demandes à SAWALI » n'est pas répétée à la connexion."""
    _inserer(env, "demandes_sawali", {"id": "d1", "statut": "realisee", "numero_sawali": "DEM-9", "modifiee_sawali_le": _il_y_a(3)})
    _inserer(env, "user_view_marks", {"user_id": "u-dg", "page": "demandes_sawali", "seen_at": _il_y_a(1)})
    assert env.get("/api/me/infos-connexion", headers={"X-User": "dg"}).json()["demandes"] == []


def test_acquittement_ne_marque_pas_ce_qui_est_arrive_apres_l_affichage(env):
    affiche = _il_y_a(2)                                           # le DG a vu l'écran il y a 2 h
    _inserer(env, "demandes_sawali", {"id": "d1", "statut": "realisee", "numero_sawali": "DEM-9", "modifiee_sawali_le": _il_y_a(1)})   # arrivée depuis
    assert env.post("/api/me/infos-connexion/ack", json={"jusqu_a": affiche}, headers={"X-User": "dg"}).status_code == 200
    assert [d["numero_sawali"] for d in env.get("/api/me/infos-connexion", headers={"X-User": "dg"}).json()["demandes"]] == ["DEM-9"]
    assert env.post("/api/me/infos-connexion/ack", json={"jusqu_a": "n'importe quoi"}, headers={"X-User": "dg"}).status_code == 422


def test_paiements_lus_en_arriere_plan_sans_bloquer_la_page(env, monkeypatch):
    """La page répond tout de suite (« jamais » lu) ; le relevé SAWALI est lu en tâche de fond, puis les paiements apparaissent."""
    import albarka_support_sawali
    appels = []

    async def fausse_lecture(chemin, corps, delai=0):
        appels.append(chemin)
        await asyncio.sleep(0.05)
        return {"transactions": [{"id": "t1", "recu_le": _il_y_a(1), "montant": 75000, "tiers": "Awa", "operateur": "Orange"}]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", fausse_lecture)

    async def parcours():
        app = env.app
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            premiere = (await c.get("/api/me/infos-connexion", headers={"X-User": "dg"})).json()
            assert premiere["paiements"] == [] and premiere["paiements_etat"] == "jamais"       # la page n'a PAS attendu SAWALI
            await asyncio.sleep(0.3)
            seconde = (await c.get("/api/me/infos-connexion", headers={"X-User": "dg"})).json()
            assert [p["montant"] for p in seconde["paiements"]] == [75000] and seconde["paiements_etat"] == "ok"
            assert len(appels) == 1                                                              # relevé gardé en mémoire : un seul appel
    asyncio.run(parcours())


def test_sawali_injoignable_ne_bloque_jamais(env, monkeypatch):
    import albarka_support_sawali

    async def en_panne(chemin, corps, delai=0):
        raise HTTPException(status_code=503, detail="Support SAWALI non configuré")
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", en_panne)

    async def parcours():
        from httpx import ASGITransport, AsyncClient
        async with AsyncClient(transport=ASGITransport(app=env.app), base_url="http://t") as c:
            assert (await c.get("/api/me/infos-connexion", headers={"X-User": "dg"})).status_code == 200
            await asyncio.sleep(0.2)
            r = (await c.get("/api/me/infos-connexion", headers={"X-User": "dg"})).json()
            assert r["paiements"] == [] and r["paiements_etat"] == "indisponible"
    asyncio.run(parcours())
