"""TABLEAU DE PAIE — « Fiche de renseignement » (lot 7).

Pour un client et un mois : la liste actualisée du personnel permanent, sous
forme de tableau, comme le questionnaire RH du cabinet :
  N° | Nom / prénoms | Salaire de base | Ancienneté | Indem. de fonction |
  Indem. de logement | Indem. de transport | Indem. de responsabilité |
  Salaire brut | Salaire net       (+ ligne TOTAL)
suivi (facultatif) des questions « RUBRIQUE PAIE » et « RUBRIQUE
OBSERVATION PRÉOCCUPATION » avec leurs lignes de réponse.

  - saisie en grille : on repart du mois précédent (ou de la liste des
    employés du client) et on corrige ; le salaire brut se calcule tout seul
    (base + ancienneté + indemnités), le net est saisi ;
  - sorties : PDF (tableau en paysage au papier à en-tête + questionnaire en
    portrait, QR code de vérification) et fichier Excel (CSV).

Routes (rôles Paie & RH) :
  GET  /hr/payroll/table?tenant_id=&period_month=
  PUT  /hr/payroll/table
  GET  /hr/payroll/table/pdf?tenant_id=&period_month=&questionnaire=&letterhead_id=
  GET  /hr/payroll/table/csv?tenant_id=&period_month=
"""
from __future__ import annotations

import csv
import io
import re
import secrets
from typing import List, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, field_validator

from albarka_auth import require_roles
from albarka_docgen import MONTHS_FR, fcfa, letterhead_image_size, load_letterhead, new_verify_token, now_iso, qr_png, verify_url
from db import db

router = APIRouter(prefix="/hr/payroll", tags=["RH & Paie — tableau"])
HR_ROLES = ["superviseur", "direction", "administrateur", "rh"]

# Colonnes chiffrées du tableau (clé -> intitulé), dans l'ordre du modèle
AMOUNT_COLUMNS = [
    ("base_salary", "Salaire de base"),
    ("seniority", "Ancienneté"),
    ("allowance_function", "Indem de fonction"),
    ("allowance_housing", "Indem de logement"),
    ("allowance_transport", "Indem de transport"),
    ("allowance_responsibility", "Indem de responsabilité"),
]
# Questions du questionnaire RH (reprises du document du cabinet)
QUESTIONNAIRE = [
    ("RUBRIQUE PAIE", [
        "Pouvez-vous confirmer la présente liste du personnel ainsi que les informations relatives au traitement salarial figurant dans le tableau ci-dessus ?",
        "Y a-t-il eu des modifications au cours de ce mois ? Si oui, précisez.",
        "Y a-t-il eu un recrutement au cours de ce mois ? Si oui, donnez leurs identités et leurs fonctions.",
        "Quelle est la nature de leurs contrats et la date d'effet ?",
        "Y a-t-il des employés qui bénéficient actuellement de congés annuels ? Si oui, lesquels ?",
    ]),
    ("RUBRIQUE OBSERVATION PRÉOCCUPATION", [
        "Avez-vous des observations ou doléances concernant cette mission et l'équipe chargée de la régularisation des actes administratifs afin qu'on puisse les transmettre à notre direction pour exécution ?",
        "Avez-vous d'autres préoccupations ?",
    ]),
]


def _month_ok(v: str) -> str:
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v or ""):
        raise ValueError("Mois attendu au format AAAA-MM")
    return v


def period_label(month: str) -> str:
    """« 2026-02 » -> « FÉVRIER 2026 »."""
    y, m = month.split("-")
    return f"{MONTHS_FR[int(m) - 1].upper()} {y}"


class PayrollRow(BaseModel):
    employee_id: Optional[str] = None
    full_name: str = Field(..., min_length=1, max_length=160)
    base_salary: float = Field(0, ge=0)
    seniority: float = Field(0, ge=0)
    allowance_function: float = Field(0, ge=0)
    allowance_housing: float = Field(0, ge=0)
    allowance_transport: float = Field(0, ge=0)
    allowance_responsibility: float = Field(0, ge=0)
    gross: Optional[float] = Field(None, ge=0)   # vide = calculé
    net: Optional[float] = Field(None, ge=0)


class PayrollTableIn(BaseModel):
    tenant_id: str
    period_month: str
    legal_form: str = Field("", max_length=40)   # ex. « SARL », imprimé sous le titre
    rows: List[PayrollRow] = Field(default_factory=list, max_length=500)

    @field_validator("period_month")
    @classmethod
    def _valid_month(cls, v):
        return _month_ok(v)


def computed_gross(row: dict) -> float:
    """Salaire brut = base + ancienneté + indemnités (sauf brut saisi)."""
    if row.get("gross") not in (None, ""):
        return float(row["gross"])
    return float(sum(float(row.get(k) or 0) for k, _ in AMOUNT_COLUMNS))


def totals_of(rows: List[dict]) -> dict:
    t = {k: sum(float(r.get(k) or 0) for r in rows) for k, _ in AMOUNT_COLUMNS}
    t["gross"] = sum(computed_gross(r) for r in rows)
    t["net"] = sum(float(r.get("net") or 0) for r in rows)
    return t


async def _company(tenant_id: str) -> str:
    u = await db.users.find_one({"id": tenant_id}, {"_id": 0, "company": 1, "full_name": 1}) or {}
    kyc = await db.client_kyc.find_one({"tenant_id": tenant_id}, {"_id": 0, "business_name": 1}) or {}
    return kyc.get("business_name") or u.get("company") or u.get("full_name") or ""


def _previous_month(month: str) -> str:
    y, m = map(int, month.split("-"))
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


async def load_table(tenant_id: str, month: str) -> dict:
    """Tableau enregistré ; sinon pré-rempli depuis le mois précédent, sinon
    depuis la liste des employés du client (salaire de base)."""
    meta = await db.payroll_tables.find_one({"tenant_id": tenant_id, "period_month": month}, {"_id": 0}) or {}
    rows = await db.payroll_lines.find({"tenant_id": tenant_id, "period_month": month}, {"_id": 0}).sort("order", 1).to_list(500)
    source = "saved" if meta else None
    if not meta:
        prev = _previous_month(month)
        prev_rows = await db.payroll_lines.find({"tenant_id": tenant_id, "period_month": prev}, {"_id": 0}).sort("order", 1).to_list(500)
        if prev_rows:
            rows, source = prev_rows, "previous_month"
            meta = {"legal_form": (await db.payroll_tables.find_one({"tenant_id": tenant_id, "period_month": prev}, {"_id": 0}) or {}).get("legal_form", "")}
        else:
            emps = await db.employees.find({"tenant_id": tenant_id}, {"_id": 0}).sort("full_name", 1).to_list(500)
            rows = [{"employee_id": e["id"], "full_name": e.get("full_name"), "base_salary": e.get("base_salary") or 0} for e in emps]
            source = "employees" if emps else "empty"
    clean = []
    for r in rows:
        row = {k: r.get(k) for k in ("employee_id", "full_name", *[c for c, _ in AMOUNT_COLUMNS], "gross", "net")}
        for k, _ in AMOUNT_COLUMNS:
            row[k] = float(row.get(k) or 0)
        row["computed_gross"] = computed_gross(row)
        clean.append(row)
    return {"tenant_id": tenant_id, "period_month": month, "period_label": period_label(month),
            "company": await _company(tenant_id), "legal_form": meta.get("legal_form", ""), "source": source,
            "saved_at": meta.get("updated_at"), "rows": clean, "totals": totals_of(clean),
            "columns": [{"key": k, "label": lbl} for k, lbl in AMOUNT_COLUMNS]}


@router.get("/table")
async def get_table(tenant_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    try:
        _month_ok(period_month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return await load_table(tenant_id, period_month)


@router.put("/table")
async def save_table(payload: PayrollTableIn, user: dict = Depends(require_roles(HR_ROLES))):
    """Enregistre (remplace) les lignes du mois pour ce client."""
    if not await db.users.find_one({"id": payload.tenant_id, "roles": "client"}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Client introuvable")
    await db.payroll_lines.delete_many({"tenant_id": payload.tenant_id, "period_month": payload.period_month})
    docs = []
    for i, r in enumerate(payload.rows):
        d = r.model_dump()
        docs.append({"id": secrets.token_hex(8), "tenant_id": payload.tenant_id, "period_month": payload.period_month,
                     "order": i, **d, "gross": d.get("gross")})
    if docs:
        await db.payroll_lines.insert_many([dict(x) for x in docs])
    existing = await db.payroll_tables.find_one({"tenant_id": payload.tenant_id, "period_month": payload.period_month}, {"_id": 0})
    await db.payroll_tables.update_one(
        {"tenant_id": payload.tenant_id, "period_month": payload.period_month},
        {"$set": {"legal_form": payload.legal_form.strip(), "company": await _company(payload.tenant_id),
                  "period_label": period_label(payload.period_month), "updated_at": now_iso(), "updated_by": user["id"],
                  "verify_token": (existing or {}).get("verify_token") or new_verify_token()},
         "$setOnInsert": {"created_at": now_iso()}},
        upsert=True)
    return await load_table(payload.tenant_id, payload.period_month)


def _cell(v: float) -> str:
    """Case vide pour zéro (comme sur le modèle), montant sinon."""
    return fcfa(v) if float(v or 0) else ""


def build_payroll_pdf(table: dict, letterhead: dict, questionnaire: bool, qr_text: Optional[str]) -> bytes:
    """PDF : tableau en paysage (papier à en-tête), questionnaire en portrait."""
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_RIGHT
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (BaseDocTemplate, Frame, Image, NextPageTemplate, PageBreak, PageTemplate,
                                    Paragraph, Spacer, Table, TableStyle)

    header, footer = letterhead.get("header"), letterhead.get("footer")

    # Images du papier à en-tête : largeur d'une page portrait au plus (en
    # paysage elles restent à leur taille normale, centrées)
    def img_w(page_w):
        return min(page_w, A4[0])

    def margins(page_w):
        hh = letterhead_image_size(header, img_w(page_w))[1] if header else 0
        fh = letterhead_image_size(footer, img_w(page_w))[1] if footer else 0
        top = hh + 0.4 * cm if header else float(letterhead.get("top_margin_cm", 2.0)) * cm
        bottom = fh + 0.3 * cm if footer else float(letterhead.get("bottom_margin_cm", 2.0)) * cm
        return hh, fh, top, bottom

    def painter(page_w, page_h):
        hh, fh, _t, _b = margins(page_w)

        w = img_w(page_w)
        x = (page_w - w) / 2

        def paint(canvas, _doc):
            if header:
                canvas.drawImage(ImageReader(io.BytesIO(header)), x, page_h - hh, w, hh, mask="auto")
            if footer:
                canvas.drawImage(ImageReader(io.BytesIO(footer)), x, 0, w, fh, mask="auto")
        return paint

    land, port = landscape(A4), A4
    side = 1.5 * cm
    _h1, _f1, top_l, bottom_l = margins(land[0])
    _h2, _f2, top_p, bottom_p = margins(port[0])
    buf = io.BytesIO()
    doc = BaseDocTemplate(buf, pagesize=land, title=f"Liste du personnel — {table['period_label']}")
    doc.addPageTemplates([
        PageTemplate("paysage", pagesize=land, onPage=painter(*land),
                     frames=[Frame(side, bottom_l, land[0] - 2 * side, land[1] - top_l - bottom_l, id="fl")]),
        PageTemplate("portrait", pagesize=port, onPage=painter(*port),
                     frames=[Frame(2.5 * cm, bottom_p, port[0] - 5 * cm, port[1] - top_p - bottom_p, id="fp")]),
    ])
    title = ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=13, leading=17, alignment=TA_CENTER)
    sub = ParagraphStyle("s", fontName="Helvetica-Bold", fontSize=11, leading=15, alignment=TA_CENTER)
    head = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=8.5, leading=10, alignment=TA_CENTER)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=9, leading=11)
    cell_r = ParagraphStyle("cr", fontName="Helvetica", fontSize=9, leading=11, alignment=TA_RIGHT)
    cell_rb = ParagraphStyle("crb", fontName="Helvetica-Bold", fontSize=9, leading=11, alignment=TA_RIGHT)
    rub = ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=11, leading=15, spaceBefore=10, spaceAfter=6)
    q = ParagraphStyle("q", fontName="Helvetica", fontSize=10.5, leading=14, alignment=TA_JUSTIFY)
    dots = ParagraphStyle("d", fontName="Helvetica", fontSize=10, leading=16, textColor=colors.HexColor("#555555"))
    right = ParagraphStyle("rt", fontName="Helvetica", fontSize=10.5, leading=14, alignment=TA_RIGHT)

    story = [Paragraph("FICHE DE RENSEIGNEMENT", title),
             Paragraph(f"LISTE ACTUALISÉE DU PERSONNEL PERMANENT {escape(table['period_label'])}", sub)]
    company = " ".join(x for x in [table.get("company") or "", table.get("legal_form") or ""] if x).strip()
    if company:
        story.append(Paragraph(escape(company.upper()), sub))
    story.append(Spacer(1, 0.35 * cm))

    # ---- Tableau du personnel
    heads = ["N°", "Nom/ prénoms", *[lbl for _k, lbl in AMOUNT_COLUMNS], "Salaire brut", "Salaire net"]
    data = [[Paragraph(h, head) for h in heads]]
    for i, r in enumerate(table["rows"], 1):
        data.append([Paragraph(str(i), cell), Paragraph(escape(r.get("full_name") or ""), cell),
                     *[Paragraph(_cell(r.get(k)), cell_r) for k, _ in AMOUNT_COLUMNS],
                     Paragraph(_cell(computed_gross(r)), cell_r), Paragraph(_cell(r.get("net")), cell_r)])
    t = table["totals"]
    data.append([Paragraph("", cell), Paragraph("<b>TOTAL</b>", cell),
                 *[Paragraph(_cell(t[k]), cell_rb) for k, _ in AMOUNT_COLUMNS],
                 Paragraph(_cell(t["gross"]), cell_rb), Paragraph(_cell(t["net"]), cell_rb)])
    width = land[0] - 2 * side
    num_w, name_w = 1.0 * cm, 5.4 * cm
    other = (width - num_w - name_w) / 8
    grid = Table(data, colWidths=[num_w, name_w, *[other] * 8], repeatRows=1)
    grid.setStyle(TableStyle([
        ("GRID", (0, 0), (-1, -1), 0.6, colors.black), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EEF2F5")), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F6F8FA")),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story.append(grid)
    if qr_text:
        story += [Spacer(1, 0.3 * cm), Table([[Image(io.BytesIO(qr_png(qr_text, box=4)), width=1.8 * cm, height=1.8 * cm),
                                               Paragraph("<font size='7' color='#555555'>Scannez pour vérifier l'authenticité de ce tableau.</font>", cell)]],
                                             colWidths=[2.1 * cm, 7 * cm], hAlign="LEFT")]

    # ---- Questionnaire (page portrait)
    if questionnaire:
        story += [NextPageTemplate("portrait"), PageBreak()]
        for rubric, questions in QUESTIONNAIRE:
            story.append(Paragraph(escape(rubric), rub))
            for n, text in enumerate(questions, 1):
                story.append(Paragraph(f"{n}. {escape(text)}", q))
                story.append(Paragraph("." * 150, dots))
                story.append(Paragraph("." * 150, dots))
                story.append(Spacer(1, 0.2 * cm))
        story += [Spacer(1, 0.8 * cm), Paragraph("La responsable", right)]

    doc.build(story)
    return buf.getvalue()


@router.get("/table/pdf")
async def table_pdf(tenant_id: str, period_month: str, questionnaire: bool = True, letterhead_id: Optional[str] = None,
                    user: dict = Depends(require_roles(HR_ROLES))):
    try:
        _month_ok(period_month)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    table = await load_table(tenant_id, period_month)
    meta = await db.payroll_tables.find_one({"tenant_id": tenant_id, "period_month": period_month}, {"_id": 0}) or {}
    if meta:
        await db.payroll_tables.update_one({"tenant_id": tenant_id, "period_month": period_month}, {"$set": {"generated_at": now_iso()}})
    qr = verify_url(meta["verify_token"]) if meta.get("verify_token") else None
    pdf = build_payroll_pdf(table, await load_letterhead(letterhead_id), questionnaire, qr)
    name = f"liste-personnel-{period_month}.pdf"
    return Response(content=pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}"'})


@router.get("/table/csv")
async def table_csv(tenant_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    """Fichier Excel (CSV ; séparateur « ; », accents conservés)."""
    table = await load_table(tenant_id, period_month)
    out = io.StringIO()
    w = csv.writer(out, delimiter=";")
    w.writerow([f"LISTE ACTUALISÉE DU PERSONNEL PERMANENT {table['period_label']}", table.get("company") or ""])
    heads = ["N°", "Nom/ prénoms", *[lbl for _k, lbl in AMOUNT_COLUMNS], "Salaire brut", "Salaire net"]
    w.writerow(heads)
    num = lambda v: (f"{float(v):.0f}" if float(v or 0) else "")  # noqa: E731 — nombres bruts pour Excel
    for i, r in enumerate(table["rows"], 1):
        w.writerow([i, r.get("full_name"), *[num(r.get(k)) for k, _ in AMOUNT_COLUMNS], num(computed_gross(r)), num(r.get("net"))])
    t = table["totals"]
    w.writerow(["", "TOTAL", *[num(t[k]) for k, _ in AMOUNT_COLUMNS], num(t["gross"]), num(t["net"])])
    body = ("﻿" + out.getvalue()).encode("utf-8")
    return Response(content=body, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="liste-personnel-{period_month}.csv"'})
