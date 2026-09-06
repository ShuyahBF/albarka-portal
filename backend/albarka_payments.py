"""Module Paiements — liens de paiement mobile money (PawaPay), réservé au
rôle "caissier".

Porté depuis ShuyahBF/Emergent (server.py, section "PawaPay — mobile money
deposit flow") : même construction de la requête PawaPay v2 /paymentpage
(host sandbox/production, correspondants Orange/Moov/Telecel, devise par
pays, gestion de la réponse) — adaptée pour ALBARKA sur un point clé :
côté référence, c'est le CLIENT qui initie son propre paiement depuis son
portail ; ici c'est le collaborateur "caissier" qui génère un lien AU NOM
d'un client choisi, pour le lui transmettre (WhatsApp/email/copier-coller).
"""
from __future__ import annotations

import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from albarka_admin_settings import get_settings_doc
from albarka_auth import require_roles
from albarka_models import PAYMENTS_ROLES, whatsapp_number_of
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.payments")

router = APIRouter(prefix="/payments", tags=["Paiements"])
webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])

PAWAPAY_HOSTS = {
    "sandbox": "https://api.sandbox.pawapay.io",
    "production": "https://api.pawapay.io",
}

# UEMOA (zone franc CFA BCEAO) partagent le XOF ; le module est pour
# l'instant scopé au Burkina Faso (BFA) comme le reste d'ALBARKA, la table
# reste facilement extensible à d'autres pays de la zone plus tard.
_PAWAPAY_CURRENCY_BY_COUNTRY = {"BFA": "XOF", "BEN": "XOF", "CIV": "XOF", "SEN": "XOF", "TGO": "XOF", "MLI": "XOF", "NER": "XOF"}
_PAWAPAY_CORRESPONDENTS = {
    "BFA": {"ORANGE": "ORANGE_BFA", "MOOV": "MOOV_BFA", "TELECEL": "TELECEL_BFA"},
}


def _pawapay_str(field: Any) -> Optional[str]:
    """PawaPay v2 renvoie parfois failureReason/rejectionReason comme un
    objet {code, message} plutôt qu'une chaîne — toujours restituer une
    chaîne imprimable, jamais un objet brut."""
    if field is None:
        return None
    if isinstance(field, str):
        return field
    if isinstance(field, dict):
        msg = field.get("failureMessage") or field.get("rejectionMessage") or field.get("message")
        code = field.get("failureCode") or field.get("rejectionCode") or field.get("code")
        if msg and code:
            return f"{code} — {msg}"
        return msg or code or str(field)[:300]
    return str(field)[:300]


def _active_token(s: Dict[str, Any]) -> Optional[str]:
    env = (s.get("pawapay_environment") or "sandbox").lower()
    if env == "production":
        return s.get("pawapay_api_token_production")
    return s.get("pawapay_api_token_sandbox")


def _currency_for_country(country: str) -> str:
    return _PAWAPAY_CURRENCY_BY_COUNTRY.get((country or "BFA").upper(), "XOF")


class PaymentLinkCreate(BaseModel):
    tenant_id: str
    amount: float = Field(..., gt=0)
    # Optionnel — préremplit le numéro sur la page hébergée PawaPay ; laissé
    # vide, le client le saisit lui-même.
    msisdn: Optional[str] = None
    reason: Optional[str] = Field(None, max_length=50)


@router.post("/pawapay/link")
async def create_payment_link(
    payload: PaymentLinkCreate, request: Request, user: dict = Depends(require_roles(PAYMENTS_ROLES)),
):
    s = await get_settings_doc()
    if not s.get("pawapay_enabled"):
        raise HTTPException(status_code=503, detail="PawaPay non activé dans les paramètres")
    token = _active_token(s)
    if not token:
        raise HTTPException(status_code=503, detail="Jeton API PawaPay non configuré")

    client = await db.users.find_one({"id": payload.tenant_id}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")

    country = (s.get("pawapay_country") or "BFA").upper()
    env = (s.get("pawapay_environment") or "sandbox").lower()
    host = PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS["sandbox"])
    deposit_id = secrets.token_urlsafe(16)

    msisdn_candidate = (payload.msisdn or whatsapp_number_of(client) or "").strip()
    msisdn_final = "".join(ch for ch in msisdn_candidate if ch.isdigit()) or None
    if msisdn_final and len(msisdn_final) < 8:
        msisdn_final = None  # trop court pour être fiable — laisser PawaPay le collecter

    origin = request.headers.get("origin") or "https://albarka-bf.com"
    return_url = f"{origin.rstrip('/')}/admin/paiements?depositId={deposit_id}"

    body: Dict[str, Any] = {
        "depositId": deposit_id,
        "returnUrl": return_url,
        "country": country,
        "amountDetails": {
            "amount": str(int(payload.amount)) if float(payload.amount).is_integer() else f"{payload.amount:.2f}",
            "currency": _currency_for_country(country),
        },
    }
    if msisdn_final:
        body["phoneNumber"] = msisdn_final
    if payload.reason:
        body["reason"] = payload.reason[:50]

    # Persisté AVANT l'appel PawaPay (best-practice PawaPay) : le lien reste
    # traçable même en cas d'erreur réseau.
    link_doc = {
        "id": secrets.token_urlsafe(12),
        "deposit_id": deposit_id,
        "tenant_id": payload.tenant_id,
        "client_label": client.get("company") or client.get("full_name"),
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "amount": payload.amount,
        "currency": _currency_for_country(country),
        "country": country,
        "msisdn": msisdn_final,
        "reason": payload.reason,
        "environment": env,
        "status": "initiated",
        "api_status": None,
        "api_message": None,
        "return_url": return_url,
        "redirect_url": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.payment_links.insert_one(link_doc.copy())

    try:
        async with httpx.AsyncClient(timeout=20) as http_client:
            r = await http_client.post(
                f"{host}/v2/paymentpage",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=body,
            )
            try:
                api_resp = r.json()
            except Exception:
                api_resp = {"raw": r.text[:500]}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {str(exc)[:200]}") from exc

    redirect_url = (api_resp or {}).get("redirectUrl")
    if not redirect_url:
        await db.payment_links.update_one(
            {"deposit_id": deposit_id},
            {"$set": {
                "status": "failed",
                "api_message": _pawapay_str(api_resp.get("failureReason") or api_resp.get("message") or api_resp),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
        )
        raise HTTPException(
            status_code=502,
            detail=_pawapay_str(api_resp.get("failureReason") or api_resp.get("message"))
            or "PawaPay n'a pas renvoyé de lien de paiement.",
        )

    await db.payment_links.update_one(
        {"deposit_id": deposit_id},
        {"$set": {"redirect_url": redirect_url, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "deposit_id": deposit_id, "redirect_url": redirect_url}


@router.get("")
async def list_payment_links(
    tenant_id: Optional[str] = None, limit: int = 200, user: dict = Depends(require_roles(PAYMENTS_ROLES)),
):
    q: Dict[str, Any] = {}
    if tenant_id:
        q["tenant_id"] = tenant_id
    items = await db.payment_links.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


# ---------------------------------------------------------------------
# Webhook PawaPay — statut du paiement (public, protégé par secret d'URL)
# ---------------------------------------------------------------------
@webhook_router.post("/pawapay/{secret}")
async def pawapay_webhook(secret: str, request: Request):
    s = await get_settings_doc()
    expected = (s.get("pawapay_callback_secret") or "").strip()
    if not expected or secret != expected:
        raise HTTPException(status_code=403, detail="Secret invalide")
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    deposit_id = payload.get("depositId") or payload.get("deposit_id")
    if not deposit_id:
        return {"ok": False, "reason": "depositId manquant"}
    api_status = (payload.get("status") or "").upper()
    new_status = {
        "COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed",
        "ACCEPTED": "pending", "PROCESSING": "pending", "SUBMITTED": "pending", "PENDING": "pending",
    }.get(api_status, "pending")
    await db.payment_links.update_one(
        {"deposit_id": deposit_id},
        {"$set": {
            "status": new_status,
            "api_status": api_status,
            "api_message": _pawapay_str(payload.get("failureReason") or payload.get("rejectionReason")),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {"ok": True, "deposit_id": deposit_id, "status": new_status}
