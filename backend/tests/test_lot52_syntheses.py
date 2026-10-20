"""Lot 52 — cartes de synthèse mensuelles du tableau de bord client (RH, CNSS, Fiscal, Comptable)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot52")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot52")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_client_space as cs  # noqa: E402

CLIENT = {"id": "c1", "email": "c1@test.bf", "roles": ["client"]}


def test_validation_theme_et_periode():
    assert cs._theme_ok("fiscal") == "fiscal" and cs._theme_ok("") == ""
    with pytest.raises(HTTPException):
        cs._theme_ok("marketing")
    assert cs._periode_ok("2026-09") == "2026-09"
    assert cs._periode_ok("", "2026-08-14") == "2026-08"                # à défaut : mois de la date du document
    assert len(cs._periode_ok("", "")) == 7                              # sinon mois courant
    with pytest.raises(HTTPException):
        cs._periode_ok("09/2026")


def _client(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(cs, "db", db)
    monkeypatch.setattr(cs, "client_modules", lambda u: ["cabinet_documents"])
    app = FastAPI()
    app.include_router(cs.me_router, prefix="/api")
    app.dependency_overrides[cs.get_current_user] = lambda: CLIENT
    c = TestClient(app)
    c.db = db
    return c


def test_syntheses_par_mois_et_par_theme_sans_jamais_melanger_les_clients(monkeypatch):
    import asyncio
    c = _client(monkeypatch)
    base = {"visible": True, "is_deleted": False, "category": "rapport", "content_type": "application/pdf", "size": 10}
    asyncio.run(c.db.client_documents.insert_many([
        {**base, "id": "r1", "tenant_id": "c1", "title": "Rapport RH septembre", "theme": "rh", "periode": "2026-09", "created_at": "2026-10-02T08:00:00+00:00"},
        {**base, "id": "r2", "tenant_id": "c1", "title": "Déclaration CNSS septembre", "theme": "cnss", "periode": "2026-09", "created_at": "2026-10-03T08:00:00+00:00"},
        {**base, "id": "r3", "tenant_id": "c1", "title": "Bilan août", "theme": "comptable", "periode": "2026-08", "created_at": "2026-09-05T08:00:00+00:00"},
        {**base, "id": "x1", "tenant_id": "c1", "title": "Sans thème", "created_at": "2026-10-01T08:00:00+00:00"},            # pas une synthèse
        {**base, "id": "x2", "tenant_id": "c1", "title": "Masqué", "theme": "fiscal", "periode": "2026-09", "visible": False, "created_at": "2026-10-01T08:00:00+00:00"},
        {**base, "id": "x3", "tenant_id": "c2", "title": "Autre client", "theme": "rh", "periode": "2026-09", "created_at": "2026-10-01T08:00:00+00:00"}]))
    r = c.get("/api/me/space/syntheses").json()
    assert [t["key"] for t in r["themes"]] == ["rh", "cnss", "fiscal", "comptable"]
    assert [m["periode"] for m in r["mois"]] == ["2026-09", "2026-08"]                 # du plus récent au plus ancien
    sept = r["mois"][0]
    assert sept["total"] == 2 and [d["id"] for d in sept["themes"]["rh"]] == ["r1"] and [d["id"] for d in sept["themes"]["cnss"]] == ["r2"]
    assert sept["themes"]["fiscal"] == [] and sept["themes"]["comptable"] == []        # le masqué et celui d'un autre client n'y sont pas
    assert r["mois"][1]["themes"]["comptable"][0]["title"] == "Bilan août"
    assert r["mois"][0]["themes"]["rh"][0]["is_new"] is True and r["mois"][0]["themes"]["rh"][0]["source"] == "upload"
