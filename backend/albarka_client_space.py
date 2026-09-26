"""Espace client — documents mis à disposition par le cabinet.

Le cabinet fait souvent ses factures, rapports, attestations… dans un autre
logiciel. Ce module lui permet de les déposer (fichier ou scan, SANS analyse
OCR) dans l'espace d'un client, et de mettre à disposition les factures,
proformas et reçus faits dans la Caisse du portail. Le client ne voit que ce
qui le concerne ET que le cabinet a rendu visible, et il est prévenu par
WhatsApp (repli e-mail) avec des textes réglables dans Paramètres.

Routes (préfixe /api) :
  /client-space/...   côté cabinet (CLIENT_SPACE_ROLES ; modules : CLIENT_MANAGE_ROLES)
  /me/space           côté client (ses documents visibles + téléchargement)

Collection : `client_documents` (fichiers dans le stockage Albarka, kind
"client_space", référencés aussi dans `stored_objects`).
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import datetime, timezone
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response

import albarka_storage
from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_roles
from albarka_models import (
    CLIENT_MANAGE_ROLES, CLIENT_PORTAL_MODULES, CLIENT_SPACE_ROLES,
    can_encaisser, client_modules, is_client, whatsapp_number_of,
)
from albarka_notifications import send_email, send_whatsapp, send_whatsapp_template, wa_window_state
from db import db

logger = logging.getLogger("albarka.client_space")

router = APIRouter(prefix="/client-space", tags=["Espace client — cabinet"])
me_router = APIRouter(prefix="/me/space", tags=["Espace client — client"])

# Catégories proposées au dépôt (les 3 premières sont aussi celles de la Caisse).
CATEGORIES: Dict[str, str] = {
    "facture": "Facture",
    "proforma": "Proforma",
    "recu": "Reçu",
    "rapport": "Rapport",
    "declaration": "Déclaration fiscale",
    "attestation": "Attestation / certificat",
    "contrat": "Contrat",
    "courrier": "Courrier",
    "autre": "Autre document",
}
MAX_FILES = 10
MAX_FILE_BYTES = 20 * 1024 * 1024  # 20 Mo, comme les pièces
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "doc", "docx", "xls", "xlsx", "txt", "csv"}
DEFAULT_BASE_URL = "https://albarka-bf.com"
CLIENT_PAGE_PATH = "/portal/documents-cabinet"

# ---------------------------------------------------------------- modèles de message
# Variables utilisables dans les textes (Paramètres → Notifications).
TEMPLATE_VARIABLES = {
    "client": "Nom du client",
    "entreprise": "Entreprise du client",
    "cabinet": "Nom du cabinet",
    "nombre": "Nombre de documents",
    "liste": "Liste des documents (une ligne par document)",
    "titre": "Titre du 1er document",
    "categorie": "Catégorie du 1er document",
    "reference": "Référence / numéro du 1er document",
    "montant": "Montant du 1er document",
    "lien": "Lien vers l'espace client",
}
# Un texte par catégorie + "default" (plusieurs catégories dans un même envoi,
# ou catégorie sans texte propre).
TEMPLATE_KEYS = ["default", *CATEGORIES]
DEFAULT_TEMPLATES: Dict[str, str] = {
    "default": ("*{cabinet}*\nBonjour {client},\n\nVous avez reçu {nombre} nouveau(x) document(s) "
                "dans votre espace client :\n{liste}\n\nConsultez-les ici : {lien}"),
    "facture": ("*{cabinet}*\nBonjour {client},\n\nUne nouvelle facture est disponible dans votre espace client :\n"
                "{liste}\n\nConsultez-la ici : {lien}"),
    "proforma": ("*{cabinet}*\nBonjour {client},\n\nUne facture proforma est disponible dans votre espace client :\n"
                 "{liste}\n\nConsultez-la ici : {lien}"),
    "recu": ("*{cabinet}*\nBonjour {client},\n\nMerci pour votre règlement. Votre reçu est disponible "
             "dans votre espace client :\n{liste}\n\nConsultez-le ici : {lien}"),
    "rapport": ("*{cabinet}*\nBonjour {client},\n\nUn nouveau rapport est disponible dans votre espace client :\n"
                "{liste}\n\nConsultez-le ici : {lien}"),
}
_VAR_RE = re.compile(r"\{([a-z_]+)\}")


def render_template(template: str, values: Dict[str, str]) -> str:
    """Remplace {variable} par sa valeur ; une accolade inconnue reste telle quelle
    (pas d'erreur si le texte contient d'autres accolades)."""
    return _VAR_RE.sub(lambda m: str(values.get(m.group(1), m.group(0))), template)


def _fmt_amount(amount: Any, currency: str = "FCFA") -> str:
    try:
        return f"{int(round(float(amount))):,} {currency}".replace(",", " ")
    except (TypeError, ValueError):
        return ""


def _item_line(it: Dict[str, Any]) -> str:
    """Ligne de la variable {liste} : « • Facture — Honoraires (FAC-…) — 150 000 FCFA »."""
    parts = [f"• {CATEGORIES.get(it['category'], 'Document')} — {it.get('title') or 'Document'}"]
    if it.get("reference"):
        parts[0] += f" ({it['reference']})"
    if it.get("amount"):
        parts.append(_fmt_amount(it["amount"], "FCFA" if (it.get("currency") or "XOF") == "XOF" else it["currency"]))
    return " — ".join(parts)


def template_values(*, client: Dict[str, Any], items: List[Dict[str, Any]], cabinet: str, link: str) -> Dict[str, str]:
    """Valeurs des variables pour un envoi (items = documents du même envoi)."""
    first = items[0] if items else {}
    return {
        "client": client.get("full_name") or client.get("email") or "",
        "entreprise": client.get("company") or client.get("full_name") or "",
        "cabinet": cabinet,
        "nombre": str(len(items)),
        "liste": "\n".join(_item_line(i) for i in items),
        "titre": first.get("title") or "",
        "categorie": CATEGORIES.get(first.get("category"), ""),
        "reference": first.get("reference") or "",
        "montant": _fmt_amount(first["amount"]) if first.get("amount") else "",
        "lien": link,
    }


def pick_template(settings: Dict[str, Any], items: List[Dict[str, Any]]) -> str:
    """Texte réglé pour la catégorie (si tous les documents sont de la même),
    sinon celui par défaut ; à défaut de réglage, le texte fourni d'origine."""
    custom = settings.get("client_docs_templates") or {}
    cats = {i.get("category") for i in items}
    if len(cats) == 1:
        cat = next(iter(cats))
        if (custom.get(cat) or "").strip():
            return custom[cat]
        if (custom.get("default") or "").strip():
            return custom["default"]
        return DEFAULT_TEMPLATES.get(cat, DEFAULT_TEMPLATES["default"])
    return (custom.get("default") or "").strip() or DEFAULT_TEMPLATES["default"]


def _portal_link(request: Optional[Request] = None) -> str:
    """Lien vers la page client ; toujours en https (garde-fous e-mail)."""
    origin = ((request.headers.get("origin") if request else "") or "").rstrip("/")
    base = origin if origin.startswith("https://") else DEFAULT_BASE_URL
    return base + CLIENT_PAGE_PATH


def _notif_email_html(*, cabinet: str, client_name: str, lines: List[str], link: str) -> str:
    """E-mail de repli (même style que les autres e-mails du cabinet ; bouton
    sans nom de domaine pour respecter les garde-fous)."""
    items = "".join(f'<li style="margin:4px 0;">{escape(l.lstrip("• "))}</li>' for l in lines)
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBFAF4;padding:24px 0;font-family:Arial,sans-serif;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="background:#0B1912;padding:24px 32px;color:#ffffff;">
        <div style="font-size:12px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">{escape(cabinet)}</div>
        <div style="font-size:22px;margin-top:4px;font-family:Georgia,serif;">Nouveaux documents disponibles</div>
      </td></tr>
      <tr><td style="padding:32px;color:#0F172A;">
        <p style="margin:0 0 12px 0;">Bonjour {escape(client_name)},</p>
        <p style="margin:0 0 12px 0;">Le cabinet a mis à votre disposition dans votre espace client :</p>
        <ul style="margin:0 0 16px 18px;padding:0;">{items}</ul>
        <p style="margin:24px 0;text-align:center;">
          <a href="{escape(link)}" style="background:#0F6B4A;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;display:inline-block;">Ouvrir mon espace client</a>
        </p>
        <p style="margin:24px 0 0 0;font-size:13px;color:#64748B;">Ce message est envoyé automatiquement par {escape(cabinet)}.</p>
      </td></tr>
    </table>
  </td></tr>
</table>
"""


async def notify_client(client: Dict[str, Any], items: List[Dict[str, Any]], *, link: str) -> Dict[str, Any]:
    """Prévient le client : notification push sur ses appareils abonnés (si
    activée), PUIS WhatsApp / e-mail comme avant. Le résultat indique en plus
    `push` = nombre d'appareils atteints ; ok si au moins un canal a abouti."""
    settings = await get_settings_doc()
    push = {"sent": 0, "failed": 0, "devices": 0}
    allowed = (settings.get("client_docs_notify_enabled", True) and client.get("can_receive_notifications") is not False
               and client.get("is_active", True))
    if allowed and settings.get("client_docs_push_enabled", True):
        try:
            from albarka_push import send_push_to_user
            cabinet = settings.get("cabinet_name") or "Cabinet ALBARKA"
            values = template_values(client=client, items=items, cabinet=cabinet, link=link)
            title = (f"{values['categorie']} disponible" if len(items) == 1 else f"{len(items)} nouveaux documents")
            push = await send_push_to_user(client["id"], title=f"{title} — {cabinet}",
                                           body=values["liste"].replace("• ", ""), url=CLIENT_PAGE_PATH, tag="client-docs")
        except Exception:  # noqa: BLE001 — le push ne doit jamais empêcher WhatsApp / e-mail
            logger.exception("[push] échec de la notification push")
    result = await _notify_whatsapp_or_email(client, items, link=link)
    result["push"] = push["sent"]
    if not result["ok"] and push["sent"]:
        result.update(ok=True, channel="push")
    return result


async def _notify_whatsapp_or_email(client: Dict[str, Any], items: List[Dict[str, Any]], *, link: str) -> Dict[str, Any]:
    """Prévient le client des documents qu'il vient de recevoir.
    1. WhatsApp : message libre (texte réglé) si la fenêtre de 24 h est
       ouverte ; sinon le modèle Meta réglé, s'il y en a un ;
    2. repli e-mail si WhatsApp est impossible (réglable).
    Retourne {ok, channel, error, at} (enregistré sur chaque document)."""
    now = datetime.now(timezone.utc).isoformat()
    settings = await get_settings_doc()
    if not settings.get("client_docs_notify_enabled", True):
        return {"ok": False, "channel": None, "error": "Notifications désactivées dans les paramètres", "at": now}
    if client.get("can_receive_notifications") is False or not client.get("is_active", True):
        return {"ok": False, "channel": None, "error": "Le client a refusé les notifications", "at": now}
    cabinet = settings.get("cabinet_name") or "Cabinet ALBARKA"
    values = template_values(client=client, items=items, cabinet=cabinet, link=link)
    text = render_template(pick_template(settings, items), values)

    wa_error = None
    phone = whatsapp_number_of(client) or ""
    if phone.startswith("+"):
        window = await wa_window_state(phone)
        tpl_name = (settings.get("client_docs_wa_template_name") or "").strip()
        if window is not True and tpl_name:
            # Hors fenêtre (ou inconnue) : seul un modèle approuvé par Meta est remis.
            params = [values.get(p.strip(), "") for p in (settings.get("client_docs_wa_template_params") or "").split(",") if p.strip()]
            r = await send_whatsapp_template(to_phone=phone, template_name=tpl_name,
                                             language=settings.get("client_docs_wa_template_lang") or "fr", body_params=params)
            if r.get("ok"):
                return {"ok": True, "channel": "whatsapp_template", "error": None, "at": now}
            wa_error = f"Modèle WhatsApp refusé : {r.get('error')}"[:300]
        else:
            r = await send_whatsapp(to_phone=phone, message=text)
            if r.get("ok") and window is not False:
                return {"ok": True, "channel": "whatsapp", "error": None, "at": now}
            wa_error = ("Hors fenêtre de 24 h WhatsApp et aucun modèle Meta réglé : message probablement non remis"
                        if r.get("ok") or r.get("outside_24h_window") else f"WhatsApp : {r.get('error')}")[:300]
    else:
        wa_error = "Pas de numéro WhatsApp au format +226…"

    # Repli e-mail
    if settings.get("client_docs_email_fallback", True) and client.get("email"):
        try:
            sent = await send_email(
                to=client["email"], subject=f"Nouveaux documents disponibles — {cabinet}",
                html=_notif_email_html(cabinet=cabinet, client_name=values["client"],
                                       lines=values["liste"].split("\n"), link=link))
            if sent:
                return {"ok": True, "channel": "email", "error": wa_error, "at": now}
        except ValueError as exc:  # garde-fous de sécurité des e-mails
            logger.warning("E-mail de notification refusé : %s", exc)
    return {"ok": False, "channel": None, "error": wa_error or "Aucun canal disponible", "at": now}


# ---------------------------------------------------------------- mise en forme
def _upload_item(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "source": "upload", "id": d["id"], "tenant_id": d["tenant_id"], "category": d["category"],
        "category_label": CATEGORIES.get(d["category"], "Document"), "title": d.get("title"),
        "reference": d.get("reference"), "amount": d.get("amount"), "currency": d.get("currency") or "XOF",
        "date": d.get("doc_date") or (d.get("created_at") or "")[:10], "created_at": d.get("created_at"),
        "filename": d.get("original_filename"), "content_type": d.get("content_type"), "size": d.get("size"),
        "visible": bool(d.get("visible")), "viewed_at": d.get("viewed_at"),
        "last_notification": (d.get("notifications") or [None])[-1],
        "uploaded_by_name": d.get("uploaded_by_name"),
    }


def _invoice_item(inv: Dict[str, Any]) -> Dict[str, Any]:
    total = float(inv.get("total") or 0)
    paid = float(inv.get("paid_amount") or 0)
    return {
        "source": "invoice", "id": inv["id"], "tenant_id": inv["tenant_id"], "category": inv["document_type"],
        "category_label": CATEGORIES.get(inv["document_type"], "Document"), "title": inv.get("title"),
        "reference": inv.get("number"), "amount": total, "currency": inv.get("currency") or "XOF",
        "date": (inv.get("created_at") or "")[:10], "created_at": inv.get("created_at"),
        "filename": f"{inv['document_type']}_{inv.get('number')}.pdf", "content_type": "application/pdf",
        "status": inv.get("status"), "paid_amount": paid,
        "remaining": round(total - paid, 2) if inv["document_type"] == "facture" else None,
        "visible": bool(inv.get("client_visible")), "viewed_at": inv.get("client_viewed_at"),
        "last_notification": (inv.get("client_notifications") or [None])[-1],
    }


async def _client_or_404(tenant_id: str) -> Dict[str, Any]:
    c = await db.users.find_one({"id": tenant_id, "roles": "client"}, {"_id": 0, "password_hash": 0})
    if not c:
        raise HTTPException(status_code=404, detail="Client introuvable")
    return c


def _check_category_rights(user: Dict[str, Any], category: str) -> None:
    if category not in CATEGORIES:
        raise HTTPException(status_code=400, detail="Catégorie inconnue")
    # Délivrer un reçu = encaisser : rôle Caissier obligatoire (superviseur compris),
    # même pour un reçu fait ailleurs.
    if category == "recu" and not can_encaisser(user):
        raise HTTPException(status_code=403, detail="Seul un collaborateur Caissier peut délivrer un reçu")


async def _log(user: Dict[str, Any], action: str, entity_id: str, meta: Dict[str, Any]) -> None:
    from albarka_phase_c import _log_platform_event  # import local : évite un cycle
    await _log_platform_event(user=user, action=action, entity_type="client_document", entity_id=entity_id, meta=meta)


# ---------------------------------------------------------------- mise à disposition des factures (Caisse)
async def publish_invoice(invoice: Dict[str, Any], *, user: Dict[str, Any], notify: bool = True,
                          request: Optional[Request] = None) -> Dict[str, Any]:
    """Rend une facture/proforma/reçu de la Caisse visible dans l'espace du
    client et le prévient (utilisé à la création, à l'encaissement et par le
    bouton « Mettre à disposition »)."""
    now = datetime.now(timezone.utc).isoformat()
    update: Dict[str, Any] = {"client_visible": True, "client_published_at": now}
    push = None
    if notify:
        client = await db.users.find_one({"id": invoice["tenant_id"]}, {"_id": 0, "password_hash": 0})
        result = await notify_client(client, [_invoice_item(invoice)], link=_portal_link(request)) if client else \
            {"ok": False, "channel": None, "error": "Client introuvable", "at": now}
        push = {"client_notifications": result}
        invoice["_notification"] = result
    await db.invoices.update_one({"id": invoice["id"]}, {"$set": update, **({"$push": push} if push else {})})
    invoice.update(update)
    await _log(user, "client_space.invoice_published", invoice["id"], {"number": invoice.get("number")})
    return invoice


@router.post("/invoices/{invoice_id}/visibility")
async def set_invoice_visibility(invoice_id: str, request: Request, payload: Dict[str, Any] = Body(...),
                                 user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Bouton de la Caisse : mettre à disposition du client / retirer de son espace."""
    inv = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not inv:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if payload.get("visible"):
        inv = await publish_invoice(inv, user=user, notify=bool(payload.get("notify", True)), request=request)
        return {"ok": True, "visible": True, "notification": inv.pop("_notification", None)}
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"client_visible": False}})
    await _log(user, "client_space.invoice_hidden", invoice_id, {"number": inv.get("number")})
    return {"ok": True, "visible": False, "notification": None}


# ---------------------------------------------------------------- cabinet : dépôts
@router.get("/catalog")
async def catalog(user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Catégories, modules, variables et textes par défaut (écrans et paramètres)."""
    return {"categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()],
            "modules": [{"key": k, "label": v} for k, v in CLIENT_PORTAL_MODULES.items()],
            "variables": [{"key": k, "label": v} for k, v in TEMPLATE_VARIABLES.items()],
            "template_keys": TEMPLATE_KEYS, "default_templates": DEFAULT_TEMPLATES,
            "can_issue_receipt": can_encaisser(user)}


@router.post("/preview")
async def preview(payload: Dict[str, Any] = Body(...), user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Aperçu d'un texte de notification avec des valeurs d'exemple (Paramètres)."""
    settings = await get_settings_doc()
    cat = payload.get("category") if payload.get("category") in CATEGORIES else "facture"
    sample = [{"category": cat, "title": "Honoraires de septembre", "reference": "FAC-202609-0042", "amount": 150000}]
    text = payload.get("template") or pick_template(settings, sample)
    values = template_values(client={"full_name": "SARL Exemple", "company": "Exemple SARL"}, items=sample,
                             cabinet=settings.get("cabinet_name") or "Cabinet ALBARKA", link=DEFAULT_BASE_URL + CLIENT_PAGE_PATH)
    return {"text": render_template(text, values)}


@router.get("/documents")
async def list_documents(tenant_id: str, category: Optional[str] = None,
                         user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Tout ce qui est (ou peut être) dans l'espace du client : dépôts et
    documents de la Caisse, avec visibilité, dernière notification et lecture."""
    q: Dict[str, Any] = {"tenant_id": tenant_id, "is_deleted": {"$ne": True}}
    if category:
        q["category"] = category
    uploads = await db.client_documents.find(q, {"_id": 0}).sort("created_at", -1).to_list(1000)
    iq: Dict[str, Any] = {"tenant_id": tenant_id}
    if category:
        iq["document_type"] = category
    invoices = await db.invoices.find(iq, {"_id": 0}).sort("created_at", -1).to_list(1000) \
        if not category or category in ("facture", "proforma", "recu") else []
    items = [_upload_item(d) for d in uploads] + [_invoice_item(i) for i in invoices]
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    client = await _client_or_404(tenant_id)
    return {"items": items, "modules": client_modules(client)}


@router.post("/documents", status_code=201)
async def upload_documents(
    request: Request,
    tenant_id: str = Form(...),
    category: str = Form("autre"),
    title: str = Form(""),
    reference: str = Form(""),
    amount: str = Form(""),
    doc_date: str = Form(""),
    visible: bool = Form(True),
    notify: bool = Form(True),
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_roles(CLIENT_SPACE_ROLES)),
):
    """Dépose un ou plusieurs fichiers (ou scans) dans l'espace d'un client.
    Aucune analyse OCR. Si visibles, le client est prévenu en UN seul message."""
    _check_category_rights(user, category)
    client = await _client_or_404(tenant_id)
    if not files:
        raise HTTPException(status_code=400, detail="Aucun fichier")
    if len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"{MAX_FILES} fichiers maximum par dépôt")
    try:
        amount_val = float(amount.replace(" ", "").replace(",", ".")) if amount.strip() else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Montant invalide")
    now = datetime.now(timezone.utc).isoformat()
    created: List[Dict[str, Any]] = []
    for f in files:
        name = f.filename or "document"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"« {name} » : format non accepté (.{ext or '?'})")
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"« {name} » dépasse 20 Mo")
        stored = await albarka_storage.save_and_log(
            db, data=data, kind="client_space", tenant_id=tenant_id, ext=ext,
            content_type=albarka_storage.guess_content_type(ext, f.content_type or "application/octet-stream"),
            original_filename=name, user_id=user["id"])
        # Titre : celui saisi (numéroté s'il y a plusieurs fichiers), sinon le nom du fichier
        base_title = title.strip()
        doc_title = (f"{base_title} ({len(created) + 1})" if base_title and len(files) > 1 else base_title) \
            or name.rsplit(".", 1)[0]
        doc = {
            "id": secrets.token_urlsafe(12), "tenant_id": tenant_id, "category": category,
            "title": doc_title[:200], "reference": reference.strip()[:80] or None, "amount": amount_val,
            "currency": "XOF", "doc_date": doc_date.strip()[:10] or None,
            "storage_id": stored["id"], "storage_path": stored["path"], "content_type": stored["content_type"],
            "size": stored["size"], "original_filename": name, "visible": bool(visible),
            "published_at": now if visible else None, "uploaded_by": user["id"],
            "uploaded_by_name": user.get("full_name") or user.get("email"), "created_at": now,
            "viewed_at": None, "is_deleted": False, "notifications": [],
        }
        await db.client_documents.insert_one(dict(doc))
        created.append(doc)
    notification = None
    if visible and notify:
        notification = await notify_client(client, [_upload_item(d) for d in created], link=_portal_link(request))
        await db.client_documents.update_many({"id": {"$in": [d["id"] for d in created]}},
                                              {"$push": {"notifications": notification}})
        for d in created:
            d["notifications"] = [notification]
    await _log(user, "client_space.upload", created[0]["id"],
               {"tenant_id": tenant_id, "count": len(created), "category": category, "visible": bool(visible)})
    return {"items": [_upload_item(d) for d in created], "notification": notification}


MAX_MULTI_CLIENTS = 300


@router.post("/documents/multi", status_code=201)
async def upload_documents_multi(
    request: Request,
    tenant_ids: str = Form(...),            # identifiants des clients, séparés par des virgules
    category: str = Form("autre"),
    title: str = Form(""),
    reference: str = Form(""),
    amount: str = Form(""),
    doc_date: str = Form(""),
    visible: bool = Form(True),
    notify: bool = Form(True),
    files: List[UploadFile] = File(...),
    user: dict = Depends(require_roles(CLIENT_SPACE_ROLES)),
):
    """Dépose le(s) même(s) document(s) dans l'espace de PLUSIEURS clients
    (ex. une note des impôts pour une liste de clients). Chaque fichier est
    stocké une seule fois ; chaque client reçoit sa propre fiche et sa propre
    notification. Aucune analyse OCR."""
    _check_category_rights(user, category)
    ids = list(dict.fromkeys(t.strip() for t in tenant_ids.split(",") if t.strip()))
    if not ids:
        raise HTTPException(status_code=400, detail="Choisissez au moins un client")
    if len(ids) > MAX_MULTI_CLIENTS:
        raise HTTPException(status_code=400, detail=f"{MAX_MULTI_CLIENTS} clients maximum par dépôt")
    clients = {c["id"]: c for c in await db.users.find({"id": {"$in": ids}, "roles": "client"},
                                                      {"_id": 0, "password_hash": 0}).to_list(MAX_MULTI_CLIENTS)}
    missing = [i for i in ids if i not in clients]
    if missing:
        raise HTTPException(status_code=404, detail=f"{len(missing)} client(s) introuvable(s)")
    if not files or len(files) > MAX_FILES:
        raise HTTPException(status_code=400, detail=f"Entre 1 et {MAX_FILES} fichiers")
    try:
        amount_val = float(amount.replace(" ", "").replace(",", ".")) if amount.strip() else None
    except ValueError:
        raise HTTPException(status_code=400, detail="Montant invalide")
    # 1. Stockage : une seule copie de chaque fichier, partagée par les fiches
    stored_files = []
    for f in files:
        name = f.filename or "document"
        ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(status_code=400, detail=f"« {name} » : format non accepté (.{ext or '?'})")
        data = await f.read()
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail=f"« {name} » dépasse 20 Mo")
        stored = await albarka_storage.save_and_log(
            db, data=data, kind="client_space", tenant_id="multi-clients", ext=ext,
            content_type=albarka_storage.guess_content_type(ext, f.content_type or "application/octet-stream"),
            original_filename=name, user_id=user["id"])
        stored_files.append((name, stored))
    # 2. Une fiche par client et par fichier, puis une notification par client
    now = datetime.now(timezone.utc).isoformat()
    link = _portal_link(request)
    summary = {"clients": len(ids), "documents": 0, "notified": 0, "not_notified": [], "module_closed": []}
    for tid in ids:
        client = clients[tid]
        created = []
        for idx, (name, stored) in enumerate(stored_files):
            base_title = title.strip()
            doc_title = (f"{base_title} ({idx + 1})" if base_title and len(stored_files) > 1 else base_title) \
                or name.rsplit(".", 1)[0]
            doc = {
                "id": secrets.token_urlsafe(12), "tenant_id": tid, "category": category,
                "title": doc_title[:200], "reference": reference.strip()[:80] or None, "amount": amount_val,
                "currency": "XOF", "doc_date": doc_date.strip()[:10] or None,
                "storage_id": stored["id"], "storage_path": stored["path"], "content_type": stored["content_type"],
                "size": stored["size"], "original_filename": name, "visible": bool(visible),
                "published_at": now if visible else None, "uploaded_by": user["id"],
                "uploaded_by_name": user.get("full_name") or user.get("email"), "created_at": now,
                "viewed_at": None, "is_deleted": False, "notifications": [], "batch": True,
            }
            await db.client_documents.insert_one(dict(doc))
            created.append(doc)
        summary["documents"] += len(created)
        # Module « Factures & documents » fermé pour ce client : signalé au cabinet
        if "cabinet_documents" not in client_modules(client):
            summary["module_closed"].append(client.get("full_name"))
        if visible and notify:
            n = await notify_client(client, [_upload_item(d) for d in created], link=link)
            await db.client_documents.update_many({"id": {"$in": [d["id"] for d in created]}},
                                                  {"$push": {"notifications": n}})
            if n.get("ok"):
                summary["notified"] += 1
            else:
                summary["not_notified"].append({"name": client.get("full_name"), "error": n.get("error")})
    await _log(user, "client_space.upload_multi", ids[0],
               {"clients": len(ids), "files": len(stored_files), "category": category, "visible": bool(visible)})
    return summary


async def _doc_or_404(doc_id: str) -> Dict[str, Any]:
    d = await db.client_documents.find_one({"id": doc_id, "is_deleted": {"$ne": True}}, {"_id": 0})
    if not d:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return d


@router.patch("/documents/{doc_id}")
async def update_document(doc_id: str, request: Request, payload: Dict[str, Any] = Body(...),
                          user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Modifie un dépôt ; le rendre visible pour la 1re fois prévient le client."""
    d = await _doc_or_404(doc_id)
    upd: Dict[str, Any] = {}
    for k in ("title", "reference", "doc_date"):
        if k in payload:
            upd[k] = (str(payload[k] or "").strip() or None)
    if "category" in payload:
        _check_category_rights(user, payload["category"])
        upd["category"] = payload["category"]
    if "amount" in payload:
        upd["amount"] = float(payload["amount"]) if payload["amount"] not in (None, "") else None
    notification = None
    if "visible" in payload:
        upd["visible"] = bool(payload["visible"])
        if upd["visible"] and not d.get("visible"):
            upd["published_at"] = datetime.now(timezone.utc).isoformat()
            if payload.get("notify", True):
                client = await _client_or_404(d["tenant_id"])
                notification = await notify_client(client, [_upload_item({**d, **upd})], link=_portal_link(request))
    await db.client_documents.update_one({"id": doc_id}, {"$set": upd, **({"$push": {"notifications": notification}} if notification else {})})
    await _log(user, "client_space.update", doc_id, {k: v for k, v in upd.items() if k != "published_at"})
    return {"item": _upload_item(await _doc_or_404(doc_id)), "notification": notification}


@router.post("/documents/{doc_id}/notify")
async def renotify(doc_id: str, request: Request, user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Renvoie la notification d'un document visible (ex. après correction du numéro WhatsApp)."""
    d = await _doc_or_404(doc_id)
    if not d.get("visible"):
        raise HTTPException(status_code=400, detail="Document non visible par le client")
    client = await _client_or_404(d["tenant_id"])
    notification = await notify_client(client, [_upload_item(d)], link=_portal_link(request))
    await db.client_documents.update_one({"id": doc_id}, {"$push": {"notifications": notification}})
    return {"notification": notification}


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str, user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    """Retire définitivement le document de l'espace client (le fichier reste
    tracé dans stored_objects, rien n'est effacé physiquement)."""
    d = await _doc_or_404(doc_id)
    await db.client_documents.update_one({"id": doc_id}, {"$set": {
        "is_deleted": True, "deleted_at": datetime.now(timezone.utc).isoformat(), "deleted_by": user["id"]}})
    await _log(user, "client_space.delete", doc_id, {"title": d.get("title"), "tenant_id": d["tenant_id"]})
    return {"ok": True}


def _file_response(data: bytes, content_type: str, filename: str, download: bool) -> Response:
    safe = re.sub(r'[^\w.\- ]', "_", filename or "document")
    return Response(content=data, media_type=content_type or "application/octet-stream",
                    headers={"Content-Disposition": f'{"attachment" if download else "inline"}; filename="{safe}"'})


@router.get("/documents/{doc_id}/file")
async def staff_file(doc_id: str, download: bool = False, user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    d = await _doc_or_404(doc_id)
    data, ct = await albarka_storage.get_object(d["storage_path"])
    return _file_response(data, d.get("content_type") or ct, d.get("original_filename"), download)


# ---------------------------------------------------------------- cabinet : modules visibles
@router.get("/modules/{tenant_id}")
async def get_modules(tenant_id: str, user: dict = Depends(require_roles(CLIENT_SPACE_ROLES))):
    client = await _client_or_404(tenant_id)
    return {"modules": client_modules(client),
            "catalog": [{"key": k, "label": v} for k, v in CLIENT_PORTAL_MODULES.items()]}


@router.put("/modules/{tenant_id}")
async def set_modules(tenant_id: str, payload: Dict[str, Any] = Body(...),
                      user: dict = Depends(require_roles(CLIENT_MANAGE_ROLES))):
    """Choisit les modules que ce client voit dans son espace."""
    await _client_or_404(tenant_id)
    mods = [m for m in (payload.get("modules") or []) if m in CLIENT_PORTAL_MODULES]
    await db.users.update_one({"id": tenant_id}, {"$set": {"portal_modules": mods}})
    await _log(user, "client_space.modules", tenant_id, {"modules": mods})
    return {"modules": mods}


# ---------------------------------------------------------------- côté client
def _require_client_module(user: Dict[str, Any]) -> None:
    if not is_client(user):
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    if "cabinet_documents" not in client_modules(user):
        raise HTTPException(status_code=403, detail="Ce module n'est pas ouvert pour votre compte")


@me_router.get("")
async def my_space(user: dict = Depends(get_current_user)):
    """Documents que le cabinet a mis à disposition du client connecté."""
    if not is_client(user):
        return {"items": [], "modules": [], "categories": []}
    mods = client_modules(user)
    if "cabinet_documents" not in mods:
        return {"items": [], "modules": mods, "categories": []}
    uploads = await db.client_documents.find({"tenant_id": user["id"], "visible": True, "is_deleted": {"$ne": True}},
                                             {"_id": 0}).to_list(2000)
    invoices = await db.invoices.find({"tenant_id": user["id"], "client_visible": True}, {"_id": 0}).to_list(2000)
    items = [_upload_item(d) for d in uploads] + [_invoice_item(i) for i in invoices]
    # Côté client : pas d'informations internes (notifications, auteur du dépôt)
    for it in items:
        it.pop("last_notification", None)
        it.pop("uploaded_by_name", None)
        it.pop("visible", None)
        it["is_new"] = not it.get("viewed_at")
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"items": items, "modules": mods, "categories": [{"key": k, "label": v} for k, v in CATEGORIES.items()]}


@me_router.get("/{source}/{item_id}/file")
async def my_file(source: str, item_id: str, download: bool = False, user: dict = Depends(get_current_user)):
    """Ouvre / télécharge un document de son espace ; la 1re ouverture est notée
    (le cabinet voit que le client l'a consulté)."""
    _require_client_module(user)
    now = datetime.now(timezone.utc).isoformat()
    if source == "upload":
        d = await db.client_documents.find_one({"id": item_id, "tenant_id": user["id"], "visible": True,
                                                "is_deleted": {"$ne": True}}, {"_id": 0})
        if not d:
            raise HTTPException(status_code=404, detail="Document introuvable")
        data, ct = await albarka_storage.get_object(d["storage_path"])
        if not d.get("viewed_at"):
            await db.client_documents.update_one({"id": item_id}, {"$set": {"viewed_at": now}})
        return _file_response(data, d.get("content_type") or ct, d.get("original_filename"), download)
    if source == "invoice":
        inv = await db.invoices.find_one({"id": item_id, "tenant_id": user["id"], "client_visible": True}, {"_id": 0})
        if not inv:
            raise HTTPException(status_code=404, detail="Document introuvable")
        from albarka_billing_docs import ensure_invoice_pdf
        inv = await ensure_invoice_pdf(inv)
        try:
            data, _ct = await albarka_storage.get_object(inv["pdf_storage_path"])
        except Exception:  # noqa: BLE001 — fichier perdu : on régénère, comme la Caisse
            await db.invoices.update_one({"id": item_id}, {"$set": {"pdf_storage_path": None}})
            inv["pdf_storage_path"] = None
            inv = await ensure_invoice_pdf(inv)
            data, _ct = await albarka_storage.get_object(inv["pdf_storage_path"])
        if not inv.get("client_viewed_at"):
            await db.invoices.update_one({"id": item_id}, {"$set": {"client_viewed_at": now}})
        return _file_response(data, "application/pdf", f"{inv['document_type']}_{inv['number']}.pdf", download)
    raise HTTPException(status_code=404, detail="Document introuvable")


async def ensure_client_space_indexes() -> None:
    """Index Mongo (appelé au démarrage, voir server.py)."""
    await db.client_documents.create_index([("tenant_id", 1), ("created_at", -1)])
    await db.invoices.create_index([("tenant_id", 1), ("client_visible", 1)])
