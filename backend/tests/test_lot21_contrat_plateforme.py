"""Lot 21 — Bandeau du contrat SAWALI pour le DG (orange autour de l'échéance, rouge au-delà).

Couvre : adresse déduite de LILUVINE_WA_URL, textes du bandeau, requête signée envoyée à SAWALI, repli sur la
dernière réponse gardée en base, route visible pour le DG seulement. MongoDB et httpx simulés.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_transmission_wa_v3_lot13_9 import CLE, _run, base, liluvine, reseau  # noqa: E402,F401

import httpx  # noqa: E402
import albarka_contrat_plateforme as cp  # noqa: E402
from albarka_transmission_wa import signer  # noqa: E402

ETAT_ROUGE = {"numero": "CTR-ALB-2026-01", "fin": "2027-10-14", "devise": "XOF", "du": 300000,
              "etat": {"niveau": "expire", "couleur": "rouge", "jours_restants": -3}}   # lot 22 : rouge de J+1 à J+5


def test_url_deduite():
    assert cp.url_contrat("https://api.sawali.test/api/webhook/liluvine-send") == "https://api.sawali.test/api/webhook/plateforme-contrat"


def test_textes_du_bandeau():
    orange = cp.bandeau({"numero": "N1", "fin": "2027-10-14", "du": 0, "etat": {"niveau": "bientot", "couleur": "orange", "jours_restants": 5}})
    assert orange["visible"] and orange["couleur"] == "orange" and "14/10/2027" in orange["message"] and "dans 5 jours" in orange["message"]
    rouge = cp.bandeau(ETAT_ROUGE)
    assert rouge["couleur"] == "rouge" and "suspendus" in rouge["message"] and "300 000 XOF" in rouge["message"]
    assert cp.bandeau({"etat": {"niveau": "ok", "couleur": None}})["visible"] is False
    assert cp.bandeau(None)["visible"] is False


def test_requete_signee_et_repli(base, liluvine, reseau, monkeypatch):
    import db as db_module
    monkeypatch.setattr(cp, "db", base)
    cp._cache.update(le=0.0, etat=None)
    reseau.reponses.append(httpx.Response(200, json=ETAT_ROUGE))
    etat = _run(cp.lire_etat(force=True))
    assert etat["numero"] == "CTR-ALB-2026-01"
    requete = reseau.appels[-1]
    assert str(requete.url).endswith("/api/webhook/plateforme-contrat")
    ts = requete.headers["X-Timestamp"]
    assert requete.headers["X-Signature"] == signer(CLE, ts, requete.content.decode())
    # SAWALI injoignable ensuite : la dernière réponse gardée en base est réutilisée
    reseau.reponses.append(httpx.Response(503, json={}))
    assert _run(cp.lire_etat(force=True))["numero"] == "CTR-ALB-2026-01"


def test_route_reservee_au_dg(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from albarka_auth import get_current_user

    async def etat(force=False):
        return ETAT_ROUGE
    monkeypatch.setattr(cp, "lire_etat", etat)
    app = FastAPI()
    app.include_router(cp.router, prefix="/api")
    for roles, visible in ((["dg"], True), (["secretariat"], False), (["client"], False)):
        app.dependency_overrides[get_current_user] = lambda roles=roles: {"id": "u", "roles": roles}
        assert TestClient(app).get("/api/contrat-plateforme").json()["visible"] is visible


def test_numero_de_lot():
    import lot
    assert int(lot.LOT.split(".")[0]) >= 21
