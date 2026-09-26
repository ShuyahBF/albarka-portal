"""PDF des FACTURES et FACTURES PROFORMA au format du modèle du cabinet (lot 7).

Reprend la facture Word du cabinet :
  1. bandeau « FACTURE N° … » sur fond bleu-gris (#7E97AD), date à droite ;
  2. encadré « Facturer à » (nom, BP/adresse, IFU, régime, division),
     et à droite le QR CODE de vérification ;
  3. tableau Quantité / Description / Prix unitaire / Total, avec des lignes
     de titre (sans montant) et des lignes détaillées sur plusieurs lignes ;
  4. totaux à droite : Sous-total, TVA x %, TOTAL, retenue x %, NET A PAYER,
     puis « Nous vous remercions de votre confiance. » ;
  5. « Arrêtée la présente facture à la somme de … (…) FRANCS CFA. » ;
  6. signataire (titre, signature si activée, nom en gras).

Le papier à en-tête choisi est dessiné sur chaque page (image d'en-tête en
haut, image de pied de page en bas) ; sans image, la marge haute du papier
préimprimé est laissée vide.
"""
from __future__ import annotations

import io
from typing import Optional
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import Image, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from albarka_docgen import fcfa, letterhead_image_size, montant_en_lettres

BAND = colors.HexColor("#7E97AD")      # bandeau du titre (couleur du modèle Word)
LINE = colors.HexColor("#585858")      # traits des tableaux
HEAD_BG = colors.HexColor("#E9EEF3")   # fond léger de l'en-tête du tableau
TITLES = {"facture": "FACTURE", "proforma": "FACTURE PROFORMA"}
PAGE_W, PAGE_H = A4
SIDE = 1.9 * cm                         # marges gauche / droite (modèle : 1,9 cm)


def _styles() -> dict:
    """Styles de texte (Helvetica = Arial du modèle)."""
    base = dict(fontName="Helvetica", fontSize=9.5, leading=12)
    return {
        "band": ParagraphStyle("band", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.black),
        "band_r": ParagraphStyle("band_r", fontName="Helvetica", fontSize=9, leading=11, alignment=TA_RIGHT),
        "cell": ParagraphStyle("cell", **base),
        "cell_b": ParagraphStyle("cell_b", **{**base, "fontName": "Helvetica-Bold"}),
        "cell_r": ParagraphStyle("cell_r", **base, alignment=TA_RIGHT),
        "cell_rb": ParagraphStyle("cell_rb", **{**base, "fontName": "Helvetica-Bold"}, alignment=TA_RIGHT),
        "head": ParagraphStyle("head", **{**base, "fontName": "Helvetica-Bold"}),
        "head_r": ParagraphStyle("head_r", **{**base, "fontName": "Helvetica-Bold"}, alignment=TA_RIGHT),
        "billto_t": ParagraphStyle("billto_t", fontName="Helvetica", fontSize=9, leading=11, textColor=colors.HexColor("#333333")),
        "billto": ParagraphStyle("billto", fontName="Helvetica-Bold", fontSize=10, leading=13),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10),
        "small_c": ParagraphStyle("small_c", fontName="Helvetica", fontSize=7, leading=8.5, alignment=1, textColor=colors.HexColor("#555555")),
        "words": ParagraphStyle("words", fontName="Helvetica", fontSize=8.5, leading=11.5),
        "sign": ParagraphStyle("sign", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "sign_b": ParagraphStyle("sign_b", fontName="Helvetica-Bold", fontSize=8.5, leading=11, alignment=TA_RIGHT),
        "note": ParagraphStyle("note", fontName="Helvetica", fontSize=8.5, leading=11, alignment=TA_LEFT),
    }


def _qty(v) -> str:
    """Quantité comme sur le modèle : « 01 », « 02 »… ; décimales si besoin."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    if f.is_integer():
        return f"{int(f):02d}"
    return f"{f:.2f}".rstrip("0").rstrip(".").replace(".", ",")


def _rate(v) -> str:
    """Taux « 18 » ou « 2,5 »."""
    f = float(v or 0)
    return str(int(f)) if f.is_integer() else f"{f:g}".replace(".", ",")


def bill_to_lines(invoice: dict, client: Optional[dict], kyc: Optional[dict]) -> list[str]:
    """Lignes de l'encadré « Facturer à » : texte saisi sur la facture, sinon
    fiche du client (raison sociale, adresse, IFU, RCCM)."""
    if (invoice.get("bill_to") or "").strip():
        return [ln for ln in invoice["bill_to"].splitlines() if ln.strip()][:8]
    client, kyc = client or {}, kyc or {}
    lines = [kyc.get("business_name") or client.get("company") or client.get("full_name") or "—"]
    if kyc.get("address") or client.get("address"):
        lines.append(kyc.get("address") or client.get("address"))
    if kyc.get("ifu"):
        lines.append(f"IFU : {kyc['ifu']}")
    if kyc.get("rccm"):
        lines.append(f"RCCM : {kyc['rccm']}")
    return lines


def build_invoice_model_pdf(
    *, invoice: dict, client: Optional[dict], kyc: Optional[dict], letterhead: dict,
    settings: dict, qr_bytes: Optional[bytes], signature_bytes: Optional[bytes] = None,
) -> bytes:
    """Construit le PDF (octets) d'une facture ou d'une facture proforma."""
    st = _styles()
    doc_type = invoice.get("document_type", "facture")
    content_w = PAGE_W - 2 * SIDE

    # ---- Papier à en-tête : hauteur des images -> marges du contenu
    header, footer = letterhead.get("header"), letterhead.get("footer")
    header_h = letterhead_image_size(header, PAGE_W)[1] if header else 0
    footer_h = letterhead_image_size(footer, PAGE_W)[1] if footer else 0
    top = header_h + 0.5 * cm if header else float(letterhead.get("top_margin_cm", 2.0)) * cm
    bottom = footer_h + 0.4 * cm if footer else float(letterhead.get("bottom_margin_cm", 2.0)) * cm

    def on_page(canvas, _doc):
        """Dessine l'en-tête et le pied de page sur toute la largeur de chaque page."""
        if header:
            canvas.drawImage(ImageReader(io.BytesIO(header)), 0, PAGE_H - header_h, PAGE_W, header_h, mask="auto")
        if footer:
            canvas.drawImage(ImageReader(io.BytesIO(footer)), 0, 0, PAGE_W, footer_h, mask="auto")

    buf = io.BytesIO()
    pdf = SimpleDocTemplate(buf, pagesize=A4, leftMargin=SIDE, rightMargin=SIDE, topMargin=top, bottomMargin=bottom,
                            title=f"{TITLES.get(doc_type, 'FACTURE')} {invoice.get('number', '')}")
    story = []

    # ---- 1. Bandeau du titre
    date_txt = (invoice.get("issue_date") or invoice.get("created_at") or "")[:10]
    date_fr = "/".join(reversed(date_txt.split("-"))) if date_txt else ""
    band = Table([[Paragraph(f"{TITLES.get(doc_type, 'FACTURE')} N° {escape(str(invoice.get('number', '')))}", st["band"]),
                   Paragraph(f"Date : {date_fr}", st["band_r"])]],
                 colWidths=[content_w * 0.68, content_w * 0.32])
    band.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), BAND), ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                              ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                              ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8)]))
    story += [band, Spacer(1, 0.45 * cm)]

    # ---- 2. « Facturer à » + QR code de vérification
    lines = bill_to_lines(invoice, client, kyc)
    bill = Table([[Paragraph("Facturer à", st["billto_t"])],
                  [Paragraph("<br/>".join(escape(ln) for ln in lines), st["billto"])]],
                 colWidths=[8.6 * cm])
    bill.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.8, LINE), ("LINEBELOW", (0, 0), (-1, 0), 0.5, LINE),
                              ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    right = []
    if qr_bytes:
        right = [Image(io.BytesIO(qr_bytes), width=2.6 * cm, height=2.6 * cm),
                 Paragraph("Scannez pour vérifier<br/>l'authenticité", st["small_c"])]
    top_row = Table([[bill, "", right]], colWidths=[8.8 * cm, content_w - 8.8 * cm - 3.2 * cm, 3.2 * cm])
    top_row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (2, 0), (2, 0), "CENTER"),
                                 ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    story += [top_row, Spacer(1, 0.35 * cm)]
    if invoice.get("title"):
        story += [Paragraph(f"<b>Objet :</b> {escape(invoice['title'])}", st["note"]), Spacer(1, 0.25 * cm)]

    # ---- 3. Lignes : Quantité / Description / Prix unitaire / Total
    widths = [2.1 * cm, content_w - 2.1 * cm - 3.0 * cm - 3.2 * cm, 3.0 * cm, 3.2 * cm]
    rows = [[Paragraph("Quantité", st["head"]), Paragraph("Description", st["head"]),
             Paragraph("Prix unitaire", st["head_r"]), Paragraph("Total", st["head_r"])]]
    section_rows = []
    for it in invoice.get("items") or []:
        label = escape(it.get("label") or "")
        detail = "<br/>".join(escape(ln) for ln in (it.get("detail") or "").splitlines() if ln.strip())
        if it.get("kind") == "section":
            # Ligne de titre : description seule, en gras (quantité facultative)
            qty = _qty(it.get("quantity")) if it.get("quantity") else ""
            rows.append([Paragraph(qty, st["cell"]), Paragraph(f"<b>{label}</b>" + (f"<br/>{detail}" if detail else ""), st["cell"]), "", ""])
            section_rows.append(len(rows) - 1)
            continue
        q, pu = float(it.get("quantity") or 0), float(it.get("unit_price") or 0)
        desc = label + (f"<br/><font size='8.5'>{detail}</font>" if detail else "")
        rows.append([Paragraph(_qty(q), st["cell"]), Paragraph(desc, st["cell"]),
                     Paragraph(fcfa(pu), st["cell_r"]), Paragraph(fcfa(q * pu), st["cell_r"])])
    while len(rows) < 5:  # lignes vides pour garder l'aspect du modèle
        rows.append(["", "", "", ""])
    items = Table(rows, colWidths=widths, repeatRows=1)
    items.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 0.8, LINE), ("INNERGRID", (0, 0), (-1, -1), 0.4, LINE),
        ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG), ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [items, Spacer(1, 0.3 * cm)]

    # ---- 4. Totaux (à droite)
    subtotal, tax, total = float(invoice.get("subtotal") or 0), float(invoice.get("tax") or 0), float(invoice.get("total") or 0)
    wh_rate, wh = float(invoice.get("withholding_rate") or 0), float(invoice.get("withholding") or 0)
    net = float(invoice.get("net_to_pay", total))
    tva_rate = invoice.get("tva_rate")
    if tva_rate is None:
        rates = {float(i.get("tax_rate") or 0) for i in invoice.get("items") or [] if i.get("kind") != "section"}
        tva_rate = rates.pop() if len(rates) == 1 else None
    tva_label = f"TVA {_rate(tva_rate)}%" if tva_rate is not None else "TVA"
    trows = [[Paragraph("Sous-total", st["cell_b"]), Paragraph(fcfa(subtotal), st["cell_r"])],
             [Paragraph(tva_label, st["cell_b"]), Paragraph(fcfa(tax), st["cell_r"])],
             [Paragraph("TOTAL", st["cell_b"]), Paragraph(fcfa(total), st["cell_rb"])]]
    if wh_rate > 0:
        label = (invoice.get("withholding_label") or "retenue").strip()
        trows += [[Paragraph(f"{escape(label)} {_rate(wh_rate)}%", st["cell_b"]), Paragraph(fcfa(wh), st["cell_r"])],
                  [Paragraph("NET A PAYER", st["cell_b"]), Paragraph(fcfa(net), st["cell_rb"])]]
    paid = float(invoice.get("paid_amount") or 0)
    if doc_type == "facture" and 0 < paid < net - 0.5:
        trows += [[Paragraph("Déjà réglé", st["cell"]), Paragraph(fcfa(paid), st["cell_r"])],
                  [Paragraph("Reste à payer", st["cell_b"]), Paragraph(fcfa(net - paid), st["cell_rb"])]]
    thanks = (settings.get("thanks_text") or "").strip()
    if thanks:
        trows.append([Paragraph(escape(thanks), st["small"]), ""])
    totals = Table(trows, colWidths=[4.4 * cm, 3.6 * cm], hAlign="RIGHT")
    tstyle = [("BOX", (0, 0), (-1, len(trows) - (2 if thanks else 1)), 0.8, LINE),
              ("INNERGRID", (0, 0), (-1, len(trows) - (2 if thanks else 1)), 0.4, LINE),
              ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    if thanks:
        tstyle.append(("SPAN", (0, len(trows) - 1), (1, len(trows) - 1)))
    totals.setStyle(TableStyle(tstyle))
    story += [totals, Spacer(1, 0.45 * cm)]

    # ---- 5. Somme en toutes lettres
    what = "facture proforma" if doc_type == "proforma" else "facture"
    final = net if wh_rate > 0 else total
    story.append(Paragraph(
        f"Arrêtée la présente {what} à la somme de {montant_en_lettres(final)} "
        f"<font size='9.5'>({fcfa(final)})</font> FRANCS CFA.", st["words"]))
    if invoice.get("due_date"):
        due = "/".join(reversed(str(invoice["due_date"])[:10].split("-")))
        story.append(Paragraph(f"Échéance de paiement : {due}", st["words"]))
    if invoice.get("notes"):
        story.append(Paragraph(f"<i>{escape(invoice['notes'])}</i>", st["words"]))
    story.append(Spacer(1, 0.7 * cm))

    # ---- 6. Signataire (à droite)
    sign = [Paragraph(escape(settings.get("signatory_title") or "Le Directeur Général"), st["sign"])]
    if signature_bytes:
        w, h = letterhead_image_size(signature_bytes, 3.6 * cm)
        img = Image(io.BytesIO(signature_bytes), width=w, height=min(h, 2.4 * cm))
        img.hAlign = "RIGHT"
        sign.append(img)
    else:
        sign.append(Spacer(1, 1.2 * cm))
    if settings.get("signatory_name"):
        sign.append(Paragraph(escape(settings["signatory_name"]), st["sign_b"]))
    story.append(KeepTogether(sign))

    pdf.build(story, onFirstPage=on_page, onLaterPages=on_page)
    return buf.getvalue()
