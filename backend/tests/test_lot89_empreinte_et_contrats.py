"""Lot 89 — (1) accès des clients sans contrat = RÉGLAGE du super-admin (faux par défaut) ;
(2) connexion par empreinte digitale (WebAuthn) : activée par le super-admin, enrôlements gérés par le DG seul.

Un « faux authentificateur » logiciel (vraie clé ES256, vraies signatures) joue le rôle du téléphone / de Windows Hello :
les vérifications cryptographiques du serveur sont donc réellement exécutées. MongoDB simulé (mongomock-motor).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
pytest.importorskip("webauthn")
mongomock_motor = pytest.importorskip("mongomock_motor")

import cbor2  # noqa: E402
from cryptography.hazmat.primitives import hashes  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402

import db as db_module  # noqa: E402
import albarka_admin_settings  # noqa: E402
import albarka_auth  # noqa: E402
import albarka_passkeys  # noqa: E402

ORIGINE = "https://albarka.exemple.bf"
RP = "albarka.exemple.bf"
USERS = {
    "sup": {"id": "u-sup", "email": "sup@albarka.bf", "full_name": "Super Admin", "roles": ["superviseur"]},
    "dg": {"id": "u-dg", "email": "dg@albarka.bf", "full_name": "DG", "roles": ["dg", "direction"]},
    "dir": {"id": "u-dir", "email": "dir@albarka.bf", "full_name": "Direction", "roles": ["direction"]},
    "awa": {"id": "u-awa", "email": "awa@albarka.bf", "full_name": "BADINI Awa", "roles": ["comptable"]},
    "c1": {"id": "c1", "email": "client@gmail.com", "full_name": "SARL Kaboré", "roles": ["client"]},
}


def b64(o: bytes) -> str:
    return base64.urlsafe_b64encode(o).rstrip(b"=").decode()


class FauxAuthentificateur:
    """Authentificateur logiciel : fabrique de vraies réponses WebAuthn (enregistrement « none », signature ES256)."""

    def __init__(self):
        self.cle = ec.generate_private_key(ec.SECP256R1())
        self.identifiant = os.urandom(32)
        self.compteur = 0

    def _cose(self) -> bytes:
        n = self.cle.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: n.x.to_bytes(32, "big"), -3: n.y.to_bytes(32, "big")})

    def enregistrer(self, options: dict) -> dict:
        donnees = json.dumps({"type": "webauthn.create", "challenge": options["challenge"], "origin": ORIGINE, "crossOrigin": False}).encode()
        auth_data = (hashlib.sha256(RP.encode()).digest() + bytes([0x01 | 0x04 | 0x40]) + struct.pack(">I", 0) + b"\x00" * 16
                     + struct.pack(">H", len(self.identifiant)) + self.identifiant + self._cose())
        att = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        return {"id": b64(self.identifiant), "rawId": b64(self.identifiant), "type": "public-key", "clientExtensionResults": {},
                "response": {"clientDataJSON": b64(donnees), "attestationObject": b64(att), "transports": ["internal"]}}

    def signer(self, options: dict, handle: bytes | None = None) -> dict:
        self.compteur += 1
        donnees = json.dumps({"type": "webauthn.get", "challenge": options["challenge"], "origin": ORIGINE, "crossOrigin": False}).encode()
        auth_data = hashlib.sha256(RP.encode()).digest() + bytes([0x01 | 0x04]) + struct.pack(">I", self.compteur)
        sig = self.cle.sign(auth_data + hashlib.sha256(donnees).digest(), ec.ECDSA(hashes.SHA256()))
        rep = {"clientDataJSON": b64(donnees), "authenticatorData": b64(auth_data), "signature": b64(sig)}
        if handle is not None:
            rep["userHandle"] = b64(handle)
        return {"id": b64(self.identifiant), "rawId": b64(self.identifiant), "type": "public-key", "clientExtensionResults": {}, "response": rep}


class Env:
    pass


@pytest.fixture()
def env(monkeypatch):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot89"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    asyncio.run(mock_db.users.insert_many([{**u, "is_active": True} for u in USERS.values()]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_passkeys.router, albarka_admin_settings.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[albarka_auth.get_current_user] = fake_user
    app.dependency_overrides[albarka_passkeys.get_current_user] = fake_user
    e = Env()
    e.db, e.c = mock_db, TestClient(app)
    e.regler = lambda **kw: asyncio.run(mock_db.settings.update_one({"_id": "global"}, {"$set": kw}, upsert=True))
    return e


H = {"Origin": ORIGINE}


def _enroler(env, qui="awa", appareil=None):
    """Parcours complet : le DG génère le code, la personne enregistre son appareil. Renvoie (appareil, réponse finale)."""
    appareil = appareil or FauxAuthentificateur()
    code = env.c.post("/api/admin/passkeys/invitations", json={"user_id": USERS[qui]["id"]}, headers={"X-User": "dg"}).json()["code"]
    o = env.c.post("/api/auth/passkeys/enroll/options", json={"code": code}, headers=H)
    assert o.status_code == 200, o.text
    r = env.c.post("/api/auth/passkeys/enroll/verify", headers=H, json={
        "code": code, "challenge_id": o.json()["challenge_id"], "credential": appareil.enregistrer(o.json()["options"]), "nom": "Mon téléphone"})
    return appareil, r


# ------------------------------------------------------------ (1) clients sans contrat
def test_reglage_par_defaut_faux_et_modifiable_par_le_super_admin(env):
    r = env.c.get("/api/admin/settings", headers={"X-User": "sup"})
    assert r.status_code == 200 and r.json()["interdire_clients_sans_contrat"] is False
    assert r.json()["empreinte_activee"] is False
    assert env.c.put("/api/admin/settings", json={"interdire_clients_sans_contrat": True}, headers={"X-User": "dg"}).status_code == 403
    assert env.c.put("/api/admin/settings", json={"interdire_clients_sans_contrat": True}, headers={"X-User": "sup"}).status_code == 200
    assert env.c.get("/api/admin/settings", headers={"X-User": "sup"}).json()["interdire_clients_sans_contrat"] is True


def test_blocage_clients_sans_contrat_suit_le_reglage(env):
    assert asyncio.run(albarka_auth.clients_sans_contrat_interdits()) is False       # défaut : accès autorisé
    env.regler(interdire_clients_sans_contrat=True)
    assert asyncio.run(albarka_auth.clients_sans_contrat_interdits()) is True


# ------------------------------------------------------------ (2) empreinte digitale
def test_config_publique_et_desactivee_par_defaut(env):
    assert env.c.get("/api/auth/passkeys/config").json() == {"enabled": False}
    assert env.c.post("/api/auth/passkeys/login/options", headers=H).status_code == 403
    # Tant que le super-admin n'a pas activé, le DG ne peut pas inviter
    assert env.c.post("/api/admin/passkeys/invitations", json={"user_id": "u-awa"}, headers={"X-User": "dg"}).status_code == 403


def test_gestion_reservee_au_dg(env):
    env.regler(empreinte_activee=True)
    for qui in ("sup", "dir", "awa"):                         # ni le super-admin, ni la Direction, ni un comptable
        assert env.c.get("/api/admin/passkeys", headers={"X-User": qui}).status_code == 403
        assert env.c.post("/api/admin/passkeys/invitations", json={"user_id": "u-awa"}, headers={"X-User": qui}).status_code == 403
    assert env.c.get("/api/admin/passkeys", headers={"X-User": "dg"}).status_code == 200


def test_enrolement_puis_connexion_par_empreinte(env):
    env.regler(empreinte_activee=True)
    appareil, r = _enroler(env)
    assert r.status_code == 200, r.text
    # La fiche porte la clé publique (jamais l'empreinte) et le DG voit l'appareil, sans clé
    vue = env.c.get("/api/admin/passkeys", headers={"X-User": "dg"}).json()
    awa = next(c for c in vue["comptes"] if c["user_id"] == "u-awa")
    assert awa["nb"] == 1 and "public_key" not in json.dumps(vue)
    # Connexion : défi, signature, jeton
    o = env.c.post("/api/auth/passkeys/login/options", headers=H).json()
    ok = env.c.post("/api/auth/passkeys/login/verify", headers=H, json={
        "challenge_id": o["challenge_id"], "credential": appareil.signer(o["options"], handle=b"u-awa")})
    assert ok.status_code == 200, ok.text
    assert ok.json()["user"]["id"] == "u-awa" and ok.json()["access_token"]
    # Un défi ne sert qu'une fois
    rejoue = env.c.post("/api/auth/passkeys/login/verify", headers=H, json={
        "challenge_id": o["challenge_id"], "credential": appareil.signer(o["options"], handle=b"u-awa")})
    assert rejoue.status_code == 400


def test_code_d_enrolement_usage_unique_et_inconnu(env):
    env.regler(empreinte_activee=True)
    _, r = _enroler(env)
    assert r.status_code == 200
    code = env.c.post("/api/admin/passkeys/invitations", json={"user_id": "u-awa"}, headers={"X-User": "dg"}).json()["code"]
    assert env.c.post("/api/auth/passkeys/enroll/options", json={"code": "ZZZZ-ZZZZ"}, headers=H).status_code == 400
    a = FauxAuthentificateur()
    o = env.c.post("/api/auth/passkeys/enroll/options", json={"code": code}, headers=H).json()
    first = env.c.post("/api/auth/passkeys/enroll/verify", headers=H, json={
        "code": code, "challenge_id": o["challenge_id"], "credential": a.enregistrer(o["options"]), "nom": "x"})
    assert first.status_code == 200
    again = env.c.post("/api/auth/passkeys/enroll/options", json={"code": code}, headers=H)
    assert again.status_code == 400                           # code consommé


def test_signature_d_un_autre_appareil_refusee(env):
    env.regler(empreinte_activee=True)
    _enroler(env)
    intrus = FauxAuthentificateur()
    o = env.c.post("/api/auth/passkeys/login/options", headers=H).json()
    r = env.c.post("/api/auth/passkeys/login/verify", headers=H, json={"challenge_id": o["challenge_id"], "credential": intrus.signer(o["options"])})
    assert r.status_code == 401


def test_dg_retire_les_empreintes_et_la_connexion_cesse(env):
    env.regler(empreinte_activee=True)
    appareil, _ = _enroler(env)
    assert env.c.delete("/api/admin/passkeys/user/u-awa", headers={"X-User": "sup"}).status_code == 403   # pas le super-admin
    assert env.c.delete("/api/admin/passkeys/user/u-awa", headers={"X-User": "dg"}).status_code == 200
    o = env.c.post("/api/auth/passkeys/login/options", headers=H).json()
    r = env.c.post("/api/auth/passkeys/login/verify", headers=H, json={"challenge_id": o["challenge_id"], "credential": appareil.signer(o["options"])})
    assert r.status_code == 401


def test_client_sans_contrat_via_empreinte_suit_le_reglage(env):
    env.regler(empreinte_activee=True)
    appareil, r = _enroler(env, qui="c1")
    assert r.status_code == 200, r.text
    def connexion():
        o = env.c.post("/api/auth/passkeys/login/options", headers=H).json()
        return env.c.post("/api/auth/passkeys/login/verify", headers=H, json={"challenge_id": o["challenge_id"], "credential": appareil.signer(o["options"])})
    assert connexion().status_code == 200                      # réglage faux (défaut) : accès autorisé sans contrat
    env.regler(interdire_clients_sans_contrat=True)
    r2 = connexion()
    assert r2.status_code == 403 and "Aucun contrat actif" in r2.json()["detail"]


def test_domaine_et_https():
    assert albarka_passkeys.origine_et_domaine("https://albarka.exemple.bf", None) == ("https://albarka.exemple.bf", "albarka.exemple.bf")
    with pytest.raises(HTTPException):
        albarka_passkeys.origine_et_domaine("http://albarka.exemple.bf", None)
