"""Boutons "Tester" de Paramètres > Cabinet / Paiements — reCAPTCHA et
PawaPay. Testent les valeurs SAISIES dans le formulaire (pas nécessairement
enregistrées), pour permettre à l'administrateur de vérifier ses identifiants
avant de sauvegarder.
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from albarka_auth import require_roles
from albarka_payments import PAWAPAY_HOSTS, _pawapay_str

logger = logging.getLogger("albarka.settings_tests")

router = APIRouter(prefix="/admin/settings/test", tags=["Paramètres — tests"])

# Même rôles que la lecture/écriture des Paramètres (albarka_admin_settings._ADMIN_ROLES),
# dupliqué ici pour éviter d'exposer un symbole privé entre modules.
_ADMIN_ROLES = ["superviseur", "direction", "administrateur"]


class RecaptchaTestPayload(BaseModel):
    site_key: str
    secret_key: str
    token: str


@router.post("/recaptcha")
async def test_recaptcha(
    payload: RecaptchaTestPayload, user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    """Vérifie le token du widget (rendu sur l'écran Paramètres avec la clé
    de site saisie) contre la clé secrète saisie — indépendamment de ce qui
    est enregistré en base, pour tester avant de sauvegarder."""
    if not payload.token:
        return {"success": False, "reason": "Cochez d'abord la case reCAPTCHA ci-dessus"}
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                "https://www.google.com/recaptcha/api/siteverify",
                data={"secret": payload.secret_key, "response": payload.token},
            )
            data = r.json()
            success = bool(data.get("success"))
            return {
                "success": success,
                "reason": "Clé secrète valide, vérification réussie" if success
                else (",".join(data.get("error-codes", [])) or "Échec de vérification"),
            }
    except Exception as e:  # noqa: BLE001
        logger.error("Échec test reCAPTCHA : %s", e)
        return {"success": False, "reason": f"Erreur réseau lors du test : {str(e)[:200]}"}


class PawapayTestPayload(BaseModel):
    environment: str = "sandbox"  # "sandbox" | "production"
    token: str
    country: str = "BFA"


@router.post("/pawapay")
async def test_pawapay(
    payload: PawapayTestPayload, user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    """Envoie une véritable requête /v2/paymentpage avec un montant symbolique
    (100) et un numéro de test fictif — y compris en production, à la
    demande explicite du client : c'est le seul moyen de distinguer un jeton
    invalide (AUTHENTICATION_ERROR) d'un jeton valide. Aucun paiement n'est
    jamais confirmé par un vrai client ; le lien créé n'est ni persisté ni
    communiqué — pur test de connexion/jeton."""
    if not payload.token:
        return {"success": False, "reason": "Renseignez d'abord le jeton API ci-dessus"}
    env = (payload.environment or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    deposit_id = secrets.token_urlsafe(16)
    body = {
        "depositId": deposit_id,
        "returnUrl": "https://albarka-bf.com/admin/settings",
        "country": (payload.country or "BFA").upper(),
        "amountDetails": {"amount": "100", "currency": "XOF"},
        "phoneNumber": "22670000000",
        "reason": "Test de configuration ALBARKA",
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            r = await client.post(
                f"{host}/v2/paymentpage",
                headers={"Authorization": f"Bearer {payload.token}", "Content-Type": "application/json"},
                json=body,
            )
            try:
                api_resp = r.json()
            except Exception:
                api_resp = {"raw": r.text[:300]}
    except httpx.TimeoutException:
        return {"success": False, "reason": "Délai dépassé lors de l'appel à PawaPay"}
    except Exception as e:  # noqa: BLE001
        return {"success": False, "reason": f"Erreur réseau lors du test : {str(e)[:200]}"}

    failure_reason = (api_resp or {}).get("failureReason")
    error_code = (api_resp or {}).get("errorCode") or (
        failure_reason.get("failureCode") if isinstance(failure_reason, dict) else None
    )
    if error_code == "AUTHENTICATION_ERROR" or r.status_code in (401, 403):
        return {"success": False, "reason": f"Jeton invalide pour l'environnement {env} (AUTHENTICATION_ERROR)"}
    if api_resp.get("redirectUrl"):
        return {"success": True, "reason": f"Jeton valide ({env}) — lien de test généré avec succès"}
    # Une réponse "rejetée" pour une autre raison (ex. numéro de test non
    # joignable) prouve tout de même que le jeton est accepté par PawaPay.
    return {
        "success": True,
        "reason": f"Jeton accepté par PawaPay ({env}) — réponse : "
                  f"{_pawapay_str(api_resp.get('failureReason') or api_resp.get('message') or api_resp)}",
    }
