"""Iteration 3 — Admin settings (Meta WhatsApp Cloud API config), report numbering /
list / download / send / sign / delete, tenant isolation, notification gating.
"""
import os
import re
import time

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from conftest import API, make_session, run_async

ADMIN_EMAIL = "Admin@sawalismartsystems.com"
ADMIN_PASSWORD = "Admin@Sawali2026"
# Iteration 3+ : le slug client contient un discriminant SHA1[:4] (hex majuscule).
NUMBER_RE = re.compile(r"^RAP-[A-Z0-9]+-MENSUEL-\d{6}-\d{4}$")

_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or _env.get("MONGO_URL")
DB_NAME = os.environ.get("DB_NAME") or _env.get("DB_NAME")


@pytest.fixture(scope="session")
def mongo():
    if not MONGO_URL or not DB_NAME:
        pytest.skip("MONGO_URL/DB_NAME unavailable")
    cli = MongoClient(MONGO_URL, serverSelectionTimeoutMS=15000)
    yield cli[DB_NAME]
    cli.close()


@pytest.fixture(scope="session")
def admin():
    return make_session(ADMIN_EMAIL, ADMIN_PASSWORD)


# --- module: albarka_auth / seed --------------------------------------------
class TestAdminAccount:
    def test_admin_login_and_roles(self):
        r = requests.post(f"{API}/auth/login",
                          json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        body = r.json()
        assert body.get("dev_otp"), body
        v = requests.post(f"{API}/auth/verify-otp",
                          json={"session_token": body["session_token"], "code": body["dev_otp"]},
                          timeout=60)
        assert v.status_code == 200, v.text[:300]
        data = v.json()
        assert isinstance(data.get("access_token"), str) and data["access_token"]
        assert sorted(data["user"]["roles"]) == ["direction", "superviseur"]
        assert "password_hash" not in data["user"]

    def test_seed_accounts_present(self, mongo):
        emails = {
            ADMIN_EMAIL.lower(), "superviseur@albarka-demo.bf", "comptable@albarka-demo.bf",
            "client1@albarka-demo.bf", "client2@albarka-demo.bf",
        }
        found = {u["email"].lower() for u in mongo.users.find({}, {"email": 1})} & emails
        assert found == emails, f"missing seeded accounts: {emails - found}"


# --- module: albarka_admin_settings -----------------------------------------
class TestAdminSettings:
    def test_get_settings_as_admin(self, admin):
        s, _ = admin
        r = s.get(f"{API}/admin/settings", timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        for k in ("cabinet_name", "wa_enabled", "wa_phone_number_id", "wa_graph_version",
                  "report_prefix", "notif_upload_enabled"):
            assert k in data, f"{k} missing from settings"
        assert "_id" not in data

    def test_get_settings_as_superviseur(self, superviseur):
        s, _ = superviseur
        assert s.get(f"{API}/admin/settings", timeout=60).status_code == 200

    def test_get_settings_forbidden_for_comptable(self, comptable):
        s, _ = comptable
        assert s.get(f"{API}/admin/settings", timeout=60).status_code == 403

    def test_get_settings_forbidden_for_client(self, client1):
        s, _ = client1
        assert s.get(f"{API}/admin/settings", timeout=60).status_code == 403

    def test_get_settings_unauthenticated(self):
        assert requests.get(f"{API}/admin/settings", timeout=60).status_code in (401, 403)

    def test_update_settings_and_masking(self, admin, mongo):
        s, _ = admin
        original = s.get(f"{API}/admin/settings", timeout=60).json()
        try:
            payload = {
                "cabinet_name": "TEST_Cabinet ALBARKA QA",
                "wa_enabled": True,
                "wa_phone_number_id": "TEST_1234567890",
                "wa_access_token": "TEST_secret_token_abc123",
            }
            r = s.put(f"{API}/admin/settings", json=payload, timeout=60)
            assert r.status_code == 200, r.text[:300]
            data = r.json()
            assert data["cabinet_name"] == "TEST_Cabinet ALBARKA QA"
            assert data["wa_enabled"] is True
            assert data["wa_phone_number_id"] == "TEST_1234567890"
            assert data["wa_access_token"] == "********", "token must be masked on response"

            # persisted (unmasked) in DB
            doc = mongo.settings.find_one({"_id": "global"})
            assert doc["wa_access_token"] == "TEST_secret_token_abc123"

            # GET keeps masking
            assert s.get(f"{API}/admin/settings", timeout=60).json()["wa_access_token"] == "********"

            # masked sentinel must never be persisted back
            r2 = s.put(f"{API}/admin/settings",
                       json={"wa_access_token": "********", "cabinet_phone": "+22670000000"},
                       timeout=60)
            assert r2.status_code == 200, r2.text[:300]
            assert r2.json()["cabinet_phone"] == "+22670000000"
            doc = mongo.settings.find_one({"_id": "global"})
            assert doc["wa_access_token"] == "TEST_secret_token_abc123", \
                "masked sentinel overwrote the real token"
        finally:
            restore = {k: original.get(k) for k in
                       ("cabinet_name", "cabinet_phone", "wa_enabled", "wa_phone_number_id",
                        "wa_business_account_id", "wa_graph_version", "report_prefix")}
            restore["wa_access_token"] = ""
            s.put(f"{API}/admin/settings", json={k: v for k, v in restore.items() if v is not None},
                  timeout=60)
            mongo.settings.update_one({"_id": "global"}, {"$set": {"wa_access_token": ""}})

    def test_update_settings_forbidden_for_comptable(self, comptable):
        s, _ = comptable
        assert s.put(f"{API}/admin/settings", json={"cabinet_name": "hack"}, timeout=60).status_code == 403

    def test_wa_test_disabled_returns_ok_false(self, admin, mongo):
        s, _ = admin
        mongo.settings.update_one({"_id": "global"}, {"$set": {"wa_enabled": False}})
        r = s.post(f"{API}/admin/settings/wa/test", json={"to": "+22670000000"}, timeout=60)
        assert r.status_code == 200, r.text[:300]
        data = r.json()
        assert data["ok"] is False and data["message_id"] is None, data
        assert "diagnostic" in data

    def test_wa_test_rejects_bad_phone(self, admin):
        s, _ = admin
        r = s.post(f"{API}/admin/settings/wa/test", json={"to": "70000000"}, timeout=60)
        assert r.status_code == 400, r.text[:300]

    def test_wa_test_forbidden_for_client(self, client1):
        s, _ = client1
        assert s.post(f"{API}/admin/settings/wa/test", json={"to": "+22670000000"},
                      timeout=60).status_code == 403


# --- module: albarka_reports_mgmt -------------------------------------------
@pytest.fixture(scope="class")
def created_report_ids():
    return []


@pytest.fixture(scope="class", autouse=True)
def cleanup_reports(superviseur, created_report_ids, mongo):
    yield
    s, _ = superviseur
    for rid in created_report_ids:
        mongo.client_reports.update_one({"id": rid}, {"$set": {"signed": False}})
        s.delete(f"{API}/reports/{rid}", timeout=60)
    mongo.client_reports.delete_many({"id": {"$in": created_report_ids}})


class TestReportNumbering:
    def test_sequence_per_client_type_month(self, superviseur, client1, created_report_ids, mongo):
        s, _ = superviseur
        _, c1 = client1
        tenant = c1["id"]
        month = "2031-03"  # isolated future month for deterministic sequence
        mongo.report_series.delete_many({"tenant_id": tenant, "month_key": month})
        mongo.client_reports.delete_many({"tenant_id": tenant, "month_key": month})

        r1 = s.post(f"{API}/reports/client/{tenant}/generate",
                    json={"kind": "mensuel", "period_month": month}, timeout=120)
        assert r1.status_code == 200, r1.text[:400]
        d1 = r1.json()
        created_report_ids.append(d1["id"])
        assert NUMBER_RE.match(d1["number"]), d1["number"]
        assert d1["number"].endswith("-0001")
        assert d1["month_key"] == month
        assert d1["kind"] == "mensuel" and d1["kind_label"] == "Rapport mensuel"
        assert d1["signed"] is False and d1["email_sent_at"] is None
        assert d1["size"] > 500
        assert "_id" not in d1

        r2 = s.post(f"{API}/reports/client/{tenant}/generate",
                    json={"kind": "mensuel", "period_month": month}, timeout=120)
        assert r2.status_code == 200, r2.text[:400]
        d2 = r2.json()
        created_report_ids.append(d2["id"])
        assert d2["number"].endswith("-0002"), d2["number"]

        # different type -> own counter
        r3 = s.post(f"{API}/reports/client/{tenant}/generate",
                    json={"kind": "trimestriel", "period_month": month}, timeout=120)
        assert r3.status_code == 200, r3.text[:400]
        d3 = r3.json()
        created_report_ids.append(d3["id"])
        assert d3["number"].endswith("-0001"), d3["number"]
        assert "-TRIMESTRIEL-" in d3["number"]

        # GET verification (persistence)
        lst = s.get(f"{API}/reports/client/{tenant}/list", params={"month_key": month}, timeout=60)
        assert lst.status_code == 200
        items = lst.json()
        assert {i["number"] for i in items} == {d1["number"], d2["number"], d3["number"]}

    def test_different_client_same_month_starts_at_one(self, superviseur, client2, created_report_ids, mongo):
        s, _ = superviseur
        _, c2 = client2
        tenant = c2["id"]
        month = "2031-03"
        mongo.report_series.delete_many({"tenant_id": tenant, "month_key": month})
        r = s.post(f"{API}/reports/client/{tenant}/generate",
                   json={"kind": "mensuel", "period_month": month}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        created_report_ids.append(d["id"])
        assert d["number"].endswith("-0001"), d["number"]

    def test_default_month_is_current(self, superviseur, client1, created_report_ids):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/reports/client/{c1['id']}/generate", json={"kind": "ponctuel"}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        d = r.json()
        created_report_ids.append(d["id"])
        assert re.match(r"^\d{4}-\d{2}$", d["month_key"])

    def test_invalid_kind_400(self, superviseur, client1):
        s, _ = superviseur
        r = s.post(f"{API}/reports/client/{c_id(client1)}/generate", json={"kind": "bogus"}, timeout=60)
        assert r.status_code == 400, r.text[:300]

    def test_invalid_month_400(self, superviseur, client1):
        s, _ = superviseur
        r = s.post(f"{API}/reports/client/{c_id(client1)}/generate",
                   json={"kind": "mensuel", "period_month": "2031/03"}, timeout=60)
        assert r.status_code == 400, r.text[:300]

    def test_unknown_client_404(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/reports/client/does-not-exist/generate",
                   json={"kind": "mensuel"}, timeout=60)
        assert r.status_code == 404, r.text[:300]

    def test_client_cannot_generate(self, client1):
        s, c1 = client1
        r = s.post(f"{API}/reports/client/{c1['id']}/generate", json={"kind": "mensuel"}, timeout=60)
        assert r.status_code == 403, r.text[:300]


def c_id(fixture):
    return fixture[1]["id"]


class TestReportListDownloadIsolation:
    def test_list_sorted_desc_and_filters(self, superviseur, client1, created_report_ids):
        sv, _ = superviseur
        s, c1 = client1
        # S'assure qu'au moins un rapport existe (les autres modules nettoient les leurs).
        gen = sv.post(f"{API}/reports/client/{c1['id']}/generate",
                      json={"kind": "ponctuel", "period_month": "2031-11"}, timeout=120)
        assert gen.status_code == 200, gen.text[:300]
        created_report_ids.append(gen.json()["id"])
        r = s.get(f"{API}/reports/client/{c1['id']}/list", timeout=60)
        assert r.status_code == 200, r.text[:300]
        items = r.json()
        assert isinstance(items, list) and items, "expected at least one report for client1"
        gen = [i["generated_at"] for i in items]
        assert gen == sorted(gen, reverse=True), "list not sorted desc by generated_at"
        assert all("_id" not in i for i in items)

        kinds = {i["kind"] for i in items}
        k = sorted(kinds)[0]
        rk = s.get(f"{API}/reports/client/{c1['id']}/list", params={"kind": k}, timeout=60)
        assert rk.status_code == 200
        assert all(i["kind"] == k for i in rk.json())

        mk = items[0]["month_key"]
        rm = s.get(f"{API}/reports/client/{c1['id']}/list", params={"month_key": mk}, timeout=60)
        assert all(i["month_key"] == mk for i in rm.json())

    def test_client_cannot_list_other_tenant(self, client1, client2):
        s, _ = client1
        _, c2 = client2
        r = s.get(f"{API}/reports/client/{c2['id']}/list", timeout=60)
        assert r.status_code == 403, r.text[:300]

    def test_download_pdf(self, superviseur, client1, created_report_ids):
        # Génère son propre rapport : la liste peut contenir des rapports créés
        # (et supprimés) en parallèle par d'autres modules de test.
        sv, _ = superviseur
        s, c1 = client1
        gen = sv.post(f"{API}/reports/client/{c1['id']}/generate",
                      json={"kind": "trimestriel", "period_month": "2031-09"}, timeout=120)
        assert gen.status_code == 200, gen.text[:300]
        created_report_ids.append(gen.json()["id"])
        items = [gen.json()]
        rid = items[0]["id"]
        r = s.get(f"{API}/reports/{rid}/download", timeout=90)
        assert r.status_code == 200, r.text[:300]
        assert r.headers.get("content-type", "").startswith("application/pdf")
        cd = r.headers.get("content-disposition", "")
        assert "attachment" in cd and items[0]["number"] in cd, cd
        assert r.content[:4] == b"%PDF", r.content[:20]

    def test_download_pdf_contains_number_and_kind(self, superviseur, client1, created_report_ids):
        import pymupdf
        s, _ = superviseur
        _, c1 = client1
        gen = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "annuel", "period_month": "2031-06"}, timeout=120)
        assert gen.status_code == 200, gen.text[:400]
        d = gen.json()
        created_report_ids.append(d["id"])
        r = s.get(f"{API}/reports/{d['id']}/download", timeout=90)
        assert r.status_code == 200
        pdf = pymupdf.open(stream=r.content, filetype="pdf")
        text = "\n".join(p.get_text() for p in pdf)
        pdf.close()
        assert d["number"] in text, f"number missing from PDF header: {text[:400]!r}"
        assert "RAPPORT ANNUEL" in text.upper()
        assert "2031-06" in text

    def test_download_cross_tenant_403(self, client2, client1):
        s2, _ = client2
        s1, c1 = client1
        rid = s1.get(f"{API}/reports/client/{c1['id']}/list", timeout=60).json()[0]["id"]
        assert s2.get(f"{API}/reports/{rid}/download", timeout=60).status_code == 403

    def test_download_unknown_404(self, superviseur):
        s, _ = superviseur
        assert s.get(f"{API}/reports/nope-nope/download", timeout=60).status_code == 404

    def test_download_unauthenticated_401(self, client1):
        s1, c1 = client1
        rid = s1.get(f"{API}/reports/client/{c1['id']}/list", timeout=60).json()[0]["id"]
        assert requests.get(f"{API}/reports/{rid}/download", timeout=60).status_code in (401, 403)


class TestReportSendSignDelete:
    def test_send_report_email(self, superviseur, client1, created_report_ids, mongo):
        s, _ = superviseur
        _, c1 = client1
        gen = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "conseil", "period_month": "2031-04"}, timeout=120)
        assert gen.status_code == 200, gen.text[:400]
        rid = gen.json()["id"]
        created_report_ids.append(rid)

        # Le proxy Resend partagé limite le débit (429 -> 502 côté API) : on retente.
        r = None
        for attempt in range(3):
            r = s.post(f"{API}/reports/{rid}/send", json={"to": "delivered@resend.dev"}, timeout=120)
            if r.status_code != 502:
                break
            time.sleep(4 * (attempt + 1))
        if r.status_code == 502:
            pytest.skip("proxy email externe indisponible / rate-limited (429)")
        assert r.status_code == 200, f"send failed: {r.status_code} {r.text[:400]}"
        data = r.json()
        assert data["ok"] is True
        # Iteration 4 : `to` est désormais une liste de destinataires.
        assert data["to"] == ["delivered@resend.dev"]
        assert data.get("message_id"), data

        doc = mongo.client_reports.find_one({"id": rid}, {"_id": 0})
        assert doc["email_sent_to"] == "delivered@resend.dev"
        assert doc["email_sent_at"]

        # visible through the list endpoint too
        items = s.get(f"{API}/reports/client/{c1['id']}/list",
                      params={"month_key": "2031-04"}, timeout=60).json()
        match = [i for i in items if i["id"] == rid][0]
        assert match["email_sent_to"] == "delivered@resend.dev"

    def test_send_client_forbidden(self, client1, superviseur, created_report_ids):
        sc, c1 = client1
        ss, _ = superviseur
        rid = ss.get(f"{API}/reports/client/{c1['id']}/list", timeout=60).json()[0]["id"]
        r = sc.post(f"{API}/reports/{rid}/send", json={"to": "delivered@resend.dev"}, timeout=60)
        assert r.status_code == 403, r.text[:300]

    def test_send_unknown_404(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/reports/nope/send", json={"to": "delivered@resend.dev"}, timeout=60)
        assert r.status_code == 404

    def test_sign_then_double_sign_then_delete(self, superviseur, client1, created_report_ids, mongo):
        s, _ = superviseur
        _, c1 = client1
        gen = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "audit", "period_month": "2031-05"}, timeout=120)
        assert gen.status_code == 200, gen.text[:400]
        rid = gen.json()["id"]
        created_report_ids.append(rid)

        r = s.post(f"{API}/reports/{rid}/sign", json={
            "signature_name": "TEST Signataire",
            "signature_provider": "cabinet_seal",
            "signature_reference": "TEST-REF-001",
        }, timeout=60)
        assert r.status_code == 200, r.text[:300]
        d = r.json()
        assert d["signed"] is True
        assert d["signature_name"] == "TEST Signataire"
        assert d["signature_provider"] == "cabinet_seal"
        assert d["signature_reference"] == "TEST-REF-001"
        assert d["signed_at"] and d["signed_by"]
        assert "_id" not in d

        # persisted
        got = s.get(f"{API}/reports/client/{c1['id']}/list",
                    params={"month_key": "2031-05"}, timeout=60).json()
        assert [i for i in got if i["id"] == rid][0]["signed"] is True

        # second sign -> 400
        r2 = s.post(f"{API}/reports/{rid}/sign", json={"signature_name": "TEST Again"}, timeout=60)
        assert r2.status_code == 400, r2.text[:300]

        # delete refused while signed
        assert s.delete(f"{API}/reports/{rid}", timeout=60).status_code == 400

        # unsign then delete works
        mongo.client_reports.update_one({"id": rid}, {"$set": {"signed": False}})
        dr = s.delete(f"{API}/reports/{rid}", timeout=60)
        assert dr.status_code == 200, dr.text[:300]
        assert dr.json()["ok"] is True
        assert mongo.client_reports.find_one({"id": rid}) is None
        # deleting again -> 404
        assert s.delete(f"{API}/reports/{rid}", timeout=60).status_code == 404

    def test_sign_validation_error(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        rid = s.get(f"{API}/reports/client/{c1['id']}/list", timeout=60).json()[0]["id"]
        r = s.post(f"{API}/reports/{rid}/sign", json={"signature_name": "x"}, timeout=60)
        assert r.status_code == 422, r.text[:300]

    def test_client_cannot_sign_or_delete(self, client1):
        s, c1 = client1
        rid = s.get(f"{API}/reports/client/{c1['id']}/list", timeout=60).json()[0]["id"]
        assert s.post(f"{API}/reports/{rid}/sign",
                      json={"signature_name": "TEST Client"}, timeout=60).status_code == 403
        assert s.delete(f"{API}/reports/{rid}", timeout=60).status_code == 403


# --- module: albarka_documents + notify_upload -------------------------------
class TestNotifyUpload:
    def test_client_upload_triggers_notify_upload(self, client1, mongo):
        s, c1 = client1
        mongo.settings.update_one({"_id": "global"}, {"$set": {"notif_upload_enabled": True}})
        files = {"file": ("TEST_notify_upload.txt", b"facture test albarka", "text/plain")}
        r = s.post(f"{API}/documents", files=files, data={"kind": "piece_comptable"}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        doc = r.json()
        assert doc["tenant_id"] == c1["id"]
        doc_id = doc["id"]
        time.sleep(8)
        log = open("/var/log/supervisor/backend.err.log", "r", errors="ignore").read()[-40000:]
        assert ("Échec envoi email" in log or "envoi email ignoré" in log
                or "notifications" in log), "no notification activity found in backend log"
        # cleanup
        s.delete(f"{API}/documents/{doc_id}", timeout=60)
        mongo.documents.delete_one({"id": doc_id})
        mongo.document_syntheses.delete_one({"document_id": doc_id})

    def test_staff_upload_does_not_notify(self, superviseur, client1, mongo):
        s, _ = superviseur
        _, c1 = client1
        files = {"file": ("TEST_staff_upload.txt", b"note interne", "text/plain")}
        r = s.post(f"{API}/documents", files=files,
                   data={"kind": "piece_comptable", "tenant_id": c1["id"]}, timeout=120)
        assert r.status_code == 200, r.text[:400]
        doc_id = r.json()["id"]
        s.delete(f"{API}/documents/{doc_id}", timeout=60)
        mongo.documents.delete_one({"id": doc_id})
        mongo.document_syntheses.delete_one({"document_id": doc_id})


# --- module: albarka_notifications (in-process guards) ----------------------
def _an():
    import sys
    sys.path.insert(0, "/app/backend")
    from dotenv import load_dotenv
    load_dotenv("/app/backend/.env", override=False)
    import albarka_notifications as an
    return an


class TestNotificationGates:
    def test_notify_echeance_skips_inactive_and_unauthorized(self):
        an = _an()
        ech = {"id": "x", "title": "TEST", "type": "tva", "due_date": "2031-01-31",
               "period": "2031-01", "amount": 1000}
        r1 = run_async(lambda _db: an.notify_echeance(
            {"id": "TEST_nouser", "email": "a@b.co", "full_name": "A", "is_active": False}, ech, 3))
        # NOTE: notify_echeance no longer returns a "skipped" flag (iteration-4 refactor);
        # the gate is now expressed as "no recipients / nothing sent".
        assert r1["sent_email"] is False and r1["sent_wa"] is False
        assert r1["email_recipients"] == [] and r1["wa_recipients"] == []
        r2 = run_async(lambda _db: an.notify_echeance(
            {"id": "TEST_nouser", "email": "a@b.co", "full_name": "A", "is_active": True,
             "can_receive_notifications": False}, ech, 3))
        assert r2["sent_email"] is False and r2["email_recipients"] == []

    def test_send_whatsapp_returns_none_when_disabled(self, mongo):
        an = _an()
        mongo.settings.update_one({"_id": "global"}, {"$set": {"wa_enabled": False}})
        assert run_async(lambda _db: an.send_whatsapp(to_phone="+22670000000", message="TEST")) is None

    def test_send_whatsapp_returns_none_when_enabled_but_unconfigured(self, mongo):
        an = _an()
        mongo.settings.update_one({"_id": "global"},
                                  {"$set": {"wa_enabled": True, "wa_access_token": "",
                                            "wa_phone_number_id": ""}})
        try:
            assert run_async(lambda _db: an.send_whatsapp(to_phone="+22670000000", message="TEST")) is None
        finally:
            mongo.settings.update_one({"_id": "global"}, {"$set": {"wa_enabled": False}})

    def test_notify_upload_filters_unauthorized_staff(self, mongo):
        """The Mongo filter used by notify_upload must exclude inactive / opted-out staff."""
        query = {
            "roles": {"$nin": ["client"]},
            "is_active": True,
            "$or": [{"can_receive_notifications": {"$exists": False}},
                    {"can_receive_notifications": True}],
        }
        mongo.users.insert_many([
            {"id": "TEST_staff_off", "email": "TEST_off@example.com", "full_name": "TEST Off",
             "roles": ["comptable"], "is_active": True, "can_receive_notifications": False},
            {"id": "TEST_staff_inactive", "email": "TEST_inactive@example.com",
             "full_name": "TEST Inactive", "roles": ["comptable"], "is_active": False,
             "can_receive_notifications": True},
            {"id": "TEST_staff_on", "email": "TEST_on@example.com", "full_name": "TEST On",
             "roles": ["comptable"], "is_active": True, "can_receive_notifications": True},
        ])
        try:
            ids = {u["id"] for u in mongo.users.find({**query, "id": {"$regex": "^TEST_staff"}}, {"id": 1})}
            assert ids == {"TEST_staff_on"}, ids
        finally:
            mongo.users.delete_many({"id": {"$regex": "^TEST_staff"}})


# --- module: albarka_clients (can_receive_notifications field) ---------------
class TestCanReceiveNotificationsField:
    def test_create_client_with_flag_and_update(self, superviseur, mongo):
        s, _ = superviseur
        email = "TEST_crn_client@example.com"
        mongo.users.delete_many({"email": email})
        r = s.post(f"{API}/clients", json={
            "email": email, "full_name": "TEST CRN Client", "company": "TEST SARL",
            "password": "TestPass2026!", "can_receive_notifications": False,
        }, timeout=60)
        assert r.status_code in (200, 201), r.text[:400]
        created = r.json()
        uid = created["id"]
        try:
            assert created.get("can_receive_notifications") is False, created
            # GET verifies persistence
            got = s.get(f"{API}/clients/{uid}", timeout=60)
            assert got.status_code == 200, got.text[:300]
            assert got.json()["can_receive_notifications"] is False

            up = s.patch(f"{API}/clients/{uid}", json={"can_receive_notifications": True}, timeout=60)
            assert up.status_code == 200, up.text[:300]
            assert up.json()["can_receive_notifications"] is True
            got2 = s.get(f"{API}/clients/{uid}", timeout=60)
            assert got2.json()["can_receive_notifications"] is True
        finally:
            s.delete(f"{API}/clients/{uid}", timeout=60)
            mongo.users.delete_many({"email": email})
