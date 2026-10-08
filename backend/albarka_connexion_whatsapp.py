"""Lot 16 — Connexion du personnel par WhatsApp (numéro + code PIN, puis code OTP).

Demande du propriétaire (08/10/2026) : « permettre aux personnels de ALBARKA
de se connecter à la plateforme avec leur numéro WA et y recevoir leur code
OTP » (même principe que DentalCare).

Principe :
  1. Dans « Personnels », un gestionnaire du personnel (Direction, DG,
     Administrateur, Superviseur) génère pour un collaborateur un code PIN à
     4 chiffres. Le PIN est affiché UNE SEULE FOIS (et envoyé par WhatsApp au
     collaborateur si on le demande) ; seul son hachage (bcrypt) est enregistré,
     dans une collection À PART (`pins_whatsapp`) : il ne peut donc jamais
     sortir par les listes de comptes (/clients/staff, /auth/me…).
  2. Page de connexion → « Se connecter par WhatsApp » : numéro WhatsApp +
     PIN. Si le couple est bon, un code à 6 chiffres est envoyé par WhatsApp
     à ce numéro (même canal que tous les WhatsApp d'ALBARKA : WABA propre,
     sinon Transmission WA Universelle Liluvine par SAWALI).
  3. Le code se saisit comme le code reçu par e-mail : POST /auth/verify-otp
     (liste blanche des appareils, contrat client, etc. inchangés).

Protections :
  - 5 PIN faux en 15 minutes pour un même numéro → connexion par WhatsApp de
    ce numéro suspendue 15 minutes (collection `tentatives_pin_wa`) ;
  - un code OTP saisi faux 5 fois est annulé (voir albarka_auth.verify_otp) ;
  - exclus : clients, comptes désactivés, Superviseur et compte admin du
    portail (super-administrateurs : connexion par e-mail uniquement) ;
  - le code OTP n'est JAMAIS renvoyé au navigateur (pas de « dev_otp » ici).

Lot 19 (08/10/2026, « oui étends la connexion WhatsApp aux clients ») : les CLIENTS aussi peuvent recevoir un PIN
(généré depuis « Clients » par la Direction, le DG, l'Administrateur ou le secrétariat) et se connecter par WhatsApp.

Aucune variable d'environnement nouvelle : l'envoi réutilise
albarka_transmission_wa.envoyer_whatsapp (paramètres WABA de la page
Paramètres, ou LILUVINE_WA_URL / LILUVINE_WA_HMAC déjà en place).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import (
    OTP_EXPIRE_MINUTES,
    generate_session_token,
    hash_password,
    require_roles,
    verify_password,
)
from albarka_models import (
    CLIENT_MANAGE_ROLES,
    STAFF_MANAGE_ROLES,
    LoginResponse,
    is_admin_account,
    whatsapp_number_of,
)
from albarka_recaptcha import verify_recaptcha
from albarka_transmission_wa import envoyer_whatsapp
from db import db

logger = logging.getLogger("albarka.connexion_whatsapp")

# ---------------------------------------------------------------------------
# Réglages de sécurité (mêmes valeurs que DentalCare)
# ---------------------------------------------------------------------------
# Nombre de chiffres du code PIN (demande : « sur 4 chiffres »).
LONGUEUR_PIN = 4
# Au-delà de 5 PIN faux en 15 minutes pour un même numéro, la connexion par
# WhatsApp de ce numéro est suspendue 15 minutes (essais au hasard).
ESSAIS_PIN_MAX = 5
FENETRE_ESSAIS_PIN_MINUTES = 15
# Indicatif ajouté à un numéro local à 8 chiffres (Burkina Faso).
INDICATIF_PAR_DEFAUT = "226"

# Lot 19 : rôles qui peuvent ouvrir la gestion des PIN (le contrôle fin par compte est fait dans _peut_gerer)
_GESTION_PIN_ROLES = sorted(set(STAFF_MANAGE_ROLES) | set(CLIENT_MANAGE_ROLES))

# Routeurs : la connexion (publique) sous /auth, la gestion des PIN sous /staff-pin.
auth_router = APIRouter(prefix="/auth", tags=["Authentification"])
router = APIRouter(prefix="/staff-pin", tags=["Connexion WhatsApp du personnel"])


# ---------------------------------------------------------------------------
# Fonctions communes (sans base de données, testées directement)
# ---------------------------------------------------------------------------
def generer_pin() -> str:
    """Code PIN à 4 chiffres, tiré au hasard de façon sûre (0000 à 9999)."""
    return f"{secrets.randbelow(10 ** LONGUEUR_PIN):0{LONGUEUR_PIN}d}"


def generer_code_otp() -> str:
    """Code de connexion à 6 chiffres, tiré au hasard de façon sûre."""
    return f"{secrets.randbelow(1_000_000):06d}"


def pin_valide(pin: Optional[str]) -> bool:
    """Vrai si la saisie est exactement 4 chiffres."""
    return bool(pin) and len(pin) == LONGUEUR_PIN and pin.isdigit()


def numero_international(numero: Optional[str]) -> str:
    """Normalise un numéro au format « +226XXXXXXXX ».

    « 70 11 22 33 » → « +22670112233 » ; « 00226 70… » → « +22670… » ;
    « +226 70-11-22-33 » → « +22670112233 ». Renvoie "" si le numéro est vide
    ou trop court pour être un vrai numéro."""
    chiffres = re.sub(r"\D", "", numero or "")
    if chiffres.startswith("00"):
        chiffres = chiffres[2:]
    if len(chiffres) == 8:          # numéro local burkinabè sans indicatif
        chiffres = INDICATIF_PAR_DEFAUT + chiffres
    if len(chiffres) < 9:
        return ""
    return "+" + chiffres


def numero_du_compte(user: dict) -> str:
    """Numéro WhatsApp d'un compte du personnel : numéro WhatsApp dédié s'il
    existe, sinon son téléphone (même règle que tous les envois ALBARKA)."""
    return numero_international(whatsapp_number_of(user) or "")


def motif_exclusion(user: Optional[dict]) -> Optional[str]:
    """Raison pour laquelle ce compte ne peut PAS se connecter par WhatsApp,
    ou None s'il le peut. Exclus : compte inexistant ou sans rôle, compte
    désactivé, Superviseur et compte admin du portail (super-administrateurs).
    Lot 19 : les clients sont désormais acceptés."""
    if not user:
        return "Compte introuvable"
    roles = set(user.get("roles") or [])
    if not roles:
        return "Compte sans rôle"
    if "superviseur" in roles or is_admin_account(user):
        return "Les comptes Superviseur et le compte admin du portail se connectent uniquement par e-mail"
    if not user.get("is_active", True):
        return "Ce compte est désactivé"
    return None


def _maintenant() -> datetime:
    """Date/heure courante UTC (une seule fonction : remplaçable dans les tests)."""
    return datetime.now(timezone.utc)


async def _journal(acteur: dict, action: str, cible: Optional[str], meta: dict) -> None:
    """Trace dans le journal de la plateforme (best-effort, jamais bloquant)."""
    try:
        from albarka_phase_c import _log_platform_event
        await _log_platform_event(user=acteur, action=action, entity_type="user", entity_id=cible, meta=meta)
    except Exception:  # noqa: BLE001 — le journal ne doit jamais bloquer
        logger.exception("Journal indisponible (%s)", action)


def _peut_gerer(acteur: dict, cible: dict) -> None:
    """Contrôle des droits sur la cible (lève 403/400 sinon) : un
    Administrateur ne peut être géré que par un Administrateur, le Superviseur
    ou le compte admin (même règle que la fiche du personnel).
    Lot 19 : le PIN d'un CLIENT est géré par les rôles qui gèrent les clients ; celui d'un collaborateur par les
    gestionnaires du personnel (un secrétariat ne touche donc pas au PIN d'un collaborateur)."""
    roles_acteur = set(acteur.get("roles") or [])
    autorises = CLIENT_MANAGE_ROLES if "client" in (cible.get("roles") or []) else STAFF_MANAGE_ROLES
    if "superviseur" not in roles_acteur and not (roles_acteur & set(autorises)):
        raise HTTPException(status_code=403, detail="Permission refusée")
    acteur_admin = bool(roles_acteur & {"administrateur", "superviseur"}) or is_admin_account(acteur)
    if "administrateur" in (cible.get("roles") or []) and not acteur_admin:
        raise HTTPException(status_code=403, detail="Seul un Administrateur ou le Superviseur peut gérer le PIN d'un Administrateur")
    motif = motif_exclusion(cible)
    if motif and motif != "Ce compte est désactivé":
        raise HTTPException(status_code=400, detail=motif)


# ---------------------------------------------------------------------------
# Gestion des PIN (page « Personnels »)
# ---------------------------------------------------------------------------
class DemandePin(BaseModel):
    """Corps de la génération du PIN : l'envoyer aussi par WhatsApp au collaborateur ?"""
    envoyer_whatsapp: bool = False


@router.get("")
async def lister_pins(user: dict = Depends(require_roles(_GESTION_PIN_ROLES))):
    """Comptes du personnel qui ont un PIN (identifiant et date uniquement —
    jamais le hachage). Sert à afficher « PIN actif » dans Personnels."""
    docs = await db.pins_whatsapp.find({}, {"_id": 0, "user_id": 1, "defini_le": 1, "defini_par_nom": 1}).to_list(5000)
    return docs


@router.post("/{user_id}")
async def generer_pin_personnel(user_id: str, demande: Optional[DemandePin] = None,
                                user: dict = Depends(require_roles(_GESTION_PIN_ROLES))):
    """Génère (ou remplace) le code PIN à 4 chiffres d'un collaborateur.

    Le PIN est rendu EN CLAIR une seule fois, ici, pour être remis au
    collaborateur ; seul son hachage est enregistré. Le numéro WhatsApp du
    compte doit être renseigné (le code de connexion y sera envoyé)."""
    cible = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not cible:
        raise HTTPException(status_code=404, detail="Collaborateur introuvable")
    _peut_gerer(user, cible)
    numero = numero_du_compte(cible)
    if not numero:
        raise HTTPException(status_code=400, detail=(
            "Renseignez d'abord le téléphone WhatsApp de ce collaborateur (bouton « Modifier ») : "
            "le code de connexion y sera envoyé."))

    pin = generer_pin()
    await db.pins_whatsapp.update_one(
        {"user_id": user_id},
        {"$set": {"user_id": user_id, "pin_hash": hash_password(pin), "defini_le": _maintenant().isoformat(),
                  "defini_par": user.get("id"), "defini_par_nom": user.get("full_name") or user.get("email")}},
        upsert=True,
    )

    # Envoi facultatif du PIN par WhatsApp (jamais bloquant pour la génération)
    envoye = None
    if demande and demande.envoyer_whatsapp:
        resultat = await envoyer_whatsapp(
            numero,
            f"Cabinet ALBARKA — votre code PIN de connexion par WhatsApp : {pin}. "
            "Gardez-le pour vous : il ne vous sera jamais demandé par téléphone.",
        )
        envoye = bool(resultat.get("ok"))
    await _journal(user, "pin_whatsapp.genere", user_id, {"envoye_whatsapp": envoye})
    return {"pin": pin, "numero_whatsapp": numero, "envoye_whatsapp": envoye}


@router.delete("/{user_id}")
async def retirer_pin_personnel(user_id: str, user: dict = Depends(require_roles(_GESTION_PIN_ROLES))):
    """Retire le code PIN : le collaborateur ne peut plus se connecter par WhatsApp."""
    cible = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    # Droits sur la cible (Administrateur, client / collaborateur — lot 19)
    if cible:
        _peut_gerer(user, cible)
    resultat = await db.pins_whatsapp.delete_one({"user_id": user_id})
    if resultat.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Aucun PIN pour ce collaborateur")
    await _journal(user, "pin_whatsapp.retire", user_id, {})
    return {"statut": "PIN retiré"}


# ---------------------------------------------------------------------------
# Connexion par WhatsApp (page de connexion, sans authentification)
# ---------------------------------------------------------------------------
class ConnexionWhatsapp(BaseModel):
    """Étape 1 de la connexion par WhatsApp : numéro WhatsApp et code PIN à 4 chiffres."""
    numero: str = Field(..., max_length=40)
    pin: str = Field(..., max_length=10)
    # reCAPTCHA (même règle que la connexion par e-mail ; ignoré s'il est désactivé)
    captcha_token: Optional[str] = None


@auth_router.post("/login-whatsapp", response_model=LoginResponse)
async def connexion_whatsapp(demande: ConnexionWhatsapp):
    """Numéro + PIN justes → un code à 6 chiffres est envoyé par WhatsApp.
    La connexion se termine par POST /auth/verify-otp (comme par e-mail)."""
    numero = numero_international(demande.numero)
    pin = (demande.pin or "").strip()
    refus = HTTPException(status_code=401, detail="Numéro WhatsApp ou code PIN incorrect")
    if not numero or not pin_valide(pin):
        raise refus

    # Trop d'essais de PIN faux pour ce numéro : suspension temporaire
    depuis = (_maintenant() - timedelta(minutes=FENETRE_ESSAIS_PIN_MINUTES)).isoformat()
    if await db.tentatives_pin_wa.count_documents({"numero": numero, "le": {"$gte": depuis}}) >= ESSAIS_PIN_MAX:
        raise HTTPException(status_code=429, detail=(
            f"Trop d'essais de code PIN. Réessayez dans {FENETRE_ESSAIS_PIN_MINUTES} minutes "
            "ou connectez-vous avec votre e-mail."))

    captcha = await verify_recaptcha(demande.captcha_token)
    if not captcha["success"]:
        raise HTTPException(status_code=400, detail=f"Captcha invalide ({captcha['reason']})")

    # Compte du personnel portant ce numéro et dont le PIN correspond
    trouve = None
    async for fiche in db.pins_whatsapp.find({}, {"_id": 0}):
        compte = await db.users.find_one({"id": fiche.get("user_id")}, {"_id": 0, "password_hash": 0})
        if not compte or motif_exclusion(compte) or numero_du_compte(compte) != numero:
            continue
        if fiche.get("pin_hash") and verify_password(pin, fiche["pin_hash"]):
            trouve = compte
            break
    if not trouve:
        # Essai faux mémorisé (sert au blocage 5 essais / 15 minutes)
        await db.tentatives_pin_wa.insert_one({"numero": numero, "le": _maintenant().isoformat()})
        raise refus

    # Code à 6 chiffres, même format que le code reçu par e-mail (collection otps)
    code = generer_code_otp()
    session_token = generate_session_token()
    await db.otps.insert_one({
        "id": secrets.token_urlsafe(12),
        "user_id": trouve["id"],
        "session_token": session_token,
        "code": code,
        "expires_at": (_maintenant() + timedelta(minutes=OTP_EXPIRE_MINUTES)).isoformat(),
        "used": False,
        "essais": 0,
        "mode": "whatsapp_pin",
        "created_at": _maintenant().isoformat(),
    })
    resultat = await envoyer_whatsapp(
        numero, f"Votre code de connexion ALBARKA : {code} (valable {OTP_EXPIRE_MINUTES} minutes).")
    await _journal(trouve, "login.whatsapp_code_envoye", trouve["id"], {"envoye": bool(resultat.get("ok"))})
    if not resultat.get("ok"):
        # Code inutilisable : on l'annule et on propose la connexion par e-mail
        await db.otps.update_one({"session_token": session_token}, {"$set": {"used": True, "annule": True}})
        raise HTTPException(status_code=502, detail=(
            "Le code n'a pas pu être envoyé par WhatsApp. Réessayez plus tard ou connectez-vous avec votre e-mail."))
    return LoginResponse(needs_otp=True, session_token=session_token,
                         message="Un code de vérification vous a été envoyé par WhatsApp.", dev_otp=None)
