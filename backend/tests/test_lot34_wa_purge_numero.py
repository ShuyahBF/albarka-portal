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
    app.dependency_overrides[inbox.get_current_user] = lambda: {"id": "u1", "email": email, "role": "superviseur", "roles": ["superviseur"]}
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


# ---- Lot 36 : état de l'envoi sous le message (Transmis → Distribué → Lu), sans jamais reculer ----

def test_etat_du_message_avance_sans_reculer_et_garde_l_heure_de_chaque_etape():
    import asyncio
    import albarka_transmission_wa as tw
    db = mongomock_motor.AsyncMongoMockClient()["test36"]

    async def scenario():
        await db.wa_messages.insert_one({"id": "m1", "direction": "outbound", "wa_message_id": "wamid.1"})
        for statut, date in (("sent", "2026-10-19T22:27:36+00:00"), ("read", "2026-10-19T22:28:10+00:00"),
                             ("delivered", "2026-10-19T22:27:50+00:00")):          # « distribué » arrive APRÈS « lu »
            await tw._appliquer_statut(db, {"statut": statut, "date": date, "message_id": "wamid.1", "id_origine": None})
        return await db.wa_messages.find_one({"id": "m1"}, {"_id": 0})
    m = asyncio.get_event_loop().run_until_complete(scenario())
    assert m["wa_status"] == "read"                                                  # l'état global ne recule pas
    assert set(m["wa_status_times"]) == {"sent", "delivered", "read"}
    assert m["wa_status_times"]["delivered"].startswith("2026-10-19T22:27:50")


# ---- Lot 38 : « Répondre » en citant un message de la conversation ----

def test_reponse_citee_transmet_l_identifiant_whatsapp_reel_et_garde_un_apercu(monkeypatch):
    import albarka_notifications as notif
    envois = []

    async def faux_send(*, to_phone, message, reply_to=None):
        envois.append({"to": to_phone, "message": message, "reply_to": reply_to})
        return {"ok": True, "message_id": "wamid.SORTANT"}

    async def faux_contact(phone):
        return "c1", "Mr OUOBA"
    monkeypatch.setattr(notif, "send_whatsapp", faux_send)
    monkeypatch.setattr(inbox, "_resolve_contact", faux_contact)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    c.portal.call(c.db.wa_messages.insert_many, [
        {"id": "in1", "phone": "+22670000009", "direction": "inbound", "body": "Bonjour cabinet", "contact_name": "Mr OUOBA",
         "wa_message_id": "liluvine:reponse:x", "wa_real_id": "wamid.RECU9"},
        {"id": "in2", "phone": "+22670000009", "direction": "inbound", "body": "Ancien message", "wa_message_id": "liluvine:reponse:y"}])
    r = c.post("/api/whatsapp/conversations/+22670000009/reply", json={"body": "Bonjour, je vous écoute", "reply_to_id": "in1"})
    assert r.status_code == 200 and envois[-1]["reply_to"] == "wamid.RECU9"                 # identifiant Meta réel transmis
    assert r.json()["message"]["reply_to"]["texte"] == "Bonjour cabinet" and r.json()["message"]["reply_to"]["auteur"] == "Mr OUOBA"
    # Message sans identifiant Meta connu (« liluvine:… ») : l'envoi part quand même, sans citation WhatsApp, aperçu gardé
    r = c.post("/api/whatsapp/conversations/+22670000009/reply", json={"body": "Merci", "reply_to_id": "in2"})
    assert r.status_code == 200 and envois[-1]["reply_to"] is None and r.json()["message"]["reply_to"]["texte"] == "Ancien message"
    # Message cité d'une autre conversation : ignoré
    r = c.post("/api/whatsapp/conversations/+22670000009/reply", json={"body": "Autre", "reply_to_id": "inconnu"})
    assert r.status_code == 200 and envois[-1]["reply_to"] is None and r.json()["message"]["reply_to"] is None
