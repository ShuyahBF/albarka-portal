"""Lot 68 — déclarations CNSS (feuilles BTN et DECLARATION) construites depuis les bulletins validés.

Reproduit l'exemple du classeur Excel du propriétaire (PHARMACIE ELITE, 3e trimestre 2026, 7 salariés) :
  base soumise = montant mensuel × 3 mois ; taux 21,5 % = 14 % + 1,5 % + 6 %.
Tests autonomes : MongoDB simulé (mongomock-motor), connexion simulée par l'en-tête X-User.
Lancer : cd backend && REACT_APP_BACKEND_URL=http://localhost:1 python -m pytest tests/test_paie_cnss_lot68.py -q
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
openpyxl = pytest.importorskip("openpyxl")

import albarka_paie  # noqa: E402
import albarka_paie_cnss  # noqa: E402
import db as db_module  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "compta": {"id": "u-cpt", "email": "cpt@albarka.bf", "full_name": "Comptable", "roles": ["comptable"], "is_active": True},
    "c1": {"id": "c1", "email": "elite@exemple.bf", "full_name": "M. Elite", "company": "PHARMACIE ELITE", "phone": "25 41 91 77",
           "roles": ["client"], "is_active": True},
}
H = {"X-User": "rh"}
# (nom, n° CNSS, base mensuelle plafonnée) — valeurs de la feuille BTN du classeur
SALARIES = [("ROUAMBA Habibou", "271041080010R", 118666), ("KABORE Elise", "278061105054F", 118627),
            ("OUEDRAOGO Lydie", "289016020033M", 84806), ("BADINI Samiratou", "293091705002V", 84868),
            ("MAIGA Mariatta", "284051105103Z", 91062), ("MOUGNIGA Aicha", "293061110042D", 79981),
            ("ILBOUDO Hamado", "", 800000)]
SOMME_MENSUELLE = sum(b for _, _, b in SALARIES)


async def _bulletins(db, mois, statut="validated", salaries=SALARIES, employeur="c1"):
    """Crée salariés (une fois) et un bulletin par salarié et par mois, avec la base CNSS plafonnée du moteur de paie."""
    for i, (nom, cnss, base) in enumerate(salaries):
        eid = f"e{i}"
        if not await db.employees.find_one({"id": eid}):
            await db.employees.insert_one({"id": eid, "tenant_id": employeur, "full_name": nom, "cnss_number": cnss})
        for m in mois:
            await db.paie_bulletins.insert_one({
                "id": f"b-{eid}-{m}", "employer_id": employeur, "employee_id": eid, "period_month": m, "status": statut,
                "employee": {"full_name": nom, "cnss_number": cnss},
                "result": {"cnss_base": base, "employer_cnss_base": base}})


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot68_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_paie, "_SETUP_DONE_FOR", None)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))
    asyncio.run(mock_db.client_kyc.insert_one({"tenant_id": "c1", "business_name": "PHARMACIE ELITE", "address": "OUAGADOUGOU",
                                               "employer_number": "235844 C"}))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(albarka_paie_cnss.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


Q3 = {"employer_id": "c1", "annee": 2026, "numero": 3}


def test_trimestre_sous_20_salaries_reproduit_le_classeur(env):
    asyncio.run(_bulletins(env.db, ["2026-07", "2026-08", "2026-09"]))
    d = env.c.get("/api/hr/paie/cnss/declaration", params=Q3, headers=H).json()
    assert d["periodicite"] == "trimestrielle" and d["effectif"] == 7                     # moins de 20 : trimestre
    assert (d["debut"], d["fin"]) == ("2026-07-01", "2026-09-30")
    assert d["employer"]["cnss_number"] == "235844 C" and d["employer"]["name"] == "PHARMACIE ELITE"
    assert len(d["lignes"]) == 7 and all(l["observation"] == "3 Mois" for l in d["lignes"])
    assert d["total_remuneration"] == SOMME_MENSUELLE * 3                                 # 800000 × 3 pour ILBOUDO, etc.
    ilboudo = next(l for l in d["lignes"] if l["full_name"].startswith("ILBOUDO"))
    assert ilboudo["remuneration"] == 2_400_000 and ilboudo["cnss_number"] == "EN COURS"  # n° absent → « EN COURS »
    # DECLARATION : 14 % + 1,5 % + 6 % = 21,5 %
    total = SOMME_MENSUELLE * 3
    assert [b["taux"] for b in d["branches"]] == [14.0, 1.5, 6.0] and d["taux_total"] == 21.5
    assert [b["cotisation"] for b in d["branches"]] == [round(total * 0.14), round(total * 0.015), round(total * 0.06)]
    assert d["cotisations"] == sum(b["cotisation"] for b in d["branches"])
    assert abs(d["cotisations"] - total * 0.215) <= 2                                      # arrondis au franc par branche
    assert d["travailleurs"]["permanents"] == 7


def test_20_salaries_ou_plus_declaration_mensuelle(env):
    gros = [(f"Salarié {i:02d}", f"N{i:05d}", 100000) for i in range(20)]
    asyncio.run(_bulletins(env.db, ["2026-08"], salaries=gros))
    d = env.c.get("/api/hr/paie/cnss/declaration", params={"employer_id": "c1", "annee": 2026, "numero": 8}, headers=H).json()
    assert d["effectif"] == 20 and d["periodicite"] == "mensuelle" and d["libelle_periode"] == "août 2026"
    assert (d["debut"], d["fin"]) == ("2026-08-01", "2026-08-31") and d["total_remuneration"] == 2_000_000
    assert d["cotisations"] == 430_000                                                     # 21,5 % de 2 000 000
    # Périodicité imposée à la main
    forcee = env.c.get("/api/hr/paie/cnss/declaration", params={**Q3, "periodicite": "trimestrielle"}, headers=H).json()
    assert forcee["periodicite"] == "trimestrielle" and len(forcee["mois"]) == 3


def test_brouillons_non_comptes_sauf_demande_et_alertes(env):
    asyncio.run(_bulletins(env.db, ["2026-07", "2026-08"]))
    asyncio.run(_bulletins(env.db, ["2026-09"], statut="draft"))                          # septembre pas encore validé
    d = env.c.get("/api/hr/paie/cnss/declaration", params=Q3, headers=H).json()
    assert d["total_remuneration"] == SOMME_MENSUELLE * 2 and all(l["observation"] == "2 Mois" for l in d["lignes"])
    assert any("brouillon" in a for a in d["alertes"])
    avec = env.c.get("/api/hr/paie/cnss/declaration", params={**Q3, "inclure_brouillons": True}, headers=H).json()
    assert avec["total_remuneration"] == SOMME_MENSUELLE * 3
    vide = env.c.get("/api/hr/paie/cnss/declaration", params={**Q3, "numero": 1}, headers=H).json()
    assert vide["lignes"] == [] and vide["cotisations"] == 0 and any("Aucun bulletin validé" in a for a in vide["alertes"])


def test_pdf_btn_recap_et_complet(env):
    asyncio.run(_bulletins(env.db, ["2026-07", "2026-08", "2026-09"]))
    env.c.put("/api/hr/paie/cnss/c1/declarant", json={"nom": "SAWADOGO Irène", "ville": "OUAGADOUGOU"}, headers=H)
    textes = {}
    for nom, url in (("btn", "btn/pdf"), ("recap", "recap/pdf"), ("tout", "pdf")):
        r = env.c.get(f"/api/hr/paie/cnss/{url}", params=Q3, headers=H)
        assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content[:4] == b"%PDF"
        with fitz.open(stream=r.content, filetype="pdf") as pdf:
            textes[nom] = (len(pdf), "\n".join(p.get_text() for p in pdf), pdf[0].rect)
    assert textes["btn"][2].width > textes["btn"][2].height                               # BTN en paysage
    assert textes["recap"][2].height > textes["recap"][2].width                           # DECLARATION en portrait
    assert textes["tout"][0] == textes["btn"][0] + textes["recap"][0]
    assert "235844 C" in textes["btn"][1] and "ROUAMBA Habibou" in textes["btn"][1] and "EN COURS" in textes["btn"][1]
    assert "2 400 000" in textes["btn"][1] and "21,5 %" in textes["btn"][1]
    assert "DÉCLARATION RÉCAPITULATIVE DES SALAIRES" in textes["recap"][1] and "Assurance vieillesse" in textes["recap"][1]
    assert "SAWADOGO Irène" in textes["recap"][1] and "14 %" in textes["recap"][1] and "1,5 %" in textes["recap"][1]


def test_pdf_btn_plusieurs_pages_avec_total_a_la_fin(env):
    gros = [(f"Salarié {i:02d}", f"N{i:05d}", 100000) for i in range(60)]
    asyncio.run(_bulletins(env.db, ["2026-08"], salaries=gros))
    r = env.c.get("/api/hr/paie/cnss/btn/pdf", params={"employer_id": "c1", "annee": 2026, "numero": 8}, headers=H)
    with fitz.open(stream=r.content, filetype="pdf") as pdf:
        assert len(pdf) >= 2 and "COTISATIONS" in pdf[len(pdf) - 1].get_text()


def test_excel_deux_feuilles_avec_formules(env):
    asyncio.run(_bulletins(env.db, ["2026-07", "2026-08", "2026-09"]))
    r = env.c.get("/api/hr/paie/cnss/excel", params=Q3, headers=H)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    wb = openpyxl.load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["BTN", "DECLARATION"]
    btn, recap = wb["BTN"], wb["DECLARATION"]
    assert btn["G3"].value == "235844 C" and btn["B7"].value == "BADINI Samiratou" and btn["D7"].value == 84868 * 3   # ordre alphabétique
    assert btn["B8"].value == "ILBOUDO Hamado" and btn["D8"].value == 2_400_000 and btn["D14"].value == "=SUM(D7:D13)"        # 7 lignes (7 à 13) → total ligne 14
    assert recap["G25"].value == "=SUM(G22:G24)" and recap["E22"].value == "=BTN!$D$14" and btn["D16"].value == "=ROUND(D14*D15,0)"


def test_acces_reserve_aux_roles_rh_et_declarant_memorise(env):
    assert env.c.get("/api/hr/paie/cnss/declaration", params=Q3, headers={"X-User": "compta"}).status_code == 403
    assert env.c.get("/api/hr/paie/cnss/declaration", params=Q3).status_code == 401
    assert env.c.put("/api/hr/paie/cnss/c1/declarant", json={"nom": "X"}, headers={"X-User": "compta"}).status_code == 403
    assert env.c.put("/api/hr/paie/cnss/inconnu/declarant", json={"nom": "X"}, headers=H).status_code == 404
    env.c.put("/api/hr/paie/cnss/c1/declarant", json={"nom": "SAWADOGO Irène", "ville": "BOBO-DIOULASSO"}, headers=H)
    d = env.c.get("/api/hr/paie/cnss/declaration", params=Q3, headers=H).json()
    assert d["declarant"] == "SAWADOGO Irène" and d["ville"] == "BOBO-DIOULASSO"
    assert env.c.get("/api/hr/paie/cnss/declaration", params={**Q3, "numero": 5}, headers=H).status_code == 422   # trimestre 1 à 4
    assert env.c.get("/api/hr/paie/cnss/declaration", params={**Q3, "periodicite": "annuelle"}, headers=H).status_code == 422
