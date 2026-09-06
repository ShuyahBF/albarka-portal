"""Filigrane + QR sur les documents envoyés par WhatsApp (albarka_wa_stamp.py).

Teste directement les fonctions pures de tamponnage (aucun appel réseau,
aucun envoi WhatsApp réel) : activation indépendante du filigrane et du QR,
et non-régression sur le fait que ces fonctions ne touchent jamais un
fichier sur disque — elles ne reçoivent et ne renvoient que des octets."""
import io

import fitz
import pytest
from PIL import Image

from albarka_wa_stamp import _render_watermark_text, _stamp_image_bytes, _stamp_pdf_bytes, stamp_for_whatsapp


def _sample_image_bytes() -> bytes:
    img = Image.new("RGB", (400, 300), (200, 100, 50))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def _sample_pdf_bytes() -> bytes:
    doc = fitz.open()
    doc.new_page(width=595, height=842)
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


class TestWatermarkTemplate:
    def test_variables_substituted(self):
        text = _render_watermark_text("{cabinet} — {date}", "Cabinet ALBARKA")
        assert "Cabinet ALBARKA" in text
        assert "—" in text

    def test_malformed_template_falls_back_gracefully(self):
        # Ne doit jamais lever — un gabarit mal formé retombe sur le texte brut.
        text = _render_watermark_text("{oops}", "Cabinet ALBARKA")
        assert text == "{oops}"


class TestImageStamping:
    def test_watermark_only(self):
        original = _sample_image_bytes()
        out = _stamp_image_bytes(original, "Cabinet ALBARKA — 06/09/2026", None)
        assert out != original

    def test_qr_only(self):
        original = _sample_image_bytes()
        out = _stamp_image_bytes(original, None, "https://albarka-bf.com")
        assert out != original

    def test_both_independent_from_watermark_only(self):
        original = _sample_image_bytes()
        wm_only = _stamp_image_bytes(original, "Cabinet ALBARKA", None)
        both = _stamp_image_bytes(original, "Cabinet ALBARKA", "https://albarka-bf.com")
        # Le QR ajoute des pixels en plus du filigrane seul — les deux rendus diffèrent.
        assert both != wm_only

    @pytest.mark.asyncio
    async def test_disabled_in_settings_returns_unchanged_bytes(self, monkeypatch):
        # Le contrat public est stamp_for_whatsapp (le seul point d'entrée
        # réellement appelé par _wa_upload_media) : quand filigrane ET QR sont
        # désactivés dans les réglages, les octets ne doivent pas être touchés
        # — _stamp_image_bytes elle-même réencode toujours en JPEG (perte
        # mineure attendue), mais ce chemin n'est jamais emprunté en pratique
        # car stamp_for_whatsapp court-circuite avant de l'appeler.
        import albarka_wa_stamp

        async def fake_settings():
            return {"wa_watermark_enabled": False, "wa_qr_enabled": False}

        monkeypatch.setattr(
            "albarka_admin_settings.get_settings_doc", fake_settings,
        )
        original = _sample_image_bytes()
        out = await stamp_for_whatsapp(original, "image/jpeg")
        assert out == original


class TestPdfStamping:
    def test_watermark_only(self):
        original = _sample_pdf_bytes()
        out = _stamp_pdf_bytes(original, "Cabinet ALBARKA — 06/09/2026", None)
        assert out != original

    def test_qr_only(self):
        original = _sample_pdf_bytes()
        out = _stamp_pdf_bytes(original, None, "https://albarka-bf.com")
        assert out != original

    def test_unicode_watermark_text_renders_without_error(self):
        # Régression : la police de base PyMuPDF "helv" rendait "—" en "?" —
        # doit maintenant utiliser la police bundlée (Unicode complet).
        original = _sample_pdf_bytes()
        out = _stamp_pdf_bytes(original, "Cabinet ALBARKA — 06/09/2026 — éàç", None)
        doc = fitz.open(stream=out, filetype="pdf")
        try:
            page_text = doc[0].get_text()
        finally:
            doc.close()
        assert "—" in page_text
        assert "é" in page_text
