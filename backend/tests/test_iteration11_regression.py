"""Regression tests — appelants `send_whatsapp` corrigés (dict contract).

Vérifie que `notify_echeance` et `notify_upload` respectent le nouveau contrat :
- Si `send_whatsapp` renvoie `ok=False`, `wa_sent` **ne s'incrémente pas**.
- Si `send_whatsapp` renvoie `ok=True`, `wa_sent` s'incrémente et
  `wa_last_id` reçoit `message_id` (pas le dict entier).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


# ---------------------------------------------------------------------
# notify_echeance
# ---------------------------------------------------------------------
class TestNotifyEcheanceWaContract:
    """Régression ligne 516-519 de albarka_notifications.py."""

    def _run_notify(self, wa_result):
        import albarka_notifications as an
        import albarka_contacts as ac

        user = {
            "id": "u_test", "email": "user@example.com", "full_name": "Test User",
            "phone": "+22670001111", "is_active": True,
            "can_receive_notifications": True,
        }
        echeance = {
            "id": "ech_test", "title": "TVA janvier", "due_date": "2026-03-01",
            "tenant_id": "u_test", "type": "tva",
        }

        with patch.object(an, "send_whatsapp",
                          new=AsyncMock(return_value=wa_result)) as m_wa, \
             patch.object(an, "send_email",
                          new=AsyncMock(return_value=None)), \
             patch.object(an, "_get_from_name",
                          new=AsyncMock(return_value="Cabinet Test")), \
             patch.object(ac, "notifiable_contacts_for",
                          new=AsyncMock(return_value=[])):
            result = asyncio.run(an.notify_echeance(user, echeance, days_left=3))
        return result, m_wa

    def test_wa_sent_stays_false_when_send_returns_ok_false(self):
        """Régression : dict truthy avec ok=False → sent_wa=False, wa_sid=None."""
        wa_result = {"ok": False, "message_id": None, "kind": "http_error",
                     "error": "Meta rejected", "outside_24h_window": None}
        result, m_wa = self._run_notify(wa_result)
        assert m_wa.await_count == 1, "send_whatsapp doit être appelé une fois"
        assert result["sent_wa"] is False, (
            f"sent_wa doit être False quand send_whatsapp renvoie ok=False. "
            f"Résultat: {result!r}"
        )
        assert result["wa_sid"] is None

    def test_wa_sent_true_and_message_id_returned_when_ok_true(self):
        """Cas succès : wa_sid = message_id (string), pas le dict entier."""
        wa_result = {"ok": True, "message_id": "wamid.ABC123", "kind": "success",
                     "error": None, "outside_24h_window": False}
        result, _m = self._run_notify(wa_result)
        assert result["sent_wa"] is True
        assert result["wa_sid"] == "wamid.ABC123", (
            "wa_sid doit être le message_id (string), pas le dict entier"
        )


# ---------------------------------------------------------------------
# notify_upload
# ---------------------------------------------------------------------
class _FakeCursor:
    def __init__(self, items): self._items = items
    async def to_list(self, _n): return list(self._items)


class _FakeUsersCollection:
    def __init__(self, staff): self._staff = staff
    def find(self, *_a, **_kw): return _FakeCursor(self._staff)


class _FakeDB:
    def __init__(self, staff):
        self.users = _FakeUsersCollection(staff)


class TestNotifyUploadWaContract:
    """Régression ligne 600-602 de albarka_notifications.py."""

    _STAFF = [
        {"id": "s1", "email": "s1@e.co", "phone": "+22670000001",
         "roles": ["comptable"], "is_active": True,
         "can_receive_notifications": True, "full_name": "Staff 1"},
        {"id": "s2", "email": "s2@e.co", "phone": "+22670000002",
         "roles": ["comptable"], "is_active": True,
         "can_receive_notifications": True, "full_name": "Staff 2"},
    ]
    _DOC = {"id": "doc1", "kind": "facture_client", "original_filename": "test.pdf"}
    _TENANT = {"id": "t1", "full_name": "Client Test", "company": "SARL X"}

    def _run_notify(self, wa_side_effect):
        import albarka_notifications as an
        import albarka_admin_settings as ams

        async def _fake_settings():
            return {"cabinet_name": "Cabinet Test",
                    "notif_upload_wa": True, "notif_upload_email": False}

        db = _FakeDB(self._STAFF)
        mock_wa = AsyncMock(side_effect=wa_side_effect) if isinstance(wa_side_effect, list) \
            else AsyncMock(return_value=wa_side_effect)

        with patch.object(an, "send_whatsapp", new=mock_wa) as m_wa, \
             patch.object(an, "send_email", new=AsyncMock(return_value=None)), \
             patch.object(ams, "get_settings_doc",
                          new=AsyncMock(side_effect=_fake_settings)):
            result = asyncio.run(
                an.notify_upload(db, document=self._DOC, tenant=self._TENANT)
            )
        return result, m_wa

    def test_wa_sent_stays_zero_when_send_returns_ok_false(self):
        """Régression : ok=False sur les 2 staff → wa_sent=0 malgré dict truthy."""
        wa_result = {"ok": False, "message_id": None, "kind": "http_error",
                     "error": "Meta 500", "outside_24h_window": None}
        result, m_wa = self._run_notify(wa_result)
        assert m_wa.await_count == 2, "send_whatsapp appelé pour chaque staff"
        assert result["wa_sent"] == 0, (
            f"wa_sent doit être 0 quand tous les envois échouent (ok=False). "
            f"Résultat: {result!r}"
        )

    def test_wa_sent_counts_only_ok_true(self):
        """Mix succès/échec : wa_sent doit refléter uniquement les ok=True."""
        results_seq = [
            {"ok": True, "message_id": "m1", "kind": "success",
             "error": None, "outside_24h_window": False},
            {"ok": False, "message_id": None, "kind": "http_error",
             "error": "boom", "outside_24h_window": None},
        ]
        result, m_wa = self._run_notify(results_seq)
        assert m_wa.await_count == 2
        assert result["wa_sent"] == 1, (
            f"wa_sent doit compter uniquement les ok=True. Résultat: {result!r}"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
