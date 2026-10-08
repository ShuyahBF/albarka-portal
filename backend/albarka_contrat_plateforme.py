"""Lot 21 — État du CONTRAT d'ALBARKA avec SAWALI, affiché au DG (bandeau orange puis rouge).

Demande du propriétaire (08/10/2026) : le contrat (n°, montant, prestations et services, paiements) est suivi dans
SAWALI. « 5 jours avant l'échéance, le bandeau situé en haut de la page est orange ; 5 jours après, une barre rouge
s'affiche pour le DG lui rappelant son renouvellement, sinon certains services pourraient être suspendus. »

En résumé (pour un développeur WinDev) :
  - ALBARKA demande l'état de SON contrat à SAWALI : POST <SAWALI>/api/webhook/plateforme-contrat, signé avec la clé
    de la transmission WhatsApp universelle (LILUVINE_WA_HMAC, LILUVINE_WA_EMETTEUR) : aucune nouvelle variable ;
    l'adresse est déduite de LILUVINE_WA_URL ;
  - la réponse est gardée 30 minutes en mémoire et recopiée en base (db.settings {_id: "contrat_plateforme"}) pour
    rester affichable si SAWALI est momentanément injoignable ;
  - GET /api/contrat-plateforme : le bandeau à afficher — seulement pour le DG (et le Superviseur, pour vérifier) ;
    orange de J-5 à J+4 autour de l'échéance, rouge à partir de J+5 (délais réglés dans SAWALI).
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.contrat_plateforme")

DUREE_CACHE_S = 30 * 60
ROLES_BANDEAU = {"dg", "superviseur"}
_cache: Dict[str, Any] = {"le": 0.0, "etat": None}

router = APIRouter(tags=["Contrat de la plateforme"])


def url_contrat(url_transmission: str) -> str:
    """Adresse de l'état du contrat déduite de LILUVINE_WA_URL (…/api/webhook/liluvine-send → …/plateforme-contrat)."""
    base = (url_transmission or "").strip().rstrip("/")
    return base.rsplit("/", 1)[0] + "/plateforme-contrat" if "/" in base else ""


def _date_fr(iso: Optional[str]) -> str:
    """« 2027-10-14 » → « 14/10/2027 »."""
    return "/".join(reversed(str(iso)[:10].split("-"))) if iso else ""


def _argent(v: Any, devise: str) -> str:
    """« 1 200 000 XOF »."""
    try:
        return f"{round(float(v)):,}".replace(",", " ") + f" {devise or 'XOF'}"
    except (TypeError, ValueError):
        return ""


def bandeau(etat_contrat: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Logique pure (testée) : bandeau à afficher d'après la réponse de SAWALI.
    {visible, couleur ("orange" | "rouge"), message}."""
    c = etat_contrat or {}
    etat = c.get("etat") or {}
    couleur = etat.get("couleur")
    if couleur not in ("orange", "rouge"):
        return {"visible": False, "couleur": None, "message": ""}
    numero = f" n° {c['numero']}" if c.get("numero") else ""
    jours = etat.get("jours_restants")
    du = f" Montant dû : {_argent(c.get('du'), c.get('devise'))}." if (c.get("du") or 0) > 0 else ""
    if etat.get("niveau") == "bientot":
        quand = "aujourd'hui" if jours == 0 else f"dans {jours} jour{'s' if jours and jours > 1 else ''}"
        message = (f"Votre contrat SAWALI{numero} arrive à échéance le {_date_fr(c.get('fin'))} ({quand}). "
                   f"Pensez à son renouvellement.{du}")
    elif couleur == "orange":
        message = (f"Votre contrat SAWALI{numero} est arrivé à échéance le {_date_fr(c.get('fin'))}. "
                   f"Merci de procéder à son renouvellement.{du}")
    else:
        retard = -(jours or 0)
        message = (f"Votre contrat SAWALI{numero} est échu depuis {retard} jours (le {_date_fr(c.get('fin'))}). "
                   f"Renouvelez-le, sinon certains services pourraient être suspendus.{du}")
    return {"visible": True, "couleur": couleur, "message": message}


async def lire_etat(force: bool = False) -> Optional[Dict[str, Any]]:
    """État du contrat demandé à SAWALI (cache 30 min ; repli sur la dernière réponse gardée en base)."""
    if not force and _cache["etat"] is not None and time.time() - _cache["le"] < DUREE_CACHE_S:
        return _cache["etat"]
    from albarka_transmission_wa import _config_liluvine, signer
    cfg = _config_liluvine()
    etat = None
    if cfg:
        try:
            import httpx
            corps = "{}"
            ts = str(int(time.time()))
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(url_contrat(cfg["url"]), content=corps, headers={
                    "Content-Type": "application/json", "X-Emetteur": cfg["emetteur"], "X-Timestamp": ts,
                    "X-Signature": signer(cfg["cle"], ts, corps)})
            if r.status_code == 200:
                etat = r.json()
                await db.settings.update_one({"_id": "contrat_plateforme"}, {"$set": {
                    "etat": etat, "lu_le": datetime.now(timezone.utc).isoformat()}}, upsert=True)
            else:
                logger.warning("État du contrat refusé par SAWALI (HTTP %s)", r.status_code)
        except Exception:  # noqa: BLE001 — SAWALI injoignable : dernière réponse connue
            logger.warning("SAWALI injoignable pour l'état du contrat")
    if etat is None:
        doc = await db.settings.find_one({"_id": "contrat_plateforme"}, {"_id": 0, "etat": 1}) or {}
        etat = doc.get("etat")
    _cache.update(le=time.time(), etat=etat)
    return etat


@router.get("/contrat-plateforme")
async def contrat_plateforme(user: dict = Depends(get_current_user)):
    """Bandeau du contrat pour le DG (orange autour de l'échéance, rouge au-delà) ; invisible pour les autres."""
    if not (set(user.get("roles") or []) & ROLES_BANDEAU):
        return {"visible": False, "couleur": None, "message": ""}
    etat = await lire_etat()
    return {**bandeau(etat), "fin": (etat or {}).get("fin"), "numero": (etat or {}).get("numero")}
