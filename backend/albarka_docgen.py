"""Socle commun des documents édités par le cabinet (lot 7).

Utilisé par les factures / proformas (albarka_invoice_layout.py), les
documents à partir de modèles (albarka_letters.py) et le tableau de paie :

- `montant_en_lettres(n)` : somme en toutes lettres, en français
  (« CINQUANTE NEUF MILLE QUATRE CENT SOIXANTE TREIZE ») ;
- PAPIERS À EN-TÊTE : plusieurs en-têtes possibles (ex. ALBARKA, GESPHARM),
  chacun avec une image d'en-tête et une image de pied de page, ou « papier
  préimprimé » (on laisse seulement la marge haute vide) ; le document choisit
  le sien, sinon celui marqué « par défaut » ;
  lot 12 : un papier peut aussi être une PAGE A4 ENTIÈRE posée en fond de
  chaque page (type « page »), le texte s'écrivant entre deux marges
  détectées automatiquement sur l'image ;
- RÉGLAGES DES DOCUMENTS : ville, signataire (titre + nom), IFU / RCCM du
  cabinet ;
- QR CODE DE VÉRIFICATION : chaque document reçoit un jeton ; le QR code
  imprimé mène à la page publique /verifier/<jeton> qui confirme que le
  document est authentique (numéro, date, client, montant).

Routes :
  GET/POST/PUT/DELETE /admin/letterheads…   papiers à en-tête
  POST                /admin/letterheads/detect  type proposé + marges détectées (lot 12)
  GET/PUT             /admin/doc-settings    ville, signataire, IFU/RCCM
  GET                 /public/verify/{token} vérification publique (sans compte)
"""
from __future__ import annotations

import io
import logging
import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from albarka_auth import require_roles, require_staff
from albarka_models import SETTINGS_ROLES
from albarka_storage import delete_object, get_object, put_object
from db import db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Documents — socle"])
public_router = APIRouter(prefix="/public", tags=["Documents — vérification"])

# Qui peut gérer les papiers à en-tête et les réglages des documents
DOC_ADMIN_ROLES = [*SETTINGS_ROLES, "direction", "dg", "administrateur"]
# Adresse officielle du portail (le QR code doit toujours pointer vers elle)
PUBLIC_BASE_URL = "https://albarka-bf.com"
_MAX_IMAGE = 5 * 1024 * 1024
_IMAGE_TYPES = {"image/png": "png", "image/jpeg": "jpg", "image/jpg": "jpg", "image/webp": "webp"}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ==========================================================================
# Montant en toutes lettres (français, FCFA)
# ==========================================================================
_UNITS = ["zéro", "un", "deux", "trois", "quatre", "cinq", "six", "sept", "huit", "neuf", "dix",
          "onze", "douze", "treize", "quatorze", "quinze", "seize"]
_TENS = {20: "vingt", 30: "trente", 40: "quarante", 50: "cinquante", 60: "soixante"}


def _below_100(n: int) -> str:
    """0 à 99 (« soixante et onze », « quatre vingts », « quatre vingt dix »)."""
    if n <= 16:
        return _UNITS[n]
    if n < 20:
        return "dix " + _UNITS[n - 10]
    if n < 70:
        tens, unit = divmod(n, 10)
        word = _TENS[tens * 10]
        if unit == 0:
            return word
        return f"{word} et un" if unit == 1 else f"{word} {_UNITS[unit]}"
    if n < 80:  # 70-79 : soixante + 10..19
        return "soixante et onze" if n == 71 else "soixante " + _below_100(n - 60)
    # 80-99 : quatre vingt(s) + 0..19
    rest = n - 80
    return "quatre vingts" if rest == 0 else "quatre vingt " + _below_100(rest)


def _below_1000(n: int) -> str:
    """0 à 999 (« deux cents », « deux cent un », « cent »)."""
    hundreds, rest = divmod(n, 100)
    if hundreds == 0:
        return _below_100(rest)
    head = "cent" if hundreds == 1 else f"{_UNITS[hundreds]} cent"
    if rest == 0:
        return head + ("s" if hundreds > 1 else "")
    return f"{head} {_below_100(rest)}"


def montant_en_lettres(amount: float, upper: bool = True) -> str:
    """Somme entière en toutes lettres (le franc CFA n'a pas de centimes).
    Ex. 59473 -> « CINQUANTE NEUF MILLE QUATRE CENT SOIXANTE TREIZE »."""
    n = int(round(float(amount or 0)))
    if n == 0:
        words = "zéro"
    else:
        parts = []
        negative = n < 0
        n = abs(n)
        for value, singular, plural in ((10**9, "milliard", "milliards"), (10**6, "million", "millions")):
            q, n = divmod(n, value)
            if q:
                parts.append(f"{_below_1000(q)} {singular if q == 1 else plural}")
        q, n = divmod(n, 1000)
        if q:
            # « mille » est invariable ; « un mille » ne se dit pas ;
            # « cents » et « vingts » perdent leur s devant mille
            # (« deux cent mille », « quatre vingt mille »)
            parts.append("mille" if q == 1 else f"{_below_1000(q).removesuffix('s')} mille")
        if n:
            parts.append(_below_1000(n))
        words = ("moins " if negative else "") + " ".join(parts)
    return words.upper() if upper else words


def fcfa(v) -> str:
    """Montant au format « 59 473 » (espace des milliers, sans décimale)."""
    try:
        return f"{float(v):,.0f}".replace(",", " ")
    except (TypeError, ValueError):
        return "0"


MONTHS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
             "septembre", "octobre", "novembre", "décembre"]
WEEKDAYS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def date_longue(iso: Optional[str] = None, weekday: bool = False) -> str:
    """« 17 août 2026 » (ou « mardi 18 août 2026 ») à partir d'une date ISO."""
    try:
        d = datetime.fromisoformat((iso or now_iso())[:10])
    except ValueError:
        return iso or ""
    txt = f"{d.day} {MONTHS_FR[d.month - 1]} {d.year}"
    return f"{WEEKDAYS_FR[d.weekday()]} {txt}" if weekday else txt


# ==========================================================================
# Réglages des documents (ville, signataire, identifiants du cabinet)
# ==========================================================================
DOC_SETTINGS_DEFAULTS = {
    "city": "Ouagadougou",
    "signatory_title": "Le Directeur Général",
    "signatory_name": "",
    "cabinet_ifu": "",
    "cabinet_rccm": "",
    "thanks_text": "Nous vous remercions de votre confiance.",
    "default_tva_rate": 18.0,
    "default_withholding_rate": 0.0,
    # Lot 8 — retenue à la source : libellé et taux selon le prestataire
    "withholding_label": "retenue",
    "withholding_rate_ifu": 5.0,        # prestataire avec numéro IFU
    "withholding_rate_no_ifu": 10.0,    # prestataire sans numéro IFU
}


class DocSettingsUpdate(BaseModel):
    city: Optional[str] = Field(None, max_length=80)
    signatory_title: Optional[str] = Field(None, max_length=120)
    signatory_name: Optional[str] = Field(None, max_length=120)
    cabinet_ifu: Optional[str] = Field(None, max_length=60)
    cabinet_rccm: Optional[str] = Field(None, max_length=80)
    thanks_text: Optional[str] = Field(None, max_length=200)
    default_tva_rate: Optional[float] = Field(None, ge=0, le=100)
    default_withholding_rate: Optional[float] = Field(None, ge=0, le=100)
    withholding_label: Optional[str] = Field(None, max_length=60)
    withholding_rate_ifu: Optional[float] = Field(None, ge=0, le=100)
    withholding_rate_no_ifu: Optional[float] = Field(None, ge=0, le=100)


async def get_doc_settings() -> dict:
    """Réglages des documents, complétés par les valeurs par défaut."""
    doc = await db.settings.find_one({"_id": "global"}, {"_id": 0, "doc_settings": 1}) or {}
    return {**DOC_SETTINGS_DEFAULTS, **(doc.get("doc_settings") or {})}


@router.get("/doc-settings")
async def read_doc_settings(user: dict = Depends(require_staff())):
    return await get_doc_settings()


@router.put("/doc-settings")
async def update_doc_settings(payload: DocSettingsUpdate, user: dict = Depends(require_roles(DOC_ADMIN_ROLES))):
    changes = {f"doc_settings.{k}": v for k, v in payload.model_dump(exclude_none=True).items()}
    if changes:
        await db.settings.update_one({"_id": "global"}, {"$set": changes}, upsert=True)
    return await get_doc_settings()


# ==========================================================================
# Papiers à en-tête
# ==========================================================================
def _public_letterhead(lh: dict, eff: Optional[dict] = None) -> dict:
    """Fiche renvoyée à l'écran (sans chemins de stockage).
    Lot 12 : `eff` = type de papier et marges effectifs (voir page_settings)."""
    eff = eff or page_settings(lh, None)
    return {
        "id": lh["id"], "name": lh.get("name"), "is_default": bool(lh.get("is_default")),
        "has_header": bool(lh.get("header_path")), "has_footer": bool(lh.get("footer_path")),
        "top_margin_cm": lh.get("top_margin_cm", 4.8), "bottom_margin_cm": lh.get("bottom_margin_cm", 2.0),
        **eff,
        "created_at": lh.get("created_at"), "updated_at": lh.get("updated_at"),
    }


async def _stored_header(lh: dict) -> Optional[bytes]:
    """Image d'en-tête enregistrée (ramenée en PNG/JPEG), ou None."""
    if not lh.get("header_path"):
        return None
    try:
        raw, _ct = await get_object(lh["header_path"])
        return normalize_image(raw)[0]
    except Exception:  # noqa: BLE001 — image absente ou illisible : pas de détection
        return None


async def _effective(lh: dict) -> dict:
    """Lot 12 : type et marges effectifs d'un papier ; l'image n'est lue que
    si c'est nécessaire (papier ancien sans type, marges jamais calculées)."""
    mode = lh.get("mode")
    need = lh.get("header_path") and (
        (mode not in LH_MODES and not lh.get("footer_path"))
        or (mode == "page" and (lh.get("page_top_mm") is None or lh.get("page_bottom_mm") is None)))
    return page_settings(lh, await _stored_header(lh) if need else None)


@router.get("/letterheads")
async def list_letterheads(user: dict = Depends(require_staff())):
    items = await db.letterheads.find({}, {"_id": 0}).sort("name", 1).to_list(100)
    return [_public_letterhead(x, await _effective(x)) for x in items]


# --------------------------------------------------------------------------
# Lot 12 — type de papier (« bandes » / « page ») et marges à l'enregistrement
# --------------------------------------------------------------------------
def _detection_report(detection: Optional[dict], has_footer: bool) -> Optional[dict]:
    """Résultat de la détection renvoyé à l'écran, avec le type proposé et un
    message en français expliquant pourquoi."""
    if detection is None:
        return None
    suggested = "page" if detection["a4_like"] and not has_footer else "bandes"
    if suggested == "page":
        msg = ("Cette image a les proportions d'une page A4 complète : le type « Page entière » est proposé "
               "(image en fond de chaque page, texte écrit entre la marge haute et la marge basse). "
               f"Marges proposées : {detection['top_mm']:g} mm en haut, {detection['bottom_mm']:g} mm en bas.")
    elif detection["a4_like"]:
        msg = ("Cette image a les proportions d'une page A4, mais le papier a aussi une image de pied de page : "
               "type « En-tête + pied séparés » conservé.")
    else:
        msg = "Image en bandeau : type « En-tête + pied séparés »."
    return {**detection, "suggested_mode": suggested, "message": msg}


def _page_changes(*, mode: Optional[str], top: Optional[float], bottom: Optional[float], left: Optional[float],
                  right: Optional[float], new_header: Optional[bytes], has_footer: bool) -> tuple[dict, Optional[dict]]:
    """Champs du mode « page » à enregistrer. Nouvelle image d'en-tête sans
    type choisi : le type est proposé automatiquement (page A4 sans pied ->
    « page ») et les marges détectées sont enregistrées (sauf si l'admin a
    saisi les siennes)."""
    changes: dict = {}
    detection = detect_page_letterhead(new_header) if new_header else None
    if mode is not None and mode != "":
        if mode not in LH_MODES:
            raise HTTPException(status_code=400, detail="Type de papier inconnu (« bandes » ou « page »)")
        changes["mode"] = mode
    elif detection is not None:
        changes["mode"] = "page" if detection["a4_like"] and not has_footer else "bandes"
    page_h = A4_MM[1]
    if top is not None:
        changes["page_top_mm"] = round(max(5.0, min(_MAX_TOP_SHARE * page_h, top)), 1)
    elif detection is not None:
        changes["page_top_mm"] = detection["top_mm"]
    if bottom is not None:
        changes["page_bottom_mm"] = round(max(5.0, min(_MAX_BOTTOM_SHARE * page_h, bottom)), 1)
    elif detection is not None:
        changes["page_bottom_mm"] = detection["bottom_mm"]
    for key, val in (("page_left_mm", left), ("page_right_mm", right)):
        if val is not None:
            changes[key] = round(max(5.0, min(60.0, val)), 1)
    return changes, _detection_report(detection, has_footer)


# --------------------------------------------------------------------------
# Lot 11 — images du papier à en-tête RAMENÉES À UN FORMAT SÛR
# Le moteur PDF des documents à modèles (PyMuPDF) ne lit pas le WEBP
# (« unknown image file format » -> erreur 500 à la génération), et une image
# abîmée ou d'un format exotique (CMYK, 16 bits, palette…) peut faire échouer
# les factures (reportlab). On convertit donc toute image en PNG (ou JPEG pour
# une photo sans transparence), redressée et réduite à la largeur d'une feuille
# A4 en 300 dpi : à l'enregistrement ET à la lecture (images déjà stockées).
# --------------------------------------------------------------------------
_MAX_IMAGE_WIDTH = 2480          # A4 en 300 dpi : bien assez pour l'impression


class ImageIllisible(ValueError):
    """Le fichier n'est pas une image que l'on sait lire."""


def normalize_image(data: bytes, max_width: int = _MAX_IMAGE_WIDTH) -> tuple[bytes, str]:
    """Renvoie (octets, type) d'une image PNG ou JPEG en couleurs RVB (avec
    transparence si l'original en a). Lève ImageIllisible sinon."""
    from PIL import Image, ImageOps
    if not data:
        raise ImageIllisible("fichier vide")
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as exc:  # noqa: BLE001 — format inconnu, fichier tronqué, image géante…
        raise ImageIllisible(str(exc) or type(exc).__name__) from exc
    fmt, (w, h) = im.format, im.size
    if w < 1 or h < 1:
        raise ImageIllisible("image vide")
    # Photo prise de travers (téléphone) : on applique l'orientation EXIF
    try:
        rotated = (im.getexif() or {}).get(0x0112, 1) not in (None, 1)
    except Exception:  # noqa: BLE001
        rotated = False
    safe = (fmt == "PNG" and im.mode in ("RGB", "RGBA", "L")) or (fmt == "JPEG" and im.mode in ("RGB", "L"))
    if safe and w <= max_width and not rotated:
        return data, "image/png" if fmt == "PNG" else "image/jpeg"
    try:
        if rotated:
            im = ImageOps.exif_transpose(im)
        if im.mode in ("I;16", "I;16B", "I;16L", "I"):
            # Niveaux de gris 16 bits -> 8 bits
            im = im.convert("I").point(lambda v: v / 256).convert("L")
        alpha = im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info)
        im = im.convert("RGBA" if alpha else "RGB")
        if im.width > max_width:
            im = im.resize((max_width, max(1, round(im.height * max_width / im.width))), Image.LANCZOS)
        buf = io.BytesIO()
        if fmt == "JPEG" and not alpha:
            im.save(buf, format="JPEG", quality=90)
            return buf.getvalue(), "image/jpeg"
        im.save(buf, format="PNG", optimize=True)
        return buf.getvalue(), "image/png"
    except Exception as exc:  # noqa: BLE001
        raise ImageIllisible(str(exc) or type(exc).__name__) from exc


async def _read_image(file: Optional[UploadFile]) -> Optional[tuple[bytes, str]]:
    """Image envoyée (PNG/JPG/WEBP, 5 Mo max) ou None si aucun fichier.
    Lot 11 : l'image est vérifiée puis enregistrée en PNG/JPEG (le WEBP est
    converti), pour que tous les documents sachent l'imprimer."""
    if file is None or not getattr(file, "filename", ""):
        return None
    ct = (file.content_type or "").lower()
    if ct not in _IMAGE_TYPES:
        raise HTTPException(status_code=400, detail="Image PNG, JPG ou WEBP attendue")
    data = await file.read()
    if len(data) > _MAX_IMAGE:
        raise HTTPException(status_code=400, detail="Image trop lourde (5 Mo maximum)")
    try:
        return normalize_image(data)
    except ImageIllisible:
        raise HTTPException(status_code=400, detail="Image illisible : enregistrez-la en PNG ou JPG puis rechargez-la")


async def _store_part(lh_id: str, part: str, img: tuple[bytes, str], previous: Optional[str]) -> str:
    """Enregistre l'image d'en-tête / de pied de page et supprime l'ancienne."""
    data, ct = img
    path = f"albarka/cabinet/letterheads/{lh_id}_{part}_{secrets.token_hex(4)}.{_IMAGE_TYPES[ct]}"
    await put_object(path, data, ct)
    if previous:
        try:
            await delete_object(previous)
        except Exception:  # noqa: BLE001 — ancien fichier déjà absent
            pass
    return path


async def _set_default(lh_id: str) -> None:
    """Un seul papier « par défaut »."""
    await db.letterheads.update_many({"id": {"$ne": lh_id}}, {"$set": {"is_default": False}})
    await db.letterheads.update_one({"id": lh_id}, {"$set": {"is_default": True}})


@router.post("/letterheads")
async def create_letterhead(
    name: str = Form(..., min_length=1, max_length=80),
    top_margin_cm: float = Form(4.8),
    bottom_margin_cm: float = Form(2.0),
    is_default: bool = Form(False),
    mode: Optional[str] = Form(None),
    page_top_mm: Optional[float] = Form(None),
    page_bottom_mm: Optional[float] = Form(None),
    page_left_mm: Optional[float] = Form(None),
    page_right_mm: Optional[float] = Form(None),
    header: Optional[UploadFile] = File(None),
    footer: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles(DOC_ADMIN_ROLES)),
):
    lh_id = secrets.token_hex(8)
    doc = {"id": lh_id, "name": name.strip(), "top_margin_cm": max(0.5, min(10.0, top_margin_cm)),
           "bottom_margin_cm": max(0.5, min(8.0, bottom_margin_cm)), "is_default": False,
           "header_path": None, "footer_path": None, "created_at": now_iso(), "updated_at": now_iso(),
           "created_by": user["id"]}
    images = {}
    for part, f in (("header", header), ("footer", footer)):
        img = await _read_image(f)
        if img:
            images[part] = img[0]
            doc[f"{part}_path"] = await _store_part(lh_id, part, img, None)
    # Lot 12 : type de papier (proposé d'après l'image si non choisi) et marges
    page, detection = _page_changes(mode=mode, top=page_top_mm, bottom=page_bottom_mm, left=page_left_mm,
                                    right=page_right_mm, new_header=images.get("header"), has_footer="footer" in images)
    doc.update({"mode": "bandes", **page})
    await db.letterheads.insert_one(doc.copy())
    # Le premier papier créé devient automatiquement celui par défaut
    if is_default or await db.letterheads.count_documents({}) == 1:
        await _set_default(lh_id)
        doc["is_default"] = True
    return {**_public_letterhead(doc, page_settings(doc, images.get("header"))), "detection": detection}


@router.put("/letterheads/{lh_id}")
async def update_letterhead(
    lh_id: str,
    name: Optional[str] = Form(None),
    top_margin_cm: Optional[float] = Form(None),
    bottom_margin_cm: Optional[float] = Form(None),
    is_default: Optional[bool] = Form(None),
    mode: Optional[str] = Form(None),
    page_top_mm: Optional[float] = Form(None),
    page_bottom_mm: Optional[float] = Form(None),
    page_left_mm: Optional[float] = Form(None),
    page_right_mm: Optional[float] = Form(None),
    remove_header: bool = Form(False),
    remove_footer: bool = Form(False),
    header: Optional[UploadFile] = File(None),
    footer: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles(DOC_ADMIN_ROLES)),
):
    lh = await db.letterheads.find_one({"id": lh_id}, {"_id": 0})
    if not lh:
        raise HTTPException(status_code=404, detail="Papier à en-tête introuvable")
    changes: dict = {"updated_at": now_iso()}
    if name is not None and name.strip():
        changes["name"] = name.strip()[:80]
    if top_margin_cm is not None:
        changes["top_margin_cm"] = max(0.5, min(10.0, top_margin_cm))
    if bottom_margin_cm is not None:
        changes["bottom_margin_cm"] = max(0.5, min(8.0, bottom_margin_cm))
    new_header = None
    for part, f, remove in (("header", header, remove_header), ("footer", footer, remove_footer)):
        img = await _read_image(f)
        if img:
            if part == "header":
                new_header = img[0]
            changes[f"{part}_path"] = await _store_part(lh_id, part, img, lh.get(f"{part}_path"))
        elif remove and lh.get(f"{part}_path"):
            try:
                await delete_object(lh[f"{part}_path"])
            except Exception:  # noqa: BLE001
                pass
            changes[f"{part}_path"] = None
    # Lot 12 : type de papier et marges (nouvelle image d'en-tête -> détection)
    has_footer = bool(changes.get("footer_path", lh.get("footer_path")))
    page, detection = _page_changes(mode=mode, top=page_top_mm, bottom=page_bottom_mm, left=page_left_mm,
                                    right=page_right_mm, new_header=new_header, has_footer=has_footer)
    changes.update(page)
    await db.letterheads.update_one({"id": lh_id}, {"$set": changes})
    if is_default:
        await _set_default(lh_id)
    fresh = await db.letterheads.find_one({"id": lh_id}, {"_id": 0})
    return {**_public_letterhead(fresh, await _effective(fresh)), "detection": detection}


@router.post("/letterheads/detect")
async def detect_letterhead(
    letterhead_id: Optional[str] = Form(None),
    header: Optional[UploadFile] = File(None),
    user: dict = Depends(require_roles(DOC_ADMIN_ROLES)),
):
    """Lot 12 — « Détecter les marges » : analyse l'image envoyée (avant
    enregistrement) ou celle d'un papier enregistré, et propose le type de
    papier et les marges haute / basse. N'enregistre rien."""
    img = await _read_image(header)
    has_footer = False
    if img:
        data = img[0]
    else:
        lh = await db.letterheads.find_one({"id": letterhead_id or ""}, {"_id": 0}) if letterhead_id else None
        if not lh:
            raise HTTPException(status_code=404, detail="Papier à en-tête introuvable")
        data = await _stored_header(lh)
        if data is None:
            raise HTTPException(status_code=400, detail="Ce papier n'a pas d'image d'en-tête lisible à analyser")
        has_footer = bool(lh.get("footer_path"))
    return _detection_report(detect_page_letterhead(data), has_footer)


@router.delete("/letterheads/{lh_id}")
async def delete_letterhead(lh_id: str, user: dict = Depends(require_roles(DOC_ADMIN_ROLES))):
    lh = await db.letterheads.find_one({"id": lh_id}, {"_id": 0})
    if not lh:
        raise HTTPException(status_code=404, detail="Papier à en-tête introuvable")
    for part in ("header_path", "footer_path"):
        if lh.get(part):
            try:
                await delete_object(lh[part])
            except Exception:  # noqa: BLE001
                pass
    await db.letterheads.delete_one({"id": lh_id})
    return {"ok": True}


@router.get("/letterheads/{lh_id}/{part}")
async def letterhead_image(lh_id: str, part: str, user: dict = Depends(require_staff())):
    """Aperçu de l'image d'en-tête ou de pied de page."""
    from fastapi.responses import Response
    if part not in ("header", "footer"):
        raise HTTPException(status_code=404, detail="Partie inconnue")
    lh = await db.letterheads.find_one({"id": lh_id}, {"_id": 0})
    if not lh or not lh.get(f"{part}_path"):
        raise HTTPException(status_code=404, detail="Image absente")
    try:
        data, ct = await get_object(lh[f"{part}_path"])
    except Exception:  # noqa: BLE001 — lot 11 : fichier absent du stockage
        logger.exception("Image %s du papier %s introuvable dans le stockage", part, lh_id)
        raise HTTPException(status_code=404, detail="Image introuvable dans le stockage : rechargez-la")
    return Response(content=data, media_type=ct or "image/png")


async def load_letterhead(lh_id: Optional[str], warnings: Optional[list] = None) -> dict:
    """Papier à utiliser pour un document : celui demandé, sinon celui par
    défaut, sinon aucun (marges simples). Renvoie les images en octets.
    `lh_id == "none"` force « sans en-tête ».
    Lot 11 : les images sont ramenées en PNG/JPEG ; une image absente du
    stockage ou illisible est laissée de côté (le document sort quand même) et
    un avertissement en français est ajouté à `warnings` (si fourni)."""
    def warn(msg: str) -> None:
        if warnings is not None and msg not in warnings:
            warnings.append(msg)

    empty = {"id": None, "name": None, "header": None, "footer": None, "top_margin_cm": 2.0, "bottom_margin_cm": 2.0,
             "mode": "bandes"}
    if lh_id == "none":
        return empty
    lh = None
    if lh_id:
        lh = await db.letterheads.find_one({"id": lh_id}, {"_id": 0})
    if not lh:
        lh = await db.letterheads.find_one({"is_default": True}, {"_id": 0})
        if lh_id:
            # Papier supprimé depuis (ex. modèle qui pointait vers un ancien papier)
            warn("Le papier à en-tête choisi n'existe plus : "
                 + (f"le papier par défaut « {lh.get('name')} » a été utilisé." if lh else "document produit sans en-tête."))
    if not lh:
        return empty
    try:
        top_cm = float(lh.get("top_margin_cm") or 4.8)
        bottom_cm = float(lh.get("bottom_margin_cm") or 2.0)
    except (TypeError, ValueError):
        top_cm, bottom_cm = 4.8, 2.0
    out = {"id": lh["id"], "name": lh.get("name"), "header": None, "footer": None,
           "top_margin_cm": top_cm, "bottom_margin_cm": bottom_cm}
    labels = {"header": "d'en-tête", "footer": "de pied de page"}
    for part in ("header", "footer"):
        path = lh.get(f"{part}_path")
        if not path:
            continue
        try:
            raw, _ct = await get_object(path)
        except Exception:  # noqa: BLE001 — image perdue (stockage) : on imprime sans
            logger.exception("Image %s du papier %s introuvable dans le stockage (%s)", part, lh["id"], path)
            warn(f"Image {labels[part]} du papier « {lh.get('name')} » introuvable : rechargez-la dans "
                 "Réglages des documents > Papiers à en-tête. Document produit sans cette image.")
            continue
        try:
            out[part], _ct = normalize_image(raw)
        except ImageIllisible as exc:
            logger.warning("Image %s du papier %s illisible (%s) : %s", part, lh["id"], path, exc)
            warn(f"Image {labels[part]} du papier « {lh.get('name')} » illisible : enregistrez-la en PNG ou JPG "
                 "et rechargez-la dans Réglages des documents > Papiers à en-tête. Document produit sans cette image.")
    # Lot 12 : type de papier et marges effectifs. En mode « page », l'image
    # d'en-tête est le fond de page et l'éventuelle image de pied est ignorée.
    out.update(page_settings(lh, out["header"]))
    if out["mode"] == "page":
        out["footer"] = None
    return out


def letterhead_image_size(data: bytes, width_pt: float) -> tuple[float, float]:
    """Taille (largeur, hauteur) en points d'une image affichée sur `width_pt`.
    Lot 11 : image illisible -> hauteur 0 (l'appelant ne l'imprime pas)."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            w, h = im.size
    except Exception:  # noqa: BLE001
        logger.warning("Image du papier à en-tête illisible : ignorée")
        return width_pt, 0.0
    return width_pt, width_pt * h / max(1, w)


# ==========================================================================
# Lot 12 — PAPIER « PAGE ENTIÈRE » (fond A4)
# Certains cabinets n'ont pas un bandeau d'en-tête et un bandeau de pied de
# page séparés, mais une PAGE A4 COMPLÈTE (logo en haut, grand blanc au
# milieu, coordonnées / RCCM / IFU en bas). Deux types de papier :
#   - « bandes » (défaut, lots 7 à 11) : image d'en-tête en haut, image de
#     pied de page en bas, chacune sur toute la largeur ;
#   - « page » : une seule image posée en FOND de chaque page, pleine page,
#     sans réduction ; le texte s'écrit entre une marge haute et une marge
#     basse (en mm), plus des marges gauche / droite.
# Les marges haute et basse sont DÉTECTÉES automatiquement (Pillow) sur
# l'image : fin de la bande imprimée du haut, début de celle du bas, plus
# une respiration de 6 mm. L'admin peut ensuite les corriger.
# ==========================================================================
LH_MODES = ("bandes", "page")
A4_MM = (210.0, 297.0)
PT_PER_MM = 72 / 25.4
PAGE_TOP_DEFAULT_MM = 35.0       # marges proposées quand la détection échoue
PAGE_BOTTOM_DEFAULT_MM = 30.0
PAGE_SIDE_DEFAULT_MM = 20.0      # marges gauche / droite du mode « page »
A4_RATIO_RANGE = (1.30, 1.52)    # hauteur / largeur « proche de l'A4 » (1,414)
_WHITE_LEVEL = 245               # pixel « blanc » : R, V et B tous >= 245
_NOISE_SHARE = 0.003             # ligne « blanche » si < 0,3 % de pixels non blancs (poussières)
_MIN_WHITE_RUN = 0.08            # zone blanche continue d'au moins 8 % de la hauteur
_BREATH_MM = 6.0                 # respiration entre la bande imprimée et le texte
_MAX_TOP_SHARE, _MAX_BOTTOM_SHARE = 0.45, 0.35   # garde-fous (part de la page)
_DETECT_CACHE: dict = {}         # chemin de l'image -> résultat de la détection


def is_a4_ratio(data: Optional[bytes]) -> bool:
    """L'image a-t-elle les proportions d'une feuille A4 portrait (ou proche) ?"""
    if not data:
        return False
    w, h = letterhead_image_size(data, 1.0)
    return bool(h) and A4_RATIO_RANGE[0] <= h / w <= A4_RATIO_RANGE[1]


def _row_flags(data: bytes) -> list[bool]:
    """Pour chaque ligne de l'image (réduite pour aller vite) : True si la
    ligne est « imprimée » (assez de pixels non blancs), False si blanche."""
    from PIL import Image, ImageChops
    with Image.open(io.BytesIO(data)) as im:
        im.load()
        # Transparence : l'image est posée sur du papier blanc
        if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
            rgba = im.convert("RGBA")
            sheet = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
            sheet.alpha_composite(rgba)
            rgb = sheet.convert("RGB")
        else:
            rgb = im.convert("RGB")
    # Environ 1 750 lignes suffisent (0,17 mm par ligne sur une page A4)
    factor = max(1, rgb.height // 1750)
    if factor > 1:
        rgb = rgb.reduce(factor)
    r, g, b = rgb.split()
    darkest = ImageChops.darker(ImageChops.darker(r, g), b)
    # 1 = pixel non blanc, 0 = pixel blanc ; moyenne par ligne = part non blanche
    mask = darkest.point(lambda v: 255 if v < _WHITE_LEVEL else 0).convert("F")
    shares = mask.resize((1, mask.height), Image.BOX).getdata()
    return [v / 255.0 > _NOISE_SHARE for v in shares]


def _band_end(flags: list[bool], min_run: int) -> Optional[int]:
    """Dernière ligne imprimée de la bande qui commence au bord de l'image,
    c.-à-d. avant la première zone blanche continue d'au moins `min_run`
    lignes. None si aucune ligne imprimée (bord entièrement blanc)."""
    last, run = None, 0
    for i, printed in enumerate(flags):
        if printed:
            last, run = i, 0
        elif last is not None:
            run += 1
            if run >= min_run:
                break
    return last


def detect_page_letterhead(data: Optional[bytes]) -> dict:
    """Analyse une image de papier « page entière » et propose les marges.
    Renvoie : a4_like (proportions A4), found (marges trouvées et
    vraisemblables), top_mm / bottom_mm (marges proposées, ou valeurs par
    défaut), warnings (messages en français pour l'admin)."""
    out = {"a4_like": is_a4_ratio(data), "found": False, "top_mm": PAGE_TOP_DEFAULT_MM,
           "bottom_mm": PAGE_BOTTOM_DEFAULT_MM, "warnings": []}
    if not data:
        return out
    try:
        flags = _row_flags(data)
    except Exception:  # noqa: BLE001 — image illisible : valeurs par défaut
        logger.warning("Détection des marges impossible : image illisible")
        out["warnings"].append("Image illisible : marges par défaut proposées (35 mm en haut, 30 mm en bas).")
        return out
    n = len(flags)
    min_run = max(1, round(n * _MIN_WHITE_RUN))
    top_end = _band_end(flags, min_run)
    bottom_end = _band_end(flags[::-1], min_run)
    page_h = A4_MM[1]
    top_mm = None if top_end is None else (top_end + 1) / n * page_h + _BREATH_MM
    bottom_mm = None if bottom_end is None else (bottom_end + 1) / n * page_h + _BREATH_MM
    ok = True
    if top_mm is None or top_mm > _MAX_TOP_SHARE * page_h:
        ok = False
        out["warnings"].append("Bande du haut non trouvée (pas de zone blanche nette sous le logo) : marge haute "
                               f"par défaut ({PAGE_TOP_DEFAULT_MM:g} mm) proposée, à vérifier.")
    else:
        out["top_mm"] = round(top_mm * 2) / 2      # arrondi au demi-millimètre
    if bottom_mm is None or bottom_mm > _MAX_BOTTOM_SHARE * page_h:
        ok = False
        out["warnings"].append("Bande du bas non trouvée (pas de zone blanche nette au-dessus des coordonnées) : "
                               f"marge basse par défaut ({PAGE_BOTTOM_DEFAULT_MM:g} mm) proposée, à vérifier.")
    else:
        out["bottom_mm"] = round(bottom_mm * 2) / 2
    out["found"] = ok
    return out


def _cached_detection(path: Optional[str], data: bytes) -> dict:
    """Détection mémorisée par image (chaque image stockée a un chemin unique)."""
    if not path:
        return detect_page_letterhead(data)
    if path not in _DETECT_CACHE:
        if len(_DETECT_CACHE) > 200:
            _DETECT_CACHE.clear()
        _DETECT_CACHE[path] = detect_page_letterhead(data)
    return _DETECT_CACHE[path]


def _num(v, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def page_settings(lh: dict, header: Optional[bytes], detection: Optional[dict] = None) -> dict:
    """Type de papier et marges EFFECTIFS d'un papier enregistré.
    - `mode` enregistré : il est respecté ;
    - papier ancien (sans `mode`) : « page » si l'image d'en-tête a les
      proportions d'une A4, qu'il n'y a pas d'image de pied de page ET que
      les marges ont pu être détectées (sinon on garde « bandes » : une image
      unie posée en fond masquerait le texte) ; `mode_auto` = True.
    Marges absentes : valeurs détectées, sinon valeurs par défaut."""
    mode = lh.get("mode") if lh.get("mode") in LH_MODES else None
    auto = False
    margins_missing = lh.get("page_top_mm") is None or lh.get("page_bottom_mm") is None
    if detection is None and header and ((mode == "page" and margins_missing)
                                         or (mode is None and not lh.get("footer_path"))):
        detection = _cached_detection(lh.get("header_path"), header)
    if mode is None:
        auto = True
        mode = "page" if (header and not lh.get("footer_path") and detection
                          and detection["a4_like"] and detection["found"]) else "bandes"
    det = detection or {}
    return {
        "mode": mode, "mode_auto": auto,
        "page_top_mm": _num(lh.get("page_top_mm"), det.get("top_mm", PAGE_TOP_DEFAULT_MM)),
        "page_bottom_mm": _num(lh.get("page_bottom_mm"), det.get("bottom_mm", PAGE_BOTTOM_DEFAULT_MM)),
        "page_left_mm": _num(lh.get("page_left_mm"), PAGE_SIDE_DEFAULT_MM),
        "page_right_mm": _num(lh.get("page_right_mm"), PAGE_SIDE_DEFAULT_MM),
    }


def page_bands(data: bytes, top_mm: float, bottom_mm: float) -> tuple[Optional[bytes], Optional[bytes]]:
    """Découpe d'une image « page entière » : (bande du haut, bande du bas),
    au-dessus de la marge haute et sous la marge basse (respiration de 6 mm
    retirée). Sert là où une image en fond de page n'est pas possible :
    version Word, pages en paysage du tableau de paie."""
    from PIL import Image
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            w, h = im.size
            out = []
            for mm, at_top in ((top_mm, True), (bottom_mm, False)):
                rows = round(max(0.0, mm - _BREATH_MM) / A4_MM[1] * h)
                if rows < 2:
                    out.append(None)
                    continue
                box = (0, 0, w, min(h, rows)) if at_top else (0, max(0, h - rows), w, h)
                band = im.crop(box)
                if band.mode not in ("RGB", "RGBA", "L"):
                    band = band.convert("RGBA" if "A" in band.mode else "RGB")
                buf = io.BytesIO()
                band.save(buf, format="PNG", optimize=True)
                out.append(buf.getvalue())
            return out[0], out[1]
    except Exception:  # noqa: BLE001
        logger.warning("Découpe du papier « page entière » impossible")
        return None, None


# ==========================================================================
# QR code de vérification
# ==========================================================================
def new_verify_token() -> str:
    return secrets.token_urlsafe(9)


def verify_url(token: str) -> str:
    return f"{PUBLIC_BASE_URL}/verifier/{token}"


def qr_png(text: str, box: int = 8) -> bytes:
    """Image PNG du QR code (noir sur blanc, marge réduite)."""
    import qrcode
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box, border=1)
    qr.add_data(text)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


_KIND_LABELS = {"facture": "Facture", "proforma": "Facture proforma", "recu": "Reçu de caisse"}


@public_router.get("/verify/{token}")
async def verify_document(token: str):
    """Page publique du QR code : confirme qu'un document a bien été émis par
    le cabinet. Ne renvoie que le strict nécessaire (pas le détail des lignes)."""
    if not token or len(token) > 40:
        raise HTTPException(status_code=404, detail="Document inconnu")
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "cabinet_name": 1}) or {}
    issuer = settings.get("cabinet_name") or "Cabinet ALBARKA"
    inv = await db.invoices.find_one({"verify_token": token}, {"_id": 0})
    if inv:
        client = await db.users.find_one({"id": inv.get("tenant_id")}, {"_id": 0, "company": 1, "full_name": 1}) or {}
        kyc = await db.client_kyc.find_one({"tenant_id": inv.get("tenant_id")}, {"_id": 0, "business_name": 1}) or {}
        return {"valid": True, "issuer": issuer, "kind": _KIND_LABELS.get(inv.get("document_type"), "Document"),
                "number": inv.get("number"), "date": (inv.get("issue_date") or inv.get("created_at") or "")[:10],
                # Même nom que l'encadré « Facturer à » (raison sociale de la fiche KYC en priorité)
                "client": kyc.get("business_name") or client.get("company") or client.get("full_name") or "—",
                "amount": inv.get("net_to_pay", inv.get("total")), "currency": inv.get("currency") or "XOF",
                "status": inv.get("status"), "title": inv.get("title")}
    gen = await db.generated_documents.find_one({"verify_token": token}, {"_id": 0})
    if gen:
        return {"valid": True, "issuer": issuer, "kind": gen.get("category_label") or "Document",
                "number": gen.get("number"), "date": (gen.get("created_at") or "")[:10],
                "client": gen.get("recipient_name") or "—", "title": gen.get("title")}
    payroll = await db.payroll_tables.find_one({"verify_token": token}, {"_id": 0})
    if payroll:
        return {"valid": True, "issuer": issuer, "kind": "Tableau de paie", "number": payroll.get("period_month"),
                "date": (payroll.get("generated_at") or "")[:10], "client": payroll.get("company") or "—",
                "title": f"Liste du personnel — {payroll.get('period_label') or ''}".strip(" —")}
    # Lot 8 : bulletin de paie
    from albarka_paie import bulletin_for_verify
    slip = await bulletin_for_verify(token)
    if slip:
        return {"valid": True, "issuer": issuer, **slip}
    raise HTTPException(status_code=404, detail="Document inconnu")
