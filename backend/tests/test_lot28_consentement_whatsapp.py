"""Lot 28 — case facultative de consentement WhatsApp à l'inscription des officines : accord noté (date, moyen, IP) seulement
si cochée ; transmis à SAWALI avec sa date ; adresse IP jamais renvoyée au navigateur. MongoDB simulé, aucun réseau.
Lancer : cd backend && python -m pytest tests/test_lot28_consentement_whatsapp.py -q"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

from routes import officines_portal as OP  # noqa: E402
from routes import sawali_contacts as C  # noqa: E402

CLE = "cle-contacts-test"


def lancer(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


@pytest.fixture()
def appli():
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    db = mongomock_motor.AsyncMongoMockClient()["albarka_l28"]
    app, api = FastAPI(), APIRouter(prefix="/api")
    OP.attach_officines_portal_routes(api, db=db, jwt_secret="secret-de-test")
    C.setup_sawali_contacts_routes(db=db, api=api)
    app.include_router(api)
    return TestClient(app), db


def inscrire(client, nom, tel, **extra):
    return client.post("/api/officines-portal/register", headers={"X-Forwarded-For": "41.138.0.7, 10.0.0.1"},
                       json={"name": nom, "email": f"{tel}@x.bf", "phone": f"+226{tel}", **extra})


def test_consentement_note_puis_transmis_a_sawali(appli, monkeypatch):
    client, db = appli
    monkeypatch.setenv("SAWALI_CONTACTS_HMAC", CLE)
    assert inscrire(client, "Pharmacie Oui", "70000001", accepte_whatsapp=True).status_code == 200
    assert inscrire(client, "Pharmacie Non", "70000002").status_code == 200                 # case non cochée
    oui = lancer(db.officines.find_one({"name": "Pharmacie Oui"}))
    non = lancer(db.officines.find_one({"name": "Pharmacie Non"}))
    assert oui["accepte_whatsapp"] is True and oui["accepte_whatsapp_moyen"] == "inscription"
    assert oui["accepte_whatsapp_le"] and oui["accepte_whatsapp_ip"] == "41.138.0.7"          # première adresse de la chaîne
    assert "accepte_whatsapp" not in non                                                    # jamais d'accord inventé
    # SAWALI ne reçoit que l'officine qui a coché la case, avec la date de son accord
    q = "limite=500&page=1"
    ts = str(int(time.time()))
    r = client.get(f"{C.CHEMIN}?{q}", headers={"X-Timestamp": ts, "X-Signature": C.signer(CLE, ts, C.CHEMIN, q)})
    assert r.status_code == 200, r.text
    contacts = r.json()["contacts"]
    assert [c["nom"] for c in contacts] == ["Pharmacie Oui"]
    assert contacts[0]["role"] == "officine" and contacts[0]["accepte_whatsapp"] is True and contacts[0]["accepte_le"]
    assert "70000002" not in r.text and "41.138.0.7" not in r.text


def test_adresse_ip_jamais_renvoyee_a_l_officine():
    assert "accepte_whatsapp_ip" not in OP._strip_officine({"_id": 1, "id": "o1", "accepte_whatsapp": True, "accepte_whatsapp_ip": "1.2.3.4"})
