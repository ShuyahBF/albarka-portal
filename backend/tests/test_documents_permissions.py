"""Pièces client (/admin/documents) — restriction téléchargement/suppression
et nouveaux endpoints d'envoi (email, WhatsApp).

Tests unitaires, sans serveur ni base de données réels : les dépendances
(_get_owned_document, get_object, send_email, send_whatsapp_document, …)
sont mockées, dans le même esprit que test_iteration11_regression.py.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch
from motor.motor_asyncio import AsyncIOMotorCollection

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import albarka_documents as ad  # noqa: E402


def _user(roles):
    return {"id": "u1", "email": "u1@example.com", "full_name": "Test User", "roles": roles}


DOC = {
    "id": "doc1", "tenant_id": "client1", "storage_path": "path/doc1.pdf",
    "original_filename": "facture.pdf", "content_type": "application/pdf",
}


# ---------------------------------------------------------------------
# _require_download_access / _require_delete_access — la restriction
# unique d'avant ("SENSITIVE_DOC_ROLES") a été scindée en deux règles
# distinctes : secretariat peut désormais télécharger mais jamais
# supprimer, et "telechargement" reste cumulable pour le téléchargement
# seul (jamais pour la suppression). Voir DOCS_PRIVILEGED_ROLES /
# DOCS_DELETE_ROLES dans albarka_models.py.
# ---------------------------------------------------------------------
class TestRequireDownloadAccess:
    def test_client_always_allowed(self):
        ad._require_download_access(_user(["client"]))  # ne doit pas lever

    @pytest.mark.parametrize(
        "role", ["superviseur", "direction", "dg", "administrateur", "secretariat", "telechargement"],
    )
    def test_staff_with_allowed_role(self, role):
        ad._require_download_access(_user([role]))  # ne doit pas lever

    @pytest.mark.parametrize("role", ["comptable", "communication", "aide_comptable", "rh", "fiscaliste"])
    def test_staff_without_allowed_role_forbidden(self, role):
        with pytest.raises(HTTPException) as exc:
            ad._require_download_access(_user([role]))
        assert exc.value.status_code == 403

    def test_cumulable_role_grants_access_regardless_of_main_profile(self):
        """Le rôle 'telechargement' cumulé à un profil métier quelconque suffit."""
        ad._require_download_access(_user(["comptable", "telechargement"]))


class TestRequireDeleteAccess:
    def test_client_always_allowed(self):
        ad._require_delete_access(_user(["client"]))  # ne doit pas lever

    @pytest.mark.parametrize("role", ["superviseur", "direction", "dg", "administrateur"])
    def test_staff_with_allowed_role(self, role):
        ad._require_delete_access(_user([role]))  # ne doit pas lever

    @pytest.mark.parametrize(
        "role", ["comptable", "communication", "secretariat", "aide_comptable", "telechargement"],
    )
    def test_staff_without_allowed_role_forbidden(self, role):
        """secretariat et telechargement donnent accès au téléchargement mais
        jamais à la suppression, plus sensible — voir DOCS_DELETE_ROLES."""
        with pytest.raises(HTTPException) as exc:
            ad._require_delete_access(_user([role]))
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------
# Endpoints de téléchargement — 403 pour un rôle non autorisé,
# accès conservé pour le client sur ses propres pièces
# ---------------------------------------------------------------------
class TestDownloadEndpointsRoleGate:
    def _patched(self, doc=None):
        return patch.object(ad, "_get_owned_document", new=AsyncMock(return_value=doc or dict(DOC)))

    def test_download_document_403_for_unauthorized_staff(self):
        with self._patched():
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.download_document("doc1", _user(["comptable"])))
        assert exc.value.status_code == 403

    def test_download_url_403_for_unauthorized_staff(self):
        with self._patched():
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.get_download_url("doc1", _user(["communication"])))
        assert exc.value.status_code == 403

    def test_download_document_ok_for_authorized_staff(self):
        with self._patched(), \
             patch.object(ad, "get_object", new=AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))):
            resp = asyncio.run(ad.download_document("doc1", _user(["direction"])))
        assert resp.status_code == 200 or resp.body  # Response construit sans lever

    def test_download_url_ok_for_authorized_staff_with_telechargement_role(self):
        with self._patched(), \
             patch.object(ad, "presigned_url", new=AsyncMock(return_value="https://r2/signed-url")):
            result = asyncio.run(ad.get_download_url("doc1", _user(["comptable", "telechargement"])))
        assert result["url"] == "https://r2/signed-url"

    def test_client_keeps_access_to_own_document(self):
        """Le client ne passe jamais par _require_download_access — son
        accès est déjà garanti par la vérification d'ownership existante."""
        with self._patched(), \
             patch.object(ad, "presigned_url", new=AsyncMock(return_value="https://r2/signed-url")):
            result = asyncio.run(ad.get_download_url("doc1", _user(["client"])))
        assert result["url"] == "https://r2/signed-url"

    def test_delete_document_403_for_unauthorized_staff(self):
        with self._patched():
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.delete_document("doc1", _user(["rh"])))
        assert exc.value.status_code == 403


# ---------------------------------------------------------------------
# Nouveaux endpoints d'envoi (email / WhatsApp)
# ---------------------------------------------------------------------
OWNER = {"id": "client1", "email": "client@example.com", "phone": "+22670000000",
         "full_name": "Client Test", "company": "SARL Test"}


class TestSendDocumentEmail:
    def _run(self, payload_to=None, send_email_result="msg-123"):
        with patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), dict(OWNER)))), \
             patch.object(ad, "get_object", new=AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))), \
             patch.object(AsyncIOMotorCollection, "update_one", new=AsyncMock()), \
             patch.object(ad, "send_email", new=AsyncMock(return_value=send_email_result)) as m_send:
            payload = ad.SendDocumentEmailPayload(to=payload_to)
            result = asyncio.run(ad.send_document_email("doc1", payload, _user(["administrateur"])))
        return result, m_send

    def test_sends_to_owner_email_by_default(self):
        result, m_send = self._run()
        assert result["ok"] is True
        assert result["to"] == "client@example.com"
        m_send.assert_awaited_once()

    def test_raises_502_when_send_fails(self):
        with patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), dict(OWNER)))), \
             patch.object(ad, "get_object", new=AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))), \
             patch.object(ad, "send_email", new=AsyncMock(return_value=None)):
            payload = ad.SendDocumentEmailPayload()
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.send_document_email("doc1", payload, _user(["administrateur"])))
        assert exc.value.status_code == 502

    def test_raises_400_when_no_email_available(self):
        owner_no_email = {**OWNER, "email": None}
        with patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), owner_no_email))):
            payload = ad.SendDocumentEmailPayload()
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.send_document_email("doc1", payload, _user(["administrateur"])))
        assert exc.value.status_code == 400


class TestSendDocumentWhatsapp:
    def _settings(self, wa_enabled=True):
        return AsyncMock(return_value={"wa_enabled": wa_enabled})

    def test_sends_pdf_as_document_type(self):
        import albarka_admin_settings as ams
        import albarka_notifications as an
        with patch.object(ams, "get_settings_doc", new=self._settings()), \
             patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), dict(OWNER)))), \
             patch.object(ad, "get_object", new=AsyncMock(return_value=(b"%PDF-1.4", "application/pdf"))), \
             patch.object(AsyncIOMotorCollection, "update_one", new=AsyncMock()), \
             patch.object(an, "_wa_upload_media", new=AsyncMock(return_value="media-1")) as m_upload, \
             patch.object(an, "send_whatsapp_document",
                           new=AsyncMock(return_value={"ok": True, "message_id": "wamid.1"})) as m_doc, \
             patch.object(an, "send_whatsapp_image", new=AsyncMock()) as m_img:
            payload = ad.SendDocumentWhatsAppPayload()
            result = asyncio.run(ad.send_document_whatsapp("doc1", payload, _user(["superviseur"])))
        assert result["ok"] is True
        m_doc.assert_awaited_once()
        m_img.assert_not_called()
        # Le vrai content-type du document doit être transmis à l'upload média
        # (pas le "application/pdf" en dur de l'ancienne signature).
        assert m_upload.call_args.kwargs["content_type"] == "application/pdf"

    def test_sends_image_as_image_type_not_document(self):
        """Régression : Meta rejette une image envoyée via le type 'document'."""
        import albarka_admin_settings as ams
        import albarka_notifications as an
        image_doc = {**DOC, "content_type": "image/jpeg", "original_filename": "recu.jpg"}
        with patch.object(ams, "get_settings_doc", new=self._settings()), \
             patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(image_doc, dict(OWNER)))), \
             patch.object(ad, "get_object", new=AsyncMock(return_value=(b"\xff\xd8\xff", "image/jpeg"))), \
             patch.object(AsyncIOMotorCollection, "update_one", new=AsyncMock()), \
             patch.object(an, "_wa_upload_media", new=AsyncMock(return_value="media-2")) as m_upload, \
             patch.object(an, "send_whatsapp_document", new=AsyncMock()) as m_doc, \
             patch.object(an, "send_whatsapp_image",
                           new=AsyncMock(return_value={"ok": True, "message_id": "wamid.2"})) as m_img:
            payload = ad.SendDocumentWhatsAppPayload()
            result = asyncio.run(ad.send_document_whatsapp("doc1", payload, _user(["superviseur"])))
        assert result["ok"] is True
        m_img.assert_awaited_once()
        m_doc.assert_not_called()
        assert m_upload.call_args.kwargs["content_type"] == "image/jpeg"

    def test_raises_400_when_wa_disabled(self):
        import albarka_admin_settings as ams
        with patch.object(ams, "get_settings_doc", new=self._settings(wa_enabled=False)), \
             patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), dict(OWNER)))):
            payload = ad.SendDocumentWhatsAppPayload()
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.send_document_whatsapp("doc1", payload, _user(["superviseur"])))
        assert exc.value.status_code == 400

    def test_raises_400_when_no_valid_phone(self):
        owner_no_phone = {**OWNER, "phone": None}
        with patch.object(ad, "_fetch_document_and_owner",
                           new=AsyncMock(return_value=(dict(DOC), owner_no_phone))):
            payload = ad.SendDocumentWhatsAppPayload()
            with pytest.raises(HTTPException) as exc:
                asyncio.run(ad.send_document_whatsapp("doc1", payload, _user(["superviseur"])))
        assert exc.value.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
