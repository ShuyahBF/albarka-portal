"""Retour vers SAWALI des RÉPONSES aux formulaires et sondages reçus de SAWALI (lot 82).

Un formulaire ou sondage transmis par SAWALI (lot 81) garde sa provenance (`source.id_sawali`). Les réponses qu'il reçoit dans ALBARKA
sont renvoyées à SAWALI, qui les range dans sa copie du document, sous le nom de la plateforme (« ALBARKA »). Les réponses RESTENT
aussi dans ALBARKA : le retour n'enlève rien.

  POST {SAWALI}/api/webhook/plateforme-reponse-formulaire   (signé : X-Emetteur, X-Timestamp, X-Signature = HMAC-SHA256 de « <ts>.<corps> »)
  Corps : {"type", "id_sawali", "reponse_id", "recu_le", "repondant": {"nom", "email"}, "data": {id du champ: valeur}}

Adresse de SAWALI : celle de LILUVINE_WA_URL (déjà saisie pour la transmission universelle), coupée avant « /api/ » ; aucune variable de plus.
Principe « boîte d'envoi » : une réponse non encore transmise porte l'absence du champ `sawali_envoye_le` ; le planificateur (chaque minute)
transmet celles en attente. Une panne réseau ou un refus 5xx laisse la réponse en attente (nouvel essai à la minute suivante) ; un refus 4xx
(signature, document inconnu) est noté (`sawali_erreur`) et n'est pas rejoué. SAWALI est idempotent (même `reponse_id` = jamais de doublon).
Les fichiers joints et signatures ne sont pas transmis : seules les valeurs saisies le sont.
"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

from albarka_transmission_wa import _config_liluvine, signer

logger = logging.getLogger("albarka.retour_reponses")

CHEMIN_SAWALI = "/api/webhook/plateforme-reponse-formulaire"
LOT_PAR_PASSAGE = 50            # réponses transmises au plus à chaque passage du planificateur
DELAI_SECONDES = 15


def url_sawali() -> Optional[str]:
    """Adresse du point d'entrée de SAWALI (déduite de LILUVINE_WA_URL), ou None si la transmission universelle n'est pas configurée."""
    cfg = _config_liluvine()
    if not cfg:
        return None
    base = cfg["url"].split("/api/")[0].rstrip("/")
    return base + CHEMIN_SAWALI if base.startswith("http") else None


def corps_reponse(form: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    """Corps envoyé à SAWALI pour une réponse (fonction pure)."""
    source = form.get("source") or {}
    return {"type": source.get("type") or "formulaire", "id_sawali": source.get("id_sawali"), "reponse_id": sub.get("id"),
            "recu_le": sub.get("created_at"),
            "repondant": {"nom": sub.get("respondent_name"), "email": sub.get("respondent_email")},
            "data": sub.get("data") or {}}


async def _poster(cfg: Dict[str, str], url: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """POST signé ; renvoie {ok, definitif, erreur}. Jamais d'exception."""
    brut = json.dumps(corps, ensure_ascii=False, separators=(",", ":"), default=str)
    horodatage = str(int(time.time()))
    entetes = {"Content-Type": "application/json", "X-Emetteur": cfg["emetteur"], "X-Timestamp": horodatage,
               "X-Signature": signer(cfg["cle"], horodatage, brut)}
    try:
        async with httpx.AsyncClient(timeout=DELAI_SECONDES) as client:
            rep = await client.post(url, content=brut.encode("utf-8"), headers=entetes)
    except httpx.HTTPError as exc:
        return {"ok": False, "definitif": False, "erreur": f"SAWALI injoignable ({type(exc).__name__})"}
    if rep.status_code < 300:
        return {"ok": True, "definitif": True, "erreur": None}
    return {"ok": False, "definitif": rep.status_code < 500, "erreur": f"refusé par SAWALI (HTTP {rep.status_code})"}


async def envoyer_reponses_en_attente(base) -> Dict[str, int]:
    """Transmet à SAWALI les réponses en attente. Renvoie {envoyees, en_attente, refusees}."""
    bilan = {"envoyees": 0, "en_attente": 0, "refusees": 0}
    cfg, url = _config_liluvine(), url_sawali()
    if not cfg or not url:
        return bilan
    formes = {f["id"]: f async for f in base["forms"].find({"source.id_sawali": {"$exists": True}}, {"_id": 0, "id": 1, "source": 1})}
    if not formes:
        return bilan
    en_attente = base["forms_submissions"].find(
        {"form_id": {"$in": list(formes)}, "sawali_envoye_le": {"$exists": False}, "sawali_erreur": {"$exists": False}},
        {"_id": 0}).sort("created_at", 1)
    for sub in await en_attente.to_list(LOT_PAR_PASSAGE):
        res = await _poster(cfg, url, corps_reponse(formes[sub["form_id"]], sub))
        if res["ok"]:
            await base["forms_submissions"].update_one({"id": sub["id"]}, {"$set": {"sawali_envoye_le": datetime.now(timezone.utc).isoformat()}})
            bilan["envoyees"] += 1
        elif res["definitif"]:
            await base["forms_submissions"].update_one({"id": sub["id"]}, {"$set": {"sawali_erreur": res["erreur"]}})
            bilan["refusees"] += 1
            logger.warning("Retour de réponse refusé par SAWALI (%s) : %s", sub["id"], res["erreur"])
        else:
            bilan["en_attente"] += 1
            break                                  # SAWALI injoignable : inutile d'insister sur toutes les réponses, on réessaie à la minute suivante
    return bilan
