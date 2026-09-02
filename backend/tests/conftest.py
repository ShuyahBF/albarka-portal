"""Shared fixtures for ALBARKA backend tests."""
import os

import pytest
import requests
from dotenv import dotenv_values

frontend_env = dotenv_values("/app/frontend/.env")
_base = os.environ.get("REACT_APP_BACKEND_URL") or frontend_env.get("REACT_APP_BACKEND_URL")
if not _base:
    raise RuntimeError("REACT_APP_BACKEND_URL missing")
BASE_URL = _base.rstrip("/")
API = f"{BASE_URL}/api"

CREDENTIALS = {
    "superviseur": ("superviseur@albarka-demo.bf", "Superviseur2026!"),
    "comptable": ("comptable@albarka-demo.bf", "Comptable2026!"),
    "client1": ("client1@albarka-demo.bf", "Client2026!"),
    "client2": ("client2@albarka-demo.bf", "Client2026!"),
}


def login_full(email, password):
    """Two-step login: /auth/login -> dev_otp -> /auth/verify-otp. Returns (token, user)."""
    r = requests.post(f"{API}/auth/login", json={"email": email, "password": password}, timeout=60)
    if r.status_code != 200:
        pytest.fail(f"login failed for {email}: {r.status_code} {r.text[:300]}")
    body = r.json()
    if not body.get("dev_otp"):
        pytest.fail(f"no dev_otp returned for {email}: {body}")
    v = requests.post(
        f"{API}/auth/verify-otp",
        json={"session_token": body["session_token"], "code": body["dev_otp"]},
        timeout=60,
    )
    if v.status_code != 200:
        pytest.fail(f"verify-otp failed for {email}: {v.status_code} {v.text[:300]}")
    data = v.json()
    return data["access_token"], data["user"]


def make_session(email, password):
    token, user = login_full(email, password)
    s = requests.Session()
    s.headers.update({"Authorization": f"Bearer {token}"})
    return s, user


@pytest.fixture(scope="session")
def api_url():
    return API


@pytest.fixture(scope="session")
def superviseur():
    return make_session(*CREDENTIALS["superviseur"])


@pytest.fixture(scope="session")
def comptable():
    return make_session(*CREDENTIALS["comptable"])


@pytest.fixture(scope="session")
def client1():
    return make_session(*CREDENTIALS["client1"])


@pytest.fixture(scope="session")
def client2():
    return make_session(*CREDENTIALS["client2"])
