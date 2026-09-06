"""Vérification Google reCAPTCHA v2 sur la page de connexion, pilotée par
les paramètres admin (recaptcha_enabled / recaptcha_site_key /
recaptcha_secret_key — voir albarka_admin_settings.py).

Portage du module recaptcha.py de l'application de référence
(ShuyahBF/Emergent), à la demande explicite du client : la fonctionnalité et
ses réglages existaient déjà pour la page de login de cette base et doivent
être réutilisés tels quels plutôt que reconstruits.

Accès direct à `db.settings` (et non via albarka_admin_settings.get_settings_doc)
pour éviter un import circulaire : albarka_admin_settings importe déjà
albarka_auth, qui importe ce module.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

from db import db

logger = logging.getLogger("albarka.recaptcha")


async def get_captcha_config() -> dict:
    """Configuration publique exposée à la page de connexion (jamais le secret)."""
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("recaptcha_enabled") and s.get("recaptcha_site_key"))
    return {"enabled": enabled, "site_key": s.get("recaptcha_site_key") if enabled else None}


async def verify_recaptcha(token: Optional[str]) -> dict:
    """Retourne {success, enabled, reason}.

    success=True sans appel réseau si le captcha est désactivé côté
    paramètres (recaptcha_enabled=False ou recaptcha_secret_key vide).
    """
    s = await db.settings.find_one({"_id": "global"}) or {}
    enabled = bool(s.get("recaptcha_enabled") and s.get("recaptcha_secret_key"))
    if not enabled:
        return {"success": True, "enabled": False, "reason": "reCAPTCHA désactivé"}

    if not token:
        return {"success": False, "enabled": True, "reason": "Captcha manquant"}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={"secret": s["recaptcha_secret_key"], "response": token},
            )
            data = r.json()
            return {
                "success": bool(data.get("success")),
                "enabled": True,
                "reason": ",".join(data.get("error-codes", [])) or "ok",
            }
    except Exception as e:
        logger.error("Échec vérification reCAPTCHA : %s", e)
        return {"success": False, "enabled": True, "reason": "Erreur de vérification captcha"}
