"""Lot 72 — espace client : la catégorie « Ordre de mission » existe (page « Ordres de mission ») et utilise le message par défaut."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import albarka_client_space as cs  # noqa: E402


def test_categorie_ordre_de_mission_proposee_au_depot():
    assert cs.CATEGORIES["ordre_mission"] == "Ordre de mission"
    assert "rapport" in cs.CATEGORIES                              # page « Rapports »


def test_message_par_defaut_pour_un_ordre_de_mission():
    txt = cs.pick_template({}, [{"category": "ordre_mission"}])
    assert txt == cs.DEFAULT_TEMPLATES["default"]
