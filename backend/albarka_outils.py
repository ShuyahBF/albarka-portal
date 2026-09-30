"""Lot 9 — espace « Outils Numériques ».

Principe :
  - le compte admin du portail (super-admin, voir is_admin_account dans
    albarka_models.py) gère la liste des outils à télécharger : lien (http(s)
    ou FTP), image (envoyée vers le stockage R2/local ou icône prédéfinie),
    légende, taille approximative, version, visible oui/non, public visé
    (clients, personnel ou les deux) et ordre d'affichage ;
  - clients et personnel voient les outils visibles qui leur sont destinés ;
  - un clic passe TOUJOURS par le serveur : les navigateurs modernes n'ouvrent
    plus les liens ftp://. Le serveur enregistre le téléchargement (date/heure
    UTC, IP réelle, utilisateur, navigateur…), puis redirige vers le lien
    http(s) ou relaie le fichier FTP en flux ;
  - les identifiants FTP (ftp://utilisateur:mot-de-passe@hôte/…) ne sortent
    jamais du serveur : ils sont masqués partout (liste admin, historique,
    journaux) ;
  - l'historique des téléchargements est réservé au super-admin (403 sinon).

Collections : digital_tools, digital_tool_downloads, digital_tool_links.
"""
from __future__ import annotations

import asyncio
import csv
import ftplib
import io
import logging
import mimetypes
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote, unquote, urlsplit

from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import RedirectResponse, Response, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from albarka_access import client_ip
from albarka_auth import ALGORITHM, SECRET_KEY, get_current_user
from albarka_models import is_admin_account
from albarka_storage import delete_object, get_object, put_object
from db import db

logger = logging.getLogger("albarka.outils")

router = APIRouter(prefix="/outils-numeriques", tags=["Outils numériques"])

# Icônes prédéfinies proposées quand aucune image n'est envoyée (le rendu
# de chaque icône est fait côté navigateur).
PRESET_ICONS = ["logiciel", "pdf", "tableur", "archive", "mobile", "video"]
# Public visé par un outil
AUDIENCES = ["tous", "clients", "personnel"]
# Protocoles acceptés pour le lien de téléchargement
ALLOWED_SCHEMES = {"http", "https", "ftp", "ftps"}
# Images acceptées (pas de SVG : il peut contenir du script)
IMAGE_MIMES = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}
MAX_IMAGE_SIZE = 2 * 1024 * 1024  # 2 Mo
# Lien de téléchargement signé : durée de validité courte, usage unique
LINK_TTL_SECONDS = 120
LINK_PURPOSE = "outil_dl"
# Taille des morceaux lus sur la connexion FTP
FTP_CHUNK = 64 * 1024
FTP_TIMEOUT = 30
# Historique : nombre maximal de lignes renvoyées à l'écran / dans l'export
HISTORY_MAX = 1000
EXPORT_MAX = 20000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


# ==========================================================================
# Contrôles d'accès
# ==========================================================================
async def require_super_admin(user: dict = Depends(get_current_user)) -> dict:
    """Réservé au compte admin du portail (pas le rôle Superviseur ni la
    Direction) — voir is_admin_account (albarka_models.py)."""
    if not is_admin_account(user):
        raise HTTPException(status_code=403, detail="Réservé à l'administrateur du portail")
    return user


def user_type(user: dict) -> str:
    """« client » pour un compte client pur, « personnel » sinon (même règle
    que require_staff dans albarka_auth.py)."""
    roles = set(user.get("roles") or [])
    return "client" if roles == {"client"} else "personnel"


def audience_filter(user: dict) -> dict:
    """Filtre Mongo des outils destinés à cet utilisateur."""
    wanted = "clients" if user_type(user) == "client" else "personnel"
    return {"audience": {"$in": ["tous", wanted]}}


def _can_see(tool: dict, user: dict) -> bool:
    wanted = "clients" if user_type(user) == "client" else "personnel"
    return bool(tool.get("visible")) and (tool.get("audience") or "tous") in ("tous", wanted)


# ==========================================================================
# Liens : validation et masquage des identifiants
# ==========================================================================
def validate_link(url: str) -> str:
    """Vérifie le lien saisi par l'admin (protocole et hôte) et le renvoie nettoyé."""
    url = (url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Lien de téléchargement requis")
    try:
        parts = urlsplit(url)
        parts.port  # port non numérique -> ValueError
    except ValueError:
        raise HTTPException(status_code=400, detail="Lien de téléchargement invalide")
    if parts.scheme.lower() not in ALLOWED_SCHEMES or not parts.hostname:
        raise HTTPException(status_code=400, detail="Lien invalide : http://, https://, ftp:// ou ftps:// avec un hôte")
    if parts.scheme.lower() in ("ftp", "ftps") and not parts.path.strip("/"):
        raise HTTPException(status_code=400, detail="Lien FTP invalide : chemin du fichier manquant")
    return url


def mask_link(url: str) -> str:
    """Remplace les identifiants éventuels par *** (ex. ftp://***@hôte/chemin)."""
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except ValueError:
        return "(lien invalide)"
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    userinfo = "***@" if (parts.username or parts.password) else ""
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{userinfo}{host}{parts.path}{query}"


def link_protocol(url: str) -> str:
    scheme = urlsplit(url or "").scheme.lower()
    return "ftp" if scheme in ("ftp", "ftps") else "http"


# ==========================================================================
# Présentation des outils
# ==========================================================================
def _public_view(tool: dict) -> dict:
    """Champs montrés aux utilisateurs (jamais le lien)."""
    return {
        "id": tool["id"],
        "caption": tool.get("caption") or "",
        "version": tool.get("version") or "",
        "size_label": tool.get("size_label") or "",
        "icon": tool.get("icon") or "logiciel",
        "has_image": bool((tool.get("image") or {}).get("path")),
        "image_rev": (tool.get("image") or {}).get("uploaded_at") or "",
        "order": tool.get("order", 0),
        # http : redirection (peut ouvrir une page) ; ftp : fichier relayé en pièce jointe
        "protocol": link_protocol(tool.get("link") or ""),
    }


def _admin_view(tool: dict) -> dict:
    """Vue super-admin : tous les champs, lien masqué."""
    view = _public_view(tool)
    view.update({
        "visible": bool(tool.get("visible")),
        "audience": tool.get("audience") or "tous",
        "link_masked": mask_link(tool.get("link") or ""),
        "has_credentials": bool(urlsplit(tool.get("link") or "").username),
        "download_count": tool.get("download_count", 0),
        "created_at": tool.get("created_at"),
        "updated_at": tool.get("updated_at"),
        "updated_by_name": tool.get("updated_by_name"),
    })
    return view


def _clean_fields(payload: dict, *, creating: bool) -> dict:
    """Contrôle les champs envoyés par le formulaire d'administration."""
    out: Dict[str, Any] = {}
    if creating or "caption" in payload:
        caption = (payload.get("caption") or "").strip()
        if not caption:
            raise HTTPException(status_code=400, detail="Légende requise")
        out["caption"] = caption[:120]
    # Lien : à la modification, vide = conserver le lien actuel (jamais renvoyé en clair)
    link = (payload.get("link") or "").strip()
    if creating or link:
        out["link"] = validate_link(link)
    for key, limit in (("version", 40), ("size_label", 40)):
        if key in payload:
            out[key] = (payload.get(key) or "").strip()[:limit]
    if "icon" in payload or creating:
        icon = payload.get("icon") or "logiciel"
        if icon not in PRESET_ICONS:
            raise HTTPException(status_code=400, detail=f"Icône inconnue (attendu : {', '.join(PRESET_ICONS)})")
        out["icon"] = icon
    if "audience" in payload or creating:
        audience = payload.get("audience") or "tous"
        if audience not in AUDIENCES:
            raise HTTPException(status_code=400, detail="Public visé : tous, clients ou personnel")
        out["audience"] = audience
    if "visible" in payload or creating:
        out["visible"] = bool(payload.get("visible", True))
    return out


async def _get_tool(tool_id: str) -> dict:
    tool = await db.digital_tools.find_one({"id": tool_id}, {"_id": 0})
    if not tool:
        raise HTTPException(status_code=404, detail="Outil introuvable")
    return tool


async def _audit(user: dict, action: str, tool_id: str, meta: Optional[dict] = None) -> None:
    """Trace des modifications dans le Journal plateforme (best-effort)."""
    try:
        from albarka_phase_c import _log_platform_event
        await _log_platform_event(user=user, action=action, entity_type="digital_tool",
                                  entity_id=tool_id, meta=meta or {})
    except Exception:  # noqa: BLE001
        logger.exception("Journal plateforme indisponible (%s)", action)


# ==========================================================================
# Administration (super-admin uniquement)
# ==========================================================================
@router.get("/admin/outils")
async def admin_list_tools(user: dict = Depends(require_super_admin)):
    items = await db.digital_tools.find({}, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(500)
    return {"items": [_admin_view(t) for t in items], "icons": PRESET_ICONS, "audiences": AUDIENCES}


@router.post("/admin/outils")
async def admin_create_tool(payload: dict = Body(...), user: dict = Depends(require_super_admin)):
    fields = _clean_fields(payload, creating=True)
    # Nouvel outil placé en fin de liste
    last = await db.digital_tools.find({}, {"_id": 0, "order": 1}).sort("order", -1).to_list(1)
    now = _now_iso()
    tool = {
        "id": secrets.token_urlsafe(12),
        **fields,
        "image": None,
        "order": (last[0].get("order", 0) + 1) if last else 1,
        "download_count": 0,
        "created_at": now, "created_by": user["id"],
        "updated_at": now, "updated_by": user["id"], "updated_by_name": user.get("full_name") or user.get("email"),
    }
    await db.digital_tools.insert_one(dict(tool))
    await _audit(user, "digital_tool.create", tool["id"], {"caption": tool["caption"], "link": mask_link(tool["link"])})
    return _admin_view(tool)


@router.put("/admin/outils/{tool_id}")
async def admin_update_tool(tool_id: str, payload: dict = Body(...), user: dict = Depends(require_super_admin)):
    await _get_tool(tool_id)
    fields = _clean_fields(payload, creating=False)
    fields.update({"updated_at": _now_iso(), "updated_by": user["id"],
                   "updated_by_name": user.get("full_name") or user.get("email")})
    await db.digital_tools.update_one({"id": tool_id}, {"$set": fields})
    meta = {k: v for k, v in fields.items() if k in ("caption", "version", "visible", "audience")}
    if "link" in fields:
        meta["link"] = mask_link(fields["link"])
    await _audit(user, "digital_tool.update", tool_id, meta)
    return _admin_view(await _get_tool(tool_id))


@router.delete("/admin/outils/{tool_id}")
async def admin_delete_tool(tool_id: str, user: dict = Depends(require_super_admin)):
    tool = await _get_tool(tool_id)
    path = (tool.get("image") or {}).get("path")
    if path:
        try:
            await delete_object(path)
        except Exception:  # noqa: BLE001
            logger.exception("Suppression image outil %s échouée (poursuite)", tool_id)
    await db.digital_tools.delete_one({"id": tool_id})
    # L'historique des téléchargements est conservé (légende et version y sont recopiées)
    await _audit(user, "digital_tool.delete", tool_id, {"caption": tool.get("caption")})
    return {"ok": True}


@router.post("/admin/outils/reorder")
async def admin_reorder_tools(payload: dict = Body(...), user: dict = Depends(require_super_admin)):
    """Ordre d'affichage : liste complète des identifiants dans l'ordre voulu."""
    ids = payload.get("ids") or []
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise HTTPException(status_code=400, detail="ids : liste d'identifiants attendue")
    for pos, tid in enumerate(ids, start=1):
        await db.digital_tools.update_one({"id": tid}, {"$set": {"order": pos}})
    return await admin_list_tools(user)


@router.post("/admin/outils/{tool_id}/image")
async def admin_upload_image(tool_id: str, file: UploadFile = File(...), user: dict = Depends(require_super_admin)):
    tool = await _get_tool(tool_id)
    ext = IMAGE_MIMES.get(file.content_type or "")
    if not ext:
        raise HTTPException(status_code=400, detail="Format non supporté : PNG, JPG, WEBP ou GIF")
    data = await file.read()
    if len(data) > MAX_IMAGE_SIZE:
        raise HTTPException(status_code=413, detail="Image trop volumineuse (2 Mo max)")
    # Même stockage que les autres images du portail (R2 si configuré, sinon local)
    path = f"albarka/cabinet/outils/{tool_id}-{secrets.token_hex(4)}.{ext}"
    await put_object(path, data, file.content_type)
    prev = (tool.get("image") or {}).get("path")
    if prev and prev != path:
        try:
            await delete_object(prev)
        except Exception:  # noqa: BLE001
            logger.exception("Suppression ancienne image outil %s échouée (poursuite)", tool_id)
    image = {"path": path, "content_type": file.content_type, "size": len(data), "uploaded_at": _now_iso()}
    await db.digital_tools.update_one({"id": tool_id}, {"$set": {"image": image, "updated_at": _now_iso()}})
    return _admin_view(await _get_tool(tool_id))


@router.delete("/admin/outils/{tool_id}/image")
async def admin_delete_image(tool_id: str, user: dict = Depends(require_super_admin)):
    """Retire l'image envoyée : l'icône prédéfinie reprend sa place."""
    tool = await _get_tool(tool_id)
    path = (tool.get("image") or {}).get("path")
    if path:
        try:
            await delete_object(path)
        except Exception:  # noqa: BLE001
            logger.exception("Suppression image outil %s échouée (poursuite)", tool_id)
    await db.digital_tools.update_one({"id": tool_id}, {"$set": {"image": None, "updated_at": _now_iso()}})
    return _admin_view(await _get_tool(tool_id))


# ==========================================================================
# Historique des téléchargements (super-admin uniquement)
# ==========================================================================
def _history_query(date_from: Optional[str], date_to: Optional[str], tool_id: Optional[str],
                   user_q: Optional[str], utype: Optional[str]) -> dict:
    """Filtres : période (AAAA-MM-JJ, bornes incluses, en UTC), outil,
    utilisateur (nom, e-mail ou société) et type (client / personnel)."""
    q: Dict[str, Any] = {}
    period: Dict[str, str] = {}
    try:
        if date_from:
            period["$gte"] = datetime.strptime(date_from[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).isoformat()
        if date_to:
            end = datetime.strptime(date_to[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
            period["$lt"] = end.isoformat()
    except ValueError:
        raise HTTPException(status_code=400, detail="Date attendue au format AAAA-MM-JJ")
    if period:
        q["created_at"] = period
    if tool_id:
        q["tool_id"] = tool_id
    if utype in ("client", "personnel"):
        q["user_type"] = utype
    if user_q and user_q.strip():
        rx = {"$regex": re.escape(user_q.strip()), "$options": "i"}
        q["$or"] = [{"user_name": rx}, {"user_email": rx}, {"user_company": rx}]
    return q


@router.get("/admin/telechargements")
async def admin_download_history(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    tool_id: Optional[str] = None, user_q: Optional[str] = Query(None, alias="user"),
    user_type_: Optional[str] = Query(None, alias="user_type"),
    limit: int = 500,
    user: dict = Depends(require_super_admin),
):
    q = _history_query(date_from, date_to, tool_id, user_q, user_type_)
    total = await db.digital_tool_downloads.count_documents(q)
    items = await db.digital_tool_downloads.find(q, {"_id": 0}).sort("created_at", -1) \
        .to_list(min(max(limit, 1), HISTORY_MAX))
    return {"items": items, "total": total}


CSV_COLUMNS = [
    ("created_at", "Date/heure (UTC)"), ("tool_caption", "Outil"), ("tool_version", "Version"),
    ("user_name", "Utilisateur"), ("user_email", "E-mail"), ("user_type", "Type"),
    ("user_roles", "Rôles"), ("user_company", "Société"), ("ip", "Adresse IP"),
    ("protocol", "Protocole"), ("status", "Statut"), ("user_agent", "Navigateur"),
]


@router.get("/admin/telechargements/csv")
async def admin_download_history_csv(
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    tool_id: Optional[str] = None, user_q: Optional[str] = Query(None, alias="user"),
    user_type_: Optional[str] = Query(None, alias="user_type"),
    user: dict = Depends(require_super_admin),
):
    """Export pour Excel : UTF-8 avec BOM, séparateur « ; », plus récent en premier."""
    q = _history_query(date_from, date_to, tool_id, user_q, user_type_)
    items = await db.digital_tool_downloads.find(q, {"_id": 0}).sort("created_at", -1).to_list(EXPORT_MAX)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([label for _, label in CSV_COLUMNS])
    for it in items:
        row = []
        for key, _ in CSV_COLUMNS:
            val = it.get(key)
            if key == "created_at" and val:
                val = str(val)[:19].replace("T", " ")
            elif key == "user_roles":
                val = ", ".join(val or [])
            row.append("" if val is None else val)
        w.writerow(row)
    stamp = _now().strftime("%Y%m%d-%H%M")
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="telechargements-outils-{stamp}.csv"'})


# ==========================================================================
# Espace utilisateur (clients et personnel)
# ==========================================================================
@router.get("")
async def list_tools(user: dict = Depends(get_current_user)):
    """Outils visibles destinés à l'utilisateur connecté, dans l'ordre choisi."""
    q = {"visible": True, **audience_filter(user)}
    items = await db.digital_tools.find(q, {"_id": 0}).sort([("order", 1), ("created_at", 1)]).to_list(500)
    return {"items": [_public_view(t) for t in items], "is_super_admin": is_admin_account(user)}


@router.get("/{tool_id}/image")
async def tool_image(tool_id: str, user: dict = Depends(get_current_user)):
    tool = await _get_tool(tool_id)
    if not (is_admin_account(user) or _can_see(tool, user)):
        raise HTTPException(status_code=404, detail="Outil introuvable")
    path = (tool.get("image") or {}).get("path")
    if not path:
        raise HTTPException(status_code=404, detail="Aucune image pour cet outil")
    data, ct = await get_object(path)
    return Response(content=data, media_type=(tool.get("image") or {}).get("content_type") or ct,
                    headers={"Cache-Control": "private, max-age=3600"})


@router.post("/{tool_id}/lien")
async def signed_link(tool_id: str, user: dict = Depends(get_current_user)):
    """Lien de téléchargement signé, court (2 min) et à usage unique : le
    navigateur l'ouvre directement, sans charger le fichier en mémoire."""
    tool = await _get_tool(tool_id)
    if not (is_admin_account(user) or _can_see(tool, user)):
        raise HTTPException(status_code=404, detail="Outil introuvable")
    exp = _now() + timedelta(seconds=LINK_TTL_SECONDS)
    token = jwt.encode({"sub": user["id"], "tool": tool_id, "purpose": LINK_PURPOSE,
                        "jti": secrets.token_urlsafe(12), "exp": exp}, SECRET_KEY, algorithm=ALGORITHM)
    # Chemin relatif à l'adresse de l'API (…/api), à compléter par le navigateur
    return {"path": f"/outils-numeriques/{tool_id}/telecharger?t={quote(token)}", "expires_in": LINK_TTL_SECONDS}


_optional_bearer = HTTPBearer(auto_error=False)


async def _download_user(tool_id: str, t: Optional[str] = Query(None),
                         creds: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer)) -> dict:
    """Utilisateur du téléchargement : lien signé (?t=…) ou jeton de connexion
    (en-tête Authorization)."""
    if not t:
        if creds is None:
            raise HTTPException(status_code=401, detail="Connexion requise")
        return await get_current_user(creds)
    try:
        payload = jwt.decode(t, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Lien de téléchargement expiré ou invalide")
    if payload.get("purpose") != LINK_PURPOSE or payload.get("tool") != tool_id or not payload.get("jti"):
        raise HTTPException(status_code=401, detail="Lien de téléchargement invalide")
    # Usage unique : le jeton est consommé à la première utilisation
    if await db.digital_tool_links.find_one({"jti": payload["jti"]}):
        raise HTTPException(status_code=410, detail="Lien de téléchargement déjà utilisé")
    await db.digital_tool_links.insert_one({"jti": payload["jti"], "used_at": _now_iso(),
                                            "expires_at": datetime.fromtimestamp(payload["exp"], tz=timezone.utc)})
    user = await db.users.find_one({"id": payload.get("sub")}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")
    return user


async def _record_download(tool: dict, user: dict, request: Request, *, via: str, status: str,
                           error: Optional[str] = None) -> None:
    """Enregistre un téléchargement dans l'historique (jamais les identifiants FTP)."""
    doc = {
        "id": secrets.token_urlsafe(12),
        "created_at": _now_iso(),
        "tool_id": tool["id"],
        "tool_caption": tool.get("caption"),
        "tool_version": tool.get("version") or "",
        "link_masked": mask_link(tool.get("link") or ""),
        "protocol": link_protocol(tool.get("link") or ""),
        "user_id": user.get("id"),
        "user_name": user.get("full_name") or "",
        "user_email": user.get("email") or "",
        "user_roles": user.get("roles") or [],
        "user_type": user_type(user),
        "user_company": user.get("company") or "",
        # IP réelle derrière le proxy (même fonction que le lot 4)
        "ip": client_ip(request),
        "user_agent": (request.headers.get("user-agent") or "")[:300],
        "via": via,
        "status": status,
    }
    if error:
        doc["error"] = error[:200]
    try:
        await db.digital_tool_downloads.insert_one(doc)
        if status == "ok":
            await db.digital_tools.update_one({"id": tool["id"]}, {"$inc": {"download_count": 1}})
    except Exception:  # noqa: BLE001
        logger.exception("Échec enregistrement téléchargement outil %s", tool.get("id"))


# ---------- FTP : lecture en flux, en tâche non bloquante ----------
def _ftp_target(url: str) -> dict:
    """Décompose ftp://[utilisateur:mot-de-passe@]hôte[:port]/chemin.
    Comme curl, le chemin est relatif au dossier d'accueil du compte FTP
    (ftp://hôte//chemin pour un chemin absolu)."""
    parts = urlsplit(url)
    path = unquote(parts.path)
    if path.startswith("/"):
        path = path[1:]
    return {
        "tls": parts.scheme.lower() == "ftps",
        "host": parts.hostname,
        "port": parts.port or 21,
        "user": unquote(parts.username) if parts.username else "anonymous",
        "password": unquote(parts.password) if parts.password else "anonymous@",
        "path": path,
        "filename": path.rsplit("/", 1)[-1] or "fichier",
    }


def _ftp_open(target: dict):
    """Connexion + ouverture du transfert (appelé dans un thread)."""
    ftp = ftplib.FTP_TLS() if target["tls"] else ftplib.FTP()
    ftp.connect(target["host"], target["port"], timeout=FTP_TIMEOUT)
    ftp.login(target["user"], target["password"])
    if target["tls"]:
        ftp.prot_p()
    ftp.voidcmd("TYPE I")
    size = None
    try:
        size = ftp.size(target["path"])
    except ftplib.all_errors:
        size = None
    conn = ftp.transfercmd("RETR " + target["path"])
    return ftp, conn, size


def _ftp_close(ftp, conn) -> None:
    """Fermeture propre du transfert et de la session (appelé dans un thread)."""
    try:
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        ftp.voidresp()
        ftp.quit()
    except Exception:  # noqa: BLE001
        try:
            ftp.close()
        except Exception:  # noqa: BLE001
            pass


def _content_disposition(filename: str) -> str:
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "_", filename) or "fichier"
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"


@router.get("/{tool_id}/telecharger")
async def download_tool(tool_id: str, request: Request, user: dict = Depends(_download_user)):
    tool = await _get_tool(tool_id)
    # Le super-admin peut tester un outil masqué ; les autres ne voient que les leurs
    if not (is_admin_account(user) or _can_see(tool, user)):
        raise HTTPException(status_code=404, detail="Outil introuvable")
    via = "lien signé" if request.query_params.get("t") else "direct"
    link = tool.get("link") or ""
    # Lien http(s) : enregistrement puis redirection
    if link_protocol(link) == "http":
        await _record_download(tool, user, request, via=via, status="ok")
        return RedirectResponse(link, status_code=302)
    # Lien FTP : le serveur lit le fichier et le renvoie en flux
    target = _ftp_target(link)
    loop = asyncio.get_running_loop()
    try:
        ftp, conn, size = await loop.run_in_executor(None, _ftp_open, target)
    except Exception as exc:  # noqa: BLE001
        # Message sans le lien ni les identifiants
        logger.warning("FTP indisponible pour l'outil %s : %s", tool_id, type(exc).__name__)
        await _record_download(tool, user, request, via=via, status="erreur", error=type(exc).__name__)
        raise HTTPException(status_code=502, detail="Fichier momentanément indisponible sur le serveur FTP")
    await _record_download(tool, user, request, via=via, status="ok")

    async def _stream():
        try:
            while True:
                chunk = await loop.run_in_executor(None, conn.recv, FTP_CHUNK)
                if not chunk:
                    break
                yield chunk
        finally:
            await loop.run_in_executor(None, _ftp_close, ftp, conn)

    headers = {"Content-Disposition": _content_disposition(target["filename"]), "Cache-Control": "no-store"}
    if size:
        headers["Content-Length"] = str(size)
    media = mimetypes.guess_type(target["filename"])[0] or "application/octet-stream"
    return StreamingResponse(_stream(), media_type=media, headers=headers)


async def ensure_outils_indexes() -> None:
    """Index : ordre d'affichage, historique trié par date, liens à usage unique."""
    await db.digital_tools.create_index("id", unique=True)
    await db.digital_tools.create_index("order")
    await db.digital_tool_downloads.create_index([("created_at", -1)])
    await db.digital_tool_downloads.create_index([("tool_id", 1), ("created_at", -1)])
    await db.digital_tool_links.create_index("jti", unique=True)
    # Les jetons consommés sont purgés automatiquement après leur expiration
    await db.digital_tool_links.create_index("expires_at", expireAfterSeconds=0)
