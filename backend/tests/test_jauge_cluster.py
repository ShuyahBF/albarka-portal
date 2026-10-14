"""Jauge du cluster Atlas : couleurs, pourcentages, mesure avec client simulé, route réservée à l'administrateur.
Lancer : cd backend && python -m pytest tests/test_jauge_cluster.py -q"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jauge_cluster as jc  # noqa: E402


def test_couleurs_aux_seuils():
    assert jc.niveau(0.44) == "ok" and jc.niveau(0.45) == "attention" and jc.niveau(0.89) == "attention"
    assert jc.niveau(0.90) == "plein" and jc.niveau(1.0) == "plein"


def test_limite_reglable_par_variable(monkeypatch):
    monkeypatch.delenv("ATLAS_LIMITE_MO", raising=False)
    assert jc.synthese(1150.5, 100)["taille"]["limite_mo"] == 5120.0       # défaut Flex
    monkeypatch.setenv("ATLAS_LIMITE_MO", "512")                            # cluster gratuit M0
    assert jc.synthese(513.2, 10)["taille"]["niveau"] == "plein"
    monkeypatch.setenv("ATLAS_LIMITE_MO", "abc")                            # valeur illisible : défaut
    assert jc.synthese(10, 10)["taille"]["limite_mo"] == 5120.0


def test_synthese_prend_le_pire_des_deux(monkeypatch):
    monkeypatch.delenv("ATLAS_LIMITE_COLLECTIONS", raising=False)
    s = jc.synthese(1150.5, 500, 5120.0)
    assert s["taille"]["pourcentage"] == 22.5 and s["taille"]["niveau"] == "ok"
    assert s["collections"]["niveau"] == "plein" and s["niveau"] == "plein" and s["pourcentage"] == 100.0


class _Base:
    def __init__(self, octets, collections):
        self.o, self.c = octets, collections

    async def command(self, nom):
        return {"dataSize": self.o, "indexSize": self.o}

    async def list_collection_names(self):
        return [f"c{i}" for i in range(self.c)]


class _Client:
    bases = {"albarka": _Base(100 * 1024 * 1024, 30), "sawali": _Base(50 * 1024 * 1024, 70)}

    async def list_database_names(self):
        return [*self.bases, "admin", "local"]

    def __getitem__(self, nom):
        return self.bases[nom]


def test_mesure_cumule_les_bases_et_ignore_les_internes():
    jc._cache.update(t=0.0, mesure=None)
    m = asyncio.new_event_loop().run_until_complete(jc.mesurer(_Client(), "albarka", forcer=True))
    assert m["taille"]["total_mo"] == 300.0 and m["collections"]["total"] == 100
    assert [b["nom"] for b in m["bases"]] == ["albarka", "sawali"] and m["bases"][0]["courante"] is True


def test_route_reservee_a_l_administrateur():
    from fastapi import APIRouter, Depends, FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from routes.jauge_cluster import setup_jauge_cluster_routes

    class _Db:                      # imite la base Motor : seul l'attribut .client sert
        client = _Client()

    async def admin(role: str = ""):
        if role != "admin":
            raise HTTPException(status_code=403, detail="Réservé à l'administrateur")
        return {"role": "admin"}

    app, api = FastAPI(), APIRouter(prefix="/api")
    setup_jauge_cluster_routes(db=_Db(), api=api, get_current_admin=admin)
    app.include_router(api)
    jc._cache.update(t=0.0, mesure=None)
    c = TestClient(app)
    assert c.get("/api/admin/atlas/jauge").status_code == 403
    r = c.get("/api/admin/atlas/jauge?role=admin&forcer=true")
    assert r.status_code == 200 and {"taille", "collections", "niveau", "pourcentage", "bases"} <= set(r.json())


def test_lot_expose():
    import lot
    assert lot.LOT and lot.LOT_LIBELLE
