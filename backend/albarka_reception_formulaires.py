"""Réception des formulaires et sondages transmis par SAWALI (lot 81).

SAWALI (Liluvine) peut transmettre un formulaire ou un sondage à la plateforme ALBARKA : le document « tombe » dans
l'espace « Mes formulaires » (FORM-ALBARKA-000N), prêt à être édité, envoyé et suivi, avec la mention de sa provenance.

  POST /api/webhooks/liluvine-formulaires   (public, signé comme les retours : X-Timestamp + X-Signature,
                                             HMAC-SHA256 de « <horodatage>.<corps> » avec LILUVINE_WA_HMAC, fenêtre ± 5 min)
  Corps : {"type": "formulaire" | "sondage", "id_sawali": "...", "titre": "...", "document": {...}}

Règles :
  - idempotent : le même `id_sawali` reçu deux fois ne crée pas de doublon (réponse « deja ») ;
  - un sondage devient un formulaire (questions → champs : note → rating, NPS → échelle 0-10, texte, choix…) ;
  - un titre déjà pris dans l'espace reçoit le suffixe « (SAWALI) » ;
  - le formulaire reçu est créé FERMÉ aux réponses publiques (aucun lien public) : l'équipe le relit puis l'ouvre.
"""
from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from forms_core.fields import normalize_pages, normalize_settings
from albarka_transmission_wa import verifier_signature_retour

logger = logging.getLogger("albarka.reception_formulaires")

router = APIRouter(prefix="/webhooks", tags=["Réception des formulaires SAWALI (lot 81)"])

PREFIXE_NUMERO = "FORM-ALBARKA"        # même numérotation que le module Formulaires (albarka_forms.py)
SCOPE = "default"                      # espace unique de formulaires du cabinet (forms_core)
# type de question d'un sondage SAWALI → type de champ du module Formulaires
TYPES_SONDAGE = {"rating": "rating", "nps": "scale", "text": "text", "textarea": "textarea", "number": "number",
                 "single": "radio", "choice": "radio", "select": "select", "multiple": "checkbox", "multiselect": "multiselect",
                 "yesno": "boolean", "boolean": "boolean", "date": "date", "email": "email", "tel": "tel"}


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def pages_depuis_document(type_doc: str, document: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pages du formulaire à créer (fonction pure). Un formulaire garde ses pages ; un sondage devient une page de champs."""
    if type_doc == "formulaire" and isinstance(document.get("pages"), list):
        brut = []
        for p in document["pages"]:
            champs = []
            for f in (p or {}).get("fields") or []:
                f = dict(f or {})
                if f.get("type") == "location":        # pas d'équivalent : texte libre
                    f["type"] = "text"
                champs.append(f)
            brut.append({**(p or {}), "fields": champs})
        return normalize_pages(brut)
    champs = []
    for q in document.get("questions") or []:
        q = q or {}
        champs.append({"id": q.get("id"), "type": TYPES_SONDAGE.get(str(q.get("type") or "text"), "text"),
                       "label": q.get("label") or q.get("text") or "Question", "help": q.get("help") or "",
                       "required": bool(q.get("required")), "options": q.get("options") or []})
    return normalize_pages([{"id": "p1", "title": "Questions", "fields": champs}])


async def _numero_suivant(base) -> str:
    """Numéro FORM-ALBARKA-000N, par le même compteur que le module Formulaires (collection forms_counters, clé « default »)."""
    doc = await base["forms_counters"].find_one_and_update({"_id": SCOPE}, {"$inc": {"value": 1}}, upsert=True, return_document=True)
    if not isinstance(doc, dict) or "value" not in doc:
        doc = await base["forms_counters"].find_one({"_id": SCOPE})
    return f"{PREFIXE_NUMERO}-{int(doc['value']):04d}"


async def creer_formulaire(base, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Crée (une seule fois) le formulaire reçu ; renvoie {ok, number, deja}."""
    type_doc = str(corps.get("type") or "").strip()
    document = corps.get("document") if isinstance(corps.get("document"), dict) else {}
    id_sawali = str(corps.get("id_sawali") or "").strip()
    titre = str(corps.get("titre") or document.get("title") or "").strip()[:190]
    if type_doc not in ("formulaire", "sondage") or not id_sawali or not titre:
        return {"ok": False, "erreur": "type, id_sawali et titre requis"}
    forms = base["forms"]
    existant = await forms.find_one({"source.id_sawali": id_sawali}, {"_id": 0, "number": 1, "id": 1})
    if existant:
        return {"ok": True, "deja": True, "number": existant["number"]}
    if await forms.find_one({"scope": SCOPE, "archived_at": None, "title": {"$regex": f"^{__import__('re').escape(titre)}$", "$options": "i"}}, {"_id": 1}):
        titre = f"{titre} (SAWALI)"
    maintenant = _maintenant()
    reglages = normalize_settings({"accepting_responses": False,
                                   "confirmation_message": document.get("thank_you") or None})
    forme = {
        "id": secrets.token_hex(8), "scope": SCOPE, "number": await _numero_suivant(base), "title": titre,
        "description": str(document.get("description") or "").strip()[:2000], "category_id": None,
        "pages": pages_depuis_document(type_doc, document), "settings": reglages,
        "public_link": {"enabled": False, "token": None}, "views": 0, "submissions_count": 0,
        "source": {"plateforme": "SAWALI", "type": type_doc, "id_sawali": id_sawali, "recu_le": maintenant},
        "created_by_id": None, "created_by_label": "SAWALI (transmission)", "created_at": maintenant, "updated_at": maintenant,
        "archived_at": None,
    }
    await forms.insert_one(dict(forme))
    return {"ok": True, "deja": False, "number": forme["number"]}


@router.post("/liluvine-formulaires")
async def recevoir_formulaire(request: Request):
    """Point d'entrée signé : un formulaire ou un sondage de SAWALI arrive dans « Mes formulaires »."""
    corps_brut = await request.body()
    motif = verifier_signature_retour(request.headers.get("X-Timestamp"), request.headers.get("X-Signature"), corps_brut)
    if motif:
        return JSONResponse(status_code=503 if motif == "Transmission non configurée" else 401, content={"detail": motif})
    try:
        corps = json.loads(corps_brut.decode("utf-8"))
    except ValueError:
        return JSONResponse(status_code=422, content={"detail": "JSON invalide"})
    if not isinstance(corps, dict):
        return JSONResponse(status_code=422, content={"detail": "Objet JSON attendu"})
    try:
        import db as db_module
        res = await creer_formulaire(db_module.db, corps)
    except Exception:  # noqa: BLE001 — SAWALI réessaiera
        logger.warning("Réception d'un formulaire SAWALI en échec", exc_info=True)
        return JSONResponse(status_code=500, content={"detail": "Erreur interne"})
    if not res.get("ok"):
        return JSONResponse(status_code=422, content={"detail": res.get("erreur")})
    return res
