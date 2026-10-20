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


# ---- Lot 44 : réponse à une citation faite depuis le téléphone → la citation apparaît côté cabinet ----

def test_reponse_a_une_citation_du_telephone_affiche_le_message_cite(monkeypatch):
    import asyncio
    import albarka_transmission_wa as tw

    async def faux_contact(phone):
        return "c1", "Mr OUOBA"
    monkeypatch.setattr(inbox, "_resolve_contact", faux_contact)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    c.portal.call(c.db.wa_messages.insert_one, {
        "id": "out1", "phone": "+22670000005", "direction": "outbound", "body": "Votre bulletin est prêt",
        "wa_message_id": "wamid.CITE1", "sent_by_name": "Cabinet ALBARKA"})
    retour = {"type": "reponse", "numero": "+22670000005", "texte": "Merci", "date": datetime.now(timezone.utc).isoformat(),
              "cite_message_id": "wamid.CITE1", "id_origine": None, "media": None}
    asyncio.run(tw._poser_reponse_dans_boite(c.db, retour, "reponse:test"))
    recu = c.portal.call(c.db.wa_messages.find_one, {"direction": "inbound", "phone": "+22670000005"})
    assert recu["reply_to"]["texte"] == "Votre bulletin est prêt" and recu["reply_to"]["auteur"] == "Cabinet ALBARKA"
    # Message cité inconnu : la réponse est quand même posée, sans citation
    retour2 = {**retour, "cite_message_id": "wamid.INCONNU", "date": "2026-10-20T00:00:00+00:00"}
    asyncio.run(tw._poser_reponse_dans_boite(c.db, retour2, "reponse:test2"))
    sans = c.portal.call(c.db.wa_messages.find_one, {"wa_message_id": "liluvine:reponse:test2"})
    assert sans["body"] == "Merci" and "reply_to" not in sans


# ---- Lots 45 / 47 / 50 : fichiers joints = bibliothèque seulement (documents ET images, partageables) ; fichiers reçus visibles ----

def _app_fichier(monkeypatch):
    import albarka_notifications as notif
    import albarka_storage as stor
    envois, stockes = [], []

    async def faux_fichier(**kw):
        envois.append((kw["to_phone"], kw["filename"], kw["content_type"], kw["caption"]))
        return {"ok": True, "message_id": "wamid.F1"}

    async def faux_put(chemin, donnees, ct):
        stockes.append((chemin, ct))
        return {}

    async def faux_get(chemin):
        return b"%PDF-contenu", "application/pdf"

    async def faux_contact(phone):
        return "c1", "Mr OUOBA"
    monkeypatch.setattr(notif, "send_whatsapp_fichier", faux_fichier)
    monkeypatch.setattr(stor, "put_object", faux_put)
    monkeypatch.setattr(stor, "get_object", faux_get)
    monkeypatch.setattr(inbox, "_resolve_contact", faux_contact)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    c.portal.call(c.db.wa_messages.insert_one, {"id": "r1", "phone": "+22670000004", "direction": "inbound",
                                                "created_at": datetime.now(timezone.utc).isoformat()})   # fenêtre de 24 h ouverte
    return c, envois, stockes


def test_plus_aucun_envoi_libre_de_fichier_depuis_l_appareil(monkeypatch):
    c, envois, _ = _app_fichier(monkeypatch)
    r = c.post("/api/whatsapp/conversations/+22670000004/send-file", files={"fichier": ("photo.png", b"\x89PNG", "image/png")})
    assert r.status_code in (404, 405) and envois == []          # la route n'existe plus : tout vient de la bibliothèque


def test_document_et_image_de_la_bibliotheque_envoyes_seulement_s_ils_sont_partageables(monkeypatch):
    c, envois, _ = _app_fichier(monkeypatch)
    c.portal.call(c.db.archives.insert_many, [
        {"id": "A1", "title": "Contrat type", "storage_path": "bibliotheque/a1.pdf", "original_filename": "contrat.pdf",
         "content_type": "application/pdf", "partageable": True},
        {"id": "A4", "title": "Plan d'accès", "storage_path": "bibliotheque/a4.png", "original_filename": "plan.png",
         "content_type": "image/png", "partageable": True},
        {"id": "A2", "title": "Note interne", "storage_path": "bibliotheque/a2.pdf", "original_filename": "note.pdf",
         "content_type": "application/pdf", "partageable": False},
        {"id": "A3", "title": "Événement sans fichier", "partageable": True}])
    url = "/api/whatsapp/conversations/+22670000004/send-archive"
    r = c.post(url, json={"archive_id": "A1", "legende": "Pour signature ✍️"})
    assert r.status_code == 200 and r.json()["ok"]
    assert envois[-1] == ("+22670000004", "contrat.pdf", "application/pdf", "Pour signature ✍️")
    m = r.json()["message"]
    assert m["message_type"] == "document" and m["archive_id"] == "A1" and "media_path" not in m
    r = c.post(url, json={"archive_id": "A4"})                               # lot 50 : image de la bibliothèque
    assert r.status_code == 200 and envois[-1][2] == "image/png" and r.json()["message"]["message_type"] == "image"
    assert c.post(url, json={"archive_id": "A2"}).status_code == 403          # non partageable
    assert c.post(url, json={"archive_id": "A3"}).status_code == 404          # pas de fichier dans la bibliothèque
    assert c.post(url, json={"archive_id": "inconnu"}).status_code == 404
    assert len(envois) == 2
    # L'écran relit la conversation : le fichier est annoncé disponible, le chemin interne n'est pas exposé
    liste = c.get("/api/whatsapp/conversations/+22670000004/messages").json()
    envoyes = [x for x in liste if x.get("media_filename")]
    assert envoyes and all(x["fichier_disponible"] and "media_path" not in x for x in envoyes)
    assert c.get(f"/api/whatsapp/messages/{envoyes[0]['id']}/fichier").content == b"%PDF-contenu"


def test_envoi_d_un_fichier_de_la_bibliotheque_hors_fenetre_demande_l_accord(monkeypatch):
    c, envois, _ = _app_fichier(monkeypatch)
    c.portal.call(c.db.wa_messages.delete_many, {})
    ancien = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat()
    c.portal.call(c.db.wa_messages.insert_one, {"id": "v9", "phone": "+22670000004", "direction": "inbound", "created_at": ancien})
    c.portal.call(c.db.archives.insert_one, {"id": "A1", "title": "Contrat", "storage_path": "b/a1.pdf", "original_filename": "c.pdf",
                                             "content_type": "application/pdf", "partageable": True})
    url = "/api/whatsapp/conversations/+22670000004/send-archive"
    r = c.post(url, json={"archive_id": "A1"})
    assert r.status_code == 409 and r.json()["detail"]["code"] == "hors_fenetre_24h" and envois == []
    assert c.post(url, json={"archive_id": "A1", "confirmer_modele": True}).status_code == 200 and len(envois) == 1


def test_fichiers_recus_conserves_et_visibles_dans_le_fil(monkeypatch):
    import asyncio
    import albarka_transmission_wa as tw
    c, _, stockes = _app_fichier(monkeypatch)
    c.portal.call(c.db.wa_messages.insert_one, {"id": "img1", "phone": "+22670000004", "direction": "inbound", "message_type": "image",
                                                "media_kind": "image", "created_at": datetime.now(timezone.utc).isoformat()})
    # Image reçue par le webhook Meta : conservée ; vidéo et type inconnu : jamais conservés
    assert asyncio.run(inbox.conserver_fichier_recu("img1", b"\xff\xd8jpeg", "image/jpeg", None)) is True
    assert asyncio.run(inbox.conserver_fichier_recu("img1", b"x", "video/mp4", None)) is False
    assert asyncio.run(inbox.conserver_fichier_recu("img1", b"x" * (10 * 1024 * 1024 + 1), "image/png", None)) is False
    assert stockes[0][1] == "image/jpeg" and stockes[0][0].endswith(".jpg") and len(stockes) == 1
    liste = c.get("/api/whatsapp/conversations/+22670000004/messages").json()
    recu = [x for x in liste if x["id"] == "img1"][0]
    assert recu["fichier_disponible"] is True and "media_path" not in recu
    # Réponse relayée par la Transmission universelle avec un document : copie lancée en arrière-plan
    lances = []

    async def faux_rapatrier(doc_id, url, mime, nom):
        lances.append((url, mime, nom))
    monkeypatch.setattr(inbox, "rapatrier_media_url", faux_rapatrier)

    async def principal():
        retour = {"type": "reponse", "numero": "+22670000004", "texte": "", "date": datetime.now(timezone.utc).isoformat(),
                  "media": {"type": "document", "url_temporaire": "https://sawali.test/f/abc", "mime": "application/pdf", "nom_fichier": "recu.pdf"}}
        await tw._poser_reponse_dans_boite(c.db, retour, "reponse:doc")
        await asyncio.sleep(0)
    asyncio.run(principal())
    assert lances == [("https://sawali.test/f/abc", "application/pdf", "recu.pdf")]


def test_purge_vide_aussi_le_support_sawali(monkeypatch):
    """Lot 59 — le bouton « Vider les conversations » demande aussi à SAWALI de vider l'espace Support."""
    import albarka_support_sawali as sup
    appels = []

    async def faux(chemin, corps, delai=15):
        appels.append((chemin, corps))
        return {"ok": True, "messages_supprimes": 4, "fichiers_supprimes": 1}
    monkeypatch.setattr(sup, "appeler_sawali", faux)
    monkeypatch.setattr(sup, "configure", lambda: True)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    r = c.post("/api/whatsapp/conversations/purge", json={"confirmation": "SUPPRIMER"}).json()
    assert appels == [("/support-plateforme/purge", {"confirmation": "SUPPRIMER"})]
    assert r["messages_supprimes"] == 2 and r["support"] == {"vide": True, "erreur": None, "messages_supprimes": 4, "fichiers_supprimes": 1}


def test_purge_locale_faite_meme_si_sawali_injoignable(monkeypatch):
    from fastapi import HTTPException
    import albarka_support_sawali as sup

    async def panne(chemin, corps, delai=15):
        raise HTTPException(status_code=503, detail="Support SAWALI injoignable : réessayez dans un instant")
    monkeypatch.setattr(sup, "appeler_sawali", panne)
    monkeypatch.setattr(sup, "configure", lambda: True)
    c = _appli(ADMIN_ACCOUNT_EMAIL)
    r = c.post("/api/whatsapp/conversations/purge", json={"confirmation": "SUPPRIMER"}).json()
    assert r["messages_supprimes"] == 2 and r["support"]["vide"] is False and "injoignable" in r["support"]["erreur"]
    assert c.portal.call(c.db.wa_messages.count_documents, {}) == 0
