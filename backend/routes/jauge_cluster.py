"""Lot 27 — GET /api/admin/atlas/jauge : occupation du cluster de production (administrateur uniquement).
Règles de calcul : jauge_cluster.py (racine du backend). Jamais d'adresse ni d'identifiant de connexion dans la réponse."""
from __future__ import annotations

import os

import jauge_cluster
from fastapi import Depends


def setup_jauge_cluster_routes(*, db, api, get_current_admin) -> None:
    """Branche la route (appelée par server.py avant app.include_router(api))."""

    @api.get("/admin/atlas/jauge", tags=["Back-office"])
    async def jauge(forcer: bool = False, _: dict = Depends(get_current_admin)):
        """Taille occupée (Mo) et nombre de collections du cluster, avec couleur et pourcentage ;
        « forcer » ignore la mesure gardée en mémoire (10 min)."""
        # Le client Mongo est celui de la base de la plateforme (db.client) ; nom de la base = DB_NAME
        return await jauge_cluster.mesurer(db.client, os.environ.get("DB_NAME", ""), forcer)
