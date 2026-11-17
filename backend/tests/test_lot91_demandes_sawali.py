"""Lot 91 — demandes d'ALBARKA à SAWALI : liste horodatée, remontée signée, numéro / statut / commentaire retournés, recherche."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_demandes_sawali as dm  # noqa: E402
import albarka_support_sawali  # noqa: E402

USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Super", "roles": ["superviseur"]},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"]},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"]},
    "secr": {"id": "u-secr", "email": "secr@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"]},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"]},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot91"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(dm.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[dm.get_current_user] = fake_user
    return TestClient(app)


H = {"X-User": "sup"}


def test_acces_refuse_aux_autres_roles(env):
    assert env.get("/api/demandes-sawali", headers={"X-User": "compta"}).status_code == 403
    assert env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Bug"}, headers={"X-User": "compta"}).status_code == 403


def test_creation_horodatee_et_validation(env):
    r = env.post("/api/demandes-sawali", json={"type": "nouveaute", "texte": "Export Excel du livre de paie"}, headers=H)
    assert r.status_code == 200 and r.json()["statut"] == "a_remonter" and r.json()["demandee_le"] and r.json()["numero_sawali"] is None
    assert env.post("/api/demandes-sawali", json={"type": "autre", "texte": "xxxxx"}, headers=H).status_code == 422


def test_remontee_numero_commentaire_et_recherche(env, monkeypatch):
    a = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Le bulletin déborde sur la 2e page"}, headers=H).json()
    b = env.post("/api/demandes-sawali", json={"type": "nouveaute", "texte": "Signature électronique des contrats"}, headers=H).json()
    envoye = {}

    async def faux_sawali(chemin, corps, delai=15):
        envoye["chemin"], envoye["corps"] = chemin, corps
        return {"demandes": [
            {"ref_locale": a["id"], "numero": "DEM-ALB-0001", "statut": "realisee", "commentaire": "Corrigé au lot 385", "realisee_le": "2026-11-14"},
            {"ref_locale": b["id"], "numero": "DEM-ALB-0002", "statut": "refusee", "commentaire": "Hors périmètre", "prevue_le": None},
            {"ref_locale": "inconnue", "numero": "DEM-ALB-0003", "statut": "realisee"},
        ]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    r = env.post("/api/demandes-sawali/envoyer", headers=H)
    assert r.status_code == 200 and r.json() == {"envoyees": 2, "mises_a_jour": 2}
    assert envoye["chemin"] == "/webhook/plateforme-demandes" and {d["ref_locale"] for d in envoye["corps"]["demandes"]} == {a["id"], b["id"]}
    liste = env.get("/api/demandes-sawali", headers=H).json()
    par_id = {d["id"]: d for d in liste["demandes"]}
    assert par_id[a["id"]]["numero_sawali"] == "DEM-ALB-0001" and par_id[a["id"]]["realisee_le"] == "2026-11-14"
    assert par_id[b["id"]]["statut"] == "refusee" and liste["compteurs"]["refusee"] == 1
    # Recherche : par numéro, par commentaire, par statut (les refusées se retrouvent)
    assert [d["id"] for d in env.get("/api/demandes-sawali?q=DEM-ALB-0001", headers=H).json()["demandes"]] == [a["id"]]
    assert [d["id"] for d in env.get("/api/demandes-sawali?q=hors périmètre", headers=H).json()["demandes"]] == [b["id"]]
    assert [d["id"] for d in env.get("/api/demandes-sawali?q=refusée", headers=H).json()["demandes"]] == [b["id"]]
    assert env.get("/api/demandes-sawali?q=introuvable", headers=H).json()["demandes"] == []
    # Plus rien à remonter au deuxième envoi : on relit seulement les statuts
    r2 = env.post("/api/demandes-sawali/envoyer", headers=H)
    assert r2.json()["envoyees"] == 0 and envoye["corps"] == {"demandes": []}


def test_droits_dg_direction_secretariat(env):
    for qui in ("dg", "dir", "secr", "sup"):
        assert env.get("/api/demandes-sawali", headers={"X-User": qui}).status_code == 200
    assert env.get("/api/demandes-sawali", headers={"X-User": "compta"}).status_code == 403


def test_modification_et_suppression_tant_que_non_validee(env, monkeypatch):
    a = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Brouillon"}, headers=H).json()
    # Avant remontée : modification et suppression purement locales (SAWALI n'est pas appelé)
    assert env.put(f"/api/demandes-sawali/{a['id']}", json={"type": "nouveaute", "texte": "Brouillon modifié"}, headers={"X-User": "secr"}).json()["texte"] == "Brouillon modifié"
    assert env.delete(f"/api/demandes-sawali/{a['id']}", headers={"X-User": "dg"}).status_code == 200
    b = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "À garder"}, headers=H).json()
    c = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "À valider"}, headers=H).json()
    appels = []

    async def faux(chemin, corps, delai=15):
        appels.append(corps)
        if corps.get("modifications") or corps.get("suppressions"):
            ref = (corps.get("modifications") or [{"ref_locale": None}])[0]["ref_locale"] or corps["suppressions"][0]
            if ref == c["id"]:     # SAWALI a validé entre-temps
                return {"demandes": [{"ref_locale": c["id"], "numero": "DEM-ALB-0002", "statut": "realisee", "realisee_le": "2026-11-15"}],
                        "refus": [{"ref_locale": c["id"], "motif": "Demande déjà validée par SAWALI : suppression impossible"}]}
            return {"demandes": [{"ref_locale": b["id"], "numero": "DEM-ALB-0001", "statut": "remontee"}], "refus": []}
        return {"demandes": [{"ref_locale": b["id"], "numero": "DEM-ALB-0001", "statut": "remontee"},
                             {"ref_locale": c["id"], "numero": "DEM-ALB-0002", "statut": "remontee"}]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux)
    env.post("/api/demandes-sawali/envoyer", headers=H)
    # Remontée mais non validée : la modification est relayée à SAWALI puis enregistrée
    r = env.put(f"/api/demandes-sawali/{b['id']}", json={"type": "correction", "texte": "Texte corrigé"}, headers=H)
    assert r.status_code == 200 and r.json()["texte"] == "Texte corrigé" and appels[-1]["modifications"][0]["texte"] == "Texte corrigé"
    # Validée entre-temps chez SAWALI : suppression refusée (409), statut relu
    r = env.delete(f"/api/demandes-sawali/{c['id']}", headers=H)
    assert r.status_code == 409 and "validée" in r.json()["detail"]
    assert {d["id"]: d for d in env.get("/api/demandes-sawali", headers=H).json()["demandes"]}[c["id"]]["statut"] == "realisee"
    # Déjà validée localement : plus modifiable
    assert env.put(f"/api/demandes-sawali/{c['id']}", json={"type": "correction", "texte": "xxxx"}, headers=H).status_code == 409
    # Remontée non validée : suppression relayée puis locale
    assert env.delete(f"/api/demandes-sawali/{b['id']}", headers=H).status_code == 200
    assert appels[-1]["suppressions"] == [b["id"]]


def test_relecture_automatique_ne_remonte_rien_et_ne_tourne_que_si_necessaire(env, monkeypatch):
    """Lot 102 — relecture des statuts (toutes les 15 min par le planificateur, 2 min par l'écran) : sans remontée, et seulement s'il y a des demandes remontées non validées."""
    import asyncio
    appels = []

    async def faux_sawali(chemin, corps, delai=15):
        appels.append(corps)
        # 1er échange (remontée) : « remontée » ; ensuite SAWALI a réalisé la demande
        statut = "remontee" if len(appels) == 1 else "realisee"
        return {"demandes": [{"ref_locale": a["id"], "numero": "DEM-ALB-0009", "statut": statut, "commentaire": "Fait", "realisee_le": "2026-11-15" if statut == "realisee" else None}]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    a = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Premier point à corriger"}, headers=H).json()
    # Rien de remonté : aucune relecture (aucun appel à SAWALI)
    assert asyncio.run(dm.releve_automatique()) is None and appels == []
    assert env.post("/api/demandes-sawali/relire", headers=H).json() == {"envoyees": 0, "mises_a_jour": 0}
    # Après la remontée, la demande est « remontée » : la relecture automatique relit les statuts
    env.post("/api/demandes-sawali/envoyer", headers=H)
    n = len(appels)
    r = env.post("/api/demandes-sawali/relire", headers=H)
    assert r.status_code == 200 and len(appels) == n + 1 and appels[-1] == {"demandes": []}          # relit sans rien remonter
    # SAWALI l'a réalisée : plus rien à suivre, plus d'appel
    assert env.get("/api/demandes-sawali", headers=H).json()["demandes"][0]["statut"] == "realisee"
    assert asyncio.run(dm.releve_automatique()) is None and len(appels) == n + 1


def test_marquer_changements_pour_la_pastille():
    """Lot 108 — seule une VRAIE modification faite par SAWALI donne `modifiee_sawali_le` ; la première remontée (action de l'utilisateur) et une relecture sans changement, non."""
    locales = [{"id": "a", "statut": "a_remonter"}, {"id": "b", "statut": "remontee", "numero_sawali": "DEM-1", "commentaire": None},
               {"id": "c", "statut": "remontee", "numero_sawali": "DEM-3", "commentaire": "ok"}]
    maj = {"a": {"numero_sawali": "DEM-0", "statut": "remontee", "commentaire": None},               # 1re remontée : pas de pastille
           "b": {"numero_sawali": "DEM-1", "statut": "realisee", "commentaire": "Fait", "realisee_le": "2026-11-15"},    # changement fait par SAWALI
           "c": {"numero_sawali": "DEM-3", "statut": "remontee", "commentaire": "ok"}}                # relue sans changement
    r = dm.marquer_changements(locales, maj)
    assert "modifiee_sawali_le" not in r["a"] and "modifiee_sawali_le" in r["b"] and "modifiee_sawali_le" not in r["c"]


def test_pastille_demandes_par_utilisateur(env, monkeypatch):
    """La pastille compte les demandes modifiées par SAWALI depuis la dernière ouverture de la page par CET utilisateur."""
    import asyncio
    import albarka_badges
    a = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Point à suivre chez SAWALI"}, headers=H).json()
    etat = {"n": 0}

    async def faux_sawali(chemin, corps, delai=15):
        etat["n"] += 1
        statut = "remontee" if etat["n"] == 1 else "realisee"
        return {"demandes": [{"ref_locale": a["id"], "numero": "DEM-ALB-0010", "statut": statut, "commentaire": "Fait" if statut == "realisee" else None}]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    env.post("/api/demandes-sawali/envoyer", headers=H)                  # 1re remontée : pas de pastille
    from db import db as base
    assert asyncio.run(base.demandes_sawali.count_documents({"modifiee_sawali_le": {"$exists": True}})) == 0
    env.post("/api/demandes-sawali/relire", headers=H)                   # SAWALI a réalisé la demande : pastille
    assert asyncio.run(base.demandes_sawali.count_documents({"modifiee_sawali_le": {"$exists": True}})) == 1


def test_statuts_en_cours_point_mort_et_duree_relus_de_sawali(env, monkeypatch):
    """Lot 120 : « En cours », « Point mort », durée estimée, début prévu et historique viennent de SAWALI et sont affichés."""
    a = env.post("/api/demandes-sawali", json={"type": "correction", "texte": "Première demande"}, headers=H).json()
    b = env.post("/api/demandes-sawali", json={"type": "nouveaute", "texte": "Deuxième demande"}, headers=H).json()

    async def faux_sawali(chemin, corps, delai=15):
        return {"demandes": [
            {"ref_locale": a["id"], "numero": "DEM-ALB-0001", "statut": "en_cours", "prevue_le": "2026-11-24", "debut_prevu_le": "2026-11-17",
             "duree_valeur": 1, "duree_unite": "semaine", "historique": [{"statut": "en_cours", "le": "2026-11-17T08:00:00+00:00"}]},
            {"ref_locale": b["id"], "numero": "DEM-ALB-0002", "statut": "point_mort", "commentaire": "Attente des données", "debut_prevu_le": "2026-11-10"},
        ]}
    monkeypatch.setattr(albarka_support_sawali, "appeler_sawali", faux_sawali)
    assert env.post("/api/demandes-sawali/envoyer", headers=H).status_code == 200
    liste = env.get("/api/demandes-sawali", headers=H).json()
    par = {d["id"]: d for d in liste["demandes"]}
    assert par[a["id"]]["statut"] == "en_cours" and par[a["id"]]["statut_libelle"] == "En cours"
    assert par[a["id"]]["duree_valeur"] == 1 and par[a["id"]]["duree_unite"] == "semaine" and par[a["id"]]["debut_prevu_le"] == "2026-11-17"
    assert par[a["id"]]["historique"][0]["statut"] == "en_cours"
    assert par[b["id"]]["statut_libelle"] == "Point mort" and liste["compteurs"]["en_cours"] == 1 and liste["compteurs"]["point_mort"] == 1
    # Recherche par statut : « point mort » retrouve la demande
    assert env.get("/api/demandes-sawali?q=point mort", headers=H).json()["demandes"][0]["id"] == b["id"]
