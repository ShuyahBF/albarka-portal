"""Lot 15.1 — Règle 4 du propriétaire : le serveur ALBARKA déclare sa présence à SAWALI.

Au démarrage (après 10 s, le temps que la version « 1.N » soit calculée), puis
toutes les 5 minutes, le serveur envoie un petit signal JSON à SAWALI :
  POST https://api.sawalismartsystems.com/api/presence-logiciel
SAWALI l'affiche dans « Plateformes en temps réel → Postes Windows — versions
déployées » (en ligne si signal < 12 min).

Principes :
  - JAMAIS bloquant : tâche de fond asyncio, délai réseau 10 s, erreurs ignorées ;
  - aucun secret dans le code : l'en-tête facultatif X-Cle-Loois est lu dans la
    variable d'environnement LOOIS_SUPPORT_CLE (envoyé seulement si elle existe) ;
  - aucune donnée client dans le signal ;
  - désactivable par la variable d'environnement PRESENCE_SAWALI=0.
"""
from __future__ import annotations

import asyncio
import logging
import os
import platform
import socket
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Adresse du service de présence de SAWALI (publique, ce n'est pas un secret)
URL_PRESENCE_SAWALI = "https://api.sawalismartsystems.com/api/presence-logiciel"
# Délais : premier envoi après 10 s, puis toutes les 5 minutes ; 10 s maximum par appel
DELAI_PREMIER_ENVOI_S = 10
INTERVALLE_S = 5 * 60
DELAI_RESEAU_S = 10

# Heure de démarrage du processus (ISO UTC), fixée au chargement du module
DEMARRE_LE = datetime.now(timezone.utc).isoformat()


def presence_active() -> bool:
    """Vrai sauf si PRESENCE_SAWALI vaut 0 / non / false / off."""
    valeur = (os.environ.get("PRESENCE_SAWALI") or "1").strip().lower()
    return valeur not in ("0", "non", "false", "off", "no")


def nom_machine() -> str:
    """Nom du service Render (RENDER_SERVICE_NAME), sinon nom d'hôte de la machine."""
    nom = (os.environ.get("RENDER_SERVICE_NAME") or "").strip()
    if nom:
        return nom
    try:
        return socket.gethostname() or "inconnu"
    except Exception:  # noqa: BLE001
        return "inconnu"


def corps_signal(infos_version: dict, machine: str, demarre_le: str) -> dict:
    """Fonction pure : construit le corps JSON du signal à partir des infos de /api/version.

    infos_version : dictionnaire renvoyé par version_deploiement.infos_version
                    (clés utilisées : « version » et « deployed_at »).
    """
    infos = infos_version or {}
    return {
        "application": "ALBARKA",
        "version": str(infos.get("version") or "inconnue"),
        "deploye_le": infos.get("deployed_at"),
        "machine": machine,
        "utilisateur": "serveur",
        "site": "albarka-bf.com",
        "systeme": f"Render · Python {platform.python_version()}",
        "demarre_le": demarre_le,
    }


def entetes_signal() -> dict:
    """En-têtes HTTP : X-Cle-Loois seulement si LOOIS_SUPPORT_CLE est définie (jamais exigée)."""
    entetes = {"Content-Type": "application/json"}
    cle = (os.environ.get("LOOIS_SUPPORT_CLE") or "").strip()
    if cle:
        entetes["X-Cle-Loois"] = cle
    return entetes


async def envoyer_signal() -> None:
    """Un envoi : calcule la version (même fonction que /api/version) puis POST vers SAWALI.

    Toute erreur (base, réseau, réponse SAWALI) est ignorée : seule une ligne de journal
    de niveau « debug » est écrite.
    """
    try:
        import httpx
        from db import db as _db
        from version_deploiement import infos_version
        # Version « 1.N » et date de déploiement, exactement comme /api/version
        infos = await infos_version(_db)
        corps = corps_signal(infos, nom_machine(), DEMARRE_LE)
        # Envoi avec un délai réseau court (10 s)
        async with httpx.AsyncClient(timeout=DELAI_RESEAU_S) as client:
            await client.post(URL_PRESENCE_SAWALI, json=corps, headers=entetes_signal())
    except Exception as exc:  # noqa: BLE001 — jamais bloquant
        logger.debug("Signal de présence SAWALI non envoyé (ignoré) : %s", exc)


async def boucle_presence_sawali() -> None:
    """Boucle de fond : premier envoi après 10 s, puis un envoi toutes les 5 minutes."""
    await asyncio.sleep(DELAI_PREMIER_ENVOI_S)
    while True:
        await envoyer_signal()
        await asyncio.sleep(INTERVALLE_S)
