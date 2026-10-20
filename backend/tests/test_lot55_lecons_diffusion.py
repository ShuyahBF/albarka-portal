"""Lot 55 — leçons multiples, accès manuel, diffusion WhatsApp programmée de l'info de la semaine."""
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot55")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot55")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import albarka_contenus as ct  # noqa: E402

CLIENT = {"id": "c1", "email": "c1@test.bf", "roles": ["client"]}
GESTION = {"id": "g1", "email": "g@test.bf", "roles": ["direction"]}


def _app(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(ct, "db", db)
    magasin = {}

    async def put(db_, **k):
        chemin = f"x/{k['original_filename']}"
        magasin[chemin] = k["data"]
        return {"id": "o", "path": chemin, "size": len(k["data"]), "content_type": "application/pdf"}

    async def get(path):
        return magasin[path], "application/pdf"
    monkeypatch.setattr(ct, "save_and_log", put)
    monkeypatch.setattr(ct, "get_object", get)
    app = FastAPI()
    app.include_router(ct.router, prefix="/api")
    app.dependency_overrides[ct.get_current_user] = lambda: CLIENT
    app.dependency_overrides[ct.GESTION_DEP] = lambda: GESTION
    c = TestClient(app)
    c.db = db
    return c


def test_serie_de_lecons_plan_visible_contenu_verrouille(monkeypatch):
    c = _app(monkeypatch)
    cid = c.post("/api/contenus", data={"type": "formation", "titre": "Paie complète", "format": "serie", "theme": "rh", "prix": "20000"}).json()["id"]
    c.post(f"/api/contenus/{cid}/lecons", data={"titre": "Introduction", "format": "video", "url": "https://youtu.be/abcDEF12345"})
    r = c.post(f"/api/contenus/{cid}/lecons", data={"titre": "Support", "format": "pdf"}, files={"fichier": ("s.pdf", b"%PDF", "application/pdf")})
    assert [l["titre"] for l in r.json()["lecons"]] == ["Introduction", "Support"]
    f = c.get("/api/contenus?type=formation").json()[0]
    assert [l["titre"] for l in f["lecons"]] == ["Introduction", "Support"]       # le plan est visible
    assert "url" not in f["lecons"][0] and "embed_url" not in f["lecons"][0]       # mais pas le contenu
    lid = r.json()["lecons"][1]["id"]
    assert c.get(f"/api/contenus/{cid}/lecons/{lid}/fichier").status_code == 402
    asyncio.run(c.db.users.insert_one({"id": "c1", "roles": ["client"], "full_name": "Un"}))
    assert c.post(f"/api/contenus/{cid}/acces", json={"tenant_id": "c1"}).status_code == 200
    f = c.get("/api/contenus?type=formation").json()[0]
    assert f["lecons"][0]["embed_url"].endswith("/abcDEF12345")
    assert c.get(f"/api/contenus/{cid}/lecons/{lid}/fichier").content == b"%PDF"
    assert c.delete(f"/api/contenus/{cid}/lecons/{lid}").json()["lecons"][0]["titre"] == "Introduction"


def test_acces_manuel_liste_et_retrait(monkeypatch):
    c = _app(monkeypatch)
    cid = c.post("/api/contenus", data={"type": "formation", "titre": "TVA", "format": "serie", "theme": "fiscalite", "prix": "5000"}).json()["id"]
    asyncio.run(c.db.users.insert_one({"id": "c1", "roles": ["client"], "company": "Société Un"}))
    c.post(f"/api/contenus/{cid}/acces", json={"tenant_id": "c1"})
    a = c.get(f"/api/contenus/{cid}/acces").json()
    assert a[0]["client"] == "Société Un" and a[0]["source"] == "manuel"
    assert c.delete(f"/api/contenus/{cid}/acces/c1").json() == {"ok": True}
    assert c.get(f"/api/contenus/{cid}/acces").json() == []
    assert c.get("/api/contenus?type=formation").json()[0]["acces"] is False


def test_diffusion_whatsapp_une_seule_fois_pas_de_nuit(monkeypatch):
    c = _app(monkeypatch)
    envoyes = []

    async def wa_libre(*, to_phone, message, **k):
        envoyes.append(to_phone)
        return {"ok": True}

    async def wa_modele(*, to_phone, template_name, body_params=None, **k):
        envoyes.append((to_phone, template_name))
        return {"ok": True}

    async def fenetre(phone):
        return phone.endswith("1")                                  # fenêtre ouverte pour un seul client
    import albarka_notifications as nt
    monkeypatch.setattr(nt, "send_whatsapp", wa_libre)
    monkeypatch.setattr(nt, "send_whatsapp_template", wa_modele)
    monkeypatch.setattr(nt, "wa_window_state", fenetre)
    monkeypatch.setattr(ct, "PAUSE_ENVOI", 0)
    asyncio.run(c.db.users.insert_many([
        {"id": "a", "roles": ["client"], "is_active": True, "phone": "+22670000001"},
        {"id": "b", "roles": ["client"], "is_active": True, "phone": "+22670000002"},
        {"id": "t", "roles": ["client"], "is_active": True, "phone": "+22670000003", "is_test_account": True},
        {"id": "r", "roles": ["client"], "is_active": True, "phone": "+22670000004", "can_receive_notifications": False},
    ]))
    r = c.post("/api/contenus", data={"type": "info", "titre": "CNSS : nouveau taux", "format": "lien", "url": "https://exemple.bf/x", "theme": "cnss"})
    assert r.json()["diffusion"]["statut"] == "a_envoyer"
    nuit = datetime(2026, 10, 20, 2, 0, tzinfo=timezone.utc)
    jour = datetime(2026, 10, 20, 9, 0, tzinfo=timezone.utc)
    assert asyncio.run(ct.diffuser_infos_dues(nuit))["infos"] == 0                      # jamais de nuit
    bilan = asyncio.run(ct.diffuser_infos_dues(jour))
    assert bilan == {"infos": 1, "envoyes": 2, "echecs": 0}
    assert sorted(map(str, envoyes)) == sorted(["+22670000001", str(("+22670000002", "message_cabinet"))])
    assert asyncio.run(ct.diffuser_infos_dues(jour))["infos"] == 0                      # jamais deux fois
    f = c.get("/api/contenus/admin/tout").json()[0]
    assert f["diffusion"]["statut"] == "envoyee" and f["diffusion"]["nb_envoyes"] == 2


def test_diffusion_coupee_par_reglage(monkeypatch):
    c = _app(monkeypatch)
    assert c.put("/api/contenus/admin/reglages", json={"diffusion_wa": False}).json()["diffusion_wa"] is False
    r = c.post("/api/contenus", data={"type": "info", "titre": "Sans diffusion", "format": "lien", "url": "https://exemple.bf/x", "theme": "autre"})
    assert "diffusion" not in r.json()


# ---------------------------------------------------------------- lot 56 : ordre et progression
def _serie(c, titre="Série", prix="0"):
    cid = c.post("/api/contenus", data={"type": "formation", "titre": titre, "format": "serie", "theme": "rh", "prix": prix}).json()["id"]
    ids = []
    for t in ("A", "B", "C"):
        r = c.post(f"/api/contenus/{cid}/lecons", data={"titre": t, "format": "lien", "url": "https://exemple.bf/" + t})
        ids = [l["id"] for l in r.json()["lecons"]]
    return cid, ids


def test_reordonner_les_lecons(monkeypatch):
    c = _app(monkeypatch)
    cid, ids = _serie(c)
    r = c.put(f"/api/contenus/{cid}/lecons-ordre", json={"ids": [ids[2], ids[0], ids[1]]})
    assert [l["titre"] for l in r.json()["lecons"]] == ["C", "A", "B"]
    assert c.put(f"/api/contenus/{cid}/lecons-ordre", json={"ids": [ids[0]]}).status_code == 400      # liste incomplète


def test_progression_par_client_et_vue_cabinet(monkeypatch):
    c = _app(monkeypatch)
    cid, ids = _serie(c)                                                   # gratuite : accès libre
    asyncio.run(c.db.users.insert_one({"id": "c1", "roles": ["client"], "company": "Société Un"}))
    r = c.post(f"/api/contenus/{cid}/progression", json={"lecon_id": ids[0], "fait": True}).json()
    assert r["pct"] == 33 and r["total"] == 3
    c.post(f"/api/contenus/{cid}/progression", json={"lecon_id": ids[1], "fait": True})
    f = c.get("/api/contenus?type=formation").json()[0]
    assert f["progression"]["pct"] == 67 and f["progression"]["derniere"] == ids[1]
    assert c.post(f"/api/contenus/{cid}/progression", json={"lecon_id": ids[1], "fait": False}).json()["pct"] == 33
    assert c.post(f"/api/contenus/{cid}/progression", json={"lecon_id": "inconnue"}).status_code == 404
    suivi = c.get(f"/api/contenus/{cid}/progression").json()
    assert suivi == [{"tenant_id": "c1", "client": "Société Un", "terminees": 1, "total": 3, "pct": 33, "maj": suivi[0]["maj"]}]


def test_progression_refusee_sans_acces_payant(monkeypatch):
    c = _app(monkeypatch)
    cid, ids = _serie(c, prix="9000")
    assert c.post(f"/api/contenus/{cid}/progression", json={"lecon_id": ids[0], "fait": True}).status_code == 402


# ---------------------------------------------------------------- lot 57 : relance WhatsApp des formations payantes
def _relance_env(monkeypatch):
    c = _app(monkeypatch)
    envoyes = []

    async def envoi(phone, texte, modele):
        envoyes.append((phone, texte))
        return {"ok": True}
    monkeypatch.setattr(ct, "_envoyer_wa", envoi)
    monkeypatch.setattr(ct, "PAUSE_ENVOI", 0)
    asyncio.run(c.db.users.insert_many([
        {"id": "a", "roles": ["client"], "is_active": True, "phone": "+22670000001"},      # a acheté, inachevé
        {"id": "b", "roles": ["client"], "is_active": True, "phone": "+22670000002"},      # n'a pas acheté
        {"id": "d", "roles": ["client"], "is_active": True},                               # pas de numéro
        {"id": "t", "roles": ["client"], "is_active": True, "phone": "+22670000009", "is_test_account": True},
    ]))
    cid, ids = _serie(c, prix="10000")
    r = c.post(f"/api/contenus/{cid}/acces", json={"tenant_id": "a"})
    assert r.status_code == 200, r.text
    return c, cid, envoyes


def test_relance_non_achetes_apercu_puis_envoi_sans_doublon(monkeypatch):
    c, cid, envoyes = _relance_env(monkeypatch)

    async def scenario():
        r = c.post(f"/api/contenus/{cid}/relance", json={"cible": "non_achetes", "simuler": True}).json()
        assert r == {"destinataires": 1, "sans_numero": 1, "deja_relances": 0} and not envoyes     # aperçu : rien ne part
        c.post(f"/api/contenus/{cid}/relance", json={"cible": "non_achetes", "simuler": False})
        await asyncio.sleep(0.2)                                                                     # tâche de fond
    asyncio.run(scenario())
    assert [e[0] for e in envoyes] == ["+22670000002"]
    r = c.post(f"/api/contenus/{cid}/relance", json={"cible": "non_achetes", "simuler": True}).json()
    assert r["destinataires"] == 0 and r["deja_relances"] == 1                                       # pas deux fois en 14 jours


def test_relance_inacheves_et_refus(monkeypatch):
    c, cid, envoyes = _relance_env(monkeypatch)
    r = c.post(f"/api/contenus/{cid}/relance", json={"cible": "inacheves", "simuler": True}).json()
    assert r["destinataires"] == 1                                                                    # a acheté, n'a rien commencé
    assert c.post(f"/api/contenus/{cid}/relance", json={"cible": "autre"}).status_code == 400
    gratuite = c.post("/api/contenus", data={"type": "formation", "titre": "Gratuite", "format": "serie", "theme": "rh"}).json()["id"]
    assert c.post(f"/api/contenus/{gratuite}/relance", json={"cible": "non_achetes"}).status_code == 400
