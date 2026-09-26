"""Accès du personnel — liste blanche (appareils + adresses IP) et jetons
d'accès temporaires.

Principe :
  - quand la liste blanche est activée (Paramètres → Accès du personnel), un
    collaborateur ne peut se connecter QUE depuis un appareil autorisé ou une
    adresse IP autorisée. Sinon, après mot de passe ET code OTP, il reçoit une
    fausse « ERREUR 404 » : un intrus ne sait même pas si ses identifiants
    étaient bons. Chaque tentative refusée est tracée et crée une demande
    d'appareil que le superviseur peut approuver ;
  - exemptés : admin (admin@sawalismartsystems.com), le rôle Superviseur (pour
    ne jamais bloquer tout le monde) et les clients ;
  - jeton d'accès temporaire : admin, ou une adresse e-mail désignée par admin,
    l'envoie à un collaborateur (e-mail + WhatsApp). Pendant sa durée, il
    ouvre l'accès depuis n'importe quel appareil ; mot de passe et OTP restent
    demandés, et la session ne dure pas plus longtemps que le jeton.

Collections : trusted_devices, device_requests, access_tokens.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import secrets
from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_roles
from albarka_models import is_admin_account, is_client, whatsapp_number_of
from db import db

logger = logging.getLogger("albarka.access")

router = APIRouter(prefix="/access", tags=["Accès du personnel"])

NOT_FOUND_DETAIL = "ERREUR 404"   # message volontairement neutre
MAX_TOKEN_HOURS = 24 * 7
DEFAULT_BASE_URL = "https://albarka-bf.com"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def client_ip(request: Optional[Request]) -> str:
    """Adresse IP réelle du navigateur (derrière le proxy : X-Forwarded-For)."""
    if request is None:
        return ""
    fwd = request.headers.get("x-forwarded-for") or ""
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def ip_allowed(ip: str, whitelist: List[str]) -> bool:
    """IP dans la liste (adresses simples ou plages CIDR, ex. 41.207.0.0/16)."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    for entry in whitelist or []:
        try:
            if addr in ipaddress.ip_network(entry.strip(), strict=False):
                return True
        except ValueError:
            continue
    return False


def normalize_ip_list(values: List[str]) -> List[str]:
    """Valide et normalise la liste d'IP / plages saisie dans les Paramètres."""
    out = []
    for v in values or []:
        v = (v or "").strip()
        if not v:
            continue
        try:
            out.append(str(ipaddress.ip_network(v, strict=False)))
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Adresse IP ou plage invalide : {v}")
    return list(dict.fromkeys(out))


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode()).hexdigest()


def is_exempt(user: Dict[str, Any]) -> bool:
    roles = set(user.get("roles") or [])
    return is_admin_account(user) or "superviseur" in roles or ("client" in roles and len(roles) == 1)


async def check_staff_access(user: Dict[str, Any], *, request: Optional[Request], device_id: Optional[str],
                             access_code: Optional[str]) -> Optional[datetime]:
    """Contrôle d'accès d'un collaborateur, APRÈS mot de passe et OTP.
    Renvoie la date de fin si l'accès passe par un jeton temporaire (la
    session ne doit pas durer plus longtemps), None sinon. Lève une 404
    neutre si l'accès est refusé."""
    settings = await get_settings_doc()
    if not settings.get("staff_whitelist_enabled") or is_exempt(user):
        return None
    ip = client_ip(request)
    device_id = (device_id or "").strip()[:80] or None
    # 1. Adresse IP autorisée (réseau du bureau)
    if ip_allowed(ip, settings.get("staff_ip_whitelist") or []):
        return None
    # 2. Appareil autorisé (partagé par tout le cabinet, ou propre à ce collaborateur)
    if device_id:
        dev = await db.trusted_devices.find_one({"device_id": device_id, "revoked": {"$ne": True},
                                                 "$or": [{"user_id": None}, {"user_id": user["id"]}]}, {"_id": 0})
        if dev:
            await db.trusted_devices.update_one({"id": dev["id"]}, {"$set": {"last_used_at": _now().isoformat(),
                                                                              "last_ip": ip}})
            return None
    # 3. Jeton d'accès temporaire valable pour ce collaborateur
    if access_code:
        tok = await db.access_tokens.find_one({"code_hash": _hash(access_code), "user_id": user["id"],
                                               "revoked": {"$ne": True}}, {"_id": 0})
        if tok and datetime.fromisoformat(tok["expires_at"]) > _now():
            await db.access_tokens.update_one({"id": tok["id"]}, {"$push": {"uses": {
                "at": _now().isoformat(), "ip": ip, "device_id": device_id}}})
            return datetime.fromisoformat(tok["expires_at"])
    # Refus : demande d'appareil (pour approbation) + journal, puis fausse 404
    ua = (request.headers.get("user-agent") if request else "") or ""
    if device_id:
        await db.device_requests.update_one(
            {"device_id": device_id, "user_id": user["id"], "status": "pending"},
            {"$set": {"ip": ip, "user_agent": ua[:250], "last_attempt_at": _now().isoformat(),
                      "user_name": user.get("full_name"), "user_email": user.get("email")},
             "$setOnInsert": {"id": secrets.token_urlsafe(10), "created_at": _now().isoformat()},
             "$inc": {"attempts": 1}}, upsert=True)
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action="login.blocked_whitelist", entity_type="user", entity_id=user["id"],
                              meta={"ip": ip, "device_id": device_id, "user_agent": ua[:250],
                                    "with_code": bool(access_code)})
    raise HTTPException(status_code=404, detail=NOT_FOUND_DETAIL)


# ---------------------------------------------------------------- qui peut créer des jetons
async def can_issue_tokens(user: Dict[str, Any]) -> bool:
    """admin, ou une adresse e-mail désignée par admin dans les Paramètres."""
    if is_admin_account(user):
        return True
    settings = await get_settings_doc()
    issuers = [e.strip().lower() for e in settings.get("access_token_issuer_emails") or []]
    return (user.get("email") or "").strip().lower() in issuers


@router.get("/me")
async def my_access_rights(user: dict = Depends(get_current_user)):
    return {"can_issue_tokens": await can_issue_tokens(user), "is_admin_account": is_admin_account(user)}


@router.get("/my-ip")
async def my_ip(request: Request, user: dict = Depends(require_roles(["superviseur"]))):
    """Adresse IP vue par le serveur (pour ajouter celle du bureau à la liste)."""
    return {"ip": client_ip(request)}


# ---------------------------------------------------------------- appareils (superviseur)
@router.get("/devices")
async def list_devices(user: dict = Depends(require_roles(["superviseur"]))):
    devices = await db.trusted_devices.find({"revoked": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(500)
    users = {u["id"]: u for u in await db.users.find(
        {"id": {"$in": [d["user_id"] for d in devices if d.get("user_id")]}}, {"_id": 0, "id": 1, "full_name": 1}).to_list(500)}
    for d in devices:
        d["user_name"] = users.get(d.get("user_id"), {}).get("full_name") if d.get("user_id") else None
    requests = await db.device_requests.find({"status": "pending"}, {"_id": 0}).sort("last_attempt_at", -1).to_list(200)
    return {"devices": devices, "requests": requests}


@router.post("/devices")
async def add_device(request: Request, payload: Dict[str, Any] = Body(...), user: dict = Depends(require_roles(["superviseur"]))):
    """Autorise un appareil : « cet appareil » (identifiant envoyé par le
    navigateur) comme poste partagé du cabinet, ou pour un collaborateur."""
    device_id = str(payload.get("device_id") or "").strip()[:80]
    if not device_id:
        raise HTTPException(status_code=400, detail="Identifiant d'appareil manquant")
    uid = payload.get("user_id") or None
    doc = {"id": secrets.token_urlsafe(10), "device_id": device_id, "user_id": uid,
           "label": str(payload.get("label") or "Appareil")[:80], "created_by": user["id"],
           "created_at": _now().isoformat(), "last_used_at": None, "revoked": False,
           "user_agent": (request.headers.get("user-agent") or "")[:250] if payload.get("current") else payload.get("user_agent")}
    await db.trusted_devices.insert_one(dict(doc))
    await db.device_requests.update_many({"device_id": device_id, "status": "pending",
                                          **({"user_id": uid} if uid else {})}, {"$set": {"status": "approved"}})
    from albarka_phase_c import _log_platform_event
    await _log_platform_event(user=user, action="device.approve", entity_type="device", entity_id=doc["id"],
                              meta={"label": doc["label"], "user_id": uid})
    doc.pop("_id", None)
    return doc


@router.post("/requests/{req_id}/approve")
async def approve_request(req_id: str, payload: Dict[str, Any] = Body(default={}), user: dict = Depends(require_roles(["superviseur"]))):
    """Approuve une demande : appareil réservé à ce collaborateur, ou poste partagé."""
    req = await db.device_requests.find_one({"id": req_id, "status": "pending"}, {"_id": 0})
    if not req:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    doc = {"id": secrets.token_urlsafe(10), "device_id": req["device_id"],
           "user_id": None if payload.get("shared") else req["user_id"],
           "label": str(payload.get("label") or f"Appareil de {req.get('user_name') or 'collaborateur'}")[:80],
           "created_by": user["id"], "created_at": _now().isoformat(), "last_used_at": None, "revoked": False,
           "user_agent": req.get("user_agent")}
    await db.trusted_devices.insert_one(dict(doc))
    await db.device_requests.update_one({"id": req_id}, {"$set": {"status": "approved", "decided_by": user["id"]}})
    from albarka_phase_c import _log_platform_event
    await _log_platform_event(user=user, action="device.approve", entity_type="device", entity_id=doc["id"],
                              meta={"label": doc["label"], "user_id": doc["user_id"]})
    return {"ok": True}


@router.post("/requests/{req_id}/reject")
async def reject_request(req_id: str, user: dict = Depends(require_roles(["superviseur"]))):
    res = await db.device_requests.update_one({"id": req_id, "status": "pending"},
                                              {"$set": {"status": "rejected", "decided_by": user["id"]}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Demande introuvable")
    return {"ok": True}


@router.delete("/devices/{dev_id}")
async def revoke_device(dev_id: str, user: dict = Depends(require_roles(["superviseur"]))):
    res = await db.trusted_devices.update_one({"id": dev_id}, {"$set": {"revoked": True, "revoked_by": user["id"],
                                                                        "revoked_at": _now().isoformat()}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    from albarka_phase_c import _log_platform_event
    await _log_platform_event(user=user, action="device.revoke", entity_type="device", entity_id=dev_id, meta={})
    return {"ok": True}


# ---------------------------------------------------------------- jetons d'accès temporaires
def _token_code() -> str:
    """Code lisible de 10 caractères (sans 0/O ni 1/I/L)."""
    alphabet = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(10))


def _token_email_html(*, cabinet: str, name: str, issuer: str, link: str, code: str, until: str, note: str) -> str:
    extra = f'<p style="margin:0 0 12px 0;white-space:pre-line;">{escape(note)}</p>' if note else ""
    return f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;max-width:560px;">
  <div style="background:#0B1912;color:#fff;padding:18px 24px;border-radius:10px 10px 0 0;">
    <div style="font-size:12px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">{escape(cabinet)}</div>
    <div style="font-size:20px;margin-top:4px;">Accès temporaire au portail</div>
  </div>
  <div style="border:1px solid #E2E8F0;border-top:0;padding:24px;border-radius:0 0 10px 10px;">
    <p style="margin:0 0 12px 0;">Bonjour {escape(name)},</p>
    <p style="margin:0 0 12px 0;">{escape(issuer)} vous ouvre un accès temporaire au portail du cabinet, valable jusqu'au <b>{escape(until)}</b>.</p>
    {extra}
    <p style="margin:20px 0;text-align:center;"><a href="{escape(link)}" style="background:#0F6B4A;color:#fff;text-decoration:none;padding:12px 22px;border-radius:8px;font-weight:600;display:inline-block;">Se connecter avec l'accès temporaire</a></p>
    <p style="margin:0 0 8px 0;font-size:13px;">Code d'accès (à saisir si besoin sur la page de connexion) : <b style="font-family:monospace;font-size:16px;">{escape(code)}</b></p>
    <p style="margin:12px 0 0 0;font-size:12px;color:#64748B;">Votre mot de passe et le code de vérification restent demandés. Ne transférez pas ce message.</p>
  </div>
</div>"""


@router.post("/tokens")
async def create_token(request: Request, payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    """Crée un jeton temporaire pour un collaborateur et le lui envoie (e-mail + WhatsApp)."""
    if not await can_issue_tokens(user):
        raise HTTPException(status_code=403, detail="Seul admin, ou une adresse désignée par admin, peut créer un accès temporaire")
    target = await db.users.find_one({"id": payload.get("user_id")}, {"_id": 0, "password_hash": 0})
    if not target or is_client(target):
        raise HTTPException(status_code=404, detail="Collaborateur introuvable")
    try:
        hours = int(payload.get("hours") or 24)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="Durée invalide")
    if not 1 <= hours <= MAX_TOKEN_HOURS:
        raise HTTPException(status_code=400, detail=f"Durée entre 1 h et {MAX_TOKEN_HOURS} h (7 jours)")
    note = str(payload.get("note") or "").strip()[:300]
    code = _token_code()
    expires = _now() + timedelta(hours=hours)
    doc = {"id": secrets.token_urlsafe(10), "code_hash": _hash(code), "user_id": target["id"],
           "user_name": target.get("full_name"), "expires_at": expires.isoformat(), "hours": hours, "note": note,
           "created_by": user["id"], "created_by_name": user.get("full_name") or user.get("email"),
           "created_at": _now().isoformat(), "revoked": False, "uses": []}
    await db.access_tokens.insert_one(dict(doc))
    # Envoi : lien de connexion (le code y est joint) par e-mail et WhatsApp
    origin = (request.headers.get("origin") or "").rstrip("/")
    base = origin if origin.startswith("https://") else DEFAULT_BASE_URL
    link = f"{base}/login?acces={code}"
    settings = await get_settings_doc()
    cabinet = settings.get("cabinet_name") or "Cabinet ALBARKA"
    until = expires.astimezone(timezone(timedelta(hours=0))).strftime("%d/%m/%Y %H:%M (GMT)")
    issuer = user.get("full_name") or "La direction"
    from albarka_notifications import send_email, send_whatsapp
    delivery: Dict[str, Any] = {}
    try:
        sent = await send_email(to=target["email"], subject=f"Accès temporaire au portail — {cabinet}",
                                html=_token_email_html(cabinet=cabinet, name=target.get("full_name") or "", issuer=issuer,
                                                       link=link, code=code, until=until, note=note))
        delivery["email"] = {"ok": bool(sent)}
    except ValueError as exc:
        delivery["email"] = {"ok": False, "error": str(exc)[:150]}
    phone = whatsapp_number_of(target) or ""
    if phone.startswith("+"):
        r = await send_whatsapp(to_phone=phone, message=(
            f"*{cabinet}*\nAccès temporaire au portail, ouvert par {issuer}, valable jusqu'au {until}.\n\n"
            f"Se connecter : {link}\nCode d'accès : {code}\n\nMot de passe et code de vérification restent demandés."))
        delivery["whatsapp"] = {"ok": bool(r.get("ok")), "error": None if r.get("ok") else r.get("error")}
    else:
        delivery["whatsapp"] = {"ok": False, "error": "Pas de numéro WhatsApp"}
    await db.access_tokens.update_one({"id": doc["id"]}, {"$set": {"delivery": delivery}})
    from albarka_phase_c import _log_platform_event
    await _log_platform_event(user=user, action="access_token.create", entity_type="user", entity_id=target["id"],
                              meta={"hours": hours, "expires_at": doc["expires_at"]})  # jamais le code
    return {"id": doc["id"], "code": code, "link": link, "expires_at": doc["expires_at"], "delivery": delivery}


@router.get("/tokens")
async def list_tokens(user: dict = Depends(get_current_user)):
    if not (await can_issue_tokens(user) or "superviseur" in (user.get("roles") or [])):
        raise HTTPException(status_code=403, detail="Accès refusé")
    items = await db.access_tokens.find({}, {"_id": 0, "code_hash": 0}).sort("created_at", -1).to_list(200)
    now = _now()
    for t in items:
        t["active"] = not t.get("revoked") and datetime.fromisoformat(t["expires_at"]) > now
    return {"items": items}


@router.delete("/tokens/{token_id}")
async def revoke_token(token_id: str, user: dict = Depends(get_current_user)):
    if not (await can_issue_tokens(user) or "superviseur" in (user.get("roles") or [])):
        raise HTTPException(status_code=403, detail="Accès refusé")
    res = await db.access_tokens.update_one({"id": token_id}, {"$set": {"revoked": True, "revoked_by": user["id"]}})
    if not res.matched_count:
        raise HTTPException(status_code=404, detail="Jeton introuvable")
    from albarka_phase_c import _log_platform_event
    await _log_platform_event(user=user, action="access_token.revoke", entity_type="access_token", entity_id=token_id, meta={})
    return {"ok": True}


async def ensure_access_indexes() -> None:
    await db.trusted_devices.create_index("device_id")
    await db.device_requests.create_index([("status", 1), ("last_attempt_at", -1)])
    await db.access_tokens.create_index("code_hash")
