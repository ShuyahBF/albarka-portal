"""Lot 26 — bulletins de paie : formules du classeur d'ALBARKA (feuille
« Taux 20% (3) », août 2024) et bulletin PDF modernisé.

Cas de contrôle OBLIGATOIRE : bulletin d'août 2026 de SEGO IRENE fourni par
ALBARKA (non cadre, 2 charges, ancienneté 0). Puis :
  - ancienneté + prime exceptionnelle (hors base CNSS) ;
  - plafond CNSS 800 000 (CNSS salariale 44 000 au maximum) ;
  - 8 charges de famille : 20 % (la ligne « 8 charges → 22 % » est supprimée) ;
  - mise à jour unique des modèles enregistrés avant le lot 26 ;
  - parcours complet par l'API (prime exceptionnelle, PDF, cumul annuel).
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
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
fitz = pytest.importorskip("fitz")
pytest.importorskip("reportlab")

import db as db_module  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_paie  # noqa: E402
import albarka_paie_moteur as moteur  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

# Bulletin d'ALBARKA : gains de SEGO IRENE (août 2026)
SEGO = {"full_name": "SEGO IRENE", "base_salary": 44637, "dependents": 2, "category": "non_cadre",
        "allowances": {"housing": 10000, "transport": 5204, "function": 6000, "other": 5000, "guard": 5000}}


# ---------------------------------------------------------------- cas SEGO IRENE
def test_sego_irene_exact():
    """Chaque montant du bulletin PDF d'ALBARKA, avec les valeurs par défaut."""
    r = moteur.compute_payslip(SEGO, None, "2026-08")
    assert r["gross"] == 75841                         # brut
    assert r["cnss"] == 4171                           # CNSS 5,5 % de 75 841
    # Contrôle à la main : CNSS fiscale = min(4 171 ; 8 % × 44 637 = 3 571)
    assert r["cnss_fiscal"] == 3571 and r["taxable"] == 72270
    # Exonérations : logement 10 000 + transport 3 614 + fonction 3 614 (5 % de 72 270)
    assert [e["amount"] for e in r["exemptions"]] == [10000, 3614, 3614]
    assert r["flat_abatement_rate"] == 25 and r["flat_abatement"] == 11159     # 25 % × 44 637
    assert r["iuts_base"] == 43800                     # 43 883 arrondi à la centaine inférieure
    assert r["iuts_gross"] == 1670 and r["family_rate"] == 10 and r["family_abatement"] == 167
    assert r["iuts"] == 1503                           # IUTS
    assert r["withholdings_total"] == 5674             # total des retenues
    assert r["net"] == 70167                           # base FSP
    assert r["patriotic_support"] == 702               # FSP 1 %
    assert r["net_to_pay"] == 69465                    # net à payer
    assert r["employer_cnss"] == 12135                 # CNSS patronale 16 %
    assert r["employer_tax"] == 2275                   # taxe patronale (TPA 3 %)
    assert r["employer_cost"] == 90251                 # masse salariale
    # La somme des branches de la CNSS patronale vaut bien 16 % (pas 12 134)
    assert sum(x["amount"] for x in r["employer_charges"] if x["kind"] == "cnss") == 12135
    fsp = next(ln for ln in r["lines"] if ln["code"] == "patriotic")
    assert fsp["label"] == "Prélèvement pour effort de paix (FSP)" and fsp["base"] == 70167


def test_sego_irene_sans_categorie_ni_modele_complet():
    """Salarié sans catégorie : taux général 25 % ; modèle partiel : nouveaux défauts."""
    r = moteur.compute_payslip({**SEGO, "category": None}, {"country": "Burkina Faso"}, "2026-08")
    assert r["net_to_pay"] == 69465 and r["employer_cost"] == 90251


# ---------------------------------------------------------------- ancienneté + prime exceptionnelle
def test_seniority_and_exceptional_bonus_outside_cnss():
    emp = {"base_salary": 200000, "hire_date": "2020-01-15", "dependents": 0, "category": "non_cadre",
           "allowances": {"housing": 50000, "transport": 20000},
           "extras": [{"label": "Prime de fin d'exercice", "amount": 100000, "exceptional": True}]}
    r = moteur.compute_payslip(emp, None, "2026-08")
    # 6 ans de service -> 5 % + 3 × 1 % = 8 % du salaire de base
    assert r["years_of_service"] == 6 and r["seniority_rate"] == 8 and r["seniority"] == 16000
    assert r["gross"] == 386000 and r["exceptional_total"] == 100000
    # Base CNSS = brut SANS la prime exceptionnelle : 286 000 × 5,5 %
    assert r["cnss_base"] == 286000 and r["cnss"] == 15730
    # Plafond fiscal = 8 % × (base + ancienneté + prime exceptionnelle) = 25 280 > CNSS
    assert r["cnss_fiscal_cap_base"] == 316000 and r["cnss_fiscal"] == 15730
    assert r["taxable"] == 370270
    # Exonérations : logement 50 000 ; transport min(20 000 ; 18 513,5 -> 18 514)
    assert r["exemptions_total"] == 68514
    # Abattement 25 % × (base + ancienneté) = 54 000
    assert r["flat_abatement_base"] == 216000 and r["flat_abatement"] == 54000
    assert r["iuts_base"] == 247700                    # 247 756 -> centaine inférieure
    assert r["iuts"] == 38931                          # barème : 38 930,9
    assert r["net"] == 331339 and r["patriotic_support"] == 3313 and r["net_to_pay"] == 328026
    # Charges patronales sur la même assiette CNSS (286 000), TPA sur le brut
    assert r["employer_cnss"] == 45760 and r["employer_tax"] == 11580
    # La prime exceptionnelle est affichée APRÈS les autres gains
    assert [ln["code"] for ln in r["lines"] if ln["kind"] == "gain"][-1] == "exc_0"
    # La même prime NON exceptionnelle entre dans la base CNSS
    plain = moteur.compute_payslip({**emp, "extras": [{"label": "Prime", "amount": 100000}]}, None, "2026-08")
    assert plain["cnss_base"] == 386000 and plain["cnss"] == 21230
    # Réglable dans le modèle : prime exceptionnelle soumise à CNSS
    subj = moteur.compute_payslip(emp, {"exceptional_bonus": {"subject_to_cnss": True}}, "2026-08")
    assert subj["cnss"] == 21230


def test_in_kind_benefit():
    """Avantage en nature : brut et IUTS, hors CNSS, dans l'abattement, retiré du net."""
    base = {"base_salary": 150000, "dependents": 0, "category": "non_cadre"}
    r0 = moteur.compute_payslip(base, None, "2026-08")
    r = moteur.compute_payslip({**base, "in_kind": 40000}, None, "2026-08")
    assert r["gross"] == r0["gross"] + 40000 and r["cnss"] == r0["cnss"]
    assert r["flat_abatement"] == round(0.25 * 190000)
    assert r["net"] == r["gross"] - r["cnss"] - r["iuts"] - 40000
    assert any(ln["code"] == "in_kind_net" for ln in r["lines"])


# ---------------------------------------------------------------- plafond CNSS
def test_cnss_ceiling_44000():
    r = moteur.compute_payslip({"base_salary": 900000, "dependents": 0, "category": "cadre"}, None, "2026-08")
    assert r["cnss_base"] == 800000 and r["cnss"] == 44000           # 5,5 % × 800 000
    assert r["employer_cnss"] == 128000                              # 16 % × 800 000
    assert r["employer_tax"] == 27000                                # TPA 3 % × 900 000 (non plafonnée)
    assert r["cnss_fiscal"] == 44000                                 # 8 % × 900 000 = 72 000 > 44 000
    assert r["flat_abatement_rate"] == 20 and r["flat_abatement"] == 180000   # cadre : 20 %
    assert r["employer_cost"] == 900000 + 128000 + 27000


# ---------------------------------------------------------------- charges de famille
def test_eight_dependents_capped_at_20_percent():
    p = moteur.normalize_params(None)
    assert [row["charges"] for row in p["family_abatement"]][-1] == 7
    assert moteur.family_rate(7, p["family_abatement"]) == 20
    assert moteur.family_rate(8, p["family_abatement"]) == 20
    r = moteur.compute_payslip({"base_salary": 300000, "dependents": 8, "category": "non_cadre"}, None, "2026-08")
    assert r["family_rate"] == 20 and r["family_abatement"] == round(r["iuts_gross"] * 0.20)
    assert r["iuts"] == r["iuts_gross"] - r["family_abatement"]


# ---------------------------------------------------------------- modèles enregistrés avant le lot 26
OLD_LOT8 = {
    "allowances": [
        {"key": "housing", "label": "Indemnité de logement", "exemption": "housing"},
        {"key": "transport", "label": "Indemnité de transport", "exemption": "transport"},
        {"key": "function", "label": "Indemnité de fonction", "exemption": "function"},
        {"key": "responsibility", "label": "Indemnité de responsabilité", "exemption": None},
        {"key": "risk", "label": "Indemnité de risque", "exemption": None},
        {"key": "subjection", "label": "Indemnité de sujétion", "exemption": None},
        {"key": "guard", "label": "Indemnité de garde", "exemption": None},
        {"key": "other", "label": "Autre indemnité", "exemption": None},
    ],
    "cnss": {"employee_rate": 5.5, "ceiling": 600000, "fiscal_cap_enabled": True, "fiscal_cap_rate": 8.0,
             "employer_ceiling": 600000, "employer_lines": [{"label": "Prestations familiales", "rate": 7.0},
                                                            {"label": "Risques professionnels", "rate": 3.5},
                                                            {"label": "Pension vieillesse", "rate": 5.5}]},
    "flat_abatement": {"mode": "single", "rate": 25.0, "categories": [{"key": "cadre", "label": "Cadre", "rate": 20.0},
                                                                      {"key": "non_cadre", "label": "Non cadre", "rate": 25.0}]},
    "family_abatement": [{"charges": n, "rate": r} for n, r in [(1, 8), (2, 10), (3, 12), (4, 14), (5, 16), (6, 18), (7, 20), (8, 22)]],
    "patriotic_support": {"enabled": True, "rate": 1.0, "label": "Soutien patriotique"},
    "rounding": {"amounts": {"step": 1, "mode": "nearest"}, "iuts_base": {"step": 100, "mode": "down"},
                 "net": {"step": 100, "mode": "nearest"}},
}


def test_upgrade_old_params_keeps_deliberate_choices():
    new, changes = moteur.upgrade_params_lot26(OLD_LOT8)
    assert new["cnss"]["ceiling"] == 800000 and new["cnss"]["employer_ceiling"] == 800000
    assert new["family_abatement"][-1] == {"charges": 7, "rate": 20.0}
    assert new["rounding"]["net"] == {"step": 1, "mode": "up"}
    assert new["patriotic_support"]["label"] == "Prélèvement pour effort de paix (FSP)"
    assert new["flat_abatement"]["mode"] == "by_category"
    al = {a["key"]: a["exemption"] for a in new["allowances"]}
    assert al["subjection"] == al["responsibility"] == "function" and "representation" in al and "cash" in al
    assert len(changes) >= 6
    # Après mise à jour, le cas SEGO IRENE donne les montants du bulletin d'ALBARKA
    assert moteur.compute_payslip(SEGO, new, "2026-08")["net_to_pay"] == 69465
    # Valeurs choisies par le cabinet (différentes des anciens défauts) : conservées
    custom = {**OLD_LOT8, "cnss": {**OLD_LOT8["cnss"], "ceiling": 700000},
              "patriotic_support": {"enabled": True, "rate": 1.0, "label": "FSP"}}
    new2, _ = moteur.upgrade_params_lot26(custom)
    assert new2["cnss"]["ceiling"] == 700000 and new2["patriotic_support"]["label"] == "FSP"
    # Paramètres déjà à jour : aucun changement
    assert moteur.upgrade_params_lot26(None)[1] == []


# ---------------------------------------------------------------- API
USERS = {
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "client@exemple.bf", "full_name": "M. Client", "company": "CLIENT SARL", "roles": ["client"], "is_active": True},
}
H = {"X-User": "rh"}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot26_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_paie, "_SETUP_DONE_FOR", None)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_paie.router, albarka_docgen.router, albarka_docgen.public_router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def test_startup_migration_runs_once(env):
    """Modèle standard et personnalisation d'un employeur enregistrés avant le
    lot 26 : mis à jour une seule fois au démarrage (ensure_paie_setup)."""
    db = env.db
    asyncio.run(db.paie_modeles.insert_one({"id": "bf-standard", "name": albarka_paie.SYSTEM_TEMPLATE_NAME,
                                            "params": moteur.normalize_params(OLD_LOT8), "is_default": True,
                                            "created_at": "2024-07-01"}))
    asyncio.run(db.paie_employeurs.insert_one({"employer_id": "c1", "template_id": None,
                                               "custom_params": moteur.normalize_params(OLD_LOT8)}))
    tpl = env.c.get("/api/hr/paie/modeles", headers=H).json()["items"][0]
    assert tpl["params"]["cnss"]["ceiling"] == 800000 and tpl["upgraded_lot26"]
    cfg = env.c.get("/api/hr/paie/employeurs/c1", headers=H).json()
    assert cfg["params"]["rounding"]["net"] == {"step": 1, "mode": "up"}
    marker = asyncio.run(db.paie_migrations.find_one({"id": "lot26"}))
    assert marker and marker["templates"] == 1 and marker["employers"] == 1
    # Le cabinet remet ensuite volontairement 600 000 : la migration ne repasse pas
    asyncio.run(db.paie_modeles.update_one({"id": "bf-standard"}, {"$set": {"params.cnss.ceiling": 600000}}))
    albarka_paie._SETUP_DONE_FOR = None
    tpl = env.c.get("/api/hr/paie/modeles", headers=H).json()["items"][0]
    assert tpl["params"]["cnss"]["ceiling"] == 600000


def test_api_exceptional_bonus_pdf_and_year_cumul(env):
    c = env.c
    e = c.post("/api/hr/paie/employees", headers=H, json={**SEGO, "tenant_id": "c1", "role": "Caissière",
                                                          "matricule": "M-42", "cnss_number": "123", "in_kind": 0}).json()
    assert e["in_kind"] == 0
    for month in ("2026-07", "2026-08"):
        c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": month})
    aug = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-08", headers=H).json()["items"][0]
    assert aug["result"]["net_to_pay"] == 69465 and aug["result"]["employer_cost"] == 90251
    # Prime exceptionnelle saisie sur le bulletin : le drapeau est conservé, la CNSS ne bouge pas
    b = c.put(f"/api/hr/paie/bulletins/{aug['id']}", headers=H, json={
        "extras": [{"label": "Prime exceptionnelle", "amount": 20000, "exceptional": True}], "deductions": []}).json()
    assert b["variables"]["extras"][0]["exceptional"] is True
    assert b["result"]["gross"] == 95841 and b["result"]["cnss"] == 4171
    # Cumul de l'année : juillet + août du même salarié chez le même employeur
    ctx = asyncio.run(albarka_paie._bulletin_pdf_context(b))
    assert ctx["cumul_year"]["gross"] == 75841 + 95841
    # PDF : structure du bulletin d'ALBARKA
    pdf = c.get(f"/api/hr/paie/bulletins/{aug['id']}/pdf", headers=H)
    with fitz.open("pdf", pdf.content) as d:
        text = " ".join(" ".join(pg.get_text() for pg in d).split())
    for needle in ("BULLETIN DE PAIE", "CLIENT SARL", "SEGO IRENE", "Total brut", "Cotisations sociales (CNSS)",
                   "Impôt retenu à la source (IUTS)", "Total retenues sociales et fiscales",
                   "Prélèvement pour effort de paix (FSP)", "NET À PAYER", "Impôt sur le salaire", "Cumul",
                   "Masse salariale", "Jours considérés", "Non cadre", "M-42",
                   "Pour vous aider à faire valoir vos droits, conservez ce bulletin de paie sans limitation de durée.",
                   "Édité le", "171 682"):
        assert needle in text, needle
    # Livre de paie : colonne FSP
    lv = c.get("/api/hr/paie/livre?employer_id=c1&period_month=2026-08", headers=H).json()
    assert any(col["label"] == "FSP" for col in lv["columns"])
