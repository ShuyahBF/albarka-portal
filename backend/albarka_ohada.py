"""Phase D — Module comptabilité OHADA (SYSCOHADA révisé).

MVP compact :
  - Plan comptable (classes 1 à 8, PCG SYSCOHADA)
  - Journal d'écritures (double partie stricte : sum(débits) == sum(crédits))
  - Grand livre par compte
  - Balance de vérification

Toutes les données sont cloisonnées par `tenant_id` (client) — un cabinet
peut donc gérer plusieurs clients OHADA en parallèle.
"""
from __future__ import annotations

import logging
import re
import secrets
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator

from albarka_auth import require_roles
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.ohada")

# =====================================================================
# Rôles autorisés (cabinet côté comptabilité)
# =====================================================================
_OHADA_ROLES = [
    "superviseur", "direction", "administrateur",
    "comptable", "aide_comptable", "fiscaliste",
]
_VALIDATE_ROLES = ["superviseur", "direction", "administrateur", "comptable"]

# =====================================================================
# Plan comptable SYSCOHADA — noyau minimal (extrait). Les cabinets
# peuvent enrichir via POST /accounting/accounts.
# =====================================================================
DEFAULT_ACCOUNTS: list[dict] = [
    # Classe 1 — Capitaux
    {"code": "101", "label": "Capital social", "class": 1, "type": "passif"},
    {"code": "106", "label": "Réserves", "class": 1, "type": "passif"},
    {"code": "121", "label": "Résultat net de l'exercice", "class": 1, "type": "passif"},
    {"code": "162", "label": "Emprunts", "class": 1, "type": "passif"},
    # Classe 2 — Immobilisations
    {"code": "211", "label": "Terrains", "class": 2, "type": "actif"},
    {"code": "213", "label": "Bâtiments", "class": 2, "type": "actif"},
    {"code": "244", "label": "Matériel et mobilier", "class": 2, "type": "actif"},
    {"code": "245", "label": "Matériel de transport", "class": 2, "type": "actif"},
    # Classe 3 — Stocks
    {"code": "311", "label": "Marchandises", "class": 3, "type": "actif"},
    {"code": "321", "label": "Matières premières", "class": 3, "type": "actif"},
    # Classe 4 — Tiers
    {"code": "401", "label": "Fournisseurs", "class": 4, "type": "passif"},
    {"code": "411", "label": "Clients", "class": 4, "type": "actif"},
    {"code": "421", "label": "Personnel — rémunérations dues", "class": 4, "type": "passif"},
    {"code": "431", "label": "Sécurité sociale (CNSS)", "class": 4, "type": "passif"},
    {"code": "441", "label": "État — impôt sur le résultat", "class": 4, "type": "passif"},
    {"code": "443", "label": "État — TVA facturée", "class": 4, "type": "passif"},
    {"code": "445", "label": "État — TVA déductible", "class": 4, "type": "actif"},
    # Classe 5 — Trésorerie
    {"code": "521", "label": "Banques", "class": 5, "type": "actif"},
    {"code": "531", "label": "Caisse", "class": 5, "type": "actif"},
    # Classe 6 — Charges
    {"code": "601", "label": "Achats de marchandises", "class": 6, "type": "charge"},
    {"code": "605", "label": "Autres achats", "class": 6, "type": "charge"},
    {"code": "622", "label": "Locations et charges locatives", "class": 6, "type": "charge"},
    {"code": "641", "label": "Impôts et taxes", "class": 6, "type": "charge"},
    {"code": "661", "label": "Charges de personnel", "class": 6, "type": "charge"},
    {"code": "671", "label": "Frais financiers", "class": 6, "type": "charge"},
    # Classe 7 — Produits
    {"code": "701", "label": "Ventes de marchandises", "class": 7, "type": "produit"},
    {"code": "706", "label": "Prestations de services", "class": 7, "type": "produit"},
    {"code": "758", "label": "Autres produits divers", "class": 7, "type": "produit"},
    # Classe 8 — Résultat
    {"code": "801", "label": "Engagements donnés", "class": 8, "type": "hors_bilan"},
]

router = APIRouter(prefix="/accounting", tags=["Comptabilité OHADA"])


# ---------------------------------------------------------------------
# Comptes
# ---------------------------------------------------------------------
class AccountCreate(BaseModel):
    tenant_id: str
    code: str = Field(..., min_length=2, max_length=12)
    label: str = Field(..., min_length=1, max_length=200)
    account_class: int = Field(..., ge=1, le=9, alias="class")
    type: str = Field(..., description="actif/passif/charge/produit/hors_bilan")
    parent_code: Optional[str] = None

    model_config = {"populate_by_name": True}

    @field_validator("code")
    @classmethod
    def _valid_code(cls, v):
        if not re.match(r"^[0-9A-Z\.]+$", v):
            raise ValueError("code doit contenir uniquement chiffres/lettres majuscules")
        return v

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v):
        if v not in ("actif", "passif", "charge", "produit", "hors_bilan"):
            raise ValueError("type invalide")
        return v


@router.post("/seed-plan")
async def seed_plan(tenant_id: str, user: dict = Depends(require_roles(_OHADA_ROLES))):
    """Insère le plan comptable SYSCOHADA par défaut pour ce client si absent."""
    existing = await db.accounting_accounts.count_documents({"tenant_id": tenant_id})
    if existing:
        return {"ok": True, "already_seeded": True, "count": existing}
    docs = [{
        "id": secrets.token_urlsafe(12), "tenant_id": tenant_id,
        "code": a["code"], "label": a["label"],
        "class": a["class"], "type": a["type"],
        "parent_code": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    } for a in DEFAULT_ACCOUNTS]
    await db.accounting_accounts.insert_many(docs)
    return {"ok": True, "seeded": len(docs)}


@router.get("/accounts")
async def list_accounts(
    tenant_id: str,
    account_class: Optional[int] = None,
    q: Optional[str] = None,
    user: dict = Depends(require_roles(_OHADA_ROLES)),
):
    query: dict = {"tenant_id": tenant_id}
    if account_class:
        query["class"] = account_class
    if q:
        query["$or"] = [
            {"code": {"$regex": q, "$options": "i"}},
            {"label": {"$regex": q, "$options": "i"}},
        ]
    items = await db.accounting_accounts.find(query, {"_id": 0}).sort("code", 1).to_list(2000)
    return serialize_many(items)


@router.post("/accounts")
async def create_account(payload: AccountCreate, user: dict = Depends(require_roles(_OHADA_ROLES))):
    existing = await db.accounting_accounts.find_one({
        "tenant_id": payload.tenant_id, "code": payload.code,
    })
    if existing:
        raise HTTPException(status_code=409, detail=f"Compte {payload.code} existe déjà")
    doc = {
        "id": secrets.token_urlsafe(12),
        "tenant_id": payload.tenant_id,
        "code": payload.code,
        "label": payload.label,
        "class": payload.account_class,
        "type": payload.type,
        "parent_code": payload.parent_code,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.accounting_accounts.insert_one(doc.copy())
    return serialize(doc)


# ---------------------------------------------------------------------
# Journaux
# ---------------------------------------------------------------------
class EntryLine(BaseModel):
    account_code: str
    debit: float = 0
    credit: float = 0
    label: Optional[str] = None

    @field_validator("debit", "credit")
    @classmethod
    def _non_negative(cls, v):
        if v < 0:
            raise ValueError("debit/credit doivent être ≥ 0")
        return v


class JournalEntryCreate(BaseModel):
    tenant_id: str
    journal: str = Field("OD", description="OD/BQ/CA/VE/AC — journal auxiliaire")
    entry_date: str = Field(..., description="YYYY-MM-DD")
    label: str = Field(..., min_length=1, max_length=200)
    reference: Optional[str] = None
    lines: List[EntryLine] = Field(..., min_length=2)

    @field_validator("entry_date")
    @classmethod
    def _valid_date(cls, v):
        try:
            date.fromisoformat(v[:10])
        except ValueError:
            raise ValueError("entry_date invalide (YYYY-MM-DD)")
        return v[:10]


async def _fetch_account_codes(tenant_id: str, codes: List[str]) -> set[str]:
    docs = await db.accounting_accounts.find(
        {"tenant_id": tenant_id, "code": {"$in": codes}},
        {"_id": 0, "code": 1},
    ).to_list(len(codes))
    return {d["code"] for d in docs}


@router.post("/entries")
async def create_entry(payload: JournalEntryCreate, user: dict = Depends(require_roles(_OHADA_ROLES))):
    """Crée une écriture non validée (statut `draft`). Double partie stricte."""
    total_debit = round(sum(l.debit for l in payload.lines), 2)
    total_credit = round(sum(l.credit for l in payload.lines), 2)
    if abs(total_debit - total_credit) > 0.01:
        raise HTTPException(
            status_code=400,
            detail=f"Écriture déséquilibrée : débits={total_debit}, crédits={total_credit}",
        )
    if total_debit <= 0:
        raise HTTPException(status_code=400, detail="Montant total nul")
    # Chaque ligne doit être soit débit, soit crédit — pas les deux à la fois.
    for i, l in enumerate(payload.lines):
        if l.debit > 0 and l.credit > 0:
            raise HTTPException(
                status_code=400,
                detail=f"Ligne {i+1} : une écriture est soit débitée soit créditée",
            )
    # Comptes doivent exister pour ce tenant
    codes = [l.account_code for l in payload.lines]
    known = await _fetch_account_codes(payload.tenant_id, codes)
    missing = [c for c in codes if c not in known]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Compte(s) inconnu(s) : {sorted(set(missing))}",
        )
    # Numérotation par (tenant, année)
    year = payload.entry_date[:4]
    key = f"entry:{payload.tenant_id}:{year}"
    seq_doc = await db.report_series.find_one_and_update(
        {"key": key},
        {"$inc": {"seq": 1},
         "$setOnInsert": {"kind": "accounting_entry", "tenant_id": payload.tenant_id, "year": year}},
        upsert=True, return_document=True,
    )
    seq = int(seq_doc.get("seq") or 1)
    number = f"{payload.journal}-{year}-{seq:06d}"
    doc = {
        "id": secrets.token_urlsafe(12),
        "number": number,
        "tenant_id": payload.tenant_id,
        "journal": payload.journal,
        "entry_date": payload.entry_date,
        "label": payload.label,
        "reference": payload.reference,
        "lines": [l.model_dump() for l in payload.lines],
        "total_debit": total_debit,
        "total_credit": total_credit,
        "status": "draft",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": user["id"],
    }
    await db.accounting_entries.insert_one(doc.copy())
    return serialize(doc)


@router.post("/entries/{entry_id}/validate")
async def validate_entry(entry_id: str, user: dict = Depends(require_roles(_VALIDATE_ROLES))):
    entry = await db.accounting_entries.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Écriture introuvable")
    if entry["status"] == "validated":
        return serialize(entry)
    await db.accounting_entries.update_one(
        {"id": entry_id},
        {"$set": {
            "status": "validated",
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "validated_by": user["id"],
        }},
    )
    updated = await db.accounting_entries.find_one({"id": entry_id}, {"_id": 0})
    return serialize(updated)


@router.delete("/entries/{entry_id}")
async def delete_entry(entry_id: str, user: dict = Depends(require_roles(_VALIDATE_ROLES))):
    entry = await db.accounting_entries.find_one({"id": entry_id}, {"_id": 0})
    if not entry:
        raise HTTPException(status_code=404, detail="Écriture introuvable")
    if entry.get("status") == "validated":
        raise HTTPException(status_code=400, detail="Impossible de supprimer une écriture validée (contre-passer)")
    await db.accounting_entries.delete_one({"id": entry_id})
    return {"ok": True, "id": entry_id}


@router.get("/entries")
async def list_entries(
    tenant_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    journal: Optional[str] = None,
    status: Optional[str] = None,
    user: dict = Depends(require_roles(_OHADA_ROLES)),
):
    q: dict = {"tenant_id": tenant_id}
    if journal: q["journal"] = journal
    if status: q["status"] = status
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["entry_date"] = rng
    items = await db.accounting_entries.find(q, {"_id": 0}).sort("entry_date", -1).to_list(1000)
    return serialize_many(items)


# ---------------------------------------------------------------------
# Grand livre & balance
# ---------------------------------------------------------------------
@router.get("/ledger/{account_code}")
async def account_ledger(
    account_code: str, tenant_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_roles(_OHADA_ROLES)),
):
    account = await db.accounting_accounts.find_one(
        {"tenant_id": tenant_id, "code": account_code}, {"_id": 0},
    )
    if not account:
        raise HTTPException(status_code=404, detail=f"Compte {account_code} introuvable")
    q: dict = {"tenant_id": tenant_id, "status": "validated"}
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["entry_date"] = rng
    entries = await db.accounting_entries.find(q, {"_id": 0}).sort("entry_date", 1).to_list(5000)
    rows = []
    running = 0.0
    for e in entries:
        for i, line in enumerate(e.get("lines") or []):
            if line.get("account_code") != account_code:
                continue
            debit = float(line.get("debit", 0))
            credit = float(line.get("credit", 0))
            running += debit - credit
            rows.append({
                "entry_id": e["id"], "entry_number": e["number"],
                "entry_date": e["entry_date"], "journal": e["journal"],
                "label": line.get("label") or e["label"],
                "debit": debit, "credit": credit, "balance": round(running, 2),
            })
    return {
        "account": serialize(account),
        "movements": rows,
        "balance": round(running, 2),
        "total_debit": round(sum(r["debit"] for r in rows), 2),
        "total_credit": round(sum(r["credit"] for r in rows), 2),
    }


@router.get("/trial-balance")
async def trial_balance(
    tenant_id: str,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    user: dict = Depends(require_roles(_OHADA_ROLES)),
):
    """Balance de vérification (comptes validés)."""
    accounts = await db.accounting_accounts.find(
        {"tenant_id": tenant_id}, {"_id": 0},
    ).sort("code", 1).to_list(2000)
    q: dict = {"tenant_id": tenant_id, "status": "validated"}
    if date_from or date_to:
        rng = {}
        if date_from: rng["$gte"] = date_from
        if date_to: rng["$lte"] = date_to
        q["entry_date"] = rng
    entries = await db.accounting_entries.find(q, {"_id": 0}).to_list(20000)
    agg: dict[str, dict] = {a["code"]: {"debit": 0.0, "credit": 0.0} for a in accounts}
    for e in entries:
        for line in e.get("lines") or []:
            code = line.get("account_code")
            if code not in agg:
                agg[code] = {"debit": 0.0, "credit": 0.0}
            agg[code]["debit"] += float(line.get("debit", 0))
            agg[code]["credit"] += float(line.get("credit", 0))
    rows = []
    total_debit = 0.0
    total_credit = 0.0
    for a in accounts:
        stats = agg.get(a["code"], {"debit": 0.0, "credit": 0.0})
        d = round(stats["debit"], 2)
        c = round(stats["credit"], 2)
        balance = round(d - c, 2)
        total_debit += d
        total_credit += c
        rows.append({
            "code": a["code"], "label": a["label"], "class": a["class"],
            "debit": d, "credit": c,
            "debit_balance": balance if balance > 0 else 0,
            "credit_balance": -balance if balance < 0 else 0,
        })
    return {
        "rows": rows,
        "total_debit": round(total_debit, 2),
        "total_credit": round(total_credit, 2),
        "balanced": abs(total_debit - total_credit) < 0.01,
    }
