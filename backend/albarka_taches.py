"""Lot 86 — Tâches du personnel (menu « Mon compte »), avec rappel quotidien.

Reprend, pour ALBARKA, le principe des tâches personnelles de SAWALI
(/portal/notes/tasks) : chaque membre du PERSONNEL crée, modifie, coche et
supprime ses propres tâches, et peut recevoir chaque jour, à l'heure qu'il
choisit lui-même, la liste de ses tâches non réalisées.

Règles :
- Réservé au personnel (un compte « client » seul n'a aucun accès).
- Chacun ne voit et ne modifie que SES tâches.
- Les rôles DG, Direction et Secrétariat (et le superviseur) peuvent en plus
  choisir un membre du personnel et consulter toutes ses tâches, réalisées
  comme non réalisées (lecture seule).
- Heure de rappel : saisie en heure du Burkina Faso (= GMT/UTC, sans heure d'été).
- Le rappel part en ARRIÈRE-PLAN depuis le planificateur (jamais dans une requête
  de page — règle 7) : un WhatsApp si le numéro est connu, sinon un e-mail.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
from albarka_models import STAFF_ROLES, has_any_role, is_staff
from db import db

logger = logging.getLogger("albarka.taches")

router = APIRouter(prefix="/me/taches", tags=["Tâches du personnel"])

# Rôles autorisés à consulter les tâches de tout le personnel (le superviseur l'est toujours)
ROLES_VUE_PERSONNEL = ["dg", "direction", "secretariat"]
STATUTS = ("a_faire", "fait")
HEURE_PAR_DEFAUT = "08:00"
# Fenêtre pendant laquelle un rappel manqué (serveur redémarré) est encore envoyé, en minutes
FENETRE_RATTRAPAGE_MIN = 180
_FORMAT_HEURE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
_FORMAT_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _maintenant() -> str:
    return datetime.now(timezone.utc).isoformat()


def _exiger_personnel(user: dict) -> None:
    """Refuse l'accès aux comptes clients (tâches réservées au personnel)."""
    if not is_staff(user):
        raise HTTPException(status_code=403, detail="Réservé au personnel du cabinet")


def peut_voir_tout_le_personnel(user: dict) -> bool:
    return has_any_role(user, ROLES_VUE_PERSONNEL)


def _date_valide(valeur: Optional[str]) -> Optional[str]:
    """Une échéance est vide ou au format AAAA-MM-JJ réel."""
    valeur = (valeur or "").strip()
    if not valeur:
        return None
    if not _FORMAT_DATE.match(valeur):
        raise HTTPException(status_code=400, detail="Date au format AAAA-MM-JJ attendue")
    try:
        datetime.strptime(valeur, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Date invalide")
    return valeur


# ---------------------------------------------------------------------
# Modèles
# ---------------------------------------------------------------------
class ElementListe(BaseModel):
    """Un élément de la liste à cocher (comme les listes de Google Keep / de SAWALI)."""
    id: Optional[str] = None
    texte: str = Field(..., min_length=1, max_length=300)
    fait: bool = False
    fait_le: Optional[str] = None


class TacheCreate(BaseModel):
    """Une tâche = texte libre (titre, détails) ET/OU liste à cocher (éléments)."""
    titre: str = Field(..., min_length=1, max_length=200)
    details: Optional[str] = Field(None, max_length=4000)
    echeance: Optional[str] = None  # AAAA-MM-JJ
    elements: Optional[List[ElementListe]] = Field(None, max_length=100)


class TacheUpdate(BaseModel):
    titre: Optional[str] = Field(None, min_length=1, max_length=200)
    details: Optional[str] = Field(None, max_length=4000)
    echeance: Optional[str] = None  # chaîne vide = retirer l'échéance
    statut: Optional[str] = None
    elements: Optional[List[ElementListe]] = Field(None, max_length=100)  # remplace toute la liste


def _normaliser_elements(elements: Optional[List[ElementListe]], anciens: Optional[List[dict]] = None) -> List[dict]:
    """Éléments propres : identifiant, ordre, et date de réalisation posée en cochant / retirée en décochant."""
    deja = {e.get("id"): e for e in (anciens or [])}
    sortie = []
    for i, e in enumerate(elements or []):
        texte = e.texte.strip()
        if not texte:
            continue
        ident = e.id or str(uuid.uuid4())
        avant = deja.get(ident) or {}
        fait_le = (avant.get("fait_le") or _maintenant()) if e.fait else None
        sortie.append({"id": ident, "texte": texte, "fait": bool(e.fait), "fait_le": fait_le, "ordre": i})
    return sortie


def _statut_depuis_elements(elements: List[dict], statut_demande: str) -> str:
    """Une tâche à liste est réalisée quand TOUS ses éléments sont cochés ; sans liste, le statut demandé s'applique."""
    if elements:
        return "fait" if all(e["fait"] for e in elements) else "a_faire"
    return statut_demande


class RappelPrefs(BaseModel):
    actif: bool = False
    heure: str = HEURE_PAR_DEFAUT  # HH:MM, heure du Burkina (GMT)


# ---------------------------------------------------------------------
# Mes tâches
# ---------------------------------------------------------------------
@router.get("")
async def mes_taches(statut: Optional[str] = Query(None), user: dict = Depends(get_current_user)):
    """Mes tâches (non réalisées d'abord, puis par échéance)."""
    _exiger_personnel(user)
    requete = {"owner_id": user["id"]}
    if statut in STATUTS:
        requete["statut"] = statut
    taches = await db.taches_personnel.find(requete, {"_id": 0}).to_list(2000)
    return _trier(taches)


@router.post("")
async def creer_tache(payload: TacheCreate, user: dict = Depends(get_current_user)):
    _exiger_personnel(user)
    titre = payload.titre.strip()
    if not titre:
        raise HTTPException(status_code=400, detail="Titre requis")
    doc = {
        "id": str(uuid.uuid4()),
        "owner_id": user["id"],
        "owner_name": user.get("full_name"),
        "titre": titre,
        "details": (payload.details or "").strip(),
        "echeance": _date_valide(payload.echeance),
        "elements": _normaliser_elements(payload.elements),
        "statut": "a_faire",
        "realisee_le": None,
        "created_at": _maintenant(),
        "updated_at": _maintenant(),
    }
    doc["statut"] = _statut_depuis_elements(doc["elements"], "a_faire")
    if doc["statut"] == "fait":
        doc["realisee_le"] = _maintenant()
    await db.taches_personnel.insert_one(doc.copy())
    return doc


@router.patch("/{tache_id}")
async def modifier_tache(tache_id: str, payload: TacheUpdate, user: dict = Depends(get_current_user)):
    """Modifier ou cocher une tâche : seulement par son propriétaire."""
    _exiger_personnel(user)
    tache = await db.taches_personnel.find_one({"id": tache_id, "owner_id": user["id"]}, {"_id": 0})
    if not tache:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    modif: dict = {}
    if payload.titre is not None:
        if not payload.titre.strip():
            raise HTTPException(status_code=400, detail="Titre requis")
        modif["titre"] = payload.titre.strip()
    if payload.details is not None:
        modif["details"] = payload.details.strip()
    if payload.echeance is not None:
        modif["echeance"] = _date_valide(payload.echeance)
    if payload.statut is not None and payload.statut not in STATUTS:
        raise HTTPException(status_code=400, detail="Statut inconnu")
    elements = tache.get("elements") or []
    if payload.elements is not None:
        elements = _normaliser_elements(payload.elements, tache.get("elements"))
        modif["elements"] = elements
    if payload.statut is not None or payload.elements is not None:
        modif["statut"] = _statut_depuis_elements(elements, payload.statut or tache.get("statut") or "a_faire")
        # La date de réalisation est posée en cochant, retirée en décochant
        if modif["statut"] == "fait" and tache.get("statut") != "fait":
            modif["realisee_le"] = _maintenant()
        elif modif["statut"] == "a_faire":
            modif["realisee_le"] = None
    modif["updated_at"] = _maintenant()
    await db.taches_personnel.update_one({"id": tache_id}, {"$set": modif})
    return {**tache, **modif}


@router.delete("/{tache_id}")
async def supprimer_tache(tache_id: str, user: dict = Depends(get_current_user)):
    _exiger_personnel(user)
    res = await db.taches_personnel.delete_one({"id": tache_id, "owner_id": user["id"]})
    if res.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Tâche introuvable")
    return {"ok": True}


# ---------------------------------------------------------------------
# Rappel quotidien (réglé par chaque personne)
# ---------------------------------------------------------------------
@router.get("/rappel")
async def lire_rappel(user: dict = Depends(get_current_user)):
    _exiger_personnel(user)
    return {"actif": bool(user.get("taches_rappel_actif")),
            "heure": user.get("taches_rappel_heure") or HEURE_PAR_DEFAUT}


@router.put("/rappel")
async def regler_rappel(payload: RappelPrefs, user: dict = Depends(get_current_user)):
    _exiger_personnel(user)
    if not _FORMAT_HEURE.match(payload.heure):
        raise HTTPException(status_code=400, detail="Heure au format HH:MM attendue")
    await db.users.update_one({"id": user["id"]}, {"$set": {
        "taches_rappel_actif": bool(payload.actif), "taches_rappel_heure": payload.heure}})
    return {"actif": bool(payload.actif), "heure": payload.heure}


# ---------------------------------------------------------------------
# Vue Direction : les tâches de tout le personnel
# ---------------------------------------------------------------------
@router.get("/personnel")
async def liste_personnel(user: dict = Depends(get_current_user)):
    """Membres du personnel avec leurs compteurs (DG / Direction / Secrétariat)."""
    _exiger_personnel(user)
    if not peut_voir_tout_le_personnel(user):
        raise HTTPException(status_code=403, detail="Réservé à la Direction, au DG et au Secrétariat")
    from albarka_models import hide_test_accounts_filter
    membres = await db.users.find(
        {"roles": {"$in": STAFF_ROLES}, "is_active": {"$ne": False}, **hide_test_accounts_filter(user)},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "roles": 1},
    ).to_list(500)
    # Un seul regroupement pour tous les compteurs (pas de requête par personne)
    compteurs = {}
    async for ligne in db.taches_personnel.aggregate([
        {"$group": {"_id": {"o": "$owner_id", "s": "$statut"}, "n": {"$sum": 1}}}]):
        compteurs.setdefault(ligne["_id"]["o"], {})[ligne["_id"]["s"]] = ligne["n"]
    for m in membres:
        c = compteurs.get(m["id"], {})
        m["a_faire"] = c.get("a_faire", 0)
        m["faites"] = c.get("fait", 0)
    membres.sort(key=lambda m: (m.get("full_name") or "").lower())
    return membres


@router.get("/personnel/{membre_id}")
async def taches_du_membre(membre_id: str, user: dict = Depends(get_current_user)):
    """Toutes les tâches d'un membre du personnel : réalisées et non réalisées (lecture seule)."""
    _exiger_personnel(user)
    if not peut_voir_tout_le_personnel(user):
        raise HTTPException(status_code=403, detail="Réservé à la Direction, au DG et au Secrétariat")
    membre = await db.users.find_one({"id": membre_id}, {"_id": 0, "id": 1, "full_name": 1, "roles": 1})
    if not membre or not is_staff(membre):
        raise HTTPException(status_code=404, detail="Membre du personnel introuvable")
    taches = await db.taches_personnel.find({"owner_id": membre_id}, {"_id": 0}).to_list(2000)
    return {"membre": membre, "taches": _trier(taches)}


def _trier(taches: List[dict]) -> List[dict]:
    """Non réalisées d'abord (échéance la plus proche en tête), puis réalisées (la plus récente en tête)."""
    a_faire = sorted((t for t in taches if t.get("statut") != "fait"),
                     key=lambda t: (t.get("echeance") or "9999-12-31", t.get("created_at") or ""))
    faites = sorted((t for t in taches if t.get("statut") == "fait"),
                    key=lambda t: t.get("realisee_le") or "", reverse=True)
    return a_faire + faites


# ---------------------------------------------------------------------
# Envoi du rappel quotidien (appelé chaque minute par le planificateur)
# ---------------------------------------------------------------------
def _texte_rappel(nom: str, taches: List[dict], aujourdhui: str) -> str:
    """Message du rappel : liste numérotée, les tâches en retard sont signalées."""
    lignes = [f"Bonjour {nom or ''}".strip() + ",", "", f"Vos tâches à réaliser ({len(taches)}) :"]
    for i, t in enumerate(_trier(taches)[:25], start=1):
        suite = ""
        if t.get("echeance"):
            suite = f" — échéance {t['echeance']}" + (" (EN RETARD)" if t["echeance"] < aujourdhui else "")
        el = t.get("elements") or []
        reste = [e for e in el if not e.get("fait")]
        if el:
            suite = f" ({len(el) - len(reste)}/{len(el)} faits)" + suite
        lignes.append(f"{i}. {t['titre']}{suite}")
        for e in reste[:5]:                      # les éléments restants de la liste, pour ne pas ouvrir le portail
            lignes.append(f"    - {e['texte']}")
    if len(taches) > 25:
        lignes.append(f"… et {len(taches) - 25} autre(s).")
    lignes += ["", "Portail ALBARKA — Mon compte › Mes tâches"]
    return "\n".join(lignes)


def _numero_whatsapp(u: dict) -> Optional[str]:
    n = (u.get("whatsapp_number") or u.get("phone") or "").replace(" ", "")
    return n if n.startswith("+") else None


async def envoyer_rappels_taches(maintenant: Optional[datetime] = None) -> int:
    """Envoie, une fois par jour, la liste des tâches non réalisées aux personnes dont l'heure choisie
    est atteinte. Renvoie le nombre de rappels envoyés.

    - 2 lectures en bloc seulement (personnes concernées, puis tâches non réalisées de ces personnes) ;
    - un rappel manqué (serveur arrêté) est rattrapé pendant FENETRE_RATTRAPAGE_MIN minutes ;
    - rien n'est envoyé s'il n'y a aucune tâche à réaliser, ni à qui a coupé les notifications."""
    maintenant = maintenant or datetime.now(timezone.utc)
    aujourdhui = maintenant.date().isoformat()
    minutes_now = maintenant.hour * 60 + maintenant.minute
    candidats = await db.users.find(
        {"taches_rappel_actif": True, "is_active": {"$ne": False},
         "can_receive_notifications": {"$ne": False}, "taches_rappel_dernier": {"$ne": aujourdhui}},
        {"_id": 0, "id": 1, "full_name": 1, "email": 1, "phone": 1, "whatsapp_number": 1,
         "roles": 1, "taches_rappel_heure": 1},
    ).to_list(1000)
    dus = []
    for u in candidats:
        if not is_staff(u):
            continue
        h, m = (u.get("taches_rappel_heure") or HEURE_PAR_DEFAUT).split(":")
        ecart = minutes_now - (int(h) * 60 + int(m))
        if 0 <= ecart <= FENETRE_RATTRAPAGE_MIN:
            dus.append(u)
    if not dus:
        return 0
    en_attente = {}
    async for t in db.taches_personnel.find(
            {"owner_id": {"$in": [u["id"] for u in dus]}, "statut": {"$ne": "fait"}}, {"_id": 0}):
        en_attente.setdefault(t["owner_id"], []).append(t)
    from albarka_notifications import send_email, send_whatsapp
    envoyes = 0
    for u in dus:
        # Marqué « fait aujourd'hui » AVANT l'envoi : jamais de doublon, même en cas de panne en cours de route
        await db.users.update_one({"id": u["id"]}, {"$set": {"taches_rappel_dernier": aujourdhui}})
        taches = en_attente.get(u["id"], [])
        if not taches:
            continue
        texte = _texte_rappel(u.get("full_name") or "", taches, aujourdhui)
        try:
            numero = _numero_whatsapp(u)
            resultat = await send_whatsapp(to_phone=numero, message=texte) if numero else {"ok": False}
            if not resultat.get("ok") and u.get("email"):
                html = "<p>" + texte.replace("\n", "<br>") + "</p>"
                await send_email(to=u["email"], subject="Vos tâches du jour — Portail ALBARKA", html=html)
            envoyes += 1
        except Exception:  # noqa: BLE001 — l'échec d'une personne n'arrête pas les autres
            logger.exception("Rappel de tâches : échec pour %s", u.get("id"))
    return envoyes
