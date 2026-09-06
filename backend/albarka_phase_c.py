"""Phase C — Modules opérationnels internes.

Regroupe six modules MVP :
  8a. Chat interne  (thread staff + client)
  8b. Caisse / facturation légère
  9.  RH / Paie (bulletins simples)
  10. Journal d'audit plateforme (platform_logs)
  11. Bibliothèque d'archives (fichiers taggués)
  12. Centre de messagerie (broadcast contacts)

Chaque module expose un CRUD Mongo minimal, protégé par les rôles cabinet.
"""
from __future__ import annotations

import base64
import logging
import secrets
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_roles, require_staff
from albarka_models import CAISSE_DATE_RANGE_ROLES, CHAT_THREAD_CREATE_ROLES, is_client
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.phase_c")

# ==========================================================================
# 8a — Chat interne
#
# Strictement réservé aux collaborateurs entre eux (mission, déplacement,
# extra-muros…) : jamais accessible aux clients, même pour une discussion
# qui les concerne — leur canal reste les Conversations WhatsApp. Organisé
# en fils nommés par sujet/mission, créables à la volée par n'importe quel
# collaborateur (pas de fil imposé, pas de notion de propriétaire de fil).
# ==========================================================================
chat_router = APIRouter(prefix="/chat", tags=["Chat interne"])


class ChatThreadCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=120)


class ChatMessageCreate(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=4000)


class ChatDmStart(BaseModel):
    peer_id: str = Field(..., min_length=1)


async def _get_thread_or_404(thread_id: str, user: Optional[dict] = None) -> dict:
    thread = await db.chat_threads.find_one({"id": thread_id}, {"_id": 0})
    if not thread:
        raise HTTPException(status_code=404, detail="Fil introuvable")
    # Une discussion directe (kind="dm") est privée à ses deux participants —
    # contrairement aux fils nommés, ouverts à tout le cabinet par design
    # (voir list_chat_threads). Un utilisateur hors de la conversation ne
    # doit ni la lire, ni y écrire, même en devinant son id.
    if user and thread.get("kind") == "dm" and user["id"] not in (thread.get("participants") or []):
        raise HTTPException(status_code=403, detail="Discussion privée réservée à ses deux participants")
    return thread


@chat_router.post("/threads")
async def create_chat_thread(payload: ChatThreadCreate, user: dict = Depends(require_roles(CHAT_THREAD_CREATE_ROLES))):
    doc = {
        "id": secrets.token_urlsafe(12),
        "kind": "group",
        "title": payload.title.strip(),
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_threads.insert_one(doc.copy())
    return serialize(doc)


@chat_router.post("/dm")
async def start_or_get_dm(payload: ChatDmStart, user: dict = Depends(require_staff())):
    """Discussion directe 1-à-1 entre deux collaborateurs, sans fil nommé à
    créer au préalable — ouverte à tout collaborateur (pas seulement
    CHAT_THREAD_CREATE_ROLES, réservé aux fils de groupe). Idempotent : un
    second appel entre les deux mêmes personnes retrouve la même discussion
    plutôt que d'en recréer une."""
    if payload.peer_id == user["id"]:
        raise HTTPException(status_code=400, detail="Impossible de démarrer une discussion avec soi-même")
    peer = await db.users.find_one({"id": payload.peer_id}, {"_id": 0, "password_hash": 0})
    if not peer or is_client(peer):
        raise HTTPException(status_code=404, detail="Collaborateur introuvable")
    participants = sorted([user["id"], payload.peer_id])
    existing = await db.chat_threads.find_one({"kind": "dm", "participants": participants}, {"_id": 0})
    if existing:
        return serialize(existing)
    doc = {
        "id": secrets.token_urlsafe(12),
        "kind": "dm",
        "participants": participants,
        "title": None,
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_threads.insert_one(doc.copy())
    return serialize(doc)


@chat_router.get("/threads")
async def list_chat_threads(user: dict = Depends(require_staff())):
    """Tous les fils de groupe (même sans message, pour qu'un fil tout
    juste créé apparaisse immédiatement) + les discussions directes dont
    l'utilisateur est l'un des deux participants — triés par activité la
    plus récente. Le titre d'une discussion directe est calculé à
    l'affichage : le nom du collègue en face, jamais stocké tel quel
    (symétrique : chacun voit le nom de l'AUTRE)."""
    threads = await db.chat_threads.find({}, {"_id": 0}).to_list(500)
    visible = [
        t for t in threads
        if t.get("kind") != "dm" or user["id"] in (t.get("participants") or [])
    ]
    last_by_thread = {
        t["_id"]: t async for t in db.chat_messages.aggregate([
            {"$sort": {"created_at": -1}},
            {"$group": {
                "_id": "$thread_id",
                "last_at": {"$first": "$created_at"},
                "last_author": {"$first": "$author_name"},
                "last_body": {"$first": "$body"},
                "count": {"$sum": 1},
            }},
        ])
    }
    result = []
    for t in visible:
        last = last_by_thread.get(t["id"])
        if t.get("kind") == "dm":
            peer_id = next((p for p in (t.get("participants") or []) if p != user["id"]), None)
            peer = await db.users.find_one({"id": peer_id}, {"_id": 0, "full_name": 1}) if peer_id else None
            title = (peer or {}).get("full_name") or "Discussion directe"
        else:
            title = t["title"]
        result.append({
            "thread_id": t["id"], "title": title, "kind": t.get("kind", "group"),
            "last_at": last["last_at"] if last else t["created_at"],
            "last_author": last["last_author"] if last else None,
            "last_body": (last["last_body"][:120] if last else ""),
            "count": last["count"] if last else 0,
        })
    result.sort(key=lambda r: r["last_at"] or "", reverse=True)
    return result


@chat_router.get("/messages")
async def list_chat_messages(
    thread_id: str,
    limit: int = 200,
    user: dict = Depends(require_staff()),
):
    await _get_thread_or_404(thread_id, user)
    items = await db.chat_messages.find(
        {"thread_id": thread_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


@chat_router.post("/messages")
async def post_chat_message(
    payload: ChatMessageCreate, user: dict = Depends(require_staff()),
):
    await _get_thread_or_404(payload.thread_id, user)
    doc = {
        "id": secrets.token_urlsafe(12),
        "thread_id": payload.thread_id,
        "body": payload.body,
        "author_id": user["id"],
        "author_name": user.get("full_name") or user.get("email"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(doc.copy())
    await _log_platform_event(
        user=user, action="chat.post", entity_type="chat_thread",
        entity_id=payload.thread_id, meta={"len": len(payload.body)},
    )
    return serialize(doc)


# ==========================================================================
# 8b — Caisse / facturation légère
# ==========================================================================
billing_router = APIRouter(prefix="/billing", tags=["Caisse"])


class InvoiceItem(BaseModel):
    label: str = Field(..., min_length=1, max_length=200)
    quantity: float = 1
    unit_price: float = 0
    tax_rate: float = 0

    @property
    def line_total(self) -> float:
        subtotal = self.quantity * self.unit_price
        return subtotal * (1 + self.tax_rate / 100.0)


class InvoiceCreate(BaseModel):
    tenant_id: str
    title: str = Field(..., min_length=1, max_length=200)
    items: List[InvoiceItem] = Field(..., min_length=1)
    currency: str = "XOF"
    due_date: Optional[str] = None
    notes: Optional[str] = None
    document_type: str = Field(
        "facture",
        description="facture | reçu | proforma — chaque type a sa propre numérotation",
    )

    @field_validator("document_type")
    @classmethod
    def _valid_doc_type(cls, v):
        if v not in ("facture", "recu", "proforma"):
            raise ValueError("document_type doit être facture | recu | proforma")
        return v


class PaymentCreate(BaseModel):
    invoice_id: str
    amount: float = Field(..., gt=0)
    method: str = Field("cash", description="cash/mobile_money/bank/other")
    paid_at: Optional[str] = None
    reference: Optional[str] = None


def _invoice_totals(items: list[dict]) -> dict:
    subtotal = sum((i["quantity"] * i["unit_price"]) for i in items)
    tax = sum((i["quantity"] * i["unit_price"] * (i.get("tax_rate", 0) / 100.0)) for i in items)
    return {"subtotal": round(subtotal, 2), "tax": round(tax, 2), "total": round(subtotal + tax, 2)}


_DOC_PREFIX = {"facture": "FAC", "recu": "REC", "proforma": "PRO"}


@billing_router.get("/invoices")
async def list_invoices(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    document_type: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if status: q["status"] = status
    if document_type: q["document_type"] = document_type
    items = await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(items)


@billing_router.post("/invoices")
async def create_invoice(payload: InvoiceCreate, user: dict = Depends(require_staff())):
    items = [i.model_dump() for i in payload.items]
    totals = _invoice_totals(items)
    # Numéro : {FAC|REC|PRO}-YYYYMM-NNNN (compteur mensuel PAR type)
    month_key = datetime.now(timezone.utc).strftime("%Y%m")
    prefix = _DOC_PREFIX[payload.document_type]
    key = f"{payload.document_type}:{month_key}"
    res = await db.report_series.find_one_and_update(
        {"key": key},
        {"$inc": {"seq": 1}, "$setOnInsert": {"kind": payload.document_type, "month_key": month_key}},
        upsert=True, return_document=True,
    )
    seq = int(res.get("seq") or 1)
    number = f"{prefix}-{month_key}-{seq:04d}"
    # Un reçu est réputé déjà payé au moment de l'émission ; un proforma
    # n'est pas payable (indicatif). Une facture reste "unpaid" par défaut.
    if payload.document_type == "recu":
        status = "paid"
        paid_amount = totals["total"]
    elif payload.document_type == "proforma":
        status = "proforma"
        paid_amount = 0.0
    else:
        status = "unpaid"
        paid_amount = 0.0
    doc = {
        "id": secrets.token_urlsafe(12),
        "number": number,
        "document_type": payload.document_type,
        "tenant_id": payload.tenant_id,
        "title": payload.title,
        "items": items,
        "currency": payload.currency,
        "due_date": payload.due_date,
        "notes": payload.notes,
        "status": status,
        "paid_amount": paid_amount,
        **totals,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.invoices.insert_one(doc.copy())
    await _log_platform_event(user=user, action=f"{payload.document_type}.create",
                              entity_type="invoice", entity_id=doc["id"],
                              meta={"total": doc["total"], "number": number})
    # Point 2 — auto-archive
    await _auto_archive(
        title=f"{payload.document_type.title()} {number} — {payload.title}",
        category="caisse",
        tags=[payload.document_type, month_key],
        source={"kind": "invoice", "id": doc["id"], "number": number, "tenant_id": doc["tenant_id"]},
        user=user,
    )
    return serialize(doc)


@billing_router.post("/payments")
async def create_payment(payload: PaymentCreate, user: dict = Depends(require_staff())):
    invoice = await db.invoices.find_one({"id": payload.invoice_id}, {"_id": 0})
    if not invoice:
        raise HTTPException(status_code=404, detail="Facture introuvable")
    payment = {
        "id": secrets.token_urlsafe(12),
        "invoice_id": payload.invoice_id,
        "invoice_number": invoice["number"],
        "tenant_id": invoice["tenant_id"],
        "amount": float(payload.amount),
        "method": payload.method,
        "reference": payload.reference,
        "paid_at": payload.paid_at or datetime.now(timezone.utc).isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.payments.insert_one(payment.copy())
    new_paid = float(invoice.get("paid_amount", 0)) + float(payload.amount)
    new_status = "paid" if new_paid >= float(invoice["total"]) - 0.01 else "partial"
    await db.invoices.update_one(
        {"id": payload.invoice_id},
        {"$set": {"paid_amount": round(new_paid, 2), "status": new_status}},
    )
    await _log_platform_event(user=user, action="payment.create",
                              entity_type="invoice", entity_id=invoice["id"],
                              meta={"amount": payment["amount"], "method": payment["method"]})
    return serialize(payment)


def _is_caisse_date_privileged(user: dict) -> bool:
    return bool(set(user.get("roles") or []) & set(CAISSE_DATE_RANGE_ROLES))


def _payments_date_bounds(
    user: dict, date_from: Optional[str], date_to: Optional[str], all_time: bool = False,
) -> tuple[Optional[str], Optional[str]]:
    """Renvoie (borne basse incluse, borne haute exclue) en ISO datetime, ou
    (None, None) si `all_time` est actif (aucun filtre de date — "Depuis
    toujours").

    Seuls Administrateur/DG/Superviseur peuvent choisir une période ou
    "Depuis toujours" — tout autre collaborateur est forcé sur la journée en
    cours côté serveur, même s'il tente de passer ses propres paramètres
    (l'UI ne lui présente pas le sélecteur, mais l'API doit refuser aussi)."""
    today = date.today()
    if not _is_caisse_date_privileged(user):
        date_from = date_to = today.isoformat()
        all_time = False
    if all_time:
        return None, None
    date_from = date_from or today.isoformat()
    date_to = date_to or today.isoformat()
    low = f"{date_from}T00:00:00"
    high_date = date.fromisoformat(date_to) + timedelta(days=1)
    high = f"{high_date.isoformat()}T00:00:00"
    return low, high


@billing_router.get("/payments")
async def list_payments(
    tenant_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    all_time: bool = False,
    user: dict = Depends(require_staff()),
):
    low, high = _payments_date_bounds(user, date_from, date_to, all_time)
    q: dict = {}
    if low is not None:
        q["paid_at"] = {"$gte": low, "$lt": high}
    if tenant_id: q["tenant_id"] = tenant_id
    if invoice_id: q["invoice_id"] = invoice_id
    items = await db.payments.find(q, {"_id": 0}).sort("paid_at", -1).to_list(1000)
    return serialize_many(items)


@billing_router.get("/summary")
async def billing_summary(
    tenant_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    all_time: bool = False,
    user: dict = Depends(require_staff()),
):
    """Agrégat rapide : total facturé / impayé (toutes dates confondues —
    les factures restent visibles sans restriction de période pour tous les
    collaborateurs) et total encaissé (carte "Encaissement", qui reflète
    strictement les encaissements visibles par l'utilisateur : journée en
    cours pour un collaborateur ordinaire, période choisie — ou "Depuis
    toujours" — pour Administrateur/DG/Superviseur, voir _payments_date_bounds)."""
    inv_q: dict = {}
    if tenant_id: inv_q["tenant_id"] = tenant_id
    invoices = await db.invoices.find(inv_q, {"_id": 0, "total": 1, "paid_amount": 1, "status": 1}).to_list(2000)
    total = sum(float(i.get("total", 0)) for i in invoices)
    outstanding = sum(float(i.get("total", 0)) - float(i.get("paid_amount", 0)) for i in invoices)
    unpaid_count = sum(1 for i in invoices if i.get("status") != "paid")

    low, high = _payments_date_bounds(user, date_from, date_to, all_time)
    pay_q: dict = {}
    if low is not None:
        pay_q["paid_at"] = {"$gte": low, "$lt": high}
    if tenant_id: pay_q["tenant_id"] = tenant_id
    payments = await db.payments.find(pay_q, {"_id": 0, "amount": 1}).to_list(5000)
    paid = sum(float(p.get("amount", 0)) for p in payments)

    return {
        "invoice_count": len(invoices),
        "total_billed": round(total, 2),
        "total_paid": round(paid, 2),
        "outstanding": round(outstanding, 2),
        "unpaid_count": unpaid_count,
        "date_range_editable": _is_caisse_date_privileged(user),
        "date_from": low[:10] if low else None,
        "date_to": (date.fromisoformat(high[:10]) - timedelta(days=1)).isoformat() if high else None,
    }


def _statement_period_label(user: dict, date_from: Optional[str], date_to: Optional[str], all_time: bool) -> str:
    if not _is_caisse_date_privileged(user):
        return f"Aujourd'hui ({date.today().isoformat()})"
    if all_time:
        return "Depuis toujours"
    low, high = _payments_date_bounds(user, date_from, date_to, all_time)
    low_d = low[:10]
    high_d = (date.fromisoformat(high[:10]) - timedelta(days=1)).isoformat()
    return f"{low_d} → {high_d}"


async def _build_statement(
    user: dict, tenant_id: Optional[str], date_from: Optional[str], date_to: Optional[str], all_time: bool,
) -> tuple[bytes, Optional[dict], str]:
    """Rassemble les factures/encaissements (mêmes filtres que l'écran Caisse
    — factures non bornées dans le temps, encaissements bornés par la
    période) et construit le PDF "situation de compte". Partagé par le
    téléchargement (GET .../pdf) et l'envoi au client (POST .../send)."""
    from albarka_reports import build_billing_statement_pdf

    client = None
    if tenant_id:
        client = await db.users.find_one({"id": tenant_id}, {"_id": 0, "password_hash": 0})
        if not client:
            raise HTTPException(status_code=404, detail="Client introuvable")

    inv_q: dict = {"tenant_id": tenant_id} if tenant_id else {}
    invoices = await db.invoices.find(inv_q, {"_id": 0}).sort("created_at", -1).to_list(2000)
    total_billed = sum(float(i.get("total", 0)) for i in invoices)
    outstanding = sum(float(i.get("total", 0)) - float(i.get("paid_amount", 0)) for i in invoices)

    low, high = _payments_date_bounds(user, date_from, date_to, all_time)
    pay_q: dict = {}
    if low is not None:
        pay_q["paid_at"] = {"$gte": low, "$lt": high}
    if tenant_id: pay_q["tenant_id"] = tenant_id
    payments = await db.payments.find(pay_q, {"_id": 0}).sort("paid_at", -1).to_list(5000)
    total_paid = sum(float(p.get("amount", 0)) for p in payments)

    period_label = _statement_period_label(user, date_from, date_to, all_time)
    pdf_bytes = build_billing_statement_pdf(
        client=client, invoices=invoices, payments=payments, period_label=period_label,
        total_billed=total_billed, total_paid=total_paid, outstanding=outstanding,
    )
    return pdf_bytes, client, period_label


@billing_router.get("/statement/pdf")
async def billing_statement_pdf(
    tenant_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    all_time: bool = False,
    user: dict = Depends(require_staff()),
):
    """Export PDF de la Caisse ("situation de compte") — mêmes filtres que
    l'écran, sans colonne Actions (voir build_billing_statement_pdf)."""
    from fastapi.responses import Response

    pdf_bytes, _client, _period = await _build_statement(user, tenant_id, date_from, date_to, all_time)
    filename = f"situation_de_compte_{tenant_id or 'tous_clients'}_{date.today().isoformat()}.pdf"
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class SendStatementPayload(BaseModel):
    tenant_id: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    all_time: bool = False
    channel: str = "whatsapp"  # "whatsapp" | "email"


@billing_router.post("/statement/send")
async def send_billing_statement(payload: SendStatementPayload, user: dict = Depends(require_staff())):
    """Envoie la situation de compte du client sélectionné par WhatsApp ou
    email — même restriction que l'envoi de pièces (_can_send_whatsapp) pour
    le canal WhatsApp : rôle Communication limité aux clients au numéro
    attesté vérifié."""
    from albarka_documents import _can_send_whatsapp
    from albarka_models import whatsapp_number_of
    from albarka_notifications import _wa_upload_media, send_email, send_whatsapp_document

    pdf_bytes, client, period_label = await _build_statement(
        user, payload.tenant_id, payload.date_from, payload.date_to, payload.all_time,
    )
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    filename = "situation_de_compte.pdf"

    if payload.channel == "email":
        recipient = (client.get("email") or "").strip()
        if not recipient:
            raise HTTPException(status_code=400, detail="Aucune adresse email disponible pour ce client")
        client_label = client.get("company") or client.get("full_name", "")
        html = f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;padding:16px;">
  <p>Bonjour,</p>
  <p>Veuillez trouver ci-joint la situation de compte de <strong>{client_label}</strong>
     pour la période : {period_label}.</p>
</div>
"""
        attachment = {
            "filename": filename,
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
            "content_type": "application/pdf",
        }
        message_id = await send_email(
            to=[recipient], subject=f"Situation de compte — {period_label}", html=html, attachments=[attachment],
        )
        if not message_id:
            raise HTTPException(status_code=502, detail="Échec envoi email (proxy indisponible ou rejeté)")
        return {"ok": True, "channel": "email", "to": recipient}

    if not _can_send_whatsapp(user, client):
        raise HTTPException(
            status_code=403,
            detail="Envoi WhatsApp réservé au rôle Communication sur un numéro attesté vérifié "
                   "(ou aux rôles superviseur/direction/DG/administrateur/secrétariat)",
        )
    phone = whatsapp_number_of(client) or ""
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp éligible (format +226…) pour ce client")
    settings = await get_settings_doc()
    if not settings.get("wa_enabled"):
        raise HTTPException(status_code=400, detail="WhatsApp désactivé dans les paramètres")
    media_id = await _wa_upload_media(pdf_bytes=pdf_bytes, filename=filename)
    if not media_id:
        raise HTTPException(status_code=502, detail="Échec de l'envoi (WhatsApp non configuré ou upload refusé)")
    result = await send_whatsapp_document(
        to_phone=phone, media_id=media_id, filename=filename,
        caption=f"Situation de compte — {period_label}",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'erreur inconnue'}")
    return {"ok": True, "channel": "whatsapp", "to": phone, "message_id": result.get("message_id")}


# ==========================================================================
# 9 — RH / Paie (bulletins simples)
# ==========================================================================
hr_router = APIRouter(prefix="/hr", tags=["RH & Paie"])
_HR_ROLES = ["superviseur", "direction", "administrateur", "rh"]


class EmployeeCreate(BaseModel):
    tenant_id: str = Field(..., description="Client du cabinet auquel l'employé appartient")
    full_name: str = Field(..., min_length=2, max_length=200)
    role: Optional[str] = None
    base_salary: float = Field(..., ge=0)
    hire_date: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None


class PayslipCreate(BaseModel):
    employee_id: str
    period_month: str = Field(..., description="YYYY-MM")
    gross_salary: float = Field(..., ge=0)
    deductions: float = 0
    bonuses: float = 0
    notes: Optional[str] = None

    @field_validator("period_month")
    @classmethod
    def _valid_month(cls, v):
        import re as _re
        if not _re.match(r"^\d{4}-\d{2}$", v):
            raise ValueError("period_month attendu au format YYYY-MM")
        return v


@hr_router.get("/employees")
async def list_employees(
    tenant_id: Optional[str] = None,
    user: dict = Depends(require_roles(_HR_ROLES)),
):
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    items = await db.employees.find(q, {"_id": 0}).sort("full_name", 1).to_list(500)
    return serialize_many(items)


@hr_router.post("/employees")
async def create_employee(payload: EmployeeCreate, user: dict = Depends(require_roles(_HR_ROLES))):
    doc = {
        "id": secrets.token_urlsafe(12),
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.employees.insert_one(doc.copy())
    return serialize(doc)


@hr_router.get("/payslips")
async def list_payslips(
    employee_id: Optional[str] = None,
    period_month: Optional[str] = None,
    user: dict = Depends(require_roles(_HR_ROLES)),
):
    q = {}
    if employee_id: q["employee_id"] = employee_id
    if period_month: q["period_month"] = period_month
    items = await db.payslips.find(q, {"_id": 0}).sort("period_month", -1).to_list(1000)
    return serialize_many(items)


@hr_router.post("/payslips")
async def create_payslip(payload: PayslipCreate, user: dict = Depends(require_roles(_HR_ROLES))):
    emp = await db.employees.find_one({"id": payload.employee_id}, {"_id": 0})
    if not emp:
        raise HTTPException(status_code=404, detail="Employé introuvable")
    net = float(payload.gross_salary) - float(payload.deductions) + float(payload.bonuses)
    doc = {
        "id": secrets.token_urlsafe(12),
        "employee_id": payload.employee_id,
        "employee_name": emp.get("full_name"),
        "tenant_id": emp.get("tenant_id"),
        "period_month": payload.period_month,
        "gross_salary": float(payload.gross_salary),
        "deductions": float(payload.deductions),
        "bonuses": float(payload.bonuses),
        "net_salary": round(net, 2),
        "notes": payload.notes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.payslips.insert_one(doc.copy())
    await _log_platform_event(user=user, action="payslip.create",
                              entity_type="payslip", entity_id=doc["id"],
                              meta={"period": doc["period_month"], "net": doc["net_salary"]})
    # Point 2 — auto-archive
    await _auto_archive(
        title=f"Bulletin de paie — {doc['employee_name']} — {doc['period_month']}",
        category="paie",
        tags=[doc["period_month"], "bulletin"],
        source={"kind": "payslip", "id": doc["id"],
                "employee_id": doc["employee_id"], "tenant_id": doc["tenant_id"]},
        user=user,
    )
    return serialize(doc)


@hr_router.get("/payslips/{payslip_id}.pdf")
async def download_payslip_pdf(payslip_id: str, user: dict = Depends(require_roles(_HR_ROLES))):
    """Génère et renvoie le bulletin en PDF (ReportLab, mise en page simple)."""
    from fastapi.responses import Response
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )
    import io as _io

    ps = await db.payslips.find_one({"id": payslip_id}, {"_id": 0})
    if not ps:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")
    emp = await db.employees.find_one({"id": ps["employee_id"]}, {"_id": 0}) or {}
    client = await db.users.find_one({"id": ps.get("tenant_id")}, {"_id": 0}) or {}

    buf = _io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=40, bottomMargin=40)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>Bulletin de paie</b>", styles["Title"]),
        Spacer(1, 10),
        Paragraph(
            f"<b>Employeur :</b> {client.get('company') or client.get('full_name') or '—'}<br/>"
            f"<b>Employé :</b> {emp.get('full_name') or ps.get('employee_name')}"
            f" · <b>Fonction :</b> {emp.get('role') or '—'}<br/>"
            f"<b>Période :</b> {ps['period_month']}",
            styles["BodyText"],
        ),
        Spacer(1, 12),
    ]
    table_data = [
        ["Rubrique", "Montant (XOF)"],
        ["Salaire brut", f"{ps['gross_salary']:,.0f}"],
        ["Primes", f"+ {ps['bonuses']:,.0f}"],
        ["Retenues", f"- {ps['deductions']:,.0f}"],
        ["Salaire net", f"{ps['net_salary']:,.0f}"],
    ]
    t = Table(table_data, colWidths=[300, 150])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F6B4A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E5A24B")),
        ("BOX", (0, 0), (-1, -1), 0.5, colors.grey),
        ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    if ps.get("notes"):
        story.append(Spacer(1, 12))
        story.append(Paragraph(f"<i>Notes :</i> {ps['notes']}", styles["BodyText"]))
    story.append(Spacer(1, 20))
    story.append(Paragraph(
        f"<font size=8 color='#888'>Émis le {datetime.now(timezone.utc).strftime('%d/%m/%Y à %H:%M UTC')} par le portail ALBARKA.</font>",
        styles["BodyText"],
    ))
    doc.build(story)
    pdf = buf.getvalue()
    filename = f"bulletin_{ps['period_month']}_{(emp.get('full_name') or 'employe').replace(' ', '_')}.pdf"
    return Response(
        content=pdf, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ==========================================================================
# 10 — Platform logs (audit)
# ==========================================================================
logs_router = APIRouter(prefix="/platform-logs", tags=["Logs plateforme"])
_LOG_ROLES = ["superviseur", "direction", "administrateur"]
# Même compte que _PROTECT_EMAILS dans albarka_migrate.py — l'administrateur
# système du portail (pas un simple rôle "administrateur" parmi d'autres).
# Ses propres actions sont masquées du journal pour tout le monde SAUF pour
# lui-même : personne d'autre — même un autre administrateur/superviseur —
# ne doit voir ce qu'il fait sur la plateforme.
_SYSTEM_ADMIN_EMAIL = "admin@sawalismartsystems.com"


async def _log_platform_event(
    *, user: dict, action: str, entity_type: str,
    entity_id: Optional[str] = None, meta: Optional[dict] = None,
):
    """Interne — enregistre un événement d'audit (best-effort)."""
    try:
        await db.platform_logs.insert_one({
            "id": secrets.token_urlsafe(12),
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "actor_id": user["id"],
            "actor_name": user.get("full_name") or user.get("email"),
            "actor_roles": user.get("roles") or [],
            "meta": meta or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception:  # noqa: BLE001
        logger.exception("Échec écriture platform_log action=%s", action)


@logs_router.get("")
async def list_platform_logs(
    action: Optional[str] = None,
    entity_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 200,
    user: dict = Depends(require_roles(_LOG_ROLES)),
):
    q = {}
    if action:
        # Recherche partielle insensible à la casse pour matcher 'broadcast' → 'broadcast.send'
        q["action"] = {"$regex": action, "$options": "i"}
    if entity_type: q["entity_type"] = entity_type
    if actor_id: q["actor_id"] = actor_id

    is_system_admin = (user.get("email") or "").strip().lower() == _SYSTEM_ADMIN_EMAIL
    if not is_system_admin:
        sys_admin = await db.users.find_one({"email": _SYSTEM_ADMIN_EMAIL}, {"_id": 0, "id": 1})
        sys_admin_id = sys_admin["id"] if sys_admin else None
        if sys_admin_id:
            if actor_id == sys_admin_id:
                # Tentative explicite de cibler l'administrateur système via
                # ?actor_id=... — jamais dévoilé à quelqu'un d'autre que lui.
                return []
            q["actor_id"] = {"$ne": sys_admin_id}
    items = await db.platform_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


# ==========================================================================
# 11 — Bibliothèque archives
# ==========================================================================
archives_router = APIRouter(prefix="/archives", tags=["Archives"])


async def _auto_archive(
    *, title: str, category: str, tags: list[str],
    source: dict, user: dict, description: Optional[str] = None,
) -> None:
    """Point 2 — capte automatiquement un événement métier dans `archives`.

    Idempotent au niveau `source.kind + source.id` : une deuxième insertion
    pour le même événement est un no-op. Best-effort : n'échoue jamais
    l'appelant (documents, rapports, factures, bulletins).
    """
    try:
        source = {**source, "auto": True}
        existing = await db.archives.find_one(
            {"source.kind": source.get("kind"), "source.id": source.get("id")},
            {"_id": 0, "id": 1},
        )
        if existing:
            return
        await db.archives.insert_one({
            "id": secrets.token_urlsafe(12),
            "title": title[:200],
            "category": category,
            "description": description,
            "tags": tags,
            "source": source,
            "auto": True,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "created_by": user["id"] if user else None,
            "created_by_name": (user.get("full_name") or user.get("email")) if user else "system",
        })
    except Exception:  # noqa: BLE001
        logger.exception("Échec auto-archive kind=%s id=%s", source.get("kind"), source.get("id"))


class ArchiveItemCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    category: str = Field("autre", max_length=60)
    description: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    storage_path: Optional[str] = None  # optional pointer to R2/local
    original_filename: Optional[str] = None


@archives_router.get("")
async def list_archives(
    category: Optional[str] = None,
    tag: Optional[str] = None,
    q: Optional[str] = None,
    source_kind: Optional[str] = None,
    only_manual: Optional[bool] = None,
    user: dict = Depends(require_staff()),
):
    query: dict = {}
    if category: query["category"] = category
    if tag: query["tags"] = tag
    if source_kind: query["source.kind"] = source_kind
    if only_manual:
        query["auto"] = {"$ne": True}
    if q:
        query["$or"] = [
            {"title": {"$regex": q, "$options": "i"}},
            {"description": {"$regex": q, "$options": "i"}},
        ]
    items = await db.archives.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(items)


@archives_router.post("")
async def create_archive(payload: ArchiveItemCreate, user: dict = Depends(require_staff())):
    doc = {
        "id": secrets.token_urlsafe(12),
        **payload.model_dump(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
    }
    await db.archives.insert_one(doc.copy())
    return serialize(doc)


@archives_router.delete("/{archive_id}")
async def delete_archive(archive_id: str, user: dict = Depends(require_staff())):
    res = await db.archives.delete_one({"id": archive_id})
    if not res.deleted_count:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    return {"ok": True, "id": archive_id}


# ==========================================================================
# 12 — Centre de messagerie (broadcast)
# ==========================================================================
messaging_router = APIRouter(prefix="/messaging", tags=["Messagerie"])


class BroadcastCreate(BaseModel):
    subject: str = Field(..., min_length=1, max_length=200)
    body: str = Field(..., min_length=1, max_length=8000)
    scope: str = Field("clients", description="clients/staff/all")
    channel: str = Field("email", description="email/whatsapp")

    @field_validator("scope")
    @classmethod
    def _valid_scope(cls, v):
        if v not in ("clients", "staff", "all"):
            raise ValueError("scope doit être clients | staff | all")
        return v

    @field_validator("channel")
    @classmethod
    def _valid_channel(cls, v):
        if v not in ("email", "whatsapp"):
            raise ValueError("channel doit être email | whatsapp")
        return v


@messaging_router.post("/broadcast")
async def send_broadcast(
    payload: BroadcastCreate,
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "communication"])),
):
    """Diffuse un message à un scope large. Écrit l'intention dans
    `broadcasts` + tente un envoi immédiat. Chaque destinataire est logué
    dans `broadcast_deliveries` avec le statut de la tentative.
    """
    if payload.scope == "clients":
        recipients = await db.users.find(
            {"roles": "client", "is_active": {"$ne": False}}, {"_id": 0},
        ).to_list(1000)
    elif payload.scope == "staff":
        recipients = await db.users.find(
            {"roles": {"$nin": ["client"]}, "is_active": {"$ne": False}}, {"_id": 0},
        ).to_list(1000)
    else:  # all
        recipients = await db.users.find(
            {"is_active": {"$ne": False}}, {"_id": 0},
        ).to_list(2000)

    bid = secrets.token_urlsafe(12)
    broadcast_doc = {
        "id": bid, "subject": payload.subject, "body": payload.body,
        "scope": payload.scope, "channel": payload.channel,
        "recipient_count": len(recipients),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
        "created_by_name": user.get("full_name") or user.get("email"),
    }
    await db.broadcasts.insert_one(broadcast_doc.copy())

    deliveries = []
    if payload.channel == "email":
        from albarka_notifications import send_email as _send_email
        for r in recipients:
            if not r.get("email"):
                continue
            if r.get("can_receive_notifications") is False:
                continue
            mid = None
            try:
                mid = await _send_email(
                    to=r["email"], subject=payload.subject,
                    html=f"<p>{payload.body}</p>",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Broadcast email error to %s", r.get("email"))
            deliveries.append({
                "id": secrets.token_urlsafe(12), "broadcast_id": bid,
                "recipient_id": r["id"], "recipient_email": r.get("email"),
                "channel": "email", "message_id": mid,
                "success": bool(mid),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
    else:  # whatsapp
        from albarka_notifications import send_whatsapp as _send_wa
        for r in recipients:
            phone = r.get("phone")
            if not phone or not phone.startswith("+"):
                continue
            if r.get("can_receive_notifications") is False:
                continue
            result: dict = {}
            try:
                result = await _send_wa(
                    to_phone=phone,
                    message=f"{payload.subject}\n\n{payload.body}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Broadcast WA error to %s", phone)
                result = {"ok": False, "message_id": None, "kind": "http_error",
                          "error": "exception", "outside_24h_window": None}
            deliveries.append({
                "id": secrets.token_urlsafe(12), "broadcast_id": bid,
                "recipient_id": r["id"], "recipient_phone": phone,
                "channel": "whatsapp", "message_id": result.get("message_id"),
                "success": bool(result.get("ok")),
                "kind": result.get("kind"),
                "error": result.get("error"),
                "outside_24h_window": result.get("outside_24h_window"),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })

    if deliveries:
        await db.broadcast_deliveries.insert_many([dict(d) for d in deliveries])
    delivered = sum(1 for d in deliveries if d["success"])
    await db.broadcasts.update_one({"id": bid}, {"$set": {
        "delivery_count": len(deliveries),
        "delivered_count": delivered,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }})
    await _log_platform_event(user=user, action="broadcast.send",
                              entity_type="broadcast", entity_id=bid,
                              meta={"scope": payload.scope, "delivered": delivered})
    return {
        "ok": True, "id": bid,
        "recipient_count": len(recipients),
        "delivery_attempts": len(deliveries),
        "delivered": delivered,
    }


@messaging_router.get("/broadcasts")
async def list_broadcasts(
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "communication"])),
):
    items = await db.broadcasts.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return serialize_many(items)


@messaging_router.get("/broadcasts/{broadcast_id}/deliveries")
async def broadcast_deliveries(
    broadcast_id: str,
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "communication"])),
):
    """Détail des livraisons pour un broadcast (Partie 2.C — enrichissement UI)."""
    b = await db.broadcasts.find_one({"id": broadcast_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Broadcast introuvable")
    items = await db.broadcast_deliveries.find(
        {"broadcast_id": broadcast_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(2000)
    return {"broadcast": serialize(b), "deliveries": serialize_many(items)}


@messaging_router.post("/broadcasts/{broadcast_id}/retry-failed")
async def retry_broadcast_failed(
    broadcast_id: str,
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "communication"])),
):
    """Renvoie uniquement les livraisons en échec de ce broadcast (Partie 2.C)."""
    b = await db.broadcasts.find_one({"id": broadcast_id}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Broadcast introuvable")
    failed = await db.broadcast_deliveries.find(
        {"broadcast_id": broadcast_id, "success": False}, {"_id": 0},
    ).to_list(2000)
    if not failed:
        return {"ok": True, "retried": 0, "delivered": 0}
    from albarka_notifications import send_email as _send_email, send_whatsapp as _send_wa
    delivered = 0
    for d in failed:
        result: dict = {}
        try:
            if d.get("channel") == "email" and d.get("recipient_email"):
                mid = await _send_email(
                    to=d["recipient_email"], subject=b["subject"],
                    html=f"<p>{b['body']}</p>",
                )
                result = {"ok": bool(mid), "message_id": mid, "kind": "success" if mid else "http_error"}
            elif d.get("channel") == "whatsapp" and d.get("recipient_phone"):
                result = await _send_wa(
                    to_phone=d["recipient_phone"],
                    message=f"{b['subject']}\n\n{b['body']}",
                )
        except Exception:  # noqa: BLE001
            logger.exception("Retry-failed error on delivery %s", d.get("id"))
        if result.get("ok"):
            delivered += 1
            await db.broadcast_deliveries.update_one(
                {"id": d["id"]},
                {"$set": {
                    "success": True,
                    "message_id": result.get("message_id"),
                    "kind": result.get("kind"),
                    "retried_at": datetime.now(timezone.utc).isoformat(),
                }},
            )
    if delivered:
        await db.broadcasts.update_one(
            {"id": broadcast_id},
            {"$inc": {"delivered_count": delivered}},
        )
    return {"ok": True, "retried": len(failed), "delivered": delivered}
