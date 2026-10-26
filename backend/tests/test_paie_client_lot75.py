"""Lot 75 — rubrique « Ressources humaines » du client : bulletins VALIDÉS et déclarations CNSS de son entreprise seulement."""
import asyncio
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest
from fastapi import HTTPException

mongomock_motor = pytest.importorskip("mongomock_motor")
import albarka_paie_client as pc  # noqa: E402


def _run(c):
    return asyncio.get_event_loop().run_until_complete(c)


CLIENT = {"id": "cli1", "roles": ["client"], "role": "client"}


def _base(monkeypatch):
    base = mongomock_motor.AsyncMongoMockClient()["test_paie_75"]
    monkeypatch.setattr(pc, "db", base)
    _run(base.paie_bulletins.insert_many([
        {"id": "b1", "employer_id": "cli1", "period_month": "2026-09", "status": "validated", "employee": {"full_name": "Zongo Awa"}, "result": {"gross": 200000, "net_to_pay": 170000}},
        {"id": "b2", "employer_id": "cli1", "period_month": "2026-09", "status": "validated", "employee": {"full_name": "Bako Ali"}, "result": {"gross": 100000, "net_to_pay": 90000}},
        {"id": "b3", "employer_id": "cli1", "period_month": "2026-09", "status": "draft", "employee": {"full_name": "Brouillon"}, "result": {"gross": 1, "net_to_pay": 1}},
        {"id": "b4", "employer_id": "cli1", "period_month": "2026-10", "status": "draft", "employee": {"full_name": "Octobre"}, "result": {}},
        {"id": "b5", "employer_id": "autre", "period_month": "2026-09", "status": "validated", "employee": {"full_name": "Autre employeur"}, "result": {}}]))
    return base


def test_periodes_cnss_mensuelle_et_trimestrielle():
    assert pc.periodes_cnss(["2026-09", "2026-08", "2026-10"], "trimestrielle") == [{"annee": 2026, "numero": 4}, {"annee": 2026, "numero": 3}]
    assert pc.periodes_cnss(["2026-09", "2026-10"], "mensuelle") == [{"annee": 2026, "numero": 10}, {"annee": 2026, "numero": 9}]


def test_bulletins_valides_de_son_employeur_seulement(monkeypatch):
    _base(monkeypatch)
    d = _run(pc.mes_bulletins(period_month="2026-09", user=CLIENT))
    assert [b["full_name"] for b in d["items"]] == ["Bako Ali", "Zongo Awa"]            # ni brouillon ni autre employeur
    assert _run(pc.mes_bulletins(period_month="2026-10", user=CLIENT))["items"] == []   # octobre : brouillon seulement
    with pytest.raises(HTTPException) as e:
        _run(pc.mes_bulletins(period_month="2026-13", user=CLIENT))
    assert e.value.status_code == 400


def test_bulletin_d_un_autre_employeur_ou_brouillon_introuvable(monkeypatch):
    _base(monkeypatch)
    assert _run(pc._bulletin_du_client("b1", "cli1"))["id"] == "b1"
    for bid in ("b3", "b5", "inconnu"):
        with pytest.raises(HTTPException) as e:
            _run(pc._bulletin_du_client(bid, "cli1"))
        assert e.value.status_code == 404


def test_ma_paie_mois_totaux_et_declarations(monkeypatch):
    _base(monkeypatch)

    async def fausse_declaration(employer_id, annee, periodicite="auto", numero=1, inclure_brouillons=False):
        assert employer_id == "cli1" and inclure_brouillons is False
        return {"periodicite": "trimestrielle", "libelle_periode": f"{numero}e trimestre {annee}"}
    monkeypatch.setattr(pc, "construire_declaration", fausse_declaration)
    d = _run(pc.ma_paie(user=CLIENT))
    assert d["mois"] == [{"period_month": "2026-09", "count": 2, "net_to_pay": 260000.0}]
    assert d["declarations"] == [{"annee": 2026, "numero": 3, "periodicite": "trimestrielle", "libelle": "3e trimestre 2026"}]


def test_reserve_aux_clients_et_module_paie(monkeypatch):
    _base(monkeypatch)
    for user in ({"id": "staff", "roles": ["comptable"]}, {"id": "cli1", "roles": ["client"], "portal_modules": ["missions"]}):
        with pytest.raises(HTTPException) as e:
            _run(pc.mes_bulletins(period_month="2026-09", user=user))
        assert e.value.status_code == 403
