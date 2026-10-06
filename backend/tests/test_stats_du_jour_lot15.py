"""Lot 15 — statistiques du jour demandées par SAWALI.

Couvre : signature valide -> JSON (indicateurs, faits marquants,
utilisateurs_connectes), signature invalide -> 401, clé absente -> 503,
période invalide -> 422, retours existants (statut) toujours traités.
Tests autonomes : MongoDB simulé (mongomock-motor).
"""
from __future__ import annotations

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

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

CLE = "cle-de-test-stats-lot15"
URL_RETOUR = "/api/webhooks/liluvine-retour"


# ---------------------------------------------------------------------------
# Préparation : base simulée, variables, application minimale
# ---------------------------------------------------------------------------
@pytest.fixture()
def base(monkeypatch):
    """Base MongoDB simulée branchée à la place de la vraie."""
    import db as db_module
    client = mongomock_motor.AsyncMongoMockClient()
    base_test = client["albarka_lot15"]
    monkeypatch.setattr(db_module, "db", base_test)
    return base_test


@pytest.fixture()
def liluvine(monkeypatch):
    """Clé partagée avec SAWALI renseignée (même variable que les retours)."""
    monkeypatch.setenv("LILUVINE_WA_URL", "https://sawali.test/api/webhook/liluvine-send")
    monkeypatch.setenv("LILUVINE_WA_HMAC", CLE)


def _client_api():
    """Application FastAPI minimale avec le routeur des retours sous /api."""
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient
    import albarka_transmission_wa as tw
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(tw.retour_router)
    app.include_router(api)
    return TestClient(app)


def _signe(corps: dict, ts: int | None = None, cle: str = CLE):
    """Corps brut + en-têtes signés comme SAWALI."""
    brut = json.dumps(corps, ensure_ascii=False)
    ts = int(time.time()) if ts is None else ts
    sig = hmac.new(cle.encode(), f"{ts}.{brut}".encode(), hashlib.sha256).hexdigest()
    return brut.encode("utf-8"), {"Content-Type": "application/json", "X-Emetteur": "sawali",
                                  "X-Timestamp": str(ts), "X-Signature": sig}


def _periode():
    """Période du jour : [aujourd'hui 00:00 UTC, demain 00:00 UTC)."""
    debut = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return debut, debut + timedelta(days=1)


def _peupler(base_test):
    """Quelques données dans la période et une hors période."""
    debut, _fin = _periode()
    dans = (debut + timedelta(hours=1)).isoformat()
    avant = (debut - timedelta(days=2)).isoformat()
    maintenant = datetime.now(timezone.utc)
    import asyncio

    async def remplir():
        await base_test.users.insert_many([
            {"id": "c1", "roles": ["client"], "created_at": dans, "last_login": dans},
            {"id": "c2", "roles": ["client"], "created_at": avant, "last_login": dans},
            {"id": "t1", "roles": ["client"], "created_at": dans, "is_test_account": True},
        ])
        await base_test.invoices.insert_many([
            {"id": "f1", "total": 100000, "created_at": dans},
            {"id": "f0", "total": 999, "created_at": avant},
        ])
        await base_test.payments.insert_many([
            {"id": "p1", "amount": 50000, "created_at": dans},
            {"id": "p2", "amount": 25000.4, "created_at": dans},
        ])
        await base_test.client_contracts.insert_one({"id": "k1", "created_at": dans})
        await base_test.documents.insert_one({"id": "d1", "created_at": dans})
        await base_test.client_documents.insert_many([
            {"id": "cd1", "created_at": dans, "is_deleted": False},
            {"id": "cd2", "created_at": dans, "is_deleted": True},
        ])
        await base_test.wa_messages.insert_many([
            {"id": "w1", "direction": "inbound", "created_at": dans},
            {"id": "w2", "direction": "outbound", "created_at": dans},
        ])
        # Présence : deux comptes actifs il y a moins de 5 min, un il y a 20 min.
        await base_test.presence.insert_many([
            {"_id": "c1", "last_seen": (maintenant - timedelta(seconds=30)).isoformat()},
            {"_id": "s1", "last_seen": (maintenant - timedelta(minutes=4)).isoformat()},
            {"_id": "c2", "last_seen": (maintenant - timedelta(minutes=20)).isoformat()},
        ])

    asyncio.run(remplir())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_stats_signature_valide(base, liluvine):
    """Signature valide : 200 avec indicateurs, faits marquants et connectés."""
    _peupler(base)
    debut, fin = _periode()
    brut, entetes = _signe({"type": "stats_du_jour", "debut": debut.isoformat().replace("+00:00", "Z"),
                            "fin": fin.isoformat().replace("+00:00", "Z")})
    rep = _client_api().post(URL_RETOUR, content=brut, headers=entetes)
    assert rep.status_code == 200, rep.text
    donnees = rep.json()
    valeurs = {i["cle"]: i["valeur"] for i in donnees["indicateurs"]}
    assert 4 <= len(donnees["indicateurs"]) <= 10
    assert all(i["libelle"] for i in donnees["indicateurs"])
    assert valeurs["connexions"] == 2
    assert valeurs["nouveaux_clients"] == 1          # compte de test exclu
    assert valeurs["factures_emises"] == 1
    assert valeurs["montant_facture_fcfa"] == 100000
    assert valeurs["paiements"] == 2
    assert valeurs["montant_encaisse_fcfa"] == 75000
    assert valeurs["contrats_crees"] == 1
    assert valeurs["pieces_deposees"] == 1
    assert valeurs["documents_publies"] == 1          # document supprimé exclu
    assert valeurs["messages_whatsapp_recus"] == 1
    assert donnees["utilisateurs_connectes"] == 2
    assert 1 <= len(donnees["faits_marquants"]) <= 5


def test_stats_base_vide(base, liluvine):
    """Base vide : zéros, connectés à 0, un fait « aucune activité »."""
    debut, fin = _periode()
    brut, entetes = _signe({"type": "stats_du_jour", "debut": debut.isoformat(), "fin": fin.isoformat()})
    rep = _client_api().post(URL_RETOUR, content=brut, headers=entetes)
    assert rep.status_code == 200
    donnees = rep.json()
    assert all(i["valeur"] == 0 for i in donnees["indicateurs"])
    assert donnees["utilisateurs_connectes"] == 0
    assert donnees["faits_marquants"] == ["Aucune activité notable sur la période"]


def test_stats_signature_invalide_401(base, liluvine):
    """Mauvaise clé ou horodatage hors fenêtre : 401."""
    debut, fin = _periode()
    corps = {"type": "stats_du_jour", "debut": debut.isoformat(), "fin": fin.isoformat()}
    client = _client_api()
    brut, entetes = _signe(corps, cle="mauvaise-cle")
    assert client.post(URL_RETOUR, content=brut, headers=entetes).status_code == 401
    brut, entetes = _signe(corps, ts=int(time.time()) - 400)
    assert client.post(URL_RETOUR, content=brut, headers=entetes).status_code == 401


def test_stats_cle_absente_503(base, monkeypatch):
    """Clé non configurée : 503."""
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)
    monkeypatch.setenv("LILUVINE_WA_URL", "https://sawali.test/x")
    debut, fin = _periode()
    brut, entetes = _signe({"type": "stats_du_jour", "debut": debut.isoformat(), "fin": fin.isoformat()})
    assert _client_api().post(URL_RETOUR, content=brut, headers=entetes).status_code == 503


@pytest.mark.parametrize("debut,fin", [
    (None, "2026-10-06T00:00:00Z"),                       # début absent
    ("pas-une-date", "2026-10-06T00:00:00Z"),             # début illisible
    ("2026-10-06T00:00:00Z", "2026-10-05T00:00:00Z"),     # période inversée
    ("2026-10-06T00:00:00Z", "2026-10-06T00:00:00Z"),     # période vide
    ("2026-08-01T00:00:00Z", "2026-10-01T00:00:00Z"),     # plus de 31 jours
])
def test_stats_periode_invalide_422(base, liluvine, debut, fin):
    """Période absente, invalide, inversée ou trop longue : 422."""
    corps = {"type": "stats_du_jour", "fin": fin}
    if debut is not None:
        corps["debut"] = debut
    brut, entetes = _signe(corps)
    assert _client_api().post(URL_RETOUR, content=brut, headers=entetes).status_code == 422


def test_retours_existants_inchanges(base, liluvine):
    """Un retour « statut » est toujours traité comme avant ; type inconnu -> 422."""
    import asyncio
    asyncio.run(base.liluvine_envois.insert_one({"id": "env-1", "statut": "accepte"}))
    client = _client_api()
    brut, entetes = _signe({"type": "statut", "id": "env-1", "statut": "delivered",
                            "date": datetime.now(timezone.utc).isoformat()})
    rep = client.post(URL_RETOUR, content=brut, headers=entetes)
    assert rep.status_code == 200 and rep.json() == {"ok": True, "doublon": False}
    doc = asyncio.run(base.liluvine_envois.find_one({"id": "env-1"}))
    assert doc["statut"] == "delivered"
    brut, entetes = _signe({"type": "inconnu"})
    assert client.post(URL_RETOUR, content=brut, headers=entetes).status_code == 422
