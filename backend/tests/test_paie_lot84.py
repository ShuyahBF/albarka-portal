"""Lot 84 — paie : « Base IUTS » dans le livre de paie (PDF compris), case « exonéré de la cotisation CNSS » sur la fiche de
l'agent, nouvelles rubriques de retenue SND / SFED / CENAMU (pourcentage du brut, du salaire de base ou du net, ou valeur).
Tests autonomes : MongoDB simulé (mongomock-motor)."""
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
fitz = pytest.importorskip("fitz")
pytest.importorskip("reportlab")

import db as db_module  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_paie  # noqa: E402
import albarka_paie_cnss  # noqa: E402
import albarka_paie_moteur as moteur  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

BASE = {"base_salary": 300000, "dependents": 0, "category": "non_cadre"}


# ---------------------------------------------------------------- moteur : CNSS exonérée
def test_agent_exonere_de_la_cnss_na_ni_cotisation_salariale_ni_patronale():
    normal = moteur.compute_payslip(BASE, None, "2026-10")
    exo = moteur.compute_payslip({**BASE, "cnss_exempt": True}, None, "2026-10")
    assert normal["cnss"] == 16500 and exo["cnss"] == 0 and exo["cnss_base"] == 0 and exo["cnss_exempt"] is True
    assert exo["employer_cnss"] == 0 and exo["employer_cnss_base"] == 0
    # La taxe patronale (TPA, sur le brut) reste due : ce n'est pas une cotisation CNSS
    assert exo["employer_tax"] == normal["employer_tax"] > 0
    # Sans CNSS à déduire, l'imposable monte et le net aussi
    assert exo["taxable"] == exo["gross"] and exo["net"] > normal["net"]
    assert not any(ln["code"] == "cnss" for ln in exo["lines"])


def test_cnss_normale_inchangee_sans_la_case():
    r = moteur.compute_payslip(BASE, None, "2026-10")
    assert r["cnss_exempt"] is False and any(ln["code"] == "cnss" for ln in r["lines"])


# ---------------------------------------------------------------- moteur : SND / SFED / CENAMU
def test_rubriques_par_defaut_sans_effet_tant_quelles_ne_sont_pas_reglees():
    r = moteur.compute_payslip(BASE, None, "2026-10")
    assert r["special_deductions"] == [] and r["special_total"] == 0
    assert [s["key"] for s in moteur.normalize_params(None)["special_deductions"]] == ["snd", "sfed", "cenamu"]


def _params(**regl):
    p = moteur.normalize_params(None)
    for s in p["special_deductions"]:
        if s["key"] in regl:
            s.update(regl[s["key"]])
    return p


def test_pourcentage_du_brut_du_salaire_de_base_ou_du_net_et_valeur_fixe():
    emp = {**BASE, "allowances": {"housing": 50000}}              # brut 350 000, base 300 000
    sans = moteur.compute_payslip(emp, None, "2026-10")
    p = _params(snd={"mode": "percent", "base": "gross", "value": 1.0},
                sfed={"mode": "percent", "base": "base", "value": 2.0},
                cenamu={"mode": "amount", "value": 1500})
    r = moteur.compute_payslip(emp, p, "2026-10")
    montants = {s["key"]: s["amount"] for s in r["special_deductions"]}
    assert montants == {"snd": 3500, "sfed": 6000, "cenamu": 1500} and r["special_total"] == 11000
    assert r["net_to_pay"] == sans["net_to_pay"] - 11000
    assert r["deductions_total"] == 11000                         # « Retenues » du livre de paie
    # Pourcentage du net : calculé sur le salaire net (avant FSP)
    p_net = _params(snd={"mode": "percent", "base": "net", "value": 1.0})
    rn = moteur.compute_payslip(emp, p_net, "2026-10")
    assert rn["special_deductions"][0]["amount"] == round(rn["net"] * 0.01)
    # Les rubriques apparaissent comme lignes de retenue du bulletin
    assert {ln["label"] for ln in r["lines"] if ln["code"].startswith("spec_")} == {"SND", "SFED", "CENAMU"}


def test_reglage_propre_au_salarie_remplace_celui_du_modele():
    p = _params(snd={"mode": "percent", "base": "gross", "value": 1.0})
    emp = {**BASE, "special_deductions": {"snd": {"mode": "amount", "value": 2500}, "cenamu": {"mode": "percent", "base": "gross", "value": 0.5}}}
    r = moteur.compute_payslip(emp, p, "2026-10")
    assert {s["key"]: s["amount"] for s in r["special_deductions"]} == {"snd": 2500, "cenamu": 1500}


def test_controle_des_rubriques():
    for mauvais in ({"mode": "percent", "value": 150}, {"mode": "amount", "value": -5}):
        p = moteur.merged_params(None)
        p["special_deductions"][0].update(mauvais)
        with pytest.raises(ValueError):
            moteur.normalize_params(p)


# ---------------------------------------------------------------- API
USERS = {
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "pharmacie@exemple.bf", "full_name": "Dr Pharma", "company": "PHARMACIE SOLEIL", "phone": "+22670112233",
           "roles": ["client"], "is_active": True},
}
H = {"X-User": "rh"}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot84_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_paie, "_SETUP_DONE_FOR", None)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_paie.router, albarka_paie_cnss.router, albarka_docgen.router, albarka_docgen.public_router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _texte(pdf_bytes: bytes) -> str:
    with fitz.open("pdf", pdf_bytes) as d:
        return " ".join(" ".join(pg.get_text() for pg in d).split())


def test_livre_de_paie_pdf_ecran_et_csv_affichent_la_base_iuts(env):
    c = env.c
    c.post("/api/hr/paie/employees", headers=H, json={**BASE, "tenant_id": "c1", "full_name": "KABORE Awa",
                                                      "allowances": {"housing": 50000}})
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2026-10"})
    livre = c.get("/api/hr/paie/livre?employer_id=c1&period_month=2026-10", headers=H).json()
    assert "iuts_base" in [col["key"] for col in livre["columns"]]
    base = livre["rows"][0]["iuts_base"]
    assert base and livre["totals"]["iuts_base"] == base
    texte = _texte(c.get("/api/hr/paie/livre/pdf?employer_id=c1&period_month=2026-10", headers=H).content)
    assert "Base IUTS" in texte and f"{int(base):,}".replace(",", " ") in texte.replace(" ", " ").replace("\xa0", " ")
    csv = c.get("/api/hr/paie/livre/csv?employer_id=c1&period_month=2026-10", headers=H).content.decode("utf-8")
    assert "Base IUTS" in csv and str(int(round(base))) in csv


def test_fiche_agent_exonere_cnss_prise_en_compte_immediatement_sur_le_bulletin(env):
    c = env.c
    e = c.post("/api/hr/paie/employees", headers=H, json={**BASE, "tenant_id": "c1", "full_name": "OUEDRAOGO Paul",
                                                         "cnss_exempt": True}).json()
    assert e["cnss_exempt"] is True
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2026-10"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-10", headers=H).json()["items"][0]
    assert b["result"]["cnss"] == 0 and b["employee"]["cnss_exempt"] is True
    # On décoche : le bulletin brouillon est recalculé à la préparation suivante (CNSS 5,5 % de 300 000)
    c.put(f"/api/hr/paie/employees/{e['id']}", headers=H, json={**BASE, "tenant_id": "c1", "full_name": "OUEDRAOGO Paul", "cnss_exempt": False})
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2026-10"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-10", headers=H).json()["items"][0]
    assert b["result"]["cnss"] == 16500
    # Simulation en direct (fiche) : la case change le résultat tout de suite
    sim = c.post("/api/hr/paie/simulate", headers=H, json={"employer_id": "c1", "employee": {**BASE, "cnss_exempt": True}}).json()
    assert sim["cnss"] == 0


def test_fiche_agent_rubriques_snd_sfed_cenamu_et_bulletin_pdf(env):
    c = env.c
    e = c.post("/api/hr/paie/employees", headers=H, json={
        **BASE, "tenant_id": "c1", "full_name": "SAWADOGO Aïcha",
        "special_deductions": {"snd": {"mode": "percent", "base": "gross", "value": 1}, "sfed": {"mode": "amount", "value": 2000},
                               "cenamu": {"mode": "percent", "base": "gross", "value": ""}}}).json()
    assert set(e["special_deductions"]) == {"snd", "sfed"}          # une rubrique laissée vide n'est pas enregistrée
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2026-10"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-10", headers=H).json()["items"][0]
    assert b["result"]["special_total"] == 5000
    texte = _texte(c.get(f"/api/hr/paie/bulletins/{b['id']}/pdf", headers=H).content)
    assert "SND" in texte and "SFED" in texte and "CENAMU" not in texte
    assert c.post("/api/hr/paie/employees", headers=H, json={**BASE, "tenant_id": "c1", "full_name": "X Y",
                                                             "special_deductions": {"snd": {"mode": "percent", "value": 500}}}).status_code == 400
    # Réglage de l'employeur : SND à 1 % du brut pour tous les salariés
    cfg = c.get("/api/hr/paie/employeurs/c1", headers=H).json()
    assert [s["key"] for s in cfg["params"]["special_deductions"]] == ["snd", "sfed", "cenamu"]
