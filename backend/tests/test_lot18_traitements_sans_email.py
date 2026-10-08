"""Lot 18 — Collaborateur créé SANS e-mail (WhatsApp seulement) + numéro de lot.

Couvre :
  - création avec le seul numéro WhatsApp : adresse technique « …@sans-email.invalid », jamais affichée ;
  - e-mail OU numéro obligatoire ; mot de passe exigé seulement avec un e-mail ; numéro déjà utilisé : 409 ;
  - aucun e-mail n'est envoyé à une adresse technique ;
  - parcours complet : création sans e-mail → code PIN → connexion WhatsApp → code reçu → jeton.
Réutilise l'environnement simulé du lot 16 (MongoDB et WhatsApp simulés).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_connexion_whatsapp_lot16 import _code_recu, _h, env  # noqa: E402,F401  (fixture réutilisée)

import albarka_clients as ac  # noqa: E402
import albarka_notifications as an  # noqa: E402


def test_adresse_technique():
    assert ac.email_technique("+22670998877") == "wa-22670998877@sans-email.invalid"
    assert ac.est_email_technique("WA-1@SANS-EMAIL.INVALID") and not ac.est_email_technique("a@b.bf")


def test_creation_sans_email(env):
    r = env.c.post("/api/clients/staff", json={"full_name": "Aïcha", "phone": "70 99 88 77", "roles": ["secretariat"]},
                   headers=_h("dg"))
    assert r.status_code == 200, r.text
    assert r.json()["email"] == "" and r.json()["sans_email"] is True
    fiche = asyncio.run(env.db.users.find_one({"full_name": "Aïcha"}))
    assert fiche["email"] == "wa-22670998877@sans-email.invalid"
    # Liste du personnel : adresse technique jamais affichée
    liste = env.c.get("/api/clients/staff", headers=_h("dg")).json()
    aicha = next(x for x in liste if x["full_name"] == "Aïcha")
    assert aicha["email"] == "" and aicha["sans_email"] is True
    # Même numéro une 2e fois : refus clair
    r2 = env.c.post("/api/clients/staff", json={"full_name": "Autre", "phone": "+226 70998877", "roles": ["rh"]},
                    headers=_h("dg"))
    assert r2.status_code == 409


def test_email_ou_numero_obligatoire_et_mot_de_passe_avec_email(env):
    assert env.c.post("/api/clients/staff", json={"full_name": "X", "roles": ["rh"]}, headers=_h("dg")).status_code == 422
    r = env.c.post("/api/clients/staff", json={"full_name": "Y", "email": "y@albarka.bf", "roles": ["rh"]}, headers=_h("dg"))
    assert r.status_code == 422 and "mot de passe" in r.json()["detail"].lower()
    r = env.c.post("/api/clients/staff", json={"full_name": "Y", "email": "y@albarka.bf", "password": "Secret-123",
                                               "roles": ["rh"]}, headers=_h("dg"))
    assert r.status_code == 200 and r.json()["email"] == "y@albarka.bf"


def test_aucun_email_vers_une_adresse_technique(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.exemple.bf")
    envoyes = []

    async def config():
        return {"from_email": "x@albarka.bf", "from_name": "ALBARKA", "reply_to": None}
    monkeypatch.setattr(an, "_get_email_config", config)
    monkeypatch.setattr(an, "_smtp_envoi_synchrone", lambda **k: envoyes.append(k["to_list"]) or "id")
    assert asyncio.run(an.send_email(to="wa-226@sans-email.invalid", subject="Test", html="<p>x</p>")) is None
    asyncio.run(an.send_email(to=["wa-226@sans-email.invalid", "vrai@albarka.bf"], subject="Test", html="<p>x</p>"))
    assert envoyes == [["vrai@albarka.bf"]]


def test_connexion_whatsapp_d_un_collaborateur_sans_email(env):
    cree = env.c.post("/api/clients/staff", json={"full_name": "Aïcha", "phone": "70 99 88 77", "roles": ["secretariat"]},
                      headers=_h("dg")).json()
    pin = env.c.post(f"/api/staff-pin/{cree['id']}", json={}, headers=_h("dg")).json()["pin"]
    r = env.c.post("/api/auth/login-whatsapp", json={"numero": "70998877", "pin": pin})
    assert r.status_code == 200, r.text
    r2 = env.c.post("/api/auth/verify-otp", json={"session_token": r.json()["session_token"], "code": _code_recu(env)})
    assert r2.status_code == 200, r2.text
    assert r2.json()["user"]["id"] == cree["id"]


def test_numero_de_lot():
    import lot
    assert float(lot.LOT.split(".")[0]) >= 18   # lots suivants : un numéro par déploiement
