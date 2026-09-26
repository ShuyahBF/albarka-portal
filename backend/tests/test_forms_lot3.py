"""Formulaires (lot 3) — branchement Albarka du module commun forms_core.

Le module lui-même (constructeur, validation, statistiques, export) est testé
dans forms-core. Ici on vérifie uniquement ce qui est propre à Albarka :
  - accès réservé au rôle « formulaires » (+ superviseur), refusé aux autres ;
  - destinataires = clients actifs, canaux selon leur fiche et leur choix ;
  - e-mail d'invitation conforme aux garde-fous de sécurité Albarka ;
  - WhatsApp hors fenêtre 24 h expliqué en clair ;
  - client : « Mes formulaires » + réponse via son lien ; non-client : lien public ;
  - fichiers joints rangés dans le stockage Albarka puis relus.

Tests autonomes : MongoDB simulé (mongomock-motor), envois et stockage
remplacés par des doublures — aucun serveur, aucune clé, aucun réseau.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")

import albarka_forms as af  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402
from albarka_models import ALBARKA_ROLES, FORMS_ROLES, STAFF_ROLES  # noqa: E402
from albarka_notifications import _assert_safe_email  # noqa: E402
from forms_core import create_routers  # noqa: E402

# Comptes de test : un collaborateur par cas d'accès + des clients
USERS = {
    "form": {"id": "u-form", "full_name": "Awa Formulaires", "roles": ["comptable", "formulaires"], "is_active": True},
    "sup": {"id": "u-sup", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "compta": {"id": "u-compta", "full_name": "Comptable seul", "roles": ["comptable"], "is_active": True},
    "c1": {"id": "c1", "full_name": "SARL Kaboré", "email": "kabore@exemple.bf", "phone": "+22670000001",
           "company": "Kaboré", "roles": ["client"], "is_active": True},
    "c2": {"id": "c2", "full_name": "Ets Ouédraogo", "email": "ouedraogo@exemple.bf", "phone": "70000002",
           "roles": ["client"], "is_active": True, "can_receive_notifications": False},
    "c3": {"id": "c3", "full_name": "Client inactif", "email": "x@exemple.bf", "roles": ["client"], "is_active": False},
}

PAGES = [{"id": "p1", "title": "Votre avis", "fields": [
    {"id": "nom", "type": "text", "label": "Nom", "required": True},
    {"id": "note", "type": "rating", "label": "Satisfaction", "max": 5},
    {"id": "piece", "type": "file", "label": "Justificatif", "accept": ".pdf"},
]}]


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["albarka_forms_test"]
    import asyncio
    asyncio.run(db.users.insert_many([dict(u) for u in USERS.values()]))

    # Doublures des envois : on garde ce qui aurait été envoyé
    sent = {"email": [], "whatsapp": [], "stored": {}, "logs": []}

    async def fake_email(*, to, subject, html, **kw):
        _assert_safe_email(subject, html)  # les vrais garde-fous Albarka s'appliquent
        sent["email"].append({"to": to, "subject": subject, "html": html})
        return "mail-1"

    async def fake_wa(*, to_phone, message):
        sent["whatsapp"].append({"to": to_phone, "message": message})
        return {"ok": False, "kind": "http_error", "error": "x", "outside_24h_window": True}

    async def fake_name():
        return "Cabinet ALBARKA"

    async def fake_save(db_, *, data, kind, tenant_id, ext, content_type=None, original_filename=None, user_id=None):
        rid = f"obj{len(sent['stored']) + 1}"
        sent["stored"][rid] = data
        await db_.stored_objects.insert_one({"id": rid, "storage_path": f"{kind}/{tenant_id}/{rid}.{ext}", "kind": kind,
                                             "tenant_id": tenant_id, "content_type": content_type, "is_deleted": False})
        return {"id": rid}

    async def fake_presign(path, expires_in=300):
        return None  # stockage local : pas de lien temporaire

    async def fake_get(path):
        return sent["stored"][path.rsplit("/", 1)[-1].split(".")[0]], "application/pdf"

    async def fake_log(**kw):
        sent["logs"].append(kw["action"])

    monkeypatch.setattr(af, "send_email", fake_email)
    monkeypatch.setattr(af, "send_whatsapp", fake_wa)
    monkeypatch.setattr(af, "_get_from_name", fake_name)
    monkeypatch.setattr(af, "_log_platform_event", fake_log)
    monkeypatch.setattr(af.albarka_storage, "save_and_log", fake_save)
    monkeypatch.setattr(af.albarka_storage, "presigned_url", fake_presign)
    monkeypatch.setattr(af.albarka_storage, "get_object", fake_get)

    adapter = af.AlbarkaFormsAdapter(db)
    api = APIRouter(prefix="/api")
    for r in create_routers(adapter).values():
        api.include_router(r)
    app = FastAPI()
    app.include_router(api)

    # Connexion simulée : l'en-tête X-User choisit le compte de test
    async def fake_user(x_user: str = Header(default="")):
        from fastapi import HTTPException
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app, headers={"Origin": "https://albarka-bf.com"}) as client:
        yield type("Env", (), {"c": client, "sent": sent, "db": db})


def _h(u):
    return {"X-User": u}


def _create(env, **extra):
    r = env.c.post("/api/forms", headers=_h("form"), json={"title": "Satisfaction clients", "pages": PAGES, **extra})
    assert r.status_code == 201, r.text
    return r.json()


def test_role_formulaires_is_a_staff_role():
    """La case « Formulaires » existe côté serveur et reste un rôle du personnel."""
    assert "formulaires" in ALBARKA_ROLES and "formulaires" in STAFF_ROLES and FORMS_ROLES == ["formulaires"]


def test_frontend_menu_and_staff_checkbox_use_the_role():
    """Menu latéral réservé au rôle + case à cocher dans la fiche du personnel."""
    front = Path(__file__).resolve().parents[2] / "frontend" / "src"
    layout = (front / "components" / "PortalLayout.jsx").read_text(encoding="utf-8")
    assert 'const FORMS_ROLES = ["formulaires"];' in layout
    assert '{ to: "/admin/forms", label: "Formulaires", icon: ClipboardCheck, roles: FORMS_ROLES }' in layout
    staff = (front / "pages" / "admin" / "AdminStaff.jsx").read_text(encoding="utf-8")
    assert '{ value: "formulaires", label: "Formulaires" }' in staff


def test_only_formulaires_role_or_superviseur(env):
    assert env.c.get("/api/forms", headers=_h("compta")).status_code == 403
    assert env.c.get("/api/forms", headers=_h("c1")).status_code == 403
    assert env.c.get("/api/forms", headers=_h("form")).status_code == 200
    assert env.c.get("/api/forms", headers=_h("sup")).status_code == 200
    f = _create(env)
    assert f["number"] == "FORM-ALBARKA-0001" and "form_created" in env.sent["logs"]


def test_recipients_are_active_clients_with_their_channels(env):
    items = {r["id"]: r for r in env.c.get("/api/forms/recipients", headers=_h("form")).json()["items"]}
    assert set(items) == {"c1", "c2"}  # ni le personnel ni le client inactif
    assert items["c1"]["can_email"] and items["c1"]["can_whatsapp"] and items["c1"]["company"] == "Kaboré"
    # Notifications refusées par le client → aucun canal proposé
    assert not items["c2"]["can_email"] and not items["c2"]["can_whatsapp"]
    assert "phone" not in items["c1"] and "_user" not in items["c1"]


def test_send_to_clients_then_client_answers(env):
    f = _create(env)
    r = env.c.post(f"/api/forms/{f['id']}/invitations", headers=_h("form"),
                   json={"recipient_ids": ["c1", "c2"], "channels": ["email", "whatsapp"], "message": "Merci de votre confiance"})
    body = r.json()
    assert r.status_code == 200 and body["sent"] == 1 and body["failed"] == 1
    res = {x["recipient_id"]: x["results"] for x in body["results"]}
    # E-mail parti, lien https du portail, texte du bouton sans nom de domaine
    mail = env.sent["email"][0]
    assert mail["to"] == "kabore@exemple.bf" and "https://albarka-bf.com/f/" in mail["html"] and "Remplir le formulaire" in mail["html"]
    assert "Merci de votre confiance" in mail["html"]
    # WhatsApp refusé par Meta (fenêtre 24 h) : raison claire pour le personnel
    assert res["c1"]["whatsapp"]["ok"] is False and "24 h" in res["c1"]["whatsapp"]["error"]
    assert env.sent["whatsapp"][0]["to"] == "+22670000001"
    # Client ayant refusé les notifications : rien n'est envoyé
    assert res["c2"]["email"]["ok"] is False and len(env.sent["email"]) == 1

    # Espace client : le formulaire apparaît, puis le client répond via son lien
    mine = env.c.get("/api/me/forms", headers=_h("c1")).json()["items"]
    assert mine[0]["title"] == "Satisfaction clients" and not mine[0]["answered_at"]
    token = mine[0]["path"].rsplit("/", 1)[-1]
    pub = env.c.get(f"/api/public/forms/{token}").json()
    assert pub["recipient"]["name"] == "SARL Kaboré"
    assert env.c.post(f"/api/public/forms/{token}/submit", json={"data": {"nom": "Kaboré", "note": 5}}).status_code == 200
    assert env.c.get("/api/me/forms", headers=_h("c1")).json()["items"][0]["answered_at"]
    assert env.c.get("/api/me/forms", headers=_h("form")).json()["items"] == []  # le personnel n'a pas de « Mes formulaires »
    st = env.c.get(f"/api/forms/{f['id']}/stats", headers=_h("form")).json()
    assert st["total_submissions"] == 1 and st["invitations"]["answered"] == 1


def test_public_link_for_non_client_with_file(env):
    f = _create(env, settings={"respondent_info": "required"})
    link = env.c.post(f"/api/forms/{f['id']}/public-link", headers=_h("form"), json={"enabled": True}).json()
    assert link["url"].startswith("https://albarka-bf.com/f/")
    token = link["token"]
    up = env.c.post(f"/api/public/forms/{token}/upload", data={"field_id": "piece"},
                    files={"file": ("rccm.pdf", b"%PDF-1.4", "application/pdf")}).json()
    # Fichier d'un non-client rangé dans le dossier « forms-public » du stockage
    stored = __import__("asyncio").run(env.db.stored_objects.find_one({"id": up["file_id"]}))
    assert stored["kind"] == "form_upload" and stored["tenant_id"] == "forms-public"
    r = env.c.post(f"/api/public/forms/{token}/submit", json={
        "data": {"nom": "Prospect", "piece": up}, "respondent_name": "Issa", "respondent_email": "issa@exemple.bf"})
    assert r.status_code == 200
    # Stockage local : pas de lien temporaire → lecture directe du fichier
    assert env.c.get(f"/api/forms/{f['id']}/files/{up['file_id']}", headers=_h("form")).json() == {"url": None}
    content = env.c.get(f"/api/forms/{f['id']}/files/{up['file_id']}/content", headers=_h("form"))
    assert content.status_code == 200 and content.content == b"%PDF-1.4"


def test_links_are_always_https(env):
    """Portail ouvert en http (poste local, aperçu) : les liens envoyés
    utilisent l'adresse officielle en https, sinon l'e-mail serait refusé."""
    f = _create(env)
    r = env.c.post(f"/api/forms/{f['id']}/invitations", headers={**_h("form"), "Origin": "http://127.0.0.1:3000"},
                   json={"recipient_ids": ["c1"], "channels": ["email"]})
    assert r.json()["sent"] == 1 and "https://albarka-bf.com/f/" in env.sent["email"][0]["html"]
