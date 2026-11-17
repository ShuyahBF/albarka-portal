"""Lot 117 — Informations montrées au DG À SA CONNEXION (comme le rappel des services web) : ce qui est arrivé depuis sa dernière lecture.

DEMANDE DU PROPRIÉTAIRE (17/11/2026)
   « Informer le DG à sa connexion (comme le rappel des services web), lors de l'arrivée de nouveaux reçus SAWALI pour des paiements
     ou de réponses de SAWALI à des demandes. »

EN RÉSUMÉ (pour un développeur WinDev)
   1. À l'ouverture du portail, le DG (seul) reçoit : (a) les NOUVEAUX PAIEMENTS reçus lus par SAWALI dans les SMS (transactions « entrée »,
      lues auprès de SAWALI), (b) les RÉPONSES DE SAWALI à ses demandes (statut, commentaire, date de réalisation ou prévue modifiés par SAWALI).
   2. « Nouveau » = arrivé APRÈS la dernière lecture « J'ai compris » du DG (ou, la toute première fois, dans les 7 derniers jours).
      Les réponses déjà vues en ouvrant « Demandes à SAWALI » ne sont pas répétées.
   3. Règle 7 (chargement des pages) : l'appel à SAWALI pour les paiements est fait EN ARRIÈRE-PLAN (jamais dans la requête de la page) ; le résultat est
      gardé 2 minutes en mémoire. La première réponse peut donc dire « paiements en cours de lecture » : l'écran redemande quelques secondes plus tard.
   4. Authenticité (règle 21) : les montants, dates et opérateurs viennent de SAWALI (jamais du navigateur) ; un SAWALI injoignable ne bloque jamais
      le portail (« paiements indisponibles »). L'acquittement ne marque comme lu que ce qui était affiché (date `jusqu_a` renvoyée par le serveur).

ROUTES (DG seul), sous /api
   GET   /me/infos-connexion        → {paiements, demandes, paiements_etat, jusqu_a}
   POST  /me/infos-connexion/ack    {jusqu_a}   — « J'ai compris »
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.infos_connexion")

router = APIRouter(prefix="/me/infos-connexion", tags=["Informations de connexion du DG"])

FENETRE_PREMIERE_FOIS_JOURS = 7        # première lecture : on remonte 7 jours en arrière, pas tout l'historique
VALIDITE_CACHE_S = 120                 # lecture des paiements chez SAWALI : au plus toutes les 2 minutes
MAX_PAIEMENTS = 30
PAGE_PAIEMENTS = "infos_connexion_paiements"
PAGE_DEMANDES = "infos_connexion_demandes"
CHEMIN_PAIEMENTS = "/webhook/plateforme-paiements"

# Mémoire du dernier relevé des paiements lus chez SAWALI : {"transactions": [...], "le": horloge, "etat": "jamais" | "ok" | "indisponible"}
_cache: Dict[str, Any] = {"transactions": [], "le": 0.0, "etat": "jamais"}
_en_cours: Optional[asyncio.Task] = None


def _exiger_dg(user: dict) -> None:
    if "dg" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au DG")


def lire_date(valeur: Any) -> Optional[datetime]:
    """Date ISO (avec ou sans fuseau, jour seul accepté) → datetime UTC ; None si illisible. Logique pure (testée)."""
    if not valeur:
        return None
    texte = str(valeur).strip().replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(texte if len(texte) > 10 else texte + "T00:00:00")
    except ValueError:
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def paiements_nouveaux(transactions: List[dict], depuis: datetime) -> List[dict]:
    """Logique pure (testée) : paiements reçus APRÈS `depuis`, du plus récent au plus ancien, avec les seuls champs utiles (jamais le texte du SMS)."""
    sortie = []
    for t in transactions or []:
        quand = lire_date(t.get("recu_le")) if isinstance(t, dict) else None
        if not quand or quand <= depuis or not t.get("montant"):
            continue
        sortie.append({"id": t.get("id"), "recu_le": quand.isoformat(), "montant": t.get("montant"), "tiers": t.get("tiers") or "",
                       "operateur": t.get("operateur") or "", "reference": (t.get("reference") or "")[:60]})
    sortie.sort(key=lambda x: x["recu_le"], reverse=True)
    return sortie[:MAX_PAIEMENTS]


def demandes_repondues(demandes: List[dict], depuis: datetime) -> List[dict]:
    """Logique pure (testée) : demandes dont SAWALI a changé le numéro, le statut, le commentaire ou une date APRÈS `depuis` (champ `modifiee_sawali_le`)."""
    sortie = []
    for d in demandes or []:
        quand = lire_date(d.get("modifiee_sawali_le"))
        if quand and quand > depuis:
            sortie.append({"id": d.get("id"), "numero_sawali": d.get("numero_sawali"), "texte": (d.get("texte") or "")[:200], "statut": d.get("statut"),
                           "commentaire": d.get("commentaire"), "prevue_le": d.get("prevue_le"), "realisee_le": d.get("realisee_le"),
                           "modifiee_le": quand.isoformat()})
    sortie.sort(key=lambda x: x["modifiee_le"], reverse=True)
    return sortie


async def _lire_paiements_sawali() -> None:
    """Relevé des paiements reçus chez SAWALI (tâche de fond, jamais attendue par la page). Un échec garde l'ancien relevé et le dit."""
    global _en_cours
    try:
        import albarka_support_sawali                      # appelé par son module : remplaçable dans les tests
        reponse = await albarka_support_sawali.appeler_sawali(CHEMIN_PAIEMENTS, {"sens": "entree", "limite": 100})
        _cache.update({"transactions": reponse.get("transactions") or [], "le": time.monotonic(), "etat": "ok"})
    except Exception as exc:                                 # noqa: BLE001 — SAWALI injoignable ou non configuré : jamais bloquant
        logger.info("Paiements SAWALI indisponibles : %s", exc)
        _cache.update({"le": time.monotonic(), "etat": "indisponible" if _cache["etat"] != "ok" else "ok"})
    finally:
        _en_cours = None


def _demander_releve() -> None:
    """Lance la lecture en arrière-plan si le relevé est périmé et qu'aucune lecture n'est en cours."""
    global _en_cours
    perime = _cache["etat"] == "jamais" or time.monotonic() - _cache["le"] > VALIDITE_CACHE_S
    if perime and _en_cours is None:
        _en_cours = asyncio.get_running_loop().create_task(_lire_paiements_sawali())


async def _depuis(user: dict, page: str, pages_liees: tuple = ()) -> datetime:
    """Date de la dernière lecture du DG : la plus récente entre son « J'ai compris » et (demandes) sa dernière ouverture de la page ; sinon 7 jours."""
    plus_recent = datetime.now(timezone.utc) - timedelta(days=FENETRE_PREMIERE_FOIS_JOURS)
    for p in (page,) + tuple(pages_liees):
        marque = await db.user_view_marks.find_one({"user_id": user["id"], "page": p}, {"_id": 0, "seen_at": 1})
        d = lire_date((marque or {}).get("seen_at"))
        if d and d > plus_recent:
            plus_recent = d
    return plus_recent


@router.get("")
async def mes_infos(user: dict = Depends(get_current_user)):
    """Ce qui est arrivé depuis la dernière lecture du DG. Rapide : les paiements viennent du relevé gardé en mémoire (rafraîchi en arrière-plan)."""
    _exiger_dg(user)
    _demander_releve()
    maintenant = datetime.now(timezone.utc)
    depuis_p = await _depuis(user, PAGE_PAIEMENTS)
    depuis_d = await _depuis(user, PAGE_DEMANDES, pages_liees=("demandes_sawali",))
    docs = await db.demandes_sawali.find({"modifiee_sawali_le": {"$exists": True, "$ne": None}}, {"_id": 0}).to_list(2000)
    return {"paiements": paiements_nouveaux(_cache["transactions"], depuis_p), "paiements_etat": _cache["etat"],
            "demandes": demandes_repondues(docs, depuis_d), "jusqu_a": maintenant.isoformat()}


class Acquittement(BaseModel):
    jusqu_a: str = Field(..., max_length=40)


@router.post("/ack")
async def acquitter(payload: Acquittement, user: dict = Depends(get_current_user)):
    """« J'ai compris » : marque comme lu ce qui était affiché (jamais au-delà de maintenant, jamais ce qui est arrivé depuis l'affichage)."""
    _exiger_dg(user)
    limite = lire_date(payload.jusqu_a)
    if not limite:
        raise HTTPException(status_code=422, detail="Date invalide")
    limite = min(limite, datetime.now(timezone.utc))
    for page in (PAGE_PAIEMENTS, PAGE_DEMANDES):
        await db.user_view_marks.update_one({"user_id": user["id"], "page": page}, {"$set": {"seen_at": limite.isoformat()}}, upsert=True)
    return {"ok": True}
