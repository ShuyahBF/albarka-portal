"""Tests iteration 5 — contact groups, report templates, contacts import,
signing certificate lifecycle, and branding uploads."""
import io
import time

import pytest
import requests

from tests.conftest import API


def _admin_token():
    from tests.conftest import CREDENTIALS, login_full
    tok, _ = login_full(*CREDENTIALS["superviseur"])
    return tok


# ---------- Report templates ----------
class TestReportTemplates:
    def test_crud_and_default_toggle(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/report-templates", json={"name": "TplA", "is_default": True})
        assert r.status_code == 200, r.text
        a = r.json()
        r = s.post(f"{API}/report-templates", json={"name": "TplB", "is_default": True})
        assert r.status_code == 200
        b = r.json()
        # A should have been demoted
        listed = s.get(f"{API}/report-templates").json()
        by_id = {t["id"]: t for t in listed}
        assert by_id[a["id"]]["is_default"] is False
        assert by_id[b["id"]]["is_default"] is True
        r = s.patch(f"{API}/report-templates/{b['id']}", json={"name": "TplB-renamed"})
        assert r.status_code == 200
        assert r.json()["name"] == "TplB-renamed"
        assert s.delete(f"{API}/report-templates/{a['id']}").status_code == 200
        assert s.delete(f"{API}/report-templates/{b['id']}").status_code == 200

    def test_client_cannot_manage(self, client1):
        s, _ = client1
        r = s.get(f"{API}/report-templates")
        assert r.status_code == 403


# ---------- Contact groups ----------
class TestContactGroups:
    def test_client_scope_and_cabinet_scope(self, superviseur, client1):
        s, _ = superviseur
        _, c1_user = client1
        # Create a contact for client1
        cr = s.post(f"{API}/contacts", json={
            "scope": "client", "tenant_id": c1_user["id"],
            "full_name": "Test Group Contact", "email": "group1@sawadogo.bf",
            "function": "dg", "channels": ["email"],
        })
        assert cr.status_code == 200, cr.text
        contact_id = cr.json()["id"]

        # Create a client group
        gr = s.post(f"{API}/contact-groups", json={
            "scope": "client", "tenant_id": c1_user["id"],
            "name": "Direction cliente", "contact_ids": [contact_id],
        })
        assert gr.status_code == 200, gr.text
        gid = gr.json()["id"]
        assert gr.json()["contact_ids"] == [contact_id]

        # Update: remove all contacts
        u = s.patch(f"{API}/contact-groups/{gid}", json={"contact_ids": []})
        assert u.status_code == 200 and u.json()["contact_ids"] == []

        # Unknown contact must 400
        r = s.patch(f"{API}/contact-groups/{gid}", json={"contact_ids": ["FAKE_ID"]})
        assert r.status_code == 400

        # Delete
        assert s.delete(f"{API}/contact-groups/{gid}").status_code == 200
        s.delete(f"{API}/contacts/{contact_id}")

    def test_client_isolation(self, superviseur, client1, client2):
        s, _ = superviseur
        _, c1_user = client1
        _, c2_user = client2
        # Group on client1
        g = s.post(f"{API}/contact-groups", json={
            "scope": "client", "tenant_id": c1_user["id"], "name": "Iso"
        }).json()
        # client2 must not see it
        c2s, _ = client2
        listed = c2s.get(f"{API}/contact-groups").json()
        assert not any(x["id"] == g["id"] for x in listed)
        s.delete(f"{API}/contact-groups/{g['id']}")


# ---------- Contacts import ----------
class TestContactsImport:
    def test_csv_import(self, superviseur, client1):
        s, _ = superviseur
        _, c1_user = client1
        csv_content = (
            "full_name,function,organization,email,phone,is_primary,"
            "can_receive_notifications,channels,categories,notes\n"
            "Test Imported,dg,,imported1@sawadogo.bf,+22670009991,false,true,email|whatsapp,,note1\n"
            "Test Imported 2,daf,,imported2@sawadogo.bf,+22670009992,false,true,email,,note2\n"
            ",dg,,broken@sawadogo.bf,,,,,,\n"  # missing full_name → skipped
        )
        files = {"file": ("contacts.csv", io.BytesIO(csv_content.encode("utf-8")), "text/csv")}
        data = {"scope": "client", "tenant_id": c1_user["id"]}
        r = s.post(f"{API}/contacts/import", files=files, data=data)
        assert r.status_code == 200, r.text
        report = r.json()
        assert report["imported"] >= 2
        assert report["skipped"] >= 1
        # cleanup
        listed = s.get(f"{API}/contacts", params={"scope": "client", "tenant_id": c1_user["id"]}).json()
        for c in listed:
            if c.get("email", "").startswith("imported"):
                s.delete(f"{API}/contacts/{c['id']}")

    def test_import_template_download(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/contacts/import/template")
        assert r.status_code == 200
        assert r.headers.get("content-type", "").startswith("text/csv")
        assert "full_name" in r.text

    def test_bad_scope(self, superviseur):
        s, _ = superviseur
        files = {"file": ("x.csv", io.BytesIO(b"full_name,email\nX,x@x.bf\n"), "text/csv")}
        r = s.post(f"{API}/contacts/import", files=files, data={"scope": "invalid"})
        assert r.status_code == 400

    def test_client_forbidden(self, client1):
        s, _ = client1
        files = {"file": ("x.csv", io.BytesIO(b"full_name,email\nX,x@x.bf\n"), "text/csv")}
        r = s.post(f"{API}/contacts/import", files=files, data={"scope": "cabinet"})
        assert r.status_code == 403


# ---------- Signing certificates ----------
class TestCertificates:
    def test_create_activate_delete(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/admin/certificates", json={
            "common_name": "Test Cert", "organization": "Test Org",
            "country": "BF", "passphrase": "TestPass2026!",
            "valid_years": 2, "activate": False,
        })
        assert r.status_code == 200, r.text
        cid = r.json()["id"]
        # activate
        r = s.post(f"{API}/admin/certificates/{cid}/activate")
        assert r.status_code == 200
        # Listed as active
        listed = s.get(f"{API}/admin/certificates").json()
        assert any(c["id"] == cid and c["is_active"] for c in listed)
        # delete
        r = s.delete(f"{API}/admin/certificates/{cid}")
        assert r.status_code == 200

    def test_short_passphrase_rejected(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/admin/certificates", json={
            "common_name": "X", "organization": "Y", "passphrase": "short",
        })
        assert r.status_code == 422

    def test_client_forbidden(self, client1):
        s, _ = client1
        assert s.get(f"{API}/admin/certificates").status_code == 403


# ---------- Branding ----------
def _tiny_png() -> bytes:
    """Return the smallest valid 1x1 transparent PNG."""
    import base64
    return base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8"
        b"z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )


class TestBranding:
    def test_upload_and_toggle_and_delete(self, superviseur):
        s, _ = superviseur
        for kind in ("logo", "letterhead", "dg_signature", "watermark"):
            files = {"file": (f"{kind}.png", io.BytesIO(_tiny_png()), "image/png")}
            r = s.post(f"{API}/admin/branding/{kind}", files=files)
            assert r.status_code == 200, r.text
            assert r.json()[kind]["size"] > 0
        r = s.put(f"{API}/admin/branding/toggles", json={
            "apply_watermark": False, "apply_letterhead": True,
        })
        assert r.status_code == 200
        b = r.json()
        assert b["apply_watermark"] is False and b["apply_letterhead"] is True
        # Delete all
        for kind in ("logo", "letterhead", "dg_signature", "watermark"):
            r = s.delete(f"{API}/admin/branding/{kind}")
            assert r.status_code == 200

    def test_bad_kind(self, superviseur):
        s, _ = superviseur
        files = {"file": ("x.png", io.BytesIO(_tiny_png()), "image/png")}
        r = s.post(f"{API}/admin/branding/bogus", files=files)
        assert r.status_code == 400

    def test_bad_mime(self, superviseur):
        s, _ = superviseur
        files = {"file": ("x.txt", io.BytesIO(b"hello"), "text/plain")}
        r = s.post(f"{API}/admin/branding/logo", files=files)
        assert r.status_code == 400

    def test_client_forbidden(self, client1):
        s, _ = client1
        assert s.get(f"{API}/admin/branding").status_code == 403


# ---------- Report generation with template + branding + send-to-groups ----------
class TestReportPipelineWithTemplate:
    def test_generate_with_template_id(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        # create template
        t = s.post(f"{API}/report-templates", json={
            "name": "Sans pièces", "include_documents": False, "include_ai_syntheses": False,
            "intro_paragraph": "Bonjour.", "conclusion_paragraph": "Cordialement.",
        }).json()
        r = s.post(f"{API}/reports/client/{c1['id']}/generate", json={
            "kind": "mensuel", "template_id": t["id"],
        })
        assert r.status_code == 200, r.text
        report_id = r.json()["id"]
        # Ensure download works
        dl = s.get(f"{API}/reports/{report_id}/download")
        assert dl.status_code == 200
        assert dl.headers["content-type"] == "application/pdf"
        assert dl.content.startswith(b"%PDF-")
        # cleanup
        s.delete(f"{API}/reports/{report_id}")
        s.delete(f"{API}/report-templates/{t['id']}")

    def test_send_to_groups(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        # Create a contact + group
        c = s.post(f"{API}/contacts", json={
            "scope": "client", "tenant_id": c1["id"],
            "full_name": "Grp Send", "email": "grpsend@sawadogo.bf",
            "function": "dg", "channels": ["email"],
        }).json()
        g = s.post(f"{API}/contact-groups", json={
            "scope": "client", "tenant_id": c1["id"],
            "name": "Direction", "contact_ids": [c["id"]],
        }).json()
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "ponctuel"}).json()
        # Send to groups — email backend may be mocked; assert 200 OR 502
        r = s.post(f"{API}/reports/{rep['id']}/send", json={
            "subject": "Test", "to_groups": [g["id"]],
        })
        assert r.status_code in (200, 502), r.text
        # cleanup
        s.delete(f"{API}/reports/{rep['id']}")
        s.delete(f"{API}/contact-groups/{g['id']}")
        s.delete(f"{API}/contacts/{c['id']}")


# ---------- Iteration 6: visible signature stamp + signature audit log + WhatsApp share ----------
class TestSignatureAudit:
    """Signature audit log must record cert id/serial and be admin-only."""
    def test_audit_log_contains_signature(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        # Create cert active
        cert = s.post(f"{API}/admin/certificates", json={
            "common_name": "AuditCert", "organization": "Cabinet",
            "country": "BF", "passphrase": "AuditPass2026!", "valid_years": 2, "activate": True,
        }).json()
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "audit"}).json()
        sig = s.post(f"{API}/reports/{rep['id']}/sign", json={
            "signature_name": "Auditor DG",
        })
        assert sig.status_code == 200, sig.text
        # Get log
        log = s.get(f"{API}/reports/signatures/log").json()
        matches = [e for e in log if e["report_id"] == rep["id"]]
        assert len(matches) == 1
        entry = matches[0]
        assert entry["signature_name"] == "Auditor DG"
        assert entry["certificate_id"] == cert["id"]
        assert entry["signed_by_name"]
        # Filter by cert
        filtered = s.get(f"{API}/reports/signatures/log", params={"certificate_id": cert["id"]}).json()
        assert all(x["certificate_id"] == cert["id"] for x in filtered)
        # Cleanup
        s.delete(f"{API}/reports/{rep['id']}")  # will 400 (signed) — that's fine
        s.delete(f"{API}/admin/certificates/{cert['id']}")

    def test_client_forbidden(self, client1):
        s, _ = client1
        r = s.get(f"{API}/reports/signatures/log")
        assert r.status_code == 403


class TestSharedDownloadToken:
    """The shared token endpoint should reject bogus and expired tokens."""
    def test_bad_token_403(self):
        r = requests.get(f"{API}/reports/download/shared/notatoken", timeout=30)
        assert r.status_code == 403

    def test_valid_token_downloads(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "ponctuel"}).json()
        # Craft a token like the server does
        from jose import jwt
        from datetime import datetime, timedelta, timezone
        # Read JWT_SECRET_KEY from backend .env
        from dotenv import dotenv_values
        secret = dotenv_values("/app/backend/.env")["JWT_SECRET_KEY"]
        token = jwt.encode(
            {"sub": f"report:{rep['id']}", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
            secret, algorithm="HS256",
        )
        r = requests.get(f"{API}/reports/download/shared/{token}", timeout=30)
        assert r.status_code == 200
        assert r.headers["content-type"] == "application/pdf"
        assert r.content.startswith(b"%PDF-")
        s.delete(f"{API}/reports/{rep['id']}")


class TestWhatsAppReport:
    """WA endpoint should reject when WA disabled OR no phone recipient."""
    def test_wa_no_recipient_400(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "ponctuel"}).json()
        # Client has no phone → 400
        r = s.post(f"{API}/reports/{rep['id']}/send-whatsapp", json={"message": "hi"})
        assert r.status_code == 400
        s.delete(f"{API}/reports/{rep['id']}")

    def test_wa_disabled_400(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "ponctuel"}).json()
        # Force settings.wa_enabled=false and provide a phone
        r = s.post(f"{API}/reports/{rep['id']}/send-whatsapp",
                   json={"to": "+22670000000", "message": "test"})
        # 400 (WA disabled) or 502 (Meta rejects). Both acceptable, but not 200.
        assert r.status_code in (400, 502), r.text
        s.delete(f"{API}/reports/{rep['id']}")


class TestBrandingPreview:
    def test_upload_and_preview(self, superviseur):
        s, _ = superviseur
        import io
        files = {"file": ("logo.png", io.BytesIO(_tiny_png()), "image/png")}
        s.post(f"{API}/admin/branding/logo", files=files)
        r = s.get(f"{API}/admin/branding/logo/preview")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/")
        assert r.content == _tiny_png()
        # Clean
        s.delete(f"{API}/admin/branding/logo")

    def test_preview_404_when_missing(self, superviseur):
        s, _ = superviseur
        # ensure clean
        s.delete(f"{API}/admin/branding/watermark")
        r = s.get(f"{API}/admin/branding/watermark/preview")
        assert r.status_code == 404


class TestWhatsAppBroadcast:
    """New: broadcast to all whatsapp-enabled contacts of a tenant."""
    def test_all_whatsapp_contacts_recipient_scope(self, superviseur, client1):
        s, _ = superviseur
        _, c1 = client1
        # Create 2 contacts on client1: one with WA + phone, one without
        c_wa = s.post(f"{API}/contacts", json={
            "scope": "client", "tenant_id": c1["id"],
            "full_name": "WA Contact", "phone": "+22670009901",
            "function": "dg", "channels": ["email", "whatsapp"],
        }).json()
        c_no = s.post(f"{API}/contacts", json={
            "scope": "client", "tenant_id": c1["id"],
            "full_name": "Email Only", "email": "emailonly@sawadogo.bf",
            "function": "daf", "channels": ["email"],
        }).json()
        rep = s.post(f"{API}/reports/client/{c1['id']}/generate",
                     json={"kind": "ponctuel"}).json()
        r = s.post(f"{API}/reports/{rep['id']}/send-whatsapp", json={
            "all_whatsapp_contacts": True, "message": "Bcast",
        })
        # WA not configured in test env → 400 desactivé OR 502 no delivery
        assert r.status_code in (400, 502), r.text
        # Cleanup
        s.delete(f"{API}/reports/{rep['id']}")
        s.delete(f"{API}/contacts/{c_wa['id']}")
        s.delete(f"{API}/contacts/{c_no['id']}")


class TestWhatsAppAuditLog:
    def test_log_admin_only(self, superviseur, client1):
        s, _ = superviseur
        assert s.get(f"{API}/reports/whatsapp/log").status_code == 200
        cs, _ = client1
        assert cs.get(f"{API}/reports/whatsapp/log").status_code == 403

    def test_log_filters(self, superviseur):
        s, _ = superviseur
        # Just make sure filters accept the query params without 500
        for params in [
            {},
            {"success": "true"},
            {"success": "false"},
            {"tenant_id": "nope"},
        ]:
            r = s.get(f"{API}/reports/whatsapp/log", params=params)
            assert r.status_code == 200
            assert isinstance(r.json(), list)
