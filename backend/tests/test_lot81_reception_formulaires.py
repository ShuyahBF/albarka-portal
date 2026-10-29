"""Lot 81 — réception des formulaires et sondages transmis par SAWALI (autonome : MongoDB simulé, aucun réseau)."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock_motor  # noqa: E402

import albarka_reception_formulaires as rec  # noqa: E402
import albarka_transmission_wa as wa  # noqa: E402

FORMULAIRE = {"type": "formulaire", "id_sawali": "F1", "titre": "Fiche RH",
              "document": {"title": "Fiche RH", "description": "Suivi mensuel", "client_id": "interne",
                           "pages": [{"id": "p1", "title": "Liste", "fields": [
                               {"id": "a1", "type": "text", "label": "Nom"}, {"id": "a2", "type": "location", "label": "Lieu"}]}]}}
SONDAGE = {"type": "sondage", "id_sawali": "S1", "titre": "Évaluation",
           "document": {"title": "Évaluation", "thank_you": "Merci !", "questions": [
               {"id": "q1", "type": "rating", "label": "Rapidité", "required": True},
               {"id": "q2", "type": "nps", "label": "Recommandation"}, {"id": "q3", "type": "text", "label": "Avis"}]}}


def test_un_formulaire_arrive_dans_mes_formulaires_sans_doublon():
    async def scenario():
        base = mongomock_motor.AsyncMongoMockClient()["t"]
        r1 = await rec.creer_formulaire(base, FORMULAIRE)
        assert r1["ok"] and r1["number"] == "FORM-ALBARKA-0001" and not r1["deja"]
        f = await base["forms"].find_one({"number": "FORM-ALBARKA-0001"})
        assert f["title"] == "Fiche RH" and f["source"]["id_sawali"] == "F1" and f["settings"]["accepting_responses"] is False
        assert [c["type"] for c in f["pages"][0]["fields"]] == ["text", "text"]       # « location » → texte libre
        r2 = await rec.creer_formulaire(base, FORMULAIRE)                              # même id : pas de doublon
        assert r2["deja"] and await base["forms"].count_documents({}) == 1
    asyncio.run(scenario())


def test_un_sondage_devient_un_formulaire_et_un_titre_pris_est_suffixe():
    async def scenario():
        base = mongomock_motor.AsyncMongoMockClient()["t"]
        await rec.creer_formulaire(base, {**FORMULAIRE, "titre": "Évaluation", "id_sawali": "F9"})
        r = await rec.creer_formulaire(base, SONDAGE)
        f = await base["forms"].find_one({"number": r["number"]})
        assert f["title"] == "Évaluation (SAWALI)"
        assert [c["type"] for c in f["pages"][0]["fields"]] == ["rating", "scale", "text"]
    asyncio.run(scenario())


def test_signature_hmac_acceptee_et_refusee(monkeypatch):
    monkeypatch.setenv("LILUVINE_WA_URL", "https://sawali.test/api/webhook/liluvine-send")
    monkeypatch.setenv("LILUVINE_WA_HMAC", "cle-test")
    brut = json.dumps(FORMULAIRE).encode()
    ts = str(int(time.time()))
    bonne = hmac.new(b"cle-test", f"{ts}.{brut.decode()}".encode(), hashlib.sha256).hexdigest()
    assert wa.verifier_signature_retour(ts, bonne, brut) is None
    assert wa.verifier_signature_retour(ts, "0" * 64, brut) == "Signature invalide"
