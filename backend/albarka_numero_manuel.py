# albarka_numero_manuel.py — Lot 17 : DEUXIÈME NUMÉRO des factures (numéro manuel).
#
# Demande du propriétaire (08/10/2026) : « faire porter 2 numéros à une facture. Celui qui est généré par la plateforme
# et le second est un numéro manuel (modifiable par la secrétaire, le DG ou n'importe qui de la direction). La gestion
# électronique du cabinet étant démarrée en cours d'année, il peut être nécessaire de suivre un ordre de numérotation.
# Après la création des factures, seul le DG peut "ouvrir" un numéro de facture pour modification. S'il est modifié,
# la facture est imprimée avec ce numéro manuel. »
#
# En résumé (pour un développeur WinDev) :
#   - `number` (FAC-AAAAMM-NNNN) reste le numéro de la plateforme : jamais modifié (journal, paiements, archives) ;
#   - `manual_number` est le second numéro, facultatif. Il peut être saisi À LA CRÉATION par le secrétariat, le DG ou la
#     direction (champ du formulaire). Ensuite il est VERROUILLÉ ;
#   - seul le DG « ouvre » le numéro d'une facture (POST …/manual-number/open) ; tant qu'il est ouvert, le secrétariat,
#     le DG ou la direction peut le saisir (PUT …/manual-number). L'enregistrement le REFERME aussitôt ;
#     le DG peut aussi refermer sans rien changer (POST …/manual-number/close) ;
#   - chaque changement est gardé dans `manual_number_history` (ancien, nouveau, qui, quand) et dans le journal ;
#   - un numéro manuel est UNIQUE par type de document (deux factures ne portent pas le même) ;
#   - impression (PDF, nom du fichier, e-mail, WhatsApp) : le numéro manuel s'il existe, sinon celui de la plateforme.
#     Le PDF est régénéré à chaque changement.
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import require_roles
from albarka_models import BILLING_ROLES
from db import db

# Rôles qui peuvent SAISIR le numéro manuel (à la création, ou quand le DG l'a ouvert)
MANUAL_NUMBER_EDIT_ROLES = ["secretariat", "dg", "direction"]
# Seul le DG ouvre / referme un numéro manuel déjà créé
MANUAL_NUMBER_OPEN_ROLES = ["dg"]
MAX_LONGUEUR = 40
_NUMERO = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ./_\-]*$")

router = APIRouter(prefix="/billing/invoices", tags=["Caisse — numéro manuel"])


def _maintenant() -> str:
    """Date et heure actuelles (UTC, ISO)."""
    return datetime.now(timezone.utc).isoformat()


# =====================================================================================
# Logique pure (testée : tests/test_lot17_numero_manuel.py)
# =====================================================================================

def peut_saisir(user: dict) -> bool:
    """Vrai si l'utilisateur peut saisir le numéro manuel (secrétariat, DG, direction)."""
    return bool(set(user.get("roles") or []) & set(MANUAL_NUMBER_EDIT_ROLES))


def peut_ouvrir(user: dict) -> bool:
    """Vrai si l'utilisateur peut ouvrir / refermer le numéro manuel d'une facture déjà créée (DG seulement)."""
    return bool(set(user.get("roles") or []) & set(MANUAL_NUMBER_OPEN_ROLES))


def normaliser_numero(valeur: Any) -> Optional[str]:
    """Numéro manuel nettoyé (espaces en trop retirés) ; None si vide. ValueError si invalide."""
    texte = re.sub(r"\s+", " ", str(valeur or "")).strip()
    if not texte:
        return None
    if len(texte) > MAX_LONGUEUR or not _NUMERO.match(texte):
        raise ValueError(f"Numéro manuel invalide : lettres, chiffres, espace, « . / _ - », {MAX_LONGUEUR} caractères au plus")
    return texte


def cle_numero(numero: Optional[str]) -> Optional[str]:
    """Clé de comparaison (unicité) : sans espaces, en majuscules."""
    return re.sub(r"\s+", "", numero or "").upper() or None


def numero_imprime(invoice: dict) -> str:
    """Numéro imprimé sur le document : le numéro manuel s'il existe, sinon celui de la plateforme."""
    return str(invoice.get("manual_number") or invoice.get("number") or "")


async def verifier_unicite(document_type: str, numero: Optional[str], sauf_id: Optional[str] = None) -> None:
    """409 si un autre document du même type porte déjà ce numéro manuel."""
    cle = cle_numero(numero)
    if not cle:
        return
    q: dict = {"document_type": document_type, "manual_number_key": cle}
    if sauf_id:
        q["id"] = {"$ne": sauf_id}
    autre = await db.invoices.find_one(q, {"_id": 0, "number": 1})
    if autre:
        raise HTTPException(status_code=409, detail=f"Le numéro manuel « {numero} » est déjà porté par {autre.get('number')}")


async def champs_creation(valeur: Any, document_type: str, user: dict) -> dict:
    """Champs à ajouter à la création d'un document quand un numéro manuel est saisi dans le formulaire."""
    try:
        numero = normaliser_numero(valeur)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not numero:
        return {}
    if not peut_saisir(user):
        raise HTTPException(status_code=403, detail="Seuls le secrétariat, le DG ou la direction peuvent saisir le numéro manuel")
    await verifier_unicite(document_type, numero)
    return {"manual_number": numero, "manual_number_key": cle_numero(numero), "manual_number_open": False,
            "manual_number_history": [{"ancien": None, "nouveau": numero, "par": user.get("id"),
                                       "par_nom": user.get("full_name") or user.get("email"), "le": _maintenant()}]}


# =====================================================================================
# Routes
# =====================================================================================

class ManualNumberPayload(BaseModel):
    manual_number: Optional[str] = Field(None, max_length=200)


async def _facture(invoice_id: str) -> dict:
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return inv


async def _journal(user: dict, action: str, inv: dict, meta: dict) -> None:
    """Trace dans le journal des activités (jamais bloquant)."""
    try:
        from albarka_phase_c import _log_platform_event
        await _log_platform_event(user=user, action=action, entity_type="invoice", entity_id=inv["id"],
                                  meta={"number": inv.get("number"), **meta})
    except Exception:  # noqa: BLE001
        pass


@router.post("/{invoice_id}/manual-number/open")
async def ouvrir(invoice_id: str, user: dict = Depends(require_roles(BILLING_ROLES))):
    """Le DG ouvre le numéro manuel d'un document pour modification."""
    if not peut_ouvrir(user):
        raise HTTPException(status_code=403, detail="Seul le DG peut ouvrir un numéro de facture pour modification")
    inv = await _facture(invoice_id)
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "manual_number_open": True, "manual_number_opened_by": user.get("id"), "manual_number_opened_at": _maintenant()}})
    await _journal(user, "invoice.manual_number_open", inv, {})
    return await _facture(invoice_id)


@router.post("/{invoice_id}/manual-number/close")
async def refermer(invoice_id: str, user: dict = Depends(require_roles(BILLING_ROLES))):
    """Le DG referme le numéro manuel sans le modifier."""
    if not peut_ouvrir(user):
        raise HTTPException(status_code=403, detail="Seul le DG peut refermer un numéro de facture")
    await _facture(invoice_id)
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"manual_number_open": False}})
    return await _facture(invoice_id)


@router.put("/{invoice_id}/manual-number")
async def modifier(invoice_id: str, payload: ManualNumberPayload, user: dict = Depends(require_roles(BILLING_ROLES))):
    """Saisie du numéro manuel d'un document OUVERT par le DG ; le numéro est refermé et le PDF régénéré."""
    if not peut_saisir(user):
        raise HTTPException(status_code=403, detail="Seuls le secrétariat, le DG ou la direction peuvent saisir le numéro manuel")
    inv = await _facture(invoice_id)
    if not inv.get("manual_number_open"):
        raise HTTPException(status_code=423, detail="Numéro verrouillé : le DG doit d'abord l'ouvrir pour modification")
    try:
        numero = normaliser_numero(payload.manual_number)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    await verifier_unicite(inv.get("document_type") or "facture", numero, sauf_id=invoice_id)
    historique = list(inv.get("manual_number_history") or [])[-49:]
    historique.append({"ancien": inv.get("manual_number"), "nouveau": numero, "par": user.get("id"),
                       "par_nom": user.get("full_name") or user.get("email"), "le": _maintenant()})
    # PDF effacé : il est régénéré (avec le nouveau numéro) à la prochaine ouverture / impression
    await db.invoices.update_one({"id": invoice_id}, {"$set": {
        "manual_number": numero, "manual_number_key": cle_numero(numero), "manual_number_open": False,
        "manual_number_history": historique, "pdf_storage_path": None, "updated_at": _maintenant()}})
    await _journal(user, "invoice.manual_number_set", inv, {"ancien": inv.get("manual_number"), "nouveau": numero})
    return await _facture(invoice_id)
