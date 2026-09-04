"""Additional security / RBAC edge-case tests for ALBARKA."""
import uuid

import requests

from conftest import API, CREDENTIALS, login_full, make_session


def _grant_active_contract(staff_session, tenant_id):
    """Feature 14 : un client ne peut se connecter qu'avec un contrat actif."""
    from datetime import date, timedelta
    r = staff_session.post(f"{API}/client-contracts", json={
        "tenant_id": tenant_id,
        "title": "TEST_Contrat RBAC",
        "start_date": (date.today() - timedelta(days=1)).isoformat(),
        "end_date": (date.today() + timedelta(days=90)).isoformat(),
        "status": "active",
    }, timeout=60)
    assert r.status_code == 200, r.text[:200]
    return r.json()["id"]


class TestRbacEdge:
    created_users = []

    @classmethod
    def teardown_class(cls):
        s, _ = make_session(*CREDENTIALS["superviseur"])
        for uid in cls.created_users:
            for ct in s.get(f"{API}/client-contracts", params={"tenant_id": uid}, timeout=60).json():
                s.delete(f"{API}/client-contracts/{ct['id']}", timeout=60)
            s.delete(f"{API}/clients/{uid}", timeout=60)

    def test_non_superviseur_staff_has_staff_access(self, comptable):
        s, user = comptable
        assert sorted(user["roles"]) == ["comptable", "fiscaliste"]
        assert s.get(f"{API}/clients", timeout=60).status_code == 200
        assert s.get(f"{API}/clients/staff", timeout=60).status_code == 200
        assert s.get(f"{API}/missions", timeout=60).status_code == 200
        assert s.get(f"{API}/echeances", timeout=60).status_code == 200
        assert s.get(f"{API}/dashboard/summary", timeout=60).status_code == 200

    def test_client_forbidden_on_staff_routes(self, client1, superviseur):
        s, u = client1
        sup, _ = superviseur
        assert s.get(f"{API}/clients/staff", timeout=60).status_code == 403
        assert s.get(f"{API}/clients/{u['id']}", timeout=60).status_code == 403
        assert s.post(f"{API}/clients", json={"email": f"x{uuid.uuid4().hex[:6]}@t.bf", "full_name": "X",
                                              "password": "TestPass2026!"}, timeout=60).status_code == 403
        assert s.patch(f"{API}/clients/{u['id']}", json={"full_name": "hack"}, timeout=60).status_code == 403
        assert s.delete(f"{API}/clients/{u['id']}", timeout=60).status_code == 403

    def test_client_cannot_patch_or_delete_mission(self, superviseur, client1):
        sup, _ = superviseur
        c1, u1 = client1
        mid = sup.post(f"{API}/missions", json={"tenant_id": u1["id"], "title": "TEST RBAC Mission"}, timeout=60).json()["id"]
        try:
            assert c1.patch(f"{API}/missions/{mid}", json={"status": "terminee"}, timeout=60).status_code == 403
            assert c1.delete(f"{API}/missions/{mid}", timeout=60).status_code == 403
        finally:
            sup.delete(f"{API}/missions/{mid}", timeout=60)

    def test_client_cannot_patch_echeance(self, superviseur, client1):
        sup, _ = superviseur
        c1, u1 = client1
        eid = sup.post(f"{API}/echeances", json={"tenant_id": u1["id"], "title": "TEST RBAC Ech",
                                                 "due_date": "2026-08-10"}, timeout=60).json()["id"]
        try:
            assert c1.patch(f"{API}/echeances/{eid}", json={"status": "traitee"}, timeout=60).status_code == 403
            assert c1.delete(f"{API}/echeances/{eid}", timeout=60).status_code == 403
        finally:
            sup.delete(f"{API}/echeances/{eid}", timeout=60)

    def test_client_cannot_spoof_tenant_on_upload(self, client1, client2):
        """A client forcing tenant_id must still land on their own tenant."""
        c1, u1 = client1
        _, u2 = client2
        files = {"file": ("TEST_spoof.txt", b"contenu de test facture 2026", "text/plain")}
        r = c1.post(f"{API}/documents", files=files, data={"kind": "autre", "tenant_id": u2["id"]}, timeout=90)
        assert r.status_code == 200, r.text
        doc = r.json()
        try:
            assert doc["tenant_id"] == u1["id"], "client managed to spoof tenant_id"
        finally:
            c1.delete(f"{API}/documents/{doc['id']}", timeout=60)

    def test_deactivated_account_cannot_login_or_use_token(self, superviseur):
        sup, _ = superviseur
        email = f"test_deact_{uuid.uuid4().hex[:8]}@albarka-demo.bf"
        uid = sup.post(f"{API}/clients", json={"email": email, "full_name": "TEST Deactivated",
                                               "password": "TestPass2026!"}, timeout=60).json()["id"]
        TestRbacEdge.created_users.append(uid)
        _grant_active_contract(sup, uid)
        token, _ = login_full(email, "TestPass2026!")
        sup.patch(f"{API}/clients/{uid}", json={"is_active": False}, timeout=60)

        r = requests.post(f"{API}/auth/login", json={"email": email, "password": "TestPass2026!"}, timeout=60)
        assert r.status_code == 403, f"deactivated login should be 403, got {r.status_code}"
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=60)
        assert me.status_code == 403, f"existing token of deactivated user should be rejected, got {me.status_code}"

    def test_token_of_deleted_user_rejected(self, superviseur):
        sup, _ = superviseur
        email = f"test_del_{uuid.uuid4().hex[:8]}@albarka-demo.bf"
        uid = sup.post(f"{API}/clients", json={"email": email, "full_name": "TEST Deleted",
                                               "password": "TestPass2026!"}, timeout=60).json()["id"]
        _grant_active_contract(sup, uid)
        token, _ = login_full(email, "TestPass2026!")
        sup.delete(f"{API}/clients/{uid}", timeout=60)
        me = requests.get(f"{API}/auth/me", headers={"Authorization": f"Bearer {token}"}, timeout=60)
        assert me.status_code == 401, me.status_code

    def test_patch_client_empty_payload_400(self, superviseur):
        sup, user = superviseur
        r = sup.patch(f"{API}/clients/{user['id']}", json={}, timeout=60)
        assert r.status_code == 400, r.status_code
