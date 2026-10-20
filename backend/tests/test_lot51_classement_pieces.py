"""Lot 51 — classement des pièces : dossier du mois, section (3), urgence."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot51")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot51")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_documents as docs  # noqa: E402

CLIENT = {"id": "c1", "email": "client@test.bf", "roles": ["client"], "tenant_id": "c1"}
AUTRE_CLIENT = {"id": "c2", "email": "autre@test.bf", "roles": ["client"], "tenant_id": "c2"}


def test_validation_du_classement():
    ok = docs._classement("prestataires", "2026-09", True)
    assert ok == {"section": "prestataires", "periode": "2026-09", "urgent": True}
    vide = docs._classement("", "", False)
    assert vide["section"] == "" and len(vide["periode"]) == 7 and vide["urgent"] is False      # non classé, mois courant
    with pytest.raises(HTTPException):
        docs._classement("banque", "2026-09", False)                                            # section inconnue
    with pytest.raises(HTTPException):
        docs._classement("fournisseurs", "09/2026", False)                                      # période mal écrite


def _client(monkeypatch, utilisateur):
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(docs, "db", db)
    monkeypatch.setattr(docs, "tenant_id_of", lambda u: u.get("tenant_id"))
    monkeypatch.setattr(docs, "client_modules", lambda u: ["documents"])
    app = FastAPI()
    app.include_router(docs.router, prefix="/api")
    app.dependency_overrides[docs.get_current_user] = lambda: utilisateur
    c = TestClient(app)
    c.db = db
    return c


def test_liste_et_reclassement_des_pieces(monkeypatch):
    c = _client(monkeypatch, CLIENT)
    c.portal = None
    import asyncio
    asyncio.run(c.db.documents.insert_many([
        {"id": "d1", "tenant_id": "c1", "created_at": "2026-09-14T10:00:00+00:00", "original_filename": "ancienne.pdf"},   # sans classement
        {"id": "d2", "tenant_id": "c1", "created_at": "2026-10-02T10:00:00+00:00", "section": "fournisseurs", "periode": "2026-10",
         "urgent": True, "original_filename": "facture.pdf"},
        {"id": "d3", "tenant_id": "c2", "created_at": "2026-10-02T10:00:00+00:00", "original_filename": "autre-client.pdf"}]))
    liste = {d["id"]: d for d in c.get("/api/documents").json()}
    assert set(liste) == {"d1", "d2"}                                                    # jamais les pièces d'un autre client
    assert liste["d1"]["periode"] == "2026-09" and liste["d1"]["section"] == "" and liste["d1"]["urgent"] is False   # défauts
    assert liste["d2"]["urgent"] is True and liste["d2"]["periode"] == "2026-10"
    # Reclassement de sa propre pièce
    r = c.patch("/api/documents/d1/classement", json={"section": "frais_generaux", "periode": "2026-09", "urgent": True})
    assert r.status_code == 200 and r.json()["section"] == "frais_generaux" and r.json()["urgent"] is True
    # Refus : pièce d'un autre client, section inconnue
    assert c.patch("/api/documents/d3/classement", json={"section": "fournisseurs", "periode": "2026-10"}).status_code == 403
    assert c.patch("/api/documents/d1/classement", json={"section": "banque", "periode": "2026-09"}).status_code == 400
    assert c.patch("/api/documents/inconnu/classement", json={}).status_code == 404
