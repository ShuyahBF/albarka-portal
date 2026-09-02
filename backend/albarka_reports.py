"""Rapports client PDF — synthèse mensuelle : missions, échéances, pièces analysées."""
from __future__ import annotations

import io
from datetime import datetime, timezone
from typing import List

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
)

# Brand colors matching the app
BRAND_EMERALD = colors.HexColor("#0F6B4A")
BRAND_EMERALD_DEEP = colors.HexColor("#0B1912")
BRAND_AMBER = colors.HexColor("#E5A24B")
BRAND_PAPER = colors.HexColor("#FBFAF4")
BRAND_INK = colors.HexColor("#0F172A")
BRAND_MUTED = colors.HexColor("#64748B")
BRAND_BORDER = colors.HexColor("#E2E8F0")

MISSION_TYPE_LABELS = {
    "tenue_comptable": "Tenue comptable",
    "declaration_fiscale": "Déclaration fiscale",
    "paie_rh": "Paie / RH",
    "audit": "Audit",
    "conseil": "Conseil",
    "creation_entreprise": "Création d'entreprise",
    "autre": "Autre",
}
MISSION_STATUS_LABELS = {
    "en_attente": "En attente", "en_cours": "En cours",
    "en_revue": "En revue", "terminee": "Terminée", "archivee": "Archivée",
}
ECHEANCE_STATUS_LABELS = {
    "a_venir": "À venir", "en_cours": "En cours",
    "traitee": "Traitée", "en_retard": "En retard",
}
DOCUMENT_STATUS_LABELS = {
    "recu": "Reçu", "en_analyse": "Analyse en cours",
    "analyse": "Analysé", "erreur_analyse": "Erreur d'analyse",
}


def _paragraph_styles():
    ss = getSampleStyleSheet()
    ss.add(ParagraphStyle(
        name="AlbTitle", parent=ss["Title"], textColor=BRAND_EMERALD_DEEP,
        fontSize=22, leading=26, spaceAfter=6, alignment=0,
    ))
    ss.add(ParagraphStyle(
        name="AlbSubtitle", parent=ss["Normal"], textColor=BRAND_MUTED,
        fontSize=10, leading=14, spaceAfter=18,
    ))
    ss.add(ParagraphStyle(
        name="AlbH2", parent=ss["Heading2"], textColor=BRAND_EMERALD,
        fontSize=14, leading=18, spaceBefore=18, spaceAfter=10,
    ))
    ss.add(ParagraphStyle(
        name="AlbBody", parent=ss["Normal"], textColor=BRAND_INK,
        fontSize=10, leading=14, spaceAfter=6,
    ))
    ss.add(ParagraphStyle(
        name="AlbLabel", parent=ss["Normal"], textColor=BRAND_MUTED,
        fontSize=8, leading=10, textTransform=None,
    ))
    return ss


def _kpi_row(kpis):
    data = [[Paragraph(f"<b>{v}</b>", ParagraphStyle(name="k", fontSize=18, textColor=BRAND_EMERALD, leading=20)) for _, v in kpis],
            [Paragraph(f"{k}", ParagraphStyle(name="l", fontSize=8, textColor=BRAND_MUTED, leading=10)) for k, _ in kpis]]
    t = Table(data, colWidths=[4.3 * cm] * len(kpis))
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BRAND_PAPER),
        ("BOX", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, BRAND_BORDER),
        ("LEFTPADDING", (0, 0), (-1, -1), 10),
        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _table(headers, rows, col_widths=None):
    """Simple styled table."""
    ss = getSampleStyleSheet()
    body_style = ParagraphStyle(name="cell", parent=ss["Normal"], fontSize=9, leading=11, textColor=BRAND_INK)
    header_style = ParagraphStyle(name="cellh", parent=ss["Normal"], fontSize=8, leading=10, textColor=colors.white, fontName="Helvetica-Bold")
    data = [[Paragraph(str(h), header_style) for h in headers]]
    for r in rows:
        data.append([Paragraph(str(c) if c is not None and c != "" else "—", body_style) for c in r])
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BRAND_EMERALD),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, BRAND_PAPER]),
        ("GRID", (0, 0), (-1, -1), 0.4, BRAND_BORDER),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return t


def build_client_report_pdf(
    *, client: dict, missions: List[dict], echeances: List[dict],
    documents: List[dict], syntheses_by_doc: dict = None,
    header_number: str = None, report_kind_label: str = None, month_key: str = None,
) -> bytes:
    """Return the PDF bytes for a client report."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=f"Rapport client — {client.get('full_name', '')}",
        author="Cabinet ALBARKA",
    )
    ss = _paragraph_styles()
    story = []
    syntheses_by_doc = syntheses_by_doc or {}

    # -------- Cover header --------
    header_bits = ["CABINET ALBARKA"]
    if report_kind_label: header_bits.append(report_kind_label.upper())
    if month_key: header_bits.append(month_key)
    if header_number: header_bits.append(f"N° {header_number}")
    story.append(Paragraph(" · ".join(header_bits), ss["AlbSubtitle"]))
    story.append(Paragraph(client.get("full_name", "—"), ss["AlbTitle"]))
    subtitle_bits = []
    if client.get("company"): subtitle_bits.append(client["company"])
    if client.get("email"): subtitle_bits.append(client["email"])
    if client.get("phone"): subtitle_bits.append(client["phone"])
    subtitle_bits.append(f"Généré le {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')}")
    story.append(Paragraph(" · ".join(subtitle_bits), ss["AlbSubtitle"]))

    # -------- KPIs --------
    kpis = [
        ("Missions", len(missions)),
        ("En cours", sum(1 for m in missions if m.get("status") in ("en_attente", "en_cours"))),
        ("Échéances", len(echeances)),
        ("En retard", sum(1 for e in echeances if e.get("status") == "en_retard")),
        ("Pièces", len(documents)),
    ]
    story.append(_kpi_row(kpis))

    # -------- Missions --------
    story.append(Paragraph("Missions du dossier", ss["AlbH2"]))
    if missions:
        rows = [
            [
                m.get("title", ""),
                MISSION_TYPE_LABELS.get(m.get("type", ""), m.get("type", "")),
                m.get("due_date") or "—",
                MISSION_STATUS_LABELS.get(m.get("status", ""), m.get("status", "")),
            ]
            for m in missions
        ]
        story.append(_table(
            ["Titre", "Type", "Échéance", "Statut"], rows,
            col_widths=[7 * cm, 4 * cm, 3 * cm, 3 * cm],
        ))
    else:
        story.append(Paragraph("<i>Aucune mission enregistrée.</i>", ss["AlbBody"]))

    # -------- Échéances fiscales --------
    story.append(Paragraph("Échéances fiscales et sociales", ss["AlbH2"]))
    if echeances:
        rows = [
            [
                e.get("title", ""),
                (e.get("type") or "").upper(),
                e.get("due_date") or "—",
                e.get("period") or "—",
                f"{int(e['amount']):,} FCFA".replace(",", " ") if e.get("amount") else "—",
                ECHEANCE_STATUS_LABELS.get(e.get("status", ""), e.get("status", "")),
            ]
            for e in echeances
        ]
        story.append(_table(
            ["Échéance", "Type", "Date", "Période", "Montant", "Statut"], rows,
            col_widths=[5.5 * cm, 2 * cm, 2.5 * cm, 2.5 * cm, 3 * cm, 2 * cm],
        ))
    else:
        story.append(Paragraph("<i>Aucune échéance enregistrée.</i>", ss["AlbBody"]))

    # -------- Pièces --------
    story.append(PageBreak())
    story.append(Paragraph("Pièces déposées et synthèses IA", ss["AlbH2"]))
    if not documents:
        story.append(Paragraph("<i>Aucune pièce déposée sur la période.</i>", ss["AlbBody"]))
    else:
        for d in documents:
            story.append(Spacer(1, 8))
            story.append(Paragraph(
                f"<b>{d.get('original_filename', '')}</b> — <font color='#64748B'>{d.get('kind', '').replace('_', ' ')} · {DOCUMENT_STATUS_LABELS.get(d.get('status', ''), d.get('status', ''))}</font>",
                ss["AlbBody"],
            ))
            syn = syntheses_by_doc.get(d["id"])
            if syn:
                if syn.get("document_type_guess"):
                    story.append(Paragraph(f"<b>Type détecté :</b> {syn['document_type_guess']}", ss["AlbBody"]))
                if syn.get("summary"):
                    story.append(Paragraph(syn["summary"], ss["AlbBody"]))
                ef = syn.get("extracted_fields") or {}
                if ef:
                    rows = [[k, str(v)] for k, v in ef.items()]
                    story.append(_table(["Champ", "Valeur"], rows, col_widths=[5 * cm, 12 * cm]))
                flags = syn.get("flags") or []
                if flags:
                    story.append(Paragraph(
                        f"<font color='#B45309'>⚠︎ {'; '.join(flags)}</font>", ss["AlbBody"],
                    ))
            else:
                story.append(Paragraph("<i>Aucune synthèse disponible.</i>", ss["AlbBody"]))

    # -------- Footer note --------
    story.append(Spacer(1, 20))
    footer = (
        "<font color='#64748B' size='8'>Document généré automatiquement par le portail ALBARKA. "
        "Confidentiel — usage interne au cabinet et au client concerné."
    )
    if header_number:
        footer += f" · Référence : {header_number}"
    footer += "</font>"
    story.append(Paragraph(footer, ss["AlbBody"]))

    doc.build(story)
    return buf.getvalue()
