"""Portail ALBARKA — API FastAPI (cabinet fiscal & comptable).

Ce fichier tient lieu d'entrée `server:app` requis par supervisor.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

load_dotenv(Path(__file__).parent / ".env")

from albarka_auth import router as auth_router  # noqa: E402
from albarka_clients import router as clients_router  # noqa: E402
from albarka_dashboard import router as dashboard_router  # noqa: E402
from albarka_documents import router as documents_router  # noqa: E402
from albarka_echeances import router as echeances_router  # noqa: E402
from albarka_missions import router as missions_router  # noqa: E402
from albarka_reports_router import router as reports_router  # noqa: E402
from albarka_storage import storage_mode  # noqa: E402
from db import client as mongo_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("albarka.app")

app = FastAPI(title="Portail ALBARKA — API", version="1.0.0")

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(clients_router)
api_router.include_router(dashboard_router)
api_router.include_router(documents_router)
api_router.include_router(echeances_router)
api_router.include_router(missions_router)
api_router.include_router(reports_router)


@api_router.get("/")
async def root():
    return {"message": "Portail ALBARKA — API"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "app": "albarka-portal", "storage": storage_mode()}


app.include_router(api_router)


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
