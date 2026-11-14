"""Lots 100-101 — fonctions des contacts (profils à cases voir / agir) et accès des contacts au portail (révocation, date de fin)."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException, Request
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_fonctions_contacts as fc  # noqa: E402

PERSONNEL = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Super", "roles": ["superviseur"]},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"]},
    "secr": {"id": "u-secr", "email": "secr@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"]},
}


# ---------- logique pure ----------
def test_code_et_options():
    assert fc.code_de("Directeur financier") == "directeur_financier"
    assert fc.code_de("Chargé d'études été") == "charge_d_etudes_ete"
    assert fc.options_valides(["echeances", "inconnue", "documents", "documents"]) == ["documents", "echeances"]


def test_acces_en_vigueur():
    auj = date(2026, 11, 14)
    assert fc.acces_en_vigueur({}, auj) is None
    assert "révoqué" in fc.acces_en_vigueur({"revoque": True}, auj)
    assert fc.acces_en_vigueur({"acces_jusqua": "2026-11-14"}, auj) is None            # la date de fin est INCLUSE
    assert "pris fin le 13/11/2026" in fc.acces_en_vigueur({"acces_jusqua": "2026-11-13"}, auj)


def test_ecriture_permise():
    assert fc.ecriture_permise("GET", "/api/documents", [])                            # lecture : toujours
    assert not fc.ecriture_permise("POST", "/api/documents", [])                       # écriture sans « agir »
    assert fc.ecriture_permise("POST", "/api/documents/abc", ["documents"])
    assert not fc.ecriture_permise("POST", "/api/documents", ["echeances"])            # « agir » d'une AUTRE option
    assert not fc.ecriture_permise("POST", "/api/route-inconnue", ["documents"])       # refus par défaut
    assert fc.ecriture_permise("POST", "/api/presence/ping", [])                       # route libre


# ---------- routes (vraies connexions : jetons signés, comptes dans une base simulée) ----------
import asyncio  # noqa: E402

import albarka_auth  # noqa: E402


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot100"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(fc.router)

    @api.get("/documents")
    async def lire_documents(u: dict = fc.Depends(fc.get_current_user)):
        return {"id": u["id"], "modules": u.get("portal_modules"), "contact": u.get("contact_nom")}

    @api.post("/documents")
    async def deposer(u: dict = fc.Depends(fc.get_current_user)):
        return {"ok": True}

    @api.post("/autre")
    async def autre(u: dict = fc.Depends(fc.get_current_user)):
        return {"ok": True}
    app.include_router(api)

    boucle = asyncio.new_event_loop()
    run = boucle.run_until_complete
    for k, u in PERSONNEL.items():
        run(mock_db.users.insert_one({**u, "password_hash": "x", "is_active": True}))
    run(mock_db.users.insert_one({"id": "cli1", "email": "client@x.bf", "full_name": "Société X", "roles": ["client"], "is_active": True, "password_hash": "x",
                                  "portal_modules": ["documents", "echeances", "missions"]}))
    run(mock_db.contacts.insert_one({"id": "ct1", "scope": "client", "tenant_id": "cli1", "full_name": "Awa BADINI", "function": "daf",
                                     "email": "awa.badini@gmail.com", "is_active": True}))
    yield TestClient(app), mock_db, run
    boucle.close()


def _h(user_id):
    return {"Authorization": f"Bearer {albarka_auth.create_access_token(user_id)}"}


def test_fonctions_de_depart_et_droits_de_gestion(env):
    c, _, _ = env
    r = c.get("/api/fonctions-contacts", headers=_h("u-secr"))
    assert r.status_code == 200 and {"dg", "daf", "autre"} <= {f["code"] for f in r.json()["fonctions"]} and "documents" in r.json()["options"]
    # Seuls le DG et le super-admin gèrent
    assert c.post("/api/fonctions-contacts", headers=_h("u-secr"), json={"libelle": "Trésorier"}).status_code == 403
    r = c.post("/api/fonctions-contacts", headers=_h("u-dg"), json={"libelle": "Trésorier", "voir": ["documents", "echeances"], "agir": ["documents", "missions"]})
    assert r.status_code == 201 and r.json()["code"] == "tresorier"
    assert r.json()["agir"] == ["documents"]                                           # « agir » suppose « voir »
    assert c.post("/api/fonctions-contacts", headers=_h("u-sup"), json={"libelle": "Trésorier"}).status_code == 409
    assert c.put("/api/fonctions-contacts/tresorier", headers=_h("u-sup"), json={"voir": ["documents"]}).json()["voir"] == ["documents"]


def test_ouverture_acces_regles(env):
    c, _, _ = env
    c.put("/api/fonctions-contacts/daf", headers=_h("u-dg"), json={"voir": ["documents", "echeances"], "agir": ["documents"]})
    assert c.post("/api/contacts/ct1/acces", headers=_h("u-secr"), json={"fonction": "daf"}).status_code == 403
    assert c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "inconnue"}).status_code == 422
    r = c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"})
    assert r.status_code == 201 and r.json()["actif"] and len(r.json()["mot_de_passe_provisoire"]) >= 8
    assert c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"}).status_code == 409      # un seul accès par contact
    assert c.get("/api/contacts/ct1/acces", headers=_h("u-dg")).json()["fonction"] == "daf"


def test_contact_voit_le_client_et_agit_selon_sa_fonction(env):
    c, mock_db, run = env
    c.put("/api/fonctions-contacts/daf", headers=_h("u-dg"), json={"voir": ["documents", "echeances", "paie"], "agir": ["documents"]})
    c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"})
    compte = run(mock_db.users.find_one({"contact_acces.contact_id": "ct1"}))
    h = _h(compte["id"])
    r = c.get("/api/documents", headers=h)
    assert r.status_code == 200 and r.json()["id"] == "cli1" and r.json()["contact"] == "Awa BADINI"
    assert sorted(r.json()["modules"]) == ["documents", "echeances"]                    # « paie » non ouvert pour ce client : absent même si la fonction le permet
    assert c.post("/api/documents", headers=h).status_code == 200                       # « agir » sur documents
    assert c.post("/api/autre", headers=h).status_code == 403                           # route non reconnue : refus par défaut


def test_revocation_date_de_fin_et_retablissement(env):
    c, mock_db, run = env
    c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"})
    h = _h(run(mock_db.users.find_one({"contact_acces.contact_id": "ct1"}))["id"])
    assert c.get("/api/documents", headers=h).status_code == 200
    # Révocation : immédiate
    assert c.delete("/api/contacts/ct1/acces", headers=_h("u-dg")).json()["revoque"] is True
    r = c.get("/api/documents", headers=h)
    assert r.status_code == 403 and "révoqué" in r.json()["detail"]
    # Rétablissement avec une date de fin déjà passée : refusé pour échéance
    hier = (date.today() - timedelta(days=1)).isoformat()
    c.put("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"revoque": False, "acces_jusqua": hier})
    assert "pris fin" in c.get("/api/documents", headers=h).json()["detail"]
    # Date de fin dans le futur : accès rétabli ; effacer la date = sans limite
    demain = (date.today() + timedelta(days=1)).isoformat()
    c.put("/api/contacts/ct1/acces", headers=_h("u-sup"), json={"acces_jusqua": demain})
    assert c.get("/api/documents", headers=h).status_code == 200
    assert c.put("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"efface_date": True}).json()["acces_jusqua"] is None


def test_client_desactive_ou_fiche_desactivee_et_suppression_fonction(env):
    c, mock_db, run = env
    c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"})
    h = _h(run(mock_db.users.find_one({"contact_acces.contact_id": "ct1"}))["id"])
    # Une fonction utilisée ne peut pas être supprimée
    assert c.delete("/api/fonctions-contacts/daf", headers=_h("u-dg")).status_code == 409
    c.post("/api/fonctions-contacts", headers=_h("u-dg"), json={"libelle": "Stagiaire"})
    assert c.delete("/api/fonctions-contacts/stagiaire", headers=_h("u-dg")).status_code == 200
    # Fiche du contact désactivée, puis compte du client désactivé : accès refusé
    run(mock_db.contacts.update_one({"id": "ct1"}, {"$set": {"is_active": False}}))
    assert c.get("/api/documents", headers=h).status_code == 403
    run(mock_db.contacts.update_one({"id": "ct1"}, {"$set": {"is_active": True}}))
    assert c.get("/api/documents", headers=h).status_code == 200
    run(mock_db.users.update_one({"id": "cli1"}, {"$set": {"is_active": False}}))
    assert c.get("/api/documents", headers=h).status_code == 403


def test_journal_des_parcours_du_contact(env):
    """Lot 104 — connexion, pages, actions et refus d'un contact sont tracés ; consultation réservée au DG et au super-admin."""
    c, mock_db, run = env
    c.put("/api/fonctions-contacts/daf", headers=_h("u-dg"), json={"voir": ["documents"], "agir": ["documents"]})
    c.post("/api/contacts/ct1/acces", headers=_h("u-dg"), json={"fonction": "daf"})
    compte = run(mock_db.users.find_one({"contact_acces.contact_id": "ct1"}))
    h = _h(compte["id"])
    c.get("/api/documents", headers=h)
    c.get("/api/documents", headers=h)                                     # relue dans la minute : notée une seule fois
    c.post("/api/documents", headers=h)                                    # action : toujours notée
    c.post("/api/autre", headers=h)                                        # refusée : notée aussi
    run(fc.journaliser_connexion(compte, "empreinte"))
    j = c.get("/api/contacts/ct1/journal", headers=_h("u-dg")).json()["journal"]
    assert [(x["type"], x["chemin"]) for x in reversed(j)] == [("page", "/api/documents"), ("action", "/api/documents"), ("refus", "/api/autre"), ("connexion", "/api/auth")]
    assert j[0]["connexion"] == "empreinte" and j[0]["nom"] == "Awa BADINI" and j[0]["fonction"] == "daf"
    assert j[1]["statut"] == 403 and "lecture seule" in j[1]["motif"]
    assert c.get("/api/contacts/ct1/journal", headers=_h("u-secr")).status_code == 403
    assert len(c.get("/api/journal-contacts?client_id=cli1", headers=_h("u-sup")).json()["journal"]) == 4
    assert c.get("/api/journal-contacts?client_id=autre", headers=_h("u-sup")).json()["journal"] == []
    assert c.get("/api/journal-contacts?du=2999-01-01", headers=_h("u-sup")).json()["journal"] == []


def test_a_journaliser_regles():
    d = {}
    assert not fc.a_journaliser("GET", "/api/presence/ping", 0, d, "x")              # sondage : pas de trace
    assert fc.a_journaliser("GET", "/api/documents", 100.0, d, "x")
    assert not fc.a_journaliser("GET", "/api/documents", 130.0, d, "x")             # même page dans la minute
    assert fc.a_journaliser("GET", "/api/documents", 161.0, d, "x")                 # plus d'une minute après
    assert fc.a_journaliser("POST", "/api/documents", 162.0, d, "x")                # écriture : toujours
