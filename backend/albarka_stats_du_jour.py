"""Lot 15 — statistiques internes du jour demandées par SAWALI.

SAWALI interroge chaque jour ALBARKA par la même « URL de retour » que la
Transmission WA Universelle (POST /api/webhooks/liluvine-retour), signée
avec la même clé (LILUVINE_WA_HMAC), avec le corps :
    {"type": "stats_du_jour", "debut": "<ISO>", "fin": "<ISO>"}
Période en UTC, borne de début incluse, borne de fin exclue : [debut, fin).

Réponse (200) :
    {"indicateurs": [{"cle", "libelle", "valeur"}, ...],
     "faits_marquants": ["...", ...],          # 5 phrases courtes au plus
     "utilisateurs_connectes": <entier ou null>}

Règles : lecture seule, réponse en moins de 8 s (chaque comptage a son
propre délai), jamais d'erreur 500 (un comptage en échec vaut 0, une
présence illisible vaut null). Les comptes de test sont exclus des clients.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("albarka.stats_du_jour")

# Durée maximale d'une période demandée (protocole : 31 jours).
PERIODE_MAX = timedelta(days=31)
# Délai maximal de CHAQUE comptage (ils tournent en parallèle : < 8 s au total).
DELAI_COMPTAGE_SECONDES = 5.0
# Fenêtre « connecté maintenant » : activité dans les 5 dernières minutes.
FENETRE_CONNECTES = timedelta(minutes=5)
# Nombre maximal de faits marquants renvoyés.
FAITS_MAX = 5


class PeriodeInvalide(ValueError):
    """Période absente, illisible, inversée ou trop longue (réponse 422)."""


# ---------------------------------------------------------------------------
# Lecture et contrôle de la période
# ---------------------------------------------------------------------------
def _lire_date(valeur: Any, nom: str) -> datetime:
    """Convertit une date ISO 8601 en datetime UTC (sans fuseau = UTC)."""
    if not isinstance(valeur, str) or not valeur.strip():
        raise PeriodeInvalide(f"« {nom} » absent ou invalide")
    try:
        dt = datetime.fromisoformat(valeur.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise PeriodeInvalide(f"« {nom} » n'est pas une date ISO valide") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def lire_periode(corps: Dict[str, Any]) -> Tuple[datetime, datetime]:
    """Renvoie (debut, fin) en UTC ou lève PeriodeInvalide."""
    debut = _lire_date(corps.get("debut"), "debut")
    fin = _lire_date(corps.get("fin"), "fin")
    if fin <= debut:
        raise PeriodeInvalide("Période inversée ou vide (fin <= debut)")
    if fin - debut > PERIODE_MAX:
        raise PeriodeInvalide("Période trop longue (31 jours au plus)")
    return debut, fin


# ---------------------------------------------------------------------------
# Comptages élémentaires (dates stockées en texte ISO UTC « +00:00 »)
# ---------------------------------------------------------------------------
def _iso(dt: datetime) -> str:
    """Même format que les dates enregistrées par ALBARKA (isoformat UTC)."""
    return dt.astimezone(timezone.utc).isoformat()


def _entre(champ: str, debut: datetime, fin: datetime) -> Dict[str, Any]:
    """Filtre Mongo « champ dans [debut, fin) » sur une date ISO texte."""
    return {champ: {"$gte": _iso(debut), "$lt": _iso(fin)}}


async def _avec_delai(coro, defaut):
    """Exécute un comptage avec délai ; en cas d'échec, renvoie `defaut`."""
    try:
        return await asyncio.wait_for(coro, timeout=DELAI_COMPTAGE_SECONDES)
    except Exception as exc:  # noqa: BLE001 — jamais d'erreur vers SAWALI
        logger.warning("Statistique du jour indisponible : %s", type(exc).__name__)
        return defaut


async def _compter(base, collection: str, filtre: Dict[str, Any]) -> int:
    """Nombre de documents d'une collection correspondant au filtre."""
    return int(await base[collection].count_documents(filtre))


async def _somme(base, collection: str, filtre: Dict[str, Any], champ: str) -> float:
    """Somme d'un champ numérique (agrégation côté MongoDB)."""
    curseur = base[collection].aggregate([
        {"$match": filtre},
        {"$group": {"_id": None, "total": {"$sum": f"${champ}"}}},
    ])
    lignes = await curseur.to_list(1)
    return float(lignes[0].get("total") or 0) if lignes else 0.0


async def utilisateurs_connectes(base, maintenant: Optional[datetime] = None) -> Optional[int]:
    """Comptes distincts actifs dans les 5 dernières minutes.

    Source : collection `presence` (un document par compte), dont `last_seen`
    est mis à jour par le battement envoyé toutes les 25 s par chaque page
    ouverte du portail (albarka_presence.py). Renvoie None si illisible."""
    maintenant = maintenant or datetime.now(timezone.utc)
    seuil = _iso(maintenant - FENETRE_CONNECTES)
    try:
        ids = await asyncio.wait_for(
            base.presence.distinct("_id", {"last_seen": {"$gte": seuil}}),
            timeout=DELAI_COMPTAGE_SECONDES,
        )
        return len(ids)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Présence illisible : %s", type(exc).__name__)
        return None


# ---------------------------------------------------------------------------
# Calcul complet
# ---------------------------------------------------------------------------
def _fcfa(montant: float) -> str:
    """Montant lisible en francs CFA (espaces des milliers)."""
    return f"{int(round(montant)):,}".replace(",", " ") + " FCFA"


def _faits_marquants(v: Dict[str, float]) -> List[str]:
    """Quelques phrases courtes tirées des indicateurs non nuls."""
    faits: List[str] = []
    if v["nouveaux_clients"]:
        n = int(v["nouveaux_clients"])
        faits.append(f"{n} nouveau{'x' if n > 1 else ''} client{'s' if n > 1 else ''} inscrit{'s' if n > 1 else ''}")
    if v["montant_encaisse_fcfa"]:
        faits.append(f"{_fcfa(v['montant_encaisse_fcfa'])} encaissés ({int(v['paiements'])} règlement(s))")
    if v["factures_emises"]:
        faits.append(f"{int(v['factures_emises'])} facture(s) émise(s) pour {_fcfa(v['montant_facture_fcfa'])}")
    if v["contrats_crees"]:
        faits.append(f"{int(v['contrats_crees'])} contrat(s) client créé(s)")
    if v["pieces_deposees"]:
        faits.append(f"{int(v['pieces_deposees'])} pièce(s) déposée(s) par les clients")
    if v["messages_whatsapp_recus"]:
        faits.append(f"{int(v['messages_whatsapp_recus'])} message(s) WhatsApp reçu(s)")
    if not faits:
        faits.append("Aucune activité notable sur la période")
    return faits[:FAITS_MAX]


async def calculer_stats(base, debut: datetime, fin: datetime,
                         maintenant: Optional[datetime] = None) -> Dict[str, Any]:
    """Indicateurs d'ALBARKA sur [debut, fin) + connectés maintenant.

    Tous les comptages partent en parallèle, chacun borné à 5 s ; un comptage
    en échec vaut 0 (jamais d'exception)."""
    pas_de_test = {"is_test_account": {"$ne": True}}
    # Définition des indicateurs : (clé, libellé, coroutine de calcul).
    definitions = [
        ("connexions", "Utilisateurs connectés sur la période",
         _compter(base, "users", {**_entre("last_login", debut, fin), **pas_de_test})),
        ("nouveaux_clients", "Nouveaux clients",
         _compter(base, "users", {**_entre("created_at", debut, fin), "roles": "client", **pas_de_test})),
        ("contrats_crees", "Contrats clients créés",
         _compter(base, "client_contracts", _entre("created_at", debut, fin))),
        ("factures_emises", "Factures émises",
         _compter(base, "invoices", _entre("created_at", debut, fin))),
        ("montant_facture_fcfa", "Montant facturé (FCFA)",
         _somme(base, "invoices", _entre("created_at", debut, fin), "total")),
        ("paiements", "Règlements enregistrés",
         _compter(base, "payments", _entre("created_at", debut, fin))),
        ("montant_encaisse_fcfa", "Montant encaissé (FCFA)",
         _somme(base, "payments", _entre("created_at", debut, fin), "amount")),
        ("pieces_deposees", "Pièces déposées par les clients",
         _compter(base, "documents", _entre("created_at", debut, fin))),
        ("documents_publies", "Documents publiés aux clients",
         _compter(base, "client_documents", {**_entre("created_at", debut, fin), "is_deleted": {"$ne": True}})),
        ("messages_whatsapp_recus", "Messages WhatsApp reçus",
         _compter(base, "wa_messages", {**_entre("created_at", debut, fin), "direction": "inbound"})),
    ]
    # Lancement en parallèle (connectés compris) : temps total ≈ comptage le plus lent.
    resultats = await asyncio.gather(
        *(_avec_delai(coro, 0) for _cle, _lib, coro in definitions),
        utilisateurs_connectes(base, maintenant),
    )
    valeurs: Dict[str, float] = {}
    indicateurs: List[Dict[str, Any]] = []
    for (cle, libelle, _coro), valeur in zip(definitions, resultats[:-1]):
        # Montants arrondis au franc ; comptages en entiers.
        valeur = int(round(valeur or 0))
        valeurs[cle] = valeur
        indicateurs.append({"cle": cle, "libelle": libelle, "valeur": valeur})
    return {
        "indicateurs": indicateurs,
        "faits_marquants": _faits_marquants(valeurs),
        "utilisateurs_connectes": resultats[-1],
    }


async def repondre_stats(base, corps: Dict[str, Any]) -> Dict[str, Any]:
    """Point d'entrée appelé par le webhook : lit la période (PeriodeInvalide
    si incorrecte -> 422) puis calcule. Base absente : chaque comptage échoue
    proprement et vaut 0, les connectés valent null."""
    debut, fin = lire_periode(corps)
    return await calculer_stats(base, debut, fin)
