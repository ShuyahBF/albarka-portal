"""Lot 24 (SAWALI lot 93) — pictogrammes de la fenêtre d'assistance : photo, document, note vocale, média.

Couvre : relais signé de la photo / du document, transcription de la note vocale, média renvoyé au navigateur,
refus de SAWALI (type, taille) transmis tels quels. Aucun appel réseau réel (httpx simulé), aucune base réelle.
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


import base64  # noqa: E402

JPEG93 = b"\xff\xd8\xff\xe0" + b"\x00" * 32 + b"\xff\xd9"


def appli93(monkeypatch, repondre):
    """Application avec le routeur du support, un utilisateur connecté simulé et SAWALI simulé."""
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)
    monkeypatch.setenv("SAWALI_API_URL", "https://sawali.test")
    monkeypatch.setattr(ss, "_transport", httpx.MockTransport(repondre))
    app = FastAPI()
    app.include_router(ss.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: PERSONNEL
    return TestClient(app)


def test_fichier_transcription_media(monkeypatch):
    """Photo relayée signée, note vocale transcrite, média renvoyé au navigateur avec son type."""
    vus = []

    def repondre(r: httpx.Request):
        corps = json.loads(r.content.decode())
        vus.append((r.url.path, corps))
        if r.url.path.endswith("/fichier"):
            return httpx.Response(200, json={"ok": True, "message": {"id": "m1", "media": {"genre": "image"}}})
        if r.url.path.endswith("/transcrire"):
            return httpx.Response(200, json={"ok": True, "texte": "Bonjour"})
        return httpx.Response(200, json={"type": "image/jpeg", "nom": "a.jpg", "contenu": base64.b64encode(JPEG93).decode()})

    c = appli93(monkeypatch, repondre)
    data = "data:image/jpeg;base64," + base64.b64encode(JPEG93).decode()
    r = c.post("/api/support-sawali/fichier", json={"fichier": data, "nom": "a.jpg", "legende": " Voici "})
    assert r.status_code == 200 and r.json()["message"]["media"]["genre"] == "image"
    assert vus[-1][0] == "/api/support-plateforme/fichier" and vus[-1][1]["legende"] == "Voici" and vus[-1][1]["utilisateur"]["id"]
    assert c.post("/api/support-sawali/transcrire", json={"audio": "data:audio/webm;base64,QUJDREVGR0g="}).json()["texte"] == "Bonjour"
    m = c.get("/api/support-sawali/media/m1")
    assert m.status_code == 200 and m.content == JPEG93 and m.headers["content-type"] == "image/jpeg"
    assert vus[-1][0] == "/api/support-plateforme/media" and vus[-1][1]["message_id"] == "m1"


def test_refus_lisible(monkeypatch):
    """Type refusé par SAWALI : le message de SAWALI est transmis tel quel (pas un « refusé » générique)."""
    c = appli93(monkeypatch, lambda r: httpx.Response(415, json={"detail": "Type de fichier non accepté"}))
    r = c.post("/api/support-sawali/fichier", json={"fichier": "data:application/x-msdownload;base64,TVo=AAAA", "nom": "x.exe"})
    assert r.status_code == 415 and r.json()["detail"] == "Type de fichier non accepté"
