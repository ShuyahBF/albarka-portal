"""ALBARKA backend API tests (health, auth+OTP, dashboard, clients, missions, echeances, documents+AI)."""
import time
import uuid

import pytest
import requests

from conftest import API, CREDENTIALS, login_full


def _pdf_bytes(text="FACTURE N 2026-001\nClient: Sawadogo Import-Export SARL\nMontant total: 1 250 000 FCFA\nDate: 15/03/2026\nTVA 18%: 225 000 FCFA\nIFU: 00012345A"):
    import pymupdf
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((60, 80), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


# ------------------------- Health -------------------------
class TestHealth:
    def test_health(self):
        r = requests.get(f"{API}/health", timeout=30)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["status"] == "ok"
        assert body["storage"] == "local"
        assert body["app"] == "albarka-portal"

    def test_root(self):
        r = requests.get(f"{API}/", timeout=30)
        assert r.status_code == 200
        assert "ALBARKA" in r.json()["message"]


# ------------------------- Auth -------------------------
class TestAuth:
    def test_login_returns_needs_otp_and_dev_otp(self):
        email, pwd = CREDENTIALS["superviseur"]
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["needs_otp"] is True
        assert isinstance(b["session_token"], str) and len(b["session_token"]) > 10
        assert b["dev_otp"] and len(b["dev_otp"]) == 6 and b["dev_otp"].isdigit()

    def test_verify_otp_returns_token_and_user(self):
        email, pwd = CREDENTIALS["superviseur"]
        token, user = login_full(email, pwd)
        assert isinstance(token, str) and len(token) > 20
        assert user["email"] == email
        assert "superviseur" in user["roles"]
        assert "password_hash" not in user

    def test_invalid_password_401(self):
        email, _ = CREDENTIALS["superviseur"]
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": "WrongPass123!"}, timeout=60)
        assert r.status_code == 401, r.text
        assert "detail" in r.json()

    def test_unknown_email_401(self):
        r = requests.post(f"{API}/auth/login", json={"email": "nobody@albarka-demo.bf", "password": "Whatever123!"}, timeout=60)
        assert r.status_code == 401

    def test_wrong_otp_code_400(self):
        email, pwd = CREDENTIALS["client1"]
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=60)
        st = r.json()["session_token"]
        v = requests.post(f"{API}/auth/verify-otp", json={"session_token": st, "code": "000000" if r.json()["dev_otp"] != "000000" else "111111"}, timeout=60)
        assert v.status_code == 400, v.text

    def test_invalid_session_token_400(self):
        v = requests.post(f"{API}/auth/verify-otp", json={"session_token": "nope-" + uuid.uuid4().hex, "code": "123456"}, timeout=60)
        assert v.status_code == 400

    def test_otp_single_use(self):
        email, pwd = CREDENTIALS["client2"]
        r = requests.post(f"{API}/auth/login", json={"email": email, "password": pwd}, timeout=60)
        b = r.json()
        first = requests.post(f"{API}/auth/verify-otp", json={"session_token": b["session_token"], "code": b["dev_otp"]}, timeout=60)
        assert first.status_code == 200
        second = requests.post(f"{API}/auth/verify-otp", json={"session_token": b["session_token"], "code": b["dev_otp"]}, timeout=60)
        assert second.status_code == 400, "OTP session should not be reusable"

    def test_me_with_valid_token(self, superviseur):
        s, user = superviseur
        r = s.get(f"{API}/auth/me", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["id"] == user["id"]
        assert r.json()["email"] == user["email"]

    def test_me_without_token_401(self):
        r = requests.get(f"{API}/auth/me", timeout=60)
        assert r.status_code in (401, 403), r.status_code

    def test_me_with_bad_token_401(self):
        r = requests.get(f"{API}/auth/me", headers={"Authorization": "Bearer garbage.token.here"}, timeout=60)
        assert r.status_code == 401


# ------------------------- Dashboard -------------------------
class TestDashboard:
    def test_summary_staff(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/dashboard/summary", timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        for k in ["documents_total", "documents_pending", "missions_active", "missions_done",
                  "echeances_upcoming", "echeances_late", "clients_total", "staff_total"]:
            assert k in b
        assert isinstance(b["clients_total"], int) and b["clients_total"] >= 2
        assert isinstance(b["staff_total"], int) and b["staff_total"] >= 2

    def test_summary_client_scoped(self, client1):
        s, _ = client1
        r = s.get(f"{API}/dashboard/summary", timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        assert b["clients_total"] is None
        assert b["staff_total"] is None
        assert isinstance(b["documents_total"], int)

    def test_activity(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/dashboard/activity", timeout=60)
        assert r.status_code == 200, r.text
        b = r.json()
        assert isinstance(b["documents"], list)
        assert isinstance(b["missions"], list)
        assert isinstance(b["echeances"], list)
        for d in b["documents"] + b["missions"] + b["echeances"]:
            assert "_id" not in d


# ------------------------- Clients / Staff -------------------------
class TestClients:
    created = []

    @classmethod
    def teardown_class(cls):
        s, _ = None, None
        from conftest import make_session
        s, _ = make_session(*CREDENTIALS["superviseur"])
        for uid in cls.created:
            s.delete(f"{API}/clients/{uid}", timeout=60)

    def test_list_clients_staff(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/clients", timeout=60)
        assert r.status_code == 200, r.text
        clients = r.json()
        assert len(clients) >= 2
        emails = [c["email"] for c in clients]
        assert "client1@albarka-demo.bf" in emails
        assert "client2@albarka-demo.bf" in emails
        for c in clients:
            assert "password_hash" not in c and "_id" not in c
            assert c["roles"] == ["client"]

    def test_client_cannot_list_clients(self, client1):
        s, _ = client1
        r = s.get(f"{API}/clients", timeout=60)
        assert r.status_code == 403, r.status_code

    def test_create_client_and_verify(self, superviseur):
        s, _ = superviseur
        email = f"test_client_{uuid.uuid4().hex[:8]}@albarka-demo.bf"
        payload = {"email": email, "full_name": "TEST Client QA", "company": "TEST SARL",
                   "phone": "+22670000000", "password": "TestPass2026!"}
        r = s.post(f"{API}/clients", json=payload, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["email"] == email
        assert body["roles"] == ["client"]
        assert "password_hash" not in body
        uid = body["id"]
        TestClients.created.append(uid)

        g = s.get(f"{API}/clients/{uid}", timeout=60)
        assert g.status_code == 200
        assert g.json()["full_name"] == "TEST Client QA"
        assert g.json()["company"] == "TEST SARL"

        listed = [c["id"] for c in s.get(f"{API}/clients", timeout=60).json()]
        assert uid in listed

    def test_create_duplicate_client_409(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/clients", json={"email": "client1@albarka-demo.bf", "full_name": "Dup",
                                           "password": "TestPass2026!"}, timeout=60)
        assert r.status_code == 409, r.text

    def test_create_client_invalid_payload_422(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/clients", json={"email": "not-an-email", "full_name": "X", "password": "short"}, timeout=60)
        assert r.status_code == 422, r.status_code

    def test_list_staff(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/clients/staff", timeout=60)
        assert r.status_code == 200, r.text
        staff = r.json()
        emails = [u["email"] for u in staff]
        assert "superviseur@albarka-demo.bf" in emails
        assert "comptable@albarka-demo.bf" in emails
        for u in staff:
            assert "client" not in u["roles"]

    def test_create_staff_and_login(self, superviseur):
        s, _ = superviseur
        email = f"test_staff_{uuid.uuid4().hex[:8]}@albarka-demo.bf"
        r = s.post(f"{API}/clients/staff", json={"email": email, "full_name": "TEST Staff QA",
                                                 "roles": ["comptable", "rh"], "password": "TestStaff2026!"}, timeout=60)
        assert r.status_code == 200, r.text
        body = r.json()
        assert sorted(body["roles"]) == ["comptable", "rh"]
        TestClients.created.append(body["id"])
        # new staff can authenticate
        token, user = login_full(email, "TestStaff2026!")
        assert token and user["email"] == email

    def test_create_staff_invalid_role_422(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/clients/staff", json={"email": f"x{uuid.uuid4().hex[:6]}@albarka-demo.bf",
                                                 "full_name": "X", "roles": ["pdg"], "password": "TestPass2026!"}, timeout=60)
        assert r.status_code == 422, r.status_code

    def test_create_staff_with_client_role_rejected(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/clients/staff", json={"email": f"x{uuid.uuid4().hex[:6]}@albarka-demo.bf",
                                                 "full_name": "X", "roles": ["client"], "password": "TestPass2026!"}, timeout=60)
        assert r.status_code == 422, r.status_code

    def test_patch_and_delete_client(self, superviseur):
        s, _ = superviseur
        email = f"test_patch_{uuid.uuid4().hex[:8]}@albarka-demo.bf"
        uid = s.post(f"{API}/clients", json={"email": email, "full_name": "TEST Before",
                                             "password": "TestPass2026!"}, timeout=60).json()["id"]
        p = s.patch(f"{API}/clients/{uid}", json={"full_name": "TEST After", "is_active": False}, timeout=60)
        assert p.status_code == 200, p.text
        assert p.json()["full_name"] == "TEST After"
        assert p.json()["is_active"] is False
        g = s.get(f"{API}/clients/{uid}", timeout=60)
        assert g.json()["full_name"] == "TEST After"

        d = s.delete(f"{API}/clients/{uid}", timeout=60)
        assert d.status_code == 200, d.text
        assert s.get(f"{API}/clients/{uid}", timeout=60).status_code == 404

    def test_delete_unknown_404(self, superviseur):
        s, _ = superviseur
        assert s.delete(f"{API}/clients/{uuid.uuid4().hex}", timeout=60).status_code == 404

    def test_delete_own_account_rejected(self, superviseur):
        s, user = superviseur
        r = s.delete(f"{API}/clients/{user['id']}", timeout=60)
        assert r.status_code == 400, r.status_code


# ------------------------- Missions -------------------------
class TestMissions:
    created = []

    @classmethod
    def teardown_class(cls):
        from conftest import make_session
        s, _ = make_session(*CREDENTIALS["superviseur"])
        for mid in cls.created:
            s.delete(f"{API}/missions/{mid}", timeout=60)

    def test_staff_sees_all_missions(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/missions", timeout=60)
        assert r.status_code == 200, r.text
        assert isinstance(r.json(), list)
        for m in r.json():
            assert "_id" not in m

    def test_create_mission_and_scoping(self, superviseur, client1, client2):
        s, sup = superviseur
        c1, u1 = client1
        c2, u2 = client2
        payload = {"tenant_id": u1["id"], "title": "TEST Mission QA", "type": "declaration_fiscale",
                   "description": "Test mission", "due_date": "2026-09-30", "status": "en_attente"}
        r = s.post(f"{API}/missions", json=payload, timeout=60)
        assert r.status_code == 200, r.text
        m = r.json()
        assert m["title"] == "TEST Mission QA"
        assert m["tenant_id"] == u1["id"]
        assert m["created_by"] == sup["id"]
        mid = m["id"]
        TestMissions.created.append(mid)

        # tenant filter
        filtered = s.get(f"{API}/missions", params={"tenant_id": u1["id"]}, timeout=60).json()
        assert all(x["tenant_id"] == u1["id"] for x in filtered)
        assert mid in [x["id"] for x in filtered]

        # client1 sees it, client2 does not
        assert mid in [x["id"] for x in c1.get(f"{API}/missions", timeout=60).json()]
        assert mid not in [x["id"] for x in c2.get(f"{API}/missions", timeout=60).json()]
        assert c2.get(f"{API}/missions/{mid}", timeout=60).status_code == 403
        assert c1.get(f"{API}/missions/{mid}", timeout=60).status_code == 200

    def test_client_cannot_create_mission(self, client1):
        s, u = client1
        r = s.post(f"{API}/missions", json={"tenant_id": u["id"], "title": "TEST hack"}, timeout=60)
        assert r.status_code == 403, r.status_code

    def test_patch_mission_status(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        mid = s.post(f"{API}/missions", json={"tenant_id": u1["id"], "title": "TEST Patch Mission"}, timeout=60).json()["id"]
        TestMissions.created.append(mid)
        p = s.patch(f"{API}/missions/{mid}", json={"status": "terminee"}, timeout=60)
        assert p.status_code == 200, p.text
        assert p.json()["status"] == "terminee"
        g = s.get(f"{API}/missions/{mid}", timeout=60)
        assert g.json()["status"] == "terminee"
        assert g.json()["updated_at"] != g.json()["created_at"]

    def test_invalid_mission_type_422(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        r = s.post(f"{API}/missions", json={"tenant_id": u1["id"], "title": "TEST", "type": "bogus"}, timeout=60)
        assert r.status_code == 422, r.status_code

    def test_patch_unknown_mission_404(self, superviseur):
        s, _ = superviseur
        r = s.patch(f"{API}/missions/{uuid.uuid4().hex}", json={"status": "terminee"}, timeout=60)
        assert r.status_code == 404

    def test_delete_mission(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        mid = s.post(f"{API}/missions", json={"tenant_id": u1["id"], "title": "TEST Del Mission"}, timeout=60).json()["id"]
        assert s.delete(f"{API}/missions/{mid}", timeout=60).status_code == 200
        assert s.get(f"{API}/missions/{mid}", timeout=60).status_code == 404


# ------------------------- Échéances -------------------------
class TestEcheances:
    created = []

    @classmethod
    def teardown_class(cls):
        from conftest import make_session
        s, _ = make_session(*CREDENTIALS["superviseur"])
        for eid in cls.created:
            s.delete(f"{API}/echeances/{eid}", timeout=60)

    def test_list_staff_and_client_scoping(self, superviseur, client1, client2):
        s, _ = superviseur
        c1, u1 = client1
        c2, u2 = client2
        r = s.get(f"{API}/echeances", timeout=60)
        assert r.status_code == 200, r.text
        payload = {"tenant_id": u1["id"], "title": "TEST TVA Mars 2026", "type": "tva",
                   "due_date": "2026-04-20", "amount": 750000.0, "period": "2026-03", "status": "a_venir"}
        c = s.post(f"{API}/echeances", json=payload, timeout=60)
        assert c.status_code == 200, c.text
        e = c.json()
        assert e["amount"] == 750000.0 and e["type"] == "tva"
        eid = e["id"]
        TestEcheances.created.append(eid)

        assert eid in [x["id"] for x in s.get(f"{API}/echeances", params={"tenant_id": u1['id']}, timeout=60).json()]
        assert eid in [x["id"] for x in c1.get(f"{API}/echeances", timeout=60).json()]
        assert eid not in [x["id"] for x in c2.get(f"{API}/echeances", timeout=60).json()]

    def test_client_cannot_create_echeance(self, client1):
        s, u = client1
        r = s.post(f"{API}/echeances", json={"tenant_id": u["id"], "title": "TEST", "due_date": "2026-05-01"}, timeout=60)
        assert r.status_code == 403

    def test_patch_echeance_status(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        eid = s.post(f"{API}/echeances", json={"tenant_id": u1["id"], "title": "TEST Patch Ech",
                                               "due_date": "2026-06-15"}, timeout=60).json()["id"]
        TestEcheances.created.append(eid)
        p = s.patch(f"{API}/echeances/{eid}", json={"status": "traitee"}, timeout=60)
        assert p.status_code == 200, p.text
        assert p.json()["status"] == "traitee"
        listed = [x for x in s.get(f"{API}/echeances", params={"tenant_id": u1["id"]}, timeout=60).json() if x["id"] == eid]
        assert listed and listed[0]["status"] == "traitee"

    def test_invalid_echeance_type_422(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        r = s.post(f"{API}/echeances", json={"tenant_id": u1["id"], "title": "TEST", "type": "xyz",
                                             "due_date": "2026-06-15"}, timeout=60)
        assert r.status_code == 422

    def test_delete_echeance(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        eid = s.post(f"{API}/echeances", json={"tenant_id": u1["id"], "title": "TEST Del Ech",
                                               "due_date": "2026-07-01"}, timeout=60).json()["id"]
        assert s.delete(f"{API}/echeances/{eid}", timeout=60).status_code == 200
        assert s.delete(f"{API}/echeances/{eid}", timeout=60).status_code == 404


# ------------------------- Documents + AI analysis -------------------------
class TestDocuments:
    doc_id = None

    def test_upload_pdf_as_client(self, client1):
        s, u = client1
        files = {"file": ("TEST_facture.pdf", _pdf_bytes(), "application/pdf")}
        r = s.post(f"{API}/documents", files=files, data={"kind": "piece_comptable"}, timeout=120)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["status"] == "en_analyse"
        assert d["tenant_id"] == u["id"]
        assert d["kind"] == "piece_comptable"
        assert d["content_type"] == "application/pdf"
        assert d["size"] > 0
        assert "_id" not in d
        TestDocuments.doc_id = d["id"]

    def test_list_documents_scoped(self, client1, client2):
        s, u = client1
        assert TestDocuments.doc_id, "upload test must run first"
        docs = s.get(f"{API}/documents", timeout=60).json()
        assert TestDocuments.doc_id in [d["id"] for d in docs]
        assert all(d["tenant_id"] == u["id"] for d in docs)
        c2, _ = client2
        assert TestDocuments.doc_id not in [d["id"] for d in c2.get(f"{API}/documents", timeout=60).json()]

    def test_other_client_cannot_access(self, client2):
        c2, _ = client2
        r = c2.get(f"{API}/documents/{TestDocuments.doc_id}", timeout=60)
        assert r.status_code == 403, r.status_code
        assert c2.get(f"{API}/documents/{TestDocuments.doc_id}/download", timeout=60).status_code == 403
        assert c2.delete(f"{API}/documents/{TestDocuments.doc_id}", timeout=60).status_code == 403

    def test_download_url_local_mode(self, client1):
        s, _ = client1
        r = s.get(f"{API}/documents/{TestDocuments.doc_id}/download-url", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json() == {"url": None, "mode": "local"}

    def test_download_binary(self, client1):
        s, _ = client1
        r = s.get(f"{API}/documents/{TestDocuments.doc_id}/download", timeout=60)
        assert r.status_code == 200, r.text
        assert r.content.startswith(b"%PDF")
        assert "attachment" in r.headers.get("content-disposition", "")

    def test_ai_analysis_completes(self, client1):
        """Poll until Claude Sonnet 5 analysis finishes (async task)."""
        s, _ = client1
        deadline = time.time() + 120
        doc = None
        while time.time() < deadline:
            r = s.get(f"{API}/documents/{TestDocuments.doc_id}", timeout=60)
            assert r.status_code == 200, r.text
            doc = r.json()
            if doc["status"] != "en_analyse":
                break
            time.sleep(5)
        assert doc is not None
        assert doc["status"] == "analyse", f"AI analysis did not succeed: status={doc['status']} synthesis={doc.get('synthesis')}"
        syn = doc.get("synthesis")
        assert syn, "synthesis missing after analysis"
        assert syn["summary"] and len(syn["summary"]) > 20
        assert isinstance(syn["extracted_fields"], dict) and syn["extracted_fields"]
        assert syn["model"] == "claude-sonnet-5"
        assert "_id" not in syn

    def test_staff_can_view_client_document(self, superviseur, client1):
        s, _ = superviseur
        _, u1 = client1
        r = s.get(f"{API}/documents/{TestDocuments.doc_id}", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["tenant_id"] == u1["id"]
        filtered = s.get(f"{API}/documents", params={"tenant_id": u1["id"]}, timeout=60).json()
        assert TestDocuments.doc_id in [d["id"] for d in filtered]

    def test_upload_invalid_extension_400(self, client1):
        s, _ = client1
        r = s.post(f"{API}/documents", files={"file": ("TEST_bad.exe", b"MZ\x00\x00", "application/octet-stream")},
                   data={"kind": "piece_comptable"}, timeout=60)
        assert r.status_code == 400, r.text

    def test_upload_invalid_kind_400(self, client1):
        s, _ = client1
        r = s.post(f"{API}/documents", files={"file": ("TEST_x.pdf", _pdf_bytes(), "application/pdf")},
                   data={"kind": "bogus_kind"}, timeout=60)
        assert r.status_code == 400, r.text

    def test_staff_upload_without_tenant_id_400(self, superviseur):
        s, _ = superviseur
        r = s.post(f"{API}/documents", files={"file": ("TEST_y.pdf", _pdf_bytes(), "application/pdf")},
                   data={"kind": "piece_comptable"}, timeout=60)
        assert r.status_code == 400, r.text

    def test_unknown_document_404(self, superviseur):
        s, _ = superviseur
        assert s.get(f"{API}/documents/{uuid.uuid4().hex}", timeout=60).status_code == 404

    def test_zz_delete_document(self, client1):
        s, _ = client1
        r = s.delete(f"{API}/documents/{TestDocuments.doc_id}", timeout=60)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True
        assert s.get(f"{API}/documents/{TestDocuments.doc_id}", timeout=60).status_code == 404


# ------------------------- Route ordering / misc -------------------------
class TestMisc:
    def test_storage_mode_meta_route(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/documents/_meta/storage-mode", timeout=60)
        assert r.status_code == 200, f"route shadowed by /documents/{{document_id}}: {r.status_code} {r.text[:200]}"
        assert r.json()["mode"] == "local"

    def test_documents_requires_auth(self):
        r = requests.get(f"{API}/documents", timeout=60)
        assert r.status_code in (401, 403)
