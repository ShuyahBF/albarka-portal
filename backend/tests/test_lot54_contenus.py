"""Lot 54 — Infos hebdomadaires et Formations (gratuites / payantes)."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot54")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot54")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_contenus as ct  # noqa: E402

CLIENT = {"id": "c1", "email": "c1@test.bf", "roles": ["client"]}
AUTRE = {"id": "c2", "email": "c2@test.bf", "roles": ["client"]}
GESTION = {"id": "g1", "email": "g@test.bf", "roles": ["direction"]}


def _app(monkeypatch, user):
    """Base en mémoire, stockage factice, utilisateur courant réglable."""
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(ct, "db", db)
    magasin = {}

    async def put(db_, **k):
        chemin = f"x/{k['original_filename']}"
        magasin[chemin] = k["data"]
        return {"id": "o", "path": chemin, "size": len(k["data"]), "content_type": k.get("content_type") or "application/octet-stream"}

    async def get(path):
        return magasin[path], "application/pdf"
    monkeypatch.setattr(ct, "save_and_log", put)
    monkeypatch.setattr(ct, "get_object", get)
    app = FastAPI()
    app.include_router(ct.router, prefix="/api")
    etat = {"user": user}
    app.dependency_overrides[ct.get_current_user] = lambda: etat["user"]
    app.dependency_overrides[ct.GESTION_DEP] = lambda: GESTION
    c = TestClient(app)
    c.db, c.etat = db, etat
    return c


def _creer(c, **kw):
    d = {"type": "info", "titre": "TVA : ce qui change", "format": "video", "url": "https://youtu.be/abcDEF12345", "theme": "fiscalite"}
    fichiers = kw.pop("_f", None)
    d.update(kw)
    return c.post("/api/contenus", data=d, files=fichiers)


def test_info_video_youtube_avec_vignette_automatique_et_lien_integre(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    r = _creer(c)
    assert r.status_code == 200, r.text
    liste = c.get("/api/contenus?type=info").json()
    assert liste[0]["embed_url"].endswith("/embed/abcDEF12345") and liste[0]["a_vignette"] and liste[0]["gratuit"]


def test_validations_listes_finies_et_https(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    assert _creer(c, theme="astrologie").status_code == 400
    assert _creer(c, url="http://exemple.bf/v").status_code == 400
    assert _creer(c, format="pdf").status_code == 400                 # PDF sans fichier


def test_formation_payante_masquee_puis_accordee(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    r = _creer(c, type="formation", prix="15000", titre="Maîtriser la paie")
    assert r.status_code == 200
    cid = r.json()["id"]
    f = c.get("/api/contenus?type=formation").json()[0]
    assert f["acces"] is False and "embed_url" not in f and "url" not in f         # lien non révélé
    assert c.get(f"/api/contenus/{cid}/fichier").status_code == 402
    asyncio.run(c.db.users.insert_one({"id": "c1", "roles": ["client"], "full_name": "Un"}))
    assert c.post(f"/api/contenus/{cid}/acces", json={"tenant_id": "c1"}).status_code == 200
    f = c.get("/api/contenus?type=formation").json()[0]
    assert f["acces"] is True and "embed_url" in f
    c.etat["user"] = AUTRE                                                          # un autre client n'a pas l'accès
    assert c.get("/api/contenus?type=formation").json()[0]["acces"] is False


def test_pdf_telechargeable_et_brouillon_cache_au_client(monkeypatch):
    c = _app(monkeypatch, CLIENT)
    r = _creer(c, format="pdf", publie="false", _f=[("fichier", ("guide.pdf", b"%PDF-1", "application/pdf"))])
    assert r.status_code == 200, r.text
    assert c.get("/api/contenus?type=info").json() == []                           # brouillon : invisible du client
    cid = r.json()["id"]
    assert c.patch(f"/api/contenus/{cid}", json={"publie": True}).status_code == 200
    assert c.get(f"/api/contenus/{cid}/fichier").content == b"%PDF-1"
    assert c.delete(f"/api/contenus/{cid}").json() == {"ok": True}
