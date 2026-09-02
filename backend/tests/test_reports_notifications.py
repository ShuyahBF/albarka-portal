"""Iteration 2 — PDF client reports, manual échéance notifications, cron webhook, multi-roles."""
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import requests
from dotenv import dotenv_values

from conftest import API, CREDENTIALS, make_session

backend_env = dotenv_values("/app/backend/.env")
CRON_SECRET = os.environ.get("WEBHOOK_CRON_SECRET") or backend_env.get("WEBHOOK_CRON_SECRET")


# ---------------- helpers ----------------
def _first_client_tenant(sess):
    r = sess.get(f"{API}/clients", timeout=60)
    assert r.status_code == 200, r.text[:300]
    data = r.json()
    assert isinstance(data, list) and data, "no clients seeded"
    return data


# ---------------- health / storage ----------------
class TestHealth:
    def test_health_storage_r2(self):
        r = requests.get(f"{API}/health", timeout=60)
        assert r.status_code == 200
        b = r.json()
        assert b["status"] == "ok"
        assert b["storage"] == "r2", f"expected r2 storage, got {b}"


# ---------------- PDF report ----------------
class TestClientReportPdf:
    def test_report_as_superviseur(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        r = s.get(f"{API}/reports/client/{u1['id']}", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.headers["content-type"].startswith("application/pdf")
        assert "attachment" in r.headers.get("content-disposition", "")
        assert r.content[:5] == b"%PDF-", r.content[:20]
        assert len(r.content) > 1024, f"pdf too small: {len(r.content)}"

    def test_report_content_parseable(self, superviseur, client1):
        import pymupdf
        s, _ = superviseur
        _, u1 = client1
        r = s.get(f"{API}/reports/client/{u1['id']}", timeout=120)
        assert r.status_code == 200
        doc = pymupdf.open(stream=r.content, filetype="pdf")
        text = "\n".join(p.get_text() for p in doc)
        doc.close()
        assert "CABINET ALBARKA" in text.upper()
        assert "RAPPORT CLIENT" in text.upper()
        assert u1["full_name"] in text, f"client name missing in PDF; got {text[:400]!r}"

    def test_report_as_comptable_multirole(self, comptable, client2):
        c, _ = comptable
        _, u2 = client2
        r = c.get(f"{API}/reports/client/{u2['id']}", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1024

    def test_report_as_own_client(self, client1):
        c1, u1 = client1
        r = c1.get(f"{API}/reports/client/{u1['id']}", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.content[:5] == b"%PDF-"
        assert len(r.content) > 1024

    def test_report_other_tenant_forbidden(self, client1, client2):
        c1, _ = client1
        _, u2 = client2
        r = c1.get(f"{API}/reports/client/{u2['id']}", timeout=60)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"

    def test_report_unknown_tenant_404(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/reports/client/{uuid.uuid4()}", timeout=60)
        assert r.status_code == 404, r.status_code

    def test_report_requires_auth(self):
        r = requests.get(f"{API}/reports/client/{uuid.uuid4()}", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------------- Manual notify ----------------
class TestManualNotify:
    @pytest.fixture(scope="class")
    def echeance(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        r = s.post(f"{API}/echeances", json={
            "tenant_id": u1["id"], "title": "TEST Notify Echeance",
            "type": "tva", "due_date": due, "period": "2026-07", "amount": 150000,
        }, timeout=60)
        assert r.status_code in (200, 201), r.text[:300]
        eid = r.json()["id"]
        yield eid
        s.delete(f"{API}/echeances/{eid}", timeout=60)

    def test_notify_as_staff(self, superviseur, echeance):
        s, _ = superviseur
        r = s.post(f"{API}/echeances/{echeance}/notify", timeout=120)
        assert r.status_code == 200, r.text[:300]
        b = r.json()
        assert b["ok"] is True
        assert b["queued"] is True
        assert isinstance(b["days_left"], int)
        assert b["days_left"] == 7, b

    def test_notify_as_comptable_multirole(self, comptable, echeance):
        c, u = comptable
        assert set(u.get("roles", [])) >= {"comptable", "fiscaliste"}, u.get("roles")
        r = c.post(f"{API}/echeances/{echeance}/notify", timeout=120)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["ok"] is True

    def test_notify_as_client_forbidden(self, client1, echeance):
        c1, _ = client1
        r = c1.post(f"{API}/echeances/{echeance}/notify", timeout=60)
        assert r.status_code == 403, f"expected 403, got {r.status_code} {r.text[:200]}"

    def test_notify_unknown_id_404(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/echeances/{uuid.uuid4()}/notify", timeout=60)
        assert r.status_code == 404, r.status_code

    def test_notify_requires_auth(self, echeance):
        r = requests.post(f"{API}/echeances/{echeance}/notify", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------------- Cron webhook ----------------
class TestCronWebhook:
    URL = f"{API}/cron/notify-echeances"

    def test_secret_present(self):
        assert CRON_SECRET, "WEBHOOK_CRON_SECRET missing from backend/.env"

    def test_no_auth_header_401(self):
        r = requests.post(self.URL, timeout=60)
        assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"

    def test_wrong_token_401(self):
        r = requests.post(self.URL, headers={"Authorization": "Bearer wrong-token"}, timeout=60)
        assert r.status_code == 401, f"{r.status_code} {r.text[:200]}"

    def test_malformed_scheme_401(self):
        r = requests.post(self.URL, headers={"Authorization": CRON_SECRET}, timeout=60)
        assert r.status_code == 401, r.status_code

    def test_valid_token_and_idempotency(self):
        run_id = f"TEST-{uuid.uuid4()}"
        headers = {"Authorization": f"Bearer {CRON_SECRET}", "X-Webhook-Id": run_id}
        started = datetime.now(timezone.utc)
        r1 = requests.post(self.URL, headers=headers, timeout=60)
        elapsed = (datetime.now(timezone.utc) - started).total_seconds()
        assert 200 <= r1.status_code < 300, f"{r1.status_code} {r1.text[:300]}"
        b1 = r1.json()
        assert b1["ok"] is True
        assert b1.get("queued") is True, b1
        assert b1.get("duplicate") is not True
        assert elapsed < 15, f"cron ack took {elapsed}s — should return immediately"

        # duplicate delivery with same webhook id
        r2 = requests.post(self.URL, headers=headers, timeout=60)
        assert r2.status_code == 200, r2.status_code
        b2 = r2.json()
        assert b2 == {"ok": True, "duplicate": True}, b2

    def test_valid_token_without_webhook_id(self):
        r = requests.post(self.URL, headers={"Authorization": f"Bearer {CRON_SECRET}"}, timeout=60)
        assert 200 <= r.status_code < 300, r.status_code
        assert r.json()["ok"] is True

    def test_trigger_as_staff(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{self.URL}/_trigger", timeout=180)
        assert r.status_code == 200, r.text[:300]
        b = r.json()
        assert b["ok"] is True
        stats = b["stats"]
        for k in ("processed", "email_sent", "wa_sent"):
            assert k in stats and isinstance(stats[k], int), stats
        # WhatsApp intentionally not configured
        assert stats["wa_sent"] == 0, f"WA should be skipped (no TWILIO_*): {stats}"

    def test_trigger_as_client_forbidden(self, client1):
        c1, _ = client1
        r = c1.post(f"{self.URL}/_trigger", timeout=60)
        assert r.status_code == 403, r.status_code

    def test_trigger_requires_auth(self):
        r = requests.post(f"{self.URL}/_trigger", timeout=60)
        assert r.status_code in (401, 403), r.status_code


# ---------------- End-to-end notification pipeline ----------------
class TestNotificationPipelineE2E:
    """Creates a real J-7 échéance so _run_daily_notifications actually sends."""

    @pytest.fixture(scope="class")
    def j7_echeance(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        due = (datetime.now(timezone.utc) + timedelta(days=7)).date().isoformat()
        r = s.post(f"{API}/echeances", json={
            "tenant_id": u1["id"], "title": "TEST J7 Pipeline",
            "type": "tva", "due_date": due, "status": "a_venir",
            "period": "2026-09", "amount": 250000,
        }, timeout=60)
        assert r.status_code in (200, 201), r.text[:300]
        eid = r.json()["id"]
        yield eid
        s.delete(f"{API}/echeances/{eid}", timeout=60)

    def test_trigger_sends_and_dedups(self, superviseur, j7_echeance):
        s, _ = superviseur
        r1 = s.post(f"{API}/cron/notify-echeances/_trigger", timeout=180)
        assert r1.status_code == 200, r1.text[:300]
        st1 = r1.json()["stats"]
        assert st1["processed"] >= 1, f"J-7 échéance not picked up: {st1}"
        assert st1["wa_sent"] == 0, f"WA must be skipped (no TWILIO_*): {st1}"
        # NOTE: email_sent stays 0 for seeded demo accounts because the Resend proxy
        # blocks the fake @albarka-demo.bf domain (422 undeliverable_recipient).
        # Transport itself is verified in TestEmailTransport below.

        # second run same day -> deduped, nothing re-sent
        r2 = s.post(f"{API}/cron/notify-echeances/_trigger", timeout=180)
        assert r2.status_code == 200
        st2 = r2.json()["stats"]
        assert st2["processed"] == 0, f"dedup failed, re-processed: {st2}"
        assert st2["email_sent"] == 0, st2


# ---------------- Email transport (Emergent Resend proxy) ----------------
class TestEmailTransport:
    """Verifies send_email/notify_echeance actually reach the Resend proxy."""

    def test_send_email_returns_id(self):
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env", override=False)
        import albarka_notifications as an
        an.EMAIL_KEY = an.EMAIL_KEY or backend_env.get("EMERGENT_EMAIL_KEY", "")

        html = an._echeance_email_html(
            full_name="TEST Client",
            echeance={"title": "TVA", "type": "tva", "due_date": "2026-09-09",
                      "period": "2026-08", "amount": 250000},
            days_left=7,
        )
        eid = asyncio.run(an.send_email(
            to="delivered@resend.dev", subject="TEST Rappel d'echeance (J-7)", html=html,
        ))
        assert eid, "send_email returned None — email guardrails or proxy rejected the message"

    def test_notify_echeance_skips_whatsapp_silently(self):
        import asyncio
        import sys
        sys.path.insert(0, "/app/backend")
        from dotenv import load_dotenv
        load_dotenv("/app/backend/.env", override=False)
        import albarka_notifications as an
        an.EMAIL_KEY = an.EMAIL_KEY or backend_env.get("EMERGENT_EMAIL_KEY", "")

        res = asyncio.run(an.notify_echeance(
            {"email": "delivered@resend.dev", "full_name": "TEST Client", "phone": "+22671111111"},
            {"id": "TEST", "title": "TVA", "type": "tva", "due_date": "2026-09-09",
             "period": "2026-08", "amount": 250000},
            7,
        ))
        assert res["sent_email"] is True, res
        assert res["wa_sid"] is None and res["sent_wa"] is False, res


# ---------------- Multi-role privileges ----------------
class TestMultiRole:
    def test_superviseur_roles_and_access(self, superviseur):
        s, u = superviseur
        assert "superviseur" in u.get("roles", []), u
        for path in ("/clients", "/missions", "/echeances", "/documents", "/dashboard/summary"):
            r = s.get(f"{API}{path}", timeout=60)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"

    def test_comptable_cumulative_roles(self, comptable):
        c, u = comptable
        roles = set(u.get("roles", []))
        assert roles >= {"comptable", "fiscaliste"}, roles
        for path in ("/clients", "/missions", "/echeances", "/clients/staff"):
            r = c.get(f"{API}{path}", timeout=60)
            assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"

    def test_client_cannot_list_staff(self, client1):
        c1, _ = client1
        r = c1.get(f"{API}/clients/staff", timeout=60)
        assert r.status_code == 403, r.status_code

    def test_client_scoped_data(self, client1, client2):
        c1, u1 = client1
        _, u2 = client2
        r = c1.get(f"{API}/echeances", timeout=60)
        assert r.status_code == 200
        for e in r.json():
            assert e["tenant_id"] == u1["id"], e
