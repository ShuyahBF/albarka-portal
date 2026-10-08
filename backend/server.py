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
from albarka_badges import router as badges_router  # noqa: E402
from albarka_billing_docs import router as billing_docs_router  # noqa: E402
from albarka_numero_manuel import router as numero_manuel_router  # noqa: E402  (lot 17 : numéro manuel des factures)
from albarka_contrat_plateforme import router as contrat_plateforme_router  # noqa: E402  (lot 21 : contrat SAWALI)
from albarka_settings_tests import router as settings_tests_router  # noqa: E402
from albarka_myaccount import router as myaccount_router  # noqa: E402
from albarka_ohada import router as ohada_router  # noqa: E402
from albarka_payments import router as payments_router, webhook_router as payments_webhook_router  # noqa: E402
# Lot 14 : encaissement PI-SPI (paramètres, transactions, notification désactivée)
from albarka_pispi import router as pispi_router, notification_router as pispi_notification_router  # noqa: E402
from albarka_phase_c import (  # noqa: E402
    chat_router,
    billing_router,
    hr_router,
    logs_router,
    archives_router,
    messaging_router,
)
from albarka_public import router as public_router  # noqa: E402
# Accès du personnel : liste blanche (appareils + IP) et jetons temporaires
from albarka_access import ensure_access_indexes, router as access_router  # noqa: E402
# Notifications push (Web Push, navigateur / téléphone)
from albarka_push import ensure_push_indexes, router as push_router  # noqa: E402
# Présence en temps réel (keep-alive : connectés / déconnectés)
from albarka_presence import ensure_presence_indexes, router as presence_router  # noqa: E402
# Espace client : documents déposés / mis à disposition par le cabinet
from albarka_client_space import (  # noqa: E402
    ensure_client_space_indexes,
    me_router as client_space_me_router,
    router as client_space_router,
)
# Formulaires (module commun forms_core branché par albarka_forms.py)
from albarka_forms import (  # noqa: E402
    ensure_forms_indexes,
    portal_router as forms_portal_router,
    public_router as forms_public_router,
    staff_router as forms_staff_router,
)
from albarka_report_templates import router as report_templates_router  # noqa: E402
from albarka_reports_mgmt import router as reports_mgmt_router  # noqa: E402
from albarka_wa_inbox import router as wa_inbox_router  # noqa: E402
from albarka_wa_extras import router as wa_extras_router  # noqa: E402
# Lot 14.1 : route temporaire de migration Emergent -> Atlas (albarka_migrate) retirée :
# la migration est terminée ; plus aucune route ne peut écrire dans une autre base.
from albarka_reports_router import router as reports_router  # noqa: E402
from albarka_signing import router as signing_router  # noqa: E402
from albarka_storage import storage_mode  # noqa: E402
from db import client as mongo_client  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("albarka.app")

app = FastAPI(title="Portail ALBARKA — API", version="1.0.0")


@app.middleware("http")
async def _remember_client_ip(request, call_next):
    """Retient l'IP réelle (derrière le proxy : X-Forwarded-For) et le
    navigateur de chaque requête, pour le Journal plateforme."""
    from albarka_request_ctx import set_request_info
    fwd = request.headers.get("x-forwarded-for") or ""
    ip = fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "")
    set_request_info(ip, request.headers.get("user-agent") or "")
    return await call_next(request)

@app.middleware("http")
async def _services_suspendus(request, call_next):
    """Lot 22 : services cochés dans SAWALI, suspendus quand le contrat est échu → réponse 423 avec un message clair.
    Retient aussi le chemin de la requête (les codes de connexion restent toujours envoyés)."""
    from albarka_suspension import message_suspension, noter_chemin, service_du_chemin, suspendus_actuels
    chemin = request.url.path
    noter_chemin(chemin)
    if chemin.startswith("/api/") and request.method != "OPTIONS":
        try:
            code = service_du_chemin(chemin, await suspendus_actuels())
        except Exception:  # noqa: BLE001 — en cas de doute, on ne bloque pas
            code = None
        if code:
            from fastapi.responses import JSONResponse
            return JSONResponse(status_code=423, content={"detail": message_suspension(code), "service_suspendu": code})
    return await call_next(request)


api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
# Lot 16 : connexion du personnel par WhatsApp (numéro + PIN, puis code OTP)
# et gestion des codes PIN dans « Personnels » (voir albarka_connexion_whatsapp.py)
from albarka_connexion_whatsapp import auth_router as connexion_wa_router, router as staff_pin_router  # noqa: E402
api_router.include_router(connexion_wa_router)
api_router.include_router(staff_pin_router)
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
api_router.include_router(myaccount_router)
api_router.include_router(payments_router)
api_router.include_router(payments_webhook_router)
api_router.include_router(pispi_router)
api_router.include_router(pispi_notification_router)
api_router.include_router(reports_router)
api_router.include_router(reports_mgmt_router)
api_router.include_router(report_templates_router)
# Phase B — Contrats clients
api_router.include_router(contracts_router)
# Phase C — Modules internes
api_router.include_router(chat_router)
api_router.include_router(billing_router)
api_router.include_router(billing_docs_router)
api_router.include_router(numero_manuel_router)   # lot 17
api_router.include_router(contrat_plateforme_router)   # lot 21 : bandeau du contrat pour le DG
api_router.include_router(settings_tests_router)
api_router.include_router(badges_router)
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
# WhatsApp extras — Partie 2.E (quick replies, labels, stats)
api_router.include_router(wa_extras_router)
# Endpoints publics (bouton wa.me — Partie 0)
api_router.include_router(public_router)
# Accès du personnel (liste blanche, jetons d'accès temporaires)
api_router.include_router(access_router)
# Notifications push : abonnement des appareils, clé publique, essai
api_router.include_router(push_router)
# Présence : battements des pages ouvertes + état lu par le cabinet
api_router.include_router(presence_router)
# Espace client : dépôts du cabinet (factures, rapports… faits ailleurs) + page client
api_router.include_router(client_space_router)
api_router.include_router(client_space_me_router)
# Formulaires : gestion (rôle formulaires), remplissage public par lien, espace client
api_router.include_router(forms_staff_router)
api_router.include_router(forms_public_router)
api_router.include_router(forms_portal_router)
# Lot 7 : papiers à en-tête + vérification QR, documents à partir de modèles, tableau de paie
from albarka_docgen import router as docgen_router, public_router as docgen_public_router  # noqa: E402
from albarka_letters import router as letters_router  # noqa: E402
from albarka_payroll import router as payroll_router  # noqa: E402
api_router.include_router(docgen_router)
api_router.include_router(docgen_public_router)
api_router.include_router(letters_router)
api_router.include_router(payroll_router)
# Lot 8 : paie (modèles de configuration, bulletins, livre de paie)
from albarka_paie import router as paie_router, ensure_paie_setup  # noqa: E402
api_router.include_router(paie_router)
# Lot 9 : espace « Outils Numériques » (téléchargements, historique réservé au super-admin)
from albarka_outils import router as outils_router, ensure_outils_indexes  # noqa: E402
api_router.include_router(outils_router)
# Lot 13 (migration Render) : sauvegardes quotidiennes chiffrées de la base dans R2
from albarka_sauvegarde import router as sauvegarde_router  # noqa: E402
api_router.include_router(sauvegarde_router)
# Lot 13.8 — Transmission WA Universelle Liluvine (état + test, super-admin)
from albarka_transmission_wa import router as transmission_wa_router  # noqa: E402
api_router.include_router(transmission_wa_router)
# Lot 13.9 — retours de SAWALI (route publique signée) et alias admin des retours
from albarka_transmission_wa import retour_router as liluvine_retour_router  # noqa: E402
from albarka_transmission_wa import admin_alias_router as transmission_wa_alias_router  # noqa: E402
api_router.include_router(liluvine_retour_router)
api_router.include_router(transmission_wa_alias_router)


@api_router.get("/")
async def root():
    return {"message": "Portail ALBARKA — API"}


@api_router.get("/health")
async def health():
    return {"status": "ok", "app": "albarka-portal", "storage": storage_mode()}


# Lot 13 (règle permanente) : version « 1.N » (compteur de déploiements) et lot déployé,
# affichés sur la page de connexion et dans le portail. Source unique : backend/lot.py.
@api_router.get("/version")
async def version():
    from db import db as _db
    from version_deploiement import infos_version
    return await infos_version(_db)


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
        # Formulaires (jetons de lien uniques, réponses par formulaire, anti-abus)
        await ensure_forms_indexes()
        # Lot 7 : index des documents et modèle « Avis de mission » fourni d'office
        from albarka_letters import ensure_letters_setup
        await ensure_letters_setup()
        # Espace client (documents du cabinet par client)
        await ensure_client_space_indexes()
        # Présence (keep-alive)
        await ensure_presence_indexes()
        # Accès du personnel
        await ensure_access_indexes()
        # Notifications push
        await ensure_push_indexes()
        # Lot 8 : paie (index + modèle « Burkina Faso — standard »)
        await ensure_paie_setup()
        # Lot 9 : outils numériques (ordre, historique des téléchargements)
        await ensure_outils_indexes()
    except Exception:
        logger.exception("Échec création index Mongo (non bloquant)")


cors_origins = [o.strip() for o in os.environ.get("CORS_ORIGINS", "*").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_credentials=True,
    allow_origins=cors_origins if cors_origins != ["*"] else ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    # Lot 11 : avertissements joints aux PDF (aperçu d'un document à modèle)
    expose_headers=["X-Avertissements"],
)


@app.on_event("startup")
async def _demarrer_planificateur():
    """Lot 13 (migration Render) : tâches périodiques (rappels d'échéances, envois WhatsApp
    planifiés) lancées par le serveur lui-même — remplace le service de crons d'Emergent."""
    import asyncio
    from albarka_planificateur import boucle_necessaire, boucle_planificateur, planificateur_actif
    from db import db as _db
    from version_deploiement import compteur_deploiements
    # Compteur de déploiements à jour dès le démarrage (numéro de version affiché)
    try:
        await compteur_deploiements(_db)
    except Exception:  # noqa: BLE001
        logger.exception("Compteur de déploiements indisponible (ignoré)")
    # Boucle de fond : envois (si PLANIFICATEUR_INTERNE ne les suspend pas) et sauvegarde nocturne
    if boucle_necessaire():
        asyncio.create_task(boucle_planificateur())
        logger.info("Planificateur interne démarré (envois %s, sauvegarde nocturne)",
                    "actifs" if planificateur_actif() else "suspendus")


@app.on_event("startup")
async def _demarrer_presence_sawali():
    """Lot 15.1 (règle 4) : déclaration de présence du serveur à SAWALI, en tâche de fond
    (10 s après le démarrage puis toutes les 5 min). Jamais bloquant ; PRESENCE_SAWALI=0 la coupe."""
    import asyncio
    from albarka_presence_sawali import boucle_presence_sawali, presence_active
    if presence_active():
        # Référence gardée sur l'application pour que la tâche ne soit pas ramassée par le GC
        app.state.tache_presence_sawali = asyncio.create_task(boucle_presence_sawali())
        logger.info("Signal de présence SAWALI démarré (toutes les 5 min)")


@app.on_event("shutdown")
async def shutdown_db_client():
    mongo_client.close()
