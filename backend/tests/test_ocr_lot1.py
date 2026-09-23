"""Lot 1 OCR — choix du modèle, coût réel FCFA, évaluation, tableau de bord.

Tests unitaires autonomes : MongoDB simulé (mongomock-motor), stockage et
appel IA remplacés par des doublures — aucun serveur, aucune clé, aucun
réseau, dans le même esprit que test_documents_permissions.py.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ.setdefault("USD_TO_XOF_RATE", "600")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import albarka_ai  # noqa: E402
import albarka_documents as ad  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

mongomock_motor = pytest.importorskip("mongomock_motor")

STAFF = {"id": "staff-1", "full_name": "Comptable Test", "roles": ["superviseur"], "is_active": True}
CLIENT = {"id": "client-1", "full_name": "Client Test", "roles": ["client"], "is_active": True}
HAIKU = "claude-haiku-4-5-20251001"


def _png(width: int, height: int) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(buf, format="PNG")
    return buf.getvalue()


def _pdf(pages: int, text: str = "") -> bytes:
    import fitz

    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page()
        if text:
            page.insert_textbox(fitz.Rect(40, 40, 560, 800), f"{text} — page {i + 1}")
    data = doc.tobytes()
    doc.close()
    return data


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------
# albarka_ai : coût, préparation, lecture de la réponse
# ---------------------------------------------------------------------
class TestAiModule:
    def test_cost_uses_real_tokens_and_rate(self):
        usd, xof = albarka_ai.compute_cost(albarka_ai.OCR_MODELS["claude-opus-5"], 1000, 500)
        assert usd == pytest.approx(0.0175) and xof == pytest.approx(10.5)

    def test_default_model_is_unchanged_sonnet(self):
        assert albarka_ai.DEFAULT_MODEL_ID == "claude-sonnet-5"

    def test_photo_is_shrunk_to_1568(self):
        with Image.open(io.BytesIO(albarka_ai._shrink_image(_png(4000, 3000)))) as img:
            assert img.format == "JPEG" and max(img.size) == albarka_ai.MAX_IMAGE_EDGE_PX

    def test_scanned_pdf_is_sent_as_images(self):
        text, images, notes = albarka_ai.prepare_pdf(_pdf(12))
        assert text == "" and len(images) == albarka_ai.MAX_PDF_PAGES and "12" in notes[0]

    def test_text_pdf_is_sent_as_text(self):
        text, images, _ = albarka_ai.prepare_pdf(_pdf(2, "Facture numéro F-12 montant 150000 FCFA " * 20))
        assert images == [] and "F-12" in text

    def test_extract_parses_json_and_computes_cost(self, monkeypatch):
        answer = {"document_type": "Facture", "summary": "ok", "flags": [],
                  "extracted_fields": {"numero": "F-12", "montant_total": 150000},
                  "confidence": 1.7, "uncertain_fields": ["numero", 3]}

        async def fake(model, text, images, filename):
            return json.dumps(answer), 2000, 400

        monkeypatch.setattr(albarka_ai, "_call_llm", fake)
        r = _run(albarka_ai.analyze_document(_png(800, 600), "image/png", "f.png", "claude-sonnet-5"))
        assert r["model"] == "claude-sonnet-5" and r["input_mode"] == "images"
        assert r["confidence"] == 1.0 and r["uncertain_fields"] == ["numero"]
        assert r["cost_usd"] == pytest.approx(0.008) and r["cost_xof"] == pytest.approx(4.8)
        assert "error" not in r

    def test_cost_kept_when_answer_is_not_json(self, monkeypatch):
        async def fake(model, text, images, filename):
            return "désolé", 1000, 10

        monkeypatch.setattr(albarka_ai, "_call_llm", fake)
        r = _run(albarka_ai.analyze_document(_png(100, 100), "image/png", "f.png", HAIKU))
        assert r["error"] and r["cost_xof"] > 0

    def test_backward_compatible_call_without_model(self, monkeypatch):
        """albarka_myaccount.py appelle analyze_document(data, ct, filename)."""
        async def fake(model, text, images, filename):
            return '{"summary": "ok"}', 10, 10

        monkeypatch.setattr(albarka_ai, "_call_llm", fake)
        r = _run(albarka_ai.analyze_document(_png(100, 100), "image/png", "f.png"))
        assert r["model"] == albarka_ai.DEFAULT_MODEL_ID

    def test_call_llm_reads_usage_from_public_api(self, monkeypatch):
        """Branchement réel sur emergentintegrations 0.2.0 : modèle transmis,
        images en ImageContent, tokens lus dans ChatResponse.usage."""
        from emergentintegrations.llm.chat import LlmChat

        captured = {}

        async def fake_send(self, message):
            captured.update(model=self.model, provider=self.provider, params=self.extra_params, message=message)
            return SimpleNamespace(content='{"summary": "x"}',
                                   usage=SimpleNamespace(input_tokens=1234, output_tokens=56))

        monkeypatch.setenv("EMERGENT_LLM_KEY", "sk-emergent-test")
        monkeypatch.setattr(LlmChat, "send_message_with_tools", fake_send)
        out = _run(albarka_ai._call_llm(albarka_ai.OCR_MODELS["claude-opus-5"], "", [b"a", b"b"], "f.pdf"))
        assert out == ('{"summary": "x"}', 1234, 56)
        assert captured["provider"] == "anthropic" and captured["model"] == "claude-opus-5"
        assert captured["params"]["max_tokens"] == 8192
        assert len(captured["message"].file_contents) == 2

    def test_missing_key_is_reported(self, monkeypatch):
        monkeypatch.delenv("EMERGENT_LLM_KEY", raising=False)
        r = _run(albarka_ai.analyze_document(_png(100, 100), "image/png", "f.png"))
        assert "EMERGENT_LLM_KEY" in r["flags"][0]


# ---------------------------------------------------------------------
# Précision réelle
# ---------------------------------------------------------------------
class TestAccuracy:
    def test_formatting_is_not_an_error(self):
        acc = ad.compute_accuracy(
            {"numero": "F-12", "montant_total": 150000, "date": "2026-09-01", "client": "SARL X"},
            {"numero": " f-12 ", "montant_total": "150 000", "date": "2026-09-02", "ifu": "00012345A"},
        )
        assert (acc["fields_total"], acc["fields_corrected"]) == (5, 2)
        assert set(acc["changed"]) == {"date", "ifu"} and acc["accuracy"] == pytest.approx(0.6)

    def test_no_fields(self):
        assert ad.compute_accuracy({}, {})["accuracy"] is None


# ---------------------------------------------------------------------
# API (FastAPI + Mongo simulé)
# ---------------------------------------------------------------------
_ORIGINAL_ANALYZE = ad._analyze_and_store


@pytest.fixture()
def api(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_test"]
    monkeypatch.setattr(ad, "db", mock_db)
    stored = {}

    async def fake_save_and_log(db, *, data, kind, tenant_id, ext, content_type=None,
                                original_filename=None, user_id=None, metadata=None):
        path = f"{kind}/{tenant_id}/{original_filename}"
        stored[path] = data
        return {"id": f"doc-{len(stored)}", "path": path, "size": len(data), "content_type": content_type}

    async def fake_get_object(path):
        return stored[path], "image/png"

    async def noop(*args, **kwargs):
        return None

    scheduled = []

    async def fake_analyze(*args):
        scheduled.append(args)

    monkeypatch.setattr(ad, "save_and_log", fake_save_and_log)
    monkeypatch.setattr(ad, "get_object", fake_get_object)
    monkeypatch.setattr(ad, "notify_upload", noop)
    monkeypatch.setattr(ad, "_analyze_and_store", fake_analyze)
    import albarka_phase_c
    monkeypatch.setattr(albarka_phase_c, "_auto_archive", noop)

    app = FastAPI()
    app.include_router(ad.router, prefix="/api")
    state = {"user": STAFF}
    app.dependency_overrides[get_current_user] = lambda: state["user"]
    return SimpleNamespace(client=TestClient(app), db=mock_db, scheduled=scheduled, state=state)


def _upload(api, **form):
    return api.client.post("/api/documents", files={"file": ("facture.png", _png(200, 100), "image/png")}, data=form)


class TestApi:
    def test_staff_upload_with_chosen_model(self, api):
        assert _upload(api, kind="piece_comptable", tenant_id=CLIENT["id"], model=HAIKU).status_code == 200
        assert api.scheduled[-1][5] == HAIKU and api.scheduled[-1][6] == STAFF["id"]

    def test_staff_upload_rejects_unknown_model(self, api):
        assert _upload(api, kind="piece_comptable", tenant_id=CLIENT["id"], model="gpt-4o").status_code == 400

    def test_client_cannot_choose_model(self, api):
        api.state["user"] = CLIENT
        assert _upload(api, kind="piece_comptable", model=HAIKU).status_code == 200
        assert api.scheduled[-1][5] == albarka_ai.DEFAULT_MODEL_ID

    def test_client_is_forbidden_from_ocr_tools(self, api):
        api.state["user"] = CLIENT
        assert api.client.get("/api/documents/ocr-stats").status_code == 403
        assert api.client.get("/api/documents/ocr-models").status_code == 403

    def test_full_cycle(self, api, monkeypatch):
        doc_id = _upload(api, kind="piece_comptable", tenant_id=CLIENT["id"], model="claude-opus-5").json()["id"]
        base = {"document_type": "Facture", "summary": "ok", "flags": [], "confidence": 0.9,
                "uncertain_fields": [], "input_mode": "images", "input_tokens": 3000, "output_tokens": 600,
                "pages_analyzed": 1, "duration_ms": 1500}
        for model, cost, fields in (("claude-opus-5", 18.0, {"numero": "F-1", "montant_total": 1000}),
                                    (HAIKU, 3.0, {"numero": "F-7", "montant_total": 1000})):
            result = dict(base, model=model, cost_xof=cost, cost_usd=cost / 600, extracted_fields=fields)

            async def fake_analyze_document(*a, _r=result):
                return dict(_r)

            monkeypatch.setattr(ad, "analyze_document", fake_analyze_document)
            _run(_ORIGINAL_ANALYZE(doc_id, b"x", "image/png", "facture.png", CLIENT["id"], model, STAFF["id"]))

        # Synthèse courante : toujours UNE par pièce (id = document_id), la plus récente
        syntheses = _run(api.db.document_syntheses.find({"document_id": doc_id}).to_list(10))
        assert len(syntheses) == 1 and syntheses[0]["id"] == doc_id and syntheses[0]["model"] == HAIKU

        staff_view = api.client.get(f"/api/documents/{doc_id}").json()
        assert [r["model"] for r in staff_view["ocr_runs"]] == ["claude-opus-5", HAIKU]
        assert staff_view["status"] == "analyse"
        assert [r["model"] for r in api.client.get("/api/documents").json()[0]["ocr_runs"]] == ["claude-opus-5", HAIKU]

        api.state["user"] = CLIENT
        client_view = api.client.get(f"/api/documents/{doc_id}").json()
        assert "ocr_runs" not in client_view
        assert "cost_xof" not in client_view["synthesis"] and "model" not in client_view["synthesis"]
        api.state["user"] = STAFF

        opus_run, haiku_run = (r["id"] for r in staff_view["ocr_runs"])
        assert api.client.post(f"/api/documents/ocr-runs/{haiku_run}/review", json={"rating": 6}).status_code == 422
        review = api.client.post(f"/api/documents/ocr-runs/{haiku_run}/review", json={
            "rating": 2, "comment": "numéro faux",
            "corrected_fields": {"numero": "F-1", "montant_total": "1 000"},
        }).json()
        assert review["accuracy"] == pytest.approx(0.5) and review["corrected_fields"] == {"numero": "F-1"}
        api.client.post(f"/api/documents/ocr-runs/{opus_run}/review", json={"rating": 5, "corrected_fields": {}})

        stats = api.client.get("/api/documents/ocr-stats?period=today").json()
        by_model = {m["model"]: m for m in stats["models"]}
        assert by_model["claude-opus-5"]["avg_rating"] == 5 and by_model["claude-opus-5"]["avg_accuracy"] == 1
        assert by_model[HAIKU]["avg_rating"] == 2
        assert stats["total"]["runs"] == 2 and stats["total"]["total_cost_xof"] == pytest.approx(21.0)
        assert api.client.get("/api/documents/ocr-stats?period=hier").status_code == 400

    def test_reanalyze_and_delete(self, api):
        doc_id = _upload(api, kind="piece_comptable", tenant_id=CLIENT["id"], model="claude-opus-5").json()["id"]
        res = api.client.post(f"/api/documents/{doc_id}/reanalyze", json={"model": "claude-sonnet-5"})
        assert res.status_code == 200 and api.scheduled[-1][5] == "claude-sonnet-5"
        assert api.client.post(f"/api/documents/{doc_id}/reanalyze", json={"model": "x"}).status_code == 400
        _run(api.db.document_ocr_runs.insert_one({"id": "r1", "document_id": doc_id}))
        assert api.client.delete(f"/api/documents/{doc_id}").status_code == 200
        assert _run(api.db.document_ocr_runs.count_documents({"document_id": doc_id})) == 0
