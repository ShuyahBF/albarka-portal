"""Lot 86 — tâches du personnel et rappel quotidien (autonome : MongoDB simulé, aucun réseau)."""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mongomock_motor  # noqa: E402
import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

import albarka_taches as t  # noqa: E402


@pytest.fixture(autouse=True)
def base(monkeypatch):
    """Base simulée neuve pour chaque test, branchée à la place de la vraie."""
    faux = mongomock_motor.AsyncMongoMockClient()["t"]
    monkeypatch.setattr(t, "db", faux)
    return faux


def _u(uid, roles, **extra):
    return {"id": uid, "full_name": f"Agent {uid}", "roles": roles, "email": f"{uid}@gmail.com", **extra}


def run(coro):
    return asyncio.run(coro)


def test_client_seul_refuse():
    with pytest.raises(HTTPException) as e:
        run(t.mes_taches(user=_u("c1", ["client"])))
    assert e.value.status_code == 403


def test_creer_modifier_cocher_supprimer_et_isolement():
    async def scenario():
        moi, autre = _u("a1", ["comptable"]), _u("a2", ["comptable"])
        tache = await t.creer_tache(t.TacheCreate(titre="Déclarer la TVA", echeance="2026-11-15"), moi)
        assert tache["statut"] == "a_faire"
        # Un autre membre du personnel ne peut ni modifier ni supprimer
        with pytest.raises(HTTPException):
            await t.modifier_tache(tache["id"], t.TacheUpdate(titre="X"), autre)
        with pytest.raises(HTTPException):
            await t.supprimer_tache(tache["id"], autre)
        # Cocher pose la date de réalisation, décocher la retire
        fait = await t.modifier_tache(tache["id"], t.TacheUpdate(statut="fait"), moi)
        assert fait["realisee_le"]
        defait = await t.modifier_tache(tache["id"], t.TacheUpdate(statut="a_faire"), moi)
        assert defait["realisee_le"] is None
        assert len(await t.mes_taches(user=autre)) == 0
        await t.supprimer_tache(tache["id"], moi)
        assert await t.mes_taches(user=moi) == []
    run(scenario())


def test_echeance_invalide_refusee():
    with pytest.raises(HTTPException):
        run(t.creer_tache(t.TacheCreate(titre="x", echeance="31/12/2026"), _u("a1", ["rh"])))


def test_reglage_du_rappel():
    async def scenario(base):
        await base.users.insert_one(_u("a1", ["rh"]))
        moi = _u("a1", ["rh"])
        with pytest.raises(HTTPException):
            await t.regler_rappel(t.RappelPrefs(actif=True, heure="25:99"), moi)
        await t.regler_rappel(t.RappelPrefs(actif=True, heure="07:30"), moi)
        u = await base.users.find_one({"id": "a1"})
        assert u["taches_rappel_actif"] is True and u["taches_rappel_heure"] == "07:30"
    run(scenario(t.db))


def test_vue_personnel_reservee_dg_direction_secretariat():
    async def scenario(base):
        await base.users.insert_many([_u("a1", ["comptable"]), _u("d1", ["dg"])])
        await t.creer_tache(t.TacheCreate(titre="T1"), _u("a1", ["comptable"]))
        done = await t.creer_tache(t.TacheCreate(titre="T2"), _u("a1", ["comptable"]))
        await t.modifier_tache(done["id"], t.TacheUpdate(statut="fait"), _u("a1", ["comptable"]))
        # Un comptable ne peut pas consulter les tâches des autres
        with pytest.raises(HTTPException) as e:
            await t.taches_du_membre("a1", _u("a3", ["comptable"]))
        assert e.value.status_code == 403
        # Le DG, la Direction et le Secrétariat le peuvent
        for roles in (["dg"], ["direction"], ["secretariat"]):
            res = await t.taches_du_membre("a1", _u("x", roles))
            assert [x["statut"] for x in res["taches"]] == ["a_faire", "fait"]
        liste = await t.liste_personnel(_u("d1", ["dg"]))
        a1 = next(m for m in liste if m["id"] == "a1")
        assert (a1["a_faire"], a1["faites"]) == (1, 1)
    run(scenario(t.db))


def _fake_envois(monkeypatch):
    envoyes = []

    async def faux_wa(*, to_phone, message, reply_to=None):
        envoyes.append(("wa", to_phone, message))
        return {"ok": True}

    async def faux_mail(**kw):
        envoyes.append(("mail", kw["to"], kw["subject"]))
    import albarka_notifications as n
    monkeypatch.setattr(n, "send_whatsapp", faux_wa)
    monkeypatch.setattr(n, "send_email", faux_mail)
    return envoyes


def test_rappel_a_l_heure_choisie_une_seule_fois_par_jour(monkeypatch):
    envoyes = _fake_envois(monkeypatch)

    async def scenario(base):
        await base.users.insert_many([
            _u("a1", ["comptable"], taches_rappel_actif=True, taches_rappel_heure="08:00", whatsapp_number="+22670000001"),
            _u("a2", ["comptable"], taches_rappel_actif=True, taches_rappel_heure="18:00", whatsapp_number="+22670000002"),
            _u("a3", ["comptable"], taches_rappel_actif=False, taches_rappel_heure="08:00", whatsapp_number="+22670000003"),
        ])
        for uid in ("a1", "a2", "a3"):
            await t.creer_tache(t.TacheCreate(titre=f"Tâche de {uid}", echeance="2026-11-01"), _u(uid, ["comptable"]))
        avant = datetime(2026, 11, 9, 7, 59, tzinfo=timezone.utc)
        heure = datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)
        assert await t.envoyer_rappels_taches(avant) == 0          # trop tôt
        assert await t.envoyer_rappels_taches(heure) == 1          # seul a1 (a2 plus tard, a3 inactif)
        assert await t.envoyer_rappels_taches(heure) == 0          # pas de doublon dans la journée
        assert [e[1] for e in envoyes] == ["+22670000001"]
        assert "EN RETARD" in envoyes[0][2]                         # échéance dépassée signalée
        # Le lendemain, le rappel repart
        lendemain = datetime(2026, 11, 10, 8, 5, tzinfo=timezone.utc)
        assert await t.envoyer_rappels_taches(lendemain) == 1
    run(scenario(t.db))


def test_rappel_sans_tache_ou_notifications_coupees_ne_part_pas(monkeypatch):
    envoyes = _fake_envois(monkeypatch)

    async def scenario(base):
        await base.users.insert_many([
            _u("a1", ["rh"], taches_rappel_actif=True, taches_rappel_heure="08:00", whatsapp_number="+22670000001"),
            _u("a2", ["rh"], taches_rappel_actif=True, taches_rappel_heure="08:00", whatsapp_number="+22670000002",
               can_receive_notifications=False),
        ])
        await t.creer_tache(t.TacheCreate(titre="x"), _u("a2", ["rh"]))   # a1 : aucune tâche ; a2 : notifications coupées
        assert await t.envoyer_rappels_taches(datetime(2026, 11, 9, 8, 0, tzinfo=timezone.utc)) == 0
        assert envoyes == []
    run(scenario(t.db))


def test_rappel_par_email_si_pas_de_whatsapp(monkeypatch):
    envoyes = _fake_envois(monkeypatch)

    async def scenario(base):
        await base.users.insert_one(_u("a1", ["rh"], taches_rappel_actif=True, taches_rappel_heure="08:00"))
        await t.creer_tache(t.TacheCreate(titre="Payer la CNSS"), _u("a1", ["rh"]))
        assert await t.envoyer_rappels_taches(datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)) == 1
        assert envoyes[0][0] == "mail"
    run(scenario(t.db))
