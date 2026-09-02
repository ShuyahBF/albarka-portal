"""Amorçage des comptes de démonstration ALBARKA (idempotent)."""
from __future__ import annotations

import asyncio
import secrets
from datetime import datetime, timezone

from albarka_auth import hash_password
from db import db

DEMO_ACCOUNTS = [
    {
        "email": "superviseur@albarka-demo.bf",
        "password": "Superviseur2026!",
        "full_name": "Superviseur Cabinet ALBARKA",
        "roles": ["superviseur"],
        "company": None,
        "phone": "+22670000001",
    },
    {
        "email": "comptable@albarka-demo.bf",
        "password": "Comptable2026!",
        "full_name": "Kadidiatou Ouédraogo",
        "roles": ["comptable", "fiscaliste"],
        "company": None,
        "phone": "+22670000002",
    },
    {
        "email": "client1@albarka-demo.bf",
        "password": "Client2026!",
        "full_name": "Boukary Sawadogo",
        "roles": ["client"],
        "company": "Sawadogo Import-Export SARL",
        "phone": "+22671111111",
    },
    {
        "email": "client2@albarka-demo.bf",
        "password": "Client2026!",
        "full_name": "Aminata Traoré",
        "roles": ["client"],
        "company": "Traoré BTP SARL",
        "phone": "+22672222222",
    },
]


async def main() -> None:
    print("Amorçage des comptes de démonstration ALBARKA...\n")
    for account in DEMO_ACCOUNTS:
        user_doc = {
            "email": account["email"].lower(),
            "password_hash": hash_password(account["password"]),
            "full_name": account["full_name"],
            "roles": account["roles"],
            "company": account["company"],
            "phone": account.get("phone"),
            "is_active": True,
            "last_login": None,
        }
        existing = await db.users.find_one({"email": user_doc["email"]})
        if existing:
            await db.users.update_one({"email": user_doc["email"]}, {"$set": user_doc})
            action = "mis à jour"
            user_id = existing["id"]
        else:
            user_doc["id"] = secrets.token_urlsafe(12)
            user_doc["created_at"] = datetime.now(timezone.utc).isoformat()
            await db.users.insert_one(user_doc)
            action = "créé"
            user_id = user_doc["id"]
        print(f"  {action:>10}  {account['email']:<35}  {account['password']:<20}  {'/'.join(account['roles'])}")

    # Seed a couple of missions and échéances per client
    clients = await db.users.find({"roles": "client"}).to_list(100)
    supervisor = await db.users.find_one({"roles": "superviseur"})
    now = datetime.now(timezone.utc).isoformat()
    for c in clients:
        # Missions
        existing_missions = await db.missions.count_documents({"tenant_id": c["id"]})
        if existing_missions == 0:
            await db.missions.insert_many([
                {
                    "id": secrets.token_urlsafe(12),
                    "tenant_id": c["id"],
                    "title": "Tenue comptable mensuelle — janvier",
                    "type": "tenue_comptable",
                    "description": "Enregistrement des pièces et rapprochements bancaires.",
                    "assigned_to": [supervisor["id"]] if supervisor else [],
                    "due_date": "2026-02-15",
                    "status": "en_cours",
                    "created_by": supervisor["id"] if supervisor else None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": secrets.token_urlsafe(12),
                    "tenant_id": c["id"],
                    "title": "Déclaration TVA T4 2025",
                    "type": "declaration_fiscale",
                    "description": "Préparation et dépôt de la déclaration TVA du dernier trimestre.",
                    "assigned_to": [],
                    "due_date": "2026-02-20",
                    "status": "en_attente",
                    "created_by": supervisor["id"] if supervisor else None,
                    "created_at": now,
                    "updated_at": now,
                },
            ])
        # Échéances
        existing_echeances = await db.echeances.count_documents({"tenant_id": c["id"]})
        if existing_echeances == 0:
            await db.echeances.insert_many([
                {
                    "id": secrets.token_urlsafe(12),
                    "tenant_id": c["id"],
                    "title": "TVA T4 2025",
                    "type": "tva",
                    "due_date": "2026-02-20",
                    "amount": None,
                    "period": "2025-Q4",
                    "notes": "Dépôt au service des impôts.",
                    "status": "a_venir",
                    "created_by": supervisor["id"] if supervisor else None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": secrets.token_urlsafe(12),
                    "tenant_id": c["id"],
                    "title": "CNSS — cotisations janvier",
                    "type": "cnss",
                    "due_date": "2026-02-15",
                    "amount": None,
                    "period": "2026-01",
                    "notes": "Cotisations salariales et patronales.",
                    "status": "a_venir",
                    "created_by": supervisor["id"] if supervisor else None,
                    "created_at": now,
                    "updated_at": now,
                },
                {
                    "id": secrets.token_urlsafe(12),
                    "tenant_id": c["id"],
                    "title": "IUTS — retenues salariales décembre",
                    "type": "iuts",
                    "due_date": "2026-01-15",
                    "amount": None,
                    "period": "2025-12",
                    "notes": "Impôt unique sur traitements et salaires.",
                    "status": "en_retard",
                    "created_by": supervisor["id"] if supervisor else None,
                    "created_at": now,
                    "updated_at": now,
                },
            ])

    print("\nComptes de démonstration prêts.\n")


if __name__ == "__main__":
    asyncio.run(main())
