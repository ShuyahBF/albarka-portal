"""Lot 13.9 — Transmission WA Universelle Liluvine, protocole v3.

Couvre : médias (lien, octets, refus local au-delà de 10 Mo), envoi de
documents sans WABA par Liluvine, webhook de retour (signature 401, fenêtre
± 5 min, idempotence, réponse visible dans la boîte WhatsApp, statut appliqué),
refus 409 « désinscrit » sans nouvel essai, repli WABA -> Liluvine hors fenêtre
de 24 h et absence de repli sur numéro invalide, route super-admin des retours.
Tests autonomes : MongoDB simulé (mongomock-motor), httpx simulé (MockTransport).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

URL_SAWALI = "https://sawali.test/api/webhook/liluvine-send"
CLE = "cle-de-test-hmac-v3"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def base(monkeypatch):
    """Base MongoDB simulée, branchée à la place de la vraie (y compris
    dans la boîte WhatsApp, qui importe db au chargement)."""
    import db as db_module
    import albarka_admin_settings as ad
    import albarka_wa_inbox as inbox
    client = mongomock_motor.AsyncMongoMockClient()
    base_test = client["albarka_lot13_9"]
    monkeypatch.setattr(db_module, "db", base_test)
    monkeypatch.setattr(ad, "db", base_test)
    monkeypatch.setattr(inbox, "db", base_test)
    return base_test


@pytest.fixture()
def liluvine(monkeypatch):
    """Variables de la transmission universelle renseignées."""
    monkeypatch.setenv("LILUVINE_WA_URL", URL_SAWALI)
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    monkeypatch.setenv("LILUVINE_WA_EMETTEUR", "albarka")


@pytest.fixture()
def reseau(monkeypatch):
    """httpx simulé : `reponses` (SAWALI) et `reponses_meta` (Meta) servies
    dans l'ordre ; par défaut, succès des deux côtés."""
    etat = type("Reseau", (), {})()
    etat.appels, etat.appels_meta = [], []
    etat.reponses, etat.reponses_meta = [], []
    original = httpx.AsyncClient

    def gestion(requete: httpx.Request):
        if "graph.facebook.com" in str(requete.url):
            etat.appels_meta.append(requete)
            if str(requete.url).endswith("/media"):
                return httpx.Response(200, json={"id": "media-123"})
            rep = etat.reponses_meta.pop(0) if etat.reponses_meta else httpx.Response(
                200, json={"messages": [{"id": "wamid.META"}]})
            return rep
        etat.appels.append(requete)
        rep = etat.reponses.pop(0) if etat.reponses else httpx.Response(
            200, json={"ok": True, "message_id": "wamid.SAWALI", "doublon": False, "media_mode": "direct"})
        if isinstance(rep, Exception):
            raise rep
        return rep

    def fabrique(*args, **kwargs):
        kwargs.pop("transport", None)
        return original(*args, transport=httpx.MockTransport(gestion), **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", fabrique)
    return etat


async def _regler_waba(base_test, actif: bool):
    """Paramètres WABA d'ALBARKA en base (settings/global)."""
    await base_test.settings.update_one(
        {"_id": "global"},
        {"$set": {"wa_enabled": actif, "wa_access_token": "jeton-meta" if actif else "",
                  "wa_phone_number_id": "123456" if actif else ""}},
        upsert=True,
    )


def _signe(corps: dict, ts: int | None = None, cle: str = CLE):
    """Corps brut + en-têtes signés comme SAWALI."""
    brut = json.dumps(corps, ensure_ascii=False)
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut.encode("utf-8"), {"Content-Type": "application/json", "X-Emetteur": "sawali",
                                  "X-Timestamp": str(ts), "X-Signature": sig}


def _client_api():
    """Application FastAPI minimale avec les routeurs du lot 13.9 sous /api."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import albarka_transmission_wa as tw
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(tw.router)
    api.include_router(tw.retour_router)
    api.include_router(tw.admin_alias_router)
    app.include_router(api)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. Médias : lien, octets, refus > 10 Mo
# ---------------------------------------------------------------------------
def test_media_par_lien(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    _run(_regler_waba(base, False))
    r = _run(tw.envoyer_whatsapp("+22670000010", "Votre facture", media={
        "type": "document", "url": "https://r2.test/facture.pdf?sig=abc",
        "nom_fichier": "facture-1.pdf", "mime": "application/pdf"}))
    assert r["ok"] and r["canal"] == "liluvine" and r["media_mode"] == "direct"
    corps = json.loads(reseau.appels[0].content)
    assert corps["media"]["url"] == "https://r2.test/facture.pdf?sig=abc"
    assert "contenu_base64" not in corps["media"] and corps["media"]["type"] == "document"
    assert corps["message"] == "Votre facture"
    # Signature calculée sur le corps exact, média compris
    req = reseau.appels[0]
    attendu = hmac.new(CLE.encode(), f"{req.headers['X-Timestamp']}.{req.content.decode()}".encode(),
                       hashlib.sha256).hexdigest()
    assert req.headers["X-Signature"] == attendu


def test_media_par_octets(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    _run(_regler_waba(base, False))
    octets = b"%PDF-1.4 contenu de test"
    r = _run(tw.envoyer_whatsapp("+22670000011", "Pièce", media={
        "contenu": octets, "nom_fichier": "piece.pdf", "mime": "application/pdf"}))
    assert r["ok"]
    m = json.loads(reseau.appels[0].content)["media"]
    assert base64.b64decode(m["contenu_base64"]) == octets
    assert m["type"] == "document" and m["nom_fichier"] == "piece.pdf" and "url" not in m


def test_media_trop_gros_refuse_sans_appel(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    _run(_regler_waba(base, False))
    gros = b"0" * (10 * 1024 * 1024 + 1)
    r = _run(tw.envoyer_whatsapp("+22670000012", "Gros", media={
        "contenu": gros, "nom_fichier": "gros.pdf", "mime": "application/pdf"}))
    assert not r["ok"] and "10 Mo" in r["erreur"]
    assert reseau.appels == [] and reseau.appels_meta == []
    # Lien ET octets à la fois : refusé aussi
    r = _run(tw.envoyer_liluvine("+22670000012", "x", media={"contenu": b"a", "url": "https://a.test/b"}))
    assert not r["ok"] and reseau.appels == []


def test_document_sans_waba_part_par_liluvine(base, liluvine, reseau):
    """Envoi de document (situation de compte, factures, pièces, rapports) :
    sans WABA, le fichier part en octets par Liluvine."""
    from albarka_notifications import send_whatsapp_fichier
    _run(_regler_waba(base, False))
    r = _run(send_whatsapp_fichier(to_phone="+22670000013", data=b"%PDF-1.4 sit", filename="situation.pdf",
                                   content_type="application/pdf", caption="Situation de compte"))
    assert r["ok"] and r["canal"] == "liluvine" and reseau.appels_meta == []
    corps = json.loads(reseau.appels[0].content)
    assert corps["message"] == "Situation de compte"
    assert base64.b64decode(corps["media"]["contenu_base64"]) == b"%PDF-1.4 sit"
    # Fichier > 10 Mo avec lien R2 présigné : envoyé par lien
    reseau.appels.clear()
    r = _run(send_whatsapp_fichier(to_phone="+22670000013", data=b"0" * (10 * 1024 * 1024 + 5),
                                   filename="gros.pdf", caption="Gros", url="https://r2.test/gros.pdf?sig=1"))
    assert r["ok"] and json.loads(reseau.appels[0].content)["media"]["url"] == "https://r2.test/gros.pdf?sig=1"


# ---------------------------------------------------------------------------
# 2. Webhook de retour
# ---------------------------------------------------------------------------
def test_retour_signature_invalide_401(base, liluvine):
    client = _client_api()
    corps = {"type": "reponse", "de": "+22670000020", "texte": "Bonjour", "date": "2026-10-04T10:00:00Z"}
    brut, entetes = _signe(corps, cle="mauvaise-cle")
    assert client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes).status_code == 401
    # Horodatage hors fenêtre de ± 5 min
    brut, entetes = _signe(corps, ts=int(time.time()) - 600)
    assert client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes).status_code == 401
    # Corps modifié après signature
    brut, entetes = _signe(corps)
    assert client.post("/api/webhooks/liluvine-retour", content=brut.replace(b"Bonjour", b"Bonsoir"),
                       headers=entetes).status_code == 401
    assert _run(base.liluvine_retours.count_documents({})) == 0


def test_retour_reponse_visible_dans_boite_et_idempotent(base, liluvine):
    import albarka_wa_inbox as inbox
    _run(base.contacts.insert_one({"id": "c1", "phone": "+22670000021", "full_name": "Awa Traoré"}))
    client = _client_api()
    corps = {"type": "reponse", "id_origine": "id-envoi-1", "de": "+22670000021",
             "texte": "Merci, bien reçu", "media": None, "date": "2026-10-04T10:00:00Z"}
    brut, entetes = _signe(corps)
    r1 = client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes)
    assert r1.status_code == 200 and r1.json() == {"ok": True, "doublon": False}
    # Même retour reçu deux fois : aucun doublon
    brut, entetes = _signe(corps)
    r2 = client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes)
    assert r2.status_code == 200 and r2.json()["doublon"] is True
    assert _run(base.liluvine_retours.count_documents({"type": "reponse"})) == 1
    msgs = _run(base.wa_messages.find({"phone": "+22670000021"}, {"_id": 0}).to_list(10))
    assert len(msgs) == 1
    m = msgs[0]
    assert m["direction"] == "inbound" and m["body"] == "Merci, bien reçu" and m["via_liluvine"] is True
    assert m["contact_name"] == "Awa Traoré" and m["read_by_staff_at"] is None
    # Visible dans la boîte WhatsApp (liste des conversations, non lu)
    convs = _run(inbox.list_conversations(user={"roles": ["direction"]}))
    conv = [c for c in convs if c["phone"] == "+22670000021"][0]
    assert conv["unread"] == 1 and conv["last_body"] == "Merci, bien reçu"
    # Une réponse via Liluvine n'ouvre pas la fenêtre de 24 h du WABA d'ALBARKA
    from albarka_notifications import _wa_last_inbound_iso
    assert _run(_wa_last_inbound_iso("+22670000021")) is None


def test_retour_statut_met_a_jour_envoi(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    _run(_regler_waba(base, False))
    r = _run(tw.envoyer_liluvine("+22670000022", "Bonjour"))
    _run(base.wa_messages.insert_one({"id": "o1", "direction": "outbound", "phone": "+22670000022",
                                      "wa_message_id": "wamid.SAWALI", "body": "Bonjour"}))
    client = _client_api()
    for statut in ("sent", "delivered"):
        brut, entetes = _signe({"type": "statut", "id": r["id"], "message_id": "wamid.SAWALI",
                                "statut": statut, "erreur": None, "date": "2026-10-04T10:01:00Z"})
        assert client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes).status_code == 200
    envoi = _run(base.liluvine_envois.find_one({"id": r["id"]}))
    assert envoi["statut"] == "delivered"
    sortant = _run(base.wa_messages.find_one({"id": "o1"}))
    assert sortant["wa_status"] == "delivered"
    assert _run(base.liluvine_retours.count_documents({"type": "statut"})) == 2


def test_retour_desinscription_et_route_admin(base, liluvine):
    import albarka_transmission_wa as tw
    import albarka_sauvegarde as sv
    client = _client_api()
    brut, entetes = _signe({"type": "desinscription", "de": "+22670000023", "date": "2026-10-04T10:02:00Z"})
    assert client.post("/api/webhooks/liluvine-retour", content=brut, headers=entetes).status_code == 200
    res = _run(tw.retours_transmission(user={"email": "admin@sawalismartsystems.com"}))
    assert res["retours"][0]["type"] == "desinscription" and res["retours"][0]["numero"] == "+22670000023"
    # Routes admin protégées par require_super_admin (la route publique ne l'est pas)
    for rt in list(tw.router.routes) + list(tw.admin_alias_router.routes):
        assert any(d.call is sv.require_super_admin for d in rt.dependant.dependencies)
    assert "/_admin/transmission-wa/retours" in {r.path for r in tw.router.routes}
    assert "/webhooks/liluvine-retour" in {r.path for r in tw.retour_router.routes}


# ---------------------------------------------------------------------------
# 3. Désinscription : 409 = échec définitif, sans nouvel essai
# ---------------------------------------------------------------------------
def test_409_desinscrit_sans_nouvel_essai(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    _run(_regler_waba(base, False))
    reseau.reponses = [httpx.Response(409, json={"detail": "Destinataire désinscrit"})]
    r = _run(tw.envoyer_liluvine("+22670000030", "Bonjour"))
    assert not r["ok"] and r["definitif"] and r["desinscrit"] and len(reseau.appels) == 1
    trace = _run(base.liluvine_retours.find_one({"type": "refus_desinscrit"}))
    assert trace and trace["numero"] == "+22670000030"
    # Par l'envoi de base : même échec définitif
    reseau.reponses = [httpx.Response(409, json={"detail": "Destinataire désinscrit"})]
    from albarka_notifications import send_whatsapp
    b = _run(send_whatsapp(to_phone="+22670000030", message="Bonjour"))
    assert b["ok"] is False and b["kind"] == "unsubscribed" and b["desinscrit"] and len(reseau.appels) == 2


# ---------------------------------------------------------------------------
# 4. Repli si le WABA propre échoue
# ---------------------------------------------------------------------------
def test_repli_waba_hors_fenetre_24h(base, liluvine, reseau):
    from albarka_notifications import send_whatsapp, send_whatsapp_fichier
    _run(_regler_waba(base, True))
    # Dernier message entrant il y a 3 jours : fenêtre de 24 h fermée
    ancien = (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()
    _run(base.wa_messages.insert_one({"phone": "+22670000040", "direction": "inbound", "created_at": ancien}))
    erreur_meta = {"error": {"code": 131047, "message": "Re-engagement message",
                             "error_data": {"details": "More than 24 hours have passed"}}}
    reseau.reponses_meta = [httpx.Response(400, json=erreur_meta)]
    r = _run(send_whatsapp(to_phone="+22670000040", message="Rappel d'échéance"))
    assert r["ok"] and r["canal"] == "liluvine_repli" and r["outside_24h_window"] is True
    assert len(reseau.appels_meta) == 1 and len(reseau.appels) == 1
    assert json.loads(reseau.appels[0].content)["message"] == "Rappel d'échéance"
    # Document : même repli, avec le même fichier
    reseau.reponses_meta = [httpx.Response(400, json=erreur_meta)]
    d = _run(send_whatsapp_fichier(to_phone="+22670000040", data=b"%PDF-1.4 f", filename="facture.pdf",
                                   caption="Facture F-1"))
    assert d["ok"] and d["canal"] == "liluvine_repli"
    m = json.loads(reseau.appels[-1].content)["media"]
    assert base64.b64decode(m["contenu_base64"]) == b"%PDF-1.4 f" and m["nom_fichier"] == "facture.pdf"


def test_pas_de_repli_sur_numero_invalide(base, liluvine, reseau):
    from albarka_notifications import send_whatsapp
    _run(_regler_waba(base, True))
    reseau.reponses_meta = [httpx.Response(400, json={"error": {
        "code": 100, "message": "(#100) Invalid parameter",
        "error_data": {"details": "Invalid WhatsApp phone number"}}})]
    r = _run(send_whatsapp(to_phone="+22670000041", message="Bonjour"))
    assert r["ok"] is False and r["kind"] == "http_error" and reseau.appels == []
    # Numéro sans indicatif : refus local, ni Meta ni SAWALI
    r = _run(send_whatsapp(to_phone="70000041", message="Bonjour"))
    assert r["kind"] == "invalid_phone" and reseau.appels == []


def test_pas_de_repli_sans_liluvine(base, reseau, monkeypatch):
    from albarka_notifications import send_whatsapp
    monkeypatch.delenv("LILUVINE_WA_URL", raising=False)
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)
    _run(_regler_waba(base, True))
    reseau.reponses_meta = [httpx.Response(400, json={"error": {"code": 131047}})]
    r = _run(send_whatsapp(to_phone="+22670000042", message="Bonjour"))
    assert r["ok"] is False and reseau.appels == []
