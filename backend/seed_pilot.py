"""Amorce les comptes de démonstration du pilote ALBARKA :
1 compte superviseur (cabinet) + 2 comptes clients test.

Idempotent : relancer ce script ne duplique pas les comptes (upsert par
email) mais réinitialise leur mot de passe à chaque exécution — pratique
pour une démo, à ne pas faire en production.

Usage :
    python3 seed_pilot.py

Nécessite un accès réseau réel à MongoDB Atlas (MONGO_URL dans .env) —
ne fonctionne pas depuis un environnement à sortie réseau restreinte.
"""
from __future__ import annotations

import asyncio
import secrets
import string
from datetime import datetime, timezone

from albarka_auth import hash_password
from db import db

DEMO_ACCOUNTS = [
    {
        "email": "superviseur@albarka-demo.bf",
        "full_name": "Superviseur Cabinet ALBARKA",
        "roles": ["superviseur"],
        "company": None,
    },
    {
        "email": "client1@albarka-demo.bf",
        "full_name": "Responsable Client Démo 1",
        "roles": ["client"],
        "company": "Client Démo 1 SARL",
    },
    {
        "email": "client2@albarka-demo.bf",
        "full_name": "Responsable Client Démo 2",
        "roles": ["client"],
        "company": "Client Démo 2 SARL",
    },
]


def _gen_password(length: int = 14) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


async def main() -> None:
    print("Amorçage des comptes de démonstration ALBARKA...\n")
    credentials = []
    for account in DEMO_ACCOUNTS:
        password = _gen_password()
        user_doc = {
            "id": secrets.token_urlsafe(12),
            "email": account["email"],
            "password_hash": hash_password(password),
            "full_name": account["full_name"],
            "roles": account["roles"],
            "company": account["company"],
            "is_active": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "last_login": None,
        }
        existing = await db.users.find_one({"email": account["email"]})
        if existing:
            user_doc["id"] = existing["id"]
            await db.users.update_one({"email": account["email"]}, {"$set": user_doc})
            action = "mis à jour"
        else:
            await db.users.insert_one(user_doc)
            action = "créé"
        credentials.append((account["email"], password, account["roles"], action))

    print(f"{'Email':<32} {'Mot de passe':<16} {'Rôles':<20} Action")
    print("-" * 90)
    for email, password, roles, action in credentials:
        print(f"{email:<32} {password:<16} {','.join(roles):<20} {action}")
    print("\nConservez ce mot de passe : il n'est affiché qu'une fois (seul son hash est stocké en base).")


if __name__ == "__main__":
    asyncio.run(main())
