"""Lot 53 — demandes de services : client connecté, visiteur public, traitement par le cabinet."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot53")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot53")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_demandes as dm  # noqa: E402

CLIENT = {"id": "c1", "email": "c1@test.bf", "full_name": "Client Un", "roles": ["client"]}
AUTRE = {"id": "c2", "email": "c2@test.bf", "full_name": "Client Deux", "roles": ["client"]}
STAFF = {"id": "s1", "email": "s@test.bf", "roles": ["comptable"]}


def _app(monkeypatch, user):
    """Application de test : base en mémoire, aucun envoi réel (alerte/accusé neutralisés)."""
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(dm, "db", db)
    envois = []

    async def faux(doc):
        envois.append(doc["id"])
    monkeypatch.setattr(dm, "_alerter_cabinet", faux)
    monkeypatch.setattr(dm, "_accuse", faux)

    async def faux_put(db_, **k):
        return {"id": "f" + str(len(envois)) + k["ext"], "path": f"x/{k['original_filename']}", "size": len(k["data"]),
                "content_type": k.get("content_type") or "application/octet-stream"}
    monkeypatch.setattr(dm, "save_and_log", faux_put)

    async def ok_captcha(t):
        return {"success": True, "enabled": False, "reason": ""}
    import albarka_recaptcha
    monkeypatch.setattr(albarka_recaptcha, "verify_recaptcha", ok_captcha)
    app = FastAPI()
    app.include_router(dm.router, prefix="/api")
    app.include_router(dm.public_router, prefix="/api")
    app.dependency_overrides[dm.get_current_user] = lambda: user
    app.dependency_overrides[dm.STAFF_DEP] = lambda: STAFF
    c = TestClient(app)
    c.db = db
    c.envois = envois
    return c


def test_client_depose_demande_texte_vocal_et_piece(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    r = c.post("/api/demandes", data={"service": "fiscalite", "message": "Déclaration TVA", "urgent": "true"},
               files=[("vocal", ("note.webm", b"voix", "audio/webm")), ("fichiers", ("facture.pdf", b"%PDF", "application/pdf"))])
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["service"] == "fiscalite" and d["urgent"] is True and d["status"] == "nouvelle"
    assert d["vocal"]["nom"] == "note.webm" and d["fichiers"][0]["nom"] == "facture.pdf"
    assert "path" not in str(d)                                    # aucun chemin de stockage exposé
    assert len(c.get("/api/demandes/mes").json()) == 1


def test_validations(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    assert c.post("/api/demandes", data={"service": "magie", "message": "x"}).status_code == 400   # service hors liste
    assert c.post("/api/demandes", data={"service": "rh"}).status_code == 400                       # rien de décrit
    r = c.post("/api/demandes", data={"service": "rh", "message": "x"}, files=[("fichiers", ("virus.exe", b"x", "application/octet-stream"))])
    assert r.status_code == 400


def test_public_robot_captcha_et_limite(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    base = {"nom": "Visiteur", "telephone": "70123456", "service": "comptable", "message": "Besoin d'un devis"}
    assert c.post("/api/public/demande-service", data={**base, "site_web": "http://spam"}).json() == {"ok": True}
    assert c.db.missions.count_documents  # robot : rien d'enregistré
    import asyncio
    assert asyncio.run(c.db.missions.count_documents({})) == 0
    for _ in range(dm.PUBLIC_MAX_PAR_HEURE):
        assert c.post("/api/public/demande-service", data=base).status_code == 200
    assert c.post("/api/public/demande-service", data=base).status_code == 429                    # au-delà : refusé


def test_isolation_client_et_traitement_cabinet(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    did = c.post("/api/demandes", data={"service": "autres", "message": "Question"}).json()["id"]
    c.app.dependency_overrides[dm.get_current_user] = lambda: AUTRE
    assert c.get("/api/demandes/mes").json() == []                                                  # l'autre client ne voit rien
    assert c.get(f"/api/demandes/{did}/fichier/vocal").status_code in (403, 404)
    assert c.get("/api/demandes/services").json()["services"][0]["code"] == "fiscalite"


def test_cabinet_liste_et_change_le_statut(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    did = c.post("/api/demandes", data={"service": "rh", "message": "Contrat"}).json()["id"]
    assert c.get("/api/demandes/admin?statut=nouvelle").json()[0]["id"] == did
    assert c.patch(f"/api/demandes/admin/{did}", json={"status": "traitee"}).json()["status"] == "traitee"
    assert c.patch(f"/api/demandes/admin/{did}", json={"status": "bizarre"}).status_code == 400
    assert c.get("/api/demandes/admin?statut=nouvelle").json() == []
