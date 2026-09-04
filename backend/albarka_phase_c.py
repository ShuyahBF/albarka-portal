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

import logging
import secrets
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field, field_validator

from albarka_auth import get_current_user, require_roles, require_staff
from albarka_models import is_client, tenant_id_of
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.phase_c")

# ==========================================================================
# 8a — Chat interne
# ==========================================================================
chat_router = APIRouter(prefix="/chat", tags=["Chat interne"])


class ChatMessageCreate(BaseModel):
    thread_id: str = Field(..., min_length=1, max_length=120)
    body: str = Field(..., min_length=1, max_length=4000)


async def _thread_visible(user: dict, thread_id: str) -> bool:
    """Client peut lire son propre thread `client:{tenant_id}` uniquement."""
    if not is_client(user):
        return True
    return thread_id == f"client:{tenant_id_of(user)}"


@chat_router.get("/messages")
async def list_chat_messages(
    thread_id: str,
    limit: int = 200,
    user: dict = Depends(get_current_user),
):
    if not await _thread_visible(user, thread_id):
        raise HTTPException(status_code=403, detail="Accès refusé")
    items = await db.chat_messages.find(
        {"thread_id": thread_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


@chat_router.post("/messages")
async def post_chat_message(
    payload: ChatMessageCreate, user: dict = Depends(get_current_user),
):
    if not await _thread_visible(user, payload.thread_id):
        raise HTTPException(status_code=403, detail="Accès refusé")
    doc = {
        "id": secrets.token_urlsafe(12),
        "thread_id": payload.thread_id,
        "body": payload.body,
        "author_id": user["id"],
        "author_name": user.get("full_name") or user.get("email"),
        "author_is_client": is_client(user),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.chat_messages.insert_one(doc.copy())
    await _log_platform_event(
        user=user, action="chat.post", entity_type="chat_thread",
        entity_id=payload.thread_id, meta={"len": len(payload.body)},
    )
    return serialize(doc)


@chat_router.get("/threads")
async def list_chat_threads(user: dict = Depends(require_staff())):
    """Liste distincts des thread_id + dernier message + auteur."""
    threads = await db.chat_messages.aggregate([
        {"$sort": {"created_at": -1}},
        {"$group": {
            "_id": "$thread_id",
            "last_at": {"$first": "$created_at"},
            "last_author": {"$first": "$author_name"},
            "last_body": {"$first": "$body"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"last_at": -1}},
        {"$limit": 200},
    ]).to_list(200)
    return [{
        "thread_id": t["_id"], "last_at": t["last_at"],
        "last_author": t["last_author"], "last_body": t["last_body"][:120],
        "count": t["count"],
    } for t in threads]


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


@billing_router.get("/invoices")
async def list_invoices(
    tenant_id: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if status: q["status"] = status
    items = await db.invoices.find(q, {"_id": 0}).sort("created_at", -1).to_list(500)
    return serialize_many(items)


@billing_router.post("/invoices")
async def create_invoice(payload: InvoiceCreate, user: dict = Depends(require_staff())):
    items = [i.model_dump() for i in payload.items]
    totals = _invoice_totals(items)
    # Numéro : FAC-YYYYMM-NNNN (compteur mensuel global)
    month_key = datetime.now(timezone.utc).strftime("%Y%m")
    key = f"invoice:{month_key}"
    res = await db.report_series.find_one_and_update(
        {"key": key},
        {"$inc": {"seq": 1}, "$setOnInsert": {"kind": "invoice", "month_key": month_key}},
        upsert=True, return_document=True,
    )
    seq = int(res.get("seq") or 1)
    number = f"FAC-{month_key}-{seq:04d}"
    doc = {
        "id": secrets.token_urlsafe(12),
        "number": number,
        "tenant_id": payload.tenant_id,
        "title": payload.title,
        "items": items,
        "currency": payload.currency,
        "due_date": payload.due_date,
        "notes": payload.notes,
        "status": "unpaid",
        "paid_amount": 0.0,
        **totals,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.invoices.insert_one(doc.copy())
    await _log_platform_event(user=user, action="invoice.create",
                              entity_type="invoice", entity_id=doc["id"],
                              meta={"total": doc["total"], "number": number})
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


@billing_router.get("/payments")
async def list_payments(
    tenant_id: Optional[str] = None,
    invoice_id: Optional[str] = None,
    user: dict = Depends(require_staff()),
):
    q = {}
    if tenant_id: q["tenant_id"] = tenant_id
    if invoice_id: q["invoice_id"] = invoice_id
    items = await db.payments.find(q, {"_id": 0}).sort("paid_at", -1).to_list(1000)
    return serialize_many(items)


@billing_router.get("/summary")
async def billing_summary(user: dict = Depends(require_staff())):
    """Agrégat rapide : total facturé, total payé, impayé."""
    invoices = await db.invoices.find({}, {"_id": 0, "total": 1, "paid_amount": 1, "status": 1}).to_list(2000)
    total = sum(float(i.get("total", 0)) for i in invoices)
    paid = sum(float(i.get("paid_amount", 0)) for i in invoices)
    unpaid_count = sum(1 for i in invoices if i.get("status") != "paid")
    return {
        "invoice_count": len(invoices),
        "total_billed": round(total, 2),
        "total_paid": round(paid, 2),
        "outstanding": round(total - paid, 2),
        "unpaid_count": unpaid_count,
    }


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
    return serialize(doc)


# ==========================================================================
# 10 — Platform logs (audit)
# ==========================================================================
logs_router = APIRouter(prefix="/platform-logs", tags=["Logs plateforme"])
_LOG_ROLES = ["superviseur", "direction", "administrateur"]


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
    items = await db.platform_logs.find(q, {"_id": 0}).sort("created_at", -1).to_list(min(max(limit, 1), 500))
    return serialize_many(items)


# ==========================================================================
# 11 — Bibliothèque archives
# ==========================================================================
archives_router = APIRouter(prefix="/archives", tags=["Archives"])


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
    user: dict = Depends(require_staff()),
):
    query: dict = {}
    if category: query["category"] = category
    if tag: query["tags"] = tag
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
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "secretariat"])),
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
            mid = None
            try:
                mid = await _send_wa(
                    to_phone=phone,
                    message=f"{payload.subject}\n\n{payload.body}",
                )
            except Exception:  # noqa: BLE001
                logger.exception("Broadcast WA error to %s", phone)
            deliveries.append({
                "id": secrets.token_urlsafe(12), "broadcast_id": bid,
                "recipient_id": r["id"], "recipient_phone": phone,
                "channel": "whatsapp", "message_id": mid,
                "success": bool(mid),
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
    user: dict = Depends(require_roles(["superviseur", "direction", "administrateur", "secretariat"])),
):
    items = await db.broadcasts.find({}, {"_id": 0}).sort("created_at", -1).to_list(200)
    return serialize_many(items)
