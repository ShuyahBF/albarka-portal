"""Lot 34 — conversations WhatsApp : remise à zéro réservée au super-admin (avec confirmation) et numéro WhatsApp du cabinet.
Tests unitaires (base simulée) : aucun appel au serveur réel."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot34")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot34")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_wa_inbox as inbox  # noqa: E402
from albarka_models import ADMIN_ACCOUNT_EMAIL  # noqa: E402


def _appli(email):
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    inbox.db = db
    app = FastAPI()
    app.include_router(inbox.router, prefix="/api")
    app.dependency_overrides[inbox.get_current_user] = lambda: {"id": "u1", "email": email, "role": "superviseur"}
    c = TestClient(app).__enter__()
    c.portal.call(db.wa_messages.insert_many, [{"phone": "+22670000001", "body": "a"}, {"phone": "+22670000002", "body": "b"}])
    c.portal.call(db.wa_conversation_labels.insert_one, {"phone": "+22670000001", "label": "todo"})
    c.db = db
    return c


def test_purge_reservee_au_super_admin():
    c = _appli("collaborateur@albarka.test")
    r = c.post("/api/whatsapp/conversations/purge", json={"confirmation": "SUPPRIMER"})
    assert r.status_code == 403
    assert c.portal.call(c.db.wa_messages.count_documents, {}) == 2          # rien n'a été supprimé


def test_purge_exige_la_confirmation():
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    assert c.post("/api/whatsapp/conversations/purge", json={"confirmation": "oui"}).status_code == 422
    assert c.post("/api/whatsapp/conversations/purge", json={}).status_code == 422
    assert c.portal.call(c.db.wa_messages.count_documents, {}) == 2


def test_purge_vide_messages_et_etiquettes():
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    r = c.post("/api/whatsapp/conversations/purge", json={"confirmation": "supprimer"})
    assert r.status_code == 200 and r.json()["messages_supprimes"] == 2 and r.json()["etiquettes_supprimees"] == 1
    assert c.portal.call(c.db.wa_messages.count_documents, {}) == 0
    assert c.portal.call(c.db.wa_conversation_labels.count_documents, {}) == 0
