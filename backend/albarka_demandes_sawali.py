"""Lot 91 — Demandes d'ALBARKA à SAWALI : corrections et nouvelles fonctionnalités, suivies avec un numéro SAWALI.

DEMANDE DU PROPRIÉTAIRE (13/11/2026)
   « Pour les requêtes à SAWALI venant d'ALBARKA, gère une liste horodatée de demandes de corrections ou nouvelles
   fonctionnalités. Puis la série de points est remontée à SAWALI qui attribue un numéro et le retourne à ALBARKA, avec un
   commentaire quand cela a été réalisé (date), sinon à partir de quand ce sera réalisé. Une zone de recherche en haut
   permet de retrouver des points demandés, y compris ceux niés (refusés) par la suite. »

EN RÉSUMÉ (pour un développeur WinDev)
   1. Le super-admin saisit ses demandes (type + texte) ; chacune est horodatée et reste « à remonter ».
   2. Bouton « Envoyer à SAWALI » : toutes les demandes à remonter partent dans UNE requête signée (même clé HMAC que le
      support SAWALI : variables LILUVINE_WA_HMAC / LILUVINE_WA_EMETTEUR). SAWALI répond pour CHAQUE demande de la plateforme :
      son numéro (DEM-…), son statut, son commentaire, la date de réalisation ou la date prévue.
   3. Le même bouton sert d'« Actualiser » : on renvoie les nouvelles demandes (il peut ne pas y en avoir) et on relit tous les statuts.
   4. Statuts : « a_remonter » (pas encore envoyée), « remontee » (numérotée, en attente), « realisee », « refusee » (niée).
   5. La recherche (zone en haut) parcourt le texte, le commentaire, le numéro et le statut, refusées comprises.

ROUTES (super-admin « superviseur » uniquement), sous /api
   GET    /demandes-sawali?q=…            — liste (filtrée par la recherche) + compteurs
   POST   /demandes-sawali                — nouvelle demande {type, texte}
   DELETE /demandes-sawali/{id}           — supprimer une demande pas encore remontée
   POST   /demandes-sawali/envoyer        — remonter les demandes à SAWALI et relire les statuts

Collection `demandes_sawali` (quelques dizaines de documents).
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.demandes_sawali")

router = APIRouter(prefix="/demandes-sawali", tags=["Demandes à SAWALI"])

TYPES = {"correction": "Correction", "nouveaute": "Nouvelle fonctionnalité"}
STATUTS = {"a_remonter": "À remonter", "remontee": "Remontée à SAWALI", "realisee": "Réalisée", "refusee": "Refusée"}
CHEMIN_SAWALI = "/webhook/plateforme-demandes"


def _exiger_super_admin(user: dict) -> None:
    if "superviseur" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au super-admin")


class DemandeCorps(BaseModel):
    type: str
    texte: str = Field(..., min_length=3, max_length=2000)


def _vue(d: dict) -> dict:
    """Une demande telle qu'affichée (jamais d'identifiant interne de base)."""
    sortie = {k: d.get(k) for k in ("id", "type", "texte", "demandee_le", "demandee_par", "statut", "numero_sawali",
                                    "commentaire", "realisee_le", "prevue_le", "remontee_le", "maj_sawali_le")}
    sortie["type_libelle"] = TYPES.get(d.get("type"), d.get("type"))
    sortie["statut_libelle"] = STATUTS.get(d.get("statut"), d.get("statut"))
    return sortie


def correspond(d: dict, q: str) -> bool:
    """Recherche : chaque mot saisi doit se trouver dans le texte, le commentaire, le numéro, le statut ou le type (casse ignorée)."""
    mots = [m for m in re.split(r"\s+", (q or "").lower().strip()) if m]
    if not mots:
        return True
    botte = " ".join(str(x or "") for x in (d.get("texte"), d.get("commentaire"), d.get("numero_sawali"),
                                              STATUTS.get(d.get("statut")), TYPES.get(d.get("type")))).lower()
    return all(m in botte for m in mots)


def appliquer_reponse(locales: List[dict], distantes: List[dict]) -> Dict[str, Dict[str, Any]]:
    """Logique pure (testée) : pour chaque réponse de SAWALI (clé = ref_locale = notre id), les champs à mettre à jour.
    Statut inconnu de SAWALI → « remontee » ; une demande inconnue de nous est ignorée."""
    connus = {d["id"] for d in locales}
    maj: Dict[str, Dict[str, Any]] = {}
    for r in distantes or []:
        ref = r.get("ref_locale")
        if ref not in connus:
            continue
        statut = r.get("statut") if r.get("statut") in ("realisee", "refusee", "remontee") else "remontee"
        maj[ref] = {"numero_sawali": r.get("numero"), "statut": statut, "commentaire": (r.get("commentaire") or None),
                    "realisee_le": r.get("realisee_le"), "prevue_le": r.get("prevue_le"),
                    "maj_sawali_le": datetime.now(timezone.utc).isoformat()}
    return maj


@router.get("")
async def lister(q: str = Query(default="", max_length=200), user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    toutes = await db.demandes_sawali.find({}, {"_id": 0}).sort("demandee_le", -1).to_list(2000)
    compteurs = {s: sum(1 for d in toutes if d.get("statut") == s) for s in STATUTS}
    return {"demandes": [_vue(d) for d in toutes if correspond(d, q)], "compteurs": compteurs, "total": len(toutes)}


@router.post("")
async def creer(payload: DemandeCorps, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    if payload.type not in TYPES:
        raise HTTPException(status_code=422, detail="Type attendu : correction ou nouveaute")
    doc = {"id": str(uuid.uuid4()), "type": payload.type, "texte": payload.texte.strip(),
           "demandee_le": datetime.now(timezone.utc).isoformat(), "demandee_par": user.get("full_name") or user.get("email"),
           "statut": "a_remonter", "numero_sawali": None, "commentaire": None, "realisee_le": None, "prevue_le": None,
           "remontee_le": None, "maj_sawali_le": None}
    await db.demandes_sawali.insert_one(dict(doc))
    return _vue(doc)


@router.delete("/{demande_id}")
async def supprimer(demande_id: str, user: dict = Depends(get_current_user)):
    """Seule une demande pas encore remontée peut être supprimée (après remontée, SAWALI en garde la trace : on la fait « refuser »)."""
    _exiger_super_admin(user)
    res = await db.demandes_sawali.delete_one({"id": demande_id, "statut": "a_remonter"})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Demande introuvable ou déjà remontée à SAWALI")
    return {"ok": True}


@router.post("/envoyer")
async def envoyer(user: dict = Depends(get_current_user)):
    """Remonte les demandes « à remonter » à SAWALI puis relit le numéro, le statut et le commentaire de toutes les demandes."""
    _exiger_super_admin(user)
    from albarka_support_sawali import appeler_sawali   # même canal signé que le support SAWALI
    toutes = await db.demandes_sawali.find({}, {"_id": 0}).to_list(2000)
    a_envoyer = [d for d in toutes if d.get("statut") == "a_remonter"]
    corps = {"demandes": [{"ref_locale": d["id"], "type": d["type"], "texte": d["texte"], "demandee_le": d["demandee_le"],
                           "demandee_par": d.get("demandee_par")} for d in a_envoyer]}
    reponse = await appeler_sawali(CHEMIN_SAWALI, corps)
    maj = appliquer_reponse(toutes, reponse.get("demandes") or [])
    maintenant = datetime.now(timezone.utc).isoformat()
    envoyees = {d["id"] for d in a_envoyer}
    for ref, champs in maj.items():
        if ref in envoyees:
            champs["remontee_le"] = maintenant
        await db.demandes_sawali.update_one({"id": ref}, {"$set": champs})
    return {"envoyees": len(a_envoyer), "mises_a_jour": len(maj)}
