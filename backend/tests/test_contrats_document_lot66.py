"""Lot 66 — document (Word, PDF, image) attaché à un contrat client par téléversement.

Tests autonomes : MongoDB simulé (mongomock-motor), stockage remplacé par une doublure en mémoire, connexion simulée
par l'en-tête X-User (aucun serveur, aucune clé, aucun réseau).
Lancer : cd backend && REACT_APP_BACKEND_URL=http://localhost:1 python -m pytest tests/test_contrats_document_lot66.py -q
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import FastAPI, Header
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import albarka_contracts as ac  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "direction": {"id": "u-dir", "full_name": "Direction", "roles": ["direction"]},
    "compta": {"id": "u-cpt", "full_name": "Comptable", "roles": ["comptable"]},
    "client": {"id": "c1", "full_name": "Client", "roles": ["client"]},
    "autre": {"id": "c2", "full_name": "Autre client", "roles": ["client"]},
}
PDF = b"%PDF-1.4\n%contrat\n"
DOCX = b"PK\x03\x04docx"


@pytest.fixture()
def env(monkeypatch):
    import asyncio
    db = mongomock_motor.AsyncMongoMockClient()["albarka_contrats_test"]
    asyncio.run(db.users.insert_many([{"id": "c1", "roles": ["client"], "full_name": "Kaboré"},
                                      {"id": "c2", "roles": ["client"], "full_name": "Autre"}]))
    fichiers, supprimes = {}, []

    async def fake_save(db_, *, data, kind, tenant_id, ext, content_type=None, original_filename=None, user_id=None):
        rid = f"obj{len(fichiers) + 1}"
        chemin = f"{kind}/{tenant_id}/{rid}.{ext}"
        fichiers[chemin] = data
        await db_.stored_objects.insert_one({"id": rid, "storage_path": chemin, "is_deleted": False})
        return {"id": rid, "path": chemin, "size": len(data), "content_type": content_type or "application/octet-stream"}

    async def fake_get(path):
        return fichiers[path], "application/octet-stream"

    async def fake_delete(path):
        supprimes.append(path)
        fichiers.pop(path, None)

    monkeypatch.setattr(ac, "db", db)
    monkeypatch.setattr(ac.albarka_storage, "save_and_log", fake_save)
    monkeypatch.setattr(ac.albarka_storage, "get_object", fake_get)
    monkeypatch.setattr(ac.albarka_storage, "delete_object", fake_delete)
    app = FastAPI()
    app.include_router(ac.router, prefix="/api")
    app.include_router(ac.me_router, prefix="/api")

    async def fake_user(x_user: str = Header("direction")):
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    c = TestClient(app)
    r = c.post("/api/client-contracts", json={"tenant_id": "c1", "title": "Tenue comptable", "start_date": "2026-01-01"})
    assert r.status_code == 200, r.text

    class E:  # noqa: D106
        pass
    e = E()
    e.c, e.db, e.fichiers, e.supprimes, e.contrat = c, db, fichiers, supprimes, r.json()
    return e


def _h(u="direction"):
    return {"X-User": u}


def test_attacher_lister_telecharger(env):
    cid = env.contrat["id"]
    r = env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("Contrat signé.pdf", PDF, "application/pdf")})
    assert r.status_code == 200 and r.json()["document"]["filename"] == "Contrat signé.pdf"
    # La liste et la fiche montrent le document SANS exposer le chemin interne de stockage
    liste = env.c.get("/api/client-contracts", headers=_h()).json()
    assert liste[0]["document"]["size"] == len(PDF) and "storage_path" not in liste[0]["document"]
    assert "storage_path" not in env.c.get(f"/api/client-contracts/{cid}", headers=_h()).json()["document"]
    # Affichage et téléchargement
    vue = env.c.get(f"/api/client-contracts/{cid}/document", headers=_h())
    assert vue.content == PDF and vue.headers["content-disposition"].startswith("inline")
    tel = env.c.get(f"/api/client-contracts/{cid}/document", params={"download": True}, headers=_h())
    assert tel.headers["content-disposition"].startswith("attachment")


def test_formats_et_contenu_controles(env):
    cid = env.contrat["id"]
    ko = lambda nom, data: env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": (nom, data, "application/octet-stream")})  # noqa: E731
    assert ko("virus.exe", b"MZ....").status_code == 400                    # format refusé
    assert ko("faux.pdf", b"MZ.... pas un pdf").status_code == 400            # contenu qui ne correspond pas au format
    assert ko("vide.pdf", b"").status_code == 400
    assert ko("contrat.docx", DOCX).status_code == 200                       # Word accepté
    assert ko("scan.png", b"\x89PNG\r\n").status_code == 200                 # image acceptée
    ac.DOC_MAX_BYTES, ancien = 10, ac.DOC_MAX_BYTES
    try:
        assert ko("gros.pdf", PDF).status_code == 413                        # trop volumineux
    finally:
        ac.DOC_MAX_BYTES = ancien


def test_remplacer_retirer_et_suppression_du_contrat(env):
    cid = env.contrat["id"]
    env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("a.pdf", PDF, "application/pdf")})
    premier = next(iter(env.fichiers))
    env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("b.docx", DOCX, "application/octet-stream")})
    assert premier in env.supprimes and len(env.fichiers) == 1               # l'ancien fichier est retiré du stockage
    assert env.c.get(f"/api/client-contracts/{cid}", headers=_h()).json()["document"]["filename"] == "b.docx"
    assert env.c.delete(f"/api/client-contracts/{cid}/document", headers=_h()).status_code == 200
    assert "document" not in env.c.get(f"/api/client-contracts/{cid}", headers=_h()).json() and not env.fichiers
    assert env.c.get(f"/api/client-contracts/{cid}/document", headers=_h()).status_code == 404
    # Contrat supprimé : son document disparaît aussi
    env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("c.pdf", PDF, "application/pdf")})
    assert env.c.delete(f"/api/client-contracts/{cid}", headers=_h()).status_code == 200 and not env.fichiers


def test_droits(env):
    cid = env.contrat["id"]
    env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("a.pdf", PDF, "application/pdf")})
    for u in ("compta", "client"):            # ni le comptable seul ni le client ne touchent au document
        assert env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(u), files={"file": ("x.pdf", PDF, "application/pdf")}).status_code == 403
        assert env.c.get(f"/api/client-contracts/{cid}/document", headers=_h(u)).status_code == 403
        assert env.c.delete(f"/api/client-contracts/{cid}/document", headers=_h(u)).status_code == 403
    assert env.c.post("/api/client-contracts/inconnu/document", headers=_h(), files={"file": ("a.pdf", PDF, "application/pdf")}).status_code == 404


def test_lot67_le_client_voit_et_telecharge_son_contrat(env):
    """Lot 67 — le client connecté voit SES contrats (sans notes internes) et ouvre / télécharge leur document ; jamais ceux d'un autre."""
    cid = env.contrat["id"]
    env.c.patch(f"/api/client-contracts/{cid}", headers=_h(), json={"notes": "note interne confidentielle"})
    env.c.post(f"/api/client-contracts/{cid}/document", headers=_h(), files={"file": ("Contrat signé.pdf", PDF, "application/pdf")})
    autre = env.c.post("/api/client-contracts", headers=_h(), json={"tenant_id": "c2", "title": "Contrat de l'autre", "start_date": "2026-02-01"}).json()
    env.c.post(f"/api/client-contracts/{autre['id']}/document", headers=_h(), files={"file": ("autre.pdf", PDF, "application/pdf")})
    # Liste : uniquement le contrat de c1, sans notes ni chemin de stockage
    liste = env.c.get("/api/me/contracts", headers=_h("client")).json()["items"]
    assert [c["id"] for c in liste] == [cid]
    assert "notes" not in liste[0] and "created_by" not in liste[0] and "storage_path" not in liste[0]["document"]
    assert liste[0]["document"]["filename"] == "Contrat signé.pdf"
    # Ouverture et téléchargement de son document
    vue = env.c.get(f"/api/me/contracts/{cid}/document", headers=_h("client"))
    assert vue.status_code == 200 and vue.content == PDF and vue.headers["content-disposition"].startswith("inline")
    tel = env.c.get(f"/api/me/contracts/{cid}/document", params={"download": True}, headers=_h("client"))
    assert tel.headers["content-disposition"].startswith("attachment")
    # Le contrat (et le document) d'un autre client est introuvable
    assert env.c.get(f"/api/me/contracts/{autre['id']}/document", headers=_h("client")).status_code == 404
    # Réservé aux clients : le personnel passe par l'écran du cabinet
    assert env.c.get("/api/me/contracts", headers=_h("direction")).status_code == 403
    # Contrat sans document : message clair
    sans = env.c.post("/api/client-contracts", headers=_h(), json={"tenant_id": "c1", "title": "Sans document", "start_date": "2026-03-01"}).json()
    assert env.c.get(f"/api/me/contracts/{sans['id']}/document", headers=_h("client")).status_code == 404
