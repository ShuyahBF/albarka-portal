"""Lot 13 (migration Render) — planificateur interne des tâches périodiques.

Sur Emergent, deux tâches étaient lancées par son service de crons
(`.emergent/crons.yml`), qui appelait des adresses HTTP du portail :
  - rappels d'échéances fiscales (e-mail + WhatsApp), chaque jour à 07h00 UTC
    -> POST /api/cron/notify-echeances ;
  - envois WhatsApp planifiés, toutes les 5 minutes
    -> POST /api/reports/cron/dispatch-scheduled-wa.

Render n'a pas ce service : la boucle ci-dessous, lancée au démarrage du
serveur, appelle les MÊMES fonctions (même code, même contrôle). Elle ne
tourne que sur Render (variable RENDER, posée automatiquement par Render) ou
si PLANIFICATEUR_INTERNE=1 ; PLANIFICATEUR_INTERNE=0 la désactive. Ainsi,
l'ancien hébergement (Emergent) n'envoie jamais deux fois les mêmes rappels.

Elle lance aussi la sauvegarde quotidienne chiffrée de la base vers R2
(albarka_sauvegarde.py, 02h00 UTC).

Anti-doublon : le rappel quotidien est noté dans `cron_runs`
(run_id « planif-echeances-AAAA-MM-JJ ») : un redémarrage du serveur dans la
journée ne le relance pas.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("albarka.planificateur")

HEURE_RAPPELS_UTC = 7          # rappels d'échéances : chaque jour à 07h00 UTC (comme sur Emergent)
INTERVALLE_WA_SECONDES = 300   # envois WhatsApp planifiés : toutes les 5 minutes
PAS_SECONDES = 60              # la boucle se réveille chaque minute


def planificateur_actif() -> bool:
    """Vrai sur Render (ou si forcé par PLANIFICATEUR_INTERNE=1) ; jamais si PLANIFICATEUR_INTERNE=0."""
    reglage = (os.environ.get("PLANIFICATEUR_INTERNE") or "").strip()
    if reglage in ("0", "1"):
        return reglage == "1"
    return bool(os.environ.get("RENDER"))


def _autorisation() -> str:
    """En-tête attendu par les routes de cron (même secret que l'ancien service de crons)."""
    return f"Bearer {os.environ.get('WEBHOOK_CRON_SECRET', '')}"


async def lancer_rappels_echeances_du_jour(maintenant: datetime) -> bool:
    """Lance les rappels d'échéances une seule fois par jour, à partir de 07h00 UTC.
    Renvoie vrai si les rappels ont été lancés lors de cet appel."""
    from db import db
    if maintenant.hour < HEURE_RAPPELS_UTC:
        return False
    run_id = f"planif-echeances-{maintenant.date().isoformat()}"
    # Déjà fait aujourd'hui (y compris avant un redémarrage) : rien à faire
    if await db.cron_runs.find_one({"run_id": run_id}):
        return False
    await db.cron_runs.insert_one({"run_id": run_id, "job": "notify-echeances",
                                   "received_at": maintenant.isoformat(), "source": "planificateur"})
    from albarka_reports_router import _run_daily_notifications
    stats = await _run_daily_notifications()
    logger.info("Rappels d'échéances du %s : %s", maintenant.date(), stats)
    return True


async def lancer_envois_wa_planifies() -> None:
    """Exécute les envois WhatsApp planifiés arrivés à échéance (même fonction que la route de cron)."""
    from albarka_reports_mgmt import cron_dispatch_scheduled_wa
    await cron_dispatch_scheduled_wa(authorization=_autorisation(), x_webhook_id=None)


async def boucle_planificateur() -> None:
    """Boucle de fond : chaque minute, rappels du jour si dus ; toutes les 5 minutes, envois WA."""
    dernier_envoi_wa = 0.0
    while True:
        maintenant = datetime.now(timezone.utc)
        # 1) Rappels d'échéances (une fois par jour)
        try:
            await lancer_rappels_echeances_du_jour(maintenant)
        except Exception:  # noqa: BLE001 — une erreur n'arrête jamais la boucle
            logger.exception("Planificateur : rappels d'échéances en erreur")
        # 2) Sauvegarde quotidienne de la base vers R2 (une fois par jour)
        try:
            from albarka_sauvegarde import sauvegarde_du_jour
            from db import db
            await sauvegarde_du_jour(db, maintenant)
        except Exception:  # noqa: BLE001
            logger.exception("Planificateur : sauvegarde quotidienne en erreur")
        # 3) Envois WhatsApp planifiés (toutes les 5 minutes)
        horloge = asyncio.get_running_loop().time()
        if horloge - dernier_envoi_wa >= INTERVALLE_WA_SECONDES:
            dernier_envoi_wa = horloge
            try:
                await lancer_envois_wa_planifies()
            except Exception:  # noqa: BLE001
                logger.exception("Planificateur : envois WhatsApp planifiés en erreur")
        await asyncio.sleep(PAS_SECONDES)
