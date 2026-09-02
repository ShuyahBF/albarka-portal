"""Point d'entrée FastAPI du pilote ALBARKA.

Volontairement distinct du `server.py` hérité de Sawali (25 000+ lignes,
des dizaines d'intégrations tierces hors sujet pour un cabinet fiscal et
comptable — Stripe, PawaPay, réseaux sociaux, Vidal, etc.). Cette app ne
monte que ce qui sert le pilote : authentification OTP + pièces client +
analyse IA. Les futurs modules (fiscalité, paie/RH, secrétariat, messagerie)
s'ajouteront ici au fur et à mesure du plan.

Lancer en local : uvicorn albarka_app:app --reload --port 8000
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, FastAPI
from starlette.middleware.cors import CORSMiddleware

from albarka_auth import router as auth_router
from albarka_documents import router as documents_router
from db import client as mongo_client

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("albarka.app")

app = FastAPI(title="Portail ALBARKA — API")
api_router = APIRouter(prefix="/api")

api_router.include_router(auth_router)
api_router.include_router(documents_router)


@api_router.get("/health")
async def health():
    return {"status": "ok", "app": "albarka-portal"}


app.include_router(api_router)

# CORS_ORIGINS : liste d'origines autorisées séparées par des virgules
# (ex. "https://albarka-bf.com,https://www.albarka-bf.com"). Par défaut,
# seul le développement local est autorisé — à définir explicitement en
# production (une origine "*" est de toute façon incompatible avec
# allow_credentials=True côté navigateur).
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", _default_origins).split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
