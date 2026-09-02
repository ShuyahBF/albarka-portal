"""ALBARKA — Iteration 4 backend tests.

Modules under test:
- albarka_contacts (CRUD carnet d'adresses, scopes, primary auto-demote, isolation)
- albarka_admin_settings (email_from_address / email_reply_to / notif_upload_wa)
- albarka_reports_mgmt (/reports/{id}/send with `to` / `to_contacts` routing)
- albarka_notifications (notify_upload WhatsApp guardrail)
"""
import asyncio
import os
import sys

import pytest
import requests

sys.path.insert(0, "/app/backend")

from conftest import API, run_async  # noqa: E402


# ---------------------------------------------------------------- helpers
def _mk(scope="client", tenant_id=None, **kw):
    payload = {
        "scope": scope,
        "full_name": kw.pop("full_name", "TEST_Contact"),
        "function": kw.pop("function", "daf"),
        "email": kw.pop("email", "test_contact@example.com"),
    }
    if tenant_id:
        payload["tenant_id"] = tenant_id
    payload.update(kw)
    return payload


@pytest.fixture(scope="module")
def created_contacts():
    ids = []
    yield ids


@pytest.fixture(scope="module", autouse=True)
def cleanup(superviseur, created_contacts):
    s, _ = superviseur
    yield
    for cid in set(created_contacts):
        try:
            s.delete(f"{API}/contacts/{cid}", timeout=60)
        except Exception:
            pass


# ============================================== CONTACTS — creation
class TestContactsCreate:
    def test_create_client_scope_contact(self, superviseur, client1, created_contacts):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_DG Sawadogo",
            function="dg", email="TEST_dg@example.com", phone="+22670000001",
            channels=["email", "whatsapp"], categories=["principal"],
        ), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        created_contacts.append(d["id"])
        assert d["scope"] == "client"
        assert d["tenant_id"] == c1["id"]
        assert d["full_name"] == "TEST_DG Sawadogo"
        assert d["function"] == "dg"
        assert d["email"] == "test_dg@example.com"  # lowercased
        assert d["channels"] == ["email", "whatsapp"]
        assert d["is_active"] is True
        assert d["can_receive_notifications"] is True
        assert "_id" not in d

        # GET verifies persistence
        g = s.get(f"{API}/contacts", params={"scope": "client", "tenant_id": c1["id"]}, timeout=60)
        assert g.status_code == 200
        found = [x for x in g.json() if x["id"] == d["id"]]
        assert len(found) == 1
        assert found[0]["email"] == "test_dg@example.com"

    def test_create_client_scope_without_tenant_id_400(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/contacts", json=_mk(), timeout=60)
        assert r.status_code == 400, r.text
        assert "tenant_id" in r.json()["detail"]

    def test_create_client_scope_unknown_tenant_404(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/contacts", json=_mk(tenant_id="nope-not-a-client"), timeout=60)
        assert r.status_code == 404, r.text

    def test_create_cabinet_scope_no_tenant_needed(self, superviseur, created_contacts):
        s, _ = superviseur
        r = s.post(f"{API}/contacts", json=_mk(
            scope="cabinet", full_name="TEST_Banque Atlantique",
            function="banque", organization="Banque Atlantique BF",
            email="TEST_banque@example.com",
        ), timeout=60)
        assert r.status_code == 200, r.text
        d = r.json()
        created_contacts.append(d["id"])
        assert d["scope"] == "cabinet"
        assert d["tenant_id"] == "cabinet"
        assert d["organization"] == "Banque Atlantique BF"

    def test_create_requires_email_or_phone(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        payload = {"scope": "client", "tenant_id": c1["id"], "full_name": "TEST_NoChannel"}
        r = s.post(f"{API}/contacts", json=payload, timeout=60)
        assert r.status_code == 400, r.text
        assert "email" in r.json()["detail"].lower()

    def test_create_as_client_forbidden(self, client1):
        s, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(tenant_id=c1["id"]), timeout=60)
        assert r.status_code == 403, r.text

    def test_create_invalid_function_rejected(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(tenant_id=c1["id"], function="grand_chef"), timeout=60)
        assert r.status_code in (400, 422), r.text

    def test_create_invalid_channel_rejected(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(tenant_id=c1["id"], channels=["sms"]), timeout=60)
        assert r.status_code in (400, 422), r.text

    def test_create_invalid_scope_rejected(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(scope="galaxy", tenant_id=c1["id"]), timeout=60)
        assert r.status_code in (400, 422), r.text

    def test_create_invalid_email_rejected(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(tenant_id=c1["id"], email="not-an-email"), timeout=60)
        assert r.status_code == 422, r.text


# ============================================== CONTACTS — primary handling
class TestContactsPrimary:
    def test_auto_demote_on_create(self, superviseur, client2, created_contacts):
        s, _ = superviseur
        _, c2 = client2
        a = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Primary A",
            email="TEST_pa@example.com", is_primary=True,
        ), timeout=60)
        assert a.status_code == 200, a.text
        aid = a.json()["id"]
        created_contacts.append(aid)
        assert a.json()["is_primary"] is True

        b = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Primary B",
            email="TEST_pb@example.com", is_primary=True,
        ), timeout=60)
        assert b.status_code == 200, b.text
        bid = b.json()["id"]
        created_contacts.append(bid)
        assert b.json()["is_primary"] is True

        items = {x["id"]: x for x in s.get(f"{API}/contacts", params={"tenant_id": c2["id"]}, timeout=60).json()}
        assert items[aid]["is_primary"] is False, "previous primary should be demoted"
        assert items[bid]["is_primary"] is True

    def test_patch_primary_demotes_others(self, superviseur, client2, created_contacts):
        s, _ = superviseur
        _, c2 = client2
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Primary C", email="TEST_pc@example.com",
        ), timeout=60)
        cid = c.json()["id"]
        created_contacts.append(cid)

        r = s.patch(f"{API}/contacts/{cid}", json={"is_primary": True}, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["is_primary"] is True

        items = s.get(f"{API}/contacts", params={"scope": "client", "tenant_id": c2["id"]}, timeout=60).json()
        primaries = [x["id"] for x in items if x.get("is_primary")]
        assert primaries == [cid], f"expected only {cid} primary, got {primaries}"

        # idempotent: re-patching itself keeps it primary
        r2 = s.patch(f"{API}/contacts/{cid}", json={"is_primary": True}, timeout=60)
        assert r2.status_code == 200 and r2.json()["is_primary"] is True

    def test_primary_scoped_per_tenant(self, superviseur, client1, client2):
        """A primary in client2 must not affect client1's primary."""
        s, _ = superviseur
        _, c1 = client1
        _, c2 = client2
        i1 = s.get(f"{API}/contacts", params={"tenant_id": c1["id"]}, timeout=60).json()
        i2 = s.get(f"{API}/contacts", params={"tenant_id": c2["id"]}, timeout=60).json()
        assert len([x for x in i1 if x.get("is_primary")]) <= 1
        assert len([x for x in i2 if x.get("is_primary")]) <= 1


# ============================================== CONTACTS — listing / isolation
class TestContactsIsolation:
    def test_client_sees_only_own(self, superviseur, client1, client2, created_contacts):
        s, _ = superviseur
        cs1, c1 = client1
        _, c2 = client2
        own = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_Own C1", email="TEST_own1@example.com",
        ), timeout=60).json()
        created_contacts.append(own["id"])
        other = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Own C2", email="TEST_own2@example.com",
        ), timeout=60).json()
        created_contacts.append(other["id"])
        cab = s.post(f"{API}/contacts", json=_mk(
            scope="cabinet", full_name="TEST_Impots DGI", function="impots",
            email="TEST_dgi@example.com",
        ), timeout=60).json()
        created_contacts.append(cab["id"])

        items = cs1.get(f"{API}/contacts", timeout=60)
        assert items.status_code == 200, items.text
        data = items.json()
        assert all(x["scope"] == "client" and x["tenant_id"] == c1["id"] for x in data), data
        ids = [x["id"] for x in data]
        assert own["id"] in ids
        assert other["id"] not in ids
        assert cab["id"] not in ids

    def test_client_cannot_force_cabinet_scope(self, client1, client2):
        cs1, c1 = client1
        _, c2 = client2
        r = cs1.get(f"{API}/contacts", params={"scope": "cabinet"}, timeout=60)
        assert r.status_code == 200
        assert all(x["scope"] == "client" and x["tenant_id"] == c1["id"] for x in r.json())

        r2 = cs1.get(f"{API}/contacts", params={"tenant_id": c2["id"]}, timeout=60)
        assert r2.status_code == 200
        assert all(x["tenant_id"] == c1["id"] for x in r2.json())

    def test_staff_filters(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        cab = s.get(f"{API}/contacts", params={"scope": "cabinet"}, timeout=60)
        assert cab.status_code == 200
        assert all(x["scope"] == "cabinet" for x in cab.json())
        t = s.get(f"{API}/contacts", params={"scope": "client", "tenant_id": c1["id"]}, timeout=60)
        assert t.status_code == 200
        assert all(x["tenant_id"] == c1["id"] for x in t.json())

    def test_unauthenticated_rejected(self):
        r = requests.get(f"{API}/contacts", timeout=60)
        assert r.status_code in (401, 403), r.text


# ============================================== CONTACTS — update / delete
class TestContactsUpdateDelete:
    def test_patch_fields_persist(self, superviseur, client1, created_contacts):
        s, _ = superviseur
        _, c1 = client1
        d = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_Patchable", email="TEST_patch@example.com",
        ), timeout=60).json()
        created_contacts.append(d["id"])
        r = s.patch(f"{API}/contacts/{d['id']}", json={
            "full_name": "TEST_Patched Name", "function": "rh",
            "channels": ["whatsapp"], "notes": "note test",
        }, timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["full_name"] == "TEST_Patched Name"
        assert r.json()["function"] == "rh"
        assert r.json()["channels"] == ["whatsapp"]
        # GET verifies persistence
        got = [x for x in s.get(f"{API}/contacts", params={"tenant_id": c1["id"]}, timeout=60).json()
               if x["id"] == d["id"]][0]
        assert got["full_name"] == "TEST_Patched Name"
        assert got["notes"] == "note test"

    def test_patch_invalid_enums(self, superviseur, client1, created_contacts):
        s, _ = superviseur
        _, c1 = client1
        d = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_EnumPatch", email="TEST_enum@example.com",
        ), timeout=60).json()
        created_contacts.append(d["id"])
        r1 = s.patch(f"{API}/contacts/{d['id']}", json={"function": "sorcier"}, timeout=60)
        assert r1.status_code in (400, 422), r1.text
        r2 = s.patch(f"{API}/contacts/{d['id']}", json={"channels": ["telegram"]}, timeout=60)
        assert r2.status_code in (400, 422), r2.text

    def test_patch_unknown_id_404(self, superviseur):
        s, _ = superviseur
        r = s.patch(f"{API}/contacts/does-not-exist", json={"full_name": "x"}, timeout=60)
        assert r.status_code == 404, r.text

    def test_client_cannot_patch_or_delete(self, superviseur, client1, client2, created_contacts):
        s, _ = superviseur
        cs1, _ = client1
        _, c2 = client2
        other = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_OtherTenant", email="TEST_other@example.com",
        ), timeout=60).json()
        created_contacts.append(other["id"])
        assert cs1.patch(f"{API}/contacts/{other['id']}", json={"full_name": "hack"}, timeout=60).status_code == 403
        assert cs1.delete(f"{API}/contacts/{other['id']}", timeout=60).status_code == 403

    def test_delete_removes_contact(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        d = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_ToDelete", email="TEST_del@example.com",
        ), timeout=60).json()
        r = s.delete(f"{API}/contacts/{d['id']}", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        remaining = [x["id"] for x in s.get(f"{API}/contacts", params={"tenant_id": c1["id"]}, timeout=60).json()]
        assert d["id"] not in remaining
        assert s.delete(f"{API}/contacts/{d['id']}", timeout=60).status_code == 404

    def test_comptable_can_manage(self, comptable, client1, created_contacts):
        s, _ = comptable
        _, c1 = client1
        r = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_ByComptable", email="TEST_compta@example.com",
        ), timeout=60)
        assert r.status_code == 200, r.text
        created_contacts.append(r.json()["id"])


# ============================================== ADMIN SETTINGS (email domain)
class TestSettingsEmailDomain:
    def test_put_and_get_email_fields(self, superviseur):
        s, _ = superviseur
        original = s.get(f"{API}/admin/settings", timeout=60)
        assert original.status_code == 200, original.text
        orig = original.json()
        assert "email_from_address" in orig and "email_reply_to" in orig
        assert "notif_upload_wa" in orig
        try:
            r = s.put(f"{API}/admin/settings", json={
                "email_from_address": "noreply@albarka-bf.com",
                "email_reply_to": "contact@albarka-bf.com",
            }, timeout=60)
            assert r.status_code == 200, r.text
            d = r.json()
            assert d["email_from_address"] == "noreply@albarka-bf.com"
            assert d["email_reply_to"] == "contact@albarka-bf.com"
            g = s.get(f"{API}/admin/settings", timeout=60).json()
            assert g["email_from_address"] == "noreply@albarka-bf.com"
            assert g["email_reply_to"] == "contact@albarka-bf.com"
            assert g["email_from_address"] != "********", "email fields must not be masked"
        finally:
            s.put(f"{API}/admin/settings", json={
                "email_from_address": orig.get("email_from_address") or "",
                "email_reply_to": orig.get("email_reply_to") or "",
            }, timeout=60)

    def test_wa_token_still_masked(self, superviseur):
        s, _ = superviseur
        g = s.get(f"{API}/admin/settings", timeout=60).json()
        if g.get("wa_access_token"):
            assert g["wa_access_token"] == "********"

    def test_client_cannot_read_settings(self, client1):
        s, _ = client1
        assert s.get(f"{API}/admin/settings", timeout=60).status_code == 403


# ============================================== REPORT SEND ROUTING
def _send_report(session, report_id, payload, attempts=3):
    """POST /reports/{id}/send with retry: the shared Resend proxy rate-limits
    (429 -> 502 côté API) when several tests send in the same second."""
    import time
    r = None
    for i in range(attempts):
        r = session.post(f"{API}/reports/{report_id}/send", json=payload, timeout=180)
        if r.status_code != 502:
            return r
        time.sleep(4 * (i + 1))
    return r


class TestReportSendRouting:
    @pytest.fixture(scope="class")
    def report(self, superviseur, client2):
        s, _ = superviseur
        _, c2 = client2
        r = s.post(f"{API}/reports/client/{c2['id']}/generate",
                   json={"kind": "ponctuel", "period_month": "2026-07"}, timeout=180)
        assert r.status_code == 200, r.text
        rep = r.json()
        yield rep
        s.delete(f"{API}/reports/{rep['id']}", timeout=60)

    def test_send_with_no_eligible_contacts_400(self, superviseur, report):
        s, _ = superviseur
        r = s.post(f"{API}/reports/{report['id']}/send",
                   json={"to_contacts": ["invalid-contact-id"]}, timeout=120)
        assert r.status_code == 400, r.text
        assert "destinataire" in r.json()["detail"].lower()

    def test_send_skips_optout_contacts(self, superviseur, client2, report, created_contacts):
        """Contact with can_receive_notifications=false must be filtered out -> 400."""
        s, _ = superviseur
        _, c2 = client2
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_OptOut", email="TEST_optout@example.com",
            can_receive_notifications=False,
        ), timeout=60).json()
        created_contacts.append(c["id"])
        r = s.post(f"{API}/reports/{report['id']}/send",
                   json={"to_contacts": [c["id"]]}, timeout=120)
        assert r.status_code == 400, r.text

    def test_send_skips_wa_only_contacts(self, superviseur, client2, report, created_contacts):
        s, _ = superviseur
        _, c2 = client2
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_WaOnly", phone="+22670000009",
            email=None, channels=["whatsapp"],
        ), timeout=60)
        assert c.status_code == 200, c.text
        cid = c.json()["id"]
        created_contacts.append(cid)
        r = s.post(f"{API}/reports/{report['id']}/send", json={"to_contacts": [cid]}, timeout=120)
        assert r.status_code == 400, r.text

    def test_send_skips_inactive_contacts(self, superviseur, client2, report, created_contacts):
        s, _ = superviseur
        _, c2 = client2
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Inactive", email="TEST_inactive@example.com",
        ), timeout=60).json()
        created_contacts.append(c["id"])
        s.patch(f"{API}/contacts/{c['id']}", json={"is_active": False}, timeout=60)
        r = s.post(f"{API}/reports/{report['id']}/send", json={"to_contacts": [c["id"]]}, timeout=120)
        assert r.status_code == 400, r.text

    def test_send_to_contacts_cross_tenant_filtered(self, superviseur, client1, report, created_contacts):
        """Contacts belonging to another tenant must not receive this client's report."""
        s, _ = superviseur
        _, c1 = client1
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_ForeignContact", email="TEST_foreign@example.com",
        ), timeout=60).json()
        created_contacts.append(c["id"])
        r = s.post(f"{API}/reports/{report['id']}/send", json={"to_contacts": [c["id"]]}, timeout=120)
        assert r.status_code == 400, r.text

    def test_send_with_explicit_to(self, superviseur, report):
        s, _ = superviseur
        r = _send_report(s, report["id"], {"to": "delivered@resend.dev", "message": "Test QA"})
        if r.status_code == 502:
            pytest.skip(f"external email proxy rate-limited (429): {r.status_code}")
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["ok"] is True
        assert isinstance(d["to"], list) and d["to"] == ["delivered@resend.dev"]
        assert d.get("message_id")

    def test_send_to_eligible_contacts(self, superviseur, client2, report, created_contacts):
        s, _ = superviseur
        _, c2 = client2
        c = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c2["id"], full_name="TEST_Eligible", email="delivered@resend.dev",
            channels=["email"],
        ), timeout=60).json()
        created_contacts.append(c["id"])
        r = _send_report(s, report["id"], {"to_contacts": [c["id"]]})
        if r.status_code == 502:
            pytest.skip(f"external email proxy rate-limited (429): {r.status_code}")
        assert r.status_code == 200, r.text
        assert r.json()["to"] == ["delivered@resend.dev"]
        # persistance de la trace d'envoi
        lst = s.get(f"{API}/reports/client/{c2['id']}/list", timeout=60).json()
        rep = [x for x in lst if x["id"] == report["id"]][0]
        assert rep["email_sent_to"] == "delivered@resend.dev"
        assert rep["email_sent_at"]

    def test_send_default_falls_back_to_client_email(self, superviseur, client2, report):
        """Fallback routing = compte client. Le proxy Resend bloque les adresses
        non délivrables (422 -> 502 côté API) : on tolère ce cas d'environnement."""
        s, _ = superviseur
        _, c2 = client2
        r = _send_report(s, report["id"], {}, attempts=1)
        if r.status_code == 502:
            pytest.skip(f"proxy email a rejeté {c2['email']} (undeliverable_recipient / 429)")
        assert r.status_code == 200, r.text
        assert r.json()["to"] == [c2["email"]]

    def test_send_as_client_forbidden(self, client2, report):
        s, _ = client2
        r = s.post(f"{API}/reports/{report['id']}/send", json={"to": "x@example.com"}, timeout=60)
        assert r.status_code == 403, r.text


# ============================================== notify_upload WA guardrail
class TestNotifyUploadWhatsAppGuardrail:
    """Unit-level: patch send_email/send_whatsapp so no external call is made."""

    def _run(self, notif_upload_wa: bool, wa_enabled: bool):
        import albarka_notifications as nt

        calls = {"email": 0, "wa": 0}
        orig_email, orig_wa = nt.send_email, nt.send_whatsapp

        async def fake_email(**kw):
            calls["email"] += 1
            return "fake-msg-id"

        async def fake_wa(**kw):
            calls["wa"] += 1
            return await orig_wa(**kw)  # real guardrail (returns None when disabled)

        nt.send_email, nt.send_whatsapp = fake_email, fake_wa

        async def scenario(db):
            before = await db.settings.find_one({"_id": "global"}) or {}
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"notif_upload_wa": notif_upload_wa, "wa_enabled": wa_enabled,
                          "notif_upload_enabled": True}},
            )
            try:
                tenant = await db.users.find_one({"roles": "client"}, {"_id": 0, "password_hash": 0})
                res = await nt.notify_upload(
                    db,
                    document={"original_filename": "TEST_piece.pdf", "kind": "facture_achat"},
                    tenant=tenant or {"full_name": "TEST", "company": "TEST"},
                )
            finally:
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"notif_upload_wa": before.get("notif_upload_wa", True),
                              "wa_enabled": before.get("wa_enabled", False),
                              "notif_upload_enabled": before.get("notif_upload_enabled", True)}},
                )
            return res

        try:
            return run_async(scenario), calls
        finally:
            nt.send_email, nt.send_whatsapp = orig_email, orig_wa

    def test_wa_optin_but_wa_disabled_silent_skip(self):
        res, calls = self._run(notif_upload_wa=True, wa_enabled=False)
        assert res["wa_sent"] == 0, res
        assert res["targets"] > 0
        assert calls["email"] == 1

    def test_wa_optout_never_attempts_wa(self):
        res, calls = self._run(notif_upload_wa=False, wa_enabled=False)
        assert res["wa_sent"] == 0, res
        assert calls["wa"] == 0, "send_whatsapp must not be called when notif_upload_wa=false"

    def test_notif_upload_disabled_short_circuits(self):
        import albarka_notifications as nt

        async def scenario(db):
            before = await db.settings.find_one({"_id": "global"}) or {}
            await db.settings.update_one({"_id": "global"}, {"$set": {"notif_upload_enabled": False}})
            try:
                return await nt.notify_upload(
                    db, document={"original_filename": "x.pdf", "kind": "autre"},
                    tenant={"full_name": "TEST"},
                )
            finally:
                await db.settings.update_one(
                    {"_id": "global"},
                    {"$set": {"notif_upload_enabled": before.get("notif_upload_enabled", True)}},
                )

        res = run_async(scenario)
        assert res == {"targets": 0, "sent": 0}


# ============================================== notifiable_contacts_for helper
class TestNotifiableContactsHelper:
    def test_helper_filters(self, superviseur, client1, created_contacts):
        s, _ = superviseur
        _, c1 = client1
        ok = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_HelperOk", email="TEST_helperok@example.com",
            phone="+22670000011", channels=["email", "whatsapp"],
        ), timeout=60).json()
        created_contacts.append(ok["id"])
        no = s.post(f"{API}/contacts", json=_mk(
            tenant_id=c1["id"], full_name="TEST_HelperNo", email="TEST_helperno@example.com",
            can_receive_notifications=False,
        ), timeout=60).json()
        created_contacts.append(no["id"])

        from albarka_contacts import notifiable_contacts_for

        emails = run_async(lambda _db: notifiable_contacts_for(c1["id"], "email"))
        ids = [c["id"] for c in emails]
        assert ok["id"] in ids
        assert no["id"] not in ids

        was = run_async(lambda _db: notifiable_contacts_for(c1["id"], "whatsapp"))
        assert ok["id"] in [c["id"] for c in was]

        assert run_async(lambda _db: notifiable_contacts_for(c1["id"], "sms")) == []


# ============================================== send_email payload (verified domain)
class TestSendEmailPayloadUsesSettings:
    """Vérifie que settings.email_from_address / email_reply_to sont transmis à
    Resend en `from_email` / `contact_email` (aucun appel réseau réel)."""

    def test_payload_fields(self):
        import albarka_notifications as nt

        captured = {}

        class _Resp:
            status_code = 202
            def raise_for_status(self): return None
            def json(self): return {"id": "unit-test-id"}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                captured["url"] = url
                captured["headers"] = headers
                captured["payload"] = json
                return _Resp()

        orig_client, orig_key = nt.httpx.AsyncClient, nt.EMAIL_KEY
        nt.httpx.AsyncClient = _FakeClient
        nt.EMAIL_KEY = orig_key or "unit-test-key"

        async def scenario(db):
            before = await db.settings.find_one({"_id": "global"})
            await db.settings.update_one({"_id": "global"}, {"$set": {
                "email_from_address": "noreply@albarka-bf.com",
                "email_reply_to": "contact@albarka-bf.com",
            }})
            try:
                return await nt.send_email(
                    to=["delivered@resend.dev"], subject="TEST unit",
                    html="<p>Bonjour</p>",
                    attachments=[{"filename": "a.pdf", "content": "eA==",
                                  "content_type": "application/pdf"}],
                )
            finally:
                await db.settings.update_one({"_id": "global"}, {"$set": {
                    "email_from_address": (before or {}).get("email_from_address", ""),
                    "email_reply_to": (before or {}).get("email_reply_to", ""),
                }})

        try:
            msg_id = run_async(scenario)
        finally:
            nt.httpx.AsyncClient, nt.EMAIL_KEY = orig_client, orig_key

        assert msg_id == "unit-test-id"
        p = captured["payload"]
        assert p["from_email"] == "noreply@albarka-bf.com"
        assert p["contact_email"] == "contact@albarka-bf.com"
        assert p["to"] == ["delivered@resend.dev"]
        assert p["from_name"]
        assert len(p["attachments"]) == 1
        assert "X-Email-Key" in captured["headers"]

    def test_explicit_reply_to_overrides_settings(self):
        import albarka_notifications as nt
        captured = {}

        class _Resp:
            def raise_for_status(self): return None
            def json(self): return {"id": "unit-2"}

        class _FakeClient:
            def __init__(self, *a, **kw): pass
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, headers=None, json=None):
                captured["payload"] = json
                return _Resp()

        orig_client, orig_key = nt.httpx.AsyncClient, nt.EMAIL_KEY
        nt.httpx.AsyncClient = _FakeClient
        nt.EMAIL_KEY = orig_key or "unit-test-key"
        try:
            run_async(lambda _db: nt.send_email(
                to="delivered@resend.dev", subject="TEST", html="<p>ok</p>",
                reply_to="override@albarka-bf.com"))
        finally:
            nt.httpx.AsyncClient, nt.EMAIL_KEY = orig_client, orig_key
        assert captured["payload"]["contact_email"] == "override@albarka-bf.com"
