"""Lot 44 — Bandeau d'alerte / d'incident et déconnexion programmée (maintenance) du portail ALBARKA.

Même fonctionnement que sur SAWALI (maintenance_plateforme.py) ; RÉSERVÉ au super-admin du portail.

1. BANDEAU : le super-admin publie un message (information, avertissement, critique), avec une image facultative
   affichée dans le coin gauche du bandeau. Il apparaît en haut du portail et sur la page de connexion, jusqu'à
   ce qu'il le retire.

2. DÉCONNEXION PROGRAMMÉE : message + durée avant la déconnexion forcée (1 à 120 minutes) + part de cette durée
   pendant laquelle l'écran est VERROUILLÉ (0 à 100 %, 5 % par défaut : l'écran se verrouille 5 % de la durée
   avant l'échéance). Trois phases, calculées uniquement à partir de l'heure du SERVEUR :
     - « annonce »      : fenêtre fermable chez tous les utilisateurs (puis bandeau rouge) ;
     - « verrouillage » : écran verrouillé, non fermable, décompte à la seconde ;
     - « maintenance »  : à l'échéance, déconnexion forcée. Toute requête d'un utilisateur autre que le super-admin
                          reçoit 503 et la connexion est refusée, jusqu'à ce que le super-admin RÉACTIVE.
   À la réactivation, les sessions ouvertes avant l'échéance restent invalides : chacun se reconnecte.
   Le super-admin n'est JAMAIS bloqué : lui seul peut se reconnecter et rouvrir la connexion.

Stockage : collection `settings` déjà existante (le cluster Atlas est plein : AUCUNE nouvelle collection), documents
`maintenance_portail_etat` (maintenance) et `maintenance_portail_bandeau` (alerte).
"""
from __future__ import annotations

import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from albarka_models import is_admin_account
from db import db

ID_ETAT, ID_BANDEAU = "maintenance_portail_etat", "maintenance_portail_bandeau"
DUREE_DEFAUT, DUREE_MIN, DUREE_MAX = 5, 1, 120        # minutes avant la déconnexion forcée
PART_VERROUILLAGE_DEFAUT = 5                          # % de la durée avec écran verrouillé (les derniers 5 %)
MESSAGE_MAX = 1000
IMAGE_MAX_OCTETS = 400_000                            # image du bandeau (data URI), ~400 Ko
AUCUNE, ANNONCE, VERROUILLAGE, MAINTENANCE = "aucune", "annonce", "verrouillage", "maintenance"
CODE_MAINTENANCE, CODE_SESSION_EXPIREE = "maintenance_portail", "session_maintenance"
MESSAGE_BLOCAGE = ("Portail en maintenance : les connexions sont suspendues. "
                   "Elles seront rétablies par l'administrateur.")
MESSAGE_SESSION_EXPIREE = "Session fermée par la maintenance du portail : reconnectez-vous."
SEVERITES = ("info", "warning", "critical")

# Lot 48 — REPRISE de l'ancien emplacement. Les lots 44 et 45 rangeaient le bandeau et la maintenance dans une collection
# `maintenance_portail` (documents « bandeau » et « etat ») ; le lot 46 les a déplacés dans `settings` (cluster plein, pas de
# nouvelle collection) SANS reprendre l'existant : le réglage du bandeau semblait perdu. Le document est donc d'abord cherché dans
# `settings` ; à défaut, dans l'ancienne collection (lecture seule, jamais créée), puis RECOPIÉ dans `settings`.
ANCIENS_ID = {ID_ETAT: "etat", ID_BANDEAU: "bandeau"}


async def lire_doc(id_doc: str, projection: Optional[dict] = None) -> dict:
    """Document `id_doc` de `settings`, repris de l'ancienne collection `maintenance_portail` s'il n'y est pas encore."""
    doc = await db.settings.find_one({"_id": id_doc}, projection)
    if doc:
        return doc
    ancien = await db.maintenance_portail.find_one({"_id": ANCIENS_ID[id_doc]})
    if not ancien:
        return {}
    await db.settings.update_one({"_id": id_doc}, {"$setOnInsert": {k: v for k, v in ancien.items() if k != "_id"}}, upsert=True)
    return await db.settings.find_one({"_id": id_doc}, projection) or {}


# Petit cache mémoire : l'état est lu à CHAQUE requête authentifiée ; les écritures le vident aussitôt.
_cache: dict = {"lu_a": 0.0, "doc": None}


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _date(valeur: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(valeur) if valeur else None


def vider_cache() -> None:
    _cache["lu_a"], _cache["doc"] = 0.0, None


async def lire_etat(cache: bool = True) -> dict:
    """Document d'état de la maintenance (vide s'il n'existe pas encore)."""
    if cache and _cache["lu_a"] and time.monotonic() - _cache["lu_a"] < 3.0:
        return _cache["doc"] or {}
    doc = await lire_doc(ID_ETAT)
    _cache.update(lu_a=time.monotonic(), doc=doc)
    return doc


def phase_de(doc: dict, a: Optional[datetime] = None) -> str:
    """Phase en cours d'après les dates de l'annonce et l'heure du serveur."""
    if not doc.get("actif"):
        return AUCUNE
    a = a or maintenant()
    if a >= _date(doc["echeance"]):
        return MAINTENANCE
    if a >= _date(doc["debut_verrouillage"]):
        return VERROUILLAGE
    return ANNONCE


def etat_public(doc: dict) -> dict:
    """État diffusé à tous (route publique) : aucune donnée sensible."""
    a = maintenant()
    phase = phase_de(doc, a)
    etat = {"phase": phase, "active": phase != AUCUNE, "maintenant_serveur": a.isoformat()}
    if phase != AUCUNE:
        etat.update({k: doc.get(k) for k in ("message", "annonce_le", "debut_verrouillage", "echeance",
                                              "duree_minutes", "part_verrouillage")})
        etat["secondes_restantes"] = max(0, int((_date(doc["echeance"]) - a).total_seconds() + 0.999))
    return etat


def calendrier(duree_minutes: int, part_verrouillage: int, depart: Optional[datetime] = None) -> dict:
    """Début du verrouillage = départ + (100 - part) % de la durée."""
    depart = depart or maintenant()
    total = timedelta(minutes=duree_minutes)
    return {"annonce_le": depart.isoformat(), "debut_verrouillage": (depart + total * (100 - part_verrouillage) / 100).isoformat(),
            "echeance": (depart + total).isoformat()}


# ---------------------------------------------------------------------------
# Contrôles appelés par l'authentification (albarka_auth)
# ---------------------------------------------------------------------------
def session_valide(doc: dict, payload: dict) -> bool:
    """Faux si le jeton a été émis (`iat`) avant l'horodatage « sessions valides après »."""
    seuil = _date(doc.get("sessions_valides_apres"))
    return not seuil or float(payload.get("iat") or 0) >= int(seuil.timestamp())


async def controler_session(user: dict, payload: dict) -> None:
    """Chaque requête authentifiée : le super-admin n'est jamais bloqué ; les autres reçoivent 503 pendant la
    maintenance, et 401 si leur session a été ouverte avant l'échéance d'une maintenance terminée."""
    if is_admin_account(user):
        return
    doc = await lire_etat()
    if not doc:
        return
    if phase_de(doc) == MAINTENANCE:
        raise HTTPException(status_code=503, detail={"code": CODE_MAINTENANCE, "message": MESSAGE_BLOCAGE})
    if not session_valide(doc, payload):
        raise HTTPException(status_code=401, detail=MESSAGE_SESSION_EXPIREE)


async def refuser_connexion_si_maintenance(user: Optional[dict] = None) -> None:
    """Connexion (mot de passe, code OTP, WhatsApp) : refusée pendant la maintenance, sauf pour le super-admin."""
    if user is not None and is_admin_account(user):
        return
    if phase_de(await lire_etat(cache=False)) == MAINTENANCE:
        raise HTTPException(status_code=503, detail={"code": CODE_MAINTENANCE, "message": MESSAGE_BLOCAGE})


# ---------------------------------------------------------------------------
# Actions du super-admin
# ---------------------------------------------------------------------------
async def super_admin(user: dict = Depends(get_current_user)) -> dict:
    if not is_admin_account(user):
        raise HTTPException(status_code=403, detail="Réservé au super-admin du portail")
    return user


def _auteur(adm: dict) -> dict:
    return {"id": adm.get("id"), "nom": adm.get("full_name") or adm.get("email") or "", "email": adm.get("email", "")}


async def _journaliser(action: str, adm: dict, doc: dict, **extra) -> None:
    """Journal des 30 dernières actions, gardé dans le document d'état."""
    ligne = {"id": str(uuid.uuid4()), "action": action, "date": maintenant().isoformat(), "par": _auteur(adm),
             **{k: doc.get(k) for k in ("message", "duree_minutes", "part_verrouillage", "echeance")}, **extra}
    await lire_doc(ID_ETAT)                               # lot 48 : reprise éventuelle de l'ancien emplacement
    await db.settings.update_one({"_id": ID_ETAT}, {"$push": {"journal": {"$each": [ligne], "$position": 0, "$slice": 30}}},
                                            upsert=True)


class AnnonceIn(BaseModel):
    message: str = Field(..., min_length=1, max_length=MESSAGE_MAX)
    duree_minutes: int = Field(DUREE_DEFAUT, ge=DUREE_MIN, le=DUREE_MAX)
    part_verrouillage: int = Field(PART_VERROUILLAGE_DEFAUT, ge=0, le=100)


class BandeauIn(BaseModel):
    debut: Optional[str] = None                      # lot 46 : début d'affichage (date-heure ISO) ; vide = tout de suite
    fin: Optional[str] = None                        # lot 46 : fin d'affichage (date-heure ISO) ; vide = jusqu'au retrait
    message: str = Field(..., min_length=1, max_length=MESSAGE_MAX)
    severite: str = "warning"
    image: Optional[str] = None                      # data URI (png / jpeg / webp / gif), 400 Ko au plus
    lien_url: Optional[str] = Field(None, max_length=500)
    lien_libelle: Optional[str] = Field(None, max_length=60)


router = APIRouter(tags=["Maintenance et alerte du portail"])


@router.get("/maintenance/etat")
async def etat():
    """État de la maintenance — route PUBLIQUE (la page de connexion et le portail la lisent)."""
    return etat_public(await lire_etat(cache=False))


@router.post("/maintenance/annoncer")
async def annoncer(p: AnnonceIn, adm: dict = Depends(super_admin)):
    doc = await lire_etat(cache=False)
    phase = phase_de(doc)
    if phase == MAINTENANCE:
        raise HTTPException(status_code=409, detail="Une maintenance est en cours : réactivez d'abord les connexions")
    if phase != AUCUNE:
        raise HTTPException(status_code=409, detail="Une déconnexion est déjà programmée : annulez-la avant d'en annoncer une autre")
    nouveau = {"actif": True, "message": p.message.strip(), "duree_minutes": p.duree_minutes,
               "part_verrouillage": p.part_verrouillage, "annonce_par": _auteur(adm),
               **calendrier(p.duree_minutes, p.part_verrouillage)}
    await lire_doc(ID_ETAT)
    await db.settings.update_one({"_id": ID_ETAT}, {"$set": nouveau}, upsert=True)
    vider_cache()
    await _journaliser("ANNONCE", adm, nouveau)
    return etat_public(await lire_etat(cache=False))


@router.post("/maintenance/annuler")
async def annuler(adm: dict = Depends(super_admin)):
    """Annulation AVANT l'échéance : personne n'est déconnecté."""
    doc = await lire_etat(cache=False)
    phase = phase_de(doc)
    if phase == AUCUNE:
        raise HTTPException(status_code=409, detail="Aucune déconnexion programmée")
    if phase == MAINTENANCE:
        raise HTTPException(status_code=409, detail="L'échéance est passée : utilisez « Réactiver les connexions »")
    await db.settings.update_one({"_id": ID_ETAT}, {"$set": {"actif": False}})
    vider_cache()
    await _journaliser("ANNULATION", adm, doc)
    return etat_public(await lire_etat(cache=False))


@router.post("/maintenance/reactiver")
async def reactiver(adm: dict = Depends(super_admin)):
    """Fin de la maintenance : connexions rétablies ; les sessions ouvertes avant l'échéance restent invalides."""
    doc = await lire_etat(cache=False)
    if phase_de(doc) != MAINTENANCE:
        raise HTTPException(status_code=409, detail="Aucune maintenance en cours (avant l'échéance, utilisez « Annuler »)")
    seuil = doc["echeance"]
    await db.settings.update_one({"_id": ID_ETAT}, {"$set": {
        "actif": False, "sessions_valides_apres": seuil, "reactive_le": maintenant().isoformat(), "reactive_par": _auteur(adm)}})
    vider_cache()
    await _journaliser("REACTIVATION", adm, doc)
    return etat_public(await lire_etat(cache=False))


@router.get("/maintenance/journal")
async def journal(adm: dict = Depends(super_admin)):
    doc = await lire_doc(ID_ETAT, {"_id": 0, "journal": 1})
    return {"journal": doc.get("journal") or []}


# ----------------------------- bandeau d'alerte / d'incident -----------------------------
def _image_valide(image: Optional[str]) -> Optional[str]:
    if not image:
        return None
    if not re.match(r"^data:image/(png|jpeg|webp|gif);base64,[A-Za-z0-9+/=]+$", image):
        raise HTTPException(status_code=422, detail="Image refusée : PNG, JPEG, WebP ou GIF uniquement")
    if len(image) > IMAGE_MAX_OCTETS * 4 // 3:
        raise HTTPException(status_code=422, detail="Image trop lourde (400 Ko au plus)")
    return image


def _instant(valeur: Optional[str], nom: str) -> Optional[datetime]:
    """Date-heure ISO → instant UTC (sans fuseau = UTC). Vide → None. Illisible → 422."""
    if not valeur:
        return None
    try:
        d = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Date et heure de {nom} illisibles")
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def statut_bandeau(doc: dict, a: Optional[datetime] = None) -> str:
    """« aucun » | « programme » (début à venir) | « affiche » | « termine » (fin passée), d'après l'heure du serveur."""
    if not doc.get("actif"):
        return "aucun"
    a = a or maintenant()
    debut, fin = _date(doc.get("debut")), _date(doc.get("fin"))
    if debut and a < debut:
        return "programme"
    if fin and a >= fin:
        return "termine"
    return "affiche"


_CHAMPS_PUBLICS = ("actif", "severite", "message", "image", "lien_url", "lien_libelle", "maj_le")
_CHAMPS_ADMIN = _CHAMPS_PUBLICS + ("debut", "fin")


@router.get("/bandeau")
async def lire_bandeau():
    """Bandeau d'alerte à afficher MAINTENANT — route PUBLIQUE (portail et page de connexion).
    {actif: false} s'il n'y en a pas, s'il est programmé pour plus tard ou si sa période est terminée."""
    doc = await lire_doc(ID_BANDEAU, {"_id": 0})
    if statut_bandeau(doc) != "affiche":
        return {"actif": False}
    return {k: doc.get(k) for k in _CHAMPS_PUBLICS}


@router.get("/bandeau/admin")
async def lire_bandeau_admin(adm: dict = Depends(super_admin)):
    """Bandeau tel que le super-admin l'a saisi (même programmé ou terminé), avec son statut."""
    doc = await lire_doc(ID_BANDEAU, {"_id": 0})
    return {**{k: doc.get(k) for k in _CHAMPS_ADMIN}, "statut": statut_bandeau(doc)}


@router.put("/bandeau")
async def publier_bandeau(p: BandeauIn, adm: dict = Depends(super_admin)):
    if p.severite not in SEVERITES:
        raise HTTPException(status_code=422, detail="Gravité inconnue")
    lien = (p.lien_url or "").strip()
    if lien and not (lien.startswith("https://") or lien.startswith("/")):
        raise HTTPException(status_code=422, detail="Le lien doit commencer par https:// ou /")
    debut, fin = _instant(p.debut, "début"), _instant(p.fin, "fin")
    if fin and fin <= maintenant():
        raise HTTPException(status_code=422, detail="La fin d'affichage est déjà passée")
    if debut and fin and fin <= debut:
        raise HTTPException(status_code=422, detail="La fin d'affichage doit être après le début")
    doc = {"actif": True, "severite": p.severite, "message": p.message.strip(), "image": _image_valide(p.image),
           "debut": debut.isoformat() if debut else None, "fin": fin.isoformat() if fin else None,
           "lien_url": lien or None, "lien_libelle": (p.lien_libelle or "").strip() or None,
           "maj_le": maintenant().isoformat(), "maj_par": _auteur(adm)}
    await db.settings.update_one({"_id": ID_BANDEAU}, {"$set": doc}, upsert=True)
    return {"ok": True, **{k: doc[k] for k in _CHAMPS_ADMIN}, "statut": statut_bandeau(doc)}


@router.delete("/bandeau")
async def retirer_bandeau(adm: dict = Depends(super_admin)):
    await db.settings.update_one({"_id": ID_BANDEAU}, {"$set": {"actif": False, "maj_le": maintenant().isoformat()}}, upsert=True)
    return {"ok": True, "actif": False}
