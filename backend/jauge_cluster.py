"""Lot 27 — JAUGE DU CLUSTER DE PRODUCTION (MongoDB Atlas) : taille occupée sur le disque et nombre de collections.

Demande du propriétaire (14/10/2026) : toutes les plateformes (ALBARKA comprise) affichent, comme SAWALI, l'occupation du cluster de
production dans la barre latérale du portail (pastille « pictogramme base + couleur + % », détail au clic).

Un cluster Atlas a deux plafonds, valables pour TOUTES les bases réunies (SAWALI, ZandGo, adLyn… partagent le même
cluster) :
    - la taille des données (« Logical Size » d'Atlas ≈ dataSize + indexSize de chaque base) : 5 Go sur un cluster Flex
      (celui d'ALBARKA, partagé avec SAWALI, par défaut ici), 512 Mo sur un cluster gratuit M0 (variable ATLAS_LIMITE_MO) ;
    - 500 collections (Flex comme M0).
Au-delà, Atlas refuse les écritures : la plateforme tombe en panne sans message clair. D'où cette jauge.

Couleurs (même règle que SAWALI) : vert sous 45 % · orange à partir de 45 % · rouge à partir de 90 % (10 % ou moins restant).
La pastille affiche le plus élevé des deux pourcentages ; l'espace disque est le plus souvent le premier plafond atteint.

Pour un développeur WinDev : mesurer() fait une « interrogation du serveur de bases » (2 appels par base : taille puis
liste des collections), gardée 10 minutes en mémoire pour ne pas la répéter à chaque affichage de page. Elle ne lève
jamais d'erreur : si le droit de lister les bases manque, on mesure au moins la base de la plateforme.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ALBARKA partage le cluster « Cluster0 » (SAWALI, ZandGo, ALBARKA…), un cluster Flex : 5 Go de données et 500 collections.
# (512 Mo = cluster gratuit M0, par exemple celui du portail e-Kol : réglable par la variable ATLAS_LIMITE_MO.)
LIMITE_MO_DEFAUT = 5120.0
LIMITE_COLLECTIONS_DEFAUT = 500    # variable ATLAS_LIMITE_COLLECTIONS
PART_ORANGE = 0.45
PART_ROUGE = 0.90
BASES_IGNOREES = {"local", "config", "admin"}      # bases internes de MongoDB, hors quota utilisateur
DUREE_CACHE_S = 600

_cache: Dict[str, Any] = {"t": 0.0, "mesure": None}


def _reel(cle: str, defaut: float) -> float:
    """Limite lue dans une variable d'environnement (nombre positif), valeur par défaut sinon."""
    try:
        v = float(os.environ.get(cle) or defaut)
        return v if v > 0 else defaut
    except ValueError:
        return defaut


def niveau(part: float) -> str:
    """Couleur de la jauge selon la part occupée (0 à 1) : ok (vert), attention (orange), plein (rouge)."""
    if part >= PART_ROUGE:
        return "plein"
    return "attention" if part >= PART_ORANGE else "ok"


def synthese(taille_mo: float, collections: int, limite_mo: Optional[float] = None,
             limite_coll: Optional[int] = None) -> Dict[str, Any]:
    """Pourcentages, places restantes et couleurs des deux jauges + couleur et % globaux (le pire des deux)."""
    limite_mo = limite_mo or _reel("ATLAS_LIMITE_MO", LIMITE_MO_DEFAUT)
    limite_coll = limite_coll or int(_reel("ATLAS_LIMITE_COLLECTIONS", LIMITE_COLLECTIONS_DEFAUT))
    p_taille = taille_mo / limite_mo if limite_mo else 1.0
    p_coll = collections / limite_coll if limite_coll else 1.0
    pire = max(p_taille, p_coll)
    return {"taille": {"total_mo": round(taille_mo, 1), "limite_mo": limite_mo, "pourcentage": round(100 * p_taille, 1),
                       "restant_mo": round(max(0.0, limite_mo - taille_mo), 1), "niveau": niveau(p_taille)},
            "collections": {"total": collections, "limite": limite_coll, "pourcentage": round(100 * p_coll, 1),
                            "restantes": max(0, limite_coll - collections), "niveau": niveau(p_coll)},
            "pourcentage": round(100 * pire, 1), "niveau": niveau(pire)}


async def mesurer(client, base_courante: str, forcer: bool = False) -> Dict[str, Any]:
    """Mesure le cluster (gardée 10 min). → synthese() + {"bases": [{nom, mo, collections, courante}], "le", "methode"}."""
    if not forcer and _cache["mesure"] and time.monotonic() - _cache["t"] < DUREE_CACHE_S:
        return _cache["mesure"]
    methode = "cluster"
    try:
        noms = [n for n in await client.list_database_names() if n not in BASES_IGNOREES]
    except Exception:  # noqa: BLE001 — droit « listDatabases » absent : on mesure la base de la plateforme seule
        noms, methode = [base_courante], "base seule"
    bases: List[Dict[str, Any]] = []
    for nom in sorted(noms):
        try:
            st = await client[nom].command("dbStats")
            mo = (float(st.get("dataSize") or 0) + float(st.get("indexSize") or 0)) / (1024 * 1024)
        except Exception:  # noqa: BLE001 — une base illisible n'empêche pas de mesurer les autres
            mo = 0.0
        try:
            nb = len(await client[nom].list_collection_names())
        except Exception:  # noqa: BLE001
            nb = 0
        bases.append({"nom": nom, "mo": round(mo, 1), "collections": nb, "courante": nom == base_courante})
    bases.sort(key=lambda b: -b["mo"])
    m = {**synthese(sum(b["mo"] for b in bases), sum(b["collections"] for b in bases)), "bases": bases,
         "methode": methode, "le": datetime.now(timezone.utc).isoformat()}
    _cache.update(t=time.monotonic(), mesure=m)
    return m
