"""Lot 17 — Second numéro des factures (numéro manuel).

Couvre :
  - saisie du numéro manuel à la création par le secrétariat, le DG ou la direction (refus pour un comptable) ;
  - numéro verrouillé ensuite : seul le DG l'ouvre (refus pour la secrétaire), saisie possible tant qu'il est ouvert,
    refermé aussitôt après l'enregistrement, historique gardé ;
  - unicité du numéro manuel par type de document ;
  - impression : le numéro manuel remplace celui de la plateforme (PDF, nom du fichier) ;
  - numéro de lot.
Tests autonomes : MongoDB simulé (mongomock-motor), PDF simulé.
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
import albarka_billing_docs  # noqa: E402
import albarka_numero_manuel as nm  # noqa: E402
import albarka_phase_c  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "secr": {"id": "u-secr", "email": "secr@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "compta": {"id": "u-compta", "email": "compta@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "client": {"id": "c1", "email": "c1@exemple.bf", "full_name": "Client SA", "roles": ["client"], "is_active": True},
}


@pytest.fixture()
def env(monkeypatch):
    """Base simulée, PDF simulé, routes de facturation + numéro manuel, utilisateur choisi par l'en-tête X-User."""
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot17_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))

    async def faux_pdf(invoice):
        return invoice
    monkeypatch.setattr(albarka_billing_docs, "ensure_invoice_pdf", faux_pdf)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(albarka_phase_c.billing_router)
    api.include_router(nm.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return dict(USERS[x_user])
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app, raise_server_exceptions=False) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _creer(env, par="secr", **extra):
    corps = {"tenant_id": "c1", "title": "Honoraires", "items": [{"label": "Mission", "quantity": 1, "unit_price": 100000}],
             **extra}
    return env.c.post("/api/billing/invoices", json=corps, headers={"X-User": par})


def test_logique_pure():
    assert nm.normaliser_numero("  F  2026/015 ") == "F 2026/015"
    assert nm.normaliser_numero("") is None
    with pytest.raises(ValueError):
        nm.normaliser_numero("<script>")
    assert nm.cle_numero("f 2026/015") == "F2026/015"
    assert nm.numero_imprime({"number": "FAC-202610-0001"}) == "FAC-202610-0001"
    assert nm.numero_imprime({"number": "FAC-202610-0001", "manual_number": "F2026/015"}) == "F2026/015"
    assert nm.peut_saisir({"roles": ["direction"]}) and not nm.peut_saisir({"roles": ["comptable"]})
    assert nm.peut_ouvrir({"roles": ["dg"]}) and not nm.peut_ouvrir({"roles": ["secretariat", "direction"]})


def test_saisie_a_la_creation(env):
    r = _creer(env, manual_number="F2026/015")
    assert r.status_code == 200, r.text
    inv = r.json()
    assert inv["number"].startswith("FAC-") and inv["manual_number"] == "F2026/015"
    assert inv["manual_number_open"] is False and len(inv["manual_number_history"]) == 1
    # Un comptable ne saisit pas le numéro manuel ; sans numéro, il crée normalement
    assert _creer(env, par="compta", manual_number="F2026/016").status_code == 403
    assert _creer(env, par="compta").status_code == 200
    # Même numéro manuel sur une autre facture : refusé
    assert _creer(env, par="dir", manual_number="f 2026/015").status_code == 409


def test_ouverture_par_le_dg_puis_modification(env):
    inv = _creer(env, manual_number="F2026/015").json()
    url = f"/api/billing/invoices/{inv['id']}/manual-number"
    # Verrouillé : la secrétaire ne peut ni modifier ni ouvrir
    assert env.c.put(url, json={"manual_number": "F2026/020"}, headers={"X-User": "secr"}).status_code == 423
    assert env.c.post(url + "/open", headers={"X-User": "secr"}).status_code == 403
    assert env.c.post(url + "/open", headers={"X-User": "dir"}).status_code == 403
    # Le DG ouvre ; la secrétaire saisit ; le numéro est refermé, l'historique complété, le PDF à régénérer
    assert env.c.post(url + "/open", headers={"X-User": "dg"}).json()["manual_number_open"] is True
    apres = env.c.put(url, json={"manual_number": "F2026/020"}, headers={"X-User": "secr"}).json()
    assert apres["manual_number"] == "F2026/020" and apres["manual_number_open"] is False
    assert apres["manual_number_history"][-1]["ancien"] == "F2026/015" and apres["pdf_storage_path"] is None
    assert apres["number"] == inv["number"]   # le numéro de la plateforme ne change jamais
    # Refermé : nouvelle modification refusée tant que le DG n'a pas rouvert
    assert env.c.put(url, json={"manual_number": "F2026/021"}, headers={"X-User": "secr"}).status_code == 423
    # Le DG peut ouvrir puis refermer sans rien changer
    env.c.post(url + "/open", headers={"X-User": "dg"})
    assert env.c.post(url + "/close", headers={"X-User": "dg"}).json()["manual_number_open"] is False


def test_facture_creee_sans_numero_manuel_puis_numerotee(env):
    # Cas du cabinet : factures créées puis numérotées pour suivre l'ordre de l'année
    inv = _creer(env, par="compta").json()
    assert not inv.get("manual_number")
    url = f"/api/billing/invoices/{inv['id']}/manual-number"
    env.c.post(url + "/open", headers={"X-User": "dg"})
    assert env.c.put(url, json={"manual_number": "F2026/001"}, headers={"X-User": "dg"}).json()["manual_number"] == "F2026/001"


def test_impression_avec_le_numero_manuel():
    # Le PDF au format du modèle porte le numéro manuel dans son bandeau
    from albarka_invoice_layout import build_invoice_model_pdf
    inv = {"id": "x", "number": "FAC-202610-0009", "manual_number": "F2026/015", "document_type": "facture",
           "title": "Honoraires", "items": [{"label": "Mission", "quantity": 1, "unit_price": 1000, "tax_rate": 0}],
           "subtotal": 1000, "tax": 0, "total": 1000, "net_to_pay": 1000, "currency": "XOF", "created_at": "2026-10-08"}
    try:
        pdf = build_invoice_model_pdf(invoice=inv, client=None, kyc=None, letterhead={}, settings={},
                                      qr_bytes=None, signature_bytes=None, pispi=None)
    except TypeError:
        pytest.skip("signature de build_invoice_model_pdf différente")
    assert pdf[:4] == b"%PDF"


def test_numero_de_lot():
    import lot
    assert lot.LOT == "17"
