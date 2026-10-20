"""Lot 44 — bandeau d'alerte et déconnexion programmée du portail (super-admin seul).
Tests unitaires (base simulée) : aucun appel au serveur réel."""
import asyncio
import os
import sys
from datetime import timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot44")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot44")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_maintenance as mt  # noqa: E402
from albarka_models import ADMIN_ACCOUNT_EMAIL  # noqa: E402

ADMIN = {"id": "a1", "email": ADMIN_ACCOUNT_EMAIL, "roles": ["superviseur"], "full_name": "Super Admin"}
AUTRE = {"id": "u1", "email": "dg@cabinet.test", "roles": ["superviseur"], "full_name": "DG"}


def _client(utilisateur):
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    mt.db = db
    mt.vider_cache()
    app = FastAPI()
    app.include_router(mt.router, prefix="/api")
    app.dependency_overrides[mt.get_current_user] = lambda: utilisateur
    return TestClient(app), db


def test_les_phases_suivent_l_heure_du_serveur():
    depart = mt.maintenant()
    doc = {"actif": True, **mt.calendrier(10, 5, depart)}      # 10 min, les 5 derniers % verrouillés = dernières 30 s
    assert mt.phase_de(doc, depart + timedelta(minutes=1)) == mt.ANNONCE
    assert mt.phase_de(doc, depart + timedelta(minutes=9, seconds=45)) == mt.VERROUILLAGE
    assert mt.phase_de(doc, depart + timedelta(minutes=10, seconds=1)) == mt.MAINTENANCE
    assert mt.phase_de({"actif": False}) == mt.AUCUNE


def test_seul_le_super_admin_annonce_annule_et_reactive():
    c, _ = _client(AUTRE)
    assert c.post("/api/maintenance/annoncer", json={"message": "Maintenance", "duree_minutes": 5}).status_code == 403
    assert c.post("/api/maintenance/reactiver").status_code == 403
    assert c.put("/api/bandeau", json={"message": "Incident"}).status_code == 403
    c, _ = _client(ADMIN)
    r = c.post("/api/maintenance/annoncer", json={"message": "Maintenance à 22 h", "duree_minutes": 5})
    assert r.status_code == 200 and r.json()["phase"] == "annonce" and r.json()["part_verrouillage"] == 5
    assert c.post("/api/maintenance/annoncer", json={"message": "Autre"}).status_code == 409      # déjà une annonce
    assert c.get("/api/maintenance/etat").json()["phase"] == "annonce"                              # lisible sans droit
    assert c.post("/api/maintenance/annuler").json()["phase"] == "aucune"


def test_apres_l_echeance_seuls_les_non_super_admin_sont_bloques_jusqu_a_la_reactivation():
    c, db = _client(ADMIN)
    c.post("/api/maintenance/annoncer", json={"message": "Maintenance", "duree_minutes": 1})
    passe = (mt.maintenant() - timedelta(minutes=2)).isoformat()
    asyncio.run(db.settings.update_one({"_id": "maintenance_portail_etat"}, {"$set": {"echeance": passe, "debut_verrouillage": passe}}))
    mt.vider_cache()
    assert c.get("/api/maintenance/etat").json()["phase"] == "maintenance"
    # Autre utilisateur : 503 (requête) et connexion refusée ; super-admin : jamais bloqué
    with pytest.raises(HTTPException) as e:
        asyncio.run(mt.controler_session(AUTRE, {"iat": 0}))
    assert e.value.status_code == 503 and e.value.detail["code"] == "maintenance_portail"
    asyncio.run(mt.controler_session(ADMIN, {"iat": 0}))
    with pytest.raises(HTTPException):
        asyncio.run(mt.refuser_connexion_si_maintenance(AUTRE))
    asyncio.run(mt.refuser_connexion_si_maintenance(ADMIN))
    # Réactivation par le super-admin : connexions rétablies, mais les sessions d'avant l'échéance restent invalides
    assert c.post("/api/maintenance/reactiver").json()["phase"] == "aucune"
    mt.vider_cache()
    with pytest.raises(HTTPException) as e:
        asyncio.run(mt.controler_session(AUTRE, {"iat": 1}))                    # ancienne session
    assert e.value.status_code == 401
    asyncio.run(mt.controler_session(AUTRE, {"iat": int(mt.maintenant().timestamp()) + 5}))   # nouvelle session


def test_bandeau_avec_image_en_coin_publie_par_le_super_admin():
    c, _ = _client(ADMIN)
    assert c.get("/api/bandeau").json() == {"actif": False}
    image = "data:image/png;base64,iVBORw0KGgo="
    r = c.put("/api/bandeau", json={"message": "Incident WhatsApp en cours", "severite": "critical", "image": image,
                                    "lien_url": "https://exemple.bf/etat", "lien_libelle": "Suivre"})
    assert r.status_code == 200
    b = c.get("/api/bandeau").json()
    assert b["actif"] and b["severite"] == "critical" and b["image"] == image and b["lien_libelle"] == "Suivre"
    # Refus : image non autorisée, gravité inconnue, lien non sûr
    assert c.put("/api/bandeau", json={"message": "x", "image": "data:text/html;base64,AAAA"}).status_code == 422
    assert c.put("/api/bandeau", json={"message": "x", "severite": "rose"}).status_code == 422
    assert c.put("/api/bandeau", json={"message": "x", "lien_url": "javascript:alert(1)"}).status_code == 422
    assert c.delete("/api/bandeau").json()["actif"] is False and c.get("/api/bandeau").json() == {"actif": False}


def test_bandeau_programme_affiche_seulement_dans_sa_periode():
    from datetime import timedelta
    c, db = _client(ADMIN)
    futur = (mt.maintenant() + timedelta(hours=2)).isoformat()
    fin = (mt.maintenant() + timedelta(hours=5)).isoformat()
    r = c.put("/api/bandeau", json={"message": "Coupure ce soir", "debut": futur, "fin": fin})
    assert r.status_code == 200 and r.json()["statut"] == "programme"
    assert c.get("/api/bandeau").json() == {"actif": False}                       # pas encore affiché au public
    admin = c.get("/api/bandeau/admin").json()
    assert admin["statut"] == "programme" and admin["message"] == "Coupure ce soir" and admin["debut"] == futur
    # Le début arrive : affiché ; la fin passe : plus affiché
    avant = (mt.maintenant() - timedelta(minutes=1)).isoformat()
    asyncio.run(db.settings.update_one({"_id": "maintenance_portail_bandeau"}, {"$set": {"debut": avant}}))
    assert c.get("/api/bandeau").json()["message"] == "Coupure ce soir"
    asyncio.run(db.settings.update_one({"_id": "maintenance_portail_bandeau"}, {"$set": {"fin": avant}}))
    assert c.get("/api/bandeau").json() == {"actif": False} and c.get("/api/bandeau/admin").json()["statut"] == "termine"
    # Refus : fin passée, fin avant le début, date illisible
    assert c.put("/api/bandeau", json={"message": "x", "fin": avant}).status_code == 422
    assert c.put("/api/bandeau", json={"message": "x", "debut": fin, "fin": futur}).status_code == 422
    assert c.put("/api/bandeau", json={"message": "x", "debut": "demain"}).status_code == 422
    # Aucune nouvelle collection : tout est dans `settings`
    assert asyncio.run(db.list_collection_names()) == ["settings"]


def test_lot48_reprise_du_bandeau_range_dans_l_ancienne_collection():
    """Les lots 44-45 rangeaient le bandeau dans `maintenance_portail` ; le lot 46 l'a cherché dans `settings` : réglage « perdu ».
    Il doit être repris (et recopié dans `settings`) sans rien perdre."""
    c, db = _client(ADMIN)
    asyncio.run(db.maintenance_portail.insert_one({"_id": "bandeau", "actif": True, "severite": "critical", "message": "Incident en cours",
                                                   "image": "data:image/png;base64,iVBORw0KGgo=", "maj_le": "2026-10-19T22:00:00+00:00"}))
    b = c.get("/api/bandeau").json()
    assert b["actif"] and b["message"] == "Incident en cours" and b["severite"] == "critical" and b["image"]
    # Le formulaire des Paramètres (lecture admin) reçoit lui aussi le bandeau repris, avec son statut
    adm = c.get("/api/bandeau/admin").json()
    assert adm["message"] == "Incident en cours" and adm["severite"] == "critical" and adm["statut"] == "affiche" and adm["image"]
    assert c.get("/api/maintenance/journal").status_code == 200
    copie = asyncio.run(db.settings.find_one({"_id": "maintenance_portail_bandeau"}))
    assert copie and copie["message"] == "Incident en cours"                          # recopié : l'ancien emplacement n'est plus lu
    # La maintenance annoncée avant le changement est reprise aussi
    asyncio.run(db.maintenance_portail.insert_one({"_id": "etat", "actif": True, "message": "Maintenance 22 h", "duree_minutes": 5,
                                                   "part_verrouillage": 5, **mt.calendrier(5, 5)}))
    mt.vider_cache()
    assert c.get("/api/maintenance/etat").json()["message"] == "Maintenance 22 h"
    # Aucune nouvelle collection n'est créée par la lecture ; l'ancienne n'est jamais modifiée
    assert asyncio.run(db.maintenance_portail.count_documents({})) == 2
