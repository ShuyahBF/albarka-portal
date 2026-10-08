"""Lot 14 — Encaissement PI-SPI (paiement instantané BCEAO / UEMOA).

PI-SPI = Plateforme Interopérable du Système de Paiement Instantané de la
BCEAO. Le QR code PI-SPI est STANDARDISÉ et fourni par la banque du cabinet :
il contient l'« adresse de paiement » (alias), jamais un numéro de téléphone.
Son format interne n'est pas public : on ne l'invente PAS, on imprime sur les
factures le QR fourni par la banque, tel quel.

Ce module regroupe :
  1. les PARAMÈTRES GLOBAUX « Encaissement PI-SPI » (collection
     `pispi_parametres`, document unique « global ») : actif, banque,
     titulaire, adresse de paiement, QR (texte décodé OU image téléversée,
     1 Mo max, stockée dans R2 via albarka_storage), consigne ;
     modifiables par le Superviseur et la Direction seulement ;
  2. le BLOC « Payer par PI-SPI » imprimé sur les factures (données
     préparées ici, dessin dans albarka_invoice_layout) ;
  3. la collection `pispi_transactions` (encaissements PI-SPI attendus /
     reçus / rapprochés / rejetés) alimentée par la saisie manuelle d'un
     règlement en mode « PISPI » (albarka_phase_c.create_payment) ;
  4. les CONNECTEURS : interface abstraite + connecteur « manuel » (seul
     actif) + emplacements documentés pour Ecobank, UBA, BSIC, IB Bank qui
     répondent « non disponible » (aucune API bancaire n'est appelée) ;
  5. la route de NOTIFICATION de paiement, prévue mais DÉSACTIVÉE (503).

Variables d'environnement prévues (facultatives, jamais affichées) :
PISPI_FOURNISSEUR, PISPI_API_URL, PISPI_CLIENT_ID, PISPI_CLIENT_SECRET.
"""
from __future__ import annotations

import logging
import os
import secrets
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from albarka_auth import require_roles
from albarka_models import BILLING_ROLES
from albarka_storage import delete_object, get_object, put_object
from db import db

logger = logging.getLogger("albarka.pispi")

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
# Code du mode de règlement PI-SPI dans db.payments (champ "method")
METHODE_PISPI = "pispi"
# Rôles autorisés à lire / modifier les paramètres (le Superviseur passe
# toujours, voir require_roles)
PISPI_ROLES = ["superviseur", "direction"]
# Banques proposées (code -> libellé affiché)
BANQUES = {"uba": "UBA", "bsic": "BSIC", "ib_bank": "IB Bank", "ecobank": "Ecobank", "autre": "Autre"}
# Consigne imprimée par défaut sous le QR
CONSIGNE_DEFAUT = ("Payez avec l'application de votre banque ou de votre mobile money (PI-SPI). "
                   "Indiquez la référence ci-dessous.")
# Image du QR téléversée : 1 Mo maximum, PNG ou JPG
QR_TAILLE_MAX = 1024 * 1024
QR_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg"}
# Statuts possibles d'une transaction PI-SPI
STATUTS = ("attendu", "recu", "rapproche", "rejete")
# Message renvoyé par les connecteurs bancaires non encore disponibles
MESSAGE_NON_DISPONIBLE = "non disponible : API Business non homologuée / accès non obtenu"

router = APIRouter(prefix="/admin/pispi", tags=["Encaissement PI-SPI"])
notification_router = APIRouter(prefix="/pispi", tags=["Encaissement PI-SPI — notification"])


# ---------------------------------------------------------------------------
# 1. Paramètres globaux
# ---------------------------------------------------------------------------
def _parametres_vides() -> Dict[str, Any]:
    """Valeurs par défaut (encaissement PI-SPI inactif)."""
    return {"actif": False, "banque": "uba", "banque_autre": "", "titulaire": "", "adresse_paiement": "",
            "qr_contenu": "", "qr_image_path": None, "qr_image_type": None, "consigne": CONSIGNE_DEFAUT}


async def charger_parametres() -> Dict[str, Any]:
    """Paramètres PI-SPI enregistrés, complétés par les valeurs par défaut."""
    doc = await db.pispi_parametres.find_one({"_id": "global"}, {"_id": 0}) or {}
    return {**_parametres_vides(), **doc}


def libelle_banque(p: Dict[str, Any]) -> str:
    """Nom de la banque à imprimer (« Autre » -> libellé saisi)."""
    if p.get("banque") == "autre":
        return (p.get("banque_autre") or "").strip() or "Autre"
    return BANQUES.get(p.get("banque") or "", p.get("banque") or "")


def _public(p: Dict[str, Any]) -> Dict[str, Any]:
    """Paramètres renvoyés à l'écran (le chemin de stockage reste interne)."""
    out = {k: v for k, v in p.items() if k != "qr_image_path"}
    out["qr_image_presente"] = bool(p.get("qr_image_path"))
    out["qr_present"] = bool((p.get("qr_contenu") or "").strip() or p.get("qr_image_path"))
    out["banques"] = BANQUES
    out["consigne_defaut"] = CONSIGNE_DEFAUT
    return out


async def _invalider_pdf_caches() -> None:
    """Les PDF déjà produits des factures non soldées et des proformas sont
    marqués obsolètes (comme après un règlement) : ils seront reconstruits à
    la prochaine lecture, avec ou sans le bloc PI-SPI selon les paramètres."""
    await db.invoices.update_many(
        {"document_type": {"$in": ["facture", "proforma"]}, "status": {"$ne": "paid"}},
        {"$set": {"pdf_storage_path": None}})


class ParametresPISPI(BaseModel):
    """Champs modifiables depuis Paramètres → Encaissement PI-SPI."""
    actif: Optional[bool] = None
    banque: Optional[str] = None
    banque_autre: Optional[str] = Field(None, max_length=80)
    titulaire: Optional[str] = Field(None, max_length=120)
    adresse_paiement: Optional[str] = Field(None, max_length=200)
    qr_contenu: Optional[str] = Field(None, max_length=2000)
    consigne: Optional[str] = Field(None, max_length=400)


@router.get("")
async def lire_parametres(user: dict = Depends(require_roles(PISPI_ROLES))):
    """Lecture des paramètres (Superviseur, Direction)."""
    return _public(await charger_parametres())


@router.put("")
async def enregistrer_parametres(payload: ParametresPISPI, user: dict = Depends(require_roles(PISPI_ROLES))):
    """Enregistrement des paramètres (Superviseur, Direction)."""
    maj = payload.model_dump(exclude_none=True)
    if "banque" in maj and maj["banque"] not in BANQUES:
        raise HTTPException(status_code=400, detail=f"Banque attendue : {', '.join(BANQUES.values())}")
    # Le texte du QR est gardé EXACTEMENT tel que saisi (seuls les retours à
    # la ligne de fin, ajoutés par un copier-coller, sont retirés)
    if "qr_contenu" in maj:
        maj["qr_contenu"] = maj["qr_contenu"].rstrip("\r\n")
    for champ in ("titulaire", "adresse_paiement", "banque_autre", "consigne"):
        if champ in maj:
            maj[champ] = maj[champ].strip()
    actuel = await charger_parametres()
    futur = {**actuel, **maj}
    # Activer sans adresse de paiement ni QR n'aurait aucun sens sur la facture
    if futur.get("actif") and not (futur.get("adresse_paiement") and
                                   ((futur.get("qr_contenu") or "").strip() or futur.get("qr_image_path"))):
        raise HTTPException(status_code=400, detail="Pour activer PI-SPI : renseignez l'adresse de paiement et le QR fourni par la banque")
    maj["modifie_le"] = datetime.now(timezone.utc).isoformat()
    maj["modifie_par"] = user["id"]
    await db.pispi_parametres.update_one({"_id": "global"}, {"$set": maj}, upsert=True)
    await _invalider_pdf_caches()
    return _public(await charger_parametres())


@router.post("/qr")
async def televerser_qr(file: UploadFile = File(...), user: dict = Depends(require_roles(PISPI_ROLES))):
    """Image du QR fournie par la banque (PNG/JPG, 1 Mo max), stockée dans R2."""
    ext = QR_TYPES.get((file.content_type or "").lower())
    if not ext:
        raise HTTPException(status_code=400, detail="Format attendu : PNG ou JPG")
    data = await file.read()
    if len(data) > QR_TAILLE_MAX:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (1 Mo maximum)")
    # Contrôle que le fichier est bien une image lisible
    try:
        from PIL import Image as PILImage
        import io
        PILImage.open(io.BytesIO(data)).verify()
    except Exception:  # noqa: BLE001 — fichier illisible
        raise HTTPException(status_code=400, detail="Image illisible")
    path = f"albarka/cabinet/pispi/qr.{ext}"
    actuel = await charger_parametres()
    # Ancienne image d'une autre extension : supprimée
    if actuel.get("qr_image_path") and actuel["qr_image_path"] != path:
        try:
            await delete_object(actuel["qr_image_path"])
        except Exception:  # noqa: BLE001
            logger.exception("Suppression de l'ancien QR PI-SPI échouée (poursuite)")
    await put_object(path, data, file.content_type)
    await db.pispi_parametres.update_one(
        {"_id": "global"},
        {"$set": {"qr_image_path": path, "qr_image_type": file.content_type,
                  "modifie_le": datetime.now(timezone.utc).isoformat(), "modifie_par": user["id"]}},
        upsert=True)
    await _invalider_pdf_caches()
    return _public(await charger_parametres())


@router.delete("/qr")
async def supprimer_qr_image(user: dict = Depends(require_roles(PISPI_ROLES))):
    """Retire l'image du QR (le texte décodé, s'il existe, reste utilisé)."""
    actuel = await charger_parametres()
    if actuel.get("qr_image_path"):
        try:
            await delete_object(actuel["qr_image_path"])
        except Exception:  # noqa: BLE001
            logger.exception("Suppression du QR PI-SPI échouée (poursuite)")
    await db.pispi_parametres.update_one({"_id": "global"}, {"$set": {"qr_image_path": None, "qr_image_type": None}},
                                         upsert=True)
    await _invalider_pdf_caches()
    return _public(await charger_parametres())


@router.get("/qr")
async def apercu_qr(user: dict = Depends(require_roles(PISPI_ROLES))):
    """Aperçu du QR tel qu'il sera imprimé sur les factures."""
    data = await qr_pispi_bytes(await charger_parametres())
    if not data:
        raise HTTPException(status_code=404, detail="Aucun QR PI-SPI enregistré")
    return Response(content=data, media_type="image/png" if data[:4] == b"\x89PNG" else "image/jpeg")


# ---------------------------------------------------------------------------
# 2. QR et bloc « Payer par PI-SPI » des factures
# ---------------------------------------------------------------------------
async def qr_pispi_bytes(p: Dict[str, Any]) -> Optional[bytes]:
    """Image du QR à imprimer :
    - image téléversée -> renvoyée telle quelle ;
    - sinon texte décodé -> QR généré à partir de ce texte, SANS modification ;
    - sinon None."""
    if p.get("qr_image_path"):
        try:
            data, _ct = await get_object(p["qr_image_path"])
            return data
        except Exception:  # noqa: BLE001 — image perdue : on tente le texte
            logger.exception("QR PI-SPI introuvable dans le stockage")
    texte = p.get("qr_contenu") or ""
    if texte.strip():
        from albarka_docgen import qr_png
        return qr_png(texte)
    return None


def reste_du(invoice: dict) -> float:
    """Reste à payer d'une facture : net à payer (ou total) moins déjà réglé
    (même règle que albarka_phase_c.amount_due)."""
    du = float(invoice.get("net_to_pay", invoice.get("total", 0)) or 0)
    return max(0.0, round(du - float(invoice.get("paid_amount") or 0), 2))


async def bloc_pispi_pour_document(invoice: dict) -> Optional[Dict[str, Any]]:
    """Données du bloc PI-SPI d'une facture ou d'une proforma, ou None.

    - facture : bloc « Payer par PI-SPI » avec le MONTANT RESTANT DÛ et la
      référence (n° de facture), seulement si la facture n'est pas soldée ;
    - proforma (devis) : rien n'est encore dû -> bloc « Modalités de
      paiement » SANS montant ;
    - reçu ou paramètre inactif / sans QR : aucun bloc."""
    doc_type = invoice.get("document_type")
    if doc_type not in ("facture", "proforma"):
        return None
    p = await charger_parametres()
    if not p.get("actif") or not p.get("adresse_paiement"):
        return None
    montant = None
    if doc_type == "facture":
        montant = reste_du(invoice)
        if montant <= 0.5 or invoice.get("status") in ("paid", "cancelled"):
            return None
    qr = await qr_pispi_bytes(p)
    if not qr:
        return None
    return {
        "mode": "payer" if doc_type == "facture" else "modalites",
        "qr_bytes": qr,
        "adresse_paiement": p["adresse_paiement"],
        "titulaire": p.get("titulaire") or "",
        "banque": libelle_banque(p),
        "montant": montant,
        # Lot 17 : référence = numéro IMPRIMÉ sur la facture (manuel s'il existe), celui que le payeur recopie
        "reference": str(invoice.get("manual_number") or invoice.get("number") or ""),
        "consigne": (p.get("consigne") or "").strip() or CONSIGNE_DEFAUT,
    }


# ---------------------------------------------------------------------------
# 3. Transactions PI-SPI (rapprochement des règlements)
# ---------------------------------------------------------------------------
def est_methode_pispi(method: Optional[str]) -> bool:
    """Vrai si le mode de règlement saisi est PI-SPI (« PISPI », « pi-spi »…)."""
    return (method or "").replace("-", "").replace("_", "").strip().lower() == METHODE_PISPI


async def enregistrer_transaction_manuelle(*, invoice: dict, payment: dict, user: dict) -> dict:
    """Trace d'un encaissement PI-SPI saisi à la main par le Caissier :
    statut « rapproche » (le règlement est déjà imputé sur la facture)."""
    tx = {
        "id": secrets.token_urlsafe(12),
        "reference": invoice.get("number"),          # n° de facture indiqué par le payeur
        "montant": float(payment["amount"]),
        "statut": "rapproche",
        "date": payment.get("paid_at") or datetime.now(timezone.utc).isoformat(),
        "source": "manuel",
        "reference_bancaire": payment.get("reference"),
        "document_id": invoice.get("id"),
        "document_type": invoice.get("document_type"),
        "payment_id": payment.get("id"),
        "tenant_id": invoice.get("tenant_id"),
        "cree_le": datetime.now(timezone.utc).isoformat(),
        "cree_par": user.get("id"),
    }
    await db.pispi_transactions.insert_one(tx.copy())
    return tx


@router.get("/transactions")
async def lister_transactions(statut: Optional[str] = None, user: dict = Depends(require_roles(BILLING_ROLES))):
    """Liste des transactions PI-SPI (plus récentes d'abord)."""
    q: Dict[str, Any] = {}
    if statut:
        if statut not in STATUTS:
            raise HTTPException(status_code=400, detail=f"Statut attendu : {', '.join(STATUTS)}")
        q["statut"] = statut
    return await db.pispi_transactions.find(q, {"_id": 0}).sort("date", -1).to_list(1000)


# ---------------------------------------------------------------------------
# 4. Connecteurs (aucune API bancaire n'est appelée aujourd'hui)
# ---------------------------------------------------------------------------
class PISPINonDisponible(Exception):
    """Fonction PI-SPI non disponible avec le connecteur choisi."""


class ConnecteurPISPI(ABC):
    """Interface commune des connecteurs PI-SPI."""
    code = ""
    libelle = ""

    @abstractmethod
    async def demander_paiement(self, *, reference: str, montant: float) -> Dict[str, Any]:
        """Demande de paiement (Request to Pay) pour une référence et un montant."""

    @abstractmethod
    async def statut(self, reference: str) -> Dict[str, Any]:
        """État des paiements reçus pour une référence."""

    @abstractmethod
    async def notification(self, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        """Traitement d'une notification de paiement envoyée par la banque."""


class ConnecteurManuel(ConnecteurPISPI):
    """Seul connecteur actif : le payeur scanne le QR imprimé, le Caissier
    saisit ensuite le règlement (mode PI-SPI + référence bancaire)."""
    code, libelle = "manuel", "Saisie manuelle par le Caissier"

    async def demander_paiement(self, *, reference: str, montant: float) -> Dict[str, Any]:
        # Pas de demande électronique : le QR imprimé sur la facture suffit
        return {"mode": "manuel", "reference": reference, "montant": montant,
                "message": "Le client paie en scannant le QR de la facture ; le Caissier saisit le règlement."}

    async def statut(self, reference: str) -> Dict[str, Any]:
        # État connu = transactions saisies à la main pour cette référence
        txs = await db.pispi_transactions.find({"reference": reference}, {"_id": 0}).to_list(100)
        return {"reference": reference, "transactions": txs}

    async def notification(self, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        raise PISPINonDisponible("le connecteur manuel ne reçoit pas de notification")


class ConnecteurBancaireNonDisponible(ConnecteurPISPI):
    """Emplacement d'un futur connecteur bancaire (API Business PI-SPI).

    À compléter UNIQUEMENT avec la documentation officielle remise par la
    banque une fois l'accès obtenu (URL, authentification, format des
    messages). D'ici là, toutes les fonctions répondent « non disponible ».
    Variables prévues : PISPI_API_URL, PISPI_CLIENT_ID, PISPI_CLIENT_SECRET."""

    async def demander_paiement(self, *, reference: str, montant: float) -> Dict[str, Any]:
        raise PISPINonDisponible(f"{self.libelle} : {MESSAGE_NON_DISPONIBLE}")

    async def statut(self, reference: str) -> Dict[str, Any]:
        raise PISPINonDisponible(f"{self.libelle} : {MESSAGE_NON_DISPONIBLE}")

    async def notification(self, corps: bytes, entetes: Dict[str, str]) -> Dict[str, Any]:
        raise PISPINonDisponible(f"{self.libelle} : {MESSAGE_NON_DISPONIBLE}")


class ConnecteurEcobank(ConnecteurBancaireNonDisponible):
    """Ecobank : seule API Business PI-SPI homologuée au Burkina (accès non obtenu)."""
    code, libelle = "ecobank", "Ecobank"


class ConnecteurUBA(ConnecteurBancaireNonDisponible):
    """UBA : participant PI-SPI, pas d'API Business homologuée (17/09/2026)."""
    code, libelle = "uba", "UBA"


class ConnecteurBSIC(ConnecteurBancaireNonDisponible):
    """BSIC : participant PI-SPI, pas d'API Business homologuée (17/09/2026)."""
    code, libelle = "bsic", "BSIC"


class ConnecteurIBBank(ConnecteurBancaireNonDisponible):
    """IB Bank : statut PI-SPI à confirmer."""
    code, libelle = "ib_bank", "IB Bank"


CONNECTEURS = {c.code: c for c in (ConnecteurManuel, ConnecteurEcobank, ConnecteurUBA, ConnecteurBSIC, ConnecteurIBBank)}


def connecteur_actif() -> ConnecteurPISPI:
    """Connecteur choisi par PISPI_FOURNISSEUR (défaut : manuel)."""
    code = (os.environ.get("PISPI_FOURNISSEUR") or "manuel").strip().lower()
    return CONNECTEURS.get(code, ConnecteurManuel)()


@router.get("/connecteurs")
async def etat_connecteurs(user: dict = Depends(require_roles(PISPI_ROLES))):
    """État des connecteurs (aucun secret renvoyé)."""
    actif = connecteur_actif()
    return {
        "actif": actif.code,
        "connecteurs": [{"code": c.code, "libelle": c.libelle,
                         "disponible": c is ConnecteurManuel} for c in CONNECTEURS.values()],
        "notification_active": False,
    }


# ---------------------------------------------------------------------------
# 5. Route de notification (prévue, DÉSACTIVÉE)
# ---------------------------------------------------------------------------
@notification_router.post("/notification")
async def notification_paiement(request: Request):
    """Notification de paiement envoyée par une banque.

    DÉSACTIVÉE : aucun connecteur bancaire n'est disponible aujourd'hui.
    Répond toujours 503 sans lire ni enregistrer le contenu reçu."""
    actif = connecteur_actif()
    if isinstance(actif, ConnecteurManuel):
        raise HTTPException(status_code=503, detail="Notification PI-SPI désactivée : aucun connecteur bancaire configuré")
    raise HTTPException(status_code=503, detail=f"Notification PI-SPI désactivée : {actif.libelle} {MESSAGE_NON_DISPONIBLE}")
