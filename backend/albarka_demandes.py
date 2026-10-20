"""Lot 53 — Demandes de services (fiscalité, RH, comptable, autres).

Un client (connecté) ou un visiteur (page publique, ou lien depuis WhatsApp) décrit son besoin :
texte, note vocale et pièces jointes. La demande est rangée dans la collection EXISTANTE `missions`
(type « demande_service ») : aucune nouvelle collection (cluster Atlas plein).
Le cabinet est alerté par e-mail (préfixe « URGENT » si coché) et le demandeur reçoit un accusé.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

from albarka_auth import get_current_user, require_staff
from albarka_models import is_client, tenant_id_of
from albarka_storage import get_object, save_and_log
from db import db, serialize, serialize_many

logger = logging.getLogger(__name__)

STAFF_DEP = require_staff()   # dépendance unique réutilisée par les routes du cabinet
router = APIRouter(prefix="/demandes", tags=["Demandes de services"])
public_router = APIRouter(prefix="/public", tags=["Public"])

# Liste finie de services -> menu déroulant côté écran.
SERVICES = [
    {"code": "fiscalite", "libelle": "Fiscalité"},
    {"code": "rh", "libelle": "Ressources humaines"},
    {"code": "comptable", "libelle": "Comptabilité"},
    {"code": "autres", "libelle": "Autres demandes"},
]
CODES = {s["code"] for s in SERVICES}
LIBELLES = {s["code"]: s["libelle"] for s in SERVICES}
STATUTS = ["nouvelle", "en_cours", "traitee", "classee"]

MAX_FICHIERS = 5
MAX_FICHIER = 10 * 1024 * 1024         # 10 Mo par pièce jointe
MAX_VOCAL = 8 * 1024 * 1024            # 8 Mo pour la note vocale
EXT_PIECES = {"pdf", "doc", "docx", "xls", "xlsx", "jpg", "jpeg", "png"}
EXT_VOCAL = {"webm", "ogg", "mp3", "m4a", "wav", "mp4", "aac"}
PUBLIC_MAX_PAR_HEURE = 5               # anti-abus de la page publique


def _ext(nom: str) -> str:
    return nom.rsplit(".", 1)[-1].lower() if "." in (nom or "") else ""


def _service_ok(code: str) -> str:
    """Valide le service choisi (liste finie)."""
    code = (code or "").strip().lower()
    if code not in CODES:
        raise HTTPException(status_code=400, detail="Service inconnu : choisissez dans la liste")
    return code


async def _ranger_fichier(f: UploadFile, *, vocal: bool, tenant: str, user_id: Optional[str], limite: int) -> Dict[str, Any]:
    """Contrôle (extension, taille) puis enregistre un fichier ; renvoie sa description."""
    ext = _ext(f.filename or "")
    if ext not in (EXT_VOCAL if vocal else EXT_PIECES):
        raise HTTPException(status_code=400, detail=f"Type de fichier non autorisé : .{ext or '?'}")
    data = await f.read()
    if not data:
        raise HTTPException(status_code=400, detail="Fichier vide")
    if len(data) > limite:
        raise HTTPException(status_code=413, detail=f"Fichier trop volumineux (max {limite // (1024 * 1024)} Mo)")
    st = await save_and_log(db, data=data, kind="demande_service", tenant_id=tenant, ext=ext,
                            content_type=f.content_type or None, original_filename=f.filename, user_id=user_id)
    return {"id": st["id"], "path": st["path"], "nom": f.filename or f"fichier.{ext}",
            "content_type": st["content_type"], "size": st["size"]}


async def _alerter_cabinet(doc: dict) -> None:
    """E-mail aux collaborateurs actifs (en arrière-plan, jamais bloquant)."""
    try:
        from albarka_notifications import send_email
        from albarka_admin_settings import get_settings_doc
        reglages = await get_settings_doc()
        staff = await db.users.find(
            {"roles": {"$nin": ["client"]}, "is_active": True, "is_test_account": {"$ne": True},
             "$or": [{"can_receive_notifications": {"$exists": False}}, {"can_receive_notifications": True}]},
            {"_id": 0, "email": 1},
        ).to_list(500)
        dest = [s["email"] for s in staff if s.get("email")]
        if reglages.get("cabinet_email"):
            dest.append(reglages["cabinet_email"])
        dest = sorted(set(dest))
        if not dest:
            return
        sujet = f"{'🚨 URGENT — ' if doc.get('urgent') else ''}Demande de service ({LIBELLES.get(doc['service'], '')}) — {doc['demandeur'].get('nom') or ''}"
        d = doc["demandeur"]
        html = (
            "<div style='font-family:Arial,sans-serif;font-size:14px;color:#0F172A'>"
            f"<h3>Nouvelle demande de service : {escape(LIBELLES.get(doc['service'], ''))}</h3>"
            f"<p><b>Demandeur :</b> {escape(d.get('nom') or '')} · {escape(d.get('telephone') or '')} · {escape(d.get('email') or '')}"
            f" ({'client' if doc['origine'] == 'client' else 'visiteur'})</p>"
            f"<p style='white-space:pre-wrap'>{escape(doc.get('description') or '(aucun texte — voir note vocale)')}</p>"
            f"<p>{len(doc.get('fichiers') or [])} pièce(s) jointe(s){' · note vocale' if doc.get('vocal') else ''}.</p>"
            "<p style='color:#64748B;font-size:12px'>Ouvrez « Demandes de services » dans le portail pour traiter.</p></div>"
        )
        await send_email(to=dest, subject=sujet, html=html)
    except Exception:  # noqa: BLE001
        logger.exception("Alerte cabinet (demande de service) non envoyée")


async def _accuse(doc: dict) -> None:
    """Accusé de réception au demandeur (e-mail si connu), best-effort."""
    try:
        d = doc["demandeur"]
        if not d.get("email"):
            return
        from albarka_notifications import send_email
        html = (
            "<div style='font-family:Arial,sans-serif;font-size:14px;color:#0F172A'>"
            f"<p>Bonjour {escape(d.get('nom') or '')},</p>"
            f"<p>Nous avons bien reçu votre demande ({escape(LIBELLES.get(doc['service'], ''))}). "
            "Un collaborateur du cabinet revient vers vous très prochainement.</p></div>"
        )
        await send_email(to=d["email"], subject="Votre demande est bien reçue", html=html)
    except Exception:  # noqa: BLE001
        logger.exception("Accusé de réception non envoyé")


async def _creer(*, service: str, message: str, urgent: bool, demandeur: dict, origine: str, tenant_id: str,
                 vocal: Optional[UploadFile], fichiers: List[UploadFile], user_id: Optional[str]) -> dict:
    """Crée la demande dans `missions` (type demande_service) et lance alerte + accusé en arrière-plan."""
    message = (message or "").strip()
    fichiers = [f for f in (fichiers or []) if f and f.filename]
    if vocal is not None and not vocal.filename:
        vocal = None
    if not message and vocal is None and not fichiers:
        raise HTTPException(status_code=400, detail="Décrivez votre demande par écrit, par note vocale ou joignez un fichier")
    if len(message) > 5000:
        raise HTTPException(status_code=400, detail="Message trop long (5000 caractères au plus)")
    if len(fichiers) > MAX_FICHIERS:
        raise HTTPException(status_code=400, detail=f"{MAX_FICHIERS} pièces jointes au plus")
    pieces = [await _ranger_fichier(f, vocal=False, tenant=tenant_id, user_id=user_id, limite=MAX_FICHIER) for f in fichiers]
    note = await _ranger_fichier(vocal, vocal=True, tenant=tenant_id, user_id=user_id, limite=MAX_VOCAL) if vocal else None
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "id": secrets.token_urlsafe(12), "tenant_id": tenant_id, "type": "demande_service",
        "title": f"Demande — {LIBELLES[service]}", "service": service, "description": message,
        "urgent": bool(urgent), "origine": origine, "demandeur": demandeur,
        "fichiers": pieces, "vocal": note, "status": "nouvelle", "assigned_to": [],
        "created_by": user_id, "created_at": now, "updated_at": now,
    }
    await db.missions.insert_one(doc.copy())
    asyncio.create_task(_alerter_cabinet(doc))
    asyncio.create_task(_accuse(doc))
    return doc


def _vue(doc: dict, *, staff: bool) -> dict:
    """Vue sans chemins de stockage : seulement de quoi télécharger via la route protégée."""
    v = serialize(dict(doc))
    v["fichiers"] = [{"index": i, "nom": f["nom"], "content_type": f["content_type"], "size": f["size"]}
                     for i, f in enumerate(doc.get("fichiers") or [])]
    if doc.get("vocal"):
        v["vocal"] = {"nom": doc["vocal"]["nom"], "content_type": doc["vocal"]["content_type"], "size": doc["vocal"]["size"]}
    if not staff:
        v.pop("created_by", None)
        v.pop("assigned_to", None)
    return v


@router.get("/services")
async def liste_services():
    """Liste finie des services (menu déroulant)."""
    return {"services": SERVICES, "statuts": STATUTS}


@router.post("")
async def demande_client(
    service: str = Form(...), message: str = Form(""), urgent: bool = Form(False),
    vocal: Optional[UploadFile] = File(None), fichiers: List[UploadFile] = File(default=[]),
    user: dict = Depends(get_current_user),
):
    """Demande déposée par un client connecté (ou par le cabinet pour le compte d'un client)."""
    service = _service_ok(service)
    tenant = tenant_id_of(user) if is_client(user) else user["id"]
    demandeur = {"nom": user.get("full_name") or user.get("company") or "", "email": user.get("email") or "",
                 "telephone": user.get("phone") or ""}
    doc = await _creer(service=service, message=message, urgent=urgent, demandeur=demandeur,
                       origine="client" if is_client(user) else "cabinet", tenant_id=tenant,
                       vocal=vocal, fichiers=fichiers, user_id=user["id"])
    return _vue(doc, staff=False)


@router.get("/mes")
async def mes_demandes(user: dict = Depends(get_current_user)):
    """Historique des demandes du client connecté."""
    docs = await db.missions.find({"type": "demande_service", "tenant_id": tenant_id_of(user)}, {"_id": 0}) \
        .sort("created_at", -1).to_list(200)
    return [_vue(d, staff=False) for d in docs]


@router.get("/admin")
async def liste_cabinet(statut: Optional[str] = None, service: Optional[str] = None,
                        user: dict = Depends(STAFF_DEP)):
    """Toutes les demandes (cabinet), filtrables par statut et service."""
    q: Dict[str, Any] = {"type": "demande_service"}
    if statut:
        q["status"] = statut
    if service:
        q["service"] = service
    docs = await db.missions.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return [_vue(d, staff=True) for d in docs]


@router.patch("/admin/{demande_id}")
async def traiter(demande_id: str, payload: dict, user: dict = Depends(STAFF_DEP)):
    """Change le statut (liste finie) et/ou la note interne d'une demande."""
    maj: Dict[str, Any] = {}
    if "status" in payload:
        if payload["status"] not in STATUTS:
            raise HTTPException(status_code=400, detail="Statut inconnu")
        maj["status"] = payload["status"]
    if "note_interne" in payload:
        maj["note_interne"] = str(payload["note_interne"] or "")[:2000]
    if not maj:
        raise HTTPException(status_code=400, detail="Rien à modifier")
    maj["updated_at"] = datetime.now(timezone.utc).isoformat()
    res = await db.missions.update_one({"id": demande_id, "type": "demande_service"}, {"$set": maj})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    doc = await db.missions.find_one({"id": demande_id}, {"_id": 0})
    return _vue(doc, staff=True)


@router.get("/{demande_id}/fichier/{quoi}")
async def telecharger(demande_id: str, quoi: str, user: dict = Depends(get_current_user)):
    """Télécharge une pièce jointe (`quoi` = index) ou la note vocale (`quoi` = « vocal »)."""
    doc = await db.missions.find_one({"id": demande_id, "type": "demande_service"}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    if is_client(user) and doc.get("tenant_id") != tenant_id_of(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    if quoi == "vocal":
        f = doc.get("vocal")
    else:
        try:
            f = (doc.get("fichiers") or [])[int(quoi)]
        except (ValueError, IndexError):
            f = None
    if not f:
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    data, ct = await get_object(f["path"])
    return Response(content=data, media_type=f.get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{f["nom"]}"'})


@public_router.post("/demande-service")
async def demande_publique(
    request: Request,
    nom: str = Form(...), telephone: str = Form(...), email: str = Form(""),
    service: str = Form(...), message: str = Form(""), urgent: bool = Form(False),
    site_web: str = Form(""),                      # piège anti-robot : doit rester vide
    captcha_token: Optional[str] = Form(None),
    vocal: Optional[UploadFile] = File(None), fichiers: List[UploadFile] = File(default=[]),
):
    """Demande d'un visiteur (sans compte) : depuis la page d'accueil ou le lien envoyé sur WhatsApp."""
    if site_web.strip():                           # robot : on répond « ok » sans rien enregistrer
        return {"ok": True}
    service = _service_ok(service)
    nom, telephone, email = nom.strip(), telephone.strip(), email.strip().lower()
    if len(nom) < 2 or len(telephone) < 6:
        raise HTTPException(status_code=400, detail="Indiquez votre nom et un numéro de téléphone valide")
    if email and "@" not in email:
        raise HTTPException(status_code=400, detail="Adresse e-mail invalide")
    from albarka_recaptcha import verify_recaptcha
    cap = await verify_recaptcha(captcha_token)
    if not cap["success"]:
        raise HTTPException(status_code=400, detail=f"Captcha invalide ({cap['reason']})")
    depuis = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    deja = await db.missions.count_documents({"type": "demande_service", "origine": "public",
                                              "demandeur.telephone": telephone, "created_at": {"$gte": depuis}})
    if deja >= PUBLIC_MAX_PAR_HEURE:
        raise HTTPException(status_code=429, detail="Trop de demandes récentes : réessayez dans une heure")
    doc = await _creer(service=service, message=message, urgent=urgent,
                       demandeur={"nom": nom, "email": email, "telephone": telephone},
                       origine="public", tenant_id="public", vocal=vocal, fichiers=fichiers, user_id=None)
    return {"ok": True, "id": doc["id"]}
