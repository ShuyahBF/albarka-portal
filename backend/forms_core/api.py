"""Routes HTTP du module Formulaires, communes à tous les sites.

Le site crée un ADAPTATEUR (sous-classe de `FormsAdapter`) qui fournit ce qui
lui est propre — base Mongo (Motor), dépendances d'authentification, liste
des destinataires, envoi e-mail/WhatsApp, stockage des fichiers — puis monte
les routeurs renvoyés par `create_routers(adapter)` :

    routers = create_routers(MonAdaptateur())
    api_router.include_router(routers["staff"])    # /forms/...        (gestionnaires)
    api_router.include_router(routers["public"])   # /public/forms/... (sans connexion)
    api_router.include_router(routers["portal"])   # /me/forms/...     (espace client)

Collections Mongo (préfixe réglable, `forms` par défaut) :
    forms, forms_submissions, forms_invitations, forms_categories, forms_counters, forms_rate
"""
from __future__ import annotations

import asyncio
from collections import Counter
import io
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from .export import submissions_rows, to_csv
from .fields import field_catalog, normalize_pages, normalize_settings, public_definition, value_fields
from .stats import form_stats, in_period, invitation_stats
from .validation import validate_submission

logger = logging.getLogger("forms_core")

MAX_CATEGORIES = 12
PUBLIC_RATE_PER_HOUR = 30      # réponses/envois de fichiers par IP et par formulaire
UPLOAD_MAX_BYTES = 10 * 1024 * 1024


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_token() -> str:
    """Jeton de lien de remplissage : 32 caractères aléatoires, impossible à deviner."""
    return secrets.token_urlsafe(24)


class FormsAdapter:
    """À sous-classer par chaque site. Tout ce qui est `NotImplementedError`
    est obligatoire ; le reste a un comportement par défaut raisonnable."""

    db = None                          # base Motor
    collection_prefix = "forms"
    code_prefix = "FORM"               # numéros : FORM-0001, FORM-0002…
    staff_prefix = "/forms"
    public_prefix = "/public/forms"
    portal_prefix = "/me/forms"
    public_path = "/f"                 # page publique de remplissage : <site>/f/<jeton>
    manager_dependency: Callable = None   # dépendance FastAPI : gestionnaire des formulaires
    user_dependency: Callable = None      # dépendance FastAPI : utilisateur connecté (espace client)

    def scope_of(self, user: Dict[str, Any]) -> str:
        """Cloisonnement : un espace de formulaires par cabinet/tenant."""
        return "default"

    def user_label(self, user: Dict[str, Any]) -> str:
        return user.get("full_name") or user.get("email") or user.get("id") or ""

    def recipient_id_of(self, user: Dict[str, Any]) -> Optional[str]:
        """Identifiant de destinataire d'un utilisateur de l'espace client (None = pas client)."""
        return None

    async def list_recipients(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        """[{id, name, company, email, phone, can_email, can_whatsapp}] — pour choisir les destinataires."""
        raise NotImplementedError

    async def get_recipient(self, recipient_id: str) -> Optional[Dict[str, Any]]:
        """Destinataire complet (coordonnées NON masquées) pour l'envoi."""
        raise NotImplementedError

    async def send_invitation(self, *, recipient: Dict[str, Any], form: Dict[str, Any], url: str,
                              channels: List[str], message: str, reminder: bool) -> Dict[str, Dict[str, Any]]:
        """Envoie le lien ; renvoie {canal: {"ok": bool, "error": str|None}}."""
        raise NotImplementedError

    async def store_file(self, *, data: bytes, filename: str, content_type: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Enregistre un fichier joint ; renvoie au moins {"file_id": str}."""
        raise NotImplementedError

    async def file_url(self, file_id: str) -> Optional[str]:
        """URL temporaire de lecture d'un fichier joint (gestionnaires
        uniquement), ou None si le stockage n'en fournit pas (disque local) :
        l'écran passe alors par `read_file`."""
        return None

    async def read_file(self, file_id: str):
        """(contenu, type MIME) d'un fichier joint, ou None — repli quand
        `file_url` ne fournit pas de lien."""
        return None

    def public_base_url(self, request: Request) -> str:
        return (request.headers.get("origin") or str(request.base_url)).rstrip("/")

    async def notify_submission(self, *, form: Dict[str, Any], submission: Dict[str, Any], emails: List[str]) -> None:
        """Prévient les e-mails indiqués dans les réglages du formulaire (facultatif)."""
        return None

    async def log_event(self, *, user: Optional[Dict[str, Any]], action: str, form: Dict[str, Any], meta: Dict[str, Any]) -> None:
        return None

    # -- collections --------------------------------------------------------
    def col(self, name: str):
        return self.db[f"{self.collection_prefix}{('_' + name) if name else ''}"]


def _strip(doc: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if doc is not None:
        doc.pop("_id", None)
    return doc


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for") or ""
    return (fwd.split(",")[0].strip() or (request.client.host if request.client else "") or "")[:64]


def _is_closed(form: Dict[str, Any]) -> Optional[str]:
    """Motif de fermeture, ou None si le formulaire accepte les réponses."""
    if form.get("archived_at"):
        return "Ce formulaire n'est plus disponible."
    s = form.get("settings") or {}
    if not s.get("accepting_responses", True):
        return "Ce formulaire n'accepte plus de réponses."
    close_at = s.get("close_at")
    if close_at and str(close_at) < now_iso()[: len(str(close_at))]:
        return "Ce formulaire est clos : la date limite de réponse est dépassée."
    return None


async def ensure_indexes(adapter: FormsAdapter) -> None:
    """Crée les index Mongo utiles au module (à appeler au démarrage du site).
    Sans eux tout fonctionne, mais les recherches par jeton, les listes de
    réponses et l'anti-abus deviennent lents quand les volumes grossissent.
    Idempotent : peut être rappelé à chaque démarrage."""
    A = adapter
    # Formulaires : liste par site (scope) et lien public retrouvé par son jeton
    await A.col("").create_index([("scope", 1), ("archived_at", 1)])
    await A.col("").create_index("public_link.token", sparse=True)
    # Invitations : jeton unique (une personne = un lien), suivi par formulaire et par client
    await A.col("invitations").create_index("token", unique=True)
    await A.col("invitations").create_index([("form_id", 1), ("recipient_id", 1)])
    await A.col("invitations").create_index("recipient_id")
    # Réponses : liste d'un formulaire triée par date
    await A.col("submissions").create_index([("form_id", 1), ("created_at", -1)])
    # Anti-abus : comptage des envois récents par adresse IP
    await A.col("rate").create_index([("key", 1), ("at", 1)])


def create_routers(adapter: FormsAdapter) -> Dict[str, APIRouter]:
    A = adapter
    forms, subs, invs, cats, counters, rate = (A.col(""), A.col("submissions"), A.col("invitations"),
                                               A.col("categories"), A.col("counters"), A.col("rate"))
    staff = APIRouter(prefix=A.staff_prefix, tags=["Formulaires"])
    public = APIRouter(prefix=A.public_prefix, tags=["Formulaires — public"])
    portal = APIRouter(prefix=A.portal_prefix, tags=["Formulaires — espace client"])
    manager = Depends(A.manager_dependency)

    # ------------------------------------------------------------------ outils
    async def _get_form(fid: str, user: Dict[str, Any], *, include_archived: bool = True) -> Dict[str, Any]:
        q: Dict[str, Any] = {"id": fid, "scope": A.scope_of(user)}
        if not include_archived:
            q["archived_at"] = None
        form = await forms.find_one(q, {"_id": 0})
        if not form:
            raise HTTPException(status_code=404, detail="Formulaire introuvable.")
        return form

    async def _next_number(scope: str) -> str:
        doc = await counters.find_one_and_update({"_id": scope}, {"$inc": {"value": 1}}, upsert=True, return_document=True)
        if not isinstance(doc, dict) or "value" not in doc:  # Motor renvoie le document mis à jour si return_document=True
            doc = await counters.find_one({"_id": scope})
        return f"{A.code_prefix}-{int(doc['value']):04d}"

    async def _check_title(scope: str, title: str, exclude_id: Optional[str] = None) -> None:
        q: Dict[str, Any] = {"scope": scope, "archived_at": None,
                             "title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}}
        if exclude_id:
            q["id"] = {"$ne": exclude_id}
        if await forms.find_one(q, {"_id": 0, "id": 1}):
            raise HTTPException(status_code=409, detail=f"Un formulaire « {title} » existe déjà.")

    def _fill_url(request: Request, token: str) -> str:
        return f"{A.public_base_url(request)}{A.public_path}/{token}"

    async def _summary(form: Dict[str, Any]) -> Dict[str, Any]:
        inv = await invs.find({"form_id": form["id"]}, {"_id": 0, "opened_at": 1, "answered_at": 1, "revoked": 1}).to_list(5000)
        out = {k: form.get(k) for k in ("id", "number", "title", "description", "category_id", "created_at", "updated_at",
                                         "created_by_label", "archived_at", "views", "submissions_count", "settings")}
        out["fields_count"] = len(value_fields(form.get("pages") or []))
        out["public_link_enabled"] = bool((form.get("public_link") or {}).get("enabled"))
        out["invitations"] = invitation_stats(inv)
        out["closed_reason"] = _is_closed(form)
        return out

    # ------------------------------------------------------------------ gestionnaires : catalogue, liste, vue d'ensemble
    @staff.get("/catalog")
    async def catalog(user: dict = manager):
        return {"field_types": field_catalog()}

    @staff.get("")
    async def list_forms(archived: bool = False, user: dict = manager):
        q = {"scope": A.scope_of(user), "archived_at": {"$ne": None} if archived else None}
        items = await forms.find(q, {"_id": 0}).sort("updated_at", -1).to_list(1000)
        return {"items": [await _summary(f) for f in items]}

    @staff.get("/overview")
    async def overview(user: dict = manager):
        scope = A.scope_of(user)
        all_forms = await forms.find({"scope": scope, "archived_at": None}, {"_id": 0, "id": 1, "title": 1, "number": 1,
                                                                              "submissions_count": 1, "views": 1}).to_list(1000)
        ids = [f["id"] for f in all_forms]
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        recent_subs = await subs.find({"form_id": {"$in": ids}, "created_at": {"$gte": since}},
                                      {"_id": 0, "created_at": 1, "form_id": 1}).to_list(50000) if ids else []
        last30 = len(recent_subs)
        # Réponses par jour sur 30 jours (jours sans réponse inclus, à 0) pour le graphique global
        per_day = Counter((s.get("created_at") or "")[:10] for s in recent_subs)
        today = datetime.now(timezone.utc).date()
        days = [(today - timedelta(days=i)).isoformat() for i in range(29, -1, -1)]
        inv = await invs.find({"form_id": {"$in": ids}}, {"_id": 0, "opened_at": 1, "answered_at": 1, "revoked": 1}).to_list(20000) if ids else []
        top = sorted(all_forms, key=lambda f: -(f.get("submissions_count") or 0))[:5]
        return {"forms": len(all_forms), "submissions_total": sum(f.get("submissions_count") or 0 for f in all_forms),
                "submissions_30d": last30, "invitations": invitation_stats(inv),
                "series_30d": [{"date": d, "count": per_day.get(d, 0)} for d in days],
                "top_forms": [{"id": f["id"], "number": f.get("number"), "title": f.get("title"),
                               "submissions": f.get("submissions_count") or 0} for f in top]}

    @staff.get("/recipients")
    async def recipients(user: dict = manager):
        return {"items": await A.list_recipients(user)}

    # ------------------------------------------------------------------ catégories
    @staff.get("/categories")
    async def list_categories(user: dict = manager):
        return {"items": await cats.find({"scope": A.scope_of(user)}, {"_id": 0}).sort("sort_order", 1).to_list(100)}

    @staff.post("/categories", status_code=201)
    async def create_category(payload: Dict[str, Any] = Body(...), user: dict = manager):
        scope = A.scope_of(user)
        name = str(payload.get("name") or "").strip()[:60]
        if not name:
            raise HTTPException(status_code=400, detail="Nom de catégorie requis.")
        if await cats.count_documents({"scope": scope}) >= MAX_CATEGORIES:
            raise HTTPException(status_code=409, detail=f"{MAX_CATEGORIES} catégories au plus.")
        if await cats.find_one({"scope": scope, "name": {"$regex": f"^{re.escape(name)}$", "$options": "i"}}):
            raise HTTPException(status_code=409, detail="Cette catégorie existe déjà.")
        doc = {"id": secrets.token_hex(6), "scope": scope, "name": name,
               "color": str(payload.get("color") or "#0F6B4A")[:20],
               "sort_order": await cats.count_documents({"scope": scope}), "created_at": now_iso()}
        await cats.insert_one(dict(doc))
        return doc

    @staff.put("/categories/{cid}")
    async def update_category(cid: str, payload: Dict[str, Any] = Body(...), user: dict = manager):
        upd = {}
        if payload.get("name"):
            upd["name"] = str(payload["name"]).strip()[:60]
        if payload.get("color"):
            upd["color"] = str(payload["color"])[:20]
        if "sort_order" in payload:
            upd["sort_order"] = int(payload.get("sort_order") or 0)
        res = await cats.update_one({"id": cid, "scope": A.scope_of(user)}, {"$set": upd})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Catégorie introuvable.")
        return {"ok": True}

    @staff.delete("/categories/{cid}")
    async def delete_category(cid: str, user: dict = manager):
        scope = A.scope_of(user)
        await cats.delete_one({"id": cid, "scope": scope})
        await forms.update_many({"scope": scope, "category_id": cid}, {"$set": {"category_id": None}})
        return {"ok": True}

    # ------------------------------------------------------------------ création / modification
    @staff.post("", status_code=201)
    async def create_form(payload: Dict[str, Any] = Body(...), user: dict = manager):
        scope = A.scope_of(user)
        title = str(payload.get("title") or "").strip()[:200]
        if not title:
            raise HTTPException(status_code=400, detail="Titre requis.")
        await _check_title(scope, title)
        now = now_iso()
        form = {
            "id": secrets.token_hex(8), "scope": scope, "number": await _next_number(scope),
            "title": title, "description": str(payload.get("description") or "").strip()[:2000],
            "category_id": payload.get("category_id") or None,
            "pages": normalize_pages(payload.get("pages")), "settings": normalize_settings(payload.get("settings")),
            "public_link": {"enabled": False, "token": None},
            "views": 0, "submissions_count": 0,
            "created_by_id": user.get("id"), "created_by_label": A.user_label(user),
            "created_at": now, "updated_at": now, "archived_at": None,
        }
        await forms.insert_one(dict(form))
        await A.log_event(user=user, action="form_created", form=form, meta={})
        return form

    @staff.get("/{fid}")
    async def get_form(fid: str, user: dict = manager):
        form = await _get_form(fid, user)
        form["closed_reason"] = _is_closed(form)
        return form

    @staff.put("/{fid}")
    async def update_form(fid: str, payload: Dict[str, Any] = Body(...), user: dict = manager):
        form = await _get_form(fid, user)
        upd: Dict[str, Any] = {"updated_at": now_iso(), "updated_by_label": A.user_label(user)}
        if "title" in payload:
            title = str(payload.get("title") or "").strip()[:200]
            if not title:
                raise HTTPException(status_code=400, detail="Titre requis.")
            await _check_title(form["scope"], title, exclude_id=fid)
            upd["title"] = title
        if "description" in payload:
            upd["description"] = str(payload.get("description") or "").strip()[:2000]
        if "category_id" in payload:
            upd["category_id"] = payload.get("category_id") or None
        if "pages" in payload:
            upd["pages"] = normalize_pages(payload.get("pages"))
        if "settings" in payload:
            upd["settings"] = normalize_settings(payload.get("settings"))
        await forms.update_one({"id": fid}, {"$set": upd})
        return await _get_form(fid, user)

    @staff.post("/{fid}/duplicate", status_code=201)
    async def duplicate_form(fid: str, user: dict = manager):
        src = await _get_form(fid, user)
        base = f"{src['title']} (copie)"
        title, n = base, 2
        while await forms.find_one({"scope": src["scope"], "archived_at": None,
                                    "title": {"$regex": f"^{re.escape(title)}$", "$options": "i"}}, {"_id": 0, "id": 1}):
            title, n = f"{base} {n}", n + 1
        return await create_form({"title": title, "description": src.get("description"), "category_id": src.get("category_id"),
                                  "pages": src.get("pages"), "settings": src.get("settings")}, user=user)

    @staff.delete("/{fid}")
    async def archive_form(fid: str, user: dict = manager):
        """Archive (les réponses sont conservées ; le formulaire peut être restauré)."""
        form = await _get_form(fid, user)
        await forms.update_one({"id": fid}, {"$set": {"archived_at": now_iso(), "public_link.enabled": False}})
        await A.log_event(user=user, action="form_archived", form=form, meta={})
        return {"ok": True}

    @staff.post("/{fid}/restore")
    async def restore_form(fid: str, user: dict = manager):
        form = await _get_form(fid, user)
        await _check_title(form["scope"], form["title"], exclude_id=fid)
        await forms.update_one({"id": fid}, {"$set": {"archived_at": None}})
        return {"ok": True}

    # ------------------------------------------------------------------ réponses
    @staff.get("/{fid}/submissions")
    async def list_submissions(fid: str, date_from: Optional[str] = None, date_to: Optional[str] = None,
                               user: dict = manager):
        form = await _get_form(fid, user)
        items = await subs.find({"form_id": fid}, {"_id": 0}).sort("created_at", -1).to_list(5000)
        items = [s for s in items if in_period(s.get("created_at"), date_from, date_to)]
        return {"form": {k: form.get(k) for k in ("id", "number", "title", "pages")}, "items": items, "total": len(items)}

    @staff.delete("/{fid}/submissions/{sid}")
    async def delete_submission(fid: str, sid: str, user: dict = manager):
        form = await _get_form(fid, user)
        sub = await subs.find_one({"id": sid, "form_id": fid}, {"_id": 0})
        if not sub:
            raise HTTPException(status_code=404, detail="Réponse introuvable.")
        await subs.delete_one({"id": sid})
        await forms.update_one({"id": fid}, {"$inc": {"submissions_count": -1}})
        if sub.get("invitation_id"):
            await invs.update_one({"id": sub["invitation_id"]}, {"$set": {"answered_at": None, "submission_id": None}})
        await A.log_event(user=user, action="form_submission_deleted", form=form, meta={"submission_id": sid})
        return {"ok": True}

    async def _check_file(fid: str, file_id: str, user: Dict[str, Any]) -> None:
        """Le fichier doit appartenir à une réponse de CE formulaire."""
        await _get_form(fid, user)
        async for s in subs.find({"form_id": fid}, {"_id": 0, "data": 1}):
            if any(isinstance(v, dict) and v.get("file_id") == file_id for v in (s.get("data") or {}).values()):
                return
        raise HTTPException(status_code=404, detail="Fichier introuvable.")

    @staff.get("/{fid}/files/{file_id}/content")
    async def file_content(fid: str, file_id: str, user: dict = manager):
        """Contenu du fichier (repli quand le stockage ne fournit pas de lien temporaire)."""
        await _check_file(fid, file_id, user)
        got = await A.read_file(file_id)
        if not got:
            raise HTTPException(status_code=404, detail="Fichier introuvable.")
        data, ctype = got[0], (got[1] if len(got) > 1 else None) or "application/octet-stream"
        return Response(content=data, media_type=ctype)

    @staff.get("/{fid}/files/{file_id}")
    async def open_file(fid: str, file_id: str, user: dict = manager):
        """Fichier joint d'une réponse de CE formulaire : lien temporaire, ou
        {"url": null} si l'écran doit lire /content (stockage local)."""
        await _check_file(fid, file_id, user)
        url = await A.file_url(file_id)
        if not url:
            return {"url": None}
        # Lien temporaire renvoyé en JSON : l'écran l'ouvre dans un nouvel onglet
        # (une redirection suivie par le navigateur serait bloquée si le stockage
        # est sur un autre domaine).
        return {"url": url}

    @staff.get("/{fid}/stats")
    async def stats(fid: str, date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = manager):
        form = await _get_form(fid, user)
        items = await subs.find({"form_id": fid}, {"_id": 0}).to_list(20000)
        items = [s for s in items if in_period(s.get("created_at"), date_from, date_to)]
        inv = await invs.find({"form_id": fid}, {"_id": 0}).to_list(20000)
        return form_stats(form.get("pages") or [], items, views=form.get("views") or 0, invitations=inv)

    @staff.get("/{fid}/export.csv")
    async def export_csv(fid: str, date_from: Optional[str] = None, date_to: Optional[str] = None, user: dict = manager):
        form = await _get_form(fid, user)
        items = await subs.find({"form_id": fid}, {"_id": 0}).to_list(20000)
        items = [s for s in items if in_period(s.get("created_at"), date_from, date_to)]
        body = to_csv(submissions_rows(form.get("pages") or [], items))
        return Response(content=body, media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{form.get("number") or "formulaire"}-reponses.csv"'})

    # ------------------------------------------------------------------ envoi aux destinataires et suivi
    @staff.get("/{fid}/invitations")
    async def list_invitations(fid: str, request: Request, user: dict = manager):
        await _get_form(fid, user)
        items = await invs.find({"form_id": fid}, {"_id": 0}).sort("created_at", -1).to_list(5000)
        for i in items:
            i["status"] = "revoked" if i.get("revoked") else "answered" if i.get("answered_at") else "opened" if i.get("opened_at") else "sent"
            i["url"] = _fill_url(request, i["token"])
        return {"items": items, "stats": invitation_stats(items)}

    async def _deliver(inv: Dict[str, Any], form: Dict[str, Any], url: str, channels: List[str], message: str,
                       reminder: bool) -> Dict[str, Any]:
        recipient = await A.get_recipient(inv["recipient_id"])
        if not recipient:
            result = {c: {"ok": False, "error": "Destinataire introuvable"} for c in channels}
        else:
            try:
                result = await A.send_invitation(recipient=recipient, form=form, url=url, channels=channels,
                                                 message=message, reminder=reminder)
            except Exception as exc:  # noqa: BLE001 — un échec d'envoi ne doit pas bloquer les autres
                logger.exception("[forms] envoi de l'invitation %s échoué", inv.get("id"))
                result = {c: {"ok": False, "error": str(exc)[:200]} for c in channels}
        entry = {"at": now_iso(), "reminder": reminder, "results": result}
        await invs.update_one({"id": inv["id"]}, {"$push": {"deliveries": entry},
                                                  "$set": {"last_sent_at": entry["at"]}})
        return result

    @staff.post("/{fid}/invitations")
    async def send_invitations(fid: str, request: Request, payload: Dict[str, Any] = Body(...), user: dict = manager):
        """Envoie le lien de remplissage à des destinataires choisis. Un même
        destinataire garde son lien (pas de doublon s'il est renvoyé)."""
        form = await _get_form(fid, user, include_archived=False)
        ids = [str(x) for x in (payload.get("recipient_ids") or []) if x][:1000]
        channels = [c for c in (payload.get("channels") or ["email"]) if c in ("email", "whatsapp")]
        if not ids:
            raise HTTPException(status_code=400, detail="Choisissez au moins un destinataire.")
        if not channels:
            raise HTTPException(status_code=400, detail="Choisissez au moins un canal d'envoi (e-mail ou WhatsApp).")
        message = str(payload.get("message") or "").strip()[:1000]
        summary = {"sent": 0, "failed": 0, "results": []}
        for rid in dict.fromkeys(ids):
            inv = await invs.find_one({"form_id": fid, "recipient_id": rid, "revoked": {"$ne": True}}, {"_id": 0})
            if not inv:
                recipient = await A.get_recipient(rid)
                inv = {"id": secrets.token_hex(8), "form_id": fid, "scope": form["scope"], "token": new_token(),
                       "recipient_id": rid, "recipient_name": (recipient or {}).get("name") or "",
                       "recipient_email": (recipient or {}).get("email") or "",
                       "created_at": now_iso(), "created_by_label": A.user_label(user),
                       "opened_at": None, "answered_at": None, "submission_id": None, "revoked": False, "deliveries": []}
                await invs.insert_one(dict(inv))
            result = await _deliver(inv, form, _fill_url(request, inv["token"]), channels, message, reminder=False)
            ok = any(r.get("ok") for r in result.values())
            summary["sent" if ok else "failed"] += 1
            summary["results"].append({"recipient_id": rid, "name": inv.get("recipient_name"), "results": result})
        await A.log_event(user=user, action="form_sent", form=form, meta={"recipients": len(ids), "channels": channels})
        return summary

    @staff.post("/{fid}/invitations/remind")
    async def remind(fid: str, request: Request, payload: Dict[str, Any] = Body(default={}), user: dict = manager):
        """Relance tous les destinataires qui n'ont pas encore répondu."""
        form = await _get_form(fid, user, include_archived=False)
        channels = [c for c in (payload.get("channels") or ["email"]) if c in ("email", "whatsapp")] or ["email"]
        message = str(payload.get("message") or "").strip()[:1000]
        pending = await invs.find({"form_id": fid, "revoked": {"$ne": True}, "answered_at": None}, {"_id": 0}).to_list(5000)
        sent = failed = 0
        for inv in pending:
            result = await _deliver(inv, form, _fill_url(request, inv["token"]), channels, message, reminder=True)
            if any(r.get("ok") for r in result.values()):
                sent += 1
            else:
                failed += 1
        return {"reminded": sent, "failed": failed, "pending": len(pending)}

    @staff.delete("/{fid}/invitations/{iid}")
    async def revoke_invitation(fid: str, iid: str, user: dict = manager):
        await _get_form(fid, user)
        res = await invs.update_one({"id": iid, "form_id": fid}, {"$set": {"revoked": True, "revoked_at": now_iso()}})
        if not res.matched_count:
            raise HTTPException(status_code=404, detail="Invitation introuvable.")
        return {"ok": True}

    # ------------------------------------------------------------------ lien public (non-clients)
    @staff.post("/{fid}/public-link")
    async def public_link(fid: str, request: Request, payload: Dict[str, Any] = Body(default={}), user: dict = manager):
        """Active/désactive le lien public ; `rotate: true` crée un nouveau lien
        (l'ancien cesse de fonctionner)."""
        form = await _get_form(fid, user, include_archived=False)
        link = dict(form.get("public_link") or {})
        enabled = bool(payload.get("enabled", True))
        if payload.get("rotate") or (enabled and not link.get("token")):
            link["token"] = new_token()
        link["enabled"] = enabled
        await forms.update_one({"id": fid}, {"$set": {"public_link": link}})
        return {"enabled": enabled, "token": link.get("token"),
                "url": _fill_url(request, link["token"]) if link.get("token") else None}

    @staff.get("/{fid}/qr.png")
    async def qr_png(fid: str, request: Request, token: Optional[str] = Query(None), user: dict = manager):
        """QR code du lien public (ou d'un lien d'invitation de ce formulaire)."""
        form = await _get_form(fid, user)
        tok = token or (form.get("public_link") or {}).get("token")
        if not tok or (token and token != (form.get("public_link") or {}).get("token")
                       and not await invs.find_one({"form_id": fid, "token": token}, {"_id": 0, "id": 1})):
            raise HTTPException(status_code=404, detail="Lien introuvable.")
        try:
            import qrcode
        except ImportError:
            raise HTTPException(status_code=501, detail="Génération de QR code indisponible sur ce serveur.")
        img = qrcode.make(_fill_url(request, tok), box_size=8, border=2)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return Response(content=buf.getvalue(), media_type="image/png")

    # ------------------------------------------------------------------ public (sans connexion)
    async def _resolve(token: str) -> Dict[str, Any]:
        """Jeton → {form, invitation|None, source}. 404 si inconnu ou désactivé."""
        if not token or len(token) > 100:
            raise HTTPException(status_code=404, detail="Lien invalide.")
        inv = await invs.find_one({"token": token}, {"_id": 0})
        if inv:
            if inv.get("revoked"):
                raise HTTPException(status_code=410, detail="Ce lien a été désactivé.")
            form = await forms.find_one({"id": inv["form_id"]}, {"_id": 0})
            if form:
                return {"form": form, "invitation": inv, "source": "invitation"}
        form = await forms.find_one({"public_link.token": token}, {"_id": 0})
        if form and (form.get("public_link") or {}).get("enabled"):
            return {"form": form, "invitation": None, "source": "public"}
        raise HTTPException(status_code=404, detail="Lien invalide ou désactivé.")

    async def _rate_limited(request: Request, form_id: str, kind: str) -> bool:
        ip = _client_ip(request)
        since = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        key = f"{kind}:{form_id}:{ip}"
        n = await rate.count_documents({"key": key, "at": {"$gte": since}})
        if n >= PUBLIC_RATE_PER_HOUR * (3 if kind == "upload" else 1):
            return True
        await rate.insert_one({"key": key, "at": now_iso()})
        return False

    @public.get("/{token}")
    async def public_get(token: str):
        ctx = await _resolve(token)
        form, inv = ctx["form"], ctx["invitation"]
        closed = _is_closed(form)
        out = {"form": public_definition(form), "source": ctx["source"], "closed_reason": closed}
        if inv:
            out["recipient"] = {"name": inv.get("recipient_name"), "email": inv.get("recipient_email")}
            out["already_answered"] = bool(inv.get("answered_at"))
            out["can_edit"] = bool((form.get("settings") or {}).get("allow_edit"))
            if inv.get("answered_at") and out["can_edit"] and inv.get("submission_id"):
                prev = await subs.find_one({"id": inv["submission_id"]}, {"_id": 0, "data": 1})
                out["previous_data"] = (prev or {}).get("data") or {}
            if not inv.get("opened_at"):
                await invs.update_one({"id": inv["id"]}, {"$set": {"opened_at": now_iso()}})
        if not closed:
            await forms.update_one({"id": form["id"]}, {"$inc": {"views": 1}})
        return out

    @public.post("/{token}/upload")
    async def public_upload(token: str, request: Request, field_id: str = Form(...), file: UploadFile = File(...)):
        ctx = await _resolve(token)
        form = ctx["form"]
        if _is_closed(form):
            raise HTTPException(status_code=403, detail=_is_closed(form))
        field = next((f for f in value_fields(form.get("pages") or []) if f["id"] == field_id), None)
        if not field or field["type"] not in ("file", "signature"):
            raise HTTPException(status_code=400, detail="Champ de fichier inconnu.")
        if await _rate_limited(request, form["id"], "upload"):
            raise HTTPException(status_code=429, detail="Trop d'envois depuis cette connexion. Réessayez plus tard.")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=400, detail="Fichier vide.")
        if len(data) > UPLOAD_MAX_BYTES:
            raise HTTPException(status_code=413, detail=f"Fichier trop volumineux ({UPLOAD_MAX_BYTES // (1024 * 1024)} Mo au plus).")
        ctype = (file.content_type or "application/octet-stream").lower()
        name = re.sub(r"[^\w.\- ]", "_", file.filename or "fichier")[:120]
        if field["type"] == "signature" and ctype != "image/png":
            raise HTTPException(status_code=400, detail="Signature invalide.")
        accept = [a.strip().lower() for a in (field.get("accept") or "").split(",") if a.strip()]
        if accept and not any((a.startswith(".") and name.lower().endswith(a)) or (a.endswith("/*") and ctype.startswith(a[:-1]))
                              or a == ctype for a in accept):
            raise HTTPException(status_code=400, detail=f"Type de fichier non accepté (attendu : {field.get('accept')}).")
        stored = await A.store_file(data=data, filename=name, content_type=ctype,
                                    meta={"form_id": form["id"], "field_id": field_id, "source": ctx["source"],
                                          "invitation_id": (ctx["invitation"] or {}).get("id")})
        return {"file_id": stored["file_id"], "filename": name, "size": len(data), "content_type": ctype}

    @public.post("/{token}/submit")
    async def public_submit(token: str, request: Request, payload: Dict[str, Any] = Body(...)):
        ctx = await _resolve(token)
        form, inv = ctx["form"], ctx["invitation"]
        closed = _is_closed(form)
        if closed:
            raise HTTPException(status_code=403, detail=closed)
        settings = form.get("settings") or {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        if payload.get("website"):  # champ piège invisible : un robot le remplit, un humain non
            return {"ok": True, "message": settings.get("confirmation_message")}
        if await _rate_limited(request, form["id"], "submit"):
            raise HTTPException(status_code=429, detail="Trop de réponses depuis cette connexion. Réessayez plus tard.")
        clean, errors = validate_submission(form.get("pages") or [], data)
        name = str(payload.get("respondent_name") or "").strip()[:120]
        email = str(payload.get("respondent_email") or "").strip().lower()[:200]
        if inv:
            name, email = inv.get("recipient_name") or name, inv.get("recipient_email") or email
        elif settings.get("respondent_info") == "required":
            if not name:
                errors["_respondent_name"] = "Indiquez votre nom."
            if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email or ""):
                errors["_respondent_email"] = "Indiquez une adresse e-mail valide."
        if errors:
            raise HTTPException(status_code=422, detail={"message": "Certaines réponses sont à corriger.", "errors": errors})
        now = now_iso()
        # Invitation déjà utilisée : modification si autorisée, sinon refus.
        if inv and inv.get("answered_at") and inv.get("submission_id"):
            if not settings.get("allow_edit"):
                raise HTTPException(status_code=409, detail="Vous avez déjà répondu à ce formulaire. Merci !")
            await subs.update_one({"id": inv["submission_id"]}, {"$set": {"data": clean, "updated_at": now},
                                                                 "$inc": {"revisions": 1}})
            return {"ok": True, "updated": True, "message": settings.get("confirmation_message")}
        if not inv and not settings.get("public_multiple", True) and email:
            if await subs.find_one({"form_id": form["id"], "respondent_email": email}, {"_id": 0, "id": 1}):
                raise HTTPException(status_code=409, detail="Une réponse a déjà été enregistrée avec cette adresse e-mail.")
        sub = {"id": secrets.token_hex(8), "form_id": form["id"], "scope": form["scope"], "form_number": form.get("number"),
               "data": clean, "source": ctx["source"], "invitation_id": (inv or {}).get("id"),
               "recipient_id": (inv or {}).get("recipient_id"), "respondent_name": name, "respondent_email": email,
               "ip": _client_ip(request), "user_agent": (request.headers.get("user-agent") or "")[:200],
               "created_at": now, "updated_at": now, "revisions": 0}
        await subs.insert_one(dict(sub))
        await forms.update_one({"id": form["id"]}, {"$inc": {"submissions_count": 1}, "$set": {"last_submission_at": now}})
        if inv:
            await invs.update_one({"id": inv["id"]}, {"$set": {"answered_at": now, "submission_id": sub["id"]}})
        if settings.get("notify_emails"):
            async def _notify():
                try:
                    await A.notify_submission(form=form, submission=sub, emails=settings["notify_emails"])
                except Exception:  # noqa: BLE001
                    logger.exception("[forms] notification de réponse échouée")
            asyncio.get_event_loop().create_task(_notify())
        return {"ok": True, "id": sub["id"], "message": settings.get("confirmation_message")}

    # ------------------------------------------------------------------ espace client : formulaires reçus
    if A.user_dependency is not None:
        @portal.get("")
        async def my_forms(request: Request, user: dict = Depends(A.user_dependency)):
            rid = A.recipient_id_of(user)
            if not rid:
                return {"items": []}
            items = await invs.find({"recipient_id": rid, "revoked": {"$ne": True}}, {"_id": 0}).sort("created_at", -1).to_list(500)
            out = []
            for inv in items:
                form = await forms.find_one({"id": inv["form_id"]}, {"_id": 0, "title": 1, "number": 1, "description": 1,
                                                                    "settings": 1, "archived_at": 1})
                if not form or form.get("archived_at"):
                    continue
                out.append({"id": inv["id"], "title": form.get("title"), "number": form.get("number"),
                            "description": form.get("description"), "received_at": inv.get("created_at"),
                            "answered_at": inv.get("answered_at"), "closed_reason": _is_closed(form),
                            "can_edit": bool((form.get("settings") or {}).get("allow_edit")),
                            "path": f"{A.public_path}/{inv['token']}"})
            return {"items": out}

    return {"staff": staff, "public": public, "portal": portal}
