"""Tests unitaires Partie 2 — fiabilité WhatsApp.

Portée : découpage message long, retour structuré send_whatsapp,
déduplication webhook. Aucun appel réseau réel — les tests HTTP
utilisent respx pour mocker l'API Meta.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from albarka_notifications import (
    _wa_split_long_text, _wa_window_open, send_whatsapp,
)


# ---------------------------------------------------------------------
# Point 2.A — _wa_split_long_text
# ---------------------------------------------------------------------
class TestSplitLongText:
    def test_short_stays_single(self):
        out = _wa_split_long_text("Salut")
        assert out == ["Salut"]

    def test_exactly_max_len_stays_single(self):
        text = "a" * 4096
        out = _wa_split_long_text(text)
        assert len(out) == 1
        assert out[0] == text

    def test_over_max_len_splits(self):
        text = ("word " * 1000).strip()  # ~4999 chars
        out = _wa_split_long_text(text)
        assert len(out) >= 2
        assert all(len(seg) <= 4096 for seg in out)
        # Reassembly (whitespace-normalized) doit reformer le texte
        reassembled = " ".join(out)
        assert reassembled.replace("  ", " ").strip() == text

    def test_9000_chars_gives_three_segments(self):
        text = "mot" + (" ab" * 3000)  # ~9003 chars
        out = _wa_split_long_text(text)
        assert len(out) == 3, f"expected 3 segments, got {len(out)}: sizes={[len(s) for s in out]}"
        for seg in out:
            assert len(seg) <= 4096

    def test_no_space_falls_back_to_hard_cut(self):
        text = "a" * 5000
        out = _wa_split_long_text(text)
        assert len(out) == 2
        assert len(out[0]) == 4096
        assert len(out[1]) == 904

    def test_empty(self):
        assert _wa_split_long_text("") == [""]


# ---------------------------------------------------------------------
# Point 2.B — _wa_window_open
# ---------------------------------------------------------------------
class TestWindowOpen:
    def test_none_when_no_inbound(self):
        assert _wa_window_open(None) is None

    def test_open_when_recent(self):
        from datetime import datetime, timezone
        recent = datetime.now(timezone.utc).isoformat()
        assert _wa_window_open(recent) is True

    def test_closed_when_old(self):
        assert _wa_window_open("2020-01-01T00:00:00+00:00") is False

    def test_invalid_returns_none(self):
        assert _wa_window_open("not-a-date") is None


# ---------------------------------------------------------------------
# Point 2.C — retour structuré send_whatsapp
# ---------------------------------------------------------------------
class TestSendWhatsappStructured:
    @pytest.mark.asyncio
    async def test_not_configured_returns_structured(self, monkeypatch):
        # Aucun accès token dans les settings → not_configured
        from albarka_notifications import _get_wa_config
        async def _no_cfg(): return None
        monkeypatch.setattr("albarka_notifications._get_wa_config", _no_cfg)
        result = await send_whatsapp(to_phone="+22670000000", message="test")
        assert result["ok"] is False
        assert result["kind"] == "not_configured"
        assert result["message_id"] is None
        assert "outside_24h_window" in result

    @pytest.mark.asyncio
    async def test_invalid_phone_returns_structured(self, monkeypatch):
        async def _cfg():
            return {"access_token": "x", "phone_number_id": "y", "graph_version": "v19.0"}
        monkeypatch.setattr("albarka_notifications._get_wa_config", _cfg)
        result = await send_whatsapp(to_phone="70000000", message="test")
        assert result["ok"] is False
        assert result["kind"] == "invalid_phone"

    @pytest.mark.asyncio
    async def test_silent_drop_detected(self, monkeypatch):
        # 2xx mais pas de message_id → silent_drop
        async def _cfg():
            return {"access_token": "x", "phone_number_id": "y", "graph_version": "v19.0"}
        async def _no_inbound(_): return None
        monkeypatch.setattr("albarka_notifications._get_wa_config", _cfg)
        monkeypatch.setattr("albarka_notifications._wa_last_inbound_iso", _no_inbound)

        class FakeResp:
            status_code = 200
            def json(self):
                return {"messaging_product": "whatsapp", "contacts": [], "messages": []}
            @property
            def text(self): return "{}"

        class FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        result = await send_whatsapp(to_phone="+22670000000", message="test")
        assert result["ok"] is False
        assert result["kind"] == "silent_drop"

    @pytest.mark.asyncio
    async def test_success_returns_message_id(self, monkeypatch):
        async def _cfg():
            return {"access_token": "x", "phone_number_id": "y", "graph_version": "v19.0"}
        async def _no_inbound(_): return None
        monkeypatch.setattr("albarka_notifications._get_wa_config", _cfg)
        monkeypatch.setattr("albarka_notifications._wa_last_inbound_iso", _no_inbound)

        class FakeResp:
            status_code = 200
            def json(self):
                return {"messages": [{"id": "wamid.ABC123"}]}
            @property
            def text(self): return "{}"

        class FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw): return FakeResp()

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        result = await send_whatsapp(to_phone="+22670000000", message="short")
        assert result["ok"] is True
        assert result["kind"] == "success"
        assert result["message_id"] == "wamid.ABC123"
        assert result["message_ids"] == ["wamid.ABC123"]

    @pytest.mark.asyncio
    async def test_long_message_splits_and_sends_multiple(self, monkeypatch):
        async def _cfg():
            return {"access_token": "x", "phone_number_id": "y", "graph_version": "v19.0"}
        async def _no_inbound(_): return None
        monkeypatch.setattr("albarka_notifications._get_wa_config", _cfg)
        monkeypatch.setattr("albarka_notifications._wa_last_inbound_iso", _no_inbound)

        counter = {"n": 0}

        class FakeResp:
            status_code = 200
            def __init__(self, i): self.i = i
            def json(self): return {"messages": [{"id": f"wamid.SEG{self.i}"}]}
            @property
            def text(self): return "{}"

        class FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, *a, **kw):
                counter["n"] += 1
                return FakeResp(counter["n"])

        monkeypatch.setattr("httpx.AsyncClient", FakeClient)
        # 9000 caractères → 3 segments
        long_msg = "mot" + (" ab" * 3000)
        result = await send_whatsapp(to_phone="+22670000000", message=long_msg)
        assert result["ok"] is True
        assert counter["n"] == 3
        assert len(result["message_ids"]) == 3


# ---------------------------------------------------------------------
# Point 2.D — Déduplication webhook
# ---------------------------------------------------------------------
class TestWebhookDedup:
    @pytest.mark.asyncio
    async def test_same_wa_message_id_inserted_once(self, monkeypatch):
        """Simule 2 réceptions du même payload → un seul insert."""
        from albarka_wa_inbox import receive_webhook
        from fastapi import Request

        # État partagé en mémoire
        store: list[dict] = []

        class FakeDb:
            class wa_messages:
                @staticmethod
                async def find_one(query, projection=None):
                    for doc in store:
                        if doc.get("wa_message_id") == query.get("wa_message_id"):
                            return doc
                    return None

                @staticmethod
                async def insert_one(doc):
                    store.append(dict(doc))
            class contacts:
                @staticmethod
                async def find_one(*a, **kw): return None
            class users:
                @staticmethod
                async def find_one(*a, **kw): return None
            class wa_conversation_labels:
                @staticmethod
                async def find_one(*a, **kw): return None
                @staticmethod
                async def update_one(*a, **kw): return None

        monkeypatch.setattr("albarka_wa_inbox.db", FakeDb)
        async def _no_settings(): return {"wa_voice_transcribe_enabled": False}
        monkeypatch.setattr("albarka_wa_inbox.get_settings_doc", _no_settings)

        payload = {
            "entry": [{
                "changes": [{
                    "value": {
                        "contacts": [{"profile": {"name": "Client Test"}}],
                        "messages": [{
                            "id": "wamid.UNIQUE_ABC",
                            "from": "22670000000",
                            "type": "text",
                            "text": {"body": "Bonjour, question facture"},
                        }],
                    }
                }]
            }]
        }

        class FakeRequest:
            async def json(self): return payload

        # Premier appel : insertion
        r1 = await receive_webhook(FakeRequest())
        assert r1["inserted"] == 1
        assert len(store) == 1
        # Deuxième appel avec le MÊME payload : doit être dédupliqué
        r2 = await receive_webhook(FakeRequest())
        assert r2["inserted"] == 0
        assert len(store) == 1
        assert store[0]["body"] == "Bonjour, question facture"
        assert store[0]["phone"] == "+22670000000"
        assert store[0]["direction"] == "inbound"

    @pytest.mark.asyncio
    async def test_resolved_conversation_auto_reopens_to_todo(self, monkeypatch):
        """Nouveau message entrant sur une conv 'resolved' → doit repasser en 'todo'."""
        from albarka_wa_inbox import receive_webhook

        msg_store: list[dict] = []
        label_store: dict[str, dict] = {"+22670000042": {
            "phone": "+22670000042", "label": "resolved",
            "updated_at": "2026-02-01T00:00:00+00:00",
        }}

        class FakeDb:
            class wa_messages:
                @staticmethod
                async def find_one(q, p=None): return None
                @staticmethod
                async def insert_one(doc): msg_store.append(dict(doc))
            class contacts:
                @staticmethod
                async def find_one(*a, **kw): return None
            class users:
                @staticmethod
                async def find_one(*a, **kw): return None
            class wa_conversation_labels:
                @staticmethod
                async def find_one(q, p=None):
                    return label_store.get(q.get("phone"))
                @staticmethod
                async def update_one(q, upd, upsert=False):
                    phone = q.get("phone")
                    label_store[phone] = {**label_store.get(phone, {}), **upd.get("$set", {})}
                    return None

        monkeypatch.setattr("albarka_wa_inbox.db", FakeDb)
        async def _no_settings(): return {"wa_voice_transcribe_enabled": False}
        monkeypatch.setattr("albarka_wa_inbox.get_settings_doc", _no_settings)

        payload = {"entry": [{"changes": [{"value": {
            "contacts": [{"profile": {"name": "Client Reopen"}}],
            "messages": [{
                "id": "wamid.REOPEN_1",
                "from": "22670000042",
                "type": "text",
                "text": {"body": "Nouvelle question !"},
            }],
        }}]}]}

        class FakeRequest:
            async def json(self): return payload

        r = await receive_webhook(FakeRequest())
        assert r["inserted"] == 1
        assert label_store["+22670000042"]["label"] == "todo", (
            f"L'étiquette 'resolved' aurait dû basculer en 'todo'. "
            f"Store: {label_store!r}"
        )
        assert label_store["+22670000042"]["updated_by"] == "system:auto_reopen"

    @pytest.mark.asyncio
    async def test_waiting_conversation_is_not_auto_reopened(self, monkeypatch):
        """Nouveau message sur 'waiting' → NE doit PAS être remis à 'todo'."""
        from albarka_wa_inbox import receive_webhook

        label_store: dict[str, dict] = {"+22670000099": {
            "phone": "+22670000099", "label": "waiting",
            "updated_at": "2026-02-01T00:00:00+00:00",
        }}

        class FakeDb:
            class wa_messages:
                @staticmethod
                async def find_one(q, p=None): return None
                @staticmethod
                async def insert_one(doc): pass
            class contacts:
                @staticmethod
                async def find_one(*a, **kw): return None
            class users:
                @staticmethod
                async def find_one(*a, **kw): return None
            class wa_conversation_labels:
                @staticmethod
                async def find_one(q, p=None): return label_store.get(q.get("phone"))
                @staticmethod
                async def update_one(q, upd, upsert=False):
                    phone = q.get("phone")
                    label_store[phone] = {**label_store.get(phone, {}), **upd.get("$set", {})}

        monkeypatch.setattr("albarka_wa_inbox.db", FakeDb)
        async def _no_settings(): return {"wa_voice_transcribe_enabled": False}
        monkeypatch.setattr("albarka_wa_inbox.get_settings_doc", _no_settings)

        payload = {"entry": [{"changes": [{"value": {
            "messages": [{
                "id": "wamid.WAITING_1",
                "from": "22670000099",
                "type": "text",
                "text": {"body": "Toujours en attente"},
            }],
        }}]}]}

        class FakeRequest:
            async def json(self): return payload

        await receive_webhook(FakeRequest())
        assert label_store["+22670000099"]["label"] == "waiting", (
            "L'étiquette 'waiting' ne doit pas être écrasée par 'todo'"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
