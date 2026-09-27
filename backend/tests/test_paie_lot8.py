"""Lot 8 — paie Burkina Faso entièrement paramétrable.

- moteur : reproduction EXACTE du fichier du cabinet « Assistante_cardi_pro_ESSAI.xlsx »
  (brut 341 672, CNSS 18 791,96, base IUTS 182 906, IUTS 24 870,60, abattement
  famille 1 989,65, IUTS net 22 880,95) et, avec les arrondis par défaut
  (franc, base IUTS à la centaine inférieure, net à la centaine), net 300 000
  et net à payer 297 000 comme sur le bulletin ;
- ancienneté à partir de 3 ans, charges de famille et abattement par catégorie
  paramétrables, mode « net négocié → brut » ;
- modèles de configuration (Appliquer, Restaurer les valeurs par défaut),
  employeur cabinet ou client avec personnalisation (Restaurer les valeurs du
  modèle), bulletins (préparation, variables, validation), PDF avec QR code,
  livre de paie avec charges patronales ;
- factures : TVA et retenue arrondies au franc (0,5 vers le haut), retenue
  avec IFU 5 % / sans IFU 10 % et libellé modifiables.
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
import albarka_phase_c  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

SANDRINE = {"base_salary": 231672, "allowances": {"housing": 50000, "transport": 30000, "function": 30000}, "dependents": 1}
EXACT = {"rounding": {"amounts": {"step": 0}, "iuts_base": {"step": 1, "mode": "down"}, "net": {"step": 0}}}


# ---------------------------------------------------------------- moteur
def test_reproduces_excel_exactly():
    r = moteur.compute_payslip(SANDRINE, EXACT, "2024-07")
    assert r["gross"] == 341672
    assert r["cnss"] == pytest.approx(18791.96) and r["cnss_fiscal"] == pytest.approx(18533.76)
    assert r["taxable"] == pytest.approx(323138.24) and r["exemptions_total"] == pytest.approx(82313.824)
    assert r["flat_abatement"] == pytest.approx(57918) and r["iuts_base"] == 182906
    assert r["iuts_gross"] == pytest.approx(24870.602) and r["family_abatement"] == pytest.approx(1989.64816)
    assert r["iuts"] == pytest.approx(22880.95384) and r["net_raw"] == pytest.approx(299999.08616)


def test_default_rounding_gives_payslip_values():
    r = moteur.compute_payslip(SANDRINE, None, "2024-07")
    assert (r["cnss"], r["iuts_base"], r["iuts_gross"], r["family_abatement"], r["iuts"]) == (18792, 182900, 24869, 1990, 22879)
    assert r["net"] == 300000 and r["patriotic_support"] == 3000 and r["net_to_pay"] == 297000
    # Charges patronales : CNSS 16 % du brut plafonné + TPA 3 % du brut
    # 7 % -> 23 917, 3,5 % -> 11 959, 5,5 % -> 18 792, TPA 3 % -> 10 250
    assert [x["amount"] for x in r["employer_charges"]] == [23917, 11959, 18792, 10250] and r["employer_total"] == 64918
    assert [x["label"] for x in r["employer_charges"]][-1].startswith("Taxe patronale")


def test_rounding_rules():
    rr = moteur.round_rule
    assert rr(9473.5, {"step": 1, "mode": "nearest"}) == 9474 and rr(299999.09, {"step": 100, "mode": "nearest"}) == 300000
    assert rr(182906, {"step": 100, "mode": "down"}) == 182900 and rr(101, {"step": 5, "mode": "up"}) == 105
    assert rr(12.34, {"step": 0}) == 12.34


def test_seniority_family_category_and_net_mode():
    p = moteur.normalize_params(None)
    assert moteur.years_of_service("2021-08-01", "2024-07") == 2 and moteur.years_of_service("2021-07-15", "2024-07") == 3
    assert moteur.seniority_rate(2, p["seniority"]) == 0 and moteur.seniority_rate(3, p["seniority"]) == 5
    assert moteur.seniority_rate(10, p["seniority"]) == 12 and moteur.seniority_rate(40, p["seniority"]) == 25
    r = moteur.compute_payslip({**SANDRINE, "hire_date": "2020-01-10"}, None, "2024-07")    # 4 ans -> 6 %
    assert r["seniority"] == round(231672 * 0.06) and r["gross"] == 341672 + r["seniority"]
    # Charges de famille : table libre, la dernière ligne vaut au-delà
    custom = {"family_abatement": [{"charges": 1, "rate": 8}, {"charges": 6, "rate": 18}, {"charges": 7, "rate": 25}]}
    assert moteur.family_rate(9, moteur.normalize_params(custom)["family_abatement"]) == 25
    assert moteur.family_rate(4, moteur.normalize_params(custom)["family_abatement"]) == 8
    # Abattement forfaitaire par catégorie
    cat = {"flat_abatement": {"mode": "by_category", "categories": [{"key": "cadre", "label": "Cadre", "rate": 20},
                                                                   {"key": "nc", "label": "Non cadre", "rate": 25}]}}
    assert moteur.compute_payslip({**SANDRINE, "category": "cadre"}, cat, "2024-07")["flat_abatement"] == round(231672 * 0.20)
    # Net négocié -> salaire de base
    base = moteur.base_for_net(SANDRINE, 300000, None, "2024-07")
    assert 231600 < base < 231700
    assert moteur.compute_payslip({**SANDRINE, "base_salary": base}, None, "2024-07")["net"] == 300000


def test_invalid_params_rejected():
    with pytest.raises(ValueError, match="croissantes"):
        moteur.normalize_params({"iuts_brackets": [{"up_to": 50000, "rate": 10}, {"up_to": 30000, "rate": 12}, {"up_to": None, "rate": 25}]})
    with pytest.raises(ValueError, match="doublon"):
        moteur.normalize_params({"family_abatement": [{"charges": 1, "rate": 8}, {"charges": 1, "rate": 9}]})
    with pytest.raises(ValueError, match="entre 0 et 100"):
        moteur.normalize_params({"cnss": {"employee_rate": 150}})


def test_invoice_rounding_half_up():
    t = albarka_phase_c._invoice_totals([{"quantity": 1, "unit_price": 52632}], 18, 5)
    assert t["tax"] == 9474 and t["withholding"] == 2632 and t["net_to_pay"] == 59474
    assert albarka_phase_c.round_franc(2.5) == 3 and albarka_phase_c.round_franc(9473.5) == 9474


# ---------------------------------------------------------------- API
USERS = {
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "c1": {"id": "c1", "email": "card@exemple.bf", "full_name": "M. Yaolile", "company": "CARD-IPRO SARL", "roles": ["client"], "is_active": True},
}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot8_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    asyncio.run(mock_db.client_kyc.insert_one({"tenant_id": "c1", "business_name": "CARD-IPRO SARL", "address": "13 BP 156 OUAGA 13"}))
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


H = {"X-User": "rh"}


def test_templates_and_employer_config(env):
    c = env.c
    assert c.get("/api/hr/paie/modeles", headers={"X-User": "secr"}).status_code == 403
    tpls = c.get("/api/hr/paie/modeles", headers=H).json()["items"]
    assert len(tpls) == 1 and tpls[0]["name"] == albarka_paie.SYSTEM_TEMPLATE_NAME and tpls[0]["is_default"]
    std = tpls[0]
    # Nouveau modèle « par catégorie », modifié puis « Appliquer », puis restauré
    t = c.post("/api/hr/paie/modeles", headers=H, json={"name": "Clients — cadres"}).json()
    params = t["params"]
    params["flat_abatement"]["mode"] = "by_category"
    params["patriotic_support"]["rate"] = 2
    t2 = c.put(f"/api/hr/paie/modeles/{t['id']}", headers=H, json={"name": "Clients — cadres", "params": params}).json()
    assert t2["params"]["flat_abatement"]["mode"] == "by_category" and t2["params"]["patriotic_support"]["rate"] == 2
    bad = dict(params, iuts_brackets=[{"up_to": 5, "rate": 10}, {"up_to": 1, "rate": 10}])
    assert c.put(f"/api/hr/paie/modeles/{t['id']}", headers=H, json={"name": "X", "params": bad}).status_code == 400
    t3 = c.post(f"/api/hr/paie/modeles/{t['id']}/restore-defaults", headers=H).json()
    assert t3["params"]["patriotic_support"]["rate"] == 1 and t3["params"]["flat_abatement"]["mode"] == "single"
    # Employeurs : cabinet + client ; le client utilise le modèle et le personnalise
    emps = c.get("/api/hr/paie/employeurs", headers=H).json()["items"]
    assert [e["employer_id"] for e in emps] == ["cabinet", "c1"] and emps[1]["template_id"] == std["id"]
    cfg = c.put("/api/hr/paie/employeurs/c1", headers=H, json={"template_id": t["id"], "cnss_number": "123456"}).json()
    assert cfg["template_name"] == "Clients — cadres" and not cfg["customized"] and cfg["name"] == "CARD-IPRO SARL"
    custom = cfg["params"]
    custom["seniority"]["start_years"] = 2
    cfg = c.put("/api/hr/paie/employeurs/c1", headers=H, json={"template_id": t["id"], "custom_params": custom}).json()
    assert cfg["customized"] and cfg["params"]["seniority"]["start_years"] == 2
    cfg = c.post("/api/hr/paie/employeurs/c1/restore-template", headers=H).json()
    assert not cfg["customized"] and cfg["params"]["seniority"]["start_years"] == 3
    # Modèle utilisé : suppression refusée
    assert c.delete(f"/api/hr/paie/modeles/{t['id']}", headers=H).status_code == 409


def test_bulletins_ledger_pdf_and_verify(env):
    c = env.c
    e = c.post("/api/hr/paie/employees", headers=H, json={
        "tenant_id": "c1", "full_name": "S.W.N. Sandrine YAOLILE", "role": "Assistante Administrative", "dependents": 1,
        "base_salary": 231672, "allowances": {"housing": 50000, "transport": 30000, "function": 30000}}).json()
    c.post("/api/hr/paie/employees", headers=H, json={
        "tenant_id": "c1", "full_name": "Net négocié", "pay_mode": "net", "net_target": 300000, "dependents": 1,
        "allowances": {"housing": 50000, "transport": 30000, "function": 30000}})
    staff = c.post("/api/hr/paie/employees", headers=H, json={"tenant_id": "cabinet", "full_name": "Comptable du cabinet",
                                                              "base_salary": 150000, "hire_date": "2019-03-01"}).json()
    assert staff["tenant_id"] == "cabinet"
    assert c.post("/api/hr/paie/employees", headers=H, json={"tenant_id": "inconnu", "full_name": "XX"}).status_code == 404

    p = c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2024-07"}).json()
    assert p["created"] == 2
    lst = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2024-07", headers=H).json()
    sandrine = next(b for b in lst["items"] if b["employee_id"] == e["id"])
    assert sandrine["result"]["net"] == 300000 and sandrine["result"]["net_to_pay"] == 297000
    nego = next(b for b in lst["items"] if b["employee_id"] != e["id"])
    assert nego["result"]["net"] == 300000 and 231600 < nego["result"]["base_salary"] < 231700
    # Éléments du mois : acompte -> net à payer diminué
    b = c.put(f"/api/hr/paie/bulletins/{sandrine['id']}", headers=H, json={"deductions": [{"label": "Acompte", "amount": 50000}],
                                                                           "extras": [], "notes": "Acompte du 15"}).json()
    assert b["result"]["net_to_pay"] == 247000
    # Validation : figé (la re-préparation ne le recalcule pas)
    c.post(f"/api/hr/paie/bulletins/{sandrine['id']}/validate", headers=H)
    assert c.put(f"/api/hr/paie/bulletins/{sandrine['id']}", headers=H, json={}).status_code == 409
    assert c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2024-07"}).json()["updated"] == 1
    # PDF du bulletin
    pdf = c.get(f"/api/hr/paie/bulletins/{sandrine['id']}/pdf", headers=H)
    with fitz.open("pdf", pdf.content) as d:
        text = " ".join(" ".join(pg.get_text() for pg in d).split())
    assert "BULLETIN DE PAIE" in text and "CARD-IPRO SARL" in text and "YAOLILE" in text and "247 000" in text
    assert "Soutien patriotique" in text and "sans limitation de durée" in text
    # Vérification par QR code
    tok = env_db_token(env, sandrine["id"])
    v = c.get(f"/api/public/verify/{tok}").json()
    assert v["valid"] and v["kind"] == "Bulletin de paie" and v["client"] == "CARD-IPRO SARL" and v["amount"] == 247000
    # Livre de paie : charges patronales
    lv = c.get("/api/hr/paie/livre?employer_id=c1&period_month=2024-07", headers=H).json()
    assert lv["totals"]["count"] == 2 and lv["totals"]["employer_total"] > 0
    assert {x["label"] for x in lv["totals"]["employer_detail"]} >= {"Prestations familiales", "Taxe patronale d'apprentissage (TPA)"}
    csv = c.get("/api/hr/paie/livre/csv?employer_id=c1&period_month=2024-07", headers=H)
    assert "YAOLILE" in csv.text and "Charges patronales" in csv.text
    assert c.get("/api/hr/paie/livre/pdf?employer_id=c1&period_month=2024-07", headers=H).content[:4] == b"%PDF"
    allp = c.get("/api/hr/paie/bulletins-pdf?employer_id=c1&period_month=2024-07", headers=H)
    with fitz.open("pdf", allp.content) as d:
        assert d.page_count == 2
    # Personnel du cabinet : ancienneté (5 ans en juillet 2024 -> 7 %)
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "cabinet", "period_month": "2024-07"})
    cab = c.get("/api/hr/paie/bulletins?employer_id=cabinet&period_month=2024-07", headers=H).json()["items"][0]
    assert cab["result"]["seniority_rate"] == 7 and cab["result"]["seniority"] == 10500


def env_db_token(env, bid):
    return asyncio.run(env.db.paie_bulletins.find_one({"id": bid}))["verify_token"]


def test_review_fixes(env):
    """Corrections après revue : net négocié + primes, catégorie absente, section
    nulle, modèle par défaut suivi, client supprimé, double préparation."""
    c = env.c
    # Sans catégorie en mode « par catégorie » : taux général (25 %), pas celui de la 1re catégorie
    cat = {"flat_abatement": {"mode": "by_category", "rate": 25, "categories": [{"key": "cadre", "label": "Cadre", "rate": 20}]}}
    assert moteur.compute_payslip(SANDRINE, cat, "2024-07")["flat_abatement"] == round(231672 * 0.25)
    # Section nulle : valeurs par défaut (et plus d'erreur 500)
    assert moteur.normalize_params({"cnss": None, "rounding": None})["cnss"]["employee_rate"] == 5.5
    # Employeur sans modèle choisi : il suit le modèle par défaut même après « Appliquer »
    cfg = c.put("/api/hr/paie/employeurs/c1", headers=H, json={"template_id": None, "cnss_number": "1"}).json()
    assert cfg["chosen_template_id"] is None
    # Net négocié : une prime du mois s'ajoute au net au lieu de baisser le salaire de base
    e = c.post("/api/hr/paie/employees", headers=H, json={
        "tenant_id": "c1", "full_name": "Net négocié", "pay_mode": "net", "net_target": 300000, "dependents": 1,
        "allowances": {"housing": 50000, "transport": 30000, "function": 30000}}).json()
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2024-07"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2024-07", headers=H).json()["items"][0]
    base = b["result"]["base_salary"]
    b = c.put(f"/api/hr/paie/bulletins/{b['id']}", headers=H, json={"extras": [{"label": "Prime", "amount": 50000}], "deductions": []}).json()
    assert b["result"]["base_salary"] == base and b["result"]["net"] > 300000
    # Double préparation simultanée : pas d'erreur (index unique respecté)
    assert c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2024-08"}).status_code == 200
    # Client supprimé : le livre de paie de ses mois passés reste consultable
    asyncio.run(env.db.users.delete_one({"id": "c1"}))
    lv = c.get("/api/hr/paie/livre?employer_id=c1&period_month=2024-07", headers=H)
    assert lv.status_code == 200 and lv.json()["employer"]["name"] == "CARD-IPRO SARL"
    assert c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2024-09"}).status_code == 404
    assert e["tenant_id"] == "c1"
