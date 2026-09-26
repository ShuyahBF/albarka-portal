"""Lot 7 — documents édités par le cabinet.

- factures / proformas au format du modèle : lignes de titre et détail sur
  plusieurs lignes, TVA unique (18 %), retenue sur le hors-taxe, net à payer,
  somme en lettres, QR code de vérification, papier à en-tête ;
- documents mis en forme à partir de MODÈLES à variables : nettoyage du HTML,
  verrouillage, génération d'un document par destinataire, numérotation,
  dépôt dans l'espace client ;
- missions : description mise en forme ;
- tableau de paie (fiche de renseignement) : saisie, reprise du mois
  précédent, PDF et fichier Excel.
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
pytest.importorskip("reportlab")

import db as db_module  # noqa: E402
import albarka_billing_docs  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_letters  # noqa: E402
import albarka_missions  # noqa: E402
import albarka_payroll  # noqa: E402
import albarka_phase_c  # noqa: E402
import albarka_storage  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"], "is_active": True},
    "dir": {"id": "u-dir", "email": "dg@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "compta": {"id": "u-compta", "email": "c@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "mini@exemple.bf", "full_name": "M. Ouédraogo", "company": "ALIMENTATION MINI PRIX",
           "roles": ["client"], "is_active": True, "phone": "+22670000001"},
    "c2": {"id": "c2", "email": "elite@exemple.bf", "full_name": "Dr Kaboré", "company": "PHARMACIE Elite",
           "roles": ["client"], "is_active": True},
}
PNG = None


def _png(w=400, h=60, color=(20, 200, 180)) -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture()
def env(monkeypatch, tmp_path):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot7_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_storage, "UPLOAD_DIR", tmp_path)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    asyncio.run(mock_db.client_kyc.insert_one({"tenant_id": "c1", "business_name": "ALIMENTATION MINI PRIX",
                                               "address": "07 BP 5257 OUAGA 07", "ifu": "00027128S"}))

    async def fake_log(**kw):
        return None

    async def fake_archive(**kw):
        return None
    monkeypatch.setattr(albarka_phase_c, "_log_platform_event", fake_log)
    monkeypatch.setattr(albarka_phase_c, "_auto_archive", fake_archive)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_phase_c.billing_router, albarka_billing_docs.router, albarka_docgen.router,
              albarka_docgen.public_router, albarka_letters.router, albarka_missions.router, albarka_payroll.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[get_current_user] = fake_user
    asyncio.run(albarka_letters.ensure_letters_setup())
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _h(u):
    return {"X-User": u}


def _pdf_text(data: bytes) -> str:
    with fitz.open("pdf", data) as d:
        text = "\n".join(p.get_text() for p in d)
    # Espaces et retours à la ligne normalisés (le PDF coupe les lignes longues)
    return " ".join(text.split())


# ---------------------------------------------------------------- somme en lettres
def test_montant_en_lettres():
    m = albarka_docgen.montant_en_lettres
    assert m(59473) == "CINQUANTE NEUF MILLE QUATRE CENT SOIXANTE TREIZE"
    assert m(80, upper=False) == "quatre vingts" and m(81, upper=False) == "quatre vingt un"
    assert m(200, upper=False) == "deux cents" and m(201, upper=False) == "deux cent un"
    assert m(280000, upper=False) == "deux cent quatre vingt mille"
    assert m(71, upper=False) == "soixante et onze" and m(1000, upper=False) == "mille"
    assert m(2000000, upper=False) == "deux millions"


# ---------------------------------------------------------------- factures
def test_invoice_model_totals_pdf_and_verification(env):
    payload = {"tenant_id": "c1", "title": "Honoraires août 2024", "document_type": "facture", "tva_rate": 18,
               "withholding_rate": 5, "items": [
                   {"kind": "section", "label": "Assistance comptable et suivi fiscal", "quantity": 1},
                   {"label": "AOUT - 2024", "detail": "Tenue\nDéclarations", "quantity": 1, "unit_price": 52632}]}
    r = env.c.post("/api/billing/invoices", headers=_h("compta"), json=payload)
    assert r.status_code == 200, r.text
    inv = r.json()
    # TVA unique arrondie au franc, retenue 5 % du hors-taxe, net à payer
    assert inv["subtotal"] == 52632 and inv["tax"] == 9474 and inv["total"] == 62106
    assert inv["withholding"] == 2632 and inv["net_to_pay"] == 59474
    assert inv["items"][0]["unit_price"] == 0 and inv["verify_token"]
    pdf = env.c.get(f"/api/billing/invoices/{inv['id']}/pdf", headers=_h("secr"))
    assert pdf.status_code == 200
    text = _pdf_text(pdf.content)
    for expected in ("FACTURE N°", "Facturer à", "ALIMENTATION MINI PRIX", "IFU : 00027128S", "Quantité",
                     "Assistance comptable", "AOUT - 2024", "Sous-total", "TVA 18%", "retenue 5%", "NET A PAYER",
                     "59 474", "CINQUANTE NEUF MILLE QUATRE CENT SOIXANTE QUATORZE", "FRANCS CFA", "Le Directeur Général"):
        assert expected in text, expected
    # QR code : page publique de vérification, sans compte
    v = env.c.get(f"/api/public/verify/{inv['verify_token']}")
    assert v.status_code == 200 and v.json()["number"] == inv["number"] and v.json()["amount"] == 59474
    assert v.json()["client"] == "ALIMENTATION MINI PRIX"
    assert env.c.get("/api/public/verify/inconnu").status_code == 404


def test_invoice_payment_uses_net_to_pay(env):
    inv = env.c.post("/api/billing/invoices", headers=_h("compta"), json={
        "tenant_id": "c1", "title": "Test", "tva_rate": 18, "withholding_rate": 5,
        "items": [{"label": "Mission", "quantity": 1, "unit_price": 100000}]}).json()
    assert inv["net_to_pay"] == 113000
    # Encaisser le net à payer solde la facture
    asyncio.run(env.db.users.update_one({"id": "u-secr"}, {"$set": {"roles": ["secretariat", "caissier"]}}))
    r = env.c.post("/api/billing/payments", headers=_h("secr"), json={"invoice_id": inv["id"], "amount": 113000})
    assert r.status_code == 200, r.text
    assert asyncio.run(env.db.invoices.find_one({"id": inv["id"]}))["status"] == "paid"


def test_proforma_and_bill_to_override(env):
    inv = env.c.post("/api/billing/invoices", headers=_h("compta"), json={
        "tenant_id": "c2", "title": "Devis", "document_type": "proforma", "tva_rate": 18,
        "bill_to": "PHARMACIE Elite\nOuagadougou\nIFU : 1234X", "items": [{"label": "Audit", "quantity": 2, "unit_price": 50000}]}).json()
    text = _pdf_text(env.c.get(f"/api/billing/invoices/{inv['id']}/pdf", headers=_h("secr")).content)
    assert "FACTURE PROFORMA N°" in text and "IFU : 1234X" in text and "facture proforma" in text
    assert "NET A PAYER" not in text          # pas de retenue -> pas de ligne net à payer


def test_letterheads_crud_and_rights(env):
    files = {"header": ("h.png", _png(), "image/png"), "footer": ("f.png", _png(400, 50), "image/png")}
    assert env.c.post("/api/admin/letterheads", headers=_h("compta"), data={"name": "X"}, files=files).status_code == 403
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "GESPHARM"}, files=files)
    assert r.status_code == 200, r.text
    lh = r.json()
    assert lh["is_default"] and lh["has_header"] and lh["has_footer"]
    # Une facture utilise le papier par défaut : l'image est dans le PDF
    inv = env.c.post("/api/billing/invoices", headers=_h("compta"), json={
        "tenant_id": "c1", "title": "T", "tva_rate": 18, "items": [{"label": "L", "quantity": 1, "unit_price": 1000}]}).json()
    pdf = env.c.get(f"/api/billing/invoices/{inv['id']}/pdf", headers=_h("secr")).content
    with fitz.open("pdf", pdf) as d:
        assert len(d[0].get_images()) >= 3      # en-tête, pied de page, QR code
    assert env.c.put(f"/api/admin/letterheads/{lh['id']}", headers=_h("dir"), data={"name": "GESPHARM 2", "remove_footer": "true"}).json()["has_footer"] is False
    assert env.c.delete(f"/api/admin/letterheads/{lh['id']}", headers=_h("dir")).status_code == 200
    s = env.c.put("/api/admin/doc-settings", headers=_h("dir"), json={"signatory_name": "Abdoul Azize SANNA"}).json()
    assert s["signatory_name"] == "Abdoul Azize SANNA" and s["city"] == "Ouagadougou"


# ---------------------------------------------------------------- modèles et génération
def test_sanitize_html_keeps_formatting_and_drops_scripts():
    raw = ('<p style="text-align:justify;position:fixed" onclick="x()">Texte <b>gras</b>'
           '<script>alert(1)</script><img src="http://evil/x.png"><img src="data:image/png;base64,AAAA">'
           '<a href="javascript:x">lien</a><span class="tpl-var evil" data-var="client.nom">{{client.nom}}</span></p>'
           '<table style="border-collapse:collapse"><tr><td style="border:1px solid #000">1</td></tr></table>')
    out = albarka_letters.sanitize_html(raw)
    assert "script" not in out and "alert" not in out and "onclick" not in out and "position" not in out
    assert "http://evil" not in out and "javascript" not in out
    assert 'text-align: justify' in out and "<b>gras</b>" in out and 'src="data:image/png;base64,AAAA"' in out
    assert 'class="tpl-var"' in out and "<table" in out and "border: 1px solid #000" in out
    # Épaisseur de bordure sans style (copie par le navigateur) : trait plein ajouté
    fixed = albarka_letters.sanitize_html('<td style="border-width: 1px; border-color: rgb(0, 0, 0)">x</td>')
    assert "border-style: solid" in fixed


def test_seed_template_generate_many_numbering_and_deposit(env):
    tpls = env.c.get("/api/letters/templates", headers=_h("secr")).json()
    avis = next(t for t in tpls if t["name"] == "Avis de mission")
    full = env.c.get(f"/api/letters/templates/{avis['id']}", headers=_h("secr")).json()
    assert {"date.lieu_jour", "client.nom", "doc.numero", "civilite", "periode_mission", "signataire.nom"} <= set(full["used_variables"])
    # Le numéro repart de 126 comme sur le document du cabinet
    body = {**{k: full[k] for k in ("name", "category", "body_html", "variables", "number_format", "title_pattern")}, "next_number": 126}
    assert env.c.put(f"/api/letters/templates/{avis['id']}", headers=_h("secr"), json=body).status_code == 200
    env.c.put("/api/admin/doc-settings", headers=_h("dir"), json={"signatory_name": "Abdoul Azize SANNA"})
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json={
        "tenant_ids": ["c1", "c2"], "doc_date": "2026-08-17", "deposit": True,
        "common_values": {"periode_mission": "du mardi 18 au vendredi 21 août 2026"},
        "recipient_values": {"c1": {"destinataire_titre": "Gérant", "civilite": "Monsieur", "civilite_min": "monsieur"}}})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["count"] == 2 and [d["number"] for d in out["items"]] == ["126/GESP/DG/2026", "127/GESP/DG/2026"]
    d1, d2 = out["items"]
    t1 = _pdf_text(env.c.get(f"/api/letters/documents/{d1['id']}/pdf", headers=_h("secr")).content)
    t2 = _pdf_text(env.c.get(f"/api/letters/documents/{d2['id']}/pdf", headers=_h("secr")).content)
    assert "Ouagadougou, le 17 août 2026" in t1 and "ALIMENTATION MINI PRIX" in t1 and "Monsieur," in t1
    assert "126/GESP/DG/2026" in t1 and "du mardi 18 au vendredi 21 août 2026" in t1 and "Abdoul Azize SANNA" in t1
    assert "PHARMACIE Elite" in t2 and "Docteur," in t2 and "Pharmacien Gérant" in t2 and "{{" not in t2
    # Déposés dans l'espace de chaque client (catégorie Courrier)
    deposited = asyncio.run(env.db.client_documents.find({"category": "courrier"}).to_list(10))
    assert {d["tenant_id"] for d in deposited} == {"c1", "c2"}
    # Impression groupée et version Word
    merged = env.c.post("/api/letters/documents/merged-pdf", headers=_h("secr"), json={"batch_id": out["batch_id"]})
    with fitz.open("pdf", merged.content) as d:
        assert d.page_count >= 2
    word = env.c.get(f"/api/letters/documents/{d1['id']}/word", headers=_h("secr"))
    assert word.status_code == 200 and "ALIMENTATION MINI PRIX" in word.content.decode("utf-8")
    # QR code du document généré
    token = asyncio.run(env.db.generated_documents.find_one({"id": d1["id"]}))["verify_token"]
    assert env.c.get(f"/api/public/verify/{token}").json()["kind"] == "Avis de mission"


def test_template_lock_rules(env):
    t = env.c.post("/api/letters/templates", headers=_h("compta"), json={
        "name": "Ordre de mission", "category": "ordre_mission", "body_html": "<p>Ordre {{client.nom}} {{lieu}}</p>",
        "variables": [{"key": "lieu", "label": "Lieu", "scope": "common"}, {"key": "client.nom", "label": "interdit"}]}).json()
    assert [v["key"] for v in t["variables"]] == ["lieu"]      # clé réservée écartée
    assert env.c.post("/api/letters/templates", headers=_h("secr"), json={"name": "ordre de MISSION"}).status_code == 409
    assert env.c.post(f"/api/letters/templates/{t['id']}/lock", headers=_h("compta")).json()["locked"] is True
    body = {"name": "Ordre de mission", "body_html": "<p>modifié</p>"}
    assert env.c.put(f"/api/letters/templates/{t['id']}", headers=_h("secr"), json=body).status_code == 423
    assert env.c.delete(f"/api/letters/templates/{t['id']}", headers=_h("secr")).status_code == 423
    # Un autre collaborateur ne peut pas déverrouiller ; la Direction le peut
    assert env.c.post(f"/api/letters/templates/{t['id']}/unlock", headers=_h("secr")).status_code == 403
    assert env.c.post(f"/api/letters/templates/{t['id']}/unlock", headers=_h("dir")).json()["locked"] is False
    assert env.c.put(f"/api/letters/templates/{t['id']}", headers=_h("secr"), json=body).status_code == 200
    dup = env.c.post(f"/api/letters/templates/{t['id']}/duplicate", headers=_h("secr")).json()
    assert dup["name"] == "Ordre de mission (copie)" and dup["locked"] is False
    assert env.c.delete(f"/api/letters/templates/{t['id']}", headers=_h("secr")).status_code == 200
    # Les clients n'ont pas accès aux modèles
    assert env.c.get("/api/letters/templates", headers=_h("c1")).status_code == 403


def test_mission_rich_description_and_generation_from_mission(env):
    m = env.c.post("/api/missions", headers=_h("secr"), json={
        "tenant_id": "c2", "title": "Mise à jour RH", "type": "paie_rh",
        "description_html": "<p><b>Dossiers</b> du personnel</p><script>x</script><ul><li>contrats</li></ul>"}).json()
    assert "<b>Dossiers</b>" in m["description_html"] and "script" not in m["description_html"]
    assert "Dossiers du personnel" in m["description"] and "contrats" in m["description"]
    t = env.c.post("/api/letters/templates", headers=_h("secr"), json={
        "name": "Ordre", "body_html": "<p>Mission : {{mission.titre}}</p>{{mission.description}}"}).json()
    r = env.c.post(f"/api/letters/templates/{t['id']}/generate", headers=_h("secr"), json={"tenant_ids": ["c2"], "mission_id": m["id"]}).json()
    text = _pdf_text(env.c.get(f"/api/letters/documents/{r['items'][0]['id']}/pdf", headers=_h("secr")).content)
    assert "Mission : Mise à jour RH" in text and "Dossiers" in text and "contrats" in text
    assert env.c.get(f"/api/letters/documents?mission_id={m['id']}", headers=_h("secr")).json()[0]["mission_id"] == m["id"]


# ---------------------------------------------------------------- tableau de paie
def test_payroll_table_save_prefill_pdf_csv(env):
    asyncio.run(env.db.employees.insert_many([
        {"id": "e1", "tenant_id": "c1", "full_name": "AYIKI SAMIRAT", "base_salary": 258700},
        {"id": "e2", "tenant_id": "c1", "full_name": "COMPAORE N. ROSINE", "base_salary": 54225}]))
    t = env.c.get("/api/hr/payroll/table?tenant_id=c1&period_month=2026-02", headers=_h("rh")).json()
    assert t["source"] == "employees" and t["period_label"] == "FÉVRIER 2026" and len(t["rows"]) == 2
    rows = [{"employee_id": "e1", "full_name": "AYIKI SAMIRAT", "base_salary": 258700, "allowance_function": 35000,
             "allowance_housing": 50000, "allowance_transport": 40000, "allowance_responsibility": 25000, "net": 346654},
            {"employee_id": "e2", "full_name": "COMPAORE N. ROSINE", "base_salary": 54225, "seniority": 3253,
             "allowance_function": 10000, "allowance_housing": 20000, "allowance_transport": 30000, "net": 101402}]
    assert env.c.put("/api/hr/payroll/table", headers=_h("compta"), json={"tenant_id": "c1", "period_month": "2026-02", "rows": rows}).status_code == 403
    saved = env.c.put("/api/hr/payroll/table", headers=_h("rh"), json={"tenant_id": "c1", "period_month": "2026-02",
                                                                      "legal_form": "SARL", "rows": rows}).json()
    assert [r["computed_gross"] for r in saved["rows"]] == [408700, 117478]       # comme sur le document du cabinet
    assert saved["totals"]["gross"] == 526178 and saved["totals"]["net"] == 448056
    # Mois suivant : repris du mois précédent
    nxt = env.c.get("/api/hr/payroll/table?tenant_id=c1&period_month=2026-03", headers=_h("rh")).json()
    assert nxt["source"] == "previous_month" and nxt["rows"][1]["seniority"] == 3253 and nxt["legal_form"] == "SARL"
    pdf = env.c.get("/api/hr/payroll/table/pdf?tenant_id=c1&period_month=2026-02", headers=_h("rh"))
    text = _pdf_text(pdf.content)
    for expected in ("FICHE DE RENSEIGNEMENT", "LISTE ACTUALISÉE DU PERSONNEL PERMANENT FÉVRIER 2026", "ALIMENTATION MINI PRIX SARL",
                     "AYIKI SAMIRAT", "408 700", "346 654", "TOTAL", "526 178", "RUBRIQUE PAIE", "La responsable"):
        assert expected in text, expected
    with fitz.open("pdf", pdf.content) as d:
        assert d[0].rect.width > d[0].rect.height and d[1].rect.width < d[1].rect.height   # paysage puis portrait
    csv_body = env.c.get("/api/hr/payroll/table/csv?tenant_id=c1&period_month=2026-02", headers=_h("rh")).content.decode("utf-8-sig")
    assert "AYIKI SAMIRAT;258700;;35000;50000;40000;25000;408700;346654" in csv_body and "TOTAL" in csv_body
    token = asyncio.run(env.db.payroll_tables.find_one({"tenant_id": "c1"}))["verify_token"]
    assert env.c.get(f"/api/public/verify/{token}").json()["kind"] == "Tableau de paie"
