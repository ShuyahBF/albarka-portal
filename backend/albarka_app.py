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

app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=["*"],  # à restreindre au domaine du portail avant mise en production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
