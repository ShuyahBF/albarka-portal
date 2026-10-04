"""Lot 13.3 (migration Render) — réparation automatique après la copie Emergent -> Atlas.

L'outil de copie d'Emergent (POST /api/_admin/migrate-mongo) retire le champ
`_id` de chaque document avant de l'écrire dans Atlas. Pour la plupart des
collections c'est sans effet (le portail retrouve les documents par `id`), mais
quelques documents sont retrouvés PAR LEUR `_id` texte et deviennent introuvables :
  - settings   : {_id: "global"} (tous les Paramètres : reCAPTCHA, e-mails…) et
                 {_id: "push_vapid"} (clés des notifications) ;
  - presence   : {_id: <id de l'utilisateur>} (présence en ligne) ;
  - forms_counters : {_id: <scope>} (numérotation FORM-ALBARKA-0001…), le scope
                 étant perdu, le compteur est recalculé depuis les formulaires.

Cette réparation remet chaque document sous son bon `_id`. Elle est sans risque
et peut tourner plusieurs fois. Deux façons de la lancer :
  - bouton « Réparer après copie » de la page Sauvegardes (super-admin),
    route POST /api/_admin/reparer-copie ;
  - au démarrage du serveur, UNIQUEMENT si REPARATION_COPIE_AUTO=1 est posée
    dans Render par le propriétaire.
Une copie relancée ajoute de nouveaux documents sans `_id` texte : le plus
récent (date de création de l'ObjectId) l'emporte, c'est la donnée d'Emergent
la plus fraîche.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends

from albarka_sauvegarde import require_super_admin

logger = logging.getLogger("albarka.reparation_copie")

router = APIRouter(prefix="/_admin/reparer-copie", tags=["Migration (lot 13.3)"])

CHAMPS_VAPID = {"private_key", "public_key"}   # signature du document {_id: "push_vapid"}
NUMERO_FORMULAIRE = re.compile(r"-(\d+)$")      # FORM-ALBARKA-0007 -> 7


async def _orphelins(col) -> List[Dict[str, Any]]:
    """Documents dont l'_id est un ObjectId (créés par la copie), du plus ancien au plus récent."""
    docs = await col.find({"_id": {"$type": "objectId"}}).to_list(None)
    return sorted(docs, key=lambda d: d["_id"].generation_time)


async def _remplacer(col, id_texte: str, doc: Dict[str, Any]) -> None:
    """Écrit le contenu de `doc` sous l'_id texte attendu (remplace l'ancien s'il existe)."""
    contenu = {k: v for k, v in doc.items() if k != "_id"}
    await col.replace_one({"_id": id_texte}, contenu, upsert=True)


async def reparer_settings(db) -> int:
    """Remet les Paramètres sous {_id: "global"} et les clés push sous {_id: "push_vapid"}."""
    reparés = 0
    for doc in await _orphelins(db.settings):
        cle = "push_vapid" if CHAMPS_VAPID <= set(doc) and len(set(doc) - {"_id"}) <= 4 else "global"
        await _remplacer(db.settings, cle, doc)       # le plus récent passe en dernier et l'emporte
        await db.settings.delete_one({"_id": doc["_id"]})
        reparés += 1
    return reparés


async def reparer_presence(db) -> int:
    """Remet chaque présence sous {_id: user_id} ; supprime celles sans user_id (sans valeur)."""
    reparés = 0
    for doc in await _orphelins(db.presence):
        if doc.get("user_id"):
            await _remplacer(db.presence, doc["user_id"], doc)
            reparés += 1
        await db.presence.delete_one({"_id": doc["_id"]})
    return reparés


async def reparer_compteurs_formulaires(db) -> int:
    """Recalcule la numérotation des formulaires par scope (plus grand numéro existant)."""
    await db.forms_counters.delete_many({"_id": {"$type": "objectId"}})
    maxima: Dict[str, int] = {}
    async for f in db.forms.find({}, {"_id": 0, "scope": 1, "number": 1}):
        m = NUMERO_FORMULAIRE.search(str(f.get("number") or ""))
        if m and f.get("scope"):
            maxima[f["scope"]] = max(maxima.get(f["scope"], 0), int(m.group(1)))
    for scope, valeur in maxima.items():
        # Jamais en arrière : on garde le plus grand du compteur actuel et du recalcul
        actuel = await db.forms_counters.find_one({"_id": scope}) or {}
        if int(actuel.get("value") or 0) < valeur:
            await db.forms_counters.update_one({"_id": scope}, {"$set": {"value": valeur}}, upsert=True)
    return len(maxima)


async def reparer_copie(db) -> Dict[str, int]:
    """Réparation complète, sans risque à relancer."""
    bilan = {
        "settings": await reparer_settings(db),
        "presence": await reparer_presence(db),
        "compteurs_formulaires": await reparer_compteurs_formulaires(db),
    }
    if any(bilan.values()):
        logger.info("Réparation après copie : %s", bilan)
    return bilan


def reparation_auto_active() -> bool:
    """Réparation au démarrage du serveur : SEULEMENT si le propriétaire a posé
    REPARATION_COPIE_AUTO=1 dans Render (décision de sa part, jamais par défaut)."""
    return (os.environ.get("REPARATION_COPIE_AUTO") or "").strip() == "1"


@router.post("")
async def route_reparer_copie(user: dict = Depends(require_super_admin)):
    """Bouton « Réparer après copie » de la page Sauvegardes (super-admin)."""
    from db import db
    return await reparer_copie(db)
