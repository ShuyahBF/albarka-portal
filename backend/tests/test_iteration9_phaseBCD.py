"""Iteration 9 — Phases B, C, D backend tests.

Phase B : contrats clients + login gate, WhatsApp retry, bulk-generate,
auto-WA J+N post signature, export trimestriel.
Phase C : chat interne, caisse/billing, RH & paie, platform logs, archives,
messagerie broadcast.
Phase D : comptabilité OHADA (plan, écritures, balance, grand livre).
"""
import secrets
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from conftest import API, make_session, run_async

TS = secrets.token_hex(4)


# =====================================================================
# Phase B — Feature 14 : contrats clients + gate login
# =====================================================================
class TestContractsAndLoginGate:
    def test_contract_crud_and_login_gate(self, superviseur):
        s, _ = superviseur
        email = f"test_gate_{TS}@albarka-demo.bf"
        password = "TestGate2026!"

        # 1. create a fresh client (no contract)
        r = s.post(f"{API}/clients", json={
            "email": email, "full_name": f"TEST_Gate {TS}",
            "password": password, "company": "TEST SARL",
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        client_id = r.json()["id"]

        try:
            # 2. login without contract -> 403 on verify-otp
            lr = requests.post(f"{API}/auth/login",
                               json={"email": email, "password": password}, timeout=60)
            assert lr.status_code == 200, lr.text[:300]
            body = lr.json()
            assert body.get("dev_otp"), body
            vr = requests.post(f"{API}/auth/verify-otp", json={
                "session_token": body["session_token"], "code": body["dev_otp"],
            }, timeout=60)
            assert vr.status_code == 403, f"expected 403, got {vr.status_code} {vr.text[:300]}"
            assert "contrat actif" in vr.json().get("detail", "").lower()

            # 3. create an active contract
            start = (date.today() - timedelta(days=10)).isoformat()
            end = (date.today() + timedelta(days=200)).isoformat()
            cr = s.post(f"{API}/client-contracts", json={
                "tenant_id": client_id, "title": "TEST_Contrat annuel",
                "start_date": start, "end_date": end,
                "amount": 1200000, "status": "en_cours",
            }, timeout=60)
            assert cr.status_code == 200, cr.text[:300]
            contract = cr.json()
            contract_id = contract["id"]
            assert contract["tenant_id"] == client_id
            assert contract["status"] == "en_cours"
            assert contract["currency"] == "XOF"
            assert "_id" not in contract

            # GET verifies persistence
            g = s.get(f"{API}/client-contracts/{contract_id}", timeout=60)
            assert g.status_code == 200
            assert g.json()["title"] == "TEST_Contrat annuel"

            # list filtered by tenant
            lst = s.get(f"{API}/client-contracts", params={"tenant_id": client_id}, timeout=60)
            assert lst.status_code == 200
            assert any(c["id"] == contract_id for c in lst.json())

            # 4. login now succeeds
            lr2 = requests.post(f"{API}/auth/login",
                                json={"email": email, "password": password}, timeout=60)
            b2 = lr2.json()
            vr2 = requests.post(f"{API}/auth/verify-otp", json={
                "session_token": b2["session_token"], "code": b2["dev_otp"],
            }, timeout=60)
            assert vr2.status_code == 200, f"{vr2.status_code} {vr2.text[:300]}"
            assert vr2.json().get("access_token")

            # 5. PATCH -> suspended blocks login again
            pr = s.patch(f"{API}/client-contracts/{contract_id}",
                         json={"status": "suspendu"}, timeout=60)
            assert pr.status_code == 200, pr.text[:300]
            assert pr.json()["status"] == "suspendu"

            lr3 = requests.post(f"{API}/auth/login",
                                json={"email": email, "password": password}, timeout=60)
            b3 = lr3.json()
            vr3 = requests.post(f"{API}/auth/verify-otp", json={
                "session_token": b3["session_token"], "code": b3["dev_otp"],
            }, timeout=60)
            assert vr3.status_code == 403, f"suspended contract should block: {vr3.status_code}"

            # 6. DELETE contract
            dr = s.delete(f"{API}/client-contracts/{contract_id}", timeout=60)
            assert dr.status_code == 200
            assert s.get(f"{API}/client-contracts/{contract_id}", timeout=60).status_code == 404
        finally:
            s.delete(f"{API}/clients/{client_id}", timeout=60)
            run_async(lambda d: d.client_contracts.delete_many({"tenant_id": client_id}))

    def test_contract_validation_and_rbac(self, superviseur, client1):
        s, _ = superviseur
        c, cu = client1
        # unknown client -> 404
        r = s.post(f"{API}/client-contracts", json={
            "tenant_id": "does-not-exist", "title": "TEST_x",
            "start_date": "2026-01-01",
        }, timeout=60)
        assert r.status_code == 404, r.text[:200]
        # bad status -> 422
        r = s.post(f"{API}/client-contracts", json={
            "tenant_id": cu["id"], "title": "TEST_x",
            "start_date": "2026-01-01", "status": "bogus",
        }, timeout=60)
        assert r.status_code == 422
        # bad date -> 422
        r = s.post(f"{API}/client-contracts", json={
            "tenant_id": cu["id"], "title": "TEST_x", "start_date": "01/01/2026",
        }, timeout=60)
        assert r.status_code == 422
        # client cannot list contracts
        assert c.get(f"{API}/client-contracts", timeout=60).status_code == 403


# =====================================================================
# Phase B — Feature 1 : WhatsApp retry
# =====================================================================
class TestWhatsAppRetry:
    def test_retry_unknown_log(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/reports/whatsapp/retry/unknown-log-id", timeout=60)
        assert r.status_code == 404, r.text[:200]

    def test_retry_failed_entry(self, superviseur):
        s, _ = superviseur
        # need an existing report to attach the log entry to
        reports = run_async(lambda d: d.client_reports.find({}, {"_id": 0}).to_list(1))
        if not reports:
            pytest.skip("no client_reports in db to attach a wa log to")
        report = reports[0]
        log_id = f"TEST_walog_{TS}"
        ok_id = f"TEST_walog_ok_{TS}"
        run_async(lambda d: d.wa_send_log.insert_many([
            {"id": log_id, "report_id": report["id"], "tenant_id": report["tenant_id"],
             "phone": "+22670000000", "success": False, "error": "TEST failure",
             "created_at": datetime.now(timezone.utc).isoformat()},
            {"id": ok_id, "report_id": report["id"], "tenant_id": report["tenant_id"],
             "phone": "+22670000001", "success": True,
             "created_at": datetime.now(timezone.utc).isoformat()},
        ]))
        try:
            # already-successful entry -> 400
            r_ok = s.post(f"{API}/reports/whatsapp/retry/{ok_id}", timeout=120)
            assert r_ok.status_code == 400, r_ok.text[:200]

            r = s.post(f"{API}/reports/whatsapp/retry/{log_id}", timeout=180)
            assert r.status_code in (200, 400, 502), f"{r.status_code} {r.text[:300]}"
            if r.status_code == 200:
                body = r.json()
                assert body["retried_log_id"] == log_id
                assert "ok" in body and "result" in body
        finally:
            run_async(lambda d: d.wa_send_log.delete_many(
                {"id": {"$in": [log_id, ok_id]}}))


# =====================================================================
# Phase B — Feature 2 : bulk generate
# =====================================================================
class TestBulkGenerate:
    def test_bulk_generate_monthly(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/reports/bulk-generate", json={
            "kind": "mensuel", "period_month": "2026-09",
            "tenant_ids": [cu["id"]],
        }, timeout=300)
        assert r.status_code == 200, r.text[:400]
        body = r.json()
        assert body["ok"] is True
        assert body["generated_count"] + body["failed_count"] == 1, body
        assert body["generated_count"] == 1, f"generation failed: {body.get('failed')}"
        rid = body["generated"][0]["report_id"]
        assert body["generated"][0]["number"]
        # verify persistence
        lst = s.get(f"{API}/reports/client/{cu['id']}/list", timeout=60)
        assert lst.status_code == 200
        assert any(x["id"] == rid for x in lst.json())
        s.delete(f"{API}/reports/{rid}", timeout=60)

    def test_bulk_generate_bad_kind(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/reports/bulk-generate",
                   json={"kind": "bogus", "period_month": "2026-09"}, timeout=60)
        assert r.status_code == 400, r.text[:200]


# =====================================================================
# Phase B — Feature 4 : export trimestriel
# =====================================================================
class TestQuarterlyReport:
    def test_generate_quarterly(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/reports/client/{cu['id']}/generate-quarterly",
                   json={"period_quarter": "2026-Q3"}, timeout=300)
        assert r.status_code == 200, r.text[:400]
        rep = r.json()
        assert rep["kind"] == "trimestriel"
        assert rep["period_quarter"] == "2026-Q3"
        assert "TRIMESTRIEL" in rep["number"]
        assert rep["size"] > 0
        assert "_id" not in rep
        # download works
        dl = s.get(f"{API}/reports/{rep['id']}/download", timeout=120)
        assert dl.status_code == 200
        s.delete(f"{API}/reports/{rep['id']}", timeout=60)

    def test_quarterly_bad_period(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/reports/client/{cu['id']}/generate-quarterly",
                   json={"period_quarter": "2026-13"}, timeout=60)
        assert r.status_code == 400, r.text[:200]


# =====================================================================
# Phase B — Feature 3 : auto WhatsApp J+N après signature
# =====================================================================
class TestAutoWhatsAppAfterSign:
    def test_auto_schedule_created_on_sign(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        prev = s.get(f"{API}/admin/settings", timeout=60)
        assert prev.status_code == 200, prev.text[:200]
        prev_enabled = prev.json().get("auto_wa_after_sign_enabled")
        prev_days = prev.json().get("auto_wa_after_sign_days")

        up = s.put(f"{API}/admin/settings", json={
            "auto_wa_after_sign_enabled": True, "auto_wa_after_sign_days": 1,
        }, timeout=60)
        assert up.status_code == 200, up.text[:300]
        assert up.json()["auto_wa_after_sign_enabled"] is True
        assert up.json()["auto_wa_after_sign_days"] == 1

        report_id = None
        try:
            g = s.post(f"{API}/reports/client/{cu['id']}/generate",
                       json={"kind": "mensuel", "period_month": "2026-08"}, timeout=300)
            assert g.status_code == 200, g.text[:400]
            report_id = g.json()["id"]

            sg = s.post(f"{API}/reports/{report_id}/sign", json={
                "signature_name": "TEST Signataire",
                "signature_provider": "cabinet_seal",
            }, timeout=180)
            assert sg.status_code == 200, sg.text[:400]
            assert sg.json()["signed"] is True

            sched = s.get(f"{API}/reports/whatsapp/scheduled", timeout=60)
            assert sched.status_code == 200
            mine = [x for x in sched.json() if x.get("report_id") == report_id]
            assert mine, f"no scheduled entry created for report {report_id}"
            entry = mine[0]
            assert entry.get("auto") is True
            assert entry["payload"].get("all_whatsapp_contacts") is True
            assert entry["status"] == "pending"
            delta = datetime.fromisoformat(entry["scheduled_at"]) - datetime.now(timezone.utc)
            assert timedelta(hours=20) < delta < timedelta(hours=28), entry["scheduled_at"]
            # cleanup scheduled entry
            s.delete(f"{API}/reports/whatsapp/scheduled/{entry['id']}", timeout=60)
        finally:
            if report_id:
                s.delete(f"{API}/reports/{report_id}", timeout=60)
                run_async(lambda d: d.scheduled_wa_sends.delete_many({"report_id": report_id}))
                run_async(lambda d: d.signature_log.delete_many({"report_id": report_id}))
            s.put(f"{API}/admin/settings", json={
                "auto_wa_after_sign_enabled": bool(prev_enabled),
                "auto_wa_after_sign_days": prev_days or 1,
            }, timeout=60)


# =====================================================================
# Phase C — 8a Chat interne
# =====================================================================
class TestChat:
    def test_staff_and_client_thread(self, superviseur, client1, client2):
        s, _ = superviseur
        c1, u1 = client1
        c2, u2 = client2
        thread = f"client:{u1['id']}"

        r = s.post(f"{API}/chat/messages",
                   json={"thread_id": thread, "body": f"TEST staff msg {TS}"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        assert r.json()["author_is_client"] is False
        assert "_id" not in r.json()

        r2 = c1.post(f"{API}/chat/messages",
                     json={"thread_id": thread, "body": f"TEST client msg {TS}"}, timeout=60)
        assert r2.status_code == 200, r2.text[:300]
        assert r2.json()["author_is_client"] is True

        lst = c1.get(f"{API}/chat/messages", params={"thread_id": thread}, timeout=60)
        assert lst.status_code == 200
        bodies = [m["body"] for m in lst.json()]
        assert f"TEST staff msg {TS}" in bodies and f"TEST client msg {TS}" in bodies

        # client2 cannot read/post to client1 thread
        assert c2.get(f"{API}/chat/messages", params={"thread_id": thread},
                      timeout=60).status_code == 403
        assert c2.post(f"{API}/chat/messages",
                       json={"thread_id": thread, "body": "hack"}, timeout=60).status_code == 403

        # threads is staff only
        th = s.get(f"{API}/chat/threads", timeout=60)
        assert th.status_code == 200
        assert any(t["thread_id"] == thread for t in th.json())
        assert c1.get(f"{API}/chat/threads", timeout=60).status_code == 403

        run_async(lambda d: d.chat_messages.delete_many({"body": {"$regex": f"TEST .* {TS}"}}))


# =====================================================================
# Phase C — 8b Caisse / billing
# =====================================================================
class TestBilling:
    def test_invoice_payment_lifecycle(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/billing/invoices", json={
            "tenant_id": cu["id"], "title": f"TEST_Facture {TS}",
            "items": [
                {"label": "Tenue comptable", "quantity": 2, "unit_price": 50000, "tax_rate": 18},
                {"label": "Conseil", "quantity": 1, "unit_price": 100000, "tax_rate": 0},
            ],
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        inv = r.json()
        invoice_id = inv["id"]
        try:
            assert inv["subtotal"] == 200000
            assert inv["tax"] == 18000
            assert inv["total"] == 218000
            assert inv["status"] == "unpaid"
            assert inv["paid_amount"] == 0
            assert inv["number"].startswith("FAC-")

            # partial payment
            p1 = s.post(f"{API}/billing/payments", json={
                "invoice_id": invoice_id, "amount": 100000, "method": "cash",
            }, timeout=60)
            assert p1.status_code == 200, p1.text[:300]
            assert p1.json()["invoice_number"] == inv["number"]
            got = s.get(f"{API}/billing/invoices", params={"tenant_id": cu["id"]}, timeout=60).json()
            cur = next(x for x in got if x["id"] == invoice_id)
            assert cur["paid_amount"] == 100000
            assert cur["status"] == "partial"

            # final payment
            p2 = s.post(f"{API}/billing/payments", json={
                "invoice_id": invoice_id, "amount": 118000, "method": "mobile_money",
            }, timeout=60)
            assert p2.status_code == 200
            got = s.get(f"{API}/billing/invoices", params={"tenant_id": cu["id"]}, timeout=60).json()
            cur = next(x for x in got if x["id"] == invoice_id)
            assert cur["paid_amount"] == 218000
            assert cur["status"] == "paid"

            pays = s.get(f"{API}/billing/payments", params={"invoice_id": invoice_id}, timeout=60)
            assert pays.status_code == 200
            assert len(pays.json()) == 2

            summ = s.get(f"{API}/billing/summary", timeout=60)
            assert summ.status_code == 200
            sb = summ.json()
            for k in ("invoice_count", "total_billed", "total_paid", "outstanding", "unpaid_count"):
                assert k in sb
            assert sb["total_billed"] >= 218000
        finally:
            run_async(lambda d: d.payments.delete_many({"invoice_id": invoice_id}))
            run_async(lambda d: d.invoices.delete_many({"id": invoice_id}))

    def test_payment_unknown_invoice_and_rbac(self, superviseur, client1):
        s, _ = superviseur
        c, _ = client1
        r = s.post(f"{API}/billing/payments",
                   json={"invoice_id": "nope", "amount": 100}, timeout=60)
        assert r.status_code == 404
        assert c.get(f"{API}/billing/invoices", timeout=60).status_code == 403
        # negative amount rejected
        r2 = s.post(f"{API}/billing/payments",
                    json={"invoice_id": "nope", "amount": -5}, timeout=60)
        assert r2.status_code == 422


# =====================================================================
# Phase C — 9 RH & Paie
# =====================================================================
class TestHR:
    def test_employee_and_payslip(self, superviseur, client1, comptable):
        s, _ = superviseur
        _, cu = client1
        comp, _ = comptable
        r = s.post(f"{API}/hr/employees", json={
            "tenant_id": cu["id"], "full_name": f"TEST_Employe {TS}",
            "role": "Caissier", "base_salary": 150000,
            "hire_date": "2025-01-15", "phone": "+22670000002",
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        emp = r.json()
        emp_id = emp["id"]
        try:
            assert emp["base_salary"] == 150000
            assert "_id" not in emp

            ps = s.post(f"{API}/hr/payslips", json={
                "employee_id": emp_id, "period_month": "2026-06",
                "gross_salary": 150000, "deductions": 20000, "bonuses": 5000,
            }, timeout=60)
            assert ps.status_code == 200, ps.text[:300]
            slip = ps.json()
            assert slip["net_salary"] == 135000
            assert slip["employee_name"] == f"TEST_Employe {TS}"
            assert slip["tenant_id"] == cu["id"]

            lst = s.get(f"{API}/hr/payslips", params={"employee_id": emp_id}, timeout=60)
            assert lst.status_code == 200
            assert any(x["id"] == slip["id"] for x in lst.json())

            emps = s.get(f"{API}/hr/employees", params={"tenant_id": cu["id"]}, timeout=60)
            assert emps.status_code == 200
            assert any(x["id"] == emp_id for x in emps.json())

            # unknown employee -> 404 ; bad month -> 422
            assert s.post(f"{API}/hr/payslips", json={
                "employee_id": "nope", "period_month": "2026-06", "gross_salary": 1,
            }, timeout=60).status_code == 404
            assert s.post(f"{API}/hr/payslips", json={
                "employee_id": emp_id, "period_month": "juin 2026", "gross_salary": 1,
            }, timeout=60).status_code == 422

            # comptable (no rh role) must be refused
            assert comp.get(f"{API}/hr/employees", timeout=60).status_code == 403
        finally:
            run_async(lambda d: d.payslips.delete_many({"employee_id": emp_id}))
            run_async(lambda d: d.employees.delete_many({"id": emp_id}))


# =====================================================================
# Phase C — 10 Platform logs
# =====================================================================
class TestPlatformLogs:
    def test_logs_rbac_and_autolog(self, superviseur, comptable, client1):
        s, _ = superviseur
        comp, _ = comptable
        c, cu = client1
        # generate an event
        inv = s.post(f"{API}/billing/invoices", json={
            "tenant_id": cu["id"], "title": f"TEST_Log {TS}",
            "items": [{"label": "x", "quantity": 1, "unit_price": 1000, "tax_rate": 0}],
        }, timeout=60)
        assert inv.status_code == 200
        invoice_id = inv.json()["id"]
        try:
            r = s.get(f"{API}/platform-logs", timeout=60)
            assert r.status_code == 200, r.text[:300]
            data = r.json()
            items = data["items"] if isinstance(data, dict) and "items" in data else data
            assert isinstance(items, list) and items
            assert any(x.get("action") == "invoice.create" for x in items), items[:2]
            assert all("_id" not in x for x in items)
            # RBAC: comptable + client refused
            assert comp.get(f"{API}/platform-logs", timeout=60).status_code == 403
            assert c.get(f"{API}/platform-logs", timeout=60).status_code == 403
        finally:
            run_async(lambda d: d.invoices.delete_many({"id": invoice_id}))
            run_async(lambda d: d.platform_logs.delete_many({"entity_id": invoice_id}))


# =====================================================================
# Phase C — 11 Archives
# =====================================================================
class TestArchives:
    def test_archive_crud(self, superviseur, client1):
        s, _ = superviseur
        c, _ = client1
        r = s.post(f"{API}/archives", json={
            "title": f"TEST_Archive {TS}", "category": "juridique",
            "description": "dossier de test", "tags": ["test", TS],
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        item = r.json()
        aid = item["id"]
        assert item["category"] == "juridique"
        assert TS in item["tags"]
        assert item.get("created_by_name")

        lst = s.get(f"{API}/archives", params={"tag": TS}, timeout=60)
        assert lst.status_code == 200
        assert [x["id"] for x in lst.json()] == [aid]

        srch = s.get(f"{API}/archives", params={"q": f"TEST_Archive {TS}"}, timeout=60)
        assert srch.status_code == 200 and len(srch.json()) == 1

        assert c.get(f"{API}/archives", timeout=60).status_code == 403

        d = s.delete(f"{API}/archives/{aid}", timeout=60)
        assert d.status_code == 200
        assert s.delete(f"{API}/archives/{aid}", timeout=60).status_code == 404
        assert s.get(f"{API}/archives", params={"tag": TS}, timeout=60).json() == []


# =====================================================================
# Phase C — 12 Messagerie broadcast
# =====================================================================
class TestBroadcast:
    def test_broadcast_scopes(self, superviseur, comptable):
        s, _ = superviseur
        comp, _ = comptable
        r = s.post(f"{API}/messaging/broadcast", json={
            "subject": f"TEST_Broadcast {TS}", "body": "message de test",
            "scope": "clients", "channel": "email",
        }, timeout=180)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        bid = body["id"]
        try:
            assert body["ok"] is True
            assert body["recipient_count"] >= 1
            assert "delivery_attempts" in body and "delivered" in body

            lst = s.get(f"{API}/messaging/broadcasts", timeout=60)
            assert lst.status_code == 200
            mine = next(x for x in lst.json() if x["id"] == bid)
            assert mine["scope"] == "clients"
            assert mine["channel"] == "email"
            assert "completed_at" in mine

            # invalid scope / channel
            assert s.post(f"{API}/messaging/broadcast", json={
                "subject": "x", "body": "y", "scope": "bogus", "channel": "email",
            }, timeout=60).status_code == 422
            assert s.post(f"{API}/messaging/broadcast", json={
                "subject": "x", "body": "y", "scope": "all", "channel": "sms",
            }, timeout=60).status_code == 422
            # comptable not allowed
            assert comp.post(f"{API}/messaging/broadcast", json={
                "subject": "x", "body": "y", "scope": "staff", "channel": "email",
            }, timeout=60).status_code == 403
        finally:
            run_async(lambda d: d.broadcast_deliveries.delete_many({"broadcast_id": bid}))
            run_async(lambda d: d.broadcasts.delete_many({"id": bid}))
            run_async(lambda d: d.platform_logs.delete_many({"entity_id": bid}))


# =====================================================================
# Phase D — Comptabilité OHADA
# =====================================================================
class TestOhada:
    def test_full_accounting_flow(self, superviseur, comptable, client1):
        s, _ = superviseur
        comp, _ = comptable
        c, cu = client1
        tenant = cu["id"]

        seed = s.post(f"{API}/accounting/seed-plan", params={"tenant_id": tenant}, timeout=120)
        assert seed.status_code == 200, seed.text[:300]
        sb = seed.json()
        assert sb["ok"] is True
        assert sb.get("seeded") == 29 or sb.get("count", 0) >= 29, sb

        # idempotent
        seed2 = s.post(f"{API}/accounting/seed-plan", params={"tenant_id": tenant}, timeout=60)
        assert seed2.status_code == 200
        assert seed2.json().get("already_seeded") is True

        accounts = s.get(f"{API}/accounting/accounts", params={"tenant_id": tenant}, timeout=60)
        assert accounts.status_code == 200
        codes = [a["code"] for a in accounts.json()]
        assert len(codes) >= 29
        assert codes == sorted(codes)
        for expected in ("101", "411", "521", "601", "701"):
            assert expected in codes

        # class filter
        cls5 = s.get(f"{API}/accounting/accounts",
                     params={"tenant_id": tenant, "account_class": 5}, timeout=60)
        assert cls5.status_code == 200
        assert {a["code"] for a in cls5.json()} == {"521", "531"}

        entry_id = None
        entry2_id = None
        try:
            # unbalanced -> 400
            bad = s.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "OD", "entry_date": "2026-07-01",
                "label": "TEST desequilibre",
                "lines": [
                    {"account_code": "601", "debit": 1000, "credit": 0},
                    {"account_code": "401", "debit": 0, "credit": 800},
                ],
            }, timeout=60)
            assert bad.status_code == 400, bad.text[:300]
            assert "quilibr" in bad.json()["detail"]

            # unknown account -> 400
            bad2 = s.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "OD", "entry_date": "2026-07-01",
                "label": "TEST compte inconnu",
                "lines": [
                    {"account_code": "999999", "debit": 1000, "credit": 0},
                    {"account_code": "401", "debit": 0, "credit": 1000},
                ],
            }, timeout=60)
            assert bad2.status_code == 400 and "inconnu" in bad2.json()["detail"]

            # debit+credit on same line -> 400
            bad3 = s.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "OD", "entry_date": "2026-07-01",
                "label": "TEST ligne double",
                "lines": [
                    {"account_code": "601", "debit": 1000, "credit": 1000},
                    {"account_code": "401", "debit": 1000, "credit": 1000},
                ],
            }, timeout=60)
            assert bad3.status_code == 400, bad3.text[:200]

            # single line -> 422 (min_length=2)
            bad4 = s.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "OD", "entry_date": "2026-07-01",
                "label": "TEST une ligne",
                "lines": [{"account_code": "601", "debit": 1000, "credit": 0}],
            }, timeout=60)
            assert bad4.status_code == 422

            # balanced entry (comptable role allowed)
            ok = comp.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "AC", "entry_date": "2026-07-05",
                "label": f"TEST achat marchandises {TS}", "reference": "F-001",
                "lines": [
                    {"account_code": "601", "debit": 500000, "credit": 0, "label": "Achat"},
                    {"account_code": "445", "debit": 90000, "credit": 0, "label": "TVA ded"},
                    {"account_code": "401", "debit": 0, "credit": 590000, "label": "Fournisseur"},
                ],
            }, timeout=60)
            assert ok.status_code == 200, ok.text[:400]
            e = ok.json()
            entry_id = e["id"]
            assert e["status"] == "draft"
            assert e["total_debit"] == 590000 == e["total_credit"]
            assert e["number"].startswith("AC-2026-")
            assert "_id" not in e

            # ledger ignores drafts
            led0 = s.get(f"{API}/accounting/ledger/601", params={"tenant_id": tenant}, timeout=60)
            assert led0.status_code == 200
            assert all(m["entry_id"] != entry_id for m in led0.json()["movements"])

            # validate
            v = s.post(f"{API}/accounting/entries/{entry_id}/validate", timeout=60)
            assert v.status_code == 200, v.text[:300]
            assert v.json()["status"] == "validated"
            assert v.json().get("validated_at")
            # idempotent validate
            assert s.post(f"{API}/accounting/entries/{entry_id}/validate",
                          timeout=60).json()["status"] == "validated"
            # cannot delete validated
            assert s.delete(f"{API}/accounting/entries/{entry_id}", timeout=60).status_code == 400

            # second entry to test running balance
            ok2 = s.post(f"{API}/accounting/entries", json={
                "tenant_id": tenant, "journal": "AC", "entry_date": "2026-07-10",
                "label": f"TEST achat 2 {TS}",
                "lines": [
                    {"account_code": "601", "debit": 100000, "credit": 0},
                    {"account_code": "401", "debit": 0, "credit": 100000},
                ],
            }, timeout=60)
            assert ok2.status_code == 200
            entry2_id = ok2.json()["id"]
            s.post(f"{API}/accounting/entries/{entry2_id}/validate", timeout=60)

            led = s.get(f"{API}/accounting/ledger/601",
                        params={"tenant_id": tenant, "date_from": "2026-07-01",
                                "date_to": "2026-07-31"}, timeout=60)
            assert led.status_code == 200
            lb = led.json()
            assert lb["account"]["code"] == "601"
            movs = [m for m in lb["movements"] if m["entry_id"] in (entry_id, entry2_id)]
            assert len(movs) == 2
            assert movs[0]["debit"] == 500000
            assert movs[1]["balance"] - movs[0]["balance"] == 100000
            assert lb["total_debit"] >= 600000

            # unknown account ledger -> 404
            assert s.get(f"{API}/accounting/ledger/999999",
                         params={"tenant_id": tenant}, timeout=60).status_code == 404

            tb = s.get(f"{API}/accounting/trial-balance",
                       params={"tenant_id": tenant, "date_from": "2026-07-01",
                               "date_to": "2026-07-31"}, timeout=60)
            assert tb.status_code == 200
            tbb = tb.json()
            assert tbb["balanced"] is True
            assert tbb["total_debit"] == tbb["total_credit"]
            row601 = next(r for r in tbb["rows"] if r["code"] == "601")
            assert row601["debit"] == 600000
            assert row601["debit_balance"] == 600000
            row401 = next(r for r in tbb["rows"] if r["code"] == "401")
            assert row401["credit"] == 690000
            assert row401["credit_balance"] == 690000

            # entries listing filters
            el = s.get(f"{API}/accounting/entries",
                       params={"tenant_id": tenant, "journal": "AC",
                               "status": "validated"}, timeout=60)
            assert el.status_code == 200
            ids = [x["id"] for x in el.json()]
            assert entry_id in ids and entry2_id in ids

            # client has no access
            assert c.get(f"{API}/accounting/accounts",
                         params={"tenant_id": tenant}, timeout=60).status_code == 403
        finally:
            run_async(lambda d: d.accounting_entries.delete_many(
                {"id": {"$in": [i for i in (entry_id, entry2_id) if i]}}))

    def test_create_duplicate_account(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/accounting/accounts", json={
            "tenant_id": cu["id"], "code": "601", "label": "dup",
            "class": 6, "type": "charge",
        }, timeout=60)
        assert r.status_code == 409, r.text[:200]


# =====================================================================
# Régression — sécurité RBAC clients (itération 8)
# =====================================================================
class TestRegressionSecurity:
    def test_client_role_cannot_be_escalated(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.patch(f"{API}/clients/{cu['id']}",
                    json={"roles": ["client", "administrateur"]}, timeout=60)
        assert r.status_code == 422, r.text[:200]
        r2 = s.patch(f"{API}/clients/{cu['id']}", json={"roles": []}, timeout=60)
        assert r2.status_code == 422, r2.text[:200]
        # roles intact
        me = s.get(f"{API}/clients/{cu['id']}", timeout=60)
        assert me.status_code == 200
        assert me.json()["roles"] == ["client"]

    def test_login_and_last_login(self, client2):
        c, u = client2
        r = c.get(f"{API}/auth/me", timeout=60)
        assert r.status_code == 200
        assert r.json()["id"] == u["id"]
        assert r.json()["last_login"]
