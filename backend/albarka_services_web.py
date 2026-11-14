"""Lot 90 — « Mes Services Web » : frais des services web du cabinet, rappelés au DG.

QUI FAIT QUOI (demande du propriétaire, 13/11/2026)
   - Le SUPER-ADMIN (rôle « superviseur ») crée et configure les services (nom, montant, payable avant le) et met à jour
     les informations de paiement (date/heure du dernier paiement, montant, référence de la transaction).
   - Le DG (rôle « dg ») est le SEUL à voir la liste (menu « Mes Services Web ») et à être rappelé : 7 jours avant,
     3 jours avant et le jour même, dans une fenêtre qu'il ferme uniquement par « J'ai compris ».
     Les services en retard (non payés après l'échéance) sont rappelés chaque jour jusqu'au paiement.
   - Ni la Direction, ni le super-admin n'ont la vue DG (le super-admin a son écran de configuration dans Paramètres).

ROUTES (sous /api)
   GET    /me/services-web                    — DG et rôles autorisés par le super-admin (lecture seule) : liste avec état et dernier paiement
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
   - Lot 91.1 (14/11/2026) : l'échéance est RÉCURRENTE. Le super-admin ne saisit plus une date mais le JOUR DU MOIS (ex. le 8) :
     chaque mois, ce jour sert d'échéance et de rappel (7 jours, 3 jours, jour même). Un mois plus court ramène le jour à son
     dernier jour (le 31 devient le 28 en février). Enregistrer un paiement qui règle l'échéance fait passer à l'échéance du
     mois suivant (`echeance_payee` = dernière échéance réglée) ; sans paiement, l'échéance reste en retard et est rappelée chaque jour.
   - Jours restants calculés sur la date du jour (UTC = heure du Burkina).
"""
from __future__ import annotations

import calendar
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


# Lot 93.1 — rôles que le super-admin peut autoriser à CONSULTER les services web (lecture seule, sans rappels) ; le DG consulte toujours.
# La mise à jour des paiements reste au super-admin, et à lui SEUL.
ROLES_CONSULTATION = ["direction", "secretariat", "administrateur", "fiscaliste", "comptable", "aide_comptable", "rh", "communication"]


async def roles_consultation() -> List[str]:
    """Rôles autorisés à consulter (réglage du super-admin, enregistré dans les paramètres globaux), limités à la liste ci-dessus."""
    doc = await db.settings.find_one({"_id": "global"}, {"services_web_consultation": 1}) or {}
    return [r for r in (doc.get("services_web_consultation") or []) if r in ROLES_CONSULTATION]


async def peut_consulter(user: dict) -> bool:
    """Vrai pour le DG et pour les rôles que le super-admin a autorisés."""
    roles = set(user.get("roles") or [])
    return "dg" in roles or bool(roles & set(await roles_consultation()))


async def _exiger_consultation(user: dict) -> None:
    if not await peut_consulter(user):
        raise HTTPException(status_code=403, detail="Consultation non autorisée pour ce rôle")


def _exiger_super_admin(user: dict) -> None:
    """Création, configuration et paiements : le super-admin (rôle « superviseur ») UNIQUEMENT."""
    if "superviseur" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au super-admin")


# ---------------------------------------------------------------- modèles
MODES = ("mensuel", "unique")     # lot 94 : paiement récurrent chaque mois, ou montant UNIQUE (réglé en une ou plusieurs fois)


class ServiceCorps(BaseModel):
    service: str = Field(..., min_length=1, max_length=250)
    montant: float = Field(..., ge=0)               # mensuel : montant de chaque échéance ; unique : montant TOTAL à payer
    devise: str = Field(default="FCFA", max_length=8)
    mode: str = Field(default="mensuel", max_length=10)
    jour_du_mois: Optional[int] = Field(default=None, ge=1, le=31)      # mensuel seulement : jour de chaque mois où le paiement est dû (ex. 8)


class ServiceModif(BaseModel):
    service: Optional[str] = Field(None, min_length=1, max_length=250)
    montant: Optional[float] = Field(None, ge=0)
    devise: Optional[str] = Field(None, max_length=8)
    jour_du_mois: Optional[int] = Field(None, ge=1, le=31)


class PaiementCorps(BaseModel):
    paye_le: str                            # date/heure ISO (ex. 2026-11-12T14:30)
    montant: float = Field(..., ge=0)
    reference: str = Field(..., min_length=1, max_length=120)
    echeance_reglee: bool = True            # ce paiement règle-t-il l'échéance en cours (plus de rappel) ?


class SmsCorps(BaseModel):
    sms_ids: List[str] = Field(..., min_length=1, max_length=50)       # paiements reçus par SMS à utiliser pour ce service


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


def est_unique(doc: dict) -> bool:
    """Service à montant UNIQUE (lot 94) : pas d'échéance mensuelle ni de rappel ; on suit le payé et le reste à payer."""
    return doc.get("mode") == "unique"


def historique(doc: dict) -> List[dict]:
    """Paiements enregistrés pour ce service (lot 94), dans l'ordre d'enregistrement."""
    return list(doc.get("paiements") or [])


def total_paye(doc: dict) -> float:
    return float(sum(float(p.get("montant") or 0) for p in historique(doc)))


def reste_a_payer(doc: dict) -> float:
    """Montant unique − total payé (jamais négatif)."""
    return max(0.0, float(doc.get("montant") or 0) - total_paye(doc))


def sms_utilises(services: List[dict]) -> dict:
    """Paiements reçus par SMS déjà utilisés : {identifiant SMS: nom du service}. Un paiement SMS ne sert qu'UNE fois, pour UN seul service."""
    return {p["sms_id"]: d.get("service") for d in services for p in historique(d) if p.get("sms_id")}


def occurrence(annee: int, mois: int, jour_du_mois: int) -> date:
    """Le jour du mois demandé, ramené au dernier jour d'un mois plus court (le 31 → le 28 en février)."""
    return date(annee, mois, min(jour_du_mois, calendar.monthrange(annee, mois)[1]))


def mois_suivant(d: date, jour_du_mois: int) -> date:
    """Échéance du mois qui suit celle de `d`."""
    annee, mois = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return occurrence(annee, mois, jour_du_mois)


def prochaine_apres_paiement(date_paiement: date, jour: int) -> date:
    """Prochaine échéance d'un service mensuel (lot 96) : UN MOIS APRÈS le dernier paiement constaté, sur le jour du mois précisé.
    On vise « date du paiement + 1 mois » et on retient l'occurrence du jour du mois la PLUS PROCHE de cette cible (strictement après le paiement) :
    payé le 20/11, jour 15 → cible 20/12 → échéance le 15/12 ; payé le 10/11 → cible 10/12 → 15/12 ; payé le 01/12 → cible 01/01 → 15/01.
    Le 31 devient le dernier jour des mois plus courts."""
    annee, mois = (date_paiement.year + 1, 1) if date_paiement.month == 12 else (date_paiement.year, date_paiement.month + 1)
    cible = date(annee, mois, min(date_paiement.day, calendar.monthrange(annee, mois)[1]))
    candidates = []
    for decalage in (-1, 0, 1):
        a, m = cible.year, cible.month + decalage
        if m == 0:
            a, m = a - 1, 12
        elif m == 13:
            a, m = a + 1, 1
        c = occurrence(a, m, jour)
        if c > date_paiement:
            candidates.append(c)
    return min(candidates, key=lambda c: (abs((c - cible).days), -c.toordinal()))


def derniere_date_paiement(doc: dict) -> Optional[date]:
    """Date du DERNIER paiement constaté : la plus récente de l'historique et de l'ancien champ « dernier paiement » (services d'avant le lot 94). None si aucun."""
    dates = []
    candidats = [p.get("paye_le") for p in historique(doc)] + [doc.get("dernier_paiement_le")]
    for v in candidats:
        try:
            dates.append(date.fromisoformat(str(v or "")[:10]))
        except ValueError:
            continue
    return max(dates) if dates else None


def jour_du_service(doc: dict) -> int:
    """Jour du mois de l'échéance (les anciens services à date unique gardent le jour de leur date)."""
    if doc.get("jour_du_mois"):
        return int(doc["jour_du_mois"])
    return date.fromisoformat(doc["payable_avant"]).day


def echeance_courante(doc: dict) -> date:
    """Échéance en cours = la première non réglée : la 1re échéance du service si rien n'est réglé, sinon le mois qui suit
    la dernière échéance réglée (`echeance_payee`). Un impayé ancien reste donc l'échéance en cours (et en retard)."""
    jour = jour_du_service(doc)
    derniere = derniere_date_paiement(doc)
    if derniere:                                       # lot 96.1 : TOUJOURS 1 mois après le dernier paiement constaté, sur le jour du mois (jamais une valeur figée)
        return prochaine_apres_paiement(derniere, jour)
    if doc.get("echeance_payee"):
        return mois_suivant(date.fromisoformat(doc["echeance_payee"]), jour)
    if doc.get("premiere_echeance"):
        return date.fromisoformat(doc["premiere_echeance"])
    if doc.get("payable_avant"):                       # ancien service à date unique (avant le lot 91.1)
        premiere = date.fromisoformat(doc["payable_avant"])
        return mois_suivant(premiere, jour) if doc.get("paye_echeance") else premiere
    return occurrence(date.today().year, date.today().month, jour)


def etat_service(doc: dict, jour: Optional[date] = None) -> dict:
    """Jours restants avant l'échéance en cours et état : « a_jour » (échéance éloignée), « bientot » (≤ 7 jours),
    « aujourdhui » (échéance ce jour), « en_retard » (échéance passée et non réglée)."""
    jour = jour or aujourdhui()
    if est_unique(doc):                                  # lot 94 : pas d'échéance ; payé / partiel / impayé
        paye = total_paye(doc)
        etat = "paye" if (doc.get("montant") or 0) > 0 and reste_a_payer(doc) <= 0 else ("partiel" if paye > 0 else "impaye")
        return {"jours_restants": None, "etat": etat, "en_retard": False, "echeance": None}
    echeance = echeance_courante(doc)
    restants = (echeance - jour).days
    if restants < 0:
        etat = "en_retard"
    elif restants == 0:
        etat = "aujourdhui"
    elif restants <= max(PALIERS_RAPPEL):
        etat = "bientot"
    else:
        etat = "a_jour"
    return {"jours_restants": restants, "etat": etat, "en_retard": etat == "en_retard", "echeance": echeance.isoformat()}


def palier_courant(doc: dict, jour: Optional[date] = None) -> Optional[str]:
    """Palier de rappel à afficher aujourd'hui : « 7 » (de 7 à 4 jours), « 3 » (de 3 à 1 jour), « 0 » (jour même),
    « retard-AAAA-MM-JJ » (chaque jour de retard) ; None si échéance lointaine."""
    jour = jour or aujourdhui()
    if est_unique(doc):                                  # lot 94 : aucun rappel mensuel pour un montant unique
        return None
    e = etat_service(doc, jour)
    if e["etat"] == "a_jour":
        return None
    r = e["jours_restants"]
    if r < 0:
        return f"retard-{jour.isoformat()}"
    if r == 0:
        return "0"
    return "3" if r <= 3 else "7"


def _vue(doc: dict, jour: Optional[date] = None) -> dict:
    """Un service tel qu'affiché (jamais les acquittements internes) ; `payable_avant` = échéance en cours (None pour un montant unique)."""
    sortie = {k: doc.get(k) for k in ("id", "service", "montant", "devise", "dernier_paiement_le",
                                      "dernier_paiement_montant", "dernier_paiement_reference")}
    sortie["mode"] = "unique" if est_unique(doc) else "mensuel"
    # Historique des paiements (lot 94) : jamais les champs internes (échéance précédente)
    sortie["paiements"] = [{k: p.get(k) for k in ("id", "paye_le", "montant", "reference", "source", "sms_id")} for p in historique(doc)]
    sortie["total_paye"] = total_paye(doc)
    sortie["reste_a_payer"] = reste_a_payer(doc) if est_unique(doc) else None
    if est_unique(doc):
        dernier = historique(doc)[-1] if historique(doc) else None
        sortie["dernier_paiement_le"] = dernier.get("paye_le") if dernier else None
        sortie["dernier_paiement_montant"] = dernier.get("montant") if dernier else None
        sortie["dernier_paiement_reference"] = dernier.get("reference") if dernier else None
        sortie["jour_du_mois"] = None
        sortie.update(etat_service(doc, jour))
        sortie["payable_avant"] = None
        return sortie
    sortie["jour_du_mois"] = jour_du_service(doc)
    etat = etat_service(doc, jour)
    sortie.update(etat)
    sortie["payable_avant"] = etat["echeance"]
    return sortie


def rappels_a_afficher(docs: List[dict], jour: Optional[date] = None) -> List[dict]:
    """Rappels non encore acquittés par le DG pour le palier du jour (une clé « échéance:palier » par service)."""
    sortie = []
    for d in docs:
        palier = palier_courant(d, jour)
        if palier is None:
            continue
        cle = f"{etat_service(d, jour)['echeance']}:{palier}"
        if cle in (d.get("acquittements") or []):
            continue
        v = _vue(d, jour)
        v["cle"] = cle
        v["palier"] = palier
        sortie.append(v)
    sortie.sort(key=lambda x: x["jours_restants"])
    return sortie


async def _tous() -> List[dict]:
    docs = await db.services_web.find({}, {"_id": 0}).to_list(500)
    # les échéances les plus proches (ou en retard) d'abord ; les montants uniques à la suite (lot 94)
    docs.sort(key=lambda d: (1, "") if est_unique(d) else (0, echeance_courante(d).isoformat()))
    return docs


# ---------------------------------------------------------------- DG
@router.get("/me/services-web")
async def mes_services_web(user: dict = Depends(get_current_user)):
    """Liste des services web du cabinet avec échéance, état et dernier paiement (LECTURE SEULE) : le DG et les rôles autorisés par le super-admin."""
    await _exiger_consultation(user)
    jour = aujourdhui()
    return {"services": [_vue(d, jour) for d in await _tous()]}


@router.get("/me/services-web/acces")
async def mon_acces(user: dict = Depends(get_current_user)):
    """Lot 93.1 — l'option « Mes Services Web » est-elle dans le menu de cet utilisateur ? (jamais d'erreur : sert à afficher ou masquer l'option)"""
    return {"consultation": await peut_consulter(user), "rappels": "dg" in (user.get("roles") or [])}


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
    valides = {f"{etat_service(d)['echeance']}:{palier_courant(d)}": d["id"] for d in docs if palier_courant(d)}
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
    """Crée un service : MENSUEL (la 1re échéance est la prochaine occurrence du jour du mois, aujourd'hui compris) ou à MONTANT UNIQUE (lot 94 : montant total
    réglé en une ou plusieurs fois, avec reste à payer)."""
    _exiger_super_admin(user)
    if payload.mode not in MODES:
        raise HTTPException(status_code=422, detail="Type attendu : mensuel ou unique")
    doc = {"id": str(uuid.uuid4()), "service": payload.service.strip(), "montant": payload.montant, "mode": payload.mode,
           "devise": (payload.devise or "FCFA").strip() or "FCFA", "paiements": [], "acquittements": [],
           "dernier_paiement_le": None, "dernier_paiement_montant": None, "dernier_paiement_reference": None,
           "created_at": datetime.now(timezone.utc).isoformat()}
    if payload.mode == "mensuel":
        if not payload.jour_du_mois:
            raise HTTPException(status_code=422, detail="Indiquez le jour du mois (1 à 31) du paiement mensuel")
        auj = aujourdhui()
        premiere = occurrence(auj.year, auj.month, payload.jour_du_mois)
        if premiere < auj:
            premiere = mois_suivant(premiere, payload.jour_du_mois)
        doc.update({"jour_du_mois": payload.jour_du_mois, "premiere_echeance": premiere.isoformat(), "echeance_payee": None})
    await db.services_web.insert_one(dict(doc))
    return _vue(doc)


# (déclarées AVANT « /admin/services-web/{service_id} » : sinon « consultation » serait pris pour un identifiant de service)
class ConsultationCorps(BaseModel):
    roles: List[str] = Field(default_factory=list, max_length=20)


@router.get("/admin/services-web/consultation")
async def admin_consultation(user: dict = Depends(get_current_user)):
    """Lot 93.1 — rôles autorisés à consulter les services web (en plus du DG), et liste des rôles possibles."""
    _exiger_super_admin(user)
    return {"roles": await roles_consultation(), "possibles": ROLES_CONSULTATION}


@router.put("/admin/services-web/consultation")
async def admin_consultation_modifier(payload: ConsultationCorps, user: dict = Depends(get_current_user)):
    """Lot 93.1 — le super-admin choisit qui peut consulter (lecture seule). Seuls les rôles de la liste sont acceptés."""
    _exiger_super_admin(user)
    inconnus = [r for r in payload.roles if r not in ROLES_CONSULTATION]
    if inconnus:
        raise HTTPException(status_code=422, detail="Rôle non autorisé à la consultation : " + ", ".join(inconnus))
    await db.settings.update_one({"_id": "global"}, {"$set": {"services_web_consultation": sorted(set(payload.roles))}}, upsert=True)
    return {"roles": sorted(set(payload.roles))}


@router.put("/admin/services-web/{service_id}")
async def admin_modifier(service_id: str, payload: ServiceModif, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service introuvable")
    maj = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    if est_unique(doc):
        maj.pop("jour_du_mois", None)                    # lot 94 : pas de jour du mois pour un montant unique
    if "service" in maj:
        maj["service"] = maj["service"].strip()
    if "jour_du_mois" in maj and not doc.get("echeance_payee"):
        # Rien encore réglé : la 1re échéance suit le nouveau jour (même mois que l'ancienne échéance en cours)
        ancienne = echeance_courante(doc)
        maj["premiere_echeance"] = occurrence(ancienne.year, ancienne.month, maj["jour_du_mois"]).isoformat()
    if "jour_du_mois" in maj and doc.get("payable_avant") and not doc.get("jour_du_mois"):
        # Ancien service à date unique : on le convertit en service récurrent à partir de son échéance en cours
        maj.setdefault("premiere_echeance", echeance_courante(doc).isoformat())
        maj["echeance_payee"] = doc.get("echeance_payee")
    if maj:
        await db.services_web.update_one({"id": service_id}, {"$set": maj})
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


@router.post("/admin/services-web/{service_id}/paiement")
async def admin_paiement(service_id: str, payload: PaiementCorps, user: dict = Depends(get_current_user)):
    """Enregistre le dernier paiement (date/heure, montant, référence) ; par défaut il règle l'échéance en cours,
    et le prochain rappel est celui du mois suivant."""
    _exiger_super_admin(user)
    try:
        datetime.fromisoformat(payload.paye_le)
    except ValueError:
        raise HTTPException(status_code=422, detail="Date et heure invalides (ex. 2026-11-12T14:30)")
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service introuvable")
    entree = {"id": str(uuid.uuid4()), "paye_le": payload.paye_le, "montant": payload.montant, "reference": payload.reference.strip(), "source": "manuel"}
    maj = {"dernier_paiement_le": payload.paye_le, "dernier_paiement_montant": payload.montant,
           "dernier_paiement_reference": payload.reference.strip()}
    if not est_unique(doc):
        entree["echeance_avant"] = doc.get("echeance_payee")           # pour pouvoir annuler ce paiement (lot 94)
        if payload.echeance_reglee:
            reglee = echeance_courante(doc)
            maj["echeance_payee"] = reglee.isoformat()
            if not doc.get("premiere_echeance"):
                maj["premiere_echeance"] = reglee.isoformat()
    await db.services_web.update_one({"id": service_id}, {"$set": maj, "$push": {"paiements": entree}})
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


def preparer_transactions_sms(transactions: List[dict], services: List[dict]) -> List[dict]:
    """Logique pure (testée) : transactions reçues de SAWALI (paiements lus dans les SMS, associés à ce cabinet), prêtes à choisir.
    `reference_proposee` = numéro de transaction de l'opérateur, sinon une référence construite (SMS + date + montant).
    Lot 94 : un paiement SMS ne sert qu'UNE fois, pour UN seul service : `deja_utilise` (et `utilise_par` = nom du service) dès qu'il a été utilisé ;
    `deja_enregistre` (lot 93) reste égal à `deja_utilise` et couvre aussi un paiement saisi à la main avec la même référence."""
    utilises = {k: (v or "un service") for k, v in sms_utilises(services).items()}
    references = {(d.get("dernier_paiement_reference") or "").strip(): (d.get("service") or "un service") for d in services if d.get("dernier_paiement_reference")}
    references.update({(p.get("reference") or "").strip(): (d.get("service") or "un service") for d in services for p in historique(d) if p.get("reference")})
    sortie = []
    for t in transactions or []:
        if not isinstance(t, dict) or not t.get("recu_le") or not t.get("montant"):
            continue
        reference = (t.get("reference") or "").strip() or f"SMS {str(t['recu_le'])[:16]} {int(t['montant'])}"
        par = utilises.get(t.get("id")) or references.get(reference)
        sortie.append({"id": t.get("id"), "recu_le": str(t["recu_le"])[:16], "montant": t["montant"], "tiers": t.get("tiers") or "",
                       "numero": t.get("numero"), "operateur": t.get("operateur"), "client": t.get("client"),
                       "reference_proposee": reference[:120], "deja_utilise": par is not None, "deja_enregistre": par is not None, "utilise_par": par})
    return sortie


@router.get("/admin/services-web/paiements-sms")
async def admin_paiements_sms(user: dict = Depends(get_current_user)):
    """Lot 93 — Paiements REÇUS lus dans les SMS (SAWALI → Transactions SMS), pour les numéros associés à ALBARKA : le super-admin en choisit un pour
    remplir « dernier paiement » sans le ressaisir. Relecture signée auprès de SAWALI ; seuls les champs structurés sont reçus (jamais le texte des SMS)."""
    _exiger_super_admin(user)
    import albarka_support_sawali                       # appelé par son module : remplaçable dans les tests
    reponse = await albarka_support_sawali.appeler_sawali("/webhook/plateforme-paiements", {"sens": "entree", "limite": 300})
    services = await db.services_web.find({}, {"_id": 0}).to_list(500)
    return {"transactions": preparer_transactions_sms(reponse.get("transactions") or [], services)}


@router.post("/admin/services-web/{service_id}/paiements-sms")
async def admin_utiliser_paiements_sms(service_id: str, payload: SmsCorps, user: dict = Depends(get_current_user)):
    """Lot 94 — utilise un OU PLUSIEURS paiements reçus par SMS pour ce service (ex. 4 paiements de 50 000 F sur un total de 250 000 F : reste à payer 50 000 F).
    Les montants, dates et références viennent de SAWALI (jamais du navigateur). Un paiement SMS déjà utilisé pour un service ne peut plus servir pour un autre.
    Service mensuel : chaque paiement règle l'échéance en cours, la plus ancienne d'abord."""
    _exiger_super_admin(user)
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service introuvable")
    import albarka_support_sawali
    reponse = await albarka_support_sawali.appeler_sawali("/webhook/plateforme-paiements", {"sens": "entree", "limite": 500})
    services = await db.services_web.find({}, {"_id": 0}).to_list(500)
    disponibles = {t["id"]: t for t in preparer_transactions_sms(reponse.get("transactions") or [], services) if t.get("id")}
    choisis = []
    for sid in dict.fromkeys(payload.sms_ids):                      # sans doublon, dans l'ordre
        t = disponibles.get(sid)
        if not t:
            raise HTTPException(status_code=404, detail="Paiement SMS introuvable (il n'est pas associé à ce compte dans SAWALI)")
        if t["deja_utilise"]:
            raise HTTPException(status_code=409, detail=f"Ce paiement SMS est déjà utilisé pour « {t['utilise_par']} » : il ne peut plus servir pour un autre service")
        choisis.append(t)
    choisis.sort(key=lambda t: t["recu_le"])
    courant = dict(doc)
    nouvelles = []
    for t in choisis:
        entree = {"id": str(uuid.uuid4()), "paye_le": t["recu_le"], "montant": t["montant"], "reference": t["reference_proposee"], "source": "sms", "sms_id": t["id"]}
        if not est_unique(courant):
            entree["echeance_avant"] = courant.get("echeance_payee")
            reglee = echeance_courante(courant)                                                     # chaque paiement règle l'échéance en cours
            courant["echeance_payee"] = reglee.isoformat()
            courant.setdefault("premiere_echeance", courant["echeance_payee"])
        nouvelles.append(entree)
    dernier = nouvelles[-1]
    maj = {"dernier_paiement_le": dernier["paye_le"], "dernier_paiement_montant": dernier["montant"], "dernier_paiement_reference": dernier["reference"]}
    if not est_unique(doc):
        maj["echeance_payee"] = courant["echeance_payee"]
        if not doc.get("premiere_echeance"):
            maj["premiere_echeance"] = courant["premiere_echeance"]
    await db.services_web.update_one({"id": service_id}, {"$set": maj, "$push": {"paiements": {"$each": nouvelles}}})
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


@router.delete("/admin/services-web/{service_id}/paiements/{paiement_id}")
async def admin_annuler_paiement(service_id: str, paiement_id: str, user: dict = Depends(get_current_user)):
    """Lot 94 — annule un paiement enregistré par erreur (un paiement SMS redevient disponible). Service mensuel : l'échéance suit les paiements qui restent."""
    _exiger_super_admin(user)
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Service introuvable")
    liste = historique(doc)
    index = next((i for i, p in enumerate(liste) if p.get("id") == paiement_id), None)
    if index is None:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    maj: dict = {}
    reste = liste[:index] + liste[index + 1:]
    dernier = reste[-1] if reste else None
    if not est_unique(doc) and not reste:
        maj["echeance_payee"] = liste[index].get("echeance_avant")           # plus aucun paiement : retour à l'état d'avant le tout premier
    maj.update({"paiements": reste, "dernier_paiement_le": dernier.get("paye_le") if dernier else None,
                "dernier_paiement_montant": dernier.get("montant") if dernier else None, "dernier_paiement_reference": dernier.get("reference") if dernier else None})
    await db.services_web.update_one({"id": service_id}, {"$set": maj})
    return _vue(await db.services_web.find_one({"id": service_id}, {"_id": 0}))


def construire_recu(doc: dict, paiement_id: str, jour: Optional[date] = None) -> Optional[dict]:
    """Lot 96 — REÇU d'un paiement de service web (logique pure, testée) : numéro, service, date, montant, référence, origine, et la PROCHAINE ÉCHÉANCE
    (service mensuel : un mois après CE paiement, sur le jour du mois) ou le reste à payer (montant unique). None si le paiement n'existe pas."""
    liste = historique(doc)
    index = next((i for i, p in enumerate(liste) if p.get("id") == paiement_id), None)
    if index is None:
        return None
    p = liste[index]
    d = date.fromisoformat(str(p["paye_le"])[:10])
    recu = {"numero": f"RECU-SW-{d.strftime('%Y%m%d')}-{str(p['id'])[:6].upper()}", "service": doc.get("service"), "devise": doc.get("devise") or "FCFA",
            "mode": "unique" if est_unique(doc) else "mensuel", "paye_le": p["paye_le"], "montant": p["montant"], "reference": p.get("reference"),
            "origine": "SMS reçu" if p.get("source") == "sms" else "Saisi à la main", "emis_le": (jour or aujourdhui()).isoformat()}
    if est_unique(doc):
        cumul = float(sum(float(x.get("montant") or 0) for x in liste[:index + 1]))
        recu.update({"montant_total": doc.get("montant"), "total_paye_apres": cumul, "reste_apres": max(0.0, float(doc.get("montant") or 0) - cumul), "prochaine_echeance": None})
    else:
        recu.update({"jour_du_mois": jour_du_service(doc), "prochaine_echeance": prochaine_apres_paiement(d, jour_du_service(doc)).isoformat()})
    return recu


async def _recu_ou_404(service_id: str, paiement_id: str) -> dict:
    doc = await db.services_web.find_one({"id": service_id}, {"_id": 0})
    recu = construire_recu(doc, paiement_id) if doc else None
    if not recu:
        raise HTTPException(status_code=404, detail="Paiement introuvable")
    return recu


@router.get("/admin/services-web/{service_id}/paiements/{paiement_id}/recu")
async def admin_recu(service_id: str, paiement_id: str, user: dict = Depends(get_current_user)):
    """Lot 96 — reçu imprimable d'un paiement (super-admin)."""
    _exiger_super_admin(user)
    return await _recu_ou_404(service_id, paiement_id)


@router.get("/me/services-web/{service_id}/paiements/{paiement_id}/recu")
async def mon_recu(service_id: str, paiement_id: str, user: dict = Depends(get_current_user)):
    """Lot 96 — reçu imprimable d'un paiement (DG et rôles autorisés à consulter)."""
    await _exiger_consultation(user)
    return await _recu_ou_404(service_id, paiement_id)


@router.delete("/admin/services-web/{service_id}")
async def admin_supprimer(service_id: str, user: dict = Depends(get_current_user)):
    _exiger_super_admin(user)
    res = await db.services_web.delete_one({"id": service_id})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Service introuvable")
    return {"ok": True}
