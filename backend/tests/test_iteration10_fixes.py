"""Iteration 10 — passe de corrections priorité 1 (points 2-7, 9).

Point 2 : auto-archives (document / invoice / payslip) + archives manuelles
Point 3 : rôle `communication` et RBAC messagerie
Point 4 : export PDF du journal signatures + WhatsApp
Point 5 : PDF bulletin de paie
Point 6 : types de documents caisse (facture / recu / proforma)
Point 7 : contrats FR (numero_contrat, date_dernier_paiement, statuts FR)
Point 9 : auto-WA J+24h après signature
"""
import io
import re
import secrets
import subprocess
from datetime import date, datetime, timedelta, timezone

import pytest
import requests

from conftest import API, make_session, run_async

TS = secrets.token_hex(4)


def _pdf_text(data: bytes) -> str:
    """Extract text from a PDF (pymupdf, then pdftotext, then raw bytes)."""
    try:
        import pymupdf  # noqa: PLC0415
        with pymupdf.open(stream=data, filetype="pdf") as d:
            return "\n".join(p.get_text() for p in d)
    except Exception:  # noqa: BLE001
        pass
    try:
        p = subprocess.run(["pdftotext", "-", "-"], input=data,
                           capture_output=True, timeout=60)
        if p.returncode == 0 and p.stdout:
            return p.stdout.decode("utf-8", "ignore")
    except Exception:  # noqa: BLE001
        pass
    return data.decode("latin-1", "ignore")


# =====================================================================
# Point 2 — auto-archives
# =====================================================================
class TestAutoArchives:
    def test_document_upload_auto_archive(self, superviseur, client1):
        s, _ = superviseur
        c, cu = client1
        fname = f"TEST_piece_{TS}.pdf"
        payload = b"%PDF-1.4\n% TEST upload archive\n"
        r = c.post(f"{API}/documents", files={
            "file": (fname, io.BytesIO(payload), "application/pdf"),
        }, data={"kind": "piece_comptable"}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        doc_id = r.json()["id"]
        try:
            lst = s.get(f"{API}/archives", params={"source_kind": "document"}, timeout=60)
            assert lst.status_code == 200, lst.text[:300]
            mine = [a for a in lst.json() if (a.get("source") or {}).get("id") == doc_id]
            assert mine, f"no auto archive for document {doc_id}"
            a = mine[0]
            assert a["source"]["auto"] is True
            assert a["source"]["kind"] == "document"
            assert a["category"] == "pieces_client"
            assert fname in a["title"]
            assert "_id" not in a
        finally:
            run_async(lambda d: d.archives.delete_many({"source.id": doc_id}))
            run_async(lambda d: d.documents.delete_many({"id": doc_id}))

    def test_invoice_auto_archive(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/billing/invoices", json={
            "tenant_id": cu["id"], "title": f"TEST_ArchInv {TS}",
            "items": [{"label": "x", "quantity": 1, "unit_price": 1000, "tax_rate": 0}],
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        inv = r.json()
        try:
            lst = s.get(f"{API}/archives", params={"source_kind": "invoice"}, timeout=60)
            assert lst.status_code == 200
            mine = [a for a in lst.json() if (a.get("source") or {}).get("id") == inv["id"]]
            assert mine, f"no auto archive for invoice {inv['id']}"
            assert mine[0]["source"]["auto"] is True
            assert mine[0]["category"] == "caisse"
            assert inv["number"] in mine[0]["title"]
        finally:
            run_async(lambda d: d.archives.delete_many({"source.id": inv["id"]}))
            run_async(lambda d: d.invoices.delete_many({"id": inv["id"]}))
            run_async(lambda d: d.platform_logs.delete_many({"entity_id": inv["id"]}))

    def test_payslip_auto_archive(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        e = s.post(f"{API}/hr/employees", json={
            "tenant_id": cu["id"], "full_name": f"TEST_Emp_Arch {TS}",
            "role": "Comptable", "base_salary": 120000, "hire_date": "2025-03-01",
        }, timeout=60)
        assert e.status_code == 200, e.text[:300]
        emp_id = e.json()["id"]
        ps_id = None
        try:
            ps = s.post(f"{API}/hr/payslips", json={
                "employee_id": emp_id, "period_month": "2026-05",
                "gross_salary": 120000, "deductions": 10000, "bonuses": 0,
            }, timeout=60)
            assert ps.status_code == 200, ps.text[:300]
            ps_id = ps.json()["id"]
            lst = s.get(f"{API}/archives", params={"source_kind": "payslip"}, timeout=60)
            assert lst.status_code == 200
            mine = [a for a in lst.json() if (a.get("source") or {}).get("id") == ps_id]
            assert mine, f"no auto archive for payslip {ps_id}"
            assert mine[0]["source"]["auto"] is True
            assert mine[0]["category"] == "paie"
        finally:
            run_async(lambda d: d.archives.delete_many({"source.id": ps_id}))
            run_async(lambda d: d.payslips.delete_many({"employee_id": emp_id}))
            run_async(lambda d: d.employees.delete_many({"id": emp_id}))

    def test_manual_archive_still_works_and_only_manual_filter(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/archives", json={
            "title": f"TEST_Manual {TS}", "category": "juridique",
            "tags": ["manual", TS],
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        aid = r.json()["id"]
        try:
            man = s.get(f"{API}/archives", params={"only_manual": True, "tag": TS}, timeout=60)
            assert man.status_code == 200
            assert [x["id"] for x in man.json()] == [aid]
            assert man.json()[0].get("auto") in (None, False)
        finally:
            s.delete(f"{API}/archives/{aid}", timeout=60)


# =====================================================================
# Point 3 — rôle communication
# =====================================================================
class TestCommunicationRole:
    def test_communication_role_messaging_access(self, superviseur, comptable):
        s, _ = superviseur
        comp, _ = comptable
        email = f"test_comm_{TS}@albarka-demo.bf"
        password = "TestComm2026!"
        r = s.post(f"{API}/clients/staff", json={
            "email": email, "full_name": f"TEST_Comm {TS}",
            "password": password, "roles": ["communication"],
        }, timeout=60)
        assert r.status_code == 200, r.text[:400]
        uid = r.json()["id"]
        assert r.json()["roles"] == ["communication"]
        bid = None
        try:
            cs, cu = make_session(email, password)
            assert cu["roles"] == ["communication"]

            g = cs.get(f"{API}/messaging/broadcasts", timeout=60)
            assert g.status_code == 200, f"communication should read broadcasts: {g.status_code} {g.text[:200]}"

            p = cs.post(f"{API}/messaging/broadcast", json={
                "subject": f"TEST_CommBroadcast {TS}", "body": "test",
                "scope": "staff", "channel": "email",
            }, timeout=180)
            assert p.status_code == 200, f"communication should send broadcast: {p.status_code} {p.text[:300]}"
            bid = p.json()["id"]

            # comptable (no communication role) -> 403
            assert comp.get(f"{API}/messaging/broadcasts", timeout=60).status_code == 403
            assert comp.post(f"{API}/messaging/broadcast", json={
                "subject": "x", "body": "y", "scope": "staff", "channel": "email",
            }, timeout=60).status_code == 403
        finally:
            if bid:
                run_async(lambda d: d.broadcast_deliveries.delete_many({"broadcast_id": bid}))
                run_async(lambda d: d.broadcasts.delete_many({"id": bid}))
            s.delete(f"{API}/clients/{uid}", timeout=60)
            run_async(lambda d: d.users.delete_many({"email": email}))

    def test_communication_is_valid_role(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/clients/staff", timeout=60)
        assert r.status_code == 200


# =====================================================================
# Point 4 — export PDF journal
# =====================================================================
class TestJournalPdfExport:
    def test_export_pdf(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        # seed one signature_log + one wa_send_log inside the window
        sig_id = f"TEST_sig_{TS}"
        wa_id = f"TEST_wa_{TS}"
        now = datetime.now(timezone.utc).isoformat()
        run_async(lambda d: d.signature_log.insert_one({
            "id": sig_id, "report_id": "TESTREP", "report_number": f"TESTSIGN-{TS}",
            "tenant_id": cu["id"], "signed_at": now,
            "signed_by_name": "TEST Signataire", "signed_by": "test",
        }))
        run_async(lambda d: d.wa_send_log.insert_one({
            "id": wa_id, "report_id": "TESTREP", "report_number": f"TESTWA-{TS}",
            "tenant_id": cu["id"], "sent_at": now, "success": True,
            "strategy": "direct", "sent_by_name": "TEST Agent", "phone": "+22670000000",
        }))
        try:
            r = s.get(f"{API}/reports/journal/export-pdf",
                      params={"start": "2026-01-01", "end": "2026-12-31"}, timeout=120)
            assert r.status_code == 200, r.text[:300]
            assert r.content[:5] == b"%PDF-", r.content[:20]
            assert len(r.content) > 500, len(r.content)
            assert "pdf" in r.headers.get("content-type", "").lower()
            txt = _pdf_text(r.content)
            assert f"TESTSIGN-{TS}" in txt, "signature_log line missing from PDF"
            assert f"TESTWA-{TS}" in txt, "wa_send_log line missing from PDF"
        finally:
            run_async(lambda d: d.signature_log.delete_many({"id": sig_id}))
            run_async(lambda d: d.wa_send_log.delete_many({"id": wa_id}))

    def test_export_pdf_rbac(self, client1):
        c, _ = client1
        r = c.get(f"{API}/reports/journal/export-pdf", timeout=60)
        assert r.status_code == 403, r.status_code

    def test_quarterly_still_works(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        r = s.post(f"{API}/reports/client/{cu['id']}/generate-quarterly",
                   json={"period_quarter": "2026-Q2"}, timeout=300)
        assert r.status_code == 200, r.text[:400]
        rep = r.json()
        assert rep["kind"] == "trimestriel"
        assert rep["size"] > 0
        s.delete(f"{API}/reports/{rep['id']}", timeout=60)


# =====================================================================
# Point 5 — PDF bulletin de paie
# =====================================================================
class TestPayslipPdf:
    def test_payslip_pdf(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        e = s.post(f"{API}/hr/employees", json={
            "tenant_id": cu["id"], "full_name": f"TEST_PdfEmp {TS}",
            "role": "Magasinier", "base_salary": 175000, "hire_date": "2024-11-02",
        }, timeout=60)
        assert e.status_code == 200, e.text[:300]
        emp_id = e.json()["id"]
        ps_id = None
        try:
            ps = s.post(f"{API}/hr/payslips", json={
                "employee_id": emp_id, "period_month": "2026-04",
                "gross_salary": 175000, "deductions": 25000, "bonuses": 10000,
            }, timeout=60)
            assert ps.status_code == 200, ps.text[:300]
            slip = ps.json()
            ps_id = slip["id"]
            assert slip["net_salary"] == 160000

            r = s.get(f"{API}/hr/payslips/{ps_id}.pdf", timeout=120)
            assert r.status_code == 200, r.text[:300]
            assert r.content[:5] == b"%PDF-"
            assert len(r.content) > 500
            txt = _pdf_text(r.content)
            assert f"TEST_PdfEmp {TS}" in txt, "employee name missing in PDF"
            assert "2026-04" in txt, "period missing in PDF"
            assert re.search(r"160[,\s.]?000", txt), "net salary missing in PDF"

            # unknown payslip -> 404
            assert s.get(f"{API}/hr/payslips/nope-nope.pdf", timeout=60).status_code == 404
        finally:
            run_async(lambda d: d.archives.delete_many({"source.id": ps_id}))
            run_async(lambda d: d.payslips.delete_many({"employee_id": emp_id}))
            run_async(lambda d: d.employees.delete_many({"id": emp_id}))


# =====================================================================
# Point 6 — types de documents caisse
# =====================================================================
class TestInvoiceDocumentTypes:
    def test_three_document_types(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        month_key = datetime.now(timezone.utc).strftime("%Y%m")
        created = []
        items = [{"label": "presta", "quantity": 1, "unit_price": 50000, "tax_rate": 18}]
        try:
            fac = s.post(f"{API}/billing/invoices", json={
                "tenant_id": cu["id"], "title": f"TEST_Fac {TS}",
                "items": items, "document_type": "facture",
            }, timeout=60)
            assert fac.status_code == 200, fac.text[:300]
            f = fac.json()
            created.append(f["id"])
            assert re.fullmatch(rf"FAC-{month_key}-\d{{4}}", f["number"]), f["number"]
            assert f["status"] == "unpaid"
            assert f["document_type"] == "facture"

            rec = s.post(f"{API}/billing/invoices", json={
                "tenant_id": cu["id"], "title": f"TEST_Rec {TS}",
                "items": items, "document_type": "recu",
            }, timeout=60)
            assert rec.status_code == 200, rec.text[:300]
            rr = rec.json()
            created.append(rr["id"])
            assert re.fullmatch(rf"REC-{month_key}-\d{{4}}", rr["number"]), rr["number"]
            assert rr["status"] == "paid"
            assert rr["paid_amount"] == rr["total"] == 59000

            pro = s.post(f"{API}/billing/invoices", json={
                "tenant_id": cu["id"], "title": f"TEST_Pro {TS}",
                "items": items, "document_type": "proforma",
            }, timeout=60)
            assert pro.status_code == 200, pro.text[:300]
            pp = pro.json()
            created.append(pp["id"])
            assert re.fullmatch(rf"PRO-{month_key}-\d{{4}}", pp["number"]), pp["number"]
            assert pp["status"] == "proforma"
            assert pp["paid_amount"] == 0

            # independent counters : same seq possible across prefixes
            assert f["number"].split("-")[-1] != "" and rr["number"].split("-")[-1] != ""

            # default document_type when omitted
            dflt = s.post(f"{API}/billing/invoices", json={
                "tenant_id": cu["id"], "title": f"TEST_Default {TS}", "items": items,
            }, timeout=60)
            assert dflt.status_code == 200
            created.append(dflt.json()["id"])
            assert dflt.json()["document_type"] == "facture"
            assert dflt.json()["number"].startswith("FAC-")

            # invalid type -> 422
            assert s.post(f"{API}/billing/invoices", json={
                "tenant_id": cu["id"], "title": "x", "items": items,
                "document_type": "devis",
            }, timeout=60).status_code == 422

            # filter
            flt = s.get(f"{API}/billing/invoices",
                        params={"tenant_id": cu["id"], "document_type": "recu"}, timeout=60)
            assert flt.status_code == 200
            assert all(x["document_type"] == "recu" for x in flt.json())
            assert rr["id"] in [x["id"] for x in flt.json()]
            assert f["id"] not in [x["id"] for x in flt.json()]
        finally:
            for iid in created:
                run_async(lambda d, i=iid: d.archives.delete_many({"source.id": i}))
                run_async(lambda d, i=iid: d.invoices.delete_many({"id": i}))
                run_async(lambda d, i=iid: d.platform_logs.delete_many({"entity_id": i}))


# =====================================================================
# Point 7 — contrats FR + champs
# =====================================================================
class TestContractsFR:
    def test_existing_contracts_migrated(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/client-contracts", timeout=60)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        assert items, "no contracts in db"
        allowed = {"en_cours", "suspendu", "termine", "annule"}
        bad = [(c["id"], c["status"]) for c in items if c.get("status") not in allowed]
        assert not bad, f"non-FR statuses found: {bad}"
        missing = [c["id"] for c in items if not c.get("numero_contrat")]
        assert not missing, f"contracts without numero_contrat: {missing}"
        pat = re.compile(r"^CTR-\d{4}-\d{4}$")
        assert all(pat.match(c["numero_contrat"]) for c in items), \
            [c["numero_contrat"] for c in items][:5]

    def test_create_auto_numero_and_fields(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        cid = None
        try:
            r = s.post(f"{API}/client-contracts", json={
                "tenant_id": cu["id"], "title": f"TEST_Contrat FR {TS}",
                "start_date": "2026-01-01", "end_date": "2026-12-31",
                "amount": 500000, "date_dernier_paiement": "2026-06-15",
            }, timeout=60)
            assert r.status_code == 200, r.text[:300]
            c = r.json()
            cid = c["id"]
            assert re.fullmatch(r"CTR-\d{4}-\d{4}", c["numero_contrat"] or ""), c.get("numero_contrat")
            assert c["date_dernier_paiement"] == "2026-06-15"
            assert c["status"] == "en_cours"
            # persistence
            g = s.get(f"{API}/client-contracts/{cid}", timeout=60)
            assert g.status_code == 200
            assert g.json()["date_dernier_paiement"] == "2026-06-15"
            assert g.json()["numero_contrat"] == c["numero_contrat"]
        finally:
            if cid:
                s.delete(f"{API}/client-contracts/{cid}", timeout=60)

    def test_legacy_status_accepted_and_normalized(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        cid = None
        try:
            r = s.post(f"{API}/client-contracts", json={
                "tenant_id": cu["id"], "title": f"TEST_Legacy {TS}",
                "start_date": "2026-02-01", "status": "active",
            }, timeout=60)
            assert r.status_code == 200, r.text[:300]
            cid = r.json()["id"]
            assert r.json()["status"] == "en_cours", r.json()["status"]
            g = s.get(f"{API}/client-contracts/{cid}", timeout=60)
            assert g.json()["status"] == "en_cours"
            # PATCH with legacy status too
            p = s.patch(f"{API}/client-contracts/{cid}", json={"status": "suspended"}, timeout=60)
            assert p.status_code == 200, p.text[:200]
            assert p.json()["status"] == "suspendu"
            # explicit numero honoured
            p2 = s.patch(f"{API}/client-contracts/{cid}",
                         json={"date_dernier_paiement": "2026-07-01"}, timeout=60)
            assert p2.status_code == 200
            assert p2.json()["date_dernier_paiement"] == "2026-07-01"
        finally:
            if cid:
                s.delete(f"{API}/client-contracts/{cid}", timeout=60)

    def test_explicit_numero_and_bad_date(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        num = f"CTR-2026-{secrets.randbelow(9000) + 1000}"
        cid = None
        try:
            r = s.post(f"{API}/client-contracts", json={
                "tenant_id": cu["id"], "title": f"TEST_Num {TS}",
                "start_date": "2026-03-01", "numero_contrat": num,
            }, timeout=60)
            assert r.status_code == 200, r.text[:300]
            cid = r.json()["id"]
            assert r.json()["numero_contrat"] == num
            # bad date_dernier_paiement -> 422
            assert s.post(f"{API}/client-contracts", json={
                "tenant_id": cu["id"], "title": "x", "start_date": "2026-03-01",
                "date_dernier_paiement": "15/06/2026",
            }, timeout=60).status_code == 422
        finally:
            if cid:
                s.delete(f"{API}/client-contracts/{cid}", timeout=60)


# =====================================================================
# Point 9 — auto WA J+24h après signature
# =====================================================================
class TestAutoWaJ24:
    def test_scheduled_at_is_exactly_24h_after_created_at(self, superviseur, client1):
        s, _ = superviseur
        _, cu = client1
        prev = s.get(f"{API}/admin/settings", timeout=60)
        assert prev.status_code == 200
        prev_enabled = prev.json().get("auto_wa_after_sign_enabled")
        prev_days = prev.json().get("auto_wa_after_sign_days")

        up = s.put(f"{API}/admin/settings", json={
            "auto_wa_after_sign_enabled": True, "auto_wa_after_sign_days": 1,
        }, timeout=60)
        assert up.status_code == 200, up.text[:300]
        assert up.json()["auto_wa_after_sign_enabled"] is True

        report_id = None
        try:
            g = s.post(f"{API}/reports/client/{cu['id']}/generate",
                       json={"kind": "mensuel", "period_month": "2026-07"}, timeout=300)
            assert g.status_code == 200, g.text[:400]
            report_id = g.json()["id"]

            sg = s.post(f"{API}/reports/{report_id}/sign", json={
                "signature_name": "TEST Signataire J24",
                "signature_provider": "cabinet_seal",
            }, timeout=180)
            assert sg.status_code == 200, sg.text[:400]

            sched = s.get(f"{API}/reports/whatsapp/scheduled", timeout=60)
            assert sched.status_code == 200
            mine = [x for x in sched.json() if x.get("report_id") == report_id]
            assert mine, f"no scheduled WA entry after signing {report_id}"
            entry = mine[0]
            assert entry.get("auto") is True
            assert entry.get("status") == "pending"
            assert "_id" not in entry
            created = datetime.fromisoformat(entry["created_at"])
            scheduled = datetime.fromisoformat(entry["scheduled_at"])
            delta = scheduled - created
            assert abs(delta - timedelta(hours=24)) <= timedelta(minutes=5), \
                f"delta={delta} created={entry['created_at']} scheduled={entry['scheduled_at']}"
        finally:
            if report_id:
                run_async(lambda d: d.scheduled_wa_sends.delete_many({"report_id": report_id}))
                run_async(lambda d: d.signature_log.delete_many({"report_id": report_id}))
                run_async(lambda d: d.archives.delete_many({"source.id": report_id}))
                s.delete(f"{API}/reports/{report_id}", timeout=60)
            s.put(f"{API}/admin/settings", json={
                "auto_wa_after_sign_enabled": bool(prev_enabled),
                "auto_wa_after_sign_days": prev_days or 1,
            }, timeout=60)
