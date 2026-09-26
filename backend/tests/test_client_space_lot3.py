"""Lot 3 (suite) — Caissier, administrateur réservé au compte admin, espace client.

- Caissier : seul habilité à encaisser et à délivrer un reçu ; chaque
  encaissement délivre un reçu automatiquement ;
- Administrateur : rôle ignoré sur tout autre compte que le compte admin ;
- Espace client : dépôts sans OCR, mise à disposition des factures de la
  Caisse, modules ouverts par client, notification WhatsApp à modèles
  réglables (message libre dans la fenêtre de 24 h, modèle Meta sinon,
  repli e-mail).

Tests autonomes : MongoDB simulé (mongomock-motor), envois, PDF et stockage
remplacés par des doublures — aucun serveur, aucune clé, aucun réseau.
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
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")

import db as db_module  # noqa: E402
import albarka_admin_settings  # noqa: E402
import albarka_auth  # noqa: E402
import albarka_billing_docs  # noqa: E402
import albarka_client_space as cs  # noqa: E402
import albarka_clients  # noqa: E402
import albarka_missions  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_storage  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402
from albarka_models import effective_roles  # noqa: E402
from albarka_notifications import _assert_safe_email  # noqa: E402

ADMIN = {"id": "u-admin", "email": "admin@sawalismartsystems.com", "full_name": "Admin", "roles": ["superviseur", "direction"], "is_active": True}
USERS = {
    "admin": ADMIN,
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "secr_caisse": {"id": "u-sc", "email": "sc@albarka.bf", "full_name": "Secrétaire caissière", "roles": ["secretariat", "caissier"], "is_active": True},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "faux_admin": {"id": "u-fa", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg", "administrateur"], "is_active": True},
    "c1": {"id": "c1", "email": "kabore@exemple.bf", "full_name": "SARL Kaboré", "company": "Kaboré & Fils", "phone": "+22670000001", "roles": ["client"], "is_active": True},
    "c2": {"id": "c2", "email": "o@exemple.bf", "full_name": "Ets Ouédraogo", "phone": "+22670000002", "roles": ["client"], "is_active": True},
    "c3": {"id": "c3", "email": "n@exemple.bf", "full_name": "Refus notifs", "phone": "+22670000003", "roles": ["client"], "is_active": True, "can_receive_notifications": False},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_cs_test"]
    real_db = db_module.db
    # Chaque module a importé `db` : on remplace la base partout où elle est référencée
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))

    sent = {"wa": [], "tpl": [], "email": [], "files": {}}
    state = {"window": True}

    async def fake_wa(*, to_phone, message):
        sent["wa"].append({"to": to_phone, "text": message})
        return {"ok": True, "kind": "success", "outside_24h_window": state["window"] is False}

    async def fake_tpl(*, to_phone, template_name, language="fr", body_params=None):
        sent["tpl"].append({"to": to_phone, "name": template_name, "lang": language, "params": body_params})
        return {"ok": True}

    async def fake_window(phone):
        return state["window"]

    async def fake_email(*, to, subject, html, **kw):
        _assert_safe_email(subject, html)  # vrais garde-fous Albarka
        sent["email"].append({"to": to, "subject": subject})
        return "mail-1"

    async def fake_save(db_, *, data, kind, tenant_id, ext, content_type=None, original_filename=None, user_id=None):
        path = f"{kind}/{tenant_id}/{len(sent['files']) + 1}.{ext}"
        sent["files"][path] = data
        return {"id": f"s{len(sent['files'])}", "path": path, "size": len(data), "content_type": content_type or "application/pdf"}

    async def fake_get(path):
        return sent["files"][path], "application/pdf"

    async def fake_put(path, data, ct):
        sent["files"][path] = data

    async def fake_pdf(invoice):
        return b"%PDF-" + invoice["number"].encode()

    async def fake_log(**kw):
        return None

    async def no_archive(**kw):
        return None

    monkeypatch.setattr(cs, "send_whatsapp", fake_wa)
    monkeypatch.setattr(cs, "send_whatsapp_template", fake_tpl)
    monkeypatch.setattr(cs, "wa_window_state", fake_window)
    monkeypatch.setattr(cs, "send_email", fake_email)
    monkeypatch.setattr(albarka_storage, "save_and_log", fake_save)
    monkeypatch.setattr(albarka_storage, "get_object", fake_get)
    monkeypatch.setattr(albarka_billing_docs, "put_object", fake_put)
    monkeypatch.setattr(albarka_billing_docs, "build_pdf_bytes", fake_pdf)
    monkeypatch.setattr(albarka_phase_c, "_log_platform_event", fake_log)
    monkeypatch.setattr(albarka_phase_c, "_auto_archive", no_archive)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_phase_c.billing_router, cs.router, cs.me_router, albarka_clients.router,
              albarka_missions.router, albarka_admin_settings.router):
        api.include_router(r)
    app.include_router(api)

    # Connexion simulée : X-User choisit le compte ; rôles effectifs comme en production
    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        u = asyncio.get_event_loop()  # noqa: F841 — garde la signature asynchrone
        doc = await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
        doc["roles"] = effective_roles(doc)
        return doc
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app, headers={"Origin": "https://albarka-bf.com"}) as client:
        yield type("Env", (), {"c": client, "sent": sent, "state": state, "db": mock_db})


def _h(u):
    return {"X-User": u}


def _invoice(env, user="secr", **extra):
    r = env.c.post("/api/billing/invoices", headers=_h(user), json={
        "tenant_id": "c1", "title": "Honoraires septembre", "document_type": "facture",
        "items": [{"label": "Tenue comptable", "quantity": 1, "unit_price": 100000, "tax_rate": 18}], **extra})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ Caissier
def test_only_caissier_can_encaisser_and_gets_a_receipt(env):
    inv = _invoice(env)
    pay = {"invoice_id": inv["id"], "amount": 50000, "method": "cash"}
    # Secrétaire ou comptable sans le rôle Caissier : refus
    assert env.c.post("/api/billing/payments", headers=_h("secr"), json=pay).status_code == 403
    assert env.c.post("/api/billing/payments", headers=_h("compta"), json=pay).status_code == 403
    # Secrétaire qui a AUSSI le rôle Caissier : encaissement + reçu délivré
    r = env.c.post("/api/billing/payments", headers=_h("secr_caisse"), json=pay)
    assert r.status_code == 200, r.text
    receipt = r.json()["receipt"]
    assert receipt["document_type"] == "recu" and receipt["number"].startswith("REC-") and receipt["total"] == 50000
    assert receipt["invoice_id"] == inv["id"] and r.json()["receipt_number"] == receipt["number"]
    facture = asyncio.run(env.db.invoices.find_one({"id": inv["id"]}))
    assert facture["status"] == "partial" and facture["paid_amount"] == 50000


def test_receipt_document_reserved_to_caissier(env):
    body = {"tenant_id": "c1", "title": "Reçu", "document_type": "recu",
            "items": [{"label": "Règlement", "quantity": 1, "unit_price": 1000, "tax_rate": 0}]}
    assert env.c.post("/api/billing/invoices", headers=_h("secr"), json=body).status_code == 403
    assert env.c.post("/api/billing/invoices", headers=_h("secr_caisse"), json=body).status_code == 200
    # Une proforma ne s'encaisse pas
    pro = _invoice(env, document_type="proforma")
    assert env.c.post("/api/billing/payments", headers=_h("secr_caisse"),
                      json={"invoice_id": pro["id"], "amount": 10}).status_code == 400


# ------------------------------------------------------------------ Administrateur
def test_administrateur_only_for_admin_account(env):
    assert "administrateur" in effective_roles(ADMIN)
    assert "administrateur" not in effective_roles(USERS["faux_admin"])
    # Création / attribution refusées sur tout autre compte, même par l'admin
    staff = {"email": "x@albarka.bf", "full_name": "X", "roles": ["administrateur"], "password": "motdepasse1"}
    assert env.c.post("/api/clients/staff", headers=_h("admin"), json=staff).status_code == 403
    assert env.c.patch("/api/clients/u-compta", headers=_h("admin"), json={"roles": ["comptable", "administrateur"]}).status_code == 403
    # La case Caissier s'attribue normalement
    assert env.c.patch("/api/clients/u-secr", headers=_h("admin"), json={"roles": ["secretariat", "caissier"]}).status_code == 200
    # Liste du personnel : rôles effectifs (le « faux » administrateur n'apparaît plus)
    listed = {u["id"]: u["roles"] for u in env.c.get("/api/clients/staff", headers=_h("admin")).json()}
    assert "administrateur" not in listed["u-fa"] and "administrateur" in listed["u-admin"]


def test_real_get_current_user_applies_effective_roles(env):
    from fastapi.security import HTTPAuthorizationCredentials
    token = albarka_auth.create_access_token("u-fa")
    u = asyncio.run(albarka_auth.get_current_user(HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)))
    assert u["roles"] == ["dg"]


# ------------------------------------------------------------------ Espace client
def test_upload_external_documents_notifies_client_once(env):
    files = [("files", ("facture-sage-042.pdf", b"%PDF-1", "application/pdf")),
             ("files", ("facture-sage-043.pdf", b"%PDF-2", "application/pdf"))]
    r = env.c.post("/api/client-space/documents", headers=_h("compta"), files=files,
                   data={"tenant_id": "c1", "category": "facture", "title": "Honoraires", "reference": "F-042", "amount": "150000"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert [i["title"] for i in body["items"]] == ["Honoraires (1)", "Honoraires (2)"]
    # UN seul message WhatsApp pour le dépôt, texte par défaut « facture »
    assert len(env.sent["wa"]) == 1 and body["notification"]["channel"] == "whatsapp"
    text = env.sent["wa"][0]["text"]
    assert "SARL Kaboré" in text and "Honoraires (1) (F-042) — 150 000 FCFA" in text and "https://albarka-bf.com/portal/documents-cabinet" in text
    # Aucune analyse OCR : rien dans documents / document_ocr_runs
    assert asyncio.run(env.db.document_ocr_runs.count_documents({})) == 0


def test_receipt_upload_reserved_to_caissier_and_bad_format(env):
    f = [("files", ("recu.pdf", b"%PDF", "application/pdf"))]
    assert env.c.post("/api/client-space/documents", headers=_h("compta"), files=f,
                      data={"tenant_id": "c1", "category": "recu"}).status_code == 403
    assert env.c.post("/api/client-space/documents", headers=_h("secr_caisse"), files=f,
                      data={"tenant_id": "c1", "category": "recu"}).status_code == 201
    bad = [("files", ("virus.exe", b"MZ", "application/octet-stream"))]
    assert env.c.post("/api/client-space/documents", headers=_h("compta"), files=bad,
                      data={"tenant_id": "c1", "category": "autre"}).status_code == 400


def test_custom_template_and_meta_template_outside_window(env):
    # Textes réglés dans Paramètres (clé inconnue refusée)
    assert env.c.put("/api/admin/settings", headers=_h("admin"), json={"client_docs_templates": {"inconnu": "x"}}).status_code == 400
    r = env.c.put("/api/admin/settings", headers=_h("admin"), json={
        "client_docs_templates": {"rapport": "{cabinet} : rapport « {titre} » pour {entreprise}. {lien}"},
        "client_docs_wa_template_name": "nouveau_document", "client_docs_wa_template_params": "client, nombre, lien"})
    assert r.status_code == 200 and r.json()["client_docs_wa_template_params"] == "client,nombre,lien"
    f = [("files", ("bilan.pdf", b"%PDF", "application/pdf"))]
    env.c.post("/api/client-space/documents", headers=_h("compta"), files=f,
               data={"tenant_id": "c1", "category": "rapport", "title": "Bilan 2025"})
    assert env.sent["wa"][-1]["text"] == "Cabinet ALBARKA : rapport « Bilan 2025 » pour Kaboré & Fils. https://albarka-bf.com/portal/documents-cabinet"
    # Hors fenêtre de 24 h : le modèle Meta est envoyé avec ses variables dans l'ordre réglé
    env.state["window"] = False
    env.c.post("/api/client-space/documents", headers=_h("compta"), files=f,
               data={"tenant_id": "c1", "category": "rapport", "title": "Bilan 2024"})
    assert env.sent["tpl"] == [{"to": "+22670000001", "name": "nouveau_document", "lang": "fr",
                                "params": ["SARL Kaboré", "1", "https://albarka-bf.com/portal/documents-cabinet"]}]
    # Aperçu du texte dans les paramètres
    prev = env.c.post("/api/client-space/preview", headers=_h("compta"), json={"category": "rapport"}).json()["text"]
    assert prev.startswith("Cabinet ALBARKA : rapport « Honoraires de septembre »")


def test_outside_window_without_meta_template_falls_back_to_email(env):
    env.state["window"] = False
    f = [("files", ("f.pdf", b"%PDF", "application/pdf"))]
    body = env.c.post("/api/client-space/documents", headers=_h("compta"), files=f,
                      data={"tenant_id": "c1", "category": "facture"}).json()
    assert body["notification"]["channel"] == "email" and "24 h" in body["notification"]["error"]
    assert env.sent["email"][0]["to"] == "kabore@exemple.bf"
    # Client qui a refusé les notifications : rien n'est envoyé
    body = env.c.post("/api/client-space/documents", headers=_h("compta"), files=f,
                      data={"tenant_id": "c3", "category": "facture"}).json()
    assert body["notification"]["ok"] is False and len(env.sent["email"]) == 1


def test_client_sees_only_visible_own_documents_and_invoices(env):
    f = [("files", ("a.pdf", b"%PDF-A", "application/pdf"))]
    env.c.post("/api/client-space/documents", headers=_h("compta"), files=f, data={"tenant_id": "c1", "category": "attestation", "title": "Attestation"})
    env.c.post("/api/client-space/documents", headers=_h("compta"), files=f, data={"tenant_id": "c1", "category": "courrier", "title": "Brouillon", "visible": "false"})
    env.c.post("/api/client-space/documents", headers=_h("compta"), files=f, data={"tenant_id": "c2", "category": "rapport", "title": "Autre client"})
    inv = _invoice(env)  # facture de la Caisse, pas encore mise à disposition
    mine = env.c.get("/api/me/space", headers=_h("c1")).json()["items"]
    assert [i["title"] for i in mine] == ["Attestation"] and mine[0]["is_new"] and "last_notification" not in mine[0]
    # Mise à disposition depuis la Caisse → visible + client prévenu
    r = env.c.post(f"/api/client-space/invoices/{inv['id']}/visibility", headers=_h("secr"), json={"visible": True})
    assert r.json()["notification"]["ok"] is True and "Honoraires septembre" in env.sent["wa"][-1]["text"]
    mine = {i["source"]: i for i in env.c.get("/api/me/space", headers=_h("c1")).json()["items"]}
    assert mine["invoice"]["reference"] == inv["number"] and mine["invoice"]["remaining"] == 118000
    # Ouverture : fichier servi, première lecture notée
    got = env.c.get(f"/api/me/space/invoice/{inv['id']}/file", headers=_h("c1"))
    assert got.status_code == 200 and got.content == b"%PDF-" + inv["number"].encode()
    staff_view = {i["id"]: i for i in env.c.get("/api/client-space/documents?tenant_id=c1", headers=_h("compta")).json()["items"]}
    assert staff_view[inv["id"]]["viewed_at"] and staff_view[inv["id"]]["visible"]
    # Un autre client ne peut pas l'ouvrir ; le reçu d'encaissement suit la visibilité de la facture
    assert env.c.get(f"/api/me/space/invoice/{inv['id']}/file", headers=_h("c2")).status_code == 404
    env.c.post("/api/billing/payments", headers=_h("secr_caisse"), json={"invoice_id": inv["id"], "amount": 118000})
    cats = sorted(i["category"] for i in env.c.get("/api/me/space", headers=_h("c1")).json()["items"])
    assert cats == ["attestation", "facture", "recu"]
    # Création avec la case « Visible dans l'espace client »
    _invoice(env, client_visible=True, title="Proforma 2027", document_type="proforma")
    assert len(env.c.get("/api/me/space", headers=_h("c1")).json()["items"]) == 4


def test_modules_closed_by_cabinet(env):
    env.c.put("/api/client-space/modules/c1", headers=_h("secr"), json={"modules": ["documents", "echeances"]})
    assert env.c.get("/api/client-space/modules/c1", headers=_h("compta")).json()["modules"] == ["documents", "echeances"]
    # Un comptable (hors gestion des clients) ne peut pas changer les modules
    assert env.c.put("/api/client-space/modules/c1", headers=_h("compta"), json={"modules": []}).status_code == 403
    assert env.c.get("/api/me/space", headers=_h("c1")).json()["items"] == []
    assert env.c.get("/api/missions", headers=_h("c1")).json() == []


def test_payment_receipt_not_counted_twice_in_summary(env):
    """Le reçu délivré à l'encaissement n'est pas une nouvelle vente :
    le « Facturé » et le « Reste dû » de la Caisse ne bougent pas."""
    inv = _invoice(env)
    env.c.post("/api/billing/payments", headers=_h("secr_caisse"), json={"invoice_id": inv["id"], "amount": 118000})
    s = env.c.get("/api/billing/summary", headers=_h("secr")).json()
    assert s["invoice_count"] == 1 and s["total_billed"] == 118000 and s["outstanding"] == 0 and s["total_paid"] == 118000
    # Un reçu fait à la main (vente payée comptant, sans facture) reste compté
    env.c.post("/api/billing/invoices", headers=_h("secr_caisse"), json={
        "tenant_id": "c1", "title": "Vente comptant", "document_type": "recu",
        "items": [{"label": "Conseil", "quantity": 1, "unit_price": 5000, "tax_rate": 0}]})
    assert env.c.get("/api/billing/summary", headers=_h("secr")).json()["total_billed"] == 123000


def test_superviseur_without_caissier_cannot_encaisser(env):
    """Pas de passe-droit superviseur : encaisser exige le rôle Caissier."""
    inv = _invoice(env)
    assert env.c.post("/api/billing/payments", headers=_h("sup"), json={"invoice_id": inv["id"], "amount": 1000}).status_code == 403
    recu = {"tenant_id": "c1", "title": "Reçu", "document_type": "recu",
            "items": [{"label": "Règlement", "quantity": 1, "unit_price": 1000, "tax_rate": 0}]}
    assert env.c.post("/api/billing/invoices", headers=_h("sup"), json=recu).status_code == 403
    f = [("files", ("recu.pdf", b"%PDF", "application/pdf"))]
    assert env.c.post("/api/client-space/documents", headers=_h("sup"), files=f,
                      data={"tenant_id": "c1", "category": "recu"}).status_code == 403
    assert env.c.get("/api/client-space/catalog", headers=_h("sup")).json()["can_issue_receipt"] is False
    # Un superviseur à qui l'on coche aussi « Caissier » peut encaisser
    asyncio.run(env.db.users.update_one({"id": "u-sup"}, {"$set": {"roles": ["superviseur", "caissier"]}}))
    assert env.c.post("/api/billing/payments", headers=_h("sup"), json={"invoice_id": inv["id"], "amount": 1000}).status_code == 200
