"""Portail ALBARKA — API FastAPI (cabinet fiscal & comptable).

Ce fichier tient lieu d'entrée `server:app` requis par supervisor.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, Depends, FastAPI
from starlette.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent / ".env")

from albarka_auth import router as auth_router, require_roles  # noqa: E402
from albarka_admin_settings import router as admin_settings_router  # noqa: E402
from albarka_branding import router as branding_router  # noqa: E402
from albarka_chat_extra import router as chat_extra_router  # noqa: E402
from albarka_clients import router as clients_router  # noqa: E402
from albarka_contact_groups import router as contact_groups_router  # noqa: E402
from albarka_contacts import router as contacts_router  # noqa: E402
from albarka_contacts_import import router as contacts_import_router  # noqa: E402
from albarka_contracts import router as contracts_router  # noqa: E402
from albarka_dashboard import router as dashboard_router  # noqa: E402
from albarka_documents import router as documents_router  # noqa: E402
from albarka_echeances import router as echeances_router  # noqa: E402
from albarka_missions import router as missions_router  # noqa: E402
from albarka_ohada import router as ohada_router  # noqa: E402
from albarka_phase_c import (  # noqa: E402
    chat_router,
    billing_router,
    hr_router,
    logs_router,
    archives_router,
    messaging_router,
)
from albarka_public import router as public_router  # noqa: E402
from albarka_report_templates import router as report_templates_router  # noqa: E402
from albarka_reports_mgmt import router as reports_mgmt_router  # noqa: E402
from albarka_wa_inbox import router as wa_inbox_router  # noqa: E402
from albarka_migrate import router as migrate_router  # noqa: E402
from albarka_reports_router import router as reports_router  # noqa: E402
from albarka_signing import router as signing_router  # noqa: E402
from albarka_storage import storage_mode  # noqa: E402
from db import client as mongo_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("albarka.app")

app = FastAPI(title="Portail ALBARKA — API", version="1.0.0")

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(admin_settings_router)
api_router.include_router(branding_router)
api_router.include_router(signing_router)
api_router.include_router(clients_router)
api_router.include_router(contacts_router)
api_router.include_router(contacts_import_router)
api_router.include_router(contact_groups_router)
api_router.include_router(dashboard_router)
api_router.include_router(documents_router)
api_router.include_router(echeances_router)
api_router.include_router(missions_router)
api_router.include_router(reports_router)
api_router.include_router(reports_mgmt_router)
api_router.include_router(migrate_router)
api_router.include_router(report_templates_router)
# Phase B — Contrats clients
api_router.include_router(contracts_router)
# Phase C — Modules internes
api_router.include_router(chat_router)
api_router.include_router(billing_router)
api_router.include_router(hr_router)
api_router.include_router(logs_router)
api_router.include_router(archives_router)
api_router.include_router(messaging_router)
# Phase D — Comptabilité OHADA
api_router.include_router(ohada_router)
# Chat interne — extensions Partie 1 (transcribe/search/photo)
api_router.include_router(chat_extra_router)
# WhatsApp inbox — Partie 2.D (webhook + conversations)
api_router.include_router(wa_inbox_router)
# Endpoints publics (bouton wa.me — Partie 0)
api_router.include_router(public_router)


@api_router.get("/")
async def root():
    return {"message": "Portail ALBARKA — API"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "app": "albarka-portal", "storage": storage_mode()}


@api_router.get("/_diag/db")
async def _diag_db(user: dict = Depends(require_roles(["superviseur", "direction"]))):
    """Diagnostic base MongoDB (staff seulement, temporaire audit réconciliation)."""
    import re as _re
    from db import mongo_url as _mu, db as _db
    host_match = _re.search(r"@([^/?]+)", _mu)
    host = host_match.group(1) if host_match else "(unknown)"
    scheme = _mu.split("://", 1)[0] if "://" in _mu else "?"
    collections = {}
    for name in await _db.list_collection_names():
        try:
            collections[name] = await _db[name].estimated_document_count()
        except Exception:
            collections[name] = -1
    return {
        "mongo_scheme": scheme,
        "mongo_host": host,
        "db_name": _db.name,
        "collections": collections,
    }


app.include_router(api_router)


@app.on_event("startup")
async def _migrate_on_startup():
    """Migrations idempotentes exécutées au démarrage du backend."""
    try:
        from albarka_contracts import migrate_contract_statuses_and_numbers
        stats = await migrate_contract_statuses_and_numbers()
        if stats.get("status_migrated") or stats.get("number_generated"):
            logger.info("Migration contrats : %s", stats)
    except Exception:  # noqa: BLE001
        logger.exception("Migration contrats — échec (ignoré)")


@app.on_event("startup")
async def _ensure_indexes():
    """Create unique indexes for race-safe dedup / idempotency."""
    from db import db as _db
    try:
        await _db.cron_runs.create_index("run_id", unique=True)
        await _db.notification_log.create_index("key", unique=True)
        await _db.echeances.create_index("due_date")
        await _db.users.create_index("email", unique=True)
        await _db.otps.create_index("session_token")
        await _db.documents.create_index([("tenant_id", 1), ("created_at", -1)])
        # Reports & series (iteration 3)
        await _db.client_reports.create_index([("tenant_id", 1), ("generated_at", -1)])
        await _db.client_reports.create_index("number", unique=True)
        await _db.report_series.create_index("key", unique=True)
        # Contacts (iteration 4)
        await _db.contacts.create_index([("scope", 1), ("tenant_id", 1), ("is_primary", -1)])
    except Exception:
        logger.exception("Échec création index Mongo (non bloquant)")


cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
