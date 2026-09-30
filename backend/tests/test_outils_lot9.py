"""Lot 9 — espace « Outils Numériques ».

- gestion (CRUD, ordre, image) réservée au compte admin du portail
  (admin@sawalismartsystems.com), refusée au Superviseur et à la Direction ;
- liste filtrée par visibilité et par public (clients / personnel) ;
- téléchargement : journalisé (IP réelle derrière le proxy, utilisateur,
  navigateur), redirection 302 pour http(s), flux FTP (ftplib simulé),
  lien signé à usage unique ;
- identifiants FTP masqués partout (liste admin, historique, journal) ;
- historique + export CSV réservés au super-admin.
Tests autonomes : MongoDB simulé (mongomock-motor).
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_outils  # noqa: E402
import albarka_phase_c  # noqa: E402,F401  (journal plateforme : base simulée)
import albarka_storage  # noqa: E402
from albarka_auth import create_access_token  # noqa: E402

USERS = {
    "admin": {"id": "u-admin", "email": "admin@sawalismartsystems.com", "full_name": "Admin",
              "roles": ["superviseur", "direction"], "is_active": True},
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "compta": {"id": "u-compta", "email": "compta@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "c1": {"id": "c1", "email": "card@exemple.bf", "full_name": "M. Client", "company": "CARD-IPRO SARL",
           "roles": ["client"], "is_active": True},
}
FTP_URL = "ftp://depot:S3cret!@ftp.albarka-bf.com/logiciels/Setup%20Albarka.exe"


def H(key: str, **extra) -> dict:
    return {"Authorization": f"Bearer {create_access_token(USERS[key]['id'])}", **extra}


class FakeConn:
    """Connexion de données FTP simulée : renvoie le contenu par morceaux."""
    def __init__(self, data: bytes):
        self.data, self.closed = data, False

    def recv(self, n):
        chunk, self.data = self.data[:n], self.data[n:]
        return chunk

    def close(self):
        self.closed = True


class FakeFTP:
    """Remplace ftplib.FTP : mémorise la connexion pour vérification."""
    instances: list = []
    content = b"MZ" + b"x" * 200_000

    def __init__(self):
        self.calls = []
        FakeFTP.instances.append(self)

    def connect(self, host, port, timeout=None):
        self.calls.append(("connect", host, port))

    def login(self, user, password):
        self.calls.append(("login", user, password))

    def voidcmd(self, cmd):
        self.calls.append(("voidcmd", cmd))

    def size(self, path):
        return len(self.content)

    def transfercmd(self, cmd):
        self.calls.append(("transfercmd", cmd))
        return FakeConn(self.content)

    def voidresp(self):
        self.calls.append(("voidresp",))

    def quit(self):
        self.calls.append(("quit",))

    def close(self):
        pass


@pytest.fixture()
def env(monkeypatch, tmp_path):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot9_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    # Stockage local temporaire (pas de R2 pendant les tests)
    monkeypatch.setattr(albarka_storage, "UPLOAD_DIR", tmp_path)
    for k in ("R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
        monkeypatch.delenv(k, raising=False)
    FakeFTP.instances = []
    monkeypatch.setattr(albarka_outils.ftplib, "FTP", FakeFTP)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(albarka_outils.router)
    app.include_router(api)
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _create(c, **fields):
    body = {"caption": "Outil", "link": "https://exemple.bf/f.pdf", "version": "1.0", "size_label": "2 Mo",
            "icon": "pdf", "visible": True, "audience": "tous", **fields}
    r = c.post("/api/outils-numeriques/admin/outils", headers=H("admin"), json=body)
    assert r.status_code == 200, r.text
    return r.json()


def test_crud_reserved_to_super_admin(env):
    c = env.c
    body = {"caption": "Logiciel", "link": "https://exemple.bf/a.exe"}
    # Superviseur, Direction, comptable, client : refusés (403) — y compris l'historique
    for who in ("sup", "dir", "compta", "c1"):
        assert c.post("/api/outils-numeriques/admin/outils", headers=H(who), json=body).status_code == 403
        assert c.get("/api/outils-numeriques/admin/outils", headers=H(who)).status_code == 403
        assert c.get("/api/outils-numeriques/admin/telechargements", headers=H(who)).status_code == 403
        assert c.get("/api/outils-numeriques/admin/telechargements/csv", headers=H(who)).status_code == 403
    assert c.get("/api/outils-numeriques/admin/outils").status_code in (401, 403)
    # Super-admin : création, validation, modification, ordre, suppression
    t1 = _create(c, caption="Logiciel", link="https://exemple.bf/a.exe", icon="logiciel", size_label="120 Mo")
    assert t1["caption"] == "Logiciel" and t1["size_label"] == "120 Mo" and t1["visible"] and t1["audience"] == "tous"
    assert c.post("/api/outils-numeriques/admin/outils", headers=H("admin"),
                  json={"caption": "X", "link": "javascript:alert(1)"}).status_code == 400
    assert c.post("/api/outils-numeriques/admin/outils", headers=H("admin"),
                  json={"caption": "X", "link": "ftp://hote.bf/"}).status_code == 400
    assert c.post("/api/outils-numeriques/admin/outils", headers=H("admin"),
                  json={"caption": "", "link": "https://a.bf/x"}).status_code == 400
    assert c.post("/api/outils-numeriques/admin/outils", headers=H("admin"),
                  json={"caption": "X", "link": "https://a.bf/x", "icon": "inconnue"}).status_code == 400
    t2 = _create(c, caption="Guide PDF")
    upd = c.put(f"/api/outils-numeriques/admin/outils/{t1['id']}", headers=H("admin"),
                json={"version": "2.1", "visible": False, "link": ""}).json()
    assert upd["version"] == "2.1" and not upd["visible"] and upd["link_masked"] == "https://exemple.bf/a.exe"
    order = c.post("/api/outils-numeriques/admin/outils/reorder", headers=H("admin"),
                   json={"ids": [t2["id"], t1["id"]]}).json()["items"]
    assert [t["id"] for t in order] == [t2["id"], t1["id"]]
    # Image envoyée vers le stockage puis lue par un utilisateur autorisé
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = c.post(f"/api/outils-numeriques/admin/outils/{t2['id']}/image", headers=H("admin"),
               files={"file": ("logo.png", png, "image/png")})
    assert r.status_code == 200 and r.json()["has_image"]
    assert c.post(f"/api/outils-numeriques/admin/outils/{t2['id']}/image", headers=H("admin"),
                  files={"file": ("x.svg", b"<svg/>", "image/svg+xml")}).status_code == 400
    img = c.get(f"/api/outils-numeriques/{t2['id']}/image", headers=H("c1"))
    assert img.status_code == 200 and img.content == png
    assert c.delete(f"/api/outils-numeriques/admin/outils/{t1['id']}", headers=H("sup")).status_code == 403
    assert c.delete(f"/api/outils-numeriques/admin/outils/{t1['id']}", headers=H("admin")).json()["ok"]
    assert len(c.get("/api/outils-numeriques/admin/outils", headers=H("admin")).json()["items"]) == 1


def test_visibility_by_audience(env):
    c = env.c
    both = _create(c, caption="Pour tous")
    clients = _create(c, caption="Clients seulement", audience="clients")
    staff = _create(c, caption="Personnel seulement", audience="personnel")
    _create(c, caption="Masqué", visible=False)
    seen_client = [t["caption"] for t in c.get("/api/outils-numeriques", headers=H("c1")).json()["items"]]
    seen_staff = [t["caption"] for t in c.get("/api/outils-numeriques", headers=H("compta")).json()["items"]]
    assert seen_client == ["Pour tous", "Clients seulement"]
    assert seen_staff == ["Pour tous", "Personnel seulement"]
    # Jamais de lien dans la vue utilisateur
    assert all("link" not in t and "link_masked" not in t for t in c.get("/api/outils-numeriques", headers=H("c1")).json()["items"])
    # Un outil non destiné à l'utilisateur ne se télécharge pas
    assert c.get(f"/api/outils-numeriques/{staff['id']}/telecharger", headers=H("c1"),
                 follow_redirects=False).status_code == 404
    assert c.post(f"/api/outils-numeriques/{clients['id']}/lien", headers=H("compta")).status_code == 404
    assert c.get(f"/api/outils-numeriques/{both['id']}/telecharger", follow_redirects=False).status_code == 401


def test_http_redirect_and_logging_with_real_ip(env):
    c = env.c
    t = _create(c, caption="Guide", link="https://cdn.exemple.bf/guide.pdf", version="3.0")
    r = c.get(f"/api/outils-numeriques/{t['id']}/telecharger", follow_redirects=False,
              headers=H("c1", **{"X-Forwarded-For": "41.207.10.20, 10.0.0.1", "User-Agent": "Mozilla/5.0 Test"}))
    assert r.status_code == 302 and r.headers["location"] == "https://cdn.exemple.bf/guide.pdf"
    logs = asyncio.run(env.db.digital_tool_downloads.find({}, {"_id": 0}).to_list(10))
    assert len(logs) == 1
    log = logs[0]
    assert log["ip"] == "41.207.10.20" and log["user_id"] == "c1" and log["user_email"] == "card@exemple.bf"
    assert log["user_type"] == "client" and log["user_company"] == "CARD-IPRO SARL" and log["tool_version"] == "3.0"
    assert log["user_agent"] == "Mozilla/5.0 Test" and log["status"] == "ok" and log["created_at"].endswith("+00:00")
    assert c.get("/api/outils-numeriques/admin/outils", headers=H("admin")).json()["items"][0]["download_count"] == 1


def test_ftp_stream_and_credentials_masked(env):
    c = env.c
    t = _create(c, caption="Logiciel Albarka", link=FTP_URL, icon="logiciel")
    # Liste admin : identifiants masqués
    item = c.get("/api/outils-numeriques/admin/outils", headers=H("admin")).json()["items"][0]
    assert item["link_masked"] == "ftp://***@ftp.albarka-bf.com/logiciels/Setup%20Albarka.exe"
    assert item["has_credentials"] and "S3cret" not in str(item) and "depot" not in str(item)
    # Lien signé -> flux FTP
    link = c.post(f"/api/outils-numeriques/{t['id']}/lien", headers=H("compta")).json()
    assert "S3cret" not in link["path"]
    r = c.get(f"/api/outils-numeriques{link['path'].split('/outils-numeriques', 1)[1]}",
              headers={"X-Forwarded-For": "196.28.1.2"})
    assert r.status_code == 200 and r.content == FakeFTP.content
    assert 'filename="Setup_Albarka.exe"' in r.headers["content-disposition"]
    assert r.headers["content-length"] == str(len(FakeFTP.content))
    ftp = FakeFTP.instances[-1]
    assert ("connect", "ftp.albarka-bf.com", 21) in ftp.calls and ("login", "depot", "S3cret!") in ftp.calls
    assert ("transfercmd", "RETR logiciels/Setup Albarka.exe") in ftp.calls and ("quit",) in ftp.calls
    # Le lien signé est à usage unique
    again = c.get(f"/api/outils-numeriques{link['path'].split('/outils-numeriques', 1)[1]}")
    assert again.status_code == 410
    # Historique : IP réelle, personnel, identifiants jamais enregistrés
    hist = c.get("/api/outils-numeriques/admin/telechargements", headers=H("admin")).json()
    assert hist["total"] == 1
    h = hist["items"][0]
    assert h["ip"] == "196.28.1.2" and h["user_type"] == "personnel" and h["via"] == "lien signé" and h["protocol"] == "ftp"
    assert "S3cret" not in str(h) and "depot:" not in str(h)
    # Serveur FTP en panne : 502 sans fuite, tentative tracée en erreur
    def boom(self, *a, **k):
        raise OSError("connexion refusée")
    FakeFTP.connect = boom
    try:
        r = c.get(f"/api/outils-numeriques/{t['id']}/telecharger", headers=H("compta"))
        assert r.status_code == 502 and "S3cret" not in r.text and "ftp.albarka" not in r.text
    finally:
        del FakeFTP.connect
    assert asyncio.run(env.db.digital_tool_downloads.count_documents({"status": "erreur"})) == 1
    # Aucun identifiant dans le journal plateforme
    logs = asyncio.run(env.db.platform_logs.find({}, {"_id": 0}).to_list(50))
    assert logs and "S3cret" not in str(logs)


def test_history_filters_and_csv(env):
    c = env.c
    a = _create(c, caption="Outil A", link="https://a.bf/a.zip", icon="archive")
    b = _create(c, caption="Outil B", link="https://b.bf/b.xlsx", icon="tableur")
    for who, tool in (("c1", a), ("compta", a), ("compta", b)):
        c.get(f"/api/outils-numeriques/{tool['id']}/telecharger", headers=H(who), follow_redirects=False)
    base = "/api/outils-numeriques/admin/telechargements"
    items = c.get(base, headers=H("admin")).json()["items"]
    assert len(items) == 3 and items[0]["created_at"] >= items[-1]["created_at"]  # plus récent en premier
    assert c.get(base, headers=H("admin"), params={"tool_id": a["id"]}).json()["total"] == 2
    assert c.get(base, headers=H("admin"), params={"user": "card@"}).json()["total"] == 1
    assert c.get(base, headers=H("admin"), params={"user_type": "personnel"}).json()["total"] == 2
    assert c.get(base, headers=H("admin"), params={"date_from": "2000-01-01", "date_to": "2000-12-31"}).json()["total"] == 0
    assert c.get(base, headers=H("admin"), params={"date_from": "hier"}).status_code == 400
    csv_r = c.get(f"{base}/csv", headers=H("admin"), params={"tool_id": a["id"]})
    assert csv_r.status_code == 200 and csv_r.headers["content-type"].startswith("text/csv")
    text = csv_r.content.decode("utf-8")
    assert text.startswith("﻿") and "Date/heure (UTC);Outil;Version" in text
    assert text.count("Outil A") == 2 and "Outil B" not in text
