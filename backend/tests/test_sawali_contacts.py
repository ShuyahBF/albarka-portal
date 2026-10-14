"""Contacts d'ALBARKA lus (signés) par SAWALI : signature, comptes clients actifs seulement. MongoDB simulé, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_sawali_contacts.py -q"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from routes import sawali_contacts as C  # noqa: E402

CLE = "cle-contacts-test"


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _entetes(requete, cle=CLE):
    ts = str(int(time.time()))
    return {"X-Timestamp": ts, "X-Signature": C.signer(cle, ts, C.CHEMIN, requete)}


def test_signature_et_peremption():
    s = C.signer("k", "1700000000", C.CHEMIN, "limite=5&page=1")
    assert C.signature_valide("k", "1700000000", s, C.CHEMIN, "limite=5&page=1", maintenant=1700000100)
    assert not C.signature_valide("k", "1700000000", s, C.CHEMIN, "limite=5&page=2", maintenant=1700000100)
    assert not C.signature_valide("k", "1700000000", s, C.CHEMIN, "limite=5&page=1", maintenant=1700000500)
    assert not C.signature_valide("k", "abc", s, C.CHEMIN, "", maintenant=1700000100)


@pytest.fixture()
def appli():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = mongomock_motor.AsyncMongoMockClient()["albarka_test"]
    lancer(db.users.insert_many([
        {"id": "c1", "role": "client", "full_name": "Pharmacie du Centre", "company": "Pharmacie du Centre", "whatsapp_number": "+228 90 11 22 33",
         "account_status": "active", "email": "p@x.tg", "password_hash": "secret"},
        {"id": "c2", "role": "client", "full_name": "Suspendu", "phone": "+22891000001", "account_status": "suspended"},
        {"id": "c3", "role": "client", "full_name": "Collègue", "phone": "+22891000002", "account_status": "active", "parent_client_id": "c1"},
        {"id": "a1", "role": "admin", "full_name": "Admin", "phone": "+22891000003", "account_status": "active"},
        {"id": "c4", "role": "client", "full_name": "Sans numéro", "account_status": "active"}]))
    lancer(db.directory_contacts.insert_one({"id": "d1", "client_id": "c1", "name": "Client de la pharmacie", "whatsapp": "+22891000009"}))
    app, api = FastAPI(), APIRouter(prefix="/api")
    C.setup_sawali_contacts_routes(db=db, api=api)
    app.include_router(api)
    return TestClient(app)


def test_refus_sans_cle_ou_signature(appli, monkeypatch):
    monkeypatch.delenv("SAWALI_CONTACTS_HMAC", raising=False)
    assert appli.get(C.CHEMIN).status_code == 503
    monkeypatch.setenv("SAWALI_CONTACTS_HMAC", CLE)
    assert appli.get(C.CHEMIN).status_code == 401
    assert appli.get(f"{C.CHEMIN}?limite=5&page=1", headers=_entetes("limite=5&page=1", cle="autre")).status_code == 401


def test_comptes_clients_actifs_seulement(appli, monkeypatch):
    monkeypatch.setenv("SAWALI_CONTACTS_HMAC", CLE)
    q = "limite=500&page=1"
    r = appli.get(f"{C.CHEMIN}?{q}", headers=_entetes(q))
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["plateforme"] == "ALBARKA" and d["total"] == 1
    assert d["contacts"][0] == {"id": "c1", "nom": "Pharmacie du Centre", "telephone": "22890112233", "role": "client",
                                "societe": "ALBARKA · Pharmacie du Centre"}
    # Ni l'annuaire des clients, ni les suspendus, ni les collègues, ni les administrateurs, ni les données sensibles
    assert "22891000009" not in r.text and "p@x.tg" not in r.text and "secret" not in r.text
