"""Filigrane + QR code apposés sur les documents (image ou PDF) juste avant
un envoi WhatsApp — jamais sur le fichier original stocké. Le point d'entrée
`stamp_for_whatsapp` est appelé depuis albarka_notifications._wa_upload_media,
le choke point unique par lequel passent déjà tous les envois de documents
WhatsApp (pièces client comme rapports signés) : rien à changer côté
appelants, la fonction reçoit toujours les octets déjà lus depuis le storage
et ne les réécrit jamais dessus.

Logique image reprise et adaptée de la référence (repo Emergent,
whatsapp_helpers.py:_wa_apply_image_watermark_qr) ; logique PDF réutilise
PyMuPDF (fitz), déjà une dépendance de fait du cabinet via
albarka_signing.py:_apply_visible_stamp (même bibliothèque, même style de
recours au fitz.Rect/insert_textbox/insert_image).
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("albarka.wa_stamp")

# Bundlé dans le repo (plutôt que de dépendre d'un paquet de polices système
# qui peut manquer sur un environnement de build minimal) — même principe
# que backend/assets/fonts pour les autres besoins de rendu texte-sur-image.
_FONT_PATH = Path(__file__).parent / "assets" / "fonts" / "DejaVuSans-Bold.ttf"

STAMPABLE_IMAGE_PREFIX = "image/"
STAMPABLE_PDF_MIME = "application/pdf"


def _render_watermark_text(template: str, cabinet_name: str) -> str:
    now = datetime.now(timezone.utc)
    try:
        return (template or "").format(cabinet=cabinet_name, date=now.strftime("%d/%m/%Y"))[:120]
    except (KeyError, IndexError):
        # Gabarit mal formé (ex. accolade orpheline) — on retombe sur le texte
        # brut plutôt que de faire échouer tout l'envoi WhatsApp pour ça.
        return template[:120]


def _stamp_image_bytes(data: bytes, watermark_text: Optional[str], qr_payload: Optional[str]) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    img = Image.open(io.BytesIO(data)).convert("RGBA")
    W, H = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    if watermark_text:
        font_size = max(14, min(36, int(H * 0.022)))
        try:
            font = ImageFont.truetype(str(_FONT_PATH), font_size)
        except Exception:
            font = ImageFont.load_default()
        try:
            bbox = draw.textbbox((0, 0), watermark_text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        except Exception:
            tw, th = font_size * len(watermark_text) // 2, font_size
        pad = max(6, font_size // 3)
        x = W - tw - pad * 2 - 12
        y = H - th - pad * 2 - 12
        draw.rounded_rectangle((x, y, x + tw + pad * 2, y + th + pad * 2), radius=pad, fill=(0, 0, 0, 140))
        draw.text((x + pad, y + pad - 2), watermark_text, font=font, fill=(255, 255, 255, 235))

    if qr_payload:
        import qrcode
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
        qr.add_data(qr_payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGBA")
        qr_size = max(72, min(220, int(W * 0.12)))
        qr_img = qr_img.resize((qr_size, qr_size), Image.NEAREST)
        qx, qy = 16, 16
        draw.rounded_rectangle((qx - 6, qy - 6, qx + qr_size + 6, qy + qr_size + 6), radius=8, fill=(255, 255, 255, 235))
        overlay.alpha_composite(qr_img, (qx, qy))

    out = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    out.save(buf, format="JPEG", quality=88, optimize=True)
    return buf.getvalue()


def _stamp_pdf_bytes(data: bytes, watermark_text: Optional[str], qr_payload: Optional[str]) -> bytes:
    import fitz  # PyMuPDF

    qr_png: Optional[bytes] = None
    if qr_payload:
        import qrcode
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=4, border=1)
        qr.add_data(qr_payload)
        qr.make(fit=True)
        qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
        qr_buf = io.BytesIO()
        qr_img.save(qr_buf, format="PNG")
        qr_png = qr_buf.getvalue()

    doc = fitz.open(stream=data, filetype="pdf")
    try:
        for page in doc:
            w, h = page.rect.width, page.rect.height
            if watermark_text:
                box_w, box_h = 200, 22
                # Bas-droite : hors du bloc d'en-tête habituel (logo/adresse en
                # haut) et du bloc de signature (bas-gauche, voir albarka_signing.py).
                x0, y0 = w - box_w - 16, h - box_h - 16
                rect = fitz.Rect(x0, y0, x0 + box_w, y0 + box_h)
                page.draw_rect(rect, color=None, fill=(0, 0, 0), fill_opacity=0.55, width=0)
                # Police bundlée (DejaVu, Unicode complet) plutôt que la police de
                # base "helv" de PyMuPDF — évite un rendu erroné des caractères
                # hors ASCII de base (ex. le tiret cadratin "—" du gabarit par défaut).
                page.insert_textbox(
                    fitz.Rect(x0 + 6, y0 + 4, x0 + box_w - 6, y0 + box_h - 4),
                    watermark_text, fontsize=8, fontname="albarka-wm", fontfile=str(_FONT_PATH),
                    color=(1, 1, 1), align=1,
                )
            if qr_png:
                # Haut-droite : hors de la zone habituelle d'un logo/en-tête
                # (généralement haut-gauche) pour éviter tout chevauchement.
                qr_size = 60
                img_rect = fitz.Rect(w - qr_size - 16, 16, w - 16, 16 + qr_size)
                page.insert_image(img_rect, stream=qr_png)
        buf = io.BytesIO()
        doc.save(buf, deflate=True, garbage=3)
        return buf.getvalue()
    finally:
        doc.close()


async def stamp_for_whatsapp(data: bytes, content_type: str) -> bytes:
    """Renvoie une COPIE tamponnée des octets si filigrane/QR est activé et
    le type de fichier est supporté (image ou PDF) — sinon renvoie `data`
    inchangé. N'écrit jamais sur le storage : l'appelant reste responsable
    de ce qu'il fait du résultat (ici, l'upload à l'API Meta uniquement)."""
    from albarka_admin_settings import get_settings_doc
    settings = await get_settings_doc()
    wm_on = bool(settings.get("wa_watermark_enabled"))
    qr_on = bool(settings.get("wa_qr_enabled"))
    if not wm_on and not qr_on:
        return data

    watermark_text = (
        _render_watermark_text(settings.get("wa_watermark_text") or "", settings.get("cabinet_name") or "Cabinet ALBARKA")
        if wm_on else None
    )
    qr_payload = (settings.get("wa_qr_content") or "").strip() if qr_on else None
    if not watermark_text and not qr_payload:
        return data

    try:
        if content_type.startswith(STAMPABLE_IMAGE_PREFIX):
            return _stamp_image_bytes(data, watermark_text, qr_payload)
        if content_type == STAMPABLE_PDF_MIME:
            return _stamp_pdf_bytes(data, watermark_text, qr_payload)
    except Exception:  # noqa: BLE001
        logger.exception("Filigrane/QR WhatsApp — échec du tamponnage, envoi du document original")
    return data
