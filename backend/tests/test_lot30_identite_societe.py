"""Lot 30 — fiche client : IFU, RCCM et N° CNSS modifiables par le cabinet, reportés sur les bulletins de paie.
Tests autonomes : MongoDB simulé (mongomock-motor)."""
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
fitz = pytest.importorskip("fitz")
pytest.importorskip("reportlab")

import db as db_module  # noqa: E402
import albarka_clients  # noqa: E402
import albarka_paie  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "dir": {"id": "u-dir", "email": "direction@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "pharmacie@exemple.bf", "full_name": "Dr Pharma", "company": "PHARMACIE SOLEIL", "phone": "+22670112233",
           "roles": ["client"], "is_active": True},
    "c2": {"id": "c2", "email": "autre@exemple.bf", "full_name": "Autre Société", "company": "AUTRE SARL", "phone": "+22670445566",
           "roles": ["client"], "is_active": True},
}
DIR, RH = {"X-User": "dir"}, {"X-User": "rh"}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot30_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_paie, "_SETUP_DONE_FOR", None)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_clients.router, albarka_paie.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def test_modifier_ifu_rccm_cnss_dans_la_fiche_client(env):
    c = env.c
    r = c.patch("/api/clients/c1", headers=DIR, json={"ifu": " 00012345A ", "rccm": "BF-OUA-2020-B-1234", "cnss_number": "E-778899"})
    assert r.status_code == 200, r.text
    assert (r.json()["ifu"], r.json()["rccm"], r.json()["cnss_number"]) == ("00012345A", "BF-OUA-2020-B-1234", "E-778899")
    # Même fiche que « Mon compte » du client (collection client_kyc, N° CNSS = employer_number)
    kyc = asyncio.run(env.db.client_kyc.find_one({"tenant_id": "c1"}))
    assert (kyc["ifu"], kyc["rccm"], kyc["employer_number"]) == ("00012345A", "BF-OUA-2020-B-1234", "E-778899")
    # La fiche et la liste les renvoient ; une autre société reste vide
    assert c.get("/api/clients/c1", headers=DIR).json()["rccm"] == "BF-OUA-2020-B-1234"
    liste = {x["id"]: x for x in c.get("/api/clients", headers=DIR).json()}
    assert liste["c1"]["ifu"] == "00012345A" and liste["c2"]["ifu"] == "" and liste["c2"]["rccm"] == ""
    # Effacer une valeur : chaîne vide
    assert c.patch("/api/clients/c1", headers=DIR, json={"rccm": ""}).json()["rccm"] == ""
    # Autres champs inchangés quand on ne touche qu'à l'identité
    assert c.get("/api/clients/c1", headers=DIR).json()["company"] == "PHARMACIE SOLEIL"


def test_droits_et_cibles(env):
    c = env.c
    assert c.patch("/api/clients/c1", headers=RH, json={"ifu": "1"}).status_code == 403            # rôle sans droit sur les clients
    assert c.patch("/api/clients/c1", headers=DIR, json={}).status_code == 400
    assert c.patch("/api/clients/u-rh", headers=DIR, json={"ifu": "1"}).status_code == 400          # compte du personnel : pas de IFU


def test_reporte_sur_les_bulletins_brouillons_pas_sur_les_valides(env):
    c = env.c
    c.patch("/api/clients/c1", headers=DIR, json={"ifu": "00012345A", "rccm": "BF-OUA-2020-B-1234", "cnss_number": "E-778899"})
    c.post("/api/hr/paie/employees", headers=DIR, json={"base_salary": 300000, "dependents": 0, "category": "non_cadre",
                                                        "full_name": "KABORE Awa", "tenant_id": "c1", "role": "Préparatrice"})
    c.post("/api/hr/paie/bulletins/prepare", headers=DIR, json={"employer_id": "c1", "period_month": "2026-10"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-10", headers=DIR).json()["items"][0]
    assert b["employer"]["rccm"] == "BF-OUA-2020-B-1234" and b["employer"]["cnss_number"] == "E-778899"
    pdf = c.get(f"/api/hr/paie/bulletins/{b['id']}/pdf", headers=DIR)
    with fitz.open("pdf", pdf.content) as d:
        text = " ".join(" ".join(pg.get_text() for pg in d).split())
    for needle in ("N° IFU : 00012345A", "N° RCCM : BF-OUA-2020-B-1234", "N° employeur (CNSS) : E-778899"):
        assert needle in text, needle
    # Un bulletin VALIDÉ garde l'identité qu'il portait ; un brouillon suit la fiche
    asyncio.run(env.db.paie_bulletins.update_one({"id": b["id"]}, {"$set": {"status": "validated"}}))
    asyncio.run(env.db.paie_bulletins.insert_one({**{k: v for k, v in b.items() if k != "_id"}, "id": "brouillon-2", "status": "draft",
                                                  "period_month": "2026-09", "employee_id": b["employee_id"]}))
    c.patch("/api/clients/c1", headers=DIR, json={"rccm": "BF-OUA-2021-B-9999"})
    valide = asyncio.run(env.db.paie_bulletins.find_one({"id": b["id"]}))
    brouillon = asyncio.run(env.db.paie_bulletins.find_one({"id": "brouillon-2"}))
    assert valide["employer"]["rccm"] == "BF-OUA-2020-B-1234"
    assert brouillon["employer"]["rccm"] == "BF-OUA-2021-B-9999"


def test_bulletin_d_un_client_ne_porte_jamais_les_numeros_du_cabinet(env):
    """Les numéros du bulletin sont CEUX DE LA SOCIÉTÉ CLIENTE : sans numéro propre, rien n'est affiché (jamais l'IFU / le RCCM d'ALBARKA)."""
    c = env.c
    asyncio.run(env.db.settings.insert_one({"_id": "global", "cabinet_name": "Cabinet ALBARKA",
                                            "doc_settings": {"cabinet_ifu": "IFU-CABINET-111", "cabinet_rccm": "RCCM-CABINET-222"}}))
    c.patch("/api/clients/c1", headers=DIR, json={"ifu": "IFU-CLIENT-1", "rccm": "RCCM-CLIENT-1", "cnss_number": "CNSS-CLIENT-1"})
    for cid, nom in (("c1", "KABORE Awa"), ("c2", "OUEDRAOGO Paul")):          # c2 : aucun numéro saisi
        c.post("/api/hr/paie/employees", headers=DIR, json={"base_salary": 300000, "dependents": 0, "category": "non_cadre",
                                                            "full_name": nom, "tenant_id": cid, "role": "Employé"})
        c.post("/api/hr/paie/bulletins/prepare", headers=DIR, json={"employer_id": cid, "period_month": "2026-10"})
    textes = {}
    for cid in ("c1", "c2"):
        b = c.get(f"/api/hr/paie/bulletins?employer_id={cid}&period_month=2026-10", headers=DIR).json()["items"][0]
        pdf = c.get(f"/api/hr/paie/bulletins/{b['id']}/pdf", headers=DIR)
        with fitz.open("pdf", pdf.content) as d:
            textes[cid] = " ".join(" ".join(pg.get_text() for pg in d).split())
    assert "IFU-CLIENT-1" in textes["c1"] and "RCCM-CLIENT-1" in textes["c1"] and "CNSS-CLIENT-1" in textes["c1"]
    for cid in ("c1", "c2"):
        assert "IFU-CABINET-111" not in textes[cid] and "RCCM-CABINET-222" not in textes[cid]
    assert "N° IFU" not in textes["c2"] and "N° RCCM" not in textes["c2"] and "N° employeur (CNSS)" not in textes["c2"]
