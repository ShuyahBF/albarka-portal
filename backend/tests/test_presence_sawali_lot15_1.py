"""Lot 15.1 — présence du serveur ALBARKA auprès de SAWALI (règle 4).

Couvre la fonction pure du corps du signal, l'en-tête facultatif X-Cle-Loois,
le nom de machine et la désactivation par PRESENCE_SAWALI=0.
Tests autonomes : aucun appel réseau, aucune base.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import albarka_presence_sawali as ps  # noqa: E402


def test_corps_signal_complet():
    """Le corps reprend la version 1.N et la date de déploiement de /api/version."""
    infos = {"version": "1.42", "deployed_at": "2026-10-06T10:00:00+00:00", "lot": "15.1"}
    corps = ps.corps_signal(infos, "albarka-backend", "2026-10-06T10:01:00+00:00")
    assert corps["application"] == "ALBARKA"
    assert corps["version"] == "1.42"
    assert corps["deploye_le"] == "2026-10-06T10:00:00+00:00"
    assert corps["machine"] == "albarka-backend"
    assert corps["utilisateur"] == "serveur"
    assert corps["site"] == "albarka-bf.com"
    assert corps["systeme"].startswith("Render · Python ")
    assert corps["demarre_le"] == "2026-10-06T10:01:00+00:00"
    # Aucune autre donnée (ni lot, ni secret) dans le signal
    assert set(corps) == {"application", "version", "deploye_le", "machine",
                          "utilisateur", "site", "systeme", "demarre_le"}


def test_corps_signal_infos_absentes():
    """Infos de version indisponibles : champs obligatoires toujours présents."""
    corps = ps.corps_signal({}, "hote", "x")
    assert corps["application"] == "ALBARKA" and corps["version"] and corps["machine"] == "hote"


def test_entete_cle_loois_facultatif(monkeypatch):
    """X-Cle-Loois n'est envoyé que si LOOIS_SUPPORT_CLE existe."""
    monkeypatch.delenv("LOOIS_SUPPORT_CLE", raising=False)
    assert "X-Cle-Loois" not in ps.entetes_signal()
    monkeypatch.setenv("LOOIS_SUPPORT_CLE", "cle-factice")
    assert ps.entetes_signal()["X-Cle-Loois"] == "cle-factice"


def test_nom_machine(monkeypatch):
    """RENDER_SERVICE_NAME prioritaire, sinon nom d'hôte."""
    monkeypatch.setenv("RENDER_SERVICE_NAME", "albarka-api")
    assert ps.nom_machine() == "albarka-api"
    monkeypatch.delenv("RENDER_SERVICE_NAME")
    assert ps.nom_machine()


def test_desactivation(monkeypatch):
    """PRESENCE_SAWALI=0 coupe le signal ; actif par défaut."""
    monkeypatch.delenv("PRESENCE_SAWALI", raising=False)
    assert ps.presence_active()
    monkeypatch.setenv("PRESENCE_SAWALI", "0")
    assert not ps.presence_active()
