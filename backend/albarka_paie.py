"""PAIE — modèles de configuration, bulletins et livre de paie (lot 8).

Le cabinet calcule la paie de SON PROPRE PERSONNEL (employeur « cabinet ») et
celle de SES CLIENTS (employeur = compte client).

  - MODÈLES DE CONFIGURATION (indépendants des employeurs) : jeux complets de
    paramètres (barème IUTS, CNSS, exonérations, abattements, charges de
    famille, ancienneté, soutien patriotique, charges patronales, arrondis).
    On les modifie, on clique « Appliquer » ; « Restaurer les valeurs par
    défaut » remet les paramètres par défaut (Burkina Faso). Un modèle
    « Burkina Faso — standard » est créé au premier démarrage.
  - CONFIGURATION D'UN EMPLOYEUR : le modèle utilisé + une personnalisation
    facultative propre à cet employeur (« Restaurer les valeurs du modèle »),
    et son en-tête de bulletin (raison sociale, adresse, téléphone, n° CNSS).
  - FICHE PAIE DU SALARIÉ : catégorie, charges de famille, date d'embauche,
    indemnités (exonérées ou non), mode « brut → net » ou « net négocié → brut ».
  - BULLETINS du mois (brouillon → validé), PDF avec QR code de vérification.
  - LIVRE DE PAIE du mois : tous les salariés, retenues, net à payer et
    CHARGES PATRONALES (CNSS employeur, TPA) ; PDF et Excel (CSV).

Collections : paie_modeles, paie_employeurs, paie_bulletins (+ employees).
"""
from __future__ import annotations

import csv
import io
import re
import secrets
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from albarka_auth import require_roles
from albarka_docgen import MONTHS_FR, fcfa, new_verify_token, now_iso, qr_png, verify_url
from albarka_paie_moteur import DEFAULT_PARAMS, base_for_net, compute_payslip, normalize_params
from db import db

router = APIRouter(prefix="/hr/paie", tags=["RH & Paie — bulletins"])
# Lot 10 : la DG a les mêmes droits que la Direction (même menu, règle du lot 5).
HR_ROLES = ["superviseur", "direction", "dg", "administrateur", "rh"]
CABINET_ID = "cabinet"                       # employeur « personnel du cabinet »
SYSTEM_TEMPLATE_NAME = "Burkina Faso — standard"


def _month_ok(v: str) -> str:
    if not re.match(r"^\d{4}-(0[1-9]|1[0-2])$", v or ""):
        raise HTTPException(status_code=400, detail="Mois attendu au format AAAA-MM")
    return v


def period_label(month: str) -> str:
    y, m = month.split("-")
    return f"{MONTHS_FR[int(m) - 1].upper()} {y}"


def period_bounds(month: str) -> tuple[str, str]:
    """(« 01/07/2024 », « 31/07/2024 »)."""
    import calendar
    y, m = map(int, month.split("-"))
    return f"01/{m:02d}/{y}", f"{calendar.monthrange(y, m)[1]:02d}/{m:02d}/{y}"


def _clean_params(params: Optional[dict]) -> dict:
    try:
        return normalize_params(params)
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ==========================================================================
# Modèles de configuration
# ==========================================================================
class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field("", max_length=500)
    params: Optional[dict] = None                # absent = valeurs par défaut


# Base pour laquelle l'initialisation est déjà faite : on ne la refait pas
# à chaque requête (index + modèle créés une seule fois par processus).
_SETUP_DONE_FOR = None


async def ensure_paie_setup() -> None:
    """Index et modèle « Burkina Faso — standard » (au premier démarrage)."""
    global _SETUP_DONE_FOR
    if _SETUP_DONE_FOR is db:
        return
    await db.paie_bulletins.create_index([("employer_id", 1), ("period_month", 1), ("employee_id", 1)], unique=True)
    await db.paie_employeurs.create_index("employer_id", unique=True)
    if not await db.paie_modeles.find_one({}, {"_id": 0, "id": 1}):
        # upsert sur un identifiant fixe : jamais deux modèles standard, même si
        # deux démarrages arrivent en même temps
        await db.paie_modeles.update_one({"id": "bf-standard"}, {"$setOnInsert": {
            "id": "bf-standard", "name": SYSTEM_TEMPLATE_NAME,
            "description": "Barème IUTS, CNSS 5,5 % plafonnée, exonérations logement/transport/fonction, "
                           "abattement 25 %, soutien patriotique 1 % (valeurs du fichier du cabinet).",
            "params": normalize_params(None), "is_default": True, "created_at": now_iso(), "updated_at": now_iso()}},
            upsert=True)
    _SETUP_DONE_FOR = db


async def _template(tid: str) -> dict:
    t = await db.paie_modeles.find_one({"id": tid}, {"_id": 0})
    if not t:
        raise HTTPException(status_code=404, detail="Modèle introuvable")
    return t


async def _default_template() -> dict:
    await ensure_paie_setup()
    return (await db.paie_modeles.find_one({"is_default": True}, {"_id": 0})
            or await db.paie_modeles.find_one({}, {"_id": 0}, sort=[("created_at", 1)]))


@router.get("/defaults")
async def get_defaults(user: dict = Depends(require_roles(HR_ROLES))):
    """Valeurs par défaut (bouton « Restaurer les valeurs par défaut »)."""
    return {"params": normalize_params(DEFAULT_PARAMS)}


@router.get("/modeles")
async def list_templates(user: dict = Depends(require_roles(HR_ROLES))):
    await ensure_paie_setup()
    items = await db.paie_modeles.find({}, {"_id": 0}).sort("created_at", 1).to_list(200)
    usage = {}
    async for e in db.paie_employeurs.find({}, {"_id": 0, "template_id": 1}):
        usage[e.get("template_id")] = usage.get(e.get("template_id"), 0) + 1
    for t in items:
        t["employers_count"] = usage.get(t["id"], 0)
    return {"items": items}


@router.post("/modeles")
async def create_template(payload: TemplateIn, user: dict = Depends(require_roles(HR_ROLES))):
    if await db.paie_modeles.find_one({"name": payload.name.strip()}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=409, detail="Un modèle porte déjà ce nom")
    doc = {"id": secrets.token_hex(8), "name": payload.name.strip(), "description": payload.description.strip(),
           "params": _clean_params(payload.params), "is_default": False, "created_at": now_iso(),
           "updated_at": now_iso(), "updated_by": user.get("email")}
    await db.paie_modeles.insert_one(doc.copy())
    return doc


@router.put("/modeles/{tid}")
async def update_template(tid: str, payload: TemplateIn, user: dict = Depends(require_roles(HR_ROLES))):
    """« Appliquer » : enregistre les paramètres du modèle (employeurs qui l'utilisent
    sans personnalisation : pris en compte pour les prochains calculs)."""
    await _template(tid)
    other = await db.paie_modeles.find_one({"name": payload.name.strip(), "id": {"$ne": tid}}, {"_id": 0, "id": 1})
    if other:
        raise HTTPException(status_code=409, detail="Un autre modèle porte déjà ce nom")
    await db.paie_modeles.update_one({"id": tid}, {"$set": {
        "name": payload.name.strip(), "description": payload.description.strip(),
        "params": _clean_params(payload.params), "updated_at": now_iso(), "updated_by": user.get("email")}})
    return await _template(tid)


@router.post("/modeles/{tid}/restore-defaults")
async def restore_template_defaults(tid: str, user: dict = Depends(require_roles(HR_ROLES))):
    """« Restaurer les valeurs par défaut » du modèle."""
    await _template(tid)
    await db.paie_modeles.update_one({"id": tid}, {"$set": {"params": normalize_params(None), "updated_at": now_iso(),
                                                             "updated_by": user.get("email")}})
    return await _template(tid)


@router.post("/modeles/{tid}/duplicate")
async def duplicate_template(tid: str, user: dict = Depends(require_roles(HR_ROLES))):
    t = await _template(tid)
    name, n = f"{t['name']} (copie)", 2
    while await db.paie_modeles.find_one({"name": name}, {"_id": 0, "id": 1}):
        name, n = f"{t['name']} (copie {n})", n + 1
    doc = {**t, "id": secrets.token_hex(8), "name": name, "is_default": False, "created_at": now_iso(),
           "updated_at": now_iso(), "updated_by": user.get("email")}
    await db.paie_modeles.insert_one(doc.copy())
    doc.pop("employers_count", None)
    return doc


@router.post("/modeles/{tid}/set-default")
async def set_default_template(tid: str, user: dict = Depends(require_roles(HR_ROLES))):
    """Modèle proposé aux employeurs qui n'en ont pas choisi."""
    await _template(tid)
    await db.paie_modeles.update_many({}, {"$set": {"is_default": False}})
    await db.paie_modeles.update_one({"id": tid}, {"$set": {"is_default": True}})
    return {"ok": True}


@router.delete("/modeles/{tid}")
async def delete_template(tid: str, user: dict = Depends(require_roles(HR_ROLES))):
    t = await _template(tid)
    if t.get("is_default"):
        raise HTTPException(status_code=400, detail="Le modèle par défaut ne peut pas être supprimé")
    if await db.paie_employeurs.count_documents({"template_id": tid}):
        raise HTTPException(status_code=409, detail="Ce modèle est utilisé par des employeurs : choisissez-leur un autre modèle d'abord")
    await db.paie_modeles.delete_one({"id": tid})
    return {"ok": True}


# ==========================================================================
# Employeurs (cabinet + clients) et leur configuration
# ==========================================================================
class EmployerConfigIn(BaseModel):
    template_id: Optional[str] = None
    custom_params: Optional[dict] = None         # None = paramètres du modèle
    display_name: str = Field("", max_length=200)
    address: str = Field("", max_length=300)
    phone: str = Field("", max_length=60)
    cnss_number: str = Field("", max_length=60)


async def _employer_identity(eid: str) -> Dict[str, str]:
    """Nom, adresse et téléphone par défaut d'un employeur."""
    if eid == CABINET_ID:
        s = await db.settings.find_one({"_id": "global"}, {"_id": 0, "cabinet_name": 1, "doc_settings": 1}) or {}
        return {"name": s.get("cabinet_name") or "Cabinet ALBARKA", "address": (s.get("doc_settings") or {}).get("city", ""),
                "phone": "", "kind": "cabinet"}
    u = await db.users.find_one({"id": eid}, {"_id": 0, "company": 1, "full_name": 1, "phone": 1, "roles": 1})
    if not u or "client" not in (u.get("roles") or []):
        raise HTTPException(status_code=404, detail="Employeur introuvable")
    kyc = await db.client_kyc.find_one({"tenant_id": eid}, {"_id": 0, "business_name": 1, "address": 1}) or {}
    return {"name": kyc.get("business_name") or u.get("company") or u.get("full_name") or "", "address": kyc.get("address") or "",
            "phone": u.get("phone") or "", "kind": "client"}


async def employer_config(eid: str, strict: bool = True) -> Dict[str, Any]:
    """Configuration effective : modèle, personnalisation, paramètres utilisés, en-tête.
    strict=False : un client supprimé reste lisible (livre de paie, bulletins passés)
    avec le nom mémorisé sur ses derniers bulletins."""
    try:
        ident = await _employer_identity(eid)
    except HTTPException:
        if strict:
            raise
        last = await db.paie_bulletins.find_one({"employer_id": eid}, {"_id": 0, "employer": 1},
                                                sort=[("period_month", -1)]) or {}
        snap = last.get("employer") or {}
        ident = {"name": snap.get("name") or eid, "address": snap.get("address") or "",
                 "phone": snap.get("phone") or "", "kind": "client"}
    cfg = await db.paie_employeurs.find_one({"employer_id": eid}, {"_id": 0}) or {}
    tpl = None
    if cfg.get("template_id"):
        tpl = await db.paie_modeles.find_one({"id": cfg["template_id"]}, {"_id": 0})
    tpl = tpl or await _default_template()
    custom = cfg.get("custom_params")
    return {
        "employer_id": eid, "kind": ident["kind"],
        "name": cfg.get("display_name") or ident["name"], "default_name": ident["name"],
        "display_name": cfg.get("display_name") or "", "address": cfg.get("address") or ident["address"],
        "phone": cfg.get("phone") or ident["phone"], "cnss_number": cfg.get("cnss_number") or "",
        "template_id": tpl["id"], "template_name": tpl["name"],
        "chosen_template_id": cfg.get("template_id") or None,     # None = suit le modèle par défaut
        "customized": custom is not None,
        "custom_params": custom, "params": normalize_params(custom if custom is not None else tpl["params"]),
    }


@router.get("/employeurs")
async def list_employers(user: dict = Depends(require_roles(HR_ROLES))):
    """Le cabinet (son personnel) puis les clients, avec leur modèle et leurs salariés."""
    cfgs = {c["employer_id"]: c async for c in db.paie_employeurs.find({}, {"_id": 0})}
    tpls = {t["id"]: t["name"] async for t in db.paie_modeles.find({}, {"_id": 0, "id": 1, "name": 1})}
    default = await _default_template()
    counts = {}
    async for e in db.employees.find({}, {"_id": 0, "tenant_id": 1}):
        counts[e.get("tenant_id")] = counts.get(e.get("tenant_id"), 0) + 1
    out = []
    cab = await _employer_identity(CABINET_ID)
    clients = await db.users.find({"roles": "client"}, {"_id": 0, "id": 1, "company": 1, "full_name": 1}).sort("company", 1).to_list(2000)
    rows = [{"employer_id": CABINET_ID, "name": cab["name"], "kind": "cabinet"}] + [
        {"employer_id": c["id"], "name": c.get("company") or c.get("full_name") or c["id"], "kind": "client"} for c in clients]
    for r in rows:
        cfg = cfgs.get(r["employer_id"]) or {}
        tid = cfg.get("template_id") or default["id"]
        out.append({**r, "name": cfg.get("display_name") or r["name"], "template_id": tid,
                    "template_name": tpls.get(tid, default["name"]), "customized": cfg.get("custom_params") is not None,
                    "employees_count": counts.get(r["employer_id"], 0)})
    return {"items": out}


@router.get("/employeurs/{eid}")
async def get_employer(eid: str, user: dict = Depends(require_roles(HR_ROLES))):
    return await employer_config(eid)


@router.put("/employeurs/{eid}")
async def put_employer(eid: str, payload: EmployerConfigIn, user: dict = Depends(require_roles(HR_ROLES))):
    """« Appliquer » : modèle choisi, personnalisation éventuelle, en-tête du bulletin."""
    await _employer_identity(eid)
    if payload.template_id:
        await _template(payload.template_id)
    custom = _clean_params(payload.custom_params) if payload.custom_params is not None else None
    await db.paie_employeurs.update_one({"employer_id": eid}, {"$set": {
        "employer_id": eid, "template_id": payload.template_id, "custom_params": custom,
        "display_name": payload.display_name.strip(), "address": payload.address.strip(), "phone": payload.phone.strip(),
        "cnss_number": payload.cnss_number.strip(), "updated_at": now_iso(), "updated_by": user.get("email")}}, upsert=True)
    return await employer_config(eid)


@router.post("/employeurs/{eid}/restore-template")
async def restore_employer_template(eid: str, user: dict = Depends(require_roles(HR_ROLES))):
    """« Restaurer les valeurs du modèle » : supprime la personnalisation de l'employeur."""
    await _employer_identity(eid)
    await db.paie_employeurs.update_one({"employer_id": eid}, {"$set": {"custom_params": None, "updated_at": now_iso()}},
                                        upsert=True)
    return await employer_config(eid)


# ==========================================================================
# Fiche paie du salarié
# ==========================================================================
class EmployeePaieIn(BaseModel):
    tenant_id: Optional[str] = None               # création : « cabinet » ou id du client
    full_name: str = Field(..., min_length=2, max_length=200)
    role: Optional[str] = Field(None, max_length=120)
    matricule: Optional[str] = Field(None, max_length=40)
    cnss_number: Optional[str] = Field(None, max_length=40)
    category: Optional[str] = Field(None, max_length=40)
    dependents: int = Field(0, ge=0, le=30)
    hire_date: Optional[str] = None
    pay_mode: str = "gross"                       # gross (brut → net) | net (net négocié → brut)
    base_salary: float = Field(0, ge=0)
    net_target: Optional[float] = Field(None, ge=0)
    allowances: Dict[str, float] = Field(default_factory=dict)
    non_exempt: List[str] = Field(default_factory=list)
    email: Optional[str] = None
    phone: Optional[str] = None


def _employee_fields(p: EmployeePaieIn) -> dict:
    if p.pay_mode not in ("gross", "net"):
        raise HTTPException(status_code=400, detail="Mode de paie inconnu")
    if p.pay_mode == "net" and not p.net_target:
        raise HTTPException(status_code=400, detail="Indiquez le salaire net négocié")
    if p.hire_date and not re.match(r"^\d{4}-\d{2}-\d{2}$", p.hire_date):
        raise HTTPException(status_code=400, detail="Date d'embauche attendue au format AAAA-MM-JJ")
    d = p.model_dump(exclude={"tenant_id"})
    d["allowances"] = {k: float(v) for k, v in (p.allowances or {}).items() if float(v or 0) > 0}
    d["full_name"] = p.full_name.strip()
    return d


@router.post("/employees")
async def create_employee(payload: EmployeePaieIn, user: dict = Depends(require_roles(HR_ROLES))):
    """Salarié du cabinet (tenant_id = « cabinet ») ou d'un client."""
    if not payload.tenant_id:
        raise HTTPException(status_code=400, detail="Choisissez l'employeur")
    await _employer_identity(payload.tenant_id)
    doc = {"id": secrets.token_urlsafe(12), "tenant_id": payload.tenant_id, **_employee_fields(payload),
           "created_at": now_iso(), "created_by": user["id"]}
    await db.employees.insert_one(doc.copy())
    return doc


@router.put("/employees/{emp_id}")
async def update_employee(emp_id: str, payload: EmployeePaieIn, user: dict = Depends(require_roles(HR_ROLES))):
    if not await db.employees.find_one({"id": emp_id}, {"_id": 0, "id": 1}):
        raise HTTPException(status_code=404, detail="Salarié introuvable")
    await db.employees.update_one({"id": emp_id}, {"$set": {**_employee_fields(payload), "updated_at": now_iso()}})
    return await db.employees.find_one({"id": emp_id}, {"_id": 0})


@router.get("/employees")
async def list_employees(employer_id: Optional[str] = None, user: dict = Depends(require_roles(HR_ROLES))):
    q = {"tenant_id": employer_id} if employer_id else {}
    return {"items": await db.employees.find(q, {"_id": 0}).sort("full_name", 1).to_list(2000)}


@router.delete("/employees/{emp_id}")
async def delete_employee(emp_id: str, user: dict = Depends(require_roles(HR_ROLES))):
    if await db.paie_bulletins.count_documents({"employee_id": emp_id, "status": "validated"}):
        raise HTTPException(status_code=409, detail="Ce salarié a des bulletins validés : il ne peut pas être supprimé")
    await db.paie_bulletins.delete_many({"employee_id": emp_id})
    await db.employees.delete_one({"id": emp_id})
    return {"ok": True}


# ==========================================================================
# Calcul et bulletins
# ==========================================================================
class SimulateIn(BaseModel):
    employer_id: Optional[str] = None
    params: Optional[dict] = None                 # paramètres en cours d'édition (aperçu)
    employee: dict = Field(default_factory=dict)
    period_month: Optional[str] = None


def _calc(emp_input: dict, params: dict, month: Optional[str]) -> dict:
    """Calcule un bulletin ; en mode « net négocié », cherche d'abord le salaire de base."""
    emp = dict(emp_input)
    if emp.get("pay_mode") == "net" and emp.get("net_target"):
        try:
            # Recherche sur la fiche seule : les primes du mois et une ancienneté
            # saisie s'ajoutent ensuite au net négocié (elles ne le réduisent pas).
            fiche = {**emp, "extras": [], "deductions": [], "seniority_amount": None}
            emp["base_salary"] = base_for_net(fiche, emp["net_target"], params, month)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    try:
        res = compute_payslip(emp, params, month)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    res["base_salary"] = float(emp.get("base_salary") or 0)
    return res


@router.post("/simulate")
async def simulate(payload: SimulateIn, user: dict = Depends(require_roles(HR_ROLES))):
    """Aperçu du calcul (écran des paramètres, fiche salarié)."""
    if payload.params is not None:
        params = _clean_params(payload.params)
    elif payload.employer_id:
        params = (await employer_config(payload.employer_id))["params"]
    else:
        params = normalize_params(None)
    return _calc(payload.employee, params, payload.period_month)


class BulletinVars(BaseModel):
    extras: List[dict] = Field(default_factory=list)          # primes du mois [{label, amount}]
    deductions: List[dict] = Field(default_factory=list)      # acomptes, prêts, autres [{label, amount}]
    seniority_amount: Optional[float] = Field(None, ge=0)     # vide = calculée
    notes: str = Field("", max_length=500)


class PrepareIn(BaseModel):
    employer_id: str
    period_month: str


def _snapshot(emp: dict) -> dict:
    keys = ("full_name", "role", "matricule", "cnss_number", "category", "dependents", "hire_date", "pay_mode",
            "base_salary", "net_target", "allowances", "non_exempt")
    return {k: emp.get(k) for k in keys}


def _clean_items(items: List[dict], default_label: str) -> List[dict]:
    out = []
    for it in items or []:
        try:
            amt = float(it.get("amount") or 0)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Montant invalide")
        if amt < 0:
            raise HTTPException(status_code=400, detail="Montant négatif interdit")
        if amt:
            out.append({"label": str(it.get("label") or default_label).strip()[:80], "amount": amt})
    return out


async def _compute_bulletin(b: dict, cfg: dict) -> dict:
    """(Re)calcule un bulletin brouillon depuis la fiche actuelle du salarié."""
    emp = await db.employees.find_one({"id": b["employee_id"]}, {"_id": 0}) or {}
    snap = _snapshot(emp) if emp else b.get("employee", {})
    v = b.get("variables") or {}
    inp = {**snap, "extras": v.get("extras") or [], "deductions": v.get("deductions") or [],
           "seniority_amount": v.get("seniority_amount")}
    res = _calc(inp, cfg["params"], b["period_month"])
    return {"employee": snap, "result": res, "params": cfg["params"], "template_name": cfg["template_name"],
            "customized": cfg["customized"],
            "employer": {k: cfg[k] for k in ("name", "address", "phone", "cnss_number")}, "updated_at": now_iso()}


@router.post("/bulletins/prepare")
async def prepare_month(payload: PrepareIn, user: dict = Depends(require_roles(HR_ROLES))):
    """Crée les bulletins du mois pour tous les salariés de l'employeur et
    recalcule les brouillons existants (les bulletins validés ne bougent pas)."""
    month = _month_ok(payload.period_month)
    cfg = await employer_config(payload.employer_id)
    emps = await db.employees.find({"tenant_id": payload.employer_id}, {"_id": 0}).to_list(2000)
    created = updated = 0
    for e in emps:
        b = await db.paie_bulletins.find_one({"employer_id": payload.employer_id, "period_month": month, "employee_id": e["id"]}, {"_id": 0})
        if b and b.get("status") == "validated":
            continue
        if not b:
            b = {"id": secrets.token_hex(8), "employer_id": payload.employer_id, "employee_id": e["id"], "period_month": month,
                 "status": "draft", "variables": {"extras": [], "deductions": [], "seniority_amount": None, "notes": ""},
                 "verify_token": new_verify_token(), "created_at": now_iso(), "created_by": user["id"]}
            b.update(await _compute_bulletin(b, cfg))
            try:
                await db.paie_bulletins.insert_one(b.copy())
            except DuplicateKeyError:       # préparation lancée deux fois en même temps
                continue
            created += 1
        else:
            await db.paie_bulletins.update_one({"id": b["id"]}, {"$set": await _compute_bulletin(b, cfg)})
            updated += 1
    return {"ok": True, "created": created, "updated": updated, "employees": len(emps)}


async def _bulletin(bid: str) -> dict:
    b = await db.paie_bulletins.find_one({"id": bid}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")
    return b


@router.get("/bulletins")
async def list_bulletins(employer_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    _month_ok(period_month)
    items = await db.paie_bulletins.find({"employer_id": employer_id, "period_month": period_month},
                                         {"_id": 0, "params": 0}).to_list(2000)
    items.sort(key=lambda b: (b.get("employee") or {}).get("full_name") or "")
    return {"items": items, "totals": _totals(items)}


@router.get("/bulletins/{bid}")
async def get_bulletin(bid: str, user: dict = Depends(require_roles(HR_ROLES))):
    return await _bulletin(bid)


@router.put("/bulletins/{bid}")
async def update_bulletin(bid: str, payload: BulletinVars, user: dict = Depends(require_roles(HR_ROLES))):
    """Éléments du mois (primes, retenues, ancienneté saisie) puis recalcul."""
    b = await _bulletin(bid)
    if b.get("status") == "validated":
        raise HTTPException(status_code=409, detail="Bulletin validé : rouvrez-le pour le modifier")
    b["variables"] = {"extras": _clean_items(payload.extras, "Prime"), "deductions": _clean_items(payload.deductions, "Retenue"),
                      "seniority_amount": payload.seniority_amount, "notes": payload.notes.strip()}
    cfg = await employer_config(b["employer_id"], strict=False)
    await db.paie_bulletins.update_one({"id": bid}, {"$set": {"variables": b["variables"], **await _compute_bulletin(b, cfg)}})
    return await _bulletin(bid)


@router.post("/bulletins/{bid}/validate")
async def validate_bulletin(bid: str, user: dict = Depends(require_roles(HR_ROLES))):
    await _bulletin(bid)
    await db.paie_bulletins.update_one({"id": bid}, {"$set": {"status": "validated", "validated_at": now_iso(),
                                                              "validated_by": user.get("email")}})
    return await _bulletin(bid)


@router.post("/bulletins/{bid}/reopen")
async def reopen_bulletin(bid: str, user: dict = Depends(require_roles(HR_ROLES))):
    await _bulletin(bid)
    await db.paie_bulletins.update_one({"id": bid}, {"$set": {"status": "draft"}, "$unset": {"validated_at": "", "validated_by": ""}})
    return await _bulletin(bid)


@router.delete("/bulletins/{bid}")
async def delete_bulletin(bid: str, user: dict = Depends(require_roles(HR_ROLES))):
    b = await _bulletin(bid)
    if b.get("status") == "validated":
        raise HTTPException(status_code=409, detail="Bulletin validé : rouvrez-le avant de le supprimer")
    await db.paie_bulletins.delete_one({"id": bid})
    return {"ok": True}


# ==========================================================================
# Livre de paie
# ==========================================================================
LEDGER_COLUMNS = [
    ("gross", "Brut"), ("cnss", "CNSS sal."), ("iuts", "IUTS net"), ("patriotic_support", "Soutien patr."),
    ("deductions_total", "Retenues"), ("net_to_pay", "Net à payer"), ("employer_total", "Charges patr."),
    ("employer_cost", "Coût total"),
]


def _totals(items: List[dict]) -> dict:
    t = {k: 0.0 for k, _ in LEDGER_COLUMNS}
    t["iuts_base"] = 0.0
    employer_detail: Dict[str, float] = {}
    for b in items:
        r = b.get("result") or {}
        for k in list(t):
            t[k] += float(r.get(k) or 0)
        for x in r.get("employer_charges") or []:
            employer_detail[x["label"]] = employer_detail.get(x["label"], 0) + float(x["amount"] or 0)
    t["count"] = len(items)
    t["employer_detail"] = [{"label": k, "amount": v} for k, v in employer_detail.items()]
    return t


@router.get("/livre")
async def ledger(employer_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    month = _month_ok(period_month)
    cfg = await employer_config(employer_id, strict=False)
    items = await db.paie_bulletins.find({"employer_id": employer_id, "period_month": month}, {"_id": 0, "params": 0}).to_list(2000)
    items.sort(key=lambda b: (b.get("employee") or {}).get("full_name") or "")
    return {"employer": {k: cfg[k] for k in ("employer_id", "name", "address", "phone", "cnss_number")},
            "period_month": month, "period_label": period_label(month),
            "rows": [{"id": b["id"], "status": b.get("status"), "full_name": (b.get("employee") or {}).get("full_name"),
                      "role": (b.get("employee") or {}).get("role"), **{k: (b.get("result") or {}).get(k) for k, _ in LEDGER_COLUMNS},
                      "employer_charges": (b.get("result") or {}).get("employer_charges") or []} for b in items],
            "totals": _totals(items), "columns": [{"key": k, "label": lbl} for k, lbl in LEDGER_COLUMNS]}


@router.get("/livre/csv")
async def ledger_csv(employer_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    data = await ledger(employer_id, period_month, user)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"Livre de paie — {data['employer']['name']} — {data['period_label']}"])
    w.writerow(["Salarié", "Fonction"] + [lbl for _, lbl in LEDGER_COLUMNS])
    for r in data["rows"]:
        w.writerow([r["full_name"], r.get("role") or ""] + [int(round(float(r.get(k) or 0))) for k, _ in LEDGER_COLUMNS])
    w.writerow(["TOTAL", ""] + [int(round(float(data["totals"].get(k) or 0))) for k, _ in LEDGER_COLUMNS])
    w.writerow([])
    w.writerow(["Charges patronales"])
    for x in data["totals"]["employer_detail"]:
        w.writerow([x["label"], "", int(round(x["amount"]))])
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", f"livre_de_paie_{data['employer']['name']}_{period_month}")[:80]
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{name}.csv"'})


# ==========================================================================
# PDF : bulletin et livre de paie
# ==========================================================================
def _money(v) -> str:
    return fcfa(v) if v not in (None, "") and float(v or 0) != 0 else ""


def build_bulletin_pdf(b: dict) -> bytes:
    """Bulletin au format du fichier du cabinet : en-tête employeur / salarié,
    rubriques (base, taux, gains, retenues), bases fiscales, net à payer, QR code."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Image as RLImage, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    green = colors.HexColor("#0F6B4A")
    st = {"h": ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=15, alignment=1, textColor=green),
          "b": ParagraphStyle("b", fontName="Helvetica", fontSize=8.8, leading=11.5),
          "bb": ParagraphStyle("bb", fontName="Helvetica-Bold", fontSize=8.8, leading=11.5),
          "s": ParagraphStyle("s", fontName="Helvetica-Oblique", fontSize=7.5, textColor=colors.HexColor("#64748B"), alignment=1)}
    e, r, emp = b.get("employer") or {}, b.get("result") or {}, b.get("employee") or {}
    d1, d2 = period_bounds(b["period_month"])
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=15 * mm, rightMargin=15 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                            title=f"Bulletin de paie {emp.get('full_name')} {b['period_month']}")
    P = lambda t, s="b": Paragraph(escape(str(t or "")), st[s])  # noqa: E731
    head = Table([
        [P("Employeur", "bb"), P(f"{period_label(b['period_month'])}", "bb"), P("Salarié", "bb")],
        [P(e.get("name"), "bb"), P(f"du {d1}"), P(emp.get("full_name"), "bb")],
        [P(e.get("address")), P(f"au {d2}"), P(emp.get("role") or "")],
        [P(f"Tél : {e.get('phone')}" if e.get("phone") else ""), P(""),
         P(" · ".join(x for x in [f"Matricule {emp['matricule']}" if emp.get("matricule") else "",
                                  f"N° CNSS {emp['cnss_number']}" if emp.get("cnss_number") else ""] if x))],
        [P(f"N° CNSS employeur : {e.get('cnss_number')}" if e.get("cnss_number") else ""), P(""),
         P(f"Charges familiales : {r.get('family_charges', 0)} · Ancienneté : {r.get('years_of_service', 0)} an(s)"
           + (f" · Catégorie : {emp['category']}" if emp.get("category") else ""))],
    ], colWidths=[70 * mm, 40 * mm, 70 * mm])
    head.setStyle(TableStyle([("BOX", (0, 0), (0, -1), 0.5, colors.grey), ("BOX", (2, 0), (2, -1), 0.5, colors.grey),
                              ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ALIGN", (1, 0), (1, -1), "CENTER")]))
    rows = [["Rubrique", "Base", "Taux", "Gains", "Retenues"]]

    def row_of(ln):
        gain = ln["amount"] if ln["kind"] == "gain" else None
        ret = ln["amount"] if ln["kind"] == "deduction" else None
        rate = f"{ln['rate']:g} %".replace(".", ",") if ln.get("rate") not in (None, "") else ""
        return [P(ln["label"]), _money(ln.get("base")), rate, _money(gain),
                ("− " + fcfa(-ret)) if ret is not None and ret < 0 else _money(ret)]
    # Ordre du modèle : gains, salaire brut, CNSS et IUTS, IUTS net, salaire net,
    # puis soutien patriotique et retenues du mois, enfin le net à payer.
    after_net = []
    for ln in r.get("lines") or []:
        if ln["code"] == "cnss":
            rows.append([P("Salaire brut", "bb"), "", "", fcfa(r.get("gross")), ""])
        if ln["code"] == "patriotic" or ln["code"].startswith("ded_"):
            after_net.append(ln)
            continue
        rows.append(row_of(ln))
    rows.append([P("IUTS net", "bb"), "", "", "", fcfa(r.get("iuts"))])
    if r.get("rounding_diff"):
        rows.append([P("Arrondi du net"), "", "", _money(r["rounding_diff"]) if r["rounding_diff"] > 0 else "",
                     _money(-r["rounding_diff"]) if r["rounding_diff"] < 0 else ""])
    rows.append([P("Salaire net", "bb"), "", "", fcfa(r.get("net")), ""])
    rows.extend(row_of(ln) for ln in after_net)
    t = Table(rows, colWidths=[72 * mm, 28 * mm, 16 * mm, 32 * mm, 32 * mm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.8), ("FONT", (1, 1), (-1, -1), "Helvetica", 8.8),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    fisc = Table([
        ["Contrôle CNSS (fiscal)", fcfa(r.get("cnss_fiscal")), "Salaire imposable IUTS", fcfa(r.get("taxable"))],
        ["Total exonérations", fcfa(r.get("exemptions_total")), f"Abattement forfaitaire ({r.get('flat_abatement_rate', 0):g} %)", fcfa(r.get("flat_abatement"))],
        ["Base IUTS", fcfa(r.get("iuts_base")), f"Abattement famille ({r.get('family_rate', 0):g} %)", fcfa(r.get("family_abatement"))],
    ], colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    fisc.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 7.8), ("TEXTCOLOR", (0, 0), (-1, -1), colors.HexColor("#475569")),
                              ("ALIGN", (1, 0), (1, -1), "RIGHT"), ("ALIGN", (3, 0), (3, -1), "RIGHT"),
                              ("BOX", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1"))]))
    pay = Table([[P("NET À PAYER", "bb"), fcfa(r.get("net_to_pay"))]], colWidths=[140 * mm, 40 * mm])
    pay.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#E5A24B")), ("FONT", (1, 0), (1, 0), "Helvetica-Bold", 11),
                             ("ALIGN", (1, 0), (1, 0), "RIGHT"), ("BOX", (0, 0), (-1, -1), 0.6, colors.grey)]))
    el = [Paragraph("BULLETIN DE PAIE", st["h"]), Spacer(1, 6), head, Spacer(1, 8), t, Spacer(1, 4), pay, Spacer(1, 6), fisc]
    notes = (b.get("variables") or {}).get("notes")
    if notes:
        el += [Spacer(1, 4), P(f"Observations : {notes}")]
    if b.get("verify_token"):
        qr = RLImage(io.BytesIO(qr_png(verify_url(b["verify_token"]), box=4)), width=22 * mm, height=22 * mm)
        el += [Spacer(1, 6), Table([[qr, P("Scannez ce code pour vérifier l'authenticité du bulletin. "
                                            + ("Bulletin validé." if b.get("status") == "validated" else "Brouillon (non validé)."))]],
                                   colWidths=[26 * mm, 154 * mm])]
    el += [Spacer(1, 8), Paragraph("Ce bulletin de salaire doit être conservé sans limitation de durée", st["s"])]
    doc.build(el)
    return buf.getvalue()


def build_ledger_pdf(data: dict) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    green = colors.HexColor("#0F6B4A")
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=13, textColor=green)
    s = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, textColor=colors.HexColor("#475569"))
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=7.8, leading=9.5)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=10 * mm, rightMargin=10 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
                            title=f"Livre de paie {data['employer']['name']} {data['period_month']}")
    rows = [["N°", "Salarié", "Fonction"] + [lbl for _, lbl in LEDGER_COLUMNS]]
    for i, r in enumerate(data["rows"], start=1):
        rows.append([str(i), Paragraph(escape(r["full_name"] or ""), cell), Paragraph(escape(r.get("role") or ""), cell)]
                    + [fcfa(r.get(k) or 0) for k, _ in LEDGER_COLUMNS])
    rows.append(["", "TOTAL", ""] + [fcfa(data["totals"].get(k) or 0) for k, _ in LEDGER_COLUMNS])
    t = Table(rows, colWidths=[8 * mm, 48 * mm, 36 * mm] + [23.3 * mm] * len(LEDGER_COLUMNS), repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), green), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                           ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 7.8), ("FONT", (0, 1), (-1, -1), "Helvetica", 7.8),
                           ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
                           ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("ALIGN", (3, 1), (-1, -1), "RIGHT"),
                           ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    detail = [["Charges patronales", "Montant"]] + [[x["label"], fcfa(x["amount"])] for x in data["totals"]["employer_detail"]] \
        + [["Total charges patronales", fcfa(data["totals"].get("employer_total") or 0)]]
    dt = Table(detail, colWidths=[80 * mm, 35 * mm], hAlign="LEFT")
    dt.setStyle(TableStyle([("FONT", (0, 0), (-1, -1), "Helvetica", 8.5), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
                            ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 8.5), ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1"))]))
    e = data["employer"]
    el = [Paragraph(escape(f"Livre de paie — {data['period_label']}"), h),
          Paragraph(escape(" · ".join(x for x in [e.get("name"), e.get("address"), f"N° CNSS {e['cnss_number']}" if e.get("cnss_number") else ""] if x)), s),
          Spacer(1, 6), t, Spacer(1, 10), dt]
    doc.build(el)
    return buf.getvalue()


@router.get("/bulletins/{bid}/pdf")
async def bulletin_pdf(bid: str, user: dict = Depends(require_roles(HR_ROLES))):
    import asyncio
    b = await _bulletin(bid)
    pdf = await asyncio.to_thread(build_bulletin_pdf, b)
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", f"bulletin_{b['period_month']}_{(b.get('employee') or {}).get('full_name') or 'salarie'}")[:90]
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{name}.pdf"'})


@router.get("/bulletins-pdf")
async def bulletins_pdf(employer_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    """Tous les bulletins du mois dans un seul PDF (impression groupée)."""
    import asyncio

    import fitz  # PyMuPDF, déjà utilisé par le portail
    items = await db.paie_bulletins.find({"employer_id": employer_id, "period_month": _month_ok(period_month)}, {"_id": 0}).to_list(2000)
    if not items:
        raise HTTPException(status_code=404, detail="Aucun bulletin pour ce mois")
    items.sort(key=lambda b: (b.get("employee") or {}).get("full_name") or "")

    def merge():
        out = fitz.open()
        for b in items:
            with fitz.open(stream=build_bulletin_pdf(b), filetype="pdf") as one:
                out.insert_pdf(one)
        return out.tobytes()
    pdf = await asyncio.to_thread(merge)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="bulletins_{period_month}.pdf"'})


@router.get("/livre/pdf")
async def ledger_pdf(employer_id: str, period_month: str, user: dict = Depends(require_roles(HR_ROLES))):
    import asyncio
    data = await ledger(employer_id, period_month, user)
    pdf = await asyncio.to_thread(build_ledger_pdf, data)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="livre_de_paie_{period_month}.pdf"'})


async def bulletin_for_verify(token: str) -> Optional[dict]:
    """Page publique du QR code (albarka_docgen.verify_document)."""
    b = await db.paie_bulletins.find_one({"verify_token": token}, {"_id": 0, "params": 0})
    if not b:
        return None
    return {"kind": "Bulletin de paie", "number": b["period_month"], "date": (b.get("validated_at") or b.get("updated_at") or "")[:10],
            "client": (b.get("employer") or {}).get("name") or "—",
            "title": f"{(b.get('employee') or {}).get('full_name') or ''} — {period_label(b['period_month'])}",
            "amount": (b.get("result") or {}).get("net_to_pay"), "currency": "XOF",
            "status": "validé" if b.get("status") == "validated" else "brouillon"}
