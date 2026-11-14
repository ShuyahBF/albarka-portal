"""Lots 100 et 101 — FONCTIONS des contacts d'un client et ACCÈS de ces contacts au portail (suivi à la place du patron, ou en même temps).

DEMANDE DU PROPRIÉTAIRE (14/11/2026)
   « Le DG souhaite permettre à des clients que certains de leurs contacts avec des fonctions puissent ouvrir la plateforme pour faire le suivi à la place ou
   en même temps que leur patron. La liste des fonctions des contacts peut être étendue (DAF, comptable, etc.). Chaque fonction, vue comme un profil, a des cases à
   cocher configurables par rapport aux options disponibles pour un compte client. Leur accès peut être révoqué à tout moment ou limité jusqu'à une certaine date.
   Les fonctions ne sont gérées que par le DG ou le super-admin ; elles sont créées et accessibles pour toute la base des clients. »
   Décisions confirmées : accès ouvert par le DG d'ALBARKA seulement (ou le super-admin) ; DEUX cases par option, « voir » et « agir » ; sessions simultanées
   avec le patron (chaque connexion est distincte et sera tracée au lot suivant).

EN RÉSUMÉ (pour un développeur WinDev)
   1. UNE FONCTION = un profil : un code, un libellé et, pour chaque option de l'espace client (documents, missions, échéances…), deux cases :
      « voir » (la rubrique apparaît) et « agir » (déposer, modifier, supprimer). Collection `fonctions_contacts`. Les fonctions de départ (DG, DAF, comptable…)
      sont créées au premier appel ; le DG en ajoute, modifie ou supprime (une fonction utilisée par un contact ou une fiche ne peut pas être supprimée).
   2. UN ACCÈS : sur la fiche d'un contact d'un client, le DG lui ouvre un accès (fonction + éventuelle date de fin). Cela crée un COMPTE du portail pour ce contact
      (champ `contact_acces` du document `users`, rôle « client »). Le mot de passe provisoire n'est montré qu'UNE FOIS au DG.
   3. À CHAQUE REQUÊTE, `appliquer_acces_contact` (appelée par get_current_user) :
        - refuse si l'accès est révoqué, échu, ou si le compte du client est désactivé ;
        - donne au contact la VUE DU CLIENT (mêmes données, même `id`) limitée aux rubriques « voir » de sa fonction ET ouvertes pour ce client ;
        - refuse toute ÉCRITURE (POST / PUT / PATCH / DELETE) sur une rubrique sans la case « agir » (et sur toute route non reconnue : refus par défaut).
   4. RÉVOCATION : immédiate (le prochain clic est refusé). Date de fin : l'accès cesse à la fin de ce jour-là. « Rétablir » rouvre l'accès.

LOTS 103-104 — CONNEXION ET JOURNAL
   - Connexion : le contact se connecte comme un client — par e-mail + mot de passe provisoire + code, par WHATSAPP (le DG lui génère un PIN depuis la fiche d'accès :
     route /staff-pin existante, puis numéro + PIN + code reçu par WhatsApp) ou par EMPREINTE (enrôlement par le DG, page « Empreintes digitales »).
   - Journal (collection `journal_contacts`) : chaque connexion, chaque page / action et chaque REFUS d'un contact est tracé (contact, fonction, méthode, chemin, résultat,
     adresse IP, heure). Une même page relue dans la minute n'est notée qu'une fois ; présence, notifications et jetons ne sont pas notés. 180 jours conservés.
     Consultation par le DG et le super-admin : par contact (fiche d'accès) ou pour tout un client.

ROUTES (sous /api)
   GET    /contacts/{contact_id}/journal             — parcours d'un contact (DG, super-admin)
   GET    /journal-superadmin?du=&au=&limit          — parcours du super-administrateur (DG SEULEMENT, lot 106)
   GET    /journal-contacts?client_id=&du=&au=&limit — parcours des contacts d'un client ou de tous (DG, super-admin)
   GET    /fonctions-contacts                        — fonctions + catalogue des options (tout le personnel)
   POST   /fonctions-contacts                        — créer {libelle, voir[], agir[]}            (DG, super-admin)
   PUT    /fonctions-contacts/{code}                 — modifier {libelle?, voir?, agir?}          (DG, super-admin)
   DELETE /fonctions-contacts/{code}                 — supprimer si inutilisée                    (DG, super-admin)
   GET    /contacts/{contact_id}/acces               — état de l'accès du contact                (DG, super-admin)
   POST   /contacts/{contact_id}/acces               — ouvrir {fonction, acces_jusqua?}           (DG, super-admin)
   PUT    /contacts/{contact_id}/acces               — modifier {fonction?, acces_jusqua?, revoque?}
   DELETE /contacts/{contact_id}/acces               — révoquer (raccourci de revoque=true)
"""
from __future__ import annotations

import re
import secrets
import unicodedata
import time
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from albarka_auth import get_current_user, hash_password, require_staff
from albarka_models import CLIENT_PORTAL_MODULES, client_modules
from db import db

router = APIRouter(tags=["Fonctions et accès des contacts"])

# Options (rubriques) de l'espace client sur lesquelles une fonction peut avoir « voir » et / ou « agir » : celles que le cabinet ouvre ou ferme client par client.
OPTIONS = dict(CLIENT_PORTAL_MODULES)

# Fonctions de départ (celles qui existaient en liste fixe) : « voir » toutes les rubriques, « agir » aucune (le DG règle ensuite).
FONCTIONS_DE_DEPART = {
    "dg": "Directeur Général", "daf": "DAF", "dfc": "DFC", "comptable_interne": "Comptable interne", "assistant": "Assistant", "rh": "RH",
    "juridique": "Juridique", "banque": "Banque", "impots": "Impôts", "cnss": "CNSS", "auditeur": "Auditeur", "avocat": "Avocat",
    "commissaire_aux_comptes": "Commissaire aux comptes", "notaire": "Notaire", "autre": "Autre",
}

# Écritures permises seulement avec la case « agir » : début de chemin → option. Toute autre écriture d'un contact est REFUSÉE (refus par défaut).
PREFIXES_ECRITURE = {
    "/api/documents": "documents", "/api/missions": "missions", "/api/echeances": "echeances",
    "/api/me/space": "cabinet_documents", "/api/me/paie": "paie", "/api/forms": "formulaires", "/api/me/forms": "formulaires",
}
# Écritures toujours permises à un contact connecté (signal de présence, jeton de notification, déconnexion…) : sans effet sur les données du client.
ECRITURES_LIBRES = ("/api/presence", "/api/push", "/api/auth/")
METHODES_ECRITURE = {"POST", "PUT", "PATCH", "DELETE"}


# =====================================================================================
# Logique pure (testée : tests/test_lot100_fonctions_contacts.py)
# =====================================================================================

def code_de(libelle: str) -> str:
    """« Directeur financier » → « directeur_financier » (sans accents, 40 caractères au plus)."""
    sans = "".join(c for c in unicodedata.normalize("NFD", libelle or "") if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "_", sans.lower()).strip("_")[:40]


def options_valides(liste: Any) -> List[str]:
    """Garde seulement les options connues, sans doublon, dans l'ordre du catalogue."""
    voulues = {str(x) for x in (liste or [])}
    return [o for o in OPTIONS if o in voulues]


def acces_en_vigueur(acces: Dict[str, Any], aujourdhui: date) -> Optional[str]:
    """None si l'accès est valable ; sinon le motif du refus (texte lisible)."""
    if acces.get("revoque"):
        return "Votre accès à la plateforme a été révoqué. Contactez le cabinet ALBARKA."
    fin = acces.get("acces_jusqua")
    if fin:
        try:
            if date.fromisoformat(str(fin)[:10]) < aujourdhui:
                return f"Votre accès à la plateforme a pris fin le {date.fromisoformat(str(fin)[:10]).strftime('%d/%m/%Y')}. Contactez le cabinet ALBARKA."
        except ValueError:
            return "Votre accès à la plateforme est invalide. Contactez le cabinet ALBARKA."
    return None


def option_de_chemin(chemin: str) -> Optional[str]:
    """Option de l'espace client concernée par une route (None = route non reconnue)."""
    for prefixe, option in PREFIXES_ECRITURE.items():
        if chemin == prefixe or chemin.startswith(prefixe + "/"):
            return option
    return None


def ecriture_permise(methode: str, chemin: str, agir: List[str]) -> bool:
    """Un contact peut-il faire cette requête ? Lecture : toujours (les rubriques sont déjà limitées). Écriture : seulement avec « agir » sur l'option, ou route libre."""
    if methode.upper() not in METHODES_ECRITURE or chemin.startswith(ECRITURES_LIBRES):
        return True
    option = option_de_chemin(chemin)
    return option is not None and option in agir


# =====================================================================================
# Accès aux données
# =====================================================================================

async def assurer_fonctions_de_depart() -> None:
    """Crée les fonctions de départ au premier appel (aucune si la collection en contient déjà)."""
    if await db.fonctions_contacts.count_documents({}) > 0:
        return
    maintenant = datetime.now(timezone.utc).isoformat()
    for code, libelle in FONCTIONS_DE_DEPART.items():
        await db.fonctions_contacts.insert_one({"code": code, "libelle": libelle, "voir": list(OPTIONS), "agir": [], "systeme": True, "cree_le": maintenant})


async def lire_fonction(code: str) -> Optional[dict]:
    await assurer_fonctions_de_depart()
    return await db.fonctions_contacts.find_one({"code": code}, {"_id": 0})


async def fonction_existe(code: str) -> bool:
    return bool(await lire_fonction(code))


def _gestionnaire(user: dict) -> None:
    """DG et super-admin (superviseur) seulement."""
    roles = set(user.get("roles") or [])
    if not (roles & {"dg", "superviseur"}):
        raise HTTPException(status_code=403, detail="Réservé au DG et au super-administrateur")


# =====================================================================================
# Journal des parcours des contacts (lot 104)
# =====================================================================================

JOURS_JOURNAL = 180
SANS_JOURNAL = ("/api/presence", "/api/push", "/api/auth/me", "/api/version", "/api/health")     # sondages et jetons : pas de trace
_derniere_page: Dict[str, float] = {}        # (contact + chemin) → instant de la dernière trace (une page relue dans la minute n'est notée qu'une fois)


def a_journaliser(methode: str, chemin: str, maintenant: float, derniere: Dict[str, float], contact_id: str) -> bool:
    """Faut-il noter cette requête ? Pas les sondages ; une lecture identique dans les 60 s n'est notée qu'une fois ; toute écriture est toujours notée."""
    if chemin.startswith(SANS_JOURNAL):
        return False
    if methode.upper() in METHODES_ECRITURE:
        return True
    cle = f"{contact_id}|{chemin}"
    if maintenant - derniere.get(cle, 0.0) < 60:
        return False
    derniere[cle] = maintenant
    if len(derniere) > 5000:                  # borne la mémoire : on repart de zéro
        derniere.clear()
    return True


def est_super_admin(compte: dict) -> bool:
    """Le super-administrateur : rôle « superviseur » ou compte admin du portail. Son parcours est tracé et seul le DG le consulte (lot 106)."""
    from albarka_models import is_admin_account
    return "superviseur" in (compte.get("roles") or []) or is_admin_account(compte)


async def journaliser(compte: dict, type_: str, methode: str = "", chemin: str = "", statut: int = 200, motif: str = "", request: Optional[Request] = None,
                      methode_connexion: str = "", categorie: str = "contact") -> None:
    """Ajoute une ligne au journal (catégorie « contact » : un contact d'un client ; « superadmin » : le super-administrateur, lot 106).
    Ne bloque ni ne fait jamais échouer la requête."""
    try:
        from albarka_access import client_ip
        acces = compte.get("contact_acces") or {}
        if categorie == "superadmin":
            acces = {"fonction": "super-administrateur"}
        await db.journal_contacts.insert_one({
            "id": secrets.token_urlsafe(10), "at": datetime.now(timezone.utc).isoformat(), "contact_id": acces.get("contact_id"), "client_id": acces.get("client_id"),
            "nom": compte.get("full_name"), "fonction": acces.get("fonction"), "type": type_, "methode": methode, "chemin": chemin[:200], "statut": statut,
            "motif": motif[:200], "ip": client_ip(request)[:60] if request is not None else "", "connexion": methode_connexion, "categorie": categorie,
        })
        if secrets.randbelow(100) == 0:      # nettoyage occasionnel des traces trop anciennes
            limite = (datetime.now(timezone.utc) - timedelta(days=JOURS_JOURNAL)).isoformat()
            await db.journal_contacts.delete_many({"at": {"$lt": limite}})
    except Exception:  # noqa: BLE001 — le journal ne doit jamais casser une requête
        pass


async def journaliser_connexion(compte: dict, methode_connexion: str, request: Optional[Request] = None) -> None:
    """Appelée après une connexion réussie (code, WhatsApp, empreinte) : pour un compte de contact ou pour le super-administrateur (lot 106)."""
    if compte.get("contact_acces"):
        await journaliser(compte, "connexion", "POST", "/api/auth", 200, request=request, methode_connexion=methode_connexion)
    elif est_super_admin(compte):
        await journaliser(compte, "connexion", "POST", "/api/auth", 200, request=request, methode_connexion=methode_connexion, categorie="superadmin")


async def tracer_super_admin(compte: dict, request: Optional[Request]) -> None:
    """Trace chaque page / action du SUPER-ADMINISTRATEUR (mêmes règles que pour un contact : sondages ignorés, page relue dans la minute notée une fois, écriture toujours notée).
    Appelée par get_current_user à chaque requête authentifiée."""
    if request is None or not est_super_admin(compte):
        return
    if a_journaliser(request.method, request.url.path, time.monotonic(), _derniere_page, "sa:" + str(compte.get("id"))):
        await journaliser(compte, "action" if request.method.upper() in METHODES_ECRITURE else "page", request.method, request.url.path, 200, request=request, categorie="superadmin")


# =====================================================================================
# Contrôle à chaque requête (appelé par albarka_auth.get_current_user)
# =====================================================================================

async def appliquer_acces_contact(compte: dict, request: Optional[Request]) -> dict:
    """Si `compte` est le compte d'un CONTACT (champ `contact_acces`), rend la VUE DU CLIENT limitée à sa fonction ; lève 403 si l'accès est révoqué / échu / interdit.
    Un compte ordinaire est rendu tel quel. Chaque page / action du contact (et chaque refus) est tracée dans le journal (lot 104)."""
    acces = compte.get("contact_acces")
    if not acces:
        return compte
    methode = request.method if request is not None else "GET"
    chemin = request.url.path if request is not None else ""

    async def refuser(motif: str):
        await journaliser(compte, "refus", methode, chemin, 403, motif, request)
        raise HTTPException(status_code=403, detail=motif)

    motif = acces_en_vigueur(acces, date.today())
    if motif:
        await refuser(motif)
    fiche = await db.contacts.find_one({"id": acces.get("contact_id")}, {"_id": 0, "is_active": 1})
    if not fiche or fiche.get("is_active") is False:
        await refuser("Votre fiche de contact est désactivée. Contactez le cabinet ALBARKA.")
    client = await db.users.find_one({"id": acces.get("client_id")}, {"_id": 0, "password_hash": 0})
    if not client or not client.get("is_active", True):
        await refuser("Le compte du client est indisponible. Contactez le cabinet ALBARKA.")
    fonction = await lire_fonction(acces.get("fonction") or "") or {"voir": [], "agir": []}
    ouverts = client_modules(client)
    voir = [m for m in ouverts if m in fonction.get("voir", [])]
    agir = [m for m in fonction.get("agir", []) if m in voir]
    if request is not None and not ecriture_permise(methode, chemin, agir):
        await refuser("Votre fonction ne permet pas cette action (lecture seule sur cette rubrique).")
    if request is not None and a_journaliser(methode, chemin, time.monotonic(), _derniere_page, compte["id"]):
        await journaliser(compte, "action" if methode.upper() in METHODES_ECRITURE else "page", methode, chemin, 200, request=request)
    return {**client, "portal_modules": voir, "contact_id": compte["id"], "contact_nom": compte.get("full_name"),
            "contact_fonction": acces.get("fonction"), "contact_agir": agir}


# =====================================================================================
# Routes — fonctions
# =====================================================================================

class FonctionCorps(BaseModel):
    libelle: str = Field(..., min_length=2, max_length=60)
    voir: List[str] = Field(default_factory=list)
    agir: List[str] = Field(default_factory=list)


class FonctionMaj(BaseModel):
    libelle: Optional[str] = Field(None, min_length=2, max_length=60)
    voir: Optional[List[str]] = None
    agir: Optional[List[str]] = None


def _normaliser(voir: Any, agir: Any) -> Dict[str, List[str]]:
    voir = options_valides(voir)
    return {"voir": voir, "agir": [o for o in options_valides(agir) if o in voir]}      # « agir » suppose « voir »


@router.get("/fonctions-contacts")
async def lister_fonctions(user: dict = Depends(require_staff())):
    await assurer_fonctions_de_depart()
    items = await db.fonctions_contacts.find({}, {"_id": 0}).sort("libelle", 1).to_list(500)
    return {"fonctions": items, "options": OPTIONS}


@router.post("/fonctions-contacts", status_code=201)
async def creer_fonction(payload: FonctionCorps, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    await assurer_fonctions_de_depart()
    code = code_de(payload.libelle)
    if not code:
        raise HTTPException(status_code=422, detail="Libellé invalide")
    if await db.fonctions_contacts.find_one({"code": code}):
        raise HTTPException(status_code=409, detail="Cette fonction existe déjà")
    doc = {"code": code, "libelle": payload.libelle.strip(), **_normaliser(payload.voir, payload.agir), "systeme": False,
           "cree_le": datetime.now(timezone.utc).isoformat(), "cree_par": user["id"]}
    await db.fonctions_contacts.insert_one(doc.copy())
    doc.pop("_id", None)
    return doc


@router.put("/fonctions-contacts/{code}")
async def modifier_fonction(code: str, payload: FonctionMaj, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    actuelle = await lire_fonction(code)
    if not actuelle:
        raise HTTPException(status_code=404, detail="Fonction introuvable")
    maj: Dict[str, Any] = {}
    if payload.libelle:
        maj["libelle"] = payload.libelle.strip()
    if payload.voir is not None or payload.agir is not None:
        maj.update(_normaliser(actuelle["voir"] if payload.voir is None else payload.voir, actuelle["agir"] if payload.agir is None else payload.agir))
    if maj:
        await db.fonctions_contacts.update_one({"code": code}, {"$set": {**maj, "modifiee_le": datetime.now(timezone.utc).isoformat()}})
    return await lire_fonction(code)


@router.delete("/fonctions-contacts/{code}")
async def supprimer_fonction(code: str, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    if not await lire_fonction(code):
        raise HTTPException(status_code=404, detail="Fonction introuvable")
    # Utilisée par un contact (fiche) ou par un accès ouvert : suppression refusée
    if await db.contacts.find_one({"function": code}) or await db.users.find_one({"contact_acces.fonction": code}):
        raise HTTPException(status_code=409, detail="Cette fonction est utilisée par des contacts : changez d'abord leur fonction.")
    await db.fonctions_contacts.delete_one({"code": code})
    return {"ok": True, "code": code}


# =====================================================================================
# Routes — accès d'un contact
# =====================================================================================

class AccesOuverture(BaseModel):
    fonction: str
    acces_jusqua: Optional[str] = Field(None, description="AAAA-MM-JJ (inclus) ; vide = sans date de fin")


class AccesMaj(BaseModel):
    fonction: Optional[str] = None
    acces_jusqua: Optional[str] = None
    efface_date: bool = False
    revoque: Optional[bool] = None


def _date_fin(texte: Optional[str]) -> Optional[str]:
    if not texte:
        return None
    try:
        return date.fromisoformat(texte[:10]).isoformat()
    except ValueError:
        raise HTTPException(status_code=422, detail="Date de fin invalide (AAAA-MM-JJ)")


async def _contact_client(contact_id: str) -> dict:
    c = await db.contacts.find_one({"id": contact_id}, {"_id": 0})
    if not c or c.get("scope") != "client":
        raise HTTPException(status_code=404, detail="Contact de client introuvable")
    return c


def _vue_acces(compte: Optional[dict]) -> Dict[str, Any]:
    if not compte or not compte.get("contact_acces"):
        return {"ouvert": False}
    a = compte["contact_acces"]
    motif = acces_en_vigueur(a, date.today())
    return {"ouvert": True, "actif": motif is None, "motif": motif, "fonction": a.get("fonction"), "acces_jusqua": a.get("acces_jusqua"),
            "revoque": bool(a.get("revoque")), "compte_id": compte.get("id"), "whatsapp": bool(compte.get("whatsapp_number")), "email": compte.get("email"), "derniere_connexion": compte.get("last_login"), "ouvert_le": a.get("cree_le")}


@router.get("/contacts/{contact_id}/acces")
async def etat_acces(contact_id: str, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    await _contact_client(contact_id)
    return _vue_acces(await db.users.find_one({"contact_acces.contact_id": contact_id}, {"_id": 0, "password_hash": 0}))


@router.post("/contacts/{contact_id}/acces", status_code=201)
async def ouvrir_acces(contact_id: str, payload: AccesOuverture, user: dict = Depends(get_current_user)):
    """Ouvre l'accès au portail pour ce contact. Rend le MOT DE PASSE PROVISOIRE, montré une seule fois (jamais enregistré en clair)."""
    _gestionnaire(user)
    contact = await _contact_client(contact_id)
    if not contact.get("email"):
        raise HTTPException(status_code=422, detail="Ce contact n'a pas d'adresse e-mail : elle sert d'identifiant de connexion.")
    if not await fonction_existe(payload.fonction):
        raise HTTPException(status_code=422, detail="Fonction inconnue")
    if await db.users.find_one({"contact_acces.contact_id": contact_id}):
        raise HTTPException(status_code=409, detail="Un accès existe déjà pour ce contact : modifiez-le.")
    if await db.users.find_one({"email": contact["email"].lower()}):
        raise HTTPException(status_code=409, detail="Cette adresse e-mail est déjà utilisée par un autre compte du portail.")
    provisoire = secrets.token_urlsafe(9)
    maintenant = datetime.now(timezone.utc).isoformat()
    compte = {
        "id": secrets.token_urlsafe(12), "email": contact["email"].lower(), "full_name": contact.get("full_name") or contact["email"],
        "password_hash": hash_password(provisoire), "roles": ["client"], "is_active": True, "created_at": maintenant,
        "phone": contact.get("phone"), "whatsapp_number": contact.get("phone"),
        "contact_acces": {"contact_id": contact_id, "client_id": contact["tenant_id"], "fonction": payload.fonction, "acces_jusqua": _date_fin(payload.acces_jusqua),
                          "revoque": False, "cree_par": user["id"], "cree_le": maintenant},
    }
    await db.users.insert_one(compte.copy())
    compte.pop("_id", None)
    return {**_vue_acces(compte), "mot_de_passe_provisoire": provisoire}


@router.put("/contacts/{contact_id}/acces")
async def modifier_acces(contact_id: str, payload: AccesMaj, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    await _contact_client(contact_id)
    compte = await db.users.find_one({"contact_acces.contact_id": contact_id}, {"_id": 0, "password_hash": 0})
    if not compte:
        raise HTTPException(status_code=404, detail="Aucun accès ouvert pour ce contact")
    maj: Dict[str, Any] = {}
    if payload.fonction is not None:
        if not await fonction_existe(payload.fonction):
            raise HTTPException(status_code=422, detail="Fonction inconnue")
        maj["contact_acces.fonction"] = payload.fonction
    if payload.efface_date:
        maj["contact_acces.acces_jusqua"] = None
    elif payload.acces_jusqua is not None:
        maj["contact_acces.acces_jusqua"] = _date_fin(payload.acces_jusqua)
    if payload.revoque is not None:
        maj["contact_acces.revoque"] = bool(payload.revoque)
        maj["contact_acces.revoque_le" if payload.revoque else "contact_acces.retabli_le"] = datetime.now(timezone.utc).isoformat()
    if maj:
        await db.users.update_one({"id": compte["id"]}, {"$set": maj})
    return _vue_acces(await db.users.find_one({"id": compte["id"]}, {"_id": 0, "password_hash": 0}))


@router.delete("/contacts/{contact_id}/acces")
async def revoquer_acces(contact_id: str, user: dict = Depends(get_current_user)):
    return await modifier_acces(contact_id, AccesMaj(revoque=True), user)


# =====================================================================================
# Routes — journal des parcours (lot 104)
# =====================================================================================

async def _lire_journal(filtre: Dict[str, Any], limite: int, superadmin: bool = False) -> List[dict]:
    """Lignes du journal, les plus récentes d'abord. Les lignes du super-administrateur (catégorie « superadmin ») ne sont lues que par la route réservée au DG."""
    filtre = {**filtre, "categorie": "superadmin"} if superadmin else {**filtre, "categorie": {"$ne": "superadmin"}}
    return await db.journal_contacts.find(filtre, {"_id": 0}).sort("at", -1).to_list(max(1, min(limite, 500)))


@router.get("/contacts/{contact_id}/journal")
async def journal_du_contact(contact_id: str, limit: int = 100, user: dict = Depends(get_current_user)):
    _gestionnaire(user)
    await _contact_client(contact_id)
    return {"journal": await _lire_journal({"contact_id": contact_id}, limit)}


@router.get("/journal-contacts")
async def journal_des_contacts(client_id: str = "", du: str = "", au: str = "", limit: int = 200, user: dict = Depends(get_current_user)):
    """Parcours des contacts d'un client (ou de tous), sur une période (AAAA-MM-JJ, bornes incluses)."""
    _gestionnaire(user)
    filtre: Dict[str, Any] = {}
    if client_id:
        filtre["client_id"] = client_id
    plage: Dict[str, str] = {}
    if du:
        plage["$gte"] = _date_fin(du) or ""
    if au:
        plage["$lt"] = (date.fromisoformat(_date_fin(au)) + timedelta(days=1)).isoformat()
    if plage:
        filtre["at"] = plage
    return {"journal": await _lire_journal(filtre, limit)}


@router.get("/journal-superadmin")
async def journal_du_super_admin(du: str = "", au: str = "", limit: int = 200, user: dict = Depends(get_current_user)):
    """Parcours du SUPER-ADMINISTRATEUR (connexions, pages, actions) : réservé au DG, qui contrôle ainsi l'usage des pouvoirs les plus larges."""
    if "dg" not in (user.get("roles") or []):
        raise HTTPException(status_code=403, detail="Réservé au DG")
    plage: Dict[str, str] = {}
    if du:
        plage["$gte"] = _date_fin(du) or ""
    if au:
        plage["$lt"] = (date.fromisoformat(_date_fin(au)) + timedelta(days=1)).isoformat()
    return {"journal": await _lire_journal({"at": plage} if plage else {}, limit, superadmin=True)}
