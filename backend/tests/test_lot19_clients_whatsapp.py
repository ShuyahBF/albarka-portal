"""Lot 19 — Connexion des CLIENTS par WhatsApp (numéro + PIN, puis code reçu) et client sans e-mail.

Couvre :
  - création d'un client avec le seul numéro WhatsApp (adresse technique masquée) ;
  - PIN d'un client généré par le secrétariat (gestion des clients), refusé à un comptable ;
    le secrétariat ne touche pas au PIN d'un collaborateur ;
  - parcours complet du client : numéro + PIN → code WhatsApp → jeton ;
  - numéro de lot.
Réutilise l'environnement simulé du lot 16 (MongoDB et WhatsApp simulés).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_connexion_whatsapp_lot16 import _code_recu, _h, env  # noqa: E402,F401  (fixture réutilisée)


def _client_sans_email(env):
    r = env.c.post("/api/clients", json={"full_name": "Boutique Wend", "company": "Wend SARL",
                                         "whatsapp_number": "76 12 34 56"}, headers=_h("secr"))
    assert r.status_code == 200, r.text
    return r.json()


def test_creation_client_sans_email(env):
    cree = _client_sans_email(env)
    assert cree["email"] == "" and cree["sans_email"] is True
    liste = env.c.get("/api/clients", headers=_h("secr")).json()
    assert next(x for x in liste if x["id"] == cree["id"])["email"] == ""
    assert env.c.get(f"/api/clients/{cree['id']}", headers=_h("secr")).json()["email"] == ""
    # Ni e-mail ni numéro : refus ; e-mail sans mot de passe : refus
    assert env.c.post("/api/clients", json={"full_name": "X"}, headers=_h("secr")).status_code == 422
    assert env.c.post("/api/clients", json={"full_name": "X", "email": "x@exemple.bf"}, headers=_h("secr")).status_code == 422


def test_droits_sur_le_pin_d_un_client(env):
    cree = _client_sans_email(env)
    # Le secrétariat gère les clients : il génère le PIN du client
    assert env.c.post(f"/api/staff-pin/{cree['id']}", json={}, headers=_h("secr")).status_code == 200
    # Un comptable non ; et le secrétariat ne touche pas au PIN d'un collaborateur
    assert env.c.post(f"/api/staff-pin/{cree['id']}", json={}, headers=_h("compta")).status_code == 403
    assert env.c.post("/api/staff-pin/u-compta", json={}, headers=_h("secr")).status_code == 403


def test_connexion_whatsapp_d_un_client(env, monkeypatch):
    cree = _client_sans_email(env)
    # Règle existante : un client ne se connecte qu'avec un contrat actif (simulé ici)
    import albarka_contracts

    async def contrat_actif(_tenant_id):
        return True
    monkeypatch.setattr(albarka_contracts, "has_active_contract", contrat_actif)
    pin = env.c.post(f"/api/staff-pin/{cree['id']}", json={}, headers=_h("secr")).json()["pin"]
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "+226 76 12 34 56", "pin": pin})
    assert r.status_code == 200, r.text
    assert env.envois[-1][0] == "+22676123456"
    r2 = env.c.post("/api/auth/verify-otp", json={"session_token": r.json()["session_token"], "code": _code_recu(env)})
    assert r2.status_code == 200, r2.text
    assert r2.json()["user"]["id"] == cree["id"] and "client" in r2.json()["user"]["roles"]


def test_client_sans_contrat_actif_refuse(env):
    # Même règle que la connexion par e-mail : sans contrat actif, pas d'accès
    cree = _client_sans_email(env)
    pin = env.c.post(f"/api/staff-pin/{cree['id']}", json={}, headers=_h("secr")).json()["pin"]
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "76123456", "pin": pin})
    r2 = env.c.post("/api/auth/verify-otp", json={"session_token": r.json()["session_token"], "code": _code_recu(env)})
    assert r2.status_code == 403 and "contrat" in r2.json()["detail"].lower()


def test_numero_de_lot():
    import lot
    assert float(lot.LOT.split(".")[0]) >= 19   # lots suivants : un numéro par déploiement
