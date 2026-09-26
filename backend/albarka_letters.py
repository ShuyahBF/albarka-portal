"""Documents mis en forme et MODÈLES À VARIABLES (lot 7).

Pour les ordres / avis de mission, courriers, attestations… :
  - le texte est saisi dans un éditeur « comme Word » (gras, couleurs, listes,
    retraits, tableaux, images…) ; le HTML reçu est NETTOYÉ ici (liste blanche
    de balises, d'attributs et de styles) avant d'être enregistré ;
  - un document peut être enregistré comme MODÈLE réutilisable ; on y place des
    VARIABLES « {{client.nom}} », « {{date.lieu_jour}} », « {{civilite}} »… ;
  - « Générer » : on choisit les destinataires (clients), on remplit les
    valeurs communes et celles propres à chaque destinataire, et AUTANT DE
    DOCUMENTS sont produits (PDF au papier à en-tête choisi + QR code de
    vérification), numérotés automatiquement, éventuellement déposés dans
    l'espace de chaque client ;
  - un modèle se modifie, se duplique, se supprime et se VERROUILLE (plus
    aucune modification ni suppression tant qu'il n'est pas déverrouillé par
    la personne qui l'a verrouillé, son auteur, la Direction/DG, un
    Administrateur ou le Superviseur).

Collections : doc_templates, generated_documents.
Le PDF est produit avec PyMuPDF (fitz.Story : HTML + CSS -> PDF), déjà présent.
"""
from __future__ import annotations

import base64
import html as html_lib
import io
import logging
import re
import secrets
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

import albarka_storage
from albarka_auth import require_staff
from albarka_docgen import (DOC_ADMIN_ROLES, date_longue, get_doc_settings, letterhead_image_size, load_letterhead,
                            new_verify_token, now_iso, qr_png, verify_url)
from db import db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/letters", tags=["Documents & modèles"])

CATEGORIES = {
    "avis_mission": "Avis de mission",
    "ordre_mission": "Ordre de mission",
    "courrier": "Courrier",
    "attestation": "Attestation",
    "convocation": "Convocation",
    "autre": "Autre document",
}
MAX_HTML = 4 * 1024 * 1024      # 4 Mo (images comprises)
MAX_RECIPIENTS = 300

# ==========================================================================
# Nettoyage du HTML de l'éditeur (liste blanche)
# ==========================================================================
_ALLOWED_TAGS = {"p", "br", "b", "strong", "i", "em", "u", "s", "strike", "span", "div", "h1", "h2", "h3", "h4",
                 "ul", "ol", "li", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "colgroup", "col", "img",
                 "hr", "blockquote", "sub", "sup", "font", "a"}
_VOID = {"br", "img", "hr", "col"}
_DROP_CONTENT = {"script", "style", "iframe", "object", "embed", "noscript", "template", "svg", "math"}
_ALLOWED_ATTRS = {"style", "class", "data-var", "colspan", "rowspan", "src", "width", "height", "alt", "align",
                  "color", "face", "size", "href", "border", "cellpadding", "cellspacing", "valign"}
_ALLOWED_CSS = {"text-align", "margin", "margin-left", "margin-right", "margin-top", "margin-bottom", "padding",
                "padding-left", "padding-right", "padding-top", "padding-bottom", "color", "background-color",
                "background", "font-weight", "font-style", "text-decoration", "font-size", "font-family", "width",
                "height", "border", "border-top", "border-bottom", "border-left", "border-right", "border-collapse",
                "border-color", "border-width", "border-style", "vertical-align", "text-indent", "line-height",
                "list-style-type", "max-width"}
_IMG_SRC = re.compile(r"^data:image/(png|jpeg|jpg|gif|webp);base64,[A-Za-z0-9+/=\s]+$")


def _clean_style(style: str) -> str:
    """Garde seulement les propriétés CSS autorisées, sans url()/expression()."""
    out = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        prop, val = decl.split(":", 1)
        prop, val = prop.strip().lower(), val.strip()
        low = val.lower()
        if prop in _ALLOWED_CSS and val and "url(" not in low and "expression" not in low and "javascript" not in low:
            out.append(f"{prop}: {val}")
    # Bordure avec une épaisseur mais sans style (certains navigateurs le
    # retirent en copiant un tableau) : trait plein, comme dans l'éditeur
    props = {d.split(":", 1)[0] for d in out}
    if "border-width" in props and not props & {"border-style", "border"}:
        out.append("border-style: solid")
    return "; ".join(out)


class _Sanitizer(HTMLParser):
    """Reconstruit le HTML en ne gardant que ce qui est autorisé."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: List[str] = []
        self.skip = 0          # profondeur dans une balise dont on jette le contenu

    def handle_starttag(self, tag, attrs):
        if tag in _DROP_CONTENT:
            self.skip += 1
            return
        if self.skip or tag not in _ALLOWED_TAGS:
            return
        kept = []
        for name, value in attrs:
            name = (name or "").lower()
            value = value or ""
            if name not in _ALLOWED_ATTRS or name.startswith("on"):
                continue
            if name == "style":
                value = _clean_style(value)
                if not value:
                    continue
            elif name == "src":
                if not _IMG_SRC.match(value):
                    continue
            elif name == "href":
                if not re.match(r"^(https?:|mailto:)", value, re.I):
                    continue
            elif name == "class":
                value = " ".join(c for c in value.split() if c in ("tpl-var",))
                if not value:
                    continue
            elif name == "data-var":
                value = re.sub(r"[^a-z0-9_.]", "", value.lower())[:60]
            kept.append(f'{name}="{html_lib.escape(value, quote=True)}"')
        if tag == "img" and not any(k.startswith("src=") for k in kept):
            return
        self.out.append(f"<{tag}{(' ' + ' '.join(kept)) if kept else ''}>")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _DROP_CONTENT:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag not in _ALLOWED_TAGS or tag in _VOID:
            return
        self.out.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.skip:
            self.out.append(html_lib.escape(data, quote=False))


def sanitize_html(raw: str) -> str:
    """HTML sûr (aucun script, aucun lien externe d'image, styles filtrés)."""
    if not raw:
        return ""
    if len(raw) > MAX_HTML:
        raise HTTPException(status_code=413, detail="Document trop volumineux (4 Mo maximum, images comprises)")
    p = _Sanitizer()
    p.feed(raw)
    p.close()
    return "".join(p.out)


def html_to_text(raw: str) -> str:
    """Texte brut (aperçu dans les listes)."""
    txt = re.sub(r"<(br|/p|/div|/li|/h\d|/tr)[^>]*>", "\n", raw or "", flags=re.I)
    txt = re.sub(r"<[^>]+>", "", txt)
    return re.sub(r"\n{3,}", "\n\n", html_lib.unescape(txt)).strip()


# ==========================================================================
# Variables
# ==========================================================================
# Variables fournies automatiquement (clé -> libellé affiché dans l'éditeur)
SYSTEM_VARIABLES = {
    "date.lieu_jour": "Lieu et date (« Ouagadougou, le 17 août 2026 »)",
    "date.jour": "Date du document (« 17 août 2026 »)",
    "doc.numero": "Numéro du document",
    "client.nom": "Client — raison sociale",
    "client.contact": "Client — nom du contact",
    "client.adresse": "Client — adresse",
    "client.ifu": "Client — IFU",
    "client.rccm": "Client — RCCM",
    "client.email": "Client — e-mail",
    "client.telephone": "Client — téléphone",
    "signataire.titre": "Signataire — titre",
    "signataire.nom": "Signataire — nom",
    "cabinet.nom": "Nom du cabinet",
    "mission.titre": "Mission — intitulé",
    "mission.description": "Mission — description",
    "mission.echeance": "Mission — échéance",
}
_VAR_RE = re.compile(r"\{\{\s*([a-z0-9_.]+)\s*\}\}")


def used_variables(body: str) -> List[str]:
    """Variables présentes dans le texte, dans l'ordre d'apparition."""
    seen: List[str] = []
    for key in _VAR_RE.findall(body or ""):
        if key not in seen:
            seen.append(key)
    return seen


def render_body(body: str, values: Dict[str, str]) -> str:
    """Remplace chaque {{variable}} par sa valeur (texte échappé, retours à la
    ligne conservés ; la description de mission est déjà du HTML nettoyé)."""
    def repl(m):
        key = m.group(1)
        if key not in values:
            return m.group(0)
        val = values[key]
        if key == "mission.description":
            return val or ""
        return html_lib.escape(str(val or "")).replace("\n", "<br>")
    out = _VAR_RE.sub(repl, body or "")
    # La pastille de variable de l'éditeur disparaît dans le document final
    return re.sub(r'<span class="tpl-var"[^>]*>(.*?)</span>', r"\1", out, flags=re.S)


async def client_values(tenant_id: str) -> Dict[str, str]:
    """Valeurs « client.* » à partir de la fiche client et de sa fiche KYC."""
    u = await db.users.find_one({"id": tenant_id}, {"_id": 0, "password_hash": 0}) or {}
    kyc = await db.client_kyc.find_one({"tenant_id": tenant_id}, {"_id": 0}) or {}
    return {
        "client.nom": kyc.get("business_name") or u.get("company") or u.get("full_name") or "",
        "client.contact": u.get("full_name") or "",
        "client.adresse": kyc.get("address") or u.get("address") or "",
        "client.ifu": kyc.get("ifu") or "",
        "client.rccm": kyc.get("rccm") or "",
        "client.email": u.get("email") or "",
        "client.telephone": u.get("phone") or "",
    }


# ==========================================================================
# PDF : HTML -> PDF (PyMuPDF Story) + papier à en-tête + QR code
# ==========================================================================
_PDF_CSS = """
body { font-family: sans-serif; font-size: 11pt; line-height: 1.35; color: #000; }
p { margin: 0 0 5pt 0; }
h1 { font-size: 18pt; margin: 6pt 0; } h2 { font-size: 15pt; margin: 6pt 0; } h3 { font-size: 13pt; margin: 5pt 0; }
table { border-collapse: collapse; }
td, th { padding: 3pt 5pt; vertical-align: top; }
blockquote { margin: 0 0 0 36pt; }
"""
_A4 = (595.0, 842.0)
_SIDE = 2.5 * 28.35          # marges gauche/droite (2,5 cm, comme le modèle)


def _extract_images(body: str):
    """Remplace les images data: par des noms de fichiers d'une archive PyMuPDF."""
    import fitz
    arch = fitz.Archive()
    count = [0]

    def repl(m):
        kind, data = m.group(1), m.group(2)
        try:
            raw = base64.b64decode(re.sub(r"\s", "", data))
        except Exception:  # noqa: BLE001
            return 'src=""'
        count[0] += 1
        name = f"img{count[0]}.{'jpg' if kind in ('jpeg', 'jpg') else kind}"
        arch.add(raw, name)
        return f'src="{name}"'

    body = re.sub(r'src="data:image/(png|jpeg|jpg|gif|webp);base64,([^"]+)"', repl, body)
    return body, arch


def html_to_pdf(body: str, letterhead: dict, qr_text: Optional[str] = None) -> bytes:
    """PDF A4 : texte mis en forme, papier à en-tête sur chaque page, QR code
    de vérification dans la marge droite de la première page."""
    import fitz
    header, footer = letterhead.get("header"), letterhead.get("footer")
    header_h = letterhead_image_size(header, _A4[0])[1] if header else 0
    footer_h = letterhead_image_size(footer, _A4[0])[1] if footer else 0
    top = header_h + 14 if header else float(letterhead.get("top_margin_cm", 2.0)) * 28.35
    bottom = footer_h + 12 if footer else float(letterhead.get("bottom_margin_cm", 2.0)) * 28.35
    body, arch = _extract_images(body or "<p></p>")
    story = fitz.Story(html=f"<body>{body}</body>", user_css=_PDF_CSS, archive=arch)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    page_rect = fitz.Rect(0, 0, *_A4)
    where = fitz.Rect(_SIDE, top, _A4[0] - _SIDE, _A4[1] - bottom)
    more, pages = 1, 0
    while more and pages < 60:
        dev = writer.begin_page(page_rect)
        more, _ = story.place(where)
        story.draw(dev)
        writer.end_page()
        pages += 1
    writer.close()
    # Second passage : images du papier à en-tête et QR code
    doc = fitz.open("pdf", buf.getvalue())
    for i, page in enumerate(doc):
        if header:
            page.insert_image(fitz.Rect(0, 0, _A4[0], header_h), stream=header, keep_proportion=False)
        if footer:
            page.insert_image(fitz.Rect(0, _A4[1] - footer_h, _A4[0], _A4[1]), stream=footer, keep_proportion=False)
        if i == 0 and qr_text:
            size = 50
            x0 = _A4[0] - _SIDE + (_SIDE - size) / 2
            y0 = top + 2
            page.insert_image(fitz.Rect(x0, y0, x0 + size, y0 + size), stream=qr_png(qr_text, box=4))
            page.insert_textbox(fitz.Rect(x0 - 8, y0 + size + 1, x0 + size + 8, y0 + size + 20), "Vérifier",
                                fontsize=6, align=1, color=(0.35, 0.35, 0.35))
    out = doc.tobytes(deflate=True, garbage=3)
    doc.close()
    return out


def word_html(body: str, letterhead: dict, title: str) -> bytes:
    """Version « Word » (.doc) : page HTML que Word ouvre et modifie telle quelle."""
    parts = []
    for part in ("header", "footer"):
        data = letterhead.get(part)
        if data:
            parts.append(f'<p style="margin:0"><img src="data:image/png;base64,{base64.b64encode(data).decode()}" width="620"></p>')
        else:
            parts.append("")
    page = (f"<html xmlns:o='urn:schemas-microsoft-com:office:office' xmlns:w='urn:schemas-microsoft-com:office:word'>"
            f"<head><meta charset='utf-8'><title>{html_lib.escape(title)}</title>"
            f"<style>body{{font-family:Arial,sans-serif;font-size:11pt}} table{{border-collapse:collapse}}"
            f" td,th{{padding:3pt 5pt;vertical-align:top}}</style></head><body>"
            f"{parts[0]}{body}{parts[1]}</body></html>")
    return ("﻿" + page).encode("utf-8")


# ==========================================================================
# Modèles
# ==========================================================================
class VariableDef(BaseModel):
    key: str = Field(..., min_length=1, max_length=40)
    label: str = Field(..., min_length=1, max_length=120)
    scope: str = Field("recipient", description="common = même valeur pour tous ; recipient = une valeur par destinataire")
    default: str = Field("", max_length=500)


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    category: str = "autre"
    body_html: str = ""
    variables: List[VariableDef] = []
    number_format: str = Field("{n}/{annee}", max_length=60)
    next_number: int = Field(1, ge=1, le=10_000_000)
    letterhead_id: Optional[str] = None
    title_pattern: str = Field("", max_length=160)


def _slug(key: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", key.strip().lower())[:40].strip("_") or "variable"


def _clean_template(payload: TemplateIn) -> Dict[str, Any]:
    """Champs nettoyés d'un modèle (HTML sûr, clés de variables normalisées)."""
    variables, seen = [], set()
    for v in payload.variables:
        # Les clés « client.nom », « date.jour »… sont réservées aux variables automatiques
        if "." in v.key:
            continue
        key = _slug(v.key)
        if key in seen:
            continue
        seen.add(key)
        variables.append({"key": key, "label": v.label.strip(), "scope": "common" if v.scope == "common" else "recipient",
                          "default": v.default})
    return {"name": payload.name.strip(), "category": payload.category if payload.category in CATEGORIES else "autre",
            "body_html": sanitize_html(payload.body_html), "variables": variables,
            "number_format": payload.number_format.strip() or "{n}/{annee}", "next_number": payload.next_number,
            "letterhead_id": payload.letterhead_id or None, "title_pattern": payload.title_pattern.strip()}


def _can_unlock(user: dict, tpl: dict) -> bool:
    roles = set(user.get("roles") or [])
    return (user["id"] in (tpl.get("locked_by"), tpl.get("created_by"))
            or bool(roles & set(DOC_ADMIN_ROLES)) or "superviseur" in roles)


def _summary(tpl: dict) -> dict:
    out = {k: tpl.get(k) for k in ("id", "name", "category", "variables", "number_format", "next_number", "letterhead_id",
                                    "title_pattern", "locked", "locked_by_name", "locked_at", "created_by_name",
                                    "created_at", "updated_at", "updated_by_name", "generated_count", "is_seed")}
    out["category_label"] = CATEGORIES.get(tpl.get("category"), "Document")
    out["excerpt"] = html_to_text(tpl.get("body_html") or "")[:220]
    return out


async def _template_or_404(tpl_id: str) -> dict:
    tpl = await db.doc_templates.find_one({"id": tpl_id, "deleted_at": None}, {"_id": 0})
    if not tpl:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return tpl


def _ensure_unlocked(tpl: dict) -> None:
    if tpl.get("locked"):
        raise HTTPException(status_code=423, detail=f"Modèle verrouillé par {tpl.get('locked_by_name') or 'un collaborateur'} : "
                                                    "déverrouillez-le d'abord.")


@router.get("/catalog")
async def catalog(user: dict = Depends(require_staff())):
    """Catégories et variables automatiques (menu « Insérer une variable »)."""
    return {"categories": CATEGORIES, "system_variables": SYSTEM_VARIABLES}


@router.get("/templates")
async def list_templates(user: dict = Depends(require_staff())):
    items = await db.doc_templates.find({"deleted_at": None}, {"_id": 0}).sort("name", 1).to_list(500)
    return [_summary(t) for t in items]


@router.get("/templates/{tpl_id}")
async def get_template(tpl_id: str, user: dict = Depends(require_staff())):
    tpl = await _template_or_404(tpl_id)
    return {**_summary(tpl), "body_html": tpl.get("body_html") or "",
            "used_variables": used_variables(tpl.get("body_html") or ""), "can_unlock": _can_unlock(user, tpl)}


@router.post("/templates", status_code=201)
async def create_template(payload: TemplateIn, user: dict = Depends(require_staff())):
    fields = _clean_template(payload)
    if await db.doc_templates.find_one({"name": {"$regex": f"^{re.escape(fields['name'])}$", "$options": "i"}, "deleted_at": None}):
        raise HTTPException(status_code=409, detail="Un modèle porte déjà ce nom")
    tpl = {"id": secrets.token_hex(8), **fields, "locked": False, "created_by": user["id"],
           "created_by_name": user.get("full_name") or user.get("email"), "created_at": now_iso(),
           "updated_at": now_iso(), "generated_count": 0, "deleted_at": None}
    await db.doc_templates.insert_one(dict(tpl))
    return await get_template(tpl["id"], user)


@router.put("/templates/{tpl_id}")
async def update_template(tpl_id: str, payload: TemplateIn, user: dict = Depends(require_staff())):
    tpl = await _template_or_404(tpl_id)
    _ensure_unlocked(tpl)
    fields = _clean_template(payload)
    clash = await db.doc_templates.find_one({"name": {"$regex": f"^{re.escape(fields['name'])}$", "$options": "i"},
                                             "deleted_at": None, "id": {"$ne": tpl_id}})
    if clash:
        raise HTTPException(status_code=409, detail="Un modèle porte déjà ce nom")
    await db.doc_templates.update_one({"id": tpl_id}, {"$set": {
        **fields, "updated_at": now_iso(), "updated_by": user["id"],
        "updated_by_name": user.get("full_name") or user.get("email")}})
    return await get_template(tpl_id, user)


@router.post("/templates/{tpl_id}/duplicate", status_code=201)
async def duplicate_template(tpl_id: str, user: dict = Depends(require_staff())):
    tpl = await _template_or_404(tpl_id)
    name = f"{tpl['name']} (copie)"
    n = 2
    while await db.doc_templates.find_one({"name": name, "deleted_at": None}):
        name = f"{tpl['name']} (copie {n})"
        n += 1
    copy = {**{k: tpl.get(k) for k in ("category", "body_html", "variables", "number_format", "letterhead_id", "title_pattern")},
            "id": secrets.token_hex(8), "name": name, "next_number": 1, "locked": False, "created_by": user["id"],
            "created_by_name": user.get("full_name") or user.get("email"), "created_at": now_iso(),
            "updated_at": now_iso(), "generated_count": 0, "deleted_at": None}
    await db.doc_templates.insert_one(dict(copy))
    return await get_template(copy["id"], user)


@router.delete("/templates/{tpl_id}")
async def delete_template(tpl_id: str, user: dict = Depends(require_staff())):
    """Suppression (les documents déjà générés sont conservés)."""
    tpl = await _template_or_404(tpl_id)
    _ensure_unlocked(tpl)
    await db.doc_templates.update_one({"id": tpl_id}, {"$set": {"deleted_at": now_iso(), "deleted_by": user["id"]}})
    return {"ok": True}


@router.post("/templates/{tpl_id}/lock")
async def lock_template(tpl_id: str, user: dict = Depends(require_staff())):
    tpl = await _template_or_404(tpl_id)
    if not tpl.get("locked"):
        await db.doc_templates.update_one({"id": tpl_id}, {"$set": {
            "locked": True, "locked_by": user["id"], "locked_by_name": user.get("full_name") or user.get("email"),
            "locked_at": now_iso()}})
    return await get_template(tpl_id, user)


@router.post("/templates/{tpl_id}/unlock")
async def unlock_template(tpl_id: str, user: dict = Depends(require_staff())):
    tpl = await _template_or_404(tpl_id)
    if tpl.get("locked") and not _can_unlock(user, tpl):
        raise HTTPException(status_code=403, detail="Seuls la personne qui l'a verrouillé, son auteur, la Direction, "
                                                    "un Administrateur ou le Superviseur peuvent le déverrouiller.")
    await db.doc_templates.update_one({"id": tpl_id}, {"$set": {"locked": False, "locked_by": None,
                                                                "locked_by_name": None, "locked_at": None}})
    return await get_template(tpl_id, user)


# ==========================================================================
# Génération
# ==========================================================================
class GenerateIn(BaseModel):
    tenant_ids: List[str] = Field(..., min_length=1)
    common_values: Dict[str, str] = {}
    recipient_values: Dict[str, Dict[str, str]] = {}
    doc_date: Optional[str] = None
    letterhead_id: Optional[str] = None
    mission_id: Optional[str] = None
    deposit: bool = False          # déposer dans l'espace de chaque client
    notify: bool = False           # et le prévenir
    body_html: Optional[str] = None  # texte modifié juste pour cette génération (facultatif)


def format_number(fmt: str, n: int, doc_date: str) -> str:
    """« {n}/GESP/DG/{annee} » -> « 126/GESP/DG/2026 » ({n:03} = 3 chiffres, {mois})."""
    year, month = (doc_date or now_iso())[:4], (doc_date or now_iso())[5:7]
    out = re.sub(r"\{n:0?(\d)\}", lambda m: str(n).zfill(int(m.group(1))), fmt or "{n}")
    return out.replace("{n}", str(n)).replace("{annee}", year).replace("{mois}", month)


async def _values_for(tpl: dict, tenant_id: str, payload: GenerateIn, settings: dict, cabinet: str,
                      mission: Optional[dict], number: str) -> Dict[str, str]:
    """Toutes les valeurs d'un destinataire : automatiques + communes + propres."""
    doc_date = (payload.doc_date or now_iso())[:10]
    values = {
        "date.jour": date_longue(doc_date),
        "date.lieu_jour": f"{settings.get('city') or 'Ouagadougou'}, le {date_longue(doc_date)}",
        "doc.numero": number,
        "signataire.titre": settings.get("signatory_title") or "",
        "signataire.nom": settings.get("signatory_name") or "",
        "cabinet.nom": cabinet,
        **await client_values(tenant_id),
    }
    if mission:
        values.update({"mission.titre": mission.get("title") or "",
                       "mission.description": sanitize_html(mission.get("description_html") or "")
                       or html_lib.escape(mission.get("description") or "").replace("\n", "<br>"),
                       "mission.echeance": date_longue(mission.get("due_date")) if mission.get("due_date") else ""})
    for v in tpl.get("variables") or []:
        if v["scope"] == "common":
            values[v["key"]] = payload.common_values.get(v["key"], v.get("default") or "")
        else:
            values[v["key"]] = (payload.recipient_values.get(tenant_id) or {}).get(v["key"], v.get("default") or "")
    return values


async def _deposit(doc: dict, pdf: bytes, user: dict, notify: bool) -> Optional[str]:
    """Dépose le PDF dans l'espace du client (catégorie Courrier) — même
    enregistrement qu'un dépôt fait depuis « Dépôt espace client »."""
    from albarka_client_space import _portal_link, _upload_item, notify_client
    fname = f"{doc['number'] or doc['title']}.pdf".replace("/", "-")
    stored = await albarka_storage.save_and_log(
        db, data=pdf, kind="client_space", tenant_id=doc["tenant_id"], ext="pdf", content_type="application/pdf",
        original_filename=fname, user_id=user["id"])
    now = now_iso()
    cdoc = {"id": secrets.token_urlsafe(12), "tenant_id": doc["tenant_id"], "category": "courrier",
            "title": doc["title"][:200], "reference": (doc.get("number") or "")[:80] or None, "amount": None,
            "currency": "XOF", "doc_date": doc.get("doc_date"), "storage_id": stored["id"], "storage_path": stored["path"],
            "content_type": "application/pdf", "size": stored["size"], "original_filename": fname,
            "visible": True, "published_at": now, "uploaded_by": user["id"],
            "uploaded_by_name": user.get("full_name") or user.get("email"), "created_at": now, "viewed_at": None,
            "is_deleted": False, "notifications": [], "generated_document_id": doc["id"]}
    await db.client_documents.insert_one(dict(cdoc))
    if notify:
        client = await db.users.find_one({"id": doc["tenant_id"]}, {"_id": 0, "password_hash": 0})
        if client:
            try:
                note = await notify_client(client, [_upload_item(cdoc)], link=_portal_link(None))
                await db.client_documents.update_one({"id": cdoc["id"]}, {"$push": {"notifications": note}})
            except Exception:  # noqa: BLE001 — le dépôt reste valable sans notification
                logger.exception("Notification du dépôt %s échouée", cdoc["id"])
    return cdoc["id"]


@router.post("/templates/{tpl_id}/preview")
async def preview(tpl_id: str, payload: GenerateIn, user: dict = Depends(require_staff())):
    """Aperçu PDF pour le 1er destinataire (rien n'est enregistré, numéro provisoire)."""
    tpl = await _template_or_404(tpl_id)
    settings = await get_doc_settings()
    cab = (await db.settings.find_one({"_id": "global"}, {"_id": 0, "cabinet_name": 1}) or {}).get("cabinet_name") or "Cabinet ALBARKA"
    mission = await db.missions.find_one({"id": payload.mission_id}, {"_id": 0}) if payload.mission_id else None
    number = format_number(tpl.get("number_format"), int(tpl.get("next_number") or 1), payload.doc_date or now_iso())
    values = await _values_for(tpl, payload.tenant_ids[0], payload, settings, cab, mission, number)
    body = sanitize_html(payload.body_html) if payload.body_html else tpl.get("body_html") or ""
    letterhead = await load_letterhead(payload.letterhead_id or tpl.get("letterhead_id"))
    pdf = html_to_pdf(render_body(body, values), letterhead, qr_text=verify_url("apercu"))
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="apercu.pdf"'})


@router.post("/templates/{tpl_id}/generate")
async def generate(tpl_id: str, payload: GenerateIn, user: dict = Depends(require_staff())):
    """Produit UN document par destinataire, numéroté, avec PDF stocké."""
    tpl = await _template_or_404(tpl_id)
    ids = list(dict.fromkeys(payload.tenant_ids))
    if len(ids) > MAX_RECIPIENTS:
        raise HTTPException(status_code=400, detail=f"{MAX_RECIPIENTS} destinataires maximum")
    clients = {c["id"]: c for c in await db.users.find({"id": {"$in": ids}, "roles": "client"}, {"_id": 0, "password_hash": 0}).to_list(len(ids))}
    missing = [i for i in ids if i not in clients]
    if missing:
        raise HTTPException(status_code=400, detail="Destinataire inconnu (clients uniquement)")
    settings = await get_doc_settings()
    cab = (await db.settings.find_one({"_id": "global"}, {"_id": 0, "cabinet_name": 1}) or {}).get("cabinet_name") or "Cabinet ALBARKA"
    mission = await db.missions.find_one({"id": payload.mission_id}, {"_id": 0}) if payload.mission_id else None
    body = sanitize_html(payload.body_html) if payload.body_html else tpl.get("body_html") or ""
    lh_id = payload.letterhead_id or tpl.get("letterhead_id")
    letterhead = await load_letterhead(lh_id)
    doc_date = (payload.doc_date or now_iso())[:10]
    batch_id = secrets.token_hex(6)
    created = []
    for tid in ids:
        # Numéro : compteur du modèle incrémenté de façon atomique
        res = await db.doc_templates.find_one_and_update({"id": tpl_id}, {"$inc": {"next_number": 1, "generated_count": 1}})
        n = int((res or {}).get("next_number") or 1)
        number = format_number(tpl.get("number_format"), n, doc_date)
        values = await _values_for(tpl, tid, payload, settings, cab, mission, number)
        rendered = render_body(body, values)
        client_name = values.get("client.nom") or clients[tid].get("full_name") or ""
        title = render_body(tpl.get("title_pattern") or "", values) if tpl.get("title_pattern") else \
            f"{CATEGORIES.get(tpl.get('category'), 'Document')} — {client_name}"
        token = new_verify_token()
        pdf = html_to_pdf(rendered, letterhead, qr_text=verify_url(token))
        stored = await albarka_storage.save_and_log(
            db, data=pdf, kind="generated_document", tenant_id=tid, ext="pdf", content_type="application/pdf",
            original_filename=f"{number}.pdf".replace("/", "-"), user_id=user["id"])
        doc = {"id": secrets.token_hex(8), "batch_id": batch_id, "template_id": tpl_id, "template_name": tpl.get("name"),
               "category": tpl.get("category"), "category_label": CATEGORIES.get(tpl.get("category"), "Document"),
               "number": number, "tenant_id": tid, "recipient_name": client_name, "title": re.sub(r"<[^>]+>", "", title)[:200],
               "body_html": rendered, "values": {k: v for k, v in values.items() if k != "mission.description"},
               "letterhead_id": lh_id, "mission_id": payload.mission_id, "doc_date": doc_date, "verify_token": token,
               "storage_path": stored["path"], "size": stored["size"], "created_by": user["id"],
               "created_by_name": user.get("full_name") or user.get("email"), "created_at": now_iso(),
               "client_document_id": None, "deleted_at": None}
        if payload.deposit:
            doc["client_document_id"] = await _deposit(doc, pdf, user, payload.notify)
        await db.generated_documents.insert_one(dict(doc))
        created.append(_doc_summary(doc))
    return {"batch_id": batch_id, "count": len(created), "items": created}


def _doc_summary(d: dict) -> dict:
    return {k: d.get(k) for k in ("id", "batch_id", "template_id", "template_name", "category", "category_label", "number",
                                   "tenant_id", "recipient_name", "title", "doc_date", "mission_id", "created_by_name",
                                   "created_at", "client_document_id")}


# ==========================================================================
# Documents générés
# ==========================================================================
@router.get("/documents")
async def list_documents(tenant_id: Optional[str] = None, template_id: Optional[str] = None,
                         mission_id: Optional[str] = None, batch_id: Optional[str] = None,
                         user: dict = Depends(require_staff())):
    q: Dict[str, Any] = {"deleted_at": None}
    for k, v in (("tenant_id", tenant_id), ("template_id", template_id), ("mission_id", mission_id), ("batch_id", batch_id)):
        if v:
            q[k] = v
    items = await db.generated_documents.find(q, {"_id": 0, "body_html": 0}).sort("created_at", -1).to_list(1000)
    return [_doc_summary(d) for d in items]


async def _gdoc_or_404(doc_id: str) -> dict:
    d = await db.generated_documents.find_one({"id": doc_id, "deleted_at": None}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return d


@router.get("/documents/{doc_id}/pdf")
async def document_pdf(doc_id: str, download: bool = False, user: dict = Depends(require_staff())):
    d = await _gdoc_or_404(doc_id)
    try:
        data, _ct = await albarka_storage.get_object(d["storage_path"])
    except Exception:  # noqa: BLE001 — fichier perdu : on le reconstruit
        data = html_to_pdf(d.get("body_html") or "", await load_letterhead(d.get("letterhead_id")), verify_url(d["verify_token"]))
    name = f"{(d.get('number') or d['id']).replace('/', '-')}.pdf"
    return Response(content=data, media_type="application/pdf",
                    headers={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{name}"'})


@router.get("/documents/{doc_id}/word")
async def document_word(doc_id: str, user: dict = Depends(require_staff())):
    """Fichier .doc (ouvrable et modifiable dans Word)."""
    d = await _gdoc_or_404(doc_id)
    data = word_html(d.get("body_html") or "", await load_letterhead(d.get("letterhead_id")), d.get("title") or "Document")
    name = f"{(d.get('number') or d['id']).replace('/', '-')}.doc"
    return Response(content=data, media_type="application/msword", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/documents/merged-pdf")
async def merged_pdf(payload: Dict[str, Any] = Body(...), user: dict = Depends(require_staff())):
    """Un seul PDF avec plusieurs documents (impression groupée d'une génération)."""
    import fitz
    ids = [str(i) for i in (payload.get("ids") or [])][:MAX_RECIPIENTS]
    if payload.get("batch_id"):
        ids = [d["id"] for d in await db.generated_documents.find({"batch_id": payload["batch_id"], "deleted_at": None},
                                                                   {"_id": 0, "id": 1}).sort("created_at", 1).to_list(MAX_RECIPIENTS)]
    if not ids:
        raise HTTPException(status_code=400, detail="Aucun document")
    out = fitz.open()
    for i in ids:
        d = await db.generated_documents.find_one({"id": i, "deleted_at": None}, {"_id": 0, "storage_path": 1})
        if not d:
            continue
        data, _ct = await albarka_storage.get_object(d["storage_path"])
        with fitz.open("pdf", data) as src:
            out.insert_pdf(src)
    data = out.tobytes(deflate=True, garbage=3)
    out.close()
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": 'inline; filename="documents.pdf"'})


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: dict = Depends(require_staff())):
    """Supprime un document généré (le dépôt éventuel dans l'espace client reste,
    il se retire depuis « Dépôt espace client »)."""
    await _gdoc_or_404(doc_id)
    await db.generated_documents.update_one({"id": doc_id}, {"$set": {"deleted_at": now_iso(), "deleted_by": user["id"]}})
    return {"ok": True}


# ==========================================================================
# Mise en place : index + modèle « Avis de mission » fourni d'office
# ==========================================================================
_SEED_AVIS = """
<p style="text-align: right">{{date.lieu_jour}}</p>
<p style="margin-left: 230px">Au<br>{{destinataire_titre}}<br>De {{client.nom}}<br>{{ville_destinataire}}</p>
<p><b>N° {{doc.numero}}</b></p>
<p><b>Objet : <u>Avis de mission</u></b></p>
<p style="text-align: center">{{civilite}},</p>
<p style="text-align: justify">Nous venons par la présente, vous informer d'une mission relative au {{objet_mission}}.</p>
<p style="text-align: justify">Cette séance de travail est prévue {{periode_mission}}.</p>
<p style="text-align: justify">Elle consistera à un entretien et à une consultation de vos pièces administratives (registre employeur, cartes des travailleurs et la fiche de déclaration à l'inspection du travail, le règlement intérieur) et des dossiers du personnel (dossiers individuels, les déclarations, les contrats de travail, les éléments de la paie).</p>
<p style="text-align: justify">À l'issue de ce traitement sera établie une mise à jour complète de vos dossiers ressources humaines.</p>
<p style="text-align: justify">À cet effet, nous vous prions de bien vouloir confirmer une date précise et de bien vouloir mettre à notre disposition les documents y relatifs pour l'exercice de cette mission.</p>
<p style="text-align: justify">Tout en vous remerciant de votre collaboration et vous souhaitant une bonne réception, recevez {{civilite_min}}, l'expression de mes salutations distinguées.</p>
<p style="margin-left: 230px; margin-top: 18px">{{signataire.titre}}</p>
<p style="margin-left: 230px; margin-top: 48px"><b>{{signataire.nom}}</b></p>
"""
_SEED_VARIABLES = [
    {"key": "destinataire_titre", "label": "Fonction du destinataire", "scope": "recipient", "default": "Pharmacien Gérant"},
    {"key": "ville_destinataire", "label": "Ville du destinataire", "scope": "recipient", "default": "OUAGADOUGOU"},
    {"key": "civilite", "label": "Formule d'appel", "scope": "recipient", "default": "Docteur"},
    {"key": "civilite_min", "label": "Formule d'appel (dans la phrase finale)", "scope": "recipient", "default": "docteur"},
    {"key": "objet_mission", "label": "Objet de la mission", "scope": "common",
     "default": "traitement des dossiers ressources humaines de vos entreprises"},
    {"key": "periode_mission", "label": "Période de la mission", "scope": "common",
     "default": "du mardi 18 au vendredi 21 août 2026"},
]


def _seed_body() -> str:
    """Corps du modèle : chaque variable dans une pastille de l'éditeur."""
    return re.sub(r"\{\{([a-z0-9_.]+)\}\}", r'<span class="tpl-var" data-var="\1">{{\1}}</span>', _SEED_AVIS.strip())


async def ensure_letters_setup() -> None:
    await db.doc_templates.create_index("id", unique=True)
    await db.generated_documents.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.generated_documents.create_index("verify_token")
    await db.invoices.create_index("verify_token")
    if not await db.doc_templates.find_one({"seed_key": "avis_mission_v1"}):
        await db.doc_templates.insert_one({
            "id": secrets.token_hex(8), "seed_key": "avis_mission_v1", "is_seed": True, "name": "Avis de mission",
            "category": "avis_mission", "body_html": _seed_body(), "variables": _SEED_VARIABLES,
            "number_format": "{n}/GESP/DG/{annee}", "next_number": 1, "letterhead_id": None,
            "title_pattern": "Avis de mission — {{client.nom}}", "locked": False, "created_by": None,
            "created_by_name": "Portail", "created_at": now_iso(), "updated_at": now_iso(), "generated_count": 0,
            "deleted_at": None})
