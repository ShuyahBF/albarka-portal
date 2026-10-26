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


# ---------- Lot 73 : génération d'un ordre de mission depuis « Documents & modèles » ----------
def test_modele_ordre_de_mission_fourni_d_office():
    import albarka_letters as al
    assert "{{intervenant_nom}}" in al._SEED_ORDRE and "{{client.nom}}" in al._SEED_ORDRE and "{{doc.numero}}" in al._SEED_ORDRE
    assert 'data-var="intervenant_nom"' in al._corps_pastilles(al._SEED_ORDRE)
    cles = {v["key"] for v in al._SEED_ORDRE_VARIABLES}
    assert {"intervenant_nom", "objet_mission", "periode_mission"} <= cles


def test_depot_dans_la_categorie_du_modele():
    """La catégorie « ordre_mission » du modèle est une catégorie de l'espace client ; une catégorie inconnue retombe sur « courrier »."""
    import albarka_letters as al
    assert "ordre_mission" in al.CATEGORIES and "ordre_mission" in cs.CATEGORIES
    assert "avis_mission" in al.CATEGORIES and "avis_mission" not in cs.CATEGORIES


def test_depot_range_l_ordre_de_mission_dans_sa_rubrique(monkeypatch):
    """Le dépôt d'un document généré garde la catégorie du modèle (ordre de mission) ; un avis de mission va dans « Courrier »."""
    import asyncio
    import albarka_letters as al
    from mongomock_motor import AsyncMongoMockClient
    base = AsyncMongoMockClient()["test_lot73"]
    monkeypatch.setattr(al, "db", base)

    async def faux_stockage(db, **k):
        return {"id": "s1", "path": "x/y.pdf", "size": 3}
    monkeypatch.setattr(al.albarka_storage, "save_and_log", faux_stockage)
    user = {"id": "u1", "full_name": "Secrétariat"}
    run = asyncio.get_event_loop().run_until_complete
    for categorie, attendu in (("ordre_mission", "ordre_mission"), ("avis_mission", "courrier")):
        doc = {"id": "g-" + categorie, "number": "1/ODM/DG/2026", "title": "Titre", "tenant_id": "cli1", "category": categorie, "doc_date": "2026-10-26"}
        cid = run(al._deposit(doc, b"%PDF", user, False))
        assert run(base.client_documents.find_one({"id": cid}))["category"] == attendu
