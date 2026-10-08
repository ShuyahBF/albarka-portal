"""Lot 22 — SERVICES SUSPENDUS automatiquement quand le contrat SAWALI est échu.

Demande du propriétaire (08/10/2026) : « Implémente les services pouvant être suspendus. Je coche ou décoche (CR, WA,
etc.). Tous ceux qui sont cochés seront suspendus automatiquement. »

En résumé (pour un développeur WinDev) :
  - les cases sont cochées dans SAWALI, sur le contrat de la plateforme ; SAWALI renvoie, dans l'état signé du contrat
    (albarka_contrat_plateforme.lire_etat), la liste « services_suspendus » : VIDE tant que le contrat n'est pas échu,
    remplie au-delà de J+5 (délai réglé dans SAWALI), de nouveau vide dès que l'échéance est repoussée ;
  - chaque CODE correspond ici à des fonctions d'ALBARKA :
      * « wa » et « email » : bloqués au plus bas niveau (envoi Meta, transmission universelle, SMTP), sauf les codes
        de connexion (routes /api/auth et /api/staff-pin) pour que personne ne soit enfermé dehors ;
      * « ia » : l'analyse des pièces renvoie une erreur claire (la pièce reste déposée) ;
      * les autres : toutes les routes de leur module répondent 423 « Service suspendu… » (middleware, server.py) ;
  - jamais bloqués : connexion, version, santé, état du contrat, webhooks entrants (messages WhatsApp reçus,
    notifications PI-SPI…) et tâches planifiées système ;
  - aucune attente : le middleware lit l'état gardé en mémoire et le fait rafraîchir en arrière-plan s'il est ancien.
"""
from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from typing import Dict, List, Optional

logger = logging.getLogger("albarka.suspension")

# Code (partagé avec SAWALI) → libellé affiché et débuts de chemins des routes bloquées
SERVICES: Dict[str, Dict] = {
    "wa": {"libelle": "WhatsApp (envois)", "chemins": []},                       # bloqué à l'envoi
    "email": {"libelle": "E-mails (envois)", "chemins": []},                     # bloqué à l'envoi
    "cr": {"libelle": "Comptes rendus / rapports clients", "chemins": ["/api/reports", "/api/report-templates"]},
    "conversations_wa": {"libelle": "Conversations WhatsApp", "chemins": ["/api/whatsapp"]},
    "ia": {"libelle": "Analyse IA (OCR) des pièces", "chemins": ["/api/documents/ocr-"]},  # + blocage de l'analyse
    "espace_client": {"libelle": "Espace client", "chemins": ["/api/client-space", "/api/me/space"]},
    "formulaires": {"libelle": "Formulaires", "chemins": ["/api/forms", "/api/public/forms", "/api/me/forms"]},
    "pispi": {"libelle": "Encaissement PI-SPI", "chemins": ["/api/admin/pispi"]},
    "modeles": {"libelle": "Documents & modèles", "chemins": ["/api/letters"]},
    "paie": {"libelle": "RH & Paie", "chemins": ["/api/hr/paie", "/api/hr/payroll"]},
    "compta": {"libelle": "Comptabilité OHADA", "chemins": ["/api/accounting"]},
    "chat": {"libelle": "Chat interne", "chemins": ["/api/chat"]},
    "push": {"libelle": "Notifications push", "chemins": ["/api/push"]},
}

# Chemins JAMAIS bloqués (connexion, état, webhooks entrants…)
TOUJOURS_OUVERTS = ("/api/auth", "/api/staff-pin", "/api/version", "/api/health", "/api/contrat-plateforme",
                    "/api/services-suspendus")
# Envois WA / e-mail toujours permis depuis ces routes (codes de connexion, PIN)
ENVOIS_TOUJOURS_PERMIS = ("/api/auth", "/api/staff-pin")

# Chemin de la requête en cours (rempli par le middleware de server.py ; "" hors requête)
_chemin: ContextVar[str] = ContextVar("albarka_suspension_chemin", default="")


def noter_chemin(chemin: str) -> None:
    """Retient le chemin de la requête en cours (pour laisser passer les codes de connexion)."""
    _chemin.set(chemin or "")


def libelle(code: str) -> str:
    """Libellé lisible d'un code de service."""
    return (SERVICES.get(code) or {}).get("libelle") or code


def message_suspension(code: str) -> str:
    """Message clair affiché à l'utilisateur."""
    return (f"Service « {libelle(code)} » suspendu : le contrat SAWALI de la plateforme est échu. "
            "Le Directeur Général doit procéder à son renouvellement pour le rétablir.")


# =====================================================================================
# Logique pure (testée : tests/test_lot22_services_suspendus.py)
# =====================================================================================

def suspendus_dans(etat_contrat: Optional[dict]) -> List[str]:
    """Codes suspendus d'après la réponse de SAWALI (codes inconnus ignorés)."""
    return [c for c in ((etat_contrat or {}).get("services_suspendus") or []) if c in SERVICES]


def service_du_chemin(chemin: str, suspendus: List[str]) -> Optional[str]:
    """Code du service suspendu qui couvre ce chemin d'API, ou None (chemin libre)."""
    if not suspendus or not chemin.startswith("/api/") or chemin.startswith(TOUJOURS_OUVERTS) or "/webhook" in chemin:
        return None
    for code in suspendus:
        for debut in SERVICES[code]["chemins"]:
            if chemin == debut or chemin.startswith(debut if debut.endswith("-") else debut + "/") or chemin.startswith(debut + "?"):
                return code
    return None


# =====================================================================================
# État courant (sans jamais faire attendre une requête)
# =====================================================================================

_rafraichissement: Dict[str, Optional[asyncio.Task]] = {"tache": None}


async def suspendus_actuels() -> List[str]:
    """Services suspendus maintenant : état gardé en mémoire (ou en base au démarrage) ; s'il a plus de 30 min, il
    est redemandé à SAWALI EN ARRIÈRE-PLAN (la requête en cours n'attend pas)."""
    import time
    import albarka_contrat_plateforme as cp
    cache = cp._cache
    if cache["etat"] is None and not cache["le"]:
        try:   # premier appel depuis le démarrage : dernière réponse gardée en base
            doc = await cp.db.settings.find_one({"_id": "contrat_plateforme"}, {"_id": 0, "etat": 1}) or {}
            cache["etat"] = doc.get("etat")
        except Exception:  # noqa: BLE001 — base illisible : rien de suspendu
            return []
    if time.time() - cache["le"] >= cp.DUREE_CACHE_S:
        tache = _rafraichissement["tache"]
        if tache is None or tache.done():
            try:
                _rafraichissement["tache"] = asyncio.get_running_loop().create_task(cp.lire_etat(force=True))
            except RuntimeError:
                pass
    return suspendus_dans(cache["etat"])


async def refus_envoi(code: str) -> Optional[str]:
    """Message de refus si l'envoi (« wa » ou « email ») est suspendu ; None sinon (codes de connexion permis)."""
    if _chemin.get().startswith(ENVOIS_TOUJOURS_PERMIS):
        return None
    try:
        if code in await suspendus_actuels():
            logger.warning("Envoi %s refusé : service suspendu (contrat SAWALI échu)", code)
            return message_suspension(code)
    except Exception:  # noqa: BLE001 — en cas de doute, on n'empêche pas l'envoi
        logger.exception("Lecture des services suspendus impossible")
    return None
