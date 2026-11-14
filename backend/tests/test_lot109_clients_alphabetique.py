"""Lot 109 — la liste des clients est triée par ordre alphabétique (raison sociale, sinon nom), sans tenir compte des accents ni des majuscules."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from albarka_clients import cle_alphabetique  # noqa: E402


def _tri(clients):
    return [c.get("company") or c.get("full_name") for c in sorted(clients, key=cle_alphabetique)]


def test_ordre_alphabetique_sans_accents_ni_majuscules():
    clients = [{"company": "zandgo SARL"}, {"company": "Étoile du Sud"}, {"company": "albarka"}, {"company": "Boulangerie Top Pain"},
               {"company": "Pharmacie WEND DENDA"}, {"company": "ÉCOLE Saint-Paul"}]
    assert _tri(clients) == ["albarka", "Boulangerie Top Pain", "ÉCOLE Saint-Paul", "Étoile du Sud", "Pharmacie WEND DENDA", "zandgo SARL"]


def test_repli_sur_le_nom_et_sans_nom_en_dernier():
    clients = [{"full_name": "SANNA Azize"}, {"company": "", "full_name": ""}, {"company": "Cabinet ALBARKA"}, {"full_name": "badini Awa"}]
    assert _tri(clients) == ["badini Awa", "Cabinet ALBARKA", "SANNA Azize", ""]
    assert [cle_alphabetique(c)[0] for c in sorted(clients, key=cle_alphabetique)] == [False, False, False, True]
