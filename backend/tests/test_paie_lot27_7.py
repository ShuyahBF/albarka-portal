"""Lot 27.7 — paie : sursalaire, prime exceptionnelle, primes d'officine ; catégorie / échelon et fonction sur le bulletin ;
adresse complète de l'employeur (BP, IFU, N° employeur, e-mail, téléphone).
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
import albarka_paie_moteur as moteur  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

BASE = {"base_salary": 300000, "dependents": 0, "category": "non_cadre"}


# ---------------------------------------------------------------- moteur
def test_sursalaire_est_dans_le_brut_et_la_base_cnss():
    r = moteur.compute_payslip({**BASE, "allowances": {"surpay": 50000}}, None, "2026-10")
    assert r["gross"] == 350000 and r["cnss_base"] == 350000
    assert any(ln["label"] == "Sursalaire" for ln in r["lines"])


def test_prime_exceptionnelle_en_indemnite_reste_hors_base_cnss():
    r = moteur.compute_payslip({**BASE, "allowances": {"exceptional": 40000}}, None, "2026-10")
    assert r["gross"] == 340000 and r["cnss_base"] == 300000 and r["exceptional_total"] == 40000
    # Même résultat que la prime exceptionnelle saisie sur le bulletin
    autre = moteur.compute_payslip({**BASE, "extras": [{"label": "Prime exceptionnelle", "amount": 40000, "exceptional": True}]},
                                   None, "2026-10")
    assert (r["gross"], r["cnss"], r["iuts"], r["net"]) == (autre["gross"], autre["cnss"], autre["iuts"], autre["net"])


def test_primes_hivernale_et_para_sont_des_gains_imposables_soumis_cnss():
    r = moteur.compute_payslip({**BASE, "allowances": {"winter": 10000, "para": 5000}}, None, "2026-10")
    assert r["gross"] == 315000 and r["cnss_base"] == 315000
    labels = [ln["label"] for ln in r["lines"]]
    assert "Prime hivernale" in labels and "Prime para" in labels


def test_mise_a_jour_des_modeles_enregistres_ajoute_les_rubriques_une_fois():
    ancien = moteur.normalize_params(None)
    ancien["allowances"] = [a for a in ancien["allowances"] if a["key"] not in moteur.LOT27_RUBRIQUES]
    new, changes = moteur.upgrade_params_lot27(ancien)
    assert len(changes) == 4 and {a["key"] for a in new["allowances"]} >= set(moteur.LOT27_RUBRIQUES)
    assert moteur.upgrade_params_lot27(new)[1] == []                      # déjà à jour : rien à faire
    # Un modèle personnalisé garde ses rubriques et ses réglages
    perso = moteur.normalize_params(None)
    perso["allowances"].append({"key": "x1", "label": "Prime maison", "exemption": None})
    assert any(a["key"] == "x1" for a in moteur.upgrade_params_lot27(perso)[0]["allowances"])


# ---------------------------------------------------------------- API
USERS = {
    "rh": {"id": "u-rh", "email": "rh@albarka.bf", "full_name": "RH", "roles": ["rh"], "is_active": True},
    "c1": {"id": "c1", "email": "pharmacie@exemple.bf", "full_name": "Dr Pharma", "company": "PHARMACIE SOLEIL", "phone": "+22670112233",
           "roles": ["client"], "is_active": True},
}
H = {"X-User": "rh"}


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot27_7_test"]
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


def test_migration_lot27_7_ajoute_les_rubriques_une_seule_fois(env):
    ancien = moteur.normalize_params(None)
    ancien["allowances"] = [a for a in ancien["allowances"] if a["key"] not in moteur.LOT27_RUBRIQUES]
    asyncio.run(env.db.paie_modeles.insert_one({"id": "bf-standard", "name": albarka_paie.SYSTEM_TEMPLATE_NAME, "params": ancien,
                                                "is_default": True, "created_at": "2024-07-01"}))
    tpl = env.c.get("/api/hr/paie/modeles", headers=H).json()["items"][0]
    assert {a["key"] for a in tpl["params"]["allowances"]} >= set(moteur.LOT27_RUBRIQUES)
    marker = asyncio.run(env.db.paie_migrations.find_one({"id": "lot27_7"}))
    assert marker and marker["templates"] == 1


def test_adresse_complete_employeur_par_defaut_depuis_la_fiche_client(env):
    asyncio.run(env.db.client_kyc.insert_one({"tenant_id": "c1", "business_name": "PHARMACIE SOLEIL", "address": "Secteur 15, Ouagadougou",
                                              "ifu": "00012345A", "bp": "BP 123 Ouaga 01", "employer_number": "E-778899"}))
    cfg = env.c.get("/api/hr/paie/employeurs/c1", headers=H).json()
    assert (cfg["bp"], cfg["ifu"], cfg["cnss_number"], cfg["email"], cfg["phone"]) == \
        ("BP 123 Ouaga 01", "00012345A", "E-778899", "pharmacie@exemple.bf", "+22670112233")
    # Saisie propre à la paie : prioritaire sur la fiche du client
    c = env.c.put("/api/hr/paie/employeurs/c1", headers=H, json={"bp": "BP 9", "ifu": "99", "officine": True}).json()
    assert c["bp"] == "BP 9" and c["ifu"] == "99" and c["officine"] is True and c["cnss_number"] == "E-778899"


def test_bulletin_pdf_fonction_categorie_echelon_et_adresse_complete(env):
    c = env.c
    c.put("/api/hr/paie/employeurs/c1", headers=H, json={"address": "Secteur 15, Ouagadougou", "bp": "BP 123 Ouaga 01",
                                                         "ifu": "00012345A", "cnss_number": "E-778899", "officine": True,
                                                         "email": "pharmacie@exemple.bf", "phone": "+22670112233"})
    e = c.post("/api/hr/paie/employees", headers=H, json={**BASE, "full_name": "KABORE Awa", "tenant_id": "c1", "role": "Préparatrice",
                                                         "grade": "5", "echelon": "B", "category": "non_cadre",
                                                         "allowances": {"surpay": 20000, "winter": 8000, "para": 4000}}).json()
    assert e["grade"] == "5" and e["echelon"] == "B"
    c.post("/api/hr/paie/bulletins/prepare", headers=H, json={"employer_id": "c1", "period_month": "2026-10"})
    b = c.get("/api/hr/paie/bulletins?employer_id=c1&period_month=2026-10", headers=H).json()["items"][0]
    assert b["employee"]["grade"] == "5" and b["employer"]["bp"] == "BP 123 Ouaga 01"
    pdf = c.get(f"/api/hr/paie/bulletins/{b['id']}/pdf", headers=H)
    with fitz.open("pdf", pdf.content) as d:
        text = " ".join(" ".join(pg.get_text() for pg in d).split())
    for needle in ("Fonction", "Préparatrice", "Catégorie / échelon", "Catégorie 5 · échelon B", "BP 123 Ouaga 01",
                   "E-mail : pharmacie@exemple.bf", "N° IFU : 00012345A", "N° employeur (CNSS) : E-778899",
                   "Sursalaire", "Prime hivernale", "Prime para"):
        assert needle in text, needle
    assert "BP : BP" not in text                       # pas de doublon quand la saisie commence déjà par « BP »
