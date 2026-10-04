"""Transmission WA Universelle Liluvine — envoi WhatsApp de secours (lot 13.8).

Règle du propriétaire : ALBARKA envoie ses WhatsApp avec SES PROPRES paramètres
WABA (API WhatsApp Business de Meta, réglés dans Paramètres Admin, collection
`settings` document `_id="global"` : wa_enabled, wa_access_token,
wa_phone_number_id, wa_graph_version) quand ils existent ; À DÉFAUT, le message
part par la « Transmission WA Universelle Liluvine » : un appel HTTP signé vers
SAWALI, qui l'envoie avec son propre compte WhatsApp.

Protocole v2 (côté émetteur) :
  POST {LILUVINE_WA_URL}
  En-têtes : Content-Type, X-Emetteur, X-Timestamp (secondes epoch UTC),
             X-Signature = hex(HMAC-SHA256(LILUVINE_WA_HMAC, f"{timestamp}.{corps_brut}"))
  Corps : {"id": uuid4, "to": "+226…", "message": "texte", "source": "Cabinet ALBARKA"}
  Délai 15 s ; un seul nouvel essai (même id, nouvelle signature) sur erreur
  réseau ou réponse 5xx, jamais sur 4xx.

Variables d'environnement (service albarka-backend sur Render) :
  LILUVINE_WA_URL       adresse du point d'entrée SAWALI (saisie par le propriétaire)
  LILUVINE_WA_HMAC      clé secrète propre à ALBARKA (saisie par le propriétaire)
  LILUVINE_WA_EMETTEUR  code émetteur, « albarka » par défaut
Si l'URL ou la clé manque, la transmission est simplement désactivée
(résultat d'erreur clair, jamais d'exception).

Sécurité : la clé et le texte complet des messages ne sont JAMAIS journalisés.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("albarka.transmission_wa")

# Délai maximal d'un appel vers SAWALI (protocole : 15 secondes).
DELAI_SECONDES = 15.0
# Longueur maximale d'un message accepté par SAWALI.
LONGUEUR_MAX = 4096
# Libellé de l'émetteur affiché au destinataire quand rien n'est précisé.
SOURCE_PAR_DEFAUT = "Cabinet ALBARKA"
# Code émetteur par défaut (identique à la valeur fixée dans render.yaml).
EMETTEUR_PAR_DEFAUT = "albarka"


# ---------------------------------------------------------------------------
# Lecture de la configuration (variables d'environnement)
# ---------------------------------------------------------------------------
def _config_liluvine() -> Optional[Dict[str, str]]:
    """Renvoie {url, cle, emetteur} si la transmission universelle est
    configurée, sinon None. Lue à chaque appel : une variable saisie sur
    Render est prise en compte au redémarrage sans autre réglage."""
    url = (os.environ.get("LILUVINE_WA_URL") or "").strip()
    cle = (os.environ.get("LILUVINE_WA_HMAC") or "").strip()
    if not url or not cle:
        return None
    emetteur = (os.environ.get("LILUVINE_WA_EMETTEUR") or EMETTEUR_PAR_DEFAUT).strip() or EMETTEUR_PAR_DEFAUT
    return {"url": url, "cle": cle, "emetteur": emetteur}


def liluvine_configure() -> bool:
    """Vrai si LILUVINE_WA_URL et LILUVINE_WA_HMAC sont renseignées."""
    return _config_liluvine() is not None


def emetteur() -> str:
    """Code émetteur annoncé à SAWALI (jamais secret)."""
    return (os.environ.get("LILUVINE_WA_EMETTEUR") or EMETTEUR_PAR_DEFAUT).strip() or EMETTEUR_PAR_DEFAUT


async def waba_configure() -> bool:
    """Vrai si les paramètres WhatsApp propres d'ALBARKA (WABA) sont utilisables :
    WhatsApp activé + jeton + identifiant du numéro (même règle que l'envoi de base)."""
    try:
        from albarka_notifications import _get_wa_config
        return bool(await _get_wa_config())
    except Exception:  # noqa: BLE001 — base indisponible : on considère « non configuré »
        return False


# ---------------------------------------------------------------------------
# Signature HMAC (protocole v2)
# ---------------------------------------------------------------------------
def signer(cle: str, horodatage: str, corps_brut: str) -> str:
    """hex(HMAC-SHA256(cle, f"{horodatage}.{corps_brut}")) — corps_brut est
    EXACTEMENT la chaîne envoyée dans la requête."""
    message = f"{horodatage}.{corps_brut}".encode("utf-8")
    return hmac.new(cle.encode("utf-8"), message, hashlib.sha256).hexdigest()


def _numero_masque(numero: str) -> str:
    """Numéro partiellement masqué pour les journaux (ex. +2267000****)."""
    n = numero or ""
    return n[:-4] + "****" if len(n) > 4 else "****"


def _resultat(ok: bool, canal: Optional[str], message_id: Any = None, erreur: Optional[str] = None,
              **extra: Any) -> Dict[str, Any]:
    """Forme de résultat uniforme de toutes les fonctions publiques du module."""
    res = {"ok": ok, "canal": canal, "message_id": message_id, "erreur": erreur}
    res.update(extra)
    return res


# ---------------------------------------------------------------------------
# Envoi par la Transmission WA Universelle (SAWALI)
# ---------------------------------------------------------------------------
async def envoyer_liluvine(numero: str, message: str, *, source: Optional[str] = None,
                           id_message: Optional[str] = None) -> Dict[str, Any]:
    """Envoie UN message texte (4 096 caractères au plus) par SAWALI.

    Résultat : {"ok", "canal": "liluvine", "message_id", "erreur", "statut"}.
    Ne lève jamais d'exception."""
    cfg = _config_liluvine()
    if not cfg:
        return _resultat(False, None, erreur="Transmission WA Universelle non configurée "
                                             "(LILUVINE_WA_URL / LILUVINE_WA_HMAC absentes)", statut=None)
    numero = (numero or "").strip()
    if not numero.startswith("+"):
        return _resultat(False, "liluvine", erreur="Numéro attendu au format international (+226…)", statut=None)
    if not (message or "").strip():
        return _resultat(False, "liluvine", erreur="Message vide", statut=None)

    # Corps sérialisé UNE SEULE FOIS : c'est cette chaîne exacte qui est signée
    # puis envoyée (même corps, donc même id, au nouvel essai).
    corps = {
        "id": id_message or str(uuid.uuid4()),
        "to": numero,
        "message": message[:LONGUEUR_MAX],
        "source": (source or SOURCE_PAR_DEFAUT).strip() or SOURCE_PAR_DEFAUT,
    }
    corps_brut = json.dumps(corps, ensure_ascii=False, separators=(",", ":"))

    derniere_erreur = None
    dernier_statut = None
    # Deux tentatives au plus : la première, puis un seul nouvel essai sur
    # erreur réseau ou 5xx (jamais sur 4xx : la demande elle-même est refusée).
    for tentative in (1, 2):
        horodatage = str(int(time.time()))  # nouvel horodatage => nouvelle signature
        entetes = {
            "Content-Type": "application/json",
            "X-Emetteur": cfg["emetteur"],
            "X-Timestamp": horodatage,
            "X-Signature": signer(cfg["cle"], horodatage, corps_brut),
        }
        try:
            async with httpx.AsyncClient(timeout=DELAI_SECONDES) as client:
                rep = await client.post(cfg["url"], content=corps_brut.encode("utf-8"), headers=entetes)
        except httpx.HTTPError as exc:
            # Erreur réseau (délai dépassé, connexion refusée…) : on réessaie une fois.
            derniere_erreur = f"Erreur réseau vers la transmission universelle : {type(exc).__name__}"
            dernier_statut = None
            logger.warning("Transmission WA vers %s : erreur réseau (essai %d)", _numero_masque(numero), tentative)
            continue
        except Exception as exc:  # noqa: BLE001 — jamais d'exception vers l'appelant
            derniere_erreur = f"Erreur inattendue : {type(exc).__name__}"
            logger.warning("Transmission WA vers %s : erreur inattendue %s", _numero_masque(numero), type(exc).__name__)
            break

        dernier_statut = rep.status_code
        # Lecture prudente de la réponse JSON (peut être absente ou invalide).
        try:
            donnees = rep.json() if rep.content else {}
        except ValueError:
            donnees = {}
        if not isinstance(donnees, dict):
            donnees = {}

        if 200 <= rep.status_code < 300 and donnees.get("ok", True):
            logger.info("Transmission WA vers %s : acceptée (id %s)", _numero_masque(numero), corps["id"])
            return _resultat(True, "liluvine", message_id=donnees.get("message_id") or corps["id"],
                             statut=rep.status_code, id=corps["id"], doublon=bool(donnees.get("doublon")))

        detail = donnees.get("detail") or donnees.get("erreur") or donnees.get("error") or ""
        derniere_erreur = f"Transmission universelle : HTTP {rep.status_code}" + (f" — {str(detail)[:200]}" if detail else "")
        logger.warning("Transmission WA vers %s : HTTP %s (essai %d)", _numero_masque(numero), rep.status_code, tentative)
        if rep.status_code < 500:
            break  # 4xx (ou 2xx avec ok=false) : pas de nouvel essai

    return _resultat(False, "liluvine", erreur=derniere_erreur, statut=dernier_statut, id=corps["id"])


async def envoyer_liluvine_long(numero: str, message: str, *, source: Optional[str] = None) -> Dict[str, Any]:
    """Comme envoyer_liluvine, mais découpe un message > 4 096 caractères en
    plusieurs envois successifs (même découpage que l'envoi WABA). Renvoie en
    plus "message_ids" (un identifiant par segment)."""
    from albarka_notifications import _wa_split_long_text
    ids = []
    res: Dict[str, Any] = _resultat(False, None, erreur="Message vide")
    for segment in _wa_split_long_text(message or "", LONGUEUR_MAX):
        res = await envoyer_liluvine(numero, segment, source=source)
        if not res.get("ok"):
            break
        ids.append(res.get("message_id"))
    res["message_ids"] = ids
    if ids:
        res["message_id"] = ids[0]
    return res


# ---------------------------------------------------------------------------
# Point d'entrée unique : WABA propre si configuré, sinon transmission universelle
# ---------------------------------------------------------------------------
async def envoyer_whatsapp(numero: str, message: str, *, source: Optional[str] = None) -> Dict[str, Any]:
    """Envoie un WhatsApp texte.

    1. Paramètres WABA d'ALBARKA configurés : envoi par l'API Meta (code
       existant send_whatsapp, comportement inchangé) ;
    2. sinon : Transmission WA Universelle Liluvine (SAWALI).

    Résultat uniforme : {"ok", "canal": "waba"|"liluvine"|None, "message_id", "erreur"}.
    Ne lève jamais d'exception."""
    try:
        if await waba_configure():
            from albarka_notifications import send_whatsapp
            r = await send_whatsapp(to_phone=numero, message=message)
            return _resultat(bool(r.get("ok")), "waba", message_id=r.get("message_id"),
                             erreur=None if r.get("ok") else (r.get("error") or r.get("kind")))
        return await envoyer_liluvine_long(numero, message, source=source)
    except Exception as exc:  # noqa: BLE001 — filet de sécurité
        logger.warning("Envoi WhatsApp vers %s impossible : %s", _numero_masque(numero), type(exc).__name__)
        return _resultat(False, None, erreur=f"Erreur inattendue : {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Repli utilisé par l'envoi de base (albarka_notifications) quand le WABA
# n'est pas configuré : renvoie la même forme que send_whatsapp().
# ---------------------------------------------------------------------------
async def repli_send_whatsapp(to_phone: str, message: str) -> Optional[Dict[str, Any]]:
    """Si la transmission universelle est configurée, envoie le message par
    SAWALI et renvoie un dictionnaire au format de send_whatsapp() (avec
    "canal": "liluvine"). Sinon renvoie None (l'appelant garde son échec
    « not_configured » d'origine)."""
    if not liluvine_configure():
        return None
    r = await envoyer_liluvine_long(to_phone, message)
    return {
        "ok": bool(r.get("ok")), "message_id": r.get("message_id"),
        "message_ids": r.get("message_ids") or [], "status": r.get("statut"),
        "error": None if r.get("ok") else r.get("erreur"),
        "kind": "success" if r.get("ok") else "http_error",
        # SAWALI gère lui-même la fenêtre de 24 h (modèle ou texte) : sans objet ici.
        "outside_24h_window": None, "canal": "liluvine",
    }


# ---------------------------------------------------------------------------
# Routes super-admin : état et message de test
# (compte admin@sawalismartsystems.com uniquement, voir require_super_admin)
# ---------------------------------------------------------------------------
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from albarka_sauvegarde import require_super_admin  # noqa: E402

router = APIRouter(prefix="/_admin/transmission-wa", tags=["Transmission WhatsApp (lot 13.8)"])

MESSAGE_TEST = "Test de transmission WhatsApp depuis ALBARKA"


class DemandeTest(BaseModel):
    """Corps de POST /test : numéro international du destinataire."""
    numero: str


@router.get("/etat")
async def etat_transmission(user: dict = Depends(require_super_admin)):
    """État des deux canaux WhatsApp. Ne renvoie JAMAIS la clé ni l'URL."""
    return {
        "waba_configure": await waba_configure(),
        "liluvine_configure": liluvine_configure(),
        "emetteur": emetteur(),
    }


@router.post("/test")
async def test_transmission(demande: DemandeTest, user: dict = Depends(require_super_admin)):
    """Envoie « Test de transmission WhatsApp depuis ALBARKA » au numéro
    indiqué, par le canal que la règle choisit (WABA propre, sinon Liluvine)."""
    numero = (demande.numero or "").strip().replace(" ", "")
    if not numero.startswith("+") or len(numero) < 8:
        raise HTTPException(status_code=400, detail="Numéro attendu au format international (+226…)")
    return await envoyer_whatsapp(numero, MESSAGE_TEST)
