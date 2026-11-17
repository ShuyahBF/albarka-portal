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

DROITS (lot 92, 14/11/2026) : le DG, la Direction et le Secrétariat (mêmes droits, + le super-admin) ouvrent « Demandes à SAWALI » depuis la
barre latérale (plus depuis les Paramètres) : ajout, modification et suppression, tant que SAWALI n'a pas VALIDÉ la demande (réalisée ou refusée).
Une demande déjà remontée est modifiée / supprimée chez SAWALI d'abord (qui peut refuser si elle vient d'être validée).

ROUTES (DG, Direction, Secrétariat, super-admin), sous /api
   GET    /demandes-sawali?q=…            — liste (filtrée par la recherche) + compteurs
   POST   /demandes-sawali                — nouvelle demande {type, texte}
   PUT    /demandes-sawali/{id}           — modifier {type, texte} tant que SAWALI n'a pas validé
   DELETE /demandes-sawali/{id}           — supprimer tant que SAWALI n'a pas validé
   POST   /demandes-sawali/envoyer        — remonter les demandes à SAWALI et relire les statuts

Collection `demandes_sawali` (quelques dizaines de documents).
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.demandes_sawali")

router = APIRouter(prefix="/demandes-sawali", tags=["Demandes à SAWALI"])

TYPES = {"correction": "Correction", "nouveaute": "Nouvelle fonctionnalité"}
# Lot 120 : « En cours » et « Point mort » viennent de SAWALI avec la durée estimée qui organise l'enchaînement des demandes (Gantt)
STATUTS = {"a_remonter": "À remonter", "remontee": "En attente", "en_cours": "En cours", "point_mort": "Point mort", "realisee": "Réalisée", "refusee": "Refusée"}
STATUTS_SAWALI = ("remontee", "en_cours", "point_mort", "realisee", "refusee")
CHEMIN_SAWALI = "/webhook/plateforme-demandes"


DEMANDES_ROLES = {"dg", "direction", "secretariat", "superviseur"}   # mêmes droits pour ces rôles


def _exiger_super_admin(user: dict) -> None:
    """Accès à « Demandes à SAWALI » : DG, Direction, Secrétariat (mêmes droits) et super-admin."""
    if not (set(user.get("roles") or []) & DEMANDES_ROLES):
        raise HTTPException(status_code=403, detail="Réservé au DG, à la Direction et au Secrétariat")


# Pièces jointes (lot 120.1) : MÊMES limites que SAWALI (qui les range sans nouvelle collection) : 5 par demande, 400 Ko chacune, images JPEG / PNG / WebP ou PDF.
# Le navigateur réduit et recompresse les images avant l'envoi ; ici on RE-contrôle tout (le navigateur n'est jamais cru sur parole).
PIECES_MAX = 5
PIECE_MAX_OCTETS = 400 * 1024
SIGNATURES_PIECES = {"image/jpeg": (b"\xff\xd8\xff",), "image/png": (b"\x89PNG\r\n\x1a\n",), "image/webp": (b"RIFF",), "application/pdf": (b"%PDF-",)}


def nettoyer_pieces(brut: Any) -> tuple:
    """Pièces reçues (base64) → (pièces valides, motif de refus ou None). Une seule mauvaise pièce refuse TOUTE la liste. Logique pure, testée."""
    import base64
    import binascii
    if not brut:
        return [], None
    if not isinstance(brut, list) or len(brut) > PIECES_MAX:
        return [], f"{PIECES_MAX} pièces jointes au plus par demande"
    sortie: List[Dict[str, Any]] = []
    for p in brut:
        if not isinstance(p, dict):
            return [], "Pièce jointe illisible"
        nom = re.sub(r"[^\w .()\-]", "_", str(p.get("nom") or "piece"))[:80] or "piece"
        type_ = p.get("type")
        if type_ not in SIGNATURES_PIECES:
            return [], f"« {nom} » : type non accepté (images JPEG, PNG, WebP ou PDF)"
        try:
            octets = base64.b64decode(str(p.get("data") or ""), validate=True)
        except (binascii.Error, ValueError):
            return [], f"« {nom} » : contenu illisible"
        if not octets or len(octets) > PIECE_MAX_OCTETS:
            return [], f"« {nom} » : {PIECE_MAX_OCTETS // 1024} Ko au plus par pièce"
        if not octets.startswith(SIGNATURES_PIECES[type_]) or (type_ == "image/webp" and octets[8:12] != b"WEBP"):
            return [], f"« {nom} » : le fichier ne correspond pas à son type"
        sortie.append({"id": str(p.get("id") or uuid.uuid4())[:40], "nom": nom, "type": type_, "taille": len(octets), "data": base64.b64encode(octets).decode()})
    return sortie, None


def sans_contenu(pieces: Any) -> List[Dict[str, Any]]:
    """Pièces SANS leur contenu : ce que les listes renvoient."""
    return [{k: p.get(k) for k in ("id", "nom", "type", "taille")} for p in pieces or []]


class DemandeCorps(BaseModel):
    type: str
    texte: str = Field(..., min_length=3, max_length=2000)
    pieces: Optional[List[Dict[str, Any]]] = None       # [{ nom, type, data (base64) }] ; None = ne pas toucher aux pièces


def _vue(d: dict) -> dict:
    """Une demande telle qu'affichée (jamais d'identifiant interne de base)."""
    sortie = {k: d.get(k) for k in ("id", "type", "texte", "demandee_le", "demandee_par", "statut", "numero_sawali",
                                    "commentaire", "realisee_le", "prevue_le", "remontee_le", "maj_sawali_le",
                                    "duree_valeur", "duree_unite", "debut_prevu_le", "historique", "alerte_pieces")}
    sortie["pieces"] = sans_contenu(d.get("pieces"))
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
        statut = r.get("statut") if r.get("statut") in STATUTS_SAWALI else "remontee"
        maj[ref] = {"numero_sawali": r.get("numero"), "statut": statut, "commentaire": (r.get("commentaire") or None),
                    "realisee_le": r.get("realisee_le"), "prevue_le": r.get("prevue_le"),
                    # Planning calculé par SAWALI (durée estimée → début et fin prévus) et historique des changements de statut
                    "duree_valeur": r.get("duree_valeur"), "duree_unite": r.get("duree_unite"), "debut_prevu_le": r.get("debut_prevu_le"),
                    "historique": r.get("historique") if isinstance(r.get("historique"), list) else [],
                    "maj_sawali_le": datetime.now(timezone.utc).isoformat()}
    return maj


CHAMPS_SUIVIS = ("numero_sawali", "statut", "commentaire", "realisee_le", "prevue_le", "duree_valeur", "duree_unite")


def marquer_changements(locales: List[dict], maj: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Logique pure (testée) : ajoute `modifiee_sawali_le` aux demandes dont SAWALI a CHANGÉ le numéro, le statut, le commentaire ou une date.
    Alimente la pastille de la barre latérale. La toute première remontée (« à remonter » → numérotée) n'est pas un changement fait par SAWALI :
    c'est l'action de l'utilisateur lui-même, pas de pastille."""
    par_id = {d["id"]: d for d in locales}
    maintenant = datetime.now(timezone.utc).isoformat()
    for ref, champs in maj.items():
        ancienne = par_id.get(ref) or {}
        if ancienne.get("statut") != "a_remonter" and any((ancienne.get(k) or None) != (champs.get(k) or None) for k in CHAMPS_SUIVIS):
            champs["modifiee_sawali_le"] = maintenant
    return maj


@router.get("")
async def lister(q: str = Query(default="", max_length=200), user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    toutes = await db.demandes_sawali.find({}, {"_id": 0}).sort("demandee_le", -1).to_list(2000)
    compteurs = {s: sum(1 for d in toutes if d.get("statut") == s) for s in STATUTS}
    return {"demandes": [_vue(d) for d in toutes if correspond(d, q)], "compteurs": compteurs, "total": len(toutes)}


@router.get("/{demande_id}/pieces/{piece_id}")
async def piece(demande_id: str, piece_id: str, user: dict = Depends(get_current_user)):
    """Contenu d'une pièce jointe (mêmes droits que la liste), servi en « inline » et sans devinette de type."""
    import base64
    _exiger_super_admin(user)
    d = await db.demandes_sawali.find_one({"id": demande_id}, {"_id": 0})
    p = next((x for x in (d or {}).get("pieces") or [] if x.get("id") == piece_id), None)
    if not p:
        raise HTTPException(status_code=404, detail="Pièce jointe introuvable")
    return Response(content=base64.b64decode(p["data"]), media_type=p["type"],
                    headers={"Content-Disposition": f'inline; filename="{p["nom"]}"', "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@router.post("")
async def creer(payload: DemandeCorps, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    if payload.type not in TYPES:
        raise HTTPException(status_code=422, detail="Type attendu : correction ou nouveaute")
    pieces, motif = nettoyer_pieces(payload.pieces)
    if motif:
        raise HTTPException(status_code=422, detail=motif)
    doc = {"id": str(uuid.uuid4()), "type": payload.type, "texte": payload.texte.strip(), "pieces": pieces,
           "demandee_le": datetime.now(timezone.utc).isoformat(), "demandee_par": user.get("full_name") or user.get("email"),
           "statut": "a_remonter", "numero_sawali": None, "commentaire": None, "realisee_le": None, "prevue_le": None,
           "remontee_le": None, "maj_sawali_le": None}
    await db.demandes_sawali.insert_one(dict(doc))
    asyncio.create_task(_synchroniser_en_arriere_plan(remonter=True))     # lot 120.5 : la demande part chez SAWALI À L'INSTANT (la réponse n'attend pas)
    return _vue(doc)


def _validee(d: dict) -> bool:
    """Validée côté SAWALI (réalisée ou refusée) : plus modifiable ni supprimable."""
    return d.get("statut") in ("realisee", "refusee")


async def _relayer(corps: Dict[str, Any], ref: str) -> None:
    """Transmet une modification / suppression à SAWALI ; si SAWALI la refuse (déjà validée), on relit les statuts et on prévient."""
    from albarka_support_sawali import appeler_sawali
    reponse = await appeler_sawali(CHEMIN_SAWALI, corps)
    toutes = await db.demandes_sawali.find({}, {"_id": 0}).to_list(2000)
    for r, champs in marquer_changements(toutes, appliquer_reponse(toutes, reponse.get("demandes") or [])).items():
        await db.demandes_sawali.update_one({"id": r}, {"$set": champs})
    for refus in reponse.get("refus") or []:
        if refus.get("ref_locale") == ref:
            raise HTTPException(status_code=409, detail=refus.get("motif") or "Demande déjà validée par SAWALI")


@router.put("/{demande_id}")
async def modifier(demande_id: str, payload: DemandeCorps, user: dict = Depends(get_current_user)):
    """Modifie le type et le texte tant que SAWALI n'a pas validé la demande (réalisée / refusée)."""
    _exiger_super_admin(user)
    if payload.type not in TYPES:
        raise HTTPException(status_code=422, detail="Type attendu : correction ou nouveaute")
    d = await db.demandes_sawali.find_one({"id": demande_id}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if _validee(d):
        raise HTTPException(status_code=409, detail="Demande déjà validée par SAWALI : elle ne peut plus être modifiée")
    maj = {"type": payload.type, "texte": payload.texte.strip()}
    if payload.pieces is not None:
        if d.get("statut") != "a_remonter":
            raise HTTPException(status_code=409, detail="Les pièces jointes ne se modifient plus une fois la demande envoyée à SAWALI")
        maj["pieces"], motif = nettoyer_pieces(payload.pieces)
        if motif:
            raise HTTPException(status_code=422, detail=motif)
    if d.get("statut") != "a_remonter":    # déjà remontée : SAWALI d'abord
        await _relayer({"demandes": [], "modifications": [{"ref_locale": demande_id, "type": payload.type, "texte": payload.texte.strip()}]}, demande_id)
    await db.demandes_sawali.update_one({"id": demande_id}, {"$set": maj})
    return _vue(await db.demandes_sawali.find_one({"id": demande_id}, {"_id": 0}))


@router.delete("/{demande_id}")
async def supprimer(demande_id: str, user: dict = Depends(get_current_user)):
    """Supprime tant que SAWALI n'a pas validé la demande ; une demande déjà remontée est d'abord supprimée chez SAWALI."""
    _exiger_super_admin(user)
    d = await db.demandes_sawali.find_one({"id": demande_id}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if _validee(d):
        raise HTTPException(status_code=409, detail="Demande déjà validée par SAWALI : elle ne peut plus être supprimée")
    if d.get("statut") != "a_remonter":
        await _relayer({"demandes": [], "suppressions": [demande_id]}, demande_id)
    await db.demandes_sawali.delete_one({"id": demande_id})
    return {"ok": True}


# Lot 120.5 : un seul échange à la fois (deux créations rapprochées ne doivent pas remonter deux fois la même demande)
_VERROU_ECHANGE = asyncio.Lock()


async def _synchroniser_en_arriere_plan(remonter: bool) -> None:
    """Échange avec SAWALI hors requête (règle 7) ; une erreur (SAWALI injoignable…) n'est jamais montrée : la demande reste « à remonter » et partira à la
    prochaine relecture ou au bouton « Envoyer à SAWALI »."""
    try:
        await synchroniser(remonter=remonter)
    except Exception as e:   # noqa: BLE001
        logging.getLogger(__name__).warning("Échange immédiat avec SAWALI impossible : %s", e)


async def synchroniser(remonter: bool = True) -> Dict[str, int]:
    async with _VERROU_ECHANGE:
        return await _synchroniser_interne(remonter)


async def _synchroniser_interne(remonter: bool = True) -> Dict[str, int]:
    """Échange avec SAWALI : remonte les demandes « à remonter » (si `remonter`) puis relit le numéro, le statut, le commentaire et les dates de TOUTES les demandes."""
    from albarka_support_sawali import appeler_sawali   # même canal signé que le support SAWALI
    toutes = await db.demandes_sawali.find({}, {"_id": 0}).to_list(2000)
    a_envoyer = [d for d in toutes if d.get("statut") == "a_remonter"] if remonter else []
    corps = {"demandes": [{"ref_locale": d["id"], "type": d["type"], "texte": d["texte"], "demandee_le": d["demandee_le"],
                           "demandee_par": d.get("demandee_par"), "pieces": d.get("pieces") or []} for d in a_envoyer]}
    reponse = await appeler_sawali(CHEMIN_SAWALI, corps)
    maj = marquer_changements(toutes, appliquer_reponse(toutes, reponse.get("demandes") or []))
    maintenant = datetime.now(timezone.utc).isoformat()
    envoyees = {d["id"] for d in a_envoyer}
    # SAWALI a pu enregistrer une demande SANS ses pièces (refusées) : on garde nos pièces et on l'écrit clairement
    for refus in reponse.get("refus") or []:
        if refus.get("ref_locale") in envoyees:
            await db.demandes_sawali.update_one({"id": refus["ref_locale"]}, {"$set": {"alerte_pieces": f"SAWALI n'a pas gardé les pièces jointes : {refus.get('motif') or 'refusées'}"}})
    for ref, champs in maj.items():
        if ref in envoyees:
            champs["remontee_le"] = maintenant
        await db.demandes_sawali.update_one({"id": ref}, {"$set": champs})
    return {"envoyees": len(a_envoyer), "mises_a_jour": len(maj)}


async def releve_automatique() -> Optional[Dict[str, int]]:
    """RELECTURE AUTOMATIQUE (planificateur, toutes les 15 minutes) : seulement s'il existe des demandes remontées et pas encore validées (réalisée / refusée).
    Ne remonte rien de nouveau (c'est le bouton « Envoyer à SAWALI ») : elle ne fait que relire les statuts. Rend None si rien à suivre."""
    if not await db.demandes_sawali.find_one({"statut": {"$in": ["remontee", "en_cours", "point_mort"]}}, {"_id": 1}):
        return None
    return await synchroniser(remonter=False)


@router.post("/envoyer")
async def envoyer(user: dict = Depends(get_current_user)):
    """Remonte les demandes « à remonter » à SAWALI puis relit le numéro, le statut et le commentaire de toutes les demandes."""
    _exiger_super_admin(user)
    return await synchroniser(remonter=True)


# Relecture à la CONNEXION (lot 120.4) : au plus une toutes les 60 secondes pour tout le serveur, même si dix collaborateurs se connectent ensemble
_DERNIERE_RELECTURE_CONNEXION = 0.0
INTERVALLE_RELECTURE_CONNEXION_S = 60


def est_client_seul(user: dict) -> bool:
    """Vrai pour un compte client (rôle « client » seul) : lui ne déclenche jamais d'échange avec SAWALI."""
    roles = user.get("roles") or []
    return "client" in roles and len(roles) == 1


async def _relire_en_arriere_plan() -> None:
    """Relecture des statuts chez SAWALI, hors requête (règle 7) : une erreur (SAWALI injoignable…) ne gêne jamais personne."""
    try:
        await releve_automatique()
    except Exception as e:   # noqa: BLE001
        logging.getLogger(__name__).warning("Relecture des demandes à SAWALI à la connexion : %s", e)


@router.post("/relire-connexion")
async def relire_connexion(user: dict = Depends(get_current_user)):
    """Appelée automatiquement par le portail à la connexion de TOUT collaborateur (jamais d'un client) : lance en ARRIÈRE-PLAN la relecture des statuts
    et du planning (durées, dates prévues) chez SAWALI, pour que le diagramme de Gantt soit à jour sans cliquer. Répond tout de suite."""
    global _DERNIERE_RELECTURE_CONNEXION
    if est_client_seul(user):
        raise HTTPException(status_code=403, detail="Réservé aux collaborateurs")
    maintenant = time.monotonic()
    if maintenant - _DERNIERE_RELECTURE_CONNEXION < INTERVALLE_RELECTURE_CONNEXION_S:
        return {"lancee": False}
    _DERNIERE_RELECTURE_CONNEXION = maintenant
    asyncio.create_task(_relire_en_arriere_plan())
    return {"lancee": True}


@router.post("/relire")
async def relire(user: dict = Depends(get_current_user)):
    """Relit les statuts SANS rien remonter (appelée par l'écran ouvert, automatiquement, ou par le bouton « Actualiser »)."""
    _exiger_super_admin(user)
    return await releve_automatique() or {"envoyees": 0, "mises_a_jour": 0}
