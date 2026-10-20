"""Lot 47 — bibliothèque : chargement d'un document (PDF / Word) et case « partageable ».
Tests unitaires (base simulée, stockage simulé)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot47")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot47")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_phase_c as pc  # noqa: E402


def _client(monkeypatch):
    import albarka_storage as stor
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(pc, "db", db)
    stockes = []

    async def faux_put(chemin, donnees, ct):
        stockes.append((chemin, ct))
        return {}
    monkeypatch.setattr(stor, "put_object", faux_put)
    app = FastAPI()
    app.include_router(pc.archives_router, prefix="/api")
    app.dependency_overrides[pc.require_staff()] = lambda: None
    # require_staff() crée une dépendance neuve à chaque appel : on remplace plutôt l'utilisateur courant
    app.dependency_overrides[pc.get_current_user] = lambda: {"id": "u1", "email": "dg@c.test", "roles": ["superviseur"], "full_name": "DG"}
    return TestClient(app), db, stockes


def test_chargement_partageable_et_liste_filtree(monkeypatch):
    c, db, stockes = _client(monkeypatch)
    r = c.post("/api/archives/fichier", files={"fichier": ("contrat.pdf", b"%PDF-1.4", "application/pdf")},
               data={"title": "Contrat type", "category": "modeles", "partageable": "true", "tags": "contrat, modèle"})
    assert r.status_code == 200 and r.json()["partageable"] is True and stockes[0][1] == "application/pdf"
    r2 = c.post("/api/archives/fichier", files={"fichier": ("note.docx", b"PK", "application/octet-stream")}, data={"title": "Note interne"})
    assert r2.status_code == 200 and r2.json()["partageable"] is False
    # Refus : autre type, fichier vide
    assert c.post("/api/archives/fichier", files={"fichier": ("film.mp4", b"x", "video/mp4")}, data={"title": "x"}).status_code == 415
    # Lot 50 : les images JPEG / PNG sont acceptées (5 Mo au plus)
    assert c.post("/api/archives/fichier", files={"fichier": ("plan.png", b"\x89PNG", "image/png")}, data={"title": "Plan", "partageable": "true"}).status_code == 200
    assert c.post("/api/archives/fichier", files={"fichier": ("grosse.jpg", b"x" * (5 * 1024 * 1024 + 1), "image/jpeg")}, data={"title": "G"}).status_code == 413
    assert c.post("/api/archives/fichier", files={"fichier": ("v.pdf", b"", "application/pdf")}, data={"title": "x"}).status_code == 400
    # Liste « partageables » : seulement le contrat ; le chemin de stockage n'est jamais exposé
    liste = c.get("/api/archives", params={"partageable": "true"}).json()
    assert sorted(a["title"] for a in liste) == ["Contrat type", "Plan"] and liste[0]["a_fichier"] is True and "storage_path" not in liste[0]
    # On marque la note comme partageable, puis on la démarque
    note_id = r2.json()["id"]
    assert c.patch(f"/api/archives/{note_id}/partageable", json={"partageable": True}).json()["partageable"] is True
    assert len(c.get("/api/archives", params={"partageable": "true"}).json()) == 3
    assert c.patch(f"/api/archives/{note_id}/partageable", json={"partageable": False}).status_code == 200
    # Un élément sans fichier (événement archivé automatiquement) ne peut pas être marqué partageable
    sf = c.post("/api/archives", json={"title": "Facture émise", "category": "autre"}).json()["id"]
    assert c.patch(f"/api/archives/{sf}/partageable", json={"partageable": True}).status_code == 400
