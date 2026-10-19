"""Lot 34 — conversations WhatsApp : remise à zéro réservée au super-admin (avec confirmation) et numéro WhatsApp du cabinet.
Tests unitaires (base simulée) : aucun appel au serveur réel."""
import os
import sys
from datetime import datetime, timedelta, timezone
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


@pytest.fixture(autouse=True)
def _pas_de_suspension(monkeypatch):
    """Aucun contrat échu dans ces tests : on n'interroge pas la vraie base (lot 41)."""
    import albarka_suspension

    async def pas_suspendu(_):
        return None
    monkeypatch.setattr(albarka_suspension, "refus_envoi", pas_suspendu)


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
         "wa_message_id": "liluvine:reponse:x", "wa_real_id": "wamid.RECU9",
         "created_at": datetime.now(timezone.utc).isoformat()},   # reçu à l'instant → fenêtre de 24 h ouverte
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


# ---- Lot 39 : confirmation avant un envoi hors fenêtre de 24 h (modèle Meta facturé) ----

def test_envoi_hors_fenetre_24h_demande_la_confirmation_du_cabinet(monkeypatch):
    import albarka_notifications as notif
    envois = []

    async def faux_send(*, to_phone, message, reply_to=None):
        envois.append(message)
        return {"ok": True, "message_id": "wamid.X"}

    async def faux_contact(phone):
        return "c1", "Mr OUOBA"
    monkeypatch.setattr(notif, "send_whatsapp", faux_send)
    monkeypatch.setattr(inbox, "_resolve_contact", faux_contact)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    ancien = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    c.portal.call(c.db.wa_messages.insert_one, {"id": "v1", "phone": "+22670000008", "direction": "inbound", "body": "vieux", "created_at": ancien})
    url = "/api/whatsapp/conversations/+22670000008/reply"
    # 1) sans accord : refus 409 « hors_fenetre_24h », rien n'est envoyé ni enregistré
    r = c.post(url, json={"body": "Bonjour"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hors_fenetre_24h" and envois == []
    assert c.portal.call(c.db.wa_messages.count_documents, {"direction": "outbound"}) == 0
    # 2) avec l'accord du cabinet : l'envoi part
    r = c.post(url, json={"body": "Bonjour", "confirmer_modele": True})
    assert r.status_code == 200 and envois == ["Bonjour"]
    # 3) contact jamais venu : fenêtre fermée aussi
    assert c.post("/api/whatsapp/conversations/+22670000007/reply", json={"body": "x"}).status_code in (404, 409)


# ---- Lot 40 : même contrôle pour les envois de pièces (bulletins) et de situations de compte ----

def test_refus_hors_fenetre_commun_aux_envois_de_pieces():
    import asyncio
    from fastapi import HTTPException
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    ancien = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    c.portal.call(c.db.wa_messages.insert_one, {"id": "o1", "phone": "+22670000006", "direction": "inbound", "created_at": ancien})
    # Fenêtre fermée et pas d'accord → 409 « hors_fenetre_24h »
    with pytest.raises(HTTPException) as e:
        asyncio.run(inbox.refus_hors_fenetre("+22670000006", False))
    assert e.value.status_code == 409 and e.value.detail["code"] == "hors_fenetre_24h"
    # Avec l'accord du cabinet → aucun refus
    asyncio.run(inbox.refus_hors_fenetre("+22670000006", True))
    # Contact qui vient d'écrire → fenêtre ouverte, aucun refus
    c.portal.call(c.db.wa_messages.insert_one, {"id": "o2", "phone": "+22670000006", "direction": "inbound",
                                                "created_at": datetime.now(timezone.utc).isoformat()})
    asyncio.run(inbox.refus_hors_fenetre("+22670000006", False))
