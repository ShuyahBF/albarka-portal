"""Lot 14 — Encaissement PI-SPI (paiement instantané BCEAO).

Couvre : paramètres globaux (droits Superviseur / Direction, contrôles,
image du QR ≤ 1 Mo), QR généré à partir du texte fourni par la banque SANS
modification, bloc « Payer par PI-SPI » présent seulement si actif et facture
non soldée (proforma : modalités sans montant), mode de règlement PISPI avec
référence bancaire et trace dans pispi_transactions, connecteurs bancaires
« non disponible », route de notification désactivée, variables PISPI_* de
render.yaml et numéro de lot.
Tests autonomes : MongoDB simulé (mongomock-motor), stockage local temporaire.
"""
from __future__ import annotations

import asyncio
import io
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
fitz = pytest.importorskip("fitz")

import db as db_module  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_pispi  # noqa: E402
import albarka_storage  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

RACINE = Path(__file__).resolve().parents[2]

# Comptes de test (le Superviseur passe partout, la Direction règle PI-SPI)
USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dg@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "caisse": {"id": "u-cai", "email": "c@albarka.bf", "full_name": "Caissier", "roles": ["caissier"], "is_active": True},
    "c1": {"id": "c1", "email": "ct1@exemple.bf", "full_name": "Client Test 1", "roles": ["client"], "is_active": True},
}

# Texte « décodé » d'un QR bancaire fictif, avec espaces et caractères
# spéciaux : il doit être encodé tel quel
QR_TEXTE = "000201 PISPI|alias=albarka.cabinet@uba ; nom=Cabinet ALBARKA ✓ "


# ---------------------------------------------------------------- environnement
@pytest.fixture()
def env(monkeypatch, tmp_path):
    """Base simulée branchée dans tous les modules, API minimale avec
    l'utilisateur choisi par l'en-tête X-User."""
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot14_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_storage, "UPLOAD_DIR", tmp_path)
    monkeypatch.delenv("PISPI_FOURNISSEUR", raising=False)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_pispi.router, albarka_pispi.notification_router, albarka_phase_c.billing_router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app, raise_server_exceptions=False) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _h(u):
    return {"X-User": u}


def _activer(env, **extra):
    """Paramètres PI-SPI actifs avec le QR donné en texte."""
    body = {"actif": True, "banque": "uba", "titulaire": "Cabinet ALBARKA",
            "adresse_paiement": "albarka.cabinet@uba", "qr_contenu": QR_TEXTE, **extra}
    r = env.c.put("/api/admin/pispi", json=body, headers=_h("dir"))
    assert r.status_code == 200, r.text
    return r.json()


def _png(size=(120, 120)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


def _facture(**over) -> dict:
    inv = {"id": "inv-1", "number": "FAC-202610-0007", "document_type": "facture", "tenant_id": "c1",
           "issue_date": "2026-10-04", "status": "unpaid", "verify_token": "tok-1",
           "items": [{"label": "Tenue de la comptabilité", "quantity": 1, "unit_price": 100000, "tax_rate": 18}],
           "subtotal": 100000, "tax": 18000, "total": 118000, "net_to_pay": 118000, "paid_amount": 0}
    inv.update(over)
    return inv


def _pdf_texte(env, invoice: dict) -> str:
    """PDF « modèle » de la facture (comme en production), texte extrait."""
    from albarka_billing_docs import build_model_pdf
    asyncio.run(env.db.invoices.insert_one(dict(invoice)))
    pdf = asyncio.run(build_model_pdf(dict(invoice), USERS["c1"]))
    doc = fitz.open("pdf", pdf)
    texte = "\n".join(page.get_text() for page in doc)
    doc.close()
    return texte


# ---------------------------------------------------------------- 1. paramètres
def test_parametres_par_defaut_inactifs(env):
    r = env.c.get("/api/admin/pispi", headers=_h("sup"))
    assert r.status_code == 200
    d = r.json()
    assert d["actif"] is False and d["qr_present"] is False
    assert set(d["banques"].values()) == {"UBA", "BSIC", "IB Bank", "Ecobank", "Autre"}
    assert "PI-SPI" in d["consigne"]


def test_parametres_reserves_superviseur_direction(env):
    assert env.c.get("/api/admin/pispi", headers=_h("secr")).status_code == 403
    assert env.c.put("/api/admin/pispi", json={"titulaire": "X"}, headers=_h("caisse")).status_code == 403
    assert env.c.put("/api/admin/pispi", json={"titulaire": "X"}, headers=_h("sup")).status_code == 200
    d = _activer(env)
    assert d["actif"] is True and d["qr_present"] is True and d["adresse_paiement"] == "albarka.cabinet@uba"
    # le chemin interne de stockage n'est jamais renvoyé
    assert "qr_image_path" not in d


def test_parametres_controles(env):
    # Banque inconnue refusée
    r = env.c.put("/api/admin/pispi", json={"banque": "banque_x"}, headers=_h("dir"))
    assert r.status_code == 400
    # « Autre » avec un libellé libre
    d = env.c.put("/api/admin/pispi", json={"banque": "autre", "banque_autre": "Coris Bank"}, headers=_h("dir")).json()
    assert albarka_pispi.libelle_banque(d) == "Coris Bank"
    # Activation impossible sans adresse de paiement ni QR
    r = env.c.put("/api/admin/pispi", json={"actif": True}, headers=_h("dir"))
    assert r.status_code == 400


def test_image_du_qr_televersee(env):
    gros = b"\x89PNG" + b"0" * (1024 * 1024 + 10)
    r = env.c.post("/api/admin/pispi/qr", files={"file": ("qr.png", gros, "image/png")}, headers=_h("dir"))
    assert r.status_code == 413
    r = env.c.post("/api/admin/pispi/qr", files={"file": ("qr.gif", b"GIF89a", "image/gif")}, headers=_h("dir"))
    assert r.status_code == 400
    image = _png()
    r = env.c.post("/api/admin/pispi/qr", files={"file": ("qr.png", image, "image/png")}, headers=_h("dir"))
    assert r.status_code == 200 and r.json()["qr_image_presente"] is True
    # L'image est imprimée TELLE QUELLE (prioritaire sur le texte)
    p = asyncio.run(albarka_pispi.charger_parametres())
    assert asyncio.run(albarka_pispi.qr_pispi_bytes(p)) == image
    assert env.c.get("/api/admin/pispi/qr", headers=_h("dir")).content == image
    # Retrait de l'image
    assert env.c.delete("/api/admin/pispi/qr", headers=_h("dir")).json()["qr_image_presente"] is False


# ---------------------------------------------------------------- 2. QR à partir du texte
def test_qr_genere_a_partir_du_texte_sans_modification(env, monkeypatch):
    _activer(env)
    p = asyncio.run(albarka_pispi.charger_parametres())
    assert p["qr_contenu"] == QR_TEXTE.rstrip("\r\n")   # enregistré exactement
    vu = []
    vrai = albarka_docgen.qr_png
    monkeypatch.setattr(albarka_docgen, "qr_png", lambda t, *a, **k: vu.append(t) or vrai(t, *a, **k))
    data = asyncio.run(albarka_pispi.qr_pispi_bytes(p))
    assert vu == [QR_TEXTE] and data[:4] == b"\x89PNG"
    # Même image que le QR encodé directement à partir du texte
    assert data == vrai(QR_TEXTE)


# ---------------------------------------------------------------- 3. bloc sur les factures
def test_bloc_present_si_actif_et_non_solde(env):
    _activer(env)
    texte = _pdf_texte(env, _facture(paid_amount=18000, status="partial"))
    assert "Payer par PI-SPI" in texte
    assert "albarka.cabinet@uba" in texte and "FAC-202610-0007" in texte
    assert "100 000" in texte.replace(" ", " ").replace("\xa0", " ")   # reste dû 118 000 - 18 000
    assert "Cabinet ALBARKA" in texte and "UBA" in texte
    # le QR de vérification est toujours là
    assert "Scannez pour vérifier" in texte


def test_bloc_absent_si_inactif(env):
    texte = _pdf_texte(env, _facture())
    assert "PI-SPI" not in texte
    _activer(env)
    env.c.put("/api/admin/pispi", json={"actif": False}, headers=_h("dir"))
    assert asyncio.run(albarka_pispi.bloc_pispi_pour_document(_facture())) is None


def test_bloc_absent_si_facture_soldee(env):
    _activer(env)
    solde = _facture(paid_amount=118000, status="paid")
    assert asyncio.run(albarka_pispi.bloc_pispi_pour_document(solde)) is None
    assert "PI-SPI" not in _pdf_texte(env, solde)
    # un reçu ne porte jamais le bloc
    assert asyncio.run(albarka_pispi.bloc_pispi_pour_document(_facture(document_type="recu"))) is None


def test_proforma_modalites_sans_montant(env):
    _activer(env)
    pro = _facture(id="pro-1", number="PRO-202610-0002", document_type="proforma", status="proforma")
    bloc = asyncio.run(albarka_pispi.bloc_pispi_pour_document(pro))
    assert bloc["mode"] == "modalites" and bloc["montant"] is None
    texte = _pdf_texte(env, pro)
    assert "Modalités de paiement" in texte and "Montant à payer" not in texte
    assert "Payer par PI-SPI" not in texte


def test_parametres_invalident_les_pdf_caches(env):
    asyncio.run(env.db.invoices.insert_one(_facture(pdf_storage_path="albarka/c1/x.pdf")))
    _activer(env)
    inv = asyncio.run(env.db.invoices.find_one({"id": "inv-1"}))
    assert inv["pdf_storage_path"] is None


# ---------------------------------------------------------------- 4. mode de règlement PISPI
def test_reglement_pispi(env):
    asyncio.run(env.db.invoices.insert_one(_facture()))
    # Référence bancaire obligatoire
    r = env.c.post("/api/billing/payments", json={"invoice_id": "inv-1", "amount": 50000, "method": "PISPI"},
                   headers=_h("caisse"))
    assert r.status_code == 400 and "référence" in r.json()["detail"]
    r = env.c.post("/api/billing/payments", json={"invoice_id": "inv-1", "amount": 50000, "method": "PISPI",
                                                  "reference": "UBA-TX-123456"}, headers=_h("caisse"))
    assert r.status_code == 200, r.text
    assert r.json()["method"] == "pispi"
    pay = asyncio.run(env.db.payments.find_one({"invoice_id": "inv-1"}, {"_id": 0}))
    assert pay["method"] == "pispi" and pay["reference"] == "UBA-TX-123456"
    tx = asyncio.run(env.db.pispi_transactions.find_one({}, {"_id": 0}))
    assert tx["reference"] == "FAC-202610-0007" and tx["montant"] == 50000
    assert tx["statut"] == "rapproche" and tx["source"] == "manuel"
    assert tx["reference_bancaire"] == "UBA-TX-123456" and tx["document_id"] == "inv-1"
    inv = asyncio.run(env.db.invoices.find_one({"id": "inv-1"}, {"_id": 0}))
    assert inv["paid_amount"] == 50000 and inv["status"] == "partial"
    # Le reçu mentionne le mode PI-SPI
    recu = asyncio.run(env.db.invoices.find_one({"document_type": "recu"}, {"_id": 0}))
    assert "PI-SPI" in recu["items"][0]["label"]
    # Liste des transactions (rôles Caisse)
    assert len(env.c.get("/api/admin/pispi/transactions", headers=_h("caisse")).json()) == 1
    # Un règlement en espèces ne crée aucune transaction PI-SPI
    env.c.post("/api/billing/payments", json={"invoice_id": "inv-1", "amount": 1000, "method": "cash"},
               headers=_h("caisse"))
    assert asyncio.run(env.db.pispi_transactions.count_documents({})) == 1


# ---------------------------------------------------------------- 5. connecteurs et notification
def test_connecteurs_non_disponibles():
    assert isinstance(albarka_pispi.connecteur_actif(), albarka_pispi.ConnecteurManuel)
    for code in ("ecobank", "uba", "bsic", "ib_bank"):
        c = albarka_pispi.CONNECTEURS[code]()
        with pytest.raises(albarka_pispi.PISPINonDisponible, match="non disponible"):
            asyncio.run(c.demander_paiement(reference="FAC-1", montant=1000))
        with pytest.raises(albarka_pispi.PISPINonDisponible):
            asyncio.run(c.statut("FAC-1"))
    m = albarka_pispi.ConnecteurManuel()
    assert asyncio.run(m.demander_paiement(reference="FAC-1", montant=10))["mode"] == "manuel"


def test_notification_desactivee(env, monkeypatch):
    r = env.c.post("/api/pispi/notification", json={"reference": "FAC-1", "montant": 1000})
    assert r.status_code == 503 and "désactivée" in r.json()["detail"]
    # même avec un fournisseur déclaré : toujours désactivée, rien d'enregistré
    monkeypatch.setenv("PISPI_FOURNISSEUR", "ecobank")
    r = env.c.post("/api/pispi/notification", json={"reference": "FAC-1"})
    assert r.status_code == 503 and "non disponible" in r.json()["detail"]
    assert asyncio.run(env.db.pispi_transactions.count_documents({})) == 0
    d = env.c.get("/api/admin/pispi/connecteurs", headers=_h("dir")).json()
    assert d["notification_active"] is False and d["actif"] == "ecobank"


# ---------------------------------------------------------------- 6. déploiement
def test_render_yaml_et_lot():
    # Lecture simple du fichier (sans dépendance yaml) : chaque variable
    # PISPI_* est suivie de « sync: false » et n'a aucune valeur écrite
    lignes = (RACINE / "render.yaml").read_text(encoding="utf-8").splitlines()
    for k in ("PISPI_FOURNISSEUR", "PISPI_API_URL", "PISPI_CLIENT_ID", "PISPI_CLIENT_SECRET"):
        i = next(n for n, ln in enumerate(lignes) if ln.strip().startswith(f"- key: {k}"))
        assert lignes[i + 1].strip() == "sync: false"
    import lot
    # Le numéro de lot change à chaque déploiement (règle 1) : on vérifie seulement qu'il est renseigné
    assert lot.LOT and lot.LOT_LIBELLE
