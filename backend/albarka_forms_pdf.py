"""Formulaires ALBARKA — PDF d'ARCHIVAGE des réponses reçues (lot 84).

Le personnel (rôle « formulaires ») peut imprimer en PDF le contenu des réponses d'un formulaire, avec un rendu qui suit la
STRUCTURE du formulaire : pages, titres et textes de section, questions dans l'ordre du constructeur, choix proposés avec
les cases cochées, tableaux, signature. Une réponse = au moins une page ; les réponses d'un même formulaire se suivent
dans un seul fichier.

Routes (préfixe /api, lecture seule) :
  GET /forms/{fid}/submissions/pdf?date_from=&date_to=   toutes les réponses de la période (une réponse par page)
  GET /forms/{fid}/submissions/{sid}/pdf                 une seule réponse

Ce fichier est propre à ALBARKA : le module commun `forms_core/` n'est pas modifié (on ne fait que le lire).
"""
from __future__ import annotations

import io
import re
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response

from albarka_auth import require_roles
from albarka_forms import adapter
from albarka_models import FORMS_ROLES
from forms_core import in_period
from forms_core.export import readable_value
from forms_core.validation import is_visible

router = APIRouter(prefix="/forms", tags=["Formulaires — PDF d'archivage"])
manager = Depends(require_roles(FORMS_ROLES))

SOURCES = {"invitation": "Invitation", "public": "Lien public", "portal": "Espace client"}


def _safe(text: Any) -> str:
    """Texte compatible avec la police standard du PDF (Latin-1 / Windows-1252) : un caractère inconnu devient « ? »
    au lieu de faire échouer toute la génération. Puis échappement pour le mini-HTML de reportlab."""
    t = "" if text is None else str(text)
    t = t.encode("cp1252", errors="replace").decode("cp1252")
    return escape(t).replace("\n", "<br/>")


def _date_fr(iso: Optional[str]) -> str:
    """« 2026-11-02T14:05:00+00:00 » → « 02/11/2026 14:05 »."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})", iso or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)} {m.group(4)}:{m.group(5)}" if m else (iso or "")


def build_responses_pdf(form: Dict[str, Any], submissions: List[Dict[str, Any]], signatures: Dict[str, bytes]) -> bytes:
    """PDF des réponses. `signatures` : {identifiant de fichier: image PNG/JPEG} des signatures déjà lues (peut être vide)."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    green, ink, muted, line = colors.HexColor("#0F6B4A"), colors.HexColor("#0F172A"), colors.HexColor("#64748B"), colors.HexColor("#CBD5E1")
    W = A4[0] - 36 * mm                                              # largeur utile (marges de 18 mm)
    st = {
        "titre": ParagraphStyle("titre", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=green),
        "meta": ParagraphStyle("meta", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=muted),
        "page": ParagraphStyle("page", fontName="Helvetica-Bold", fontSize=10.5, leading=13, textColor=colors.white),
        "section": ParagraphStyle("section", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=green, spaceBefore=6),
        "aide": ParagraphStyle("aide", fontName="Helvetica-Oblique", fontSize=8, leading=10.5, textColor=muted),
        "q": ParagraphStyle("q", fontName="Helvetica-Bold", fontSize=9, leading=11.5, textColor=ink),
        "r": ParagraphStyle("r", fontName="Helvetica", fontSize=9.5, leading=12.5, textColor=ink),
        "vide": ParagraphStyle("vide", fontName="Helvetica-Oblique", fontSize=9, leading=12, textColor=muted),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11, textColor=ink),
        "cellh": ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=ink),
    }

    def P(txt, style="r"):
        return Paragraph(_safe(txt), st[style])

    def boite(contenu) -> Table:
        """Zone de réponse : cadre fin, comme une case de saisie du formulaire."""
        t = Table([[contenu]], colWidths=[W])
        t.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.5, line), ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
                               ("LEFTPADDING", (0, 0), (-1, -1), 7), ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
        return t

    def reponse(f: Dict[str, Any], v: Any):
        """Élément(s) de la zone de réponse d'une question, selon son type."""
        t = f.get("type")
        vide = v is None or v == "" or v == [] or v == {}
        if t in ("radio", "select", "checkbox", "multiselect"):
            # Tous les choix proposés : [X] = choisi, [ ] = non choisi (une valeur hors liste est ajoutée à la suite)
            choisis = v if isinstance(v, list) else ([] if vide else [v])
            options = list(f.get("options") or []) + [c for c in choisis if c not in (f.get("options") or [])]
            return boite([P(f"{'[X]' if o in choisis else '[  ]'}  {o}", "r") for o in options] or P("—", "vide"))
        if t == "boolean":
            return boite(P(f"{'[X]' if v is True else '[  ]'} Oui        {'[X]' if v is False else '[  ]'} Non", "r"))
        if t == "table" and isinstance(v, list) and v:
            cols = f.get("columns") or []
            data = [[Paragraph(_safe(c["label"]), st["cellh"]) for c in cols]]
            data += [[Paragraph(_safe(row.get(c["key"], "")), st["cell"]) for c in cols] for row in v if isinstance(row, dict)]
            tb = Table(data, colWidths=[W / max(len(cols), 1)] * len(cols), repeatRows=1)
            tb.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, line), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8F3EE")),
                                    ("VALIGN", (0, 0), (-1, -1), "TOP")]))
            return tb
        if t == "signature" and isinstance(v, dict):
            data = signatures.get(str(v.get("file_id") or ""))
            if data:
                try:
                    w, h = ImageReader(io.BytesIO(data)).getSize()
                    larg = min(60 * mm, W - 14)
                    return boite(Image(io.BytesIO(data), width=larg, height=larg * h / max(w, 1)))
                except Exception:                                    # image illisible : on garde la mention « Signé »
                    pass
            return boite(P("Signé (image non reproduite)", "r"))
        if t == "rating" and not vide:
            return boite(P(f"{v} / {int(f.get('max') or 5)}", "r"))
        if t == "scale" and not vide:
            return boite(P(f"{v} / 10", "r"))
        if vide:
            return boite(P("Non renseigné", "vide"))
        return boite(P(readable_value(f, v), "r"))                   # texte, nombre, date, e-mail, fichier (nom)…

    pages = form.get("pages") or []
    story: List[Any] = []
    for n, s in enumerate(submissions):
        if n:
            story.append(PageBreak())
        data = s.get("data") or {}
        # En-tête de la réponse : titre du formulaire + qui, quand, par quel canal
        story += [P(form.get("title") or "Formulaire", "titre"),
                  P(" · ".join(x for x in [form.get("number"), f"Réponse {n + 1} sur {len(submissions)}"] if x), "meta")]
        if form.get("description"):
            story.append(P(form["description"], "meta"))
        story += [Spacer(1, 3),
                  P(" · ".join(x for x in [
                      f"Répondant : {s.get('respondent_name') or 'Anonyme'}",
                      s.get("respondent_email") or "",
                      f"Reçue le {_date_fr(s.get('created_at'))}",
                      f"Origine : {SOURCES.get(s.get('source') or 'public', s.get('source') or '')}"] if x), "meta"),
                  Spacer(1, 8)]
        # Pages du formulaire, dans l'ordre du constructeur
        for pg in pages:
            champs = [f for f in (pg.get("fields") or []) if is_visible(f, data)]
            if not champs:
                continue
            if pg.get("title") and len(pages) > 1:
                bandeau = Table([[P(pg["title"], "page")]], colWidths=[W])
                bandeau.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), green), ("TOPPADDING", (0, 0), (-1, -1), 4),
                                             ("BOTTOMPADDING", (0, 0), (-1, -1), 4), ("LEFTPADDING", (0, 0), (-1, -1), 7)]))
                story += [bandeau, Spacer(1, 6)]
            for f in champs:
                if f.get("type") == "section":                      # titre / texte du formulaire
                    story.append(P(f.get("label") or "", "section"))
                    if f.get("help"):
                        story.append(P(f["help"], "aide"))
                    story.append(Spacer(1, 3))
                    continue
                bloc = [P(f"{f.get('label') or ''}{' *' if f.get('required') else ''}", "q")]
                if f.get("help"):
                    bloc.append(P(f["help"], "aide"))
                bloc += [Spacer(1, 2), reponse(f, data.get(f["id"])), Spacer(1, 7)]
                # Une question reste d'un seul tenant (sauf un tableau, qui peut être long et passer à la page suivante)
                if f.get("type") == "table":
                    story += bloc
                else:
                    story.append(KeepTogether(bloc))

    if not story:
        story = [P(form.get("title") or "Formulaire", "titre"), P("Aucune réponse sur la période demandée.", "vide")]

    titre = _safe(form.get("title") or "Formulaire").replace("<br/>", " ")
    numero = form.get("number") or ""

    def pied(canvas, doc):
        """Pied de page : référence du formulaire et numéro de page (archivage)."""
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(18 * mm, 10 * mm, f"{numero} - Cabinet ALBARKA - archivage des réponses".encode("cp1252", "replace").decode("cp1252"))
        canvas.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {doc.page}")
        canvas.restoreState()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm, bottomMargin=18 * mm,
                            title=f"{numero} {re.sub('<[^>]+>', '', titre)}".strip(), author="Cabinet ALBARKA")
    doc.build(story, onFirstPage=pied, onLaterPages=pied)
    return buf.getvalue()


# ---------------------------------------------------------------- accès aux données
async def _formulaire(fid: str, user: Dict[str, Any]) -> Dict[str, Any]:
    """Le formulaire, uniquement s'il appartient à l'espace du cabinet de l'utilisateur (même contrôle que le module commun)."""
    form = await adapter.col("").find_one({"id": fid, "scope": adapter.scope_of(user)}, {"_id": 0})
    if not form:
        raise HTTPException(status_code=404, detail="Formulaire introuvable.")
    return form


async def _signatures(form: Dict[str, Any], submissions: List[Dict[str, Any]]) -> Dict[str, bytes]:
    """Lit les images de signature des réponses (stockage ALBARKA) pour les reproduire dans le PDF."""
    champs = [f["id"] for pg in form.get("pages") or [] for f in pg.get("fields") or [] if f.get("type") == "signature"]
    out: Dict[str, bytes] = {}
    for s in submissions:
        for cid in champs:
            v = (s.get("data") or {}).get(cid)
            fid = str(v.get("file_id") or "") if isinstance(v, dict) else ""
            if fid and fid not in out:
                try:
                    lu = await adapter.read_file(fid)
                    if lu:
                        out[fid] = lu[0]
                except Exception:                                   # signature introuvable : le PDF indique « Signé »
                    pass
    return out


def _reponse_pdf(form: Dict[str, Any], contenu: bytes, suffixe: str) -> Response:
    nom = re.sub(r"[^A-Za-z0-9_-]+", "_", f"{form.get('number') or 'formulaire'}-{suffixe}")[:90]
    return Response(contenu, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{nom}.pdf"'})


@router.get("/{fid}/submissions/pdf")
async def pdf_toutes_les_reponses(fid: str, date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = manager):
    """Toutes les réponses de la période dans un seul PDF (une réponse par page, la plus ancienne d'abord)."""
    import asyncio
    form = await _formulaire(fid, user)
    items = await adapter.col("submissions").find({"form_id": fid}, {"_id": 0}).to_list(5000)
    items = sorted((s for s in items if in_period(s.get("created_at"), date_from, date_to)), key=lambda s: s.get("created_at") or "")
    if not items:
        raise HTTPException(status_code=404, detail="Aucune réponse sur la période demandée.")
    sigs = await _signatures(form, items)
    pdf = await asyncio.to_thread(build_responses_pdf, form, items, sigs)
    return _reponse_pdf(form, pdf, "reponses")


@router.get("/{fid}/submissions/{sid}/pdf")
async def pdf_une_reponse(fid: str, sid: str, user: dict = manager):
    """Une seule réponse en PDF."""
    import asyncio
    form = await _formulaire(fid, user)
    s = await adapter.col("submissions").find_one({"id": sid, "form_id": fid}, {"_id": 0})
    if not s:
        raise HTTPException(status_code=404, detail="Réponse introuvable.")
    sigs = await _signatures(form, [s])
    pdf = await asyncio.to_thread(build_responses_pdf, form, [s], sigs)
    return _reponse_pdf(form, pdf, f"reponse-{sid[:8]}")
