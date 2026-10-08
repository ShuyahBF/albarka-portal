"""Transmission WA Universelle Liluvine — envoi WhatsApp de secours (lots 13.8 et 13.9).

Lot 13.9 (protocole v3) : médias et documents (champ « media », 10 Mo au plus),
retours de SAWALI (POST /api/webhooks/liluvine-retour : statuts, réponses des
clients posées dans la boîte WhatsApp, désinscriptions), refus 409 « désinscrit »
traité comme échec définitif, et repli par Liluvine quand le WABA propre échoue.

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

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
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
# Accès à la base (lu à chaque appel : les tests peuvent remplacer db.db)
# ---------------------------------------------------------------------------
def _base():
    """Base MongoDB courante (module db), ou None si indisponible."""
    try:
        import db as db_module
        return db_module.db
    except Exception:  # noqa: BLE001 — base absente : on continue sans journal
        return None


def _maintenant_iso() -> str:
    """Date/heure courante UTC au format ISO (même format que le reste d'ALBARKA)."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Médias (protocole v3, section 1)
# ---------------------------------------------------------------------------
# Taille maximale d'un fichier transmis en octets (avant encodage base64).
MEDIA_MAX_OCTETS = 10 * 1024 * 1024
# Types de média acceptés par SAWALI.
TYPES_MEDIA = ("document", "image", "video", "audio")


def type_media_depuis_mime(mime: Optional[str]) -> str:
    """Type WhatsApp déduit du type MIME (image/…, video/…, audio/…, sinon document)."""
    m = (mime or "").lower()
    for prefixe in ("image", "video", "audio"):
        if m.startswith(prefixe + "/"):
            return prefixe
    return "document"


def preparer_media(media: Optional[Dict[str, Any]]) -> tuple:
    """Vérifie et convertit le média de l'appelant au format du protocole.

    Entrée : {"type", "url" | "contenu" (octets), "nom_fichier", "mime", "legende"}.
    Sortie : (media_protocole | None, erreur | None). Aucun appel réseau ici :
    un fichier de plus de 10 Mo est refusé localement avec une erreur claire."""
    if not media:
        return None, None
    if not isinstance(media, dict):
        return None, "Média invalide (dictionnaire attendu)"
    url = (media.get("url") or "").strip() if isinstance(media.get("url"), str) else ""
    contenu = media.get("contenu")
    # Exactement un des deux : lien OU octets.
    if bool(url) == (contenu is not None):
        return None, "Média : fournir exactement un lien (url) OU un contenu (octets)"
    mime = (media.get("mime") or "").strip() or "application/octet-stream"
    type_media = (media.get("type") or "").strip() or type_media_depuis_mime(mime)
    if type_media not in TYPES_MEDIA:
        return None, f"Type de média inconnu : {type_media}"
    sortie: Dict[str, Any] = {"type": type_media}
    if url:
        if not url.lower().startswith("https://"):
            return None, "Lien du média attendu en HTTPS"
        sortie["url"] = url
    else:
        if isinstance(contenu, str):
            contenu = contenu.encode("utf-8")
        if not isinstance(contenu, (bytes, bytearray)) or not contenu:
            return None, "Contenu du média vide ou invalide"
        if len(contenu) > MEDIA_MAX_OCTETS:
            return None, (f"Fichier trop volumineux pour la transmission WhatsApp "
                          f"({len(contenu) / 1048576:.1f} Mo, 10 Mo au plus)")
        sortie["contenu_base64"] = base64.b64encode(bytes(contenu)).decode("ascii")
    sortie["nom_fichier"] = (media.get("nom_fichier") or "fichier").strip()[:200] or "fichier"
    sortie["mime"] = mime
    if (media.get("legende") or "").strip():
        sortie["legende"] = media["legende"].strip()[:1024]
    return sortie, None


# ---------------------------------------------------------------------------
# Journal des envois Liluvine (collection `liluvine_envois`) : permet de
# mettre à jour l'état d'un envoi quand SAWALI renvoie un statut.
# ---------------------------------------------------------------------------
async def _journaliser_envoi(corps: Dict[str, Any], res: Dict[str, Any], canal: str) -> None:
    """Enregistre l'envoi (sans le texte complet ni le média). Jamais bloquant."""
    base = _base()
    if base is None:
        return
    try:
        await base.liluvine_envois.update_one(
            {"id": corps["id"]},
            {"$set": {
                "id": corps["id"], "numero": corps["to"], "canal": canal,
                "ok": bool(res.get("ok")), "statut": "accepte" if res.get("ok") else "echec",
                "message_id": res.get("message_id"), "erreur": res.get("erreur"),
                "media_type": (corps.get("media") or {}).get("type"),
                "media_mode": res.get("media_mode"), "envoye_le": _maintenant_iso(),
            }},
            upsert=True,
        )
    except Exception:  # noqa: BLE001
        logger.warning("Journal liluvine_envois indisponible")


async def _enregistrer_retour(cle: str, document: Dict[str, Any]) -> bool:
    """Insère un retour dans `liluvine_retours` s'il n'existe pas déjà (clé
    d'idempotence `cle`). Renvoie True si c'est un nouveau retour."""
    base = _base()
    if base is None:
        return False
    doc = dict(document)
    doc["cle"] = cle
    doc.setdefault("recu_le", _maintenant_iso())
    res = await base.liluvine_retours.update_one({"cle": cle}, {"$setOnInsert": doc}, upsert=True)
    return res.upserted_id is not None


# ---------------------------------------------------------------------------
# Envoi par la Transmission WA Universelle (SAWALI)
# ---------------------------------------------------------------------------
async def envoyer_liluvine(numero: str, message: str, *, source: Optional[str] = None,
                           id_message: Optional[str] = None, media: Optional[Dict[str, Any]] = None,
                           canal: str = "liluvine") -> Dict[str, Any]:
    """Envoie UN message texte (4 096 caractères au plus), avec un média
    facultatif (protocole v3), par SAWALI.

    Résultat : {"ok", "canal", "message_id", "erreur", "statut", "media_mode",
    "definitif", "desinscrit"}. `canal` vaut « liluvine » ou « liluvine_repli »
    (repli après échec du WABA). Ne lève jamais d'exception."""
    cfg = _config_liluvine()
    if not cfg:
        return _resultat(False, None, erreur="Transmission WA Universelle non configurée "
                                             "(LILUVINE_WA_URL / LILUVINE_WA_HMAC absentes)", statut=None)
    # Lot 20 : numéro au format +226… ; envoi du super-admin → numéro WhatsApp de test (jamais le client)
    from albarka_envoi_test import numero_effectif
    from albarka_models import numero_international_wa
    numero, refus = await numero_effectif(numero_international_wa(numero) or (numero or "").strip())
    if refus:
        return _resultat(False, canal, erreur=refus, statut=None, definitif=True)
    numero = (numero or "").strip()
    if not numero.startswith("+"):
        return _resultat(False, canal, erreur="Numéro attendu au format international (+226…)", statut=None)
    if not (message or "").strip():
        return _resultat(False, canal, erreur="Message vide", statut=None)
    # Média : vérifié AVANT tout appel (refus local au-delà de 10 Mo).
    media_protocole, erreur_media = preparer_media(media)
    if erreur_media:
        return _resultat(False, canal, erreur=erreur_media, statut=None, definitif=True)

    # Corps sérialisé UNE SEULE FOIS : c'est cette chaîne exacte qui est signée
    # puis envoyée (même corps, donc même id, au nouvel essai).
    corps: Dict[str, Any] = {
        "id": id_message or str(uuid.uuid4()),
        "to": numero,
        "message": message[:LONGUEUR_MAX],
        "source": (source or SOURCE_PAR_DEFAUT).strip() or SOURCE_PAR_DEFAUT,
    }
    if media_protocole:
        corps["media"] = media_protocole
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
            res = _resultat(True, canal, message_id=donnees.get("message_id") or corps["id"],
                            statut=rep.status_code, id=corps["id"], doublon=bool(donnees.get("doublon")))
            if media_protocole:
                # Mode d'envoi du média choisi par SAWALI : direct | modele | lien.
                res["media_mode"] = donnees.get("media_mode")
            await _journaliser_envoi(corps, res, canal)
            return res

        detail = donnees.get("detail") or donnees.get("erreur") or donnees.get("error") or ""
        derniere_erreur = f"Transmission universelle : HTTP {rep.status_code}" + (f" — {str(detail)[:200]}" if detail else "")
        logger.warning("Transmission WA vers %s : HTTP %s (essai %d)", _numero_masque(numero), rep.status_code, tentative)

        # Section 3 (v3) — 409 : destinataire désinscrit chez SAWALI (STOP).
        # Échec DÉFINITIF : aucun nouvel essai, trace dans liluvine_retours.
        if rep.status_code == 409:
            try:
                await _enregistrer_retour(f"refus_desinscrit:{corps['id']}", {
                    "type": "refus_desinscrit", "id_origine": corps["id"], "numero": numero,
                    "statut": "refuse", "texte": None, "date": _maintenant_iso(),
                })
            except Exception:  # noqa: BLE001
                logger.warning("Trace du refus 409 impossible")
            res = _resultat(False, canal, erreur="Destinataire désinscrit (il a répondu STOP) — "
                                                 "réinscription à faire dans SAWALI",
                            statut=409, id=corps["id"], definitif=True, desinscrit=True)
            await _journaliser_envoi(corps, res, canal)
            return res
        if rep.status_code < 500:
            break  # 4xx (ou 2xx avec ok=false) : pas de nouvel essai

    res = _resultat(False, canal, erreur=derniere_erreur, statut=dernier_statut, id=corps["id"],
                    definitif=bool(dernier_statut and dernier_statut < 500))
    await _journaliser_envoi(corps, res, canal)
    return res


async def envoyer_liluvine_long(numero: str, message: str, *, source: Optional[str] = None,
                                canal: str = "liluvine") -> Dict[str, Any]:
    """Comme envoyer_liluvine, mais découpe un message > 4 096 caractères en
    plusieurs envois successifs (même découpage que l'envoi WABA). Renvoie en
    plus "message_ids" (un identifiant par segment)."""
    from albarka_notifications import _wa_split_long_text
    ids = []
    res: Dict[str, Any] = _resultat(False, None, erreur="Message vide")
    for segment in _wa_split_long_text(message or "", LONGUEUR_MAX):
        res = await envoyer_liluvine(numero, segment, source=source, canal=canal)
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
async def envoyer_whatsapp(numero: str, message: str, *, source: Optional[str] = None,
                           media: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Envoie un WhatsApp texte, avec un média facultatif (protocole v3) :
    media = {"type", "url" | "contenu" (octets), "nom_fichier", "mime", "legende"}.

    1. Paramètres WABA d'ALBARKA configurés : envoi par l'API Meta ; en cas
       d'échec (hors numéro invalide), repli par Liluvine (« liluvine_repli ») ;
    2. sinon : Transmission WA Universelle Liluvine (SAWALI).

    Résultat uniforme : {"ok", "canal": "waba"|"liluvine"|"liluvine_repli"|None,
    "message_id", "erreur"}. Ne lève jamais d'exception."""
    try:
        # Média vérifié localement d'abord (> 10 Mo refusé sans aucun appel).
        if media:
            _m, erreur_media = preparer_media(media)
            if erreur_media:
                return _resultat(False, None, erreur=erreur_media, definitif=True)
        if await waba_configure():
            if media:
                from albarka_notifications import send_whatsapp_fichier
                r = await send_whatsapp_fichier(
                    to_phone=numero, data=media.get("contenu"), url=media.get("url"),
                    filename=media.get("nom_fichier") or "fichier",
                    content_type=media.get("mime") or "application/octet-stream",
                    caption=media.get("legende") or message,
                )
            else:
                from albarka_notifications import send_whatsapp
                r = await send_whatsapp(to_phone=numero, message=message)
            return _resultat(bool(r.get("ok")), r.get("canal") or "waba", message_id=r.get("message_id"),
                             erreur=None if r.get("ok") else (r.get("error") or r.get("kind")))
        if media:
            return await envoyer_liluvine(numero, message, source=source, media=media)
        return await envoyer_liluvine_long(numero, message, source=source)
    except Exception as exc:  # noqa: BLE001 — filet de sécurité
        logger.warning("Envoi WhatsApp vers %s impossible : %s", _numero_masque(numero), type(exc).__name__)
        return _resultat(False, None, erreur=f"Erreur inattendue : {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Repli utilisé par l'envoi de base (albarka_notifications) : WABA absent, ou
# WABA en échec (section 4). Renvoie la même forme que send_whatsapp().
# ---------------------------------------------------------------------------
def _au_format_send_whatsapp(r: Dict[str, Any], *, outside: Optional[bool] = None) -> Dict[str, Any]:
    """Convertit un résultat de ce module au format de send_whatsapp()."""
    return {
        "ok": bool(r.get("ok")), "message_id": r.get("message_id"),
        "message_ids": r.get("message_ids") or ([r["message_id"]] if r.get("ok") and r.get("message_id") else []),
        "status": r.get("statut"),
        "error": None if r.get("ok") else r.get("erreur"),
        "kind": "success" if r.get("ok") else ("unsubscribed" if r.get("desinscrit") else "http_error"),
        # SAWALI gère lui-même la fenêtre de 24 h ; on garde l'information
        # du WABA quand le repli suit un échec du WABA.
        "outside_24h_window": outside, "canal": r.get("canal") or "liluvine",
        "media_mode": r.get("media_mode"), "definitif": bool(r.get("definitif")),
        "desinscrit": bool(r.get("desinscrit")),
    }


async def repli_send_whatsapp(to_phone: str, message: str, *, media: Optional[Dict[str, Any]] = None,
                              canal: str = "liluvine", outside: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    """Si la transmission universelle est configurée, envoie le message (et
    le média éventuel) par SAWALI et renvoie un dictionnaire au format de
    send_whatsapp() (avec "canal"). Sinon renvoie None (l'appelant garde son
    échec d'origine)."""
    if not liluvine_configure():
        return None
    if media:
        r = await envoyer_liluvine(to_phone, message, media=media, canal=canal)
    else:
        r = await envoyer_liluvine_long(to_phone, message, canal=canal)
    return _au_format_send_whatsapp(r, outside=outside)


# Erreurs « numéro invalide » : PAS de repli (le numéro ne marchera nulle part).
_MOTIF_NUMERO_INVALIDE = re.compile(
    r"invalid_phone|numéro invalide|"
    r"(invalid|not a valid|incorrect)[^\"]{0,40}(phone|number|recipient|wa_id)|"
    r"(phone|number|recipient)[^\"]{0,40}(is invalid|not valid|invalid)",
    re.IGNORECASE,
)


def erreur_numero_invalide(resultat: Dict[str, Any]) -> bool:
    """Vrai si l'échec du WABA vient du numéro lui-même (pas de repli)."""
    if (resultat or {}).get("kind") == "invalid_phone":
        return True
    texte = str((resultat or {}).get("error") or "")
    return bool(_MOTIF_NUMERO_INVALIDE.search(texte))


async def repli_apres_echec_waba(to_phone: str, message: str, resultat_waba: Dict[str, Any], *,
                                 media: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Section 4 (v3) — le WABA d'ALBARKA a échoué (fenêtre de 24 h fermée,
    modèle requis — codes Meta 131047, 131026, 470 —, ou toute autre panne non
    liée au numéro) : on réessaie par Liluvine, même texte et même média,
    canal « liluvine_repli ». Renvoie None si pas de repli (succès du WABA,
    numéro invalide, ou transmission universelle non configurée)."""
    if not resultat_waba or resultat_waba.get("ok"):
        return None
    if erreur_numero_invalide(resultat_waba) or not liluvine_configure():
        return None
    logger.info("WABA en échec vers %s (%s) : repli par la transmission universelle",
                _numero_masque(to_phone), resultat_waba.get("kind"))
    repli = await repli_send_whatsapp(to_phone, message, media=media, canal="liluvine_repli",
                                      outside=resultat_waba.get("outside_24h_window"))
    if repli is not None:
        # On garde la cause de l'échec du WABA pour le diagnostic.
        repli["echec_waba"] = {"kind": resultat_waba.get("kind"), "status": resultat_waba.get("status")}
    return repli

# ---------------------------------------------------------------------------
# Routes super-admin : état et message de test
# (compte admin@sawalismartsystems.com uniquement, voir require_super_admin)
# ---------------------------------------------------------------------------
from fastapi import APIRouter, Depends, HTTPException  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from albarka_sauvegarde import require_super_admin  # noqa: E402

router = APIRouter(prefix="/_admin/transmission-wa", tags=["Transmission WhatsApp (lots 13.8 et 13.9)"])

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


# ---------------------------------------------------------------------------
# Retours de SAWALI (protocole v3, sections 2 et 3)
#   POST /api/webhooks/liluvine-retour  (public, signé avec LILUVINE_WA_HMAC)
#   GET  /api/_admin/transmission-wa/retours  (super-admin, 100 derniers)
# ---------------------------------------------------------------------------
from fastapi import Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402

# Fenêtre de validité de l'horodatage d'un retour : ± 5 minutes.
FENETRE_RETOUR_SECONDES = 300

# Route publique : routeur distinct (pas de contrôle de session, la
# signature HMAC tient lieu d'authentification).
retour_router = APIRouter(prefix="/webhooks", tags=["Transmission WhatsApp — retours (lot 13.9)"])


def verifier_signature_retour(horodatage: Optional[str], signature: Optional[str], corps_brut: bytes) -> Optional[str]:
    """Contrôle d'un retour SAWALI. Renvoie None si valide, sinon le motif du refus."""
    cfg = _config_liluvine()
    if not cfg:
        return "Transmission non configurée"
    try:
        ts = int((horodatage or "").strip())
    except ValueError:
        return "Horodatage absent ou invalide"
    # Fenêtre ± 5 min : protège contre le rejeu d'un ancien retour.
    if abs(time.time() - ts) > FENETRE_RETOUR_SECONDES:
        return "Horodatage hors fenêtre (± 5 min)"
    try:
        texte = corps_brut.decode("utf-8")
    except UnicodeDecodeError:
        return "Corps illisible"
    attendu = signer(cfg["cle"], str(ts), texte)
    # Comparaison à temps constant (hmac.compare_digest).
    if not hmac.compare_digest(attendu, (signature or "").strip().lower()):
        return "Signature invalide"
    return None


def _date_iso(valeur: Any) -> str:
    """Date ISO reçue de SAWALI normalisée en UTC (format ALBARKA) ; à défaut, maintenant."""
    try:
        dt = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError):
        return _maintenant_iso()


def _numero(valeur: Any) -> str:
    """Numéro international « +226… » (ajoute le + s'il manque)."""
    n = str(valeur or "").strip().replace(" ", "")
    return n if not n or n.startswith("+") else f"+{n}"


async def _poser_reponse_dans_boite(base, retour: Dict[str, Any], cle: str) -> None:
    """La réponse du client apparaît dans la boîte WhatsApp d'ALBARKA
    (collection wa_messages, mêmes champs qu'un message entrant du webhook
    Meta), marquée « via Liluvine » (via_liluvine / canal)."""
    import secrets as _secrets
    from albarka_wa_inbox import _resolve_contact
    phone = retour["numero"]
    media = retour.get("media") or {}
    media_kind = media.get("type") if isinstance(media, dict) else None
    doc = {
        "id": _secrets.token_urlsafe(12),
        "direction": "inbound",
        "phone": phone,
        # Identifiant unique : la boîte déduplique déjà par wa_message_id.
        "wa_message_id": f"liluvine:{cle}",
        "message_type": media_kind or "text",
        "body": retour.get("texte") or "",
        "media_url": media.get("url_temporaire") if media_kind else None,
        "media_mime": media.get("mime") if media_kind else None,
        "media_kind": media_kind,
        "media_filename": media.get("nom_fichier") if media_kind else None,
        "voice_note_transcript": None,
        "created_at": retour["date"],
        "read_by_staff_at": None,
        "profile_name": None,
        "via_liluvine": True,
        "canal": "liluvine",
        "liluvine_id_origine": retour.get("id_origine"),
    }
    try:
        contact_id, contact_name = await _resolve_contact(phone)
    except Exception:  # noqa: BLE001
        contact_id, contact_name = None, None
    doc["contact_id"] = contact_id
    doc["contact_name"] = contact_name
    await base.wa_messages.insert_one(dict(doc))
    # Comme pour le webhook Meta : une conversation « résolue » repasse « à traiter ».
    etiquette = await base.wa_conversation_labels.find_one({"phone": phone}, {"_id": 0, "label": 1})
    if etiquette and etiquette.get("label") == "resolved":
        await base.wa_conversation_labels.update_one(
            {"phone": phone},
            {"$set": {"phone": phone, "label": "todo", "updated_at": _maintenant_iso(),
                      "updated_by": "system:auto_reopen", "updated_by_name": "Réouverture automatique"}},
            upsert=True,
        )
    # Signalement aux administrateurs : la boîte WhatsApp (badge « non lus »)
    # et le journal du serveur — aucun WhatsApp n'est réenvoyé.
    logger.info("Réponse WhatsApp reçue via Liluvine de %s (boîte WhatsApp)", _numero_masque(phone))


async def _appliquer_statut(base, retour: Dict[str, Any]) -> None:
    """Met à jour l'état de l'envoi d'origine (journal liluvine_envois et
    message sortant de la boîte WhatsApp)."""
    ids = [v for v in (retour.get("id_origine"), retour.get("message_id")) if v]
    if not ids:
        return
    maj = {"statut": retour["statut"], "statut_le": retour["date"], "erreur_statut": retour.get("erreur")}
    await base.liluvine_envois.update_many({"$or": [{"id": {"$in": ids}}, {"message_id": {"$in": ids}}]},
                                           {"$set": maj})
    await base.wa_messages.update_many(
        {"direction": "outbound", "wa_message_id": {"$in": ids}},
        {"$set": {"wa_status": retour["statut"], "wa_status_at": retour["date"],
                  "wa_status_error": retour.get("erreur")}},
    )


async def traiter_retour(corps: Dict[str, Any]) -> Dict[str, Any]:
    """Enregistre un retour déjà authentifié. Idempotent : clé =
    (type, id | message_id | numéro + date) ; un doublon ne fait rien."""
    base = _base()
    if base is None:
        return {"ok": False, "erreur": "Base indisponible"}
    type_retour = str(corps.get("type") or "").strip()
    date = _date_iso(corps.get("date"))
    if type_retour == "statut":
        statut = str(corps.get("statut") or "").strip()
        ref = corps.get("id") or corps.get("message_id")
        if not ref or statut not in ("sent", "delivered", "read", "failed"):
            return {"ok": False, "erreur": "Statut incomplet"}
        # Le statut fait partie de la clé : « sent » puis « delivered » = deux retours.
        cle = f"statut:{ref}:{statut}"
        retour = {"type": "statut", "id_origine": corps.get("id"), "message_id": corps.get("message_id"),
                  "numero": None, "statut": statut, "erreur": corps.get("erreur"), "texte": None, "date": date}
    elif type_retour == "reponse":
        de = _numero(corps.get("de"))
        if not de:
            return {"ok": False, "erreur": "Réponse sans numéro"}
        cle = f"reponse:{de}:{date}"
        retour = {"type": "reponse", "id_origine": corps.get("id_origine"), "numero": de, "statut": None,
                  "texte": str(corps.get("texte") or "")[:8000], "date": date,
                  "media": corps.get("media") if isinstance(corps.get("media"), dict) else None}
    elif type_retour == "desinscription":
        de = _numero(corps.get("de"))
        if not de:
            return {"ok": False, "erreur": "Désinscription sans numéro"}
        cle = f"desinscription:{de}:{date}"
        retour = {"type": "desinscription", "id_origine": None, "numero": de, "statut": "desinscrit",
                  "texte": None, "date": date}
    else:
        return {"ok": False, "erreur": "Type de retour inconnu"}

    nouveau = await _enregistrer_retour(cle, retour)
    if not nouveau:
        return {"ok": True, "doublon": True}
    if type_retour == "statut":
        await _appliquer_statut(base, retour)
    elif type_retour == "reponse":
        await _poser_reponse_dans_boite(base, retour, cle)
    else:
        logger.info("Désinscription WhatsApp (STOP) reçue via Liluvine : %s", _numero_masque(retour["numero"]))
    return {"ok": True, "doublon": False}


async def _repondre_stats_du_jour(corps: Dict[str, Any]):
    """Réponse à {"type": "stats_du_jour", "debut", "fin"} (lot 15).

    Période absente, illisible, inversée ou > 31 jours : 422. Toute autre
    panne : 200 avec des indicateurs vides et utilisateurs_connectes à null."""
    from albarka_stats_du_jour import PeriodeInvalide, lire_periode, repondre_stats
    try:
        lire_periode(corps)
    except PeriodeInvalide as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    try:
        return await repondre_stats(_base(), corps)
    except Exception as exc:  # noqa: BLE001 — filet de sécurité : jamais de 500
        logger.warning("Statistiques du jour non calculées : %s", type(exc).__name__)
        return {"indicateurs": [], "faits_marquants": [], "utilisateurs_connectes": None}


@retour_router.post("/liluvine-retour")
async def recevoir_retour(request: Request):
    """Point d'entrée des retours SAWALI : signature HMAC + fenêtre ± 5 min
    (sinon 401), réponse rapide, idempotent."""
    corps_brut = await request.body()
    motif = verifier_signature_retour(request.headers.get("X-Timestamp"),
                                      request.headers.get("X-Signature"), corps_brut)
    if motif:
        code = 503 if motif == "Transmission non configurée" else 401
        return JSONResponse(status_code=code, content={"detail": motif})
    try:
        corps = json.loads(corps_brut.decode("utf-8"))
    except ValueError:
        return JSONResponse(status_code=422, content={"detail": "JSON invalide"})
    if not isinstance(corps, dict):
        return JSONResponse(status_code=422, content={"detail": "Objet JSON attendu"})
    # Lot 15 — demande de statistiques du jour par SAWALI (même signature,
    # même URL). Lecture seule ; période invalide -> 422 ; jamais de 500.
    if str(corps.get("type") or "").strip() == "stats_du_jour":
        return await _repondre_stats_du_jour(corps)
    try:
        res = await traiter_retour(corps)
    except Exception as exc:  # noqa: BLE001 — SAWALI réessaiera
        logger.warning("Retour Liluvine non traité : %s", type(exc).__name__)
        return JSONResponse(status_code=500, content={"detail": "Erreur interne"})
    if not res.get("ok"):
        return JSONResponse(status_code=422, content={"detail": res.get("erreur")})
    return res


async def _derniers_retours(limite: int = 100):
    """Les `limite` derniers retours (plus récents d'abord)."""
    base = _base()
    if base is None:
        return []
    return await base.liluvine_retours.find({}, {"_id": 0}).sort("recu_le", -1).to_list(limite)


@router.get("/retours")
async def retours_transmission(user: dict = Depends(require_super_admin)):
    """Les 100 derniers retours de SAWALI (statuts, réponses, désinscriptions,
    refus 409)."""
    return {"retours": await _derniers_retours(100)}


# Alias du chemin cité par le protocole (/api/admin/transmission-wa/retours),
# protégé de la même façon (super-admin uniquement).
admin_alias_router = APIRouter(prefix="/admin/transmission-wa", tags=["Transmission WhatsApp — retours (lot 13.9)"])


@admin_alias_router.get("/retours")
async def retours_transmission_alias(user: dict = Depends(require_super_admin)):
    """Même contenu que /_admin/transmission-wa/retours."""
    return {"retours": await _derniers_retours(100)}
