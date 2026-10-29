"""Lot 82 — réponses aux formulaires reçus de SAWALI, renvoyées à SAWALI (autonome : MongoDB simulé, aucun réseau)."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock_motor  # noqa: E402

import albarka_retour_reponses as retour  # noqa: E402


def _config(monkeypatch):
    monkeypatch.setenv("LILUVINE_WA_URL", "https://api.sawali.test/api/webhook/liluvine-send")
    monkeypatch.setenv("LILUVINE_WA_HMAC", "cle-test")


async def _base():
    base = mongomock_motor.AsyncMongoMockClient()["t"]
    await base["forms"].insert_one({"id": "f1", "source": {"plateforme": "SAWALI", "type": "formulaire", "id_sawali": "SAW-F1"}})
    await base["forms"].insert_one({"id": "f2"})                                                       # formulaire créé dans ALBARKA : jamais renvoyé
    for i, (fid, nom) in enumerate([("f1", "Awa"), ("f1", "Boubacar"), ("f2", "Interne")]):
        await base["forms_submissions"].insert_one({"id": f"s{i}", "form_id": fid, "respondent_name": nom, "data": {"a1": nom},
                                                     "created_at": f"2026-10-29T10:0{i}:00+00:00"})
    return base


def test_adresse_de_sawali_deduite_de_la_transmission_universelle(monkeypatch):
    _config(monkeypatch)
    assert retour.url_sawali() == "https://api.sawali.test/api/webhook/plateforme-reponse-formulaire"
    monkeypatch.delenv("LILUVINE_WA_URL")
    assert retour.url_sawali() is None


def test_seules_les_reponses_des_formulaires_de_sawali_sont_renvoyees_une_fois(monkeypatch):
    _config(monkeypatch)
    envoyes = []

    async def faux_post(cfg, url, corps):
        envoyes.append(corps)
        return {"ok": True, "definitif": True, "erreur": None}
    monkeypatch.setattr(retour, "_poster", faux_post)

    async def scenario():
        base = await _base()
        bilan = await retour.envoyer_reponses_en_attente(base)
        assert bilan["envoyees"] == 2 and len(envoyes) == 2
        assert envoyes[0]["id_sawali"] == "SAW-F1" and envoyes[0]["type"] == "formulaire" and envoyes[0]["repondant"]["nom"] == "Awa"
        assert envoyes[0]["reponse_id"] == "s0" and envoyes[0]["data"] == {"a1": "Awa"}
        assert (await retour.envoyer_reponses_en_attente(base))["envoyees"] == 0                  # déjà transmises : pas de renvoi
        assert (await base["forms_submissions"].find_one({"id": "s2"})).get("sawali_envoye_le") is None   # la réponse du formulaire interne reste intacte
    asyncio.run(scenario())


def test_panne_reseau_reessaie_et_refus_definitif_nest_pas_rejoue(monkeypatch):
    _config(monkeypatch)
    reponses = iter([{"ok": False, "definitif": False, "erreur": "SAWALI injoignable"},
                     {"ok": False, "definitif": True, "erreur": "refusé par SAWALI (HTTP 401)"},
                     {"ok": True, "definitif": True, "erreur": None}])

    async def faux_post(cfg, url, corps):
        return next(reponses)
    monkeypatch.setattr(retour, "_poster", faux_post)

    async def scenario():
        base = await _base()
        assert (await retour.envoyer_reponses_en_attente(base)) == {"envoyees": 0, "en_attente": 1, "refusees": 0}   # panne : tout reste en attente
        bilan = await retour.envoyer_reponses_en_attente(base)                                                       # s0 refusée, s1 envoyée
        assert bilan == {"envoyees": 1, "en_attente": 0, "refusees": 1}
        assert "401" in (await base["forms_submissions"].find_one({"id": "s0"}))["sawali_erreur"]
        assert (await retour.envoyer_reponses_en_attente(base))["envoyees"] == 0                                     # la refusée n'est pas rejouée
    asyncio.run(scenario())


def test_non_configure_rien_nest_envoye(monkeypatch):
    monkeypatch.delenv("LILUVINE_WA_URL", raising=False)
    monkeypatch.delenv("LILUVINE_WA_HMAC", raising=False)

    async def scenario():
        assert (await retour.envoyer_reponses_en_attente(await _base()))["envoyees"] == 0
    asyncio.run(scenario())
