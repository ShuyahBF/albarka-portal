"""Lot 16 — Connexion du personnel par WhatsApp (numéro + PIN, puis code OTP).

Couvre (même principe que DentalCare, tests/test_medecins_pin_whatsapp.py) :
  - PIN à 4 chiffres généré par un gestionnaire du personnel, affiché une
    seule fois, envoi WhatsApp facultatif, seul le hachage en base (collection
    à part), jamais renvoyé par /clients/staff ni /staff-pin ;
  - numéro WhatsApp obligatoire, Superviseur / compte admin / clients exclus,
    droits (un comptable ne génère pas de PIN, un DG ne touche pas au PIN
    d'un Administrateur) ;
  - connexion complète : numéro (formats variés) + PIN → code reçu par
    WhatsApp → /auth/verify-otp → jeton du collaborateur ;
  - 5 PIN faux en 15 minutes bloquent le numéro (429, même avec le bon PIN) ;
  - un code OTP faux 5 fois est annulé ;
  - compte désactivé ou PIN retiré : plus de connexion ;
  - échec d'envoi WhatsApp : erreur claire, code annulé, jamais affiché ;
  - numéro de lot.
Tests autonomes : MongoDB simulé (mongomock-motor), WhatsApp simulé.
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
import albarka_auth  # noqa: E402
import albarka_clients  # noqa: E402
import albarka_connexion_whatsapp as cw  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

# Comptes de test : gestionnaires du personnel, collaborateurs, exclus
USERS = {
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg"], "is_active": True},
    "adm": {"id": "u-adm", "email": "adm@albarka.bf", "full_name": "Admin", "roles": ["administrateur"],
            "is_active": True, "phone": "+226 71 00 00 01"},
    "compta": {"id": "u-compta", "email": "compta@albarka.bf", "full_name": "Comptable", "roles": ["comptable"],
               "is_active": True, "phone": "70 11 22 33"},
    "secr": {"id": "u-secr", "email": "secr@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"],
             "is_active": True, "phone": "+22670000009", "whatsapp_number": "+226 76 55 44 33"},
    "sans_tel": {"id": "u-st", "email": "st@albarka.bf", "full_name": "Sans téléphone", "roles": ["rh"], "is_active": True},
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Superviseur", "roles": ["superviseur"],
            "is_active": True, "phone": "+22672000000"},
    "client": {"id": "c1", "email": "c1@exemple.bf", "full_name": "Client", "roles": ["client"],
               "is_active": True, "phone": "+22673000000"},
}


@pytest.fixture()
def env(monkeypatch):
    """Base simulée branchée dans tous les modules, WhatsApp simulé, API
    minimale : vraies routes de connexion + routes PIN avec l'utilisateur
    choisi par l'en-tête X-User."""
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot16_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([{**u, "password_hash": albarka_auth.hash_password("Secret-123")}
                                           for u in USERS.values()]))

    # WhatsApp simulé : on garde les messages envoyés
    envois = []
    etat = {"ok": True}

    async def faux_whatsapp(numero, message, **kwargs):
        envois.append((numero, message))
        return {"ok": etat["ok"], "canal": "liluvine"}
    monkeypatch.setattr(cw, "envoyer_whatsapp", faux_whatsapp)

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_auth.router, cw.auth_router, cw.router, albarka_clients.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0, "password_hash": 0})
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app, raise_server_exceptions=False) as client:
        yield type("Env", (), {"c": client, "db": mock_db, "envois": envois, "etat": etat})


def _h(u):
    return {"X-User": u}


def _code_recu(env):
    """Code à 6 chiffres du dernier WhatsApp envoyé."""
    return "".join(c for c in env.envois[-1][1].split(":")[1] if c.isdigit())[:6]


def _pin(env, cible="compta", par="dg", **corps):
    r = env.c.post(f"/api/staff-pin/{USERS[cible]['id']}", json=corps, headers=_h(par))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- fonctions communes ----------
def test_normalisation_des_numeros():
    assert cw.numero_international("70 11 22 33") == "+22670112233"
    assert cw.numero_international("+226 70-11-22-33") == "+22670112233"
    assert cw.numero_international("0022670112233") == "+22670112233"
    assert cw.numero_international("123") == "" and cw.numero_international(None) == ""
    assert cw.pin_valide("0420") and not cw.pin_valide("042") and not cw.pin_valide("04a0")
    assert all(len(cw.generer_pin()) == 4 and cw.generer_pin().isdigit() for _ in range(20))


# ---------- 1) code PIN ----------
def test_pin_genere_une_fois_seul_le_hachage_en_base(env):
    data = _pin(env, envoyer_whatsapp=True)
    pin = data["pin"]
    assert len(pin) == 4 and pin.isdigit()
    assert data["numero_whatsapp"] == "+22670112233" and data["envoye_whatsapp"] is True
    assert env.envois[-1][0] == "+22670112233" and pin in env.envois[-1][1]
    fiche = asyncio.run(env.db.pins_whatsapp.find_one({"user_id": "u-compta"}))
    assert fiche["pin_hash"] != pin and fiche["pin_hash"].startswith("$2")
    # Jamais renvoyé : ni par la liste des PIN, ni par la liste du personnel
    liste = env.c.get("/api/staff-pin", headers=_h("dg")).json()
    assert liste and all("pin_hash" not in x for x in liste) and liste[0]["user_id"] == "u-compta"
    staff = env.c.get("/api/clients/staff", headers=_h("dg")).text
    assert "pin_hash" not in staff and fiche["pin_hash"] not in staff


def test_pin_sans_envoi_whatsapp_par_defaut(env):
    data = _pin(env)
    assert data["envoye_whatsapp"] is None and env.envois == []


def test_pin_exige_un_numero_whatsapp(env):
    r = env.c.post("/api/staff-pin/u-st", json={}, headers=_h("dg"))
    assert r.status_code == 400 and "téléphone whatsapp" in r.json()["detail"].lower()


def test_pin_refuse_superviseur_client_et_inconnu(env):
    assert env.c.post("/api/staff-pin/u-sup", json={}, headers=_h("dg")).status_code == 400
    # Lot 19 : les clients ont désormais droit à un PIN (voir test_lot19_clients_whatsapp.py)
    assert env.c.post("/api/staff-pin/c1", json={}, headers=_h("dg")).status_code == 200
    assert env.c.post("/api/staff-pin/inconnu", json={}, headers=_h("dg")).status_code == 404


def test_droits_de_gestion_des_pin(env):
    # Un comptable ne gère pas les PIN
    assert env.c.post("/api/staff-pin/u-secr", json={}, headers=_h("compta")).status_code == 403
    assert env.c.get("/api/staff-pin", headers=_h("compta")).status_code == 403
    # Un DG ne touche pas au PIN d'un Administrateur ; un Administrateur oui
    assert env.c.post("/api/staff-pin/u-adm", json={}, headers=_h("dg")).status_code == 403
    assert env.c.post("/api/staff-pin/u-adm", json={}, headers=_h("adm")).status_code == 200


# ---------- 2) connexion par WhatsApp ----------
def test_connexion_whatsapp_complete(env):
    pin = _pin(env)["pin"]
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "70 11 22 33", "pin": pin})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["needs_otp"] is True and body["dev_otp"] is None and "WhatsApp" in body["message"]
    assert env.envois[-1][0] == "+22670112233"
    r2 = env.c.post("/api/auth/verify-otp", json={"session_token": body["session_token"], "code": _code_recu(env)})
    assert r2.status_code == 200, r2.text
    assert r2.json()["user"]["id"] == "u-compta" and r2.json()["access_token"]


def test_connexion_avec_le_numero_whatsapp_dedie(env):
    # Le numéro WhatsApp dédié prime sur le téléphone
    pin = _pin(env, cible="secr")["pin"]
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670000009", "pin": pin}).status_code == 401
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+226 76 55 44 33", "pin": pin}).status_code == 200


def test_pin_faux_puis_blocage_du_numero(env):
    pin = _pin(env)["pin"]
    faux = "0000" if pin != "0000" else "1111"
    for _ in range(cw.ESSAIS_PIN_MAX):
        r = env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": faux})
        assert r.status_code == 401
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": pin})
    assert r.status_code == 429                     # même le bon PIN est refusé pendant 15 minutes


def test_code_otp_annule_apres_cinq_erreurs(env):
    pin = _pin(env)["pin"]
    jeton = env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": pin}).json()["session_token"]
    bon = _code_recu(env)
    faux = "000000" if bon != "000000" else "111111"
    for _ in range(albarka_auth.OTP_ESSAIS_MAX):
        assert env.c.post("/api/auth/verify-otp", json={"session_token": jeton, "code": faux}).status_code == 400
    r = env.c.post("/api/auth/verify-otp", json={"session_token": jeton, "code": bon})
    assert r.status_code == 400                     # le code a été annulé


def test_compte_desactive_ou_pin_retire_ne_se_connecte_plus(env):
    pin = _pin(env)["pin"]
    asyncio.run(env.db.users.update_one({"id": "u-compta"}, {"$set": {"is_active": False}}))
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": pin}).status_code == 401
    asyncio.run(env.db.users.update_one({"id": "u-compta"}, {"$set": {"is_active": True}}))
    assert env.c.delete("/api/staff-pin/u-compta", headers=_h("dg")).status_code == 200
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": pin}).status_code == 401
    assert env.c.delete("/api/staff-pin/u-compta", headers=_h("dg")).status_code == 404


def test_superviseur_exclu_meme_avec_un_pin_en_base(env):
    # PIN posé directement en base (contournement) : le Superviseur reste exclu
    asyncio.run(env.db.pins_whatsapp.insert_one({"user_id": "u-sup", "pin_hash": albarka_auth.hash_password("1234")}))
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+22672000000", "pin": "1234"}).status_code == 401


def test_echec_envoi_whatsapp_code_annule(env):
    pin = _pin(env)["pin"]
    env.etat["ok"] = False
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": pin})
    assert r.status_code == 502 and "e-mail" in r.json()["detail"]
    otp = asyncio.run(env.db.otps.find_one({"user_id": "u-compta"}))
    assert otp["used"] is True                      # le code ne peut plus servir


def test_saisie_invalide_refusee_sans_appel(env):
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "12", "pin": "1234"}).status_code == 401
    assert env.c.post("/api/auth/login-whatsapp", json={"numero": "+22670112233", "pin": "12"}).status_code == 401
    assert env.envois == []


def test_numero_de_lot():
    import lot
    # Le lot 16 est en ligne ; les lots suivants changent le numéro (règle : un lot par déploiement)
    assert float(lot.LOT.split(".")[0]) >= 16
