"""Lot 22 — bandeau limité à ± 5 jours de l'échéance et services suspendus automatiquement (contrat SAWALI échu).

Couvre : fenêtre du bandeau, annonce des services et de la date, correspondance chemin → service, réponse 423 du
middleware, chemins toujours ouverts, envois WhatsApp / e-mail refusés sauf codes de connexion, analyse IA refusée.
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")   # base jamais jointe : l'état est mis en cache
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import albarka_contrat_plateforme as cp  # noqa: E402
import albarka_suspension as su  # noqa: E402

ECHU = {"numero": "CTR-ALB-2026-01", "fin": "2027-10-15", "etat": {"niveau": "echu", "couleur": None, "jours_restants": -9},
        "services_a_suspendre": ["wa", "cr"], "services_suspendus": ["wa", "cr", "inconnu"], "suspension_le": "2027-10-21"}


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _etat_en_cache(etat):
    """Place un état « frais » dans le cache (aucun appel à SAWALI)."""
    cp._cache.update(le=time.time(), etat=etat)


def test_bandeau_seulement_autour_de_l_echeance():
    # Lot 22.2 : contrat échu AVEC services suspendus → barre rouge permanente qui les nomme
    suspendu = cp.bandeau(ECHU)
    assert suspendu["visible"] and suspendu["couleur"] == "rouge" and "Services suspendus depuis le 21/10/2027" in suspendu["message"]
    assert cp.bandeau({**ECHU, "services_suspendus": []})["visible"] is False   # échu sans service coché : rien
    assert cp.bandeau({"etat": {"niveau": "ok", "couleur": None}})["visible"] is False
    rouge = cp.bandeau({**ECHU, "etat": {"niveau": "expire", "couleur": "rouge", "jours_restants": -2},
                        "services_catalogue": [{"code": "cr", "libelle": "Comptes rendus"}]})
    assert rouge["couleur"] == "rouge"
    assert "suspendus le 21/10/2027" in rouge["message"] and "Comptes rendus" in rouge["message"]
    assert "WhatsApp (envois)" in rouge["message"]                    # libellé local à défaut du catalogue
    orange = cp.bandeau({"fin": "2027-10-15", "etat": {"niveau": "bientot", "couleur": "orange", "jours_restants": 0}})
    assert orange["visible"] and "aujourd'hui" in orange["message"]


def test_chemins_et_services():
    assert su.suspendus_dans(ECHU) == ["wa", "cr"]
    assert su.service_du_chemin("/api/reports/abc", ["cr"]) == "cr"
    assert su.service_du_chemin("/api/report-templates", ["cr"]) == "cr"
    assert su.service_du_chemin("/api/reportsX", ["cr"]) is None
    assert su.service_du_chemin("/api/whatsapp/webhook", ["conversations_wa"]) is None   # messages reçus : jamais bloqués
    assert su.service_du_chemin("/api/whatsapp/conversations", ["conversations_wa"]) == "conversations_wa"
    assert su.service_du_chemin("/api/documents/ocr-stats", ["ia"]) == "ia"
    assert su.service_du_chemin("/api/documents", ["ia"]) is None
    assert su.service_du_chemin("/api/auth/login", list(su.SERVICES)) is None
    assert su.service_du_chemin("/api/reports/x", []) is None


def test_middleware_423(monkeypatch):
    from fastapi.testclient import TestClient
    import server
    _etat_en_cache(ECHU)
    c = TestClient(server.app)
    r = c.get("/api/reports/rien")
    assert r.status_code == 423 and r.json()["service_suspendu"] == "cr" and "renouvellement" in r.json()["detail"]
    assert c.get("/api/auth/me").status_code != 423          # connexion : jamais bloquée
    _etat_en_cache({**ECHU, "services_suspendus": []})   # échéance repoussée : plus rien de bloqué
    assert c.get("/api/reports/rien").status_code != 423


def test_envois_refuses_sauf_connexion():
    from albarka_envoi_test import emails_effectifs, numero_effectif
    _etat_en_cache({**ECHU, "services_suspendus": ["wa", "email"]})
    su.noter_chemin("/api/billing/invoices/1/send")
    numero, refus = _run(numero_effectif("+22670000000"))
    assert numero is None and "WhatsApp" in refus
    assert _run(emails_effectifs(["client@exemple.bf"])) == []
    su.noter_chemin("/api/auth/whatsapp/code")           # code de connexion : toujours envoyé
    assert _run(numero_effectif("+22670000000")) == ("+22670000000", None)
    su.noter_chemin("")
    _etat_en_cache({**ECHU, "services_suspendus": []})
    assert _run(numero_effectif("+22670000000")) == ("+22670000000", None)


def test_analyse_ia_refusee():
    import albarka_ai
    _etat_en_cache({**ECHU, "services_suspendus": ["ia"]})
    r = _run(albarka_ai.analyze_document(b"x", "application/pdf", "a.pdf"))
    assert "suspendu" in r["error"] and r["cost_xof"] == 0.0
    _etat_en_cache(None)


def test_numero_de_lot():
    import lot
    assert int(lot.LOT.split(".")[0]) >= 22
