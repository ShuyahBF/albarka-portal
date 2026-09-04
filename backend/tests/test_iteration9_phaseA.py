"""Iteration 9 - Phase A: role 'administrateur', PATCH /clients/{id}, last_login."""
import re
import secrets

import pytest
import requests

from conftest import API, login_full, make_session


# --- Feature 5: role administrateur ---------------------------------------
@pytest.fixture(scope="module")
def admin_only_user(superviseur_module):
    s, _ = superviseur_module
    email = f"test_admin_{secrets.token_hex(4)}@albarka-test.bf"
    password = "AdminTest2026!"
    r = s.post(f"{API}/clients/staff", json={
        "email": email,
        "full_name": "TEST Administrateur Seul",
        "roles": ["administrateur"],
        "password": password,
    }, timeout=60)
    assert r.status_code in (200, 201), f"{r.status_code} {r.text[:300]}"
    body = r.json()
    assert body["roles"] == ["administrateur"], body
    assert body["email"] == email.lower()
    assert "password_hash" not in body
    assert "_id" not in body
    yield body, password
    d = s.delete(f"{API}/clients/{body['id']}", timeout=60)
    assert d.status_code in (200, 204, 404)


@pytest.fixture(scope="module")
def superviseur_module():
    return make_session("superviseur@albarka-demo.bf", "Superviseur2026!")


@pytest.fixture(scope="module")
def comptable_module():
    return make_session("comptable@albarka-demo.bf", "Comptable2026!")


class TestAdministrateurRole:
    def test_role_persisted_via_get(self, superviseur_module, admin_only_user):
        s, _ = superviseur_module
        user, _pw = admin_only_user
        g = s.get(f"{API}/clients/{user['id']}", timeout=60)
        assert g.status_code == 200, g.text[:300]
        assert g.json()["roles"] == ["administrateur"]

    def test_admin_only_user_can_login_and_access_admin_endpoints(self, admin_only_user):
        user, password = admin_only_user
        token, me = login_full(user["email"], password)
        assert me["roles"] == ["administrateur"]
        s = requests.Session()
        s.headers.update({"Authorization": f"Bearer {token}"})

        g = s.get(f"{API}/admin/settings", timeout=60)
        assert g.status_code == 200, f"GET settings: {g.status_code} {g.text[:300]}"
        assert "cabinet_name" in g.json()

        p = s.put(f"{API}/admin/settings", json={"cabinet_phone": "+22670000009"}, timeout=60)
        assert p.status_code == 200, f"PUT settings: {p.status_code} {p.text[:300]}"
        assert p.json()["cabinet_phone"] == "+22670000009"

        b = s.get(f"{API}/admin/branding", timeout=60)
        assert b.status_code == 200, f"GET branding: {b.status_code} {b.text[:300]}"

    def test_comptable_forbidden_on_admin_endpoints(self, comptable_module):
        s, me = comptable_module
        assert not set(me["roles"]) & {"superviseur", "direction", "administrateur"}
        assert s.get(f"{API}/admin/settings", timeout=60).status_code == 403
        assert s.put(f"{API}/admin/settings", json={"cabinet_phone": "x"}, timeout=60).status_code == 403
        assert s.get(f"{API}/admin/branding", timeout=60).status_code == 403

    def test_client_role_rejected_on_staff_creation(self, superviseur_module):
        s, _ = superviseur_module
        r = s.post(f"{API}/clients/staff", json={
            "email": f"test_bad_{secrets.token_hex(3)}@albarka-test.bf",
            "full_name": "TEST Bad",
            "roles": ["administrateur", "client"],
            "password": "AdminTest2026!",
        }, timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:200]}"


# --- Feature 13: last_login ------------------------------------------------
class TestLastLogin:
    def test_last_login_set_after_otp(self, superviseur_module):
        s, me = superviseur_module
        m = s.get(f"{API}/auth/me", timeout=60)
        assert m.status_code == 200, m.text[:200]
        body = m.json()
        assert "last_login" in body, body
        assert body["last_login"], "last_login is empty after successful login"


# --- Feature 6: PATCH /clients/{id} ---------------------------------------
class TestPatchUser:
    def test_patch_staff_fields_and_email_immutable(self, superviseur_module):
        s, _ = superviseur_module
        email = f"test_patch_{secrets.token_hex(4)}@albarka-test.bf"
        c = s.post(f"{API}/clients/staff", json={
            "email": email, "full_name": "TEST Avant", "roles": ["comptable"],
            "password": "PatchTest2026!",
        }, timeout=60)
        assert c.status_code in (200, 201), c.text[:300]
        uid = c.json()["id"]
        try:
            p = s.patch(f"{API}/clients/{uid}", json={
                "full_name": "TEST Apres",
                "roles": ["comptable", "administrateur"],
                "phone": "+22671234567",
                "is_active": False,
                "can_receive_notifications": False,
                "email": "hacker@evil.bf",
            }, timeout=60)
            assert p.status_code == 200, f"{p.status_code} {p.text[:300]}"
            d = p.json()
            assert d["full_name"] == "TEST Apres"
            assert set(d["roles"]) == {"comptable", "administrateur"}
            assert d["phone"] == "+22671234567"
            assert d["is_active"] is False
            assert d["can_receive_notifications"] is False
            assert d["email"] == email.lower(), "email must not be mutable"

            g = s.get(f"{API}/clients/{uid}", timeout=60)
            assert g.status_code == 200
            gd = g.json()
            assert gd["full_name"] == "TEST Apres"
            assert gd["email"] == email.lower()
            assert gd["is_active"] is False
            assert "_id" not in gd and "password_hash" not in gd
        finally:
            s.delete(f"{API}/clients/{uid}", timeout=60)

    def test_patch_client_company_phone(self, superviseur_module):
        s, _ = superviseur_module
        lst = s.get(f"{API}/clients", timeout=60)
        assert lst.status_code == 200
        clients = lst.json()
        assert clients, "no demo clients present"
        target = clients[0]
        original = {"company": target.get("company"), "phone": target.get("phone")}
        try:
            p = s.patch(f"{API}/clients/{target['id']}", json={
                "company": "TEST Company SARL", "phone": "+22670999888",
            }, timeout=60)
            assert p.status_code == 200, p.text[:300]
            assert p.json()["company"] == "TEST Company SARL"
            g = s.get(f"{API}/clients/{target['id']}", timeout=60).json()
            assert g["company"] == "TEST Company SARL"
            assert g["phone"] == "+22670999888"
            assert g["roles"] == ["client"]
        finally:
            s.patch(f"{API}/clients/{target['id']}", json={
                "company": original["company"] or "Sawadogo Import-Export SARL",
                "phone": original["phone"] or "+22670000001",
            }, timeout=60)

    def test_patch_invalid_role_rejected(self, superviseur_module):
        s, _ = superviseur_module
        lst = s.get(f"{API}/clients/staff", timeout=60).json()
        uid = lst[0]["id"]
        r = s.patch(f"{API}/clients/{uid}", json={"roles": ["not_a_role"]}, timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:200]}"

    def test_patch_unknown_user_404(self, superviseur_module):
        s, _ = superviseur_module
        r = s.patch(f"{API}/clients/does-not-exist", json={"full_name": "X"}, timeout=60)
        assert r.status_code == 404, f"{r.status_code} {r.text[:200]}"

    def test_patch_empty_payload_400(self, superviseur_module):
        s, _ = superviseur_module
        lst = s.get(f"{API}/clients/staff", timeout=60).json()
        r = s.patch(f"{API}/clients/{lst[0]['id']}", json={}, timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:200]}"

    def test_patch_requires_staff(self, api_url):
        s, _ = make_session("client1@albarka-demo.bf", "Client2026!")
        r = s.patch(f"{API}/clients/whatever", json={"full_name": "X"}, timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"


# --- Regression: client portal --------------------------------------------
class TestClientRegression:
    def test_client_sees_own_data(self):
        s, me = make_session("client1@albarka-demo.bf", "Client2026!")
        assert me["roles"] == ["client"]
        for path in ("/documents", "/missions", "/echeances"):
            r = s.get(f"{API}{path}", timeout=60)
            assert r.status_code == 200, f"{path}: {r.status_code} {r.text[:200]}"
            assert isinstance(r.json(), list)

    def test_client_cannot_list_clients(self):
        s, _ = make_session("client2@albarka-demo.bf", "Client2026!")
        assert s.get(f"{API}/clients", timeout=60).status_code == 403


# --- Security gaps found in iteration 9 phase A (documented, currently failing) ---
class TestRoleInvariantsOnPatch:
    """PATCH /clients/{id} does not enforce the 'client' role exclusivity nor a
    non-empty roles list, unlike POST /clients/staff. Marked xfail until fixed."""

    @pytest.mark.xfail(reason="UserUpdate.roles accepts 'client' mixed with staff roles", strict=False)
    def test_client_role_cannot_be_mixed_with_staff_roles(self, superviseur_module):
        s, _ = superviseur_module
        target = s.get(f"{API}/clients", timeout=60).json()[0]
        r = s.patch(f"{API}/clients/{target['id']}",
                    json={"roles": ["client", "administrateur"]}, timeout=60)
        if r.status_code == 200:
            s.patch(f"{API}/clients/{target['id']}", json={"roles": ["client"]}, timeout=60)
        assert r.status_code == 422, f"privilege escalation allowed: {r.status_code}"

    @pytest.mark.xfail(reason="UserUpdate.roles accepts an empty list", strict=False)
    def test_empty_roles_rejected(self, superviseur_module):
        s, _ = superviseur_module
        c = s.post(f"{API}/clients/staff", json={
            "email": f"test_empty_{secrets.token_hex(3)}@albarka-test.bf",
            "full_name": "TEST Empty Roles", "roles": ["comptable"],
            "password": "EmptyTest2026!"}, timeout=60)
        uid = c.json()["id"]
        try:
            r = s.patch(f"{API}/clients/{uid}", json={"roles": []}, timeout=60)
            assert r.status_code == 422, f"empty roles accepted: {r.status_code}"
        finally:
            s.delete(f"{API}/clients/{uid}", timeout=60)
