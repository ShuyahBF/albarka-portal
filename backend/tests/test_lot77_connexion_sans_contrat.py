"""Lot 77 — client sans contrat actif : la raison du refus reste lisible à chaque essai (le code n'est pas consommé)."""
import asyncio

from tests.test_access_lot4 import env, _login, USERS  # noqa: F401  (fixture partagée)


def test_refus_sans_contrat_ne_consomme_pas_le_code(env):
    # Lot 89 : le blocage est un réglage du super-admin (faux par défaut) — ici il est activé
    asyncio.run(env.db.settings.update_one({"_id": "global"}, {"$set": {"interdire_clients_sans_contrat": True}}, upsert=True))
    # Client sans aucun contrat : refus 403 explicite ...
    r1 = _login(env, "c1")
    assert r1.status_code == 403 and "Aucun contrat actif" in r1.json()["detail"]
    otp = asyncio.run(env.db.otps.find_one({"user_id": USERS["c1"]["id"]}))
    assert otp["used"] is False
    # ... et le même code, ressaisi, donne encore la vraie raison (plus « Session invalide ou expirée »)
    r2 = env.c.post("/api/auth/verify-otp", json={"session_token": otp["session_token"], "code": "123456"})
    assert r2.status_code == 403 and "Aucun contrat actif" in r2.json()["detail"]
