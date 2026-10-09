"""Lot 23 — Pictogramme « Assistance » : relais du support SAWALI.

Couvre : /etat actif seulement si la clé est saisie, requête signée (HMAC) envoyée à l'adresse déduite de
LILUVINE_WA_URL avec l'identité de l'utilisateur, erreurs de SAWALI (403, indisponible, injoignable) traduites en
messages lisibles, sans jamais exposer la clé. Aucun appel réseau réel (httpx simulé), aucune base réelle.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_support_sawali as ss  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

CLE = "cle-support-test"
PERSONNEL = {"id": "u-1", "full_name": "Awa Traoré", "email": "awa@albarka.test", "roles": ["comptable"],
             "phone": "+22670000000"}
CLIENT = {"id": "c-9", "full_name": "Issa Ouédraogo", "email": "issa@client.test", "roles": ["client"],
          "company": "SOGEB SARL", "whatsapp_number": "+22671111111"}


def _run(coro):
    return asyncio.run(coro)


def _appli(utilisateur):
    """Petite application avec le seul routeur du support et un utilisateur connecté simulé."""
    app = FastAPI()
    app.include_router(ss.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: utilisateur
    return TestClient(app)


@pytest.fixture()
def cle_saisie(monkeypatch):
    """Variables de la transmission WhatsApp universelle renseignées (même clé que pour WhatsApp)."""
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    monkeypatch.setenv("LILUVINE_WA_EMETTEUR", "albarka")
    monkeypatch.setenv("LILUVINE_WA_URL", "https://api.sawali.test/api/webhook/liluvine-send")
    monkeypatch.delenv("SAWALI_API_URL", raising=False)


def test_etat_actif_seulement_si_cle(monkeypatch):
    """Sans clé : pictogramme caché ; avec la clé : affiché (pour tout utilisateur connecté, client compris)."""
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)
    assert _appli(PERSONNEL).get("/api/support-sawali/etat").json() == {"actif": False}
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    reponse = _appli(CLIENT).get("/api/support-sawali/etat")
    assert reponse.status_code == 200 and reponse.json() == {"actif": True}
    assert CLE not in reponse.text


def test_etat_exige_une_connexion():
    """Sans jeton de connexion : refus (le pictogramme n'existe que dans le portail connecté)."""
    from server import app  # noqa: WPS433 — application complète : le routeur y est bien branché
    assert any(getattr(r, "path", "") == "/api/support-sawali/etat" for r in app.routes)
    assert TestClient(app).get("/api/support-sawali/etat").status_code in (401, 403)


def test_relais_signe(cle_saisie, monkeypatch):
    """Le message part signé avec la clé d'émetteur, vers l'adresse déduite de LILUVINE_WA_URL, avec l'identité."""
    vus = {}

    def repondre(requete: httpx.Request):
        vus["url"] = str(requete.url)
        vus["entetes"] = requete.headers
        vus["corps"] = requete.content.decode()
        return httpx.Response(200, json={"ok": True, "requete": {"numero": "SUP-0001", "statut": "attente"}})

    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(repondre))
    r = _appli(CLIENT).post("/api/support-sawali/messages", json={"texte": "  Bonjour, besoin d'aide  "})
    assert r.status_code == 200 and r.json()["requete"]["numero"] == "SUP-0001"
    assert vus["url"] == "https://api.sawali.test/api/support-plateforme/messages"
    h = vus["entetes"]
    attendu = hmac.new(CLE.encode(), f"{h['X-Timestamp']}.{vus['corps']}".encode(), hashlib.sha256).hexdigest()
    assert h["X-Emetteur"] == "albarka" and h["X-Signature"] == attendu
    corps = json.loads(vus["corps"])
    assert corps["texte"] == "Bonjour, besoin d'aide"
    assert corps["utilisateur"]["id"] == "c-9" and corps["utilisateur"]["contexte"] == "Client ALBARKA — SOGEB SARL"
    assert corps["utilisateur"]["telephone"] == "+22671111111"


def test_fil_et_adresse_directe(cle_saisie, monkeypatch):
    """Lecture du fil : depuis / marquer_lu transmis ; SAWALI_API_URL prioritaire ; émetteur par défaut « albarka »."""
    monkeypatch.setenv("SAWALI_API_URL", "https://autre.sawali.test/")
    monkeypatch.delenv("LILUVINE_WA_EMETTEUR", raising=False)
    vus = {}

    def repondre(requete: httpx.Request):
        vus["url"] = str(requete.url)
        vus["emetteur"] = requete.headers["X-Emetteur"]
        vus["corps"] = json.loads(requete.content)
        return httpx.Response(200, json={"messages": [], "non_lus": 2})

    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(repondre))
    r = _appli(PERSONNEL).post("/api/support-sawali/fil", json={"depuis": "2026-10-09T10:00:00Z", "marquer_lu": False})
    assert r.status_code == 200 and r.json()["non_lus"] == 2
    assert vus["url"] == "https://autre.sawali.test/api/support-plateforme/fil" and vus["emetteur"] == "albarka"
    assert vus["corps"]["depuis"] == "2026-10-09T10:00:00Z" and vus["corps"]["marquer_lu"] is False
    assert vus["corps"]["utilisateur"]["contexte"] == "Cabinet ALBARKA"
    assert vus["corps"]["utilisateur"]["role"] == "comptable"


def test_erreurs_lisibles(monkeypatch):
    """Sans clé : 503 ; 403 de SAWALI : « pas encore activé » ; 500 : indisponible ; réseau coupé : injoignable.
    Jamais la clé dans le message."""
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)
    with pytest.raises(HTTPException) as e:
        _run(ss.appeler_sawali("/x", {}))
    assert e.value.status_code == 503 and "non configuré" in e.value.detail

    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(lambda r: httpx.Response(403, json={"detail": "x"})))
    with pytest.raises(HTTPException) as e:
        _run(ss.appeler_sawali("/x", {}))
    assert e.value.status_code == 503 and "pas encore activé" in e.value.detail and CLE not in e.value.detail

    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(lambda r: httpx.Response(500, text="boom")))
    with pytest.raises(HTTPException) as e:
        _run(ss.appeler_sawali("/x", {}))
    assert e.value.status_code == 503 and "indisponible" in e.value.detail

    def coupe(requete):
        raise httpx.ConnectError("hors ligne", request=requete)
    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(coupe))
    with pytest.raises(HTTPException) as e:
        _run(ss.appeler_sawali("/x", {}))
    assert e.value.status_code == 503 and "injoignable" in e.value.detail

    # Par la route : le navigateur reçoit le message lisible dans « detail »
    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(lambda r: httpx.Response(403, json={})))
    r = _appli(PERSONNEL).post("/api/support-sawali/messages", json={"texte": "Bonjour"})
    assert r.status_code == 503 and "pas encore activé" in r.json()["detail"]
