"""Lot 90 — « Mes Services Web » : frais des services web du cabinet, rappelés au DG.

QUI FAIT QUOI (demande du propriétaire, 13/11/2026)
   - Le SUPER-ADMIN (rôle « superviseur ») crée et configure les services (nom, montant, payable avant le) et met à jour
     les informations de paiement (date/heure du dernier paiement, montant, référence de la transaction).
   - Le DG (rôle « dg ») est le SEUL à voir la liste (menu « Mes Services Web ») et à être rappelé : 7 jours avant,
     3 jours avant et le jour même, dans une fenêtre qu'il ferme uniquement par « J'ai compris ».
     Les services en retard (non payés après l'échéance) sont rappelés chaque jour jusqu'au paiement.
   - Ni la Direction, ni le super-admin n'ont la vue DG (le super-admin a son écran de configuration dans Paramètres).

ROUTES (sous /api)
   GET    /me/services-web                    — DG : liste avec état (à jour, dans N jours, en retard) et dernier paiement
   GET    /me/services-web/rappels            — DG : rappels à acquitter maintenant
   POST   /me/services-web/rappels/ack        — DG : « j'ai compris » (enregistre l'acquittement)
   GET    /admin/services-web                 — super-admin : liste de configuration
   POST   /admin/services-web                 — super-admin : créer un service
   PUT    /admin/services-web/{id}            — super-admin : modifier (nom, montant, échéance)
   POST   /admin/services-web/{id}/paiement   — super-admin : enregistrer le dernier paiement (date/heure, montant, référence)
   DELETE /admin/services-web/{id}            — super-admin : supprimer

DÉCISIONS
   - Collection `services_web` (quelques documents seulement). L'acquittement du DG est gardé dans le document du service
     (`acquittements`, clés « échéance:palier ») : une nouvelle échéance donne de nouveaux rappels.
   - Un service « payé pour cette échéance » (`paye_echeance`) n'est plus rappelé ; changer l'échéance remet l'indicateur à faux.
   - Jours restants calculés sur la date du jour (UTC = heure du Burkina).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.services_web")

router = APIRouter(tags=["Services Web"])

PALIERS_RAPPEL = (7, 3, 0)          # jours avant l'échéance où le DG est rappelé (0 = le jour même)
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------- droits
def _exiger_dg(user: dict) -> None:
    """Vue et rappels : le DG UNIQUEMENT (ni le super-admin, ni la Direction)."""
    if "dg" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au DG")


def _exiger_super_admin(user: dict) -> None:
    """Création, configuration et paiements : le super-admin (rôle « superviseur ») UNIQUEMENT."""
    if "superviseur" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au super-admin")


# ---------------------------------------------------------------- modèles
class ServiceCorps(BaseModel):
    service: str = Field(..., min_length=1, max_length=120)
    montant: float = Field(..., ge=0)
    devise: str = Field(default="FCFA", max_length=8)
    payable_avant: str                      # AAAA-MM-JJ


class ServiceModif(BaseModel):
    service: Optional[str] = Field(None, min_length=1, max_length=120)
    montant: Optional[float] = Field(None, ge=0)
    devise: Optional[str] = Field(None, max_length=8)
    payable_avant: Optional[str] = None


class PaiementCorps(BaseModel):
    paye_le: str                            # date/heure ISO (ex. 2026-11-12T14:30)
    montant: float = Field(..., ge=0)
    reference: str = Field(..., min_length=1, max_length=120)
    echeance_reglee: bool = True            # ce paiement règle-t-il l'échéance en cours (plus de rappel) ?


class AckCorps(BaseModel):
    cles: List[str] = Field(..., min_length=1, max_length=50)


# ---------------------------------------------------------------- calculs (logique pure, testée)
def _date_valide(texte: str) -> str:
    if not _DATE_RE.match(texte or ""):
        raise HTTPException(status_code=422, detail="Date attendue au format AAAA-MM-JJ")
    try:
        date.fromisoformat(texte)
    except ValueError:
        raise HTTPException(status_code=422, detail="Date invalide")
    return texte


def aujourdhui() -> date:
    return datetime.now(timezone.utc).date()


def etat_service(doc: dict, jour: Optional[date] = None) -> dict:
    """Jours restants et état : « paye » (échéance réglée), « a_jour » (échéance éloignée), « bientot » (≤ 7 jours),
    « aujourdhui » (échéance ce jour), « en_retard » (échéance passée et non réglée)."""
    jour = jour or aujourdhui()
    restants = (date.fromisoformat(doc["payable_avant"]) - jour).days
    if doc.get("paye_echeance"):
        etat = "paye"
    elif restants < 0:
        etat = "en_retard"
    elif restants == 0:
        etat = "aujourdhui"
    elif restants <= max(PALIERS_RAPPEL):
        etat = "bientot"
    else:
        etat = "a_jour"
    return {"jours_restants": restants, "etat": etat, "en_retard": etat == "en_retard"}


def palier_courant(doc: dict, jour: Optional[date] = None) -> Optional[str]:
    """Palier de rappel à afficher aujourd'hui : « 7 » (de 7 à 4 jours), « 3 » (de 3 à 1 jour), « 0 » (jour même),
    « retard-AAAA-MM-JJ » (chaque jour de retard) ; None si rien à rappeler (payé ou échéance lointaine)."""
    jour = jour or aujourdhui()
    e = etat_service(doc, jour)
    if e["etat"] in ("paye", "a_jour"):
        return None
    r = e["jours_restants"]
    if r < 0:
        return f"retard-{jour.isoformat()}"
    if r == 0:
        return "0"
    return "3" if r <= 3 else "7"


def _vue(doc: dict, jour: Optional[date] = None) -> dict:
    """Un service tel qu'affiché (jamais les acquittements internes)."""
    sortie = {k: doc.get(k) for k in ("id", "service", "montant", "devise", "payable_avant", "paye_echeance",
                                      "dernier_paiement_le", "dernier_paiement_montant", "dernier_paiement_reference")}
    sortie.update(etat_service(doc, jour))
    return sortie


def rappels_a_afficher(docs: List[dict], jour: Optional[date] = None) -> List[dict]:
    """Rappels non encore acquittés par le DG pour le palier du jour (une clé « échéance:palier » par service)."""
    sortie = []
    for d in docs:
        palier = palier_courant(d, jour)
        if palier is None:
            continue
        cle = f"{d['payable_avant']}:{palier}"
        if cle in (d.get("acquittements") or []):
            continue
        v = _vue(d, jour)
        v["cle"] = cle
        v["palier"] = palier
        sortie.append(v)
    sortie.sort(key=lambda x: x["jours_restants"])
    return sortie


async def _tous() -> List[dict]:
    return await db.services_web.find({}, {"_id": 0}).sort("payable_avant", 1).to_list(500)


# ---------------------------------------------------------------- DG
@router.get("/me/services-web")
async def mes_services_web(user: dict = Depends(get_current_user)):
    """Liste des services web du cabinet avec échéance, état et dernier paiement (lecture seule)."""
    _exiger_dg(user)
    jour = aujourdhui()
    return {"services": [_vue(d, jour) for d in await _tous()]}


@router.get("/me/services-web/rappels")
async def mes_rappels(user: dict = Depends(get_current_user)):
    """Rappels à acquitter maintenant (fenêtre « J'ai compris » à l'ouverture du portail)."""
    _exiger_dg(user)
    return {"rappels": rappels_a_afficher(await _tous())}


@router.post("/me/services-web/rappels/ack")
async def acquitter(payload: AckCorps, user: dict = Depends(get_current_user)):
    """« J'ai compris » : enregistre l'acquittement des rappels affichés (clés « échéance:palier » valides seulement)."""
    _exiger_dg(user)
    docs = await _tous()
    valides = {f"{d['payable_avant']}:{palier_courant(d)}": d["id"] for d in docs if palier_courant(d)}
    for cle in payload.cles:
        sid = valides.get(cle)
        if sid:
            await db.services_web.update_one({"id": sid}, {"$addToSet": {"acquittements": cle}})
    return {"ok": True}


# ---------------------------------------------------------------- super-admin
@router.get("/admin/services-web")
async def admin_liste(user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    jour = aujourdhui()
    return {"services": [_vue(d, jour) for d in await _tous()]}


@router.post("/admin/services-web")
async def admin_creer(payload: ServiceCorps, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    doc = {
        "id": str(uuid.uuid4()), "service": payload.service.strip(), "montant": payload.montant,
        "devise": (payload.devise or "FCFA").strip() or "FCFA", "payable_avant": _date_valide(payload.payable_avant),
        "paye_echeance": False, "dernier_paiement_le": None, "dernier_paiement_montant": None,
        "dernier_paiement_reference": None, "acquittements": [], "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.services_web.insert_one(dict(doc))
    return _vue(doc)


@router.put("/admin/services-web/{service_id}")
async def admin_modifier(service_id: str, payload: ServiceModif, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service introuvable")
    maj = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if "service" in maj:
        maj["service"] = maj["service"].strip()
    if "payable_avant" in maj:
        maj["payable_avant"] = _date_valide(maj["payable_avant"])
        if maj["payable_avant"] != doc["payable_avant"]:
            maj["paye_echeance"] = False          # nouvelle échéance : à régler de nouveau
    if maj:
        await db.services_web.update_one({"id": service_id}, {"$set": maj})
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


@router.post("/admin/services-web/{service_id}/paiement")
async def admin_paiement(service_id: str, payload: PaiementCorps, user: dict = Depends(get_current_user)):
    """Enregistre le dernier paiement (date/heure, montant, référence) ; par défaut il règle l'échéance en cours."""
    _exiger_super_admin(user)
    try:
        datetime.fromisoformat(payload.paye_le)
    except ValueError:
        raise HTTPException(status_code=422, detail="Date et heure invalides (ex. 2026-11-12T14:30)")
    res = await db.services_web.update_one({"id": service_id}, {"$set": {
        "dernier_paiement_le": payload.paye_le, "dernier_paiement_montant": payload.montant,
        "dernier_paiement_reference": payload.reference.strip(), "paye_echeance": bool(payload.echeance_reglee)}})
    if res.matched_count == 0:
        raise HTTPException(status_code=404, detail="Service introuvable")
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


@router.delete("/admin/services-web/{service_id}")
async def admin_supprimer(service_id: str, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    res = await db.services_web.delete_one({"id": service_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service introuvable")
    return {"ok": True}
