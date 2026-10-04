"""Lot 13.8 — Transmission WA Universelle Liluvine.

Couvre : signature HMAC calculée sur le corps exact envoyé, repli Liluvine
quand le WABA d'ALBARKA n'est pas configuré (y compris depuis l'envoi de base
send_whatsapp et l'envoi par modèle), priorité au WABA quand il est configuré,
même id au nouvel essai (5xx / erreur réseau), aucun nouvel essai sur 4xx,
désactivation propre sans variables, routes super-admin sans secret.
Tests autonomes : MongoDB simulé (mongomock-motor), httpx simulé (MockTransport).
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

URL_SAWALI = "https://sawali.test/api/webhook/liluvine-send"
CLE = "cle-de-test-hmac"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def base(monkeypatch):
    """Base MongoDB simulée, branchée à la place de la vraie."""
    import db as db_module
    import albarka_admin_settings as ad
    client = mongomock_motor.AsyncMongoMockClient()
    base_test = client["albarka_lot13_8"]
    monkeypatch.setattr(db_module, "db", base_test)
    monkeypatch.setattr(ad, "db", base_test)
    return base_test


@pytest.fixture()
def liluvine(monkeypatch):
    """Variables de la transmission universelle renseignées."""
    monkeypatch.setenv("LILUVINE_WA_URL", URL_SAWALI)
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    monkeypatch.setenv("LILUVINE_WA_EMETTEUR", "albarka")


@pytest.fixture()
def reseau(monkeypatch):
    """Remplace httpx.AsyncClient par un client simulé. `reseau.reponses` est
    une liste de réponses (ou d'exceptions) servies dans l'ordre aux appels
    vers SAWALI ; les appels Meta reçoivent toujours un succès."""
    etat = type("Reseau", (), {})()
    etat.appels = []       # requêtes vers SAWALI
    etat.appels_meta = []  # requêtes vers graph.facebook.com
    etat.reponses = []
    original = httpx.AsyncClient

    def gestion(requete: httpx.Request):
        if "graph.facebook.com" in str(requete.url):
            etat.appels_meta.append(requete)
            return httpx.Response(200, json={"messages": [{"id": "wamid.META"}]})
        etat.appels.append(requete)
        rep = etat.reponses.pop(0) if etat.reponses else httpx.Response(
            200, json={"ok": True, "message_id": "wamid.SAWALI", "doublon": False})
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


# ---------------------------------------------------------------------------
# 1. Signature HMAC sur le corps exact, en-têtes du protocole
# ---------------------------------------------------------------------------
def test_signature_hmac_corps_exact(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    r = _run(tw.envoyer_liluvine("+22670000000", "Bonjour", source="Cabinet ALBARKA"))
    assert r["ok"] and r["canal"] == "liluvine" and r["message_id"] == "wamid.SAWALI"
    req = reseau.appels[0]
    corps_brut = req.content.decode("utf-8")
    attendu = hmac.new(CLE.encode(), f"{req.headers['X-Timestamp']}.{corps_brut}".encode(), hashlib.sha256).hexdigest()
    assert req.headers["X-Signature"] == attendu
    assert req.headers["X-Emetteur"] == "albarka"
    assert req.headers["Content-Type"] == "application/json"
    corps = json.loads(corps_brut)
    assert corps["to"] == "+22670000000" and corps["message"] == "Bonjour" and corps["source"] == "Cabinet ALBARKA"
    assert len(corps["id"]) == 36  # uuid4


# ---------------------------------------------------------------------------
# 2. Repli Liluvine sans WABA (fonction dédiée ET envoi de base)
# ---------------------------------------------------------------------------
def test_repli_liluvine_sans_waba(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    from albarka_notifications import send_whatsapp, send_whatsapp_template
    _run(_regler_waba(base, False))
    r = _run(tw.envoyer_whatsapp("+22670000001", "Rappel"))
    assert r == {"ok": True, "canal": "liluvine", "message_id": "wamid.SAWALI", "erreur": None,
                 "message_ids": ["wamid.SAWALI"], "statut": 200, "id": r["id"], "doublon": False}
    assert json.loads(reseau.appels[-1].content)["source"] == "Cabinet ALBARKA"
    # Envoi de base (rappels, notifications…) : repli automatique
    b = _run(send_whatsapp(to_phone="+22670000001", message="Échéance"))
    assert b["ok"] and b["kind"] == "success" and b["canal"] == "liluvine"
    # Modèle sans WABA : le texte rendu part par Liluvine…
    m = _run(send_whatsapp_template(to_phone="+22670000001", template_name="notif", texte_rendu="Texte rendu"))
    assert m["ok"] and m["canal"] == "liluvine"
    assert json.loads(reseau.appels[-1].content)["message"] == "Texte rendu"
    # … et sans texte rendu, l'échec d'origine est conservé.
    n = _run(send_whatsapp_template(to_phone="+22670000001", template_name="notif"))
    assert not n["ok"] and n["kind"] == "not_configured"
    assert reseau.appels_meta == []


def test_message_long_decoupe(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    r = _run(tw.envoyer_whatsapp("+22670000001", ("mot " * 1500).strip()))
    assert r["ok"] and len(reseau.appels) == 2
    assert all(len(json.loads(a.content)["message"]) <= 4096 for a in reseau.appels)


# ---------------------------------------------------------------------------
# 3. Priorité au WABA d'ALBARKA quand il est configuré
# ---------------------------------------------------------------------------
def test_priorite_waba(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    from albarka_notifications import send_whatsapp
    _run(_regler_waba(base, True))
    r = _run(tw.envoyer_whatsapp("+22670000002", "Bonjour"))
    assert r == {"ok": True, "canal": "waba", "message_id": "wamid.META", "erreur": None}
    b = _run(send_whatsapp(to_phone="+22670000002", message="Bonjour"))
    assert b["ok"] and "canal" not in b  # comportement WABA inchangé
    assert reseau.appels == [] and len(reseau.appels_meta) == 2


# ---------------------------------------------------------------------------
# 4. Nouvel essai : même id, nouvelle signature ; pas de nouvel essai sur 4xx
# ---------------------------------------------------------------------------
def test_nouvel_essai_meme_id_sur_5xx_et_reseau(base, liluvine, reseau, monkeypatch):
    import albarka_transmission_wa as tw
    import itertools
    horloge = itertools.count(1_000_000, 7)  # horloge qui avance à chaque lecture
    monkeypatch.setattr(tw.time, "time", lambda: next(horloge))
    reseau.reponses = [httpx.Response(503, json={"detail": "indisponible"})]
    r = _run(tw.envoyer_liluvine("+22670000003", "Bonjour"))
    assert r["ok"] and len(reseau.appels) == 2
    a, b = reseau.appels
    assert a.content == b.content  # même corps, donc même id
    assert a.headers["X-Timestamp"] != b.headers["X-Timestamp"]
    assert a.headers["X-Signature"] != b.headers["X-Signature"]
    # Erreur réseau puis succès
    reseau.appels.clear()
    reseau.reponses = [httpx.ConnectError("coupure")]
    r = _run(tw.envoyer_liluvine("+22670000003", "Bonjour"))
    assert r["ok"] and len(reseau.appels) == 2
    assert json.loads(reseau.appels[0].content)["id"] == json.loads(reseau.appels[1].content)["id"]


def test_deux_echecs_5xx_un_seul_nouvel_essai(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    reseau.reponses = [httpx.Response(502), httpx.Response(502), httpx.Response(200, json={"ok": True})]
    r = _run(tw.envoyer_liluvine("+22670000004", "Bonjour"))
    assert not r["ok"] and r["canal"] == "liluvine" and len(reseau.appels) == 2 and "502" in r["erreur"]


def test_pas_de_nouvel_essai_sur_4xx(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    reseau.reponses = [httpx.Response(429, json={"detail": "quota dépassé"})]
    r = _run(tw.envoyer_liluvine("+22670000005", "Bonjour"))
    assert not r["ok"] and len(reseau.appels) == 1 and "429" in r["erreur"]
    assert CLE not in repr(r)


# ---------------------------------------------------------------------------
# 5. Désactivation propre sans variables
# ---------------------------------------------------------------------------
def test_desactivation_sans_variables(base, reseau, monkeypatch):
    import albarka_transmission_wa as tw
    from albarka_notifications import send_whatsapp
    monkeypatch.delenv("LILUVINE_WA_URL", raising=False)
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)
    _run(_regler_waba(base, False))
    assert not tw.liluvine_configure()
    r = _run(tw.envoyer_whatsapp("+22670000006", "Bonjour"))
    assert r["ok"] is False and r["canal"] is None and "non configurée" in r["erreur"]
    b = _run(send_whatsapp(to_phone="+22670000006", message="Bonjour"))
    assert b["kind"] == "not_configured"  # comportement d'origine
    assert reseau.appels == []
    # URL présente mais clé absente : toujours désactivée
    monkeypatch.setenv("LILUVINE_WA_URL", URL_SAWALI)
    assert not tw.liluvine_configure()


# ---------------------------------------------------------------------------
# 6. Routes super-admin : état sans secret, test
# ---------------------------------------------------------------------------
def test_routes_super_admin(base, liluvine, reseau):
    import albarka_transmission_wa as tw
    from fastapi import HTTPException
    _run(_regler_waba(base, False))
    admin = {"email": "admin@sawalismartsystems.com", "roles": []}
    e = _run(tw.etat_transmission(user=admin))
    assert e == {"waba_configure": False, "liluvine_configure": True, "emetteur": "albarka"}
    assert CLE not in repr(e) and URL_SAWALI not in repr(e)
    r = _run(tw.test_transmission(tw.DemandeTest(numero="+226 70 00 00 07"), user=admin))
    assert r["ok"] and r["canal"] == "liluvine"
    assert json.loads(reseau.appels[-1].content)["message"] == "Test de transmission WhatsApp depuis ALBARKA"
    with pytest.raises(HTTPException):
        _run(tw.test_transmission(tw.DemandeTest(numero="70000007"), user=admin))
    # Routes enregistrées et protégées par require_super_admin
    import albarka_sauvegarde as sv
    chemins = {r.path: r for r in tw.router.routes}
    assert "/_admin/transmission-wa/test" in chemins and "/_admin/transmission-wa/etat" in chemins
    for route in chemins.values():
        assert any(d.call is sv.require_super_admin for d in route.dependant.dependencies)
