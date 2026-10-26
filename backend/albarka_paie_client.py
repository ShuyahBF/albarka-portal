"""Lot 75 — Espace client, rubrique « Ressources humaines » : les bulletins de paie VALIDÉS et les déclarations CNSS de SON entreprise.

Le client est l'employeur : ses salariés sont rangés sous son identifiant (`employer_id` = id du client). Il ne voit que :
  - les bulletins dont le statut est « validé » par le cabinet (jamais un brouillon), en PDF, un par un ou tous ceux d'un mois ;
  - les déclarations CNSS (BTN + DECLARATION) des périodes où des bulletins sont validés, en PDF (mensuelle ou trimestrielle selon l'effectif,
    même règle que le cabinet).
Un client ne peut jamais lire le bulletin d'un autre employeur (404). Module « paie » (CLIENT_PORTAL_MODULES) à ouvrir dans sa fiche.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Response

from albarka_auth import get_current_user
from albarka_models import client_modules, is_client, tenant_id_of
from albarka_paie import _bulletin_pdf_context, build_bulletin_pdf
from albarka_paie_cnss import construire_declaration, declaration_pdf
from db import db

router = APIRouter(prefix="/me/paie", tags=["Espace client — paie"])
_MOIS = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _employeur(user: dict) -> str:
    """Identifiant de l'employeur = le client connecté ; réservé aux clients dont le module « paie » est ouvert."""
    if not is_client(user):
        raise HTTPException(status_code=403, detail="Réservé aux clients")
    if "paie" not in client_modules(user):
        raise HTTPException(status_code=403, detail="Rubrique fermée pour ce compte")
    return tenant_id_of(user)


def _mois_ok(m: str) -> str:
    if not _MOIS.match(m or ""):
        raise HTTPException(status_code=400, detail="Mois invalide (AAAA-MM attendu)")
    return m


def periodes_cnss(mois: List[str], mode: str) -> List[Dict[str, Any]]:
    """Périodes de déclaration (annee, numero) qui contiennent au moins un des mois donnés. `mode` = mensuelle | trimestrielle."""
    vus: Dict[tuple, bool] = {}
    for m in mois:
        annee, mm = int(m[:4]), int(m[5:7])
        vus[(annee, mm if mode == "mensuelle" else (mm - 1) // 3 + 1)] = True
    return [{"annee": a, "numero": n} for a, n in sorted(vus, reverse=True)]


@router.get("")
async def ma_paie(user: dict = Depends(get_current_user)):
    """Mois avec bulletins validés (nombre, net à payer total) et périodes de déclaration CNSS disponibles."""
    eid = _employeur(user)
    valides = await db.paie_bulletins.find({"employer_id": eid, "status": "validated"}, {"_id": 0, "period_month": 1, "result": 1}).to_list(5000)
    par_mois: Dict[str, Dict[str, Any]] = {}
    for b in valides:
        m = par_mois.setdefault(b.get("period_month") or "", {"period_month": b.get("period_month"), "count": 0, "net_to_pay": 0.0})
        m["count"] += 1
        m["net_to_pay"] += float((b.get("result") or {}).get("net_to_pay") or 0)
    mois = sorted(par_mois.values(), key=lambda x: x["period_month"] or "", reverse=True)
    declarations: List[Dict[str, Any]] = []
    for annee in sorted({int(m["period_month"][:4]) for m in mois if m["period_month"]}, reverse=True):
        d0 = await construire_declaration(eid, annee, "auto", 1)                # périodicité selon l'effectif (comme le cabinet)
        mode = d0["periodicite"]
        for p in periodes_cnss([m["period_month"] for m in mois if (m["period_month"] or "").startswith(str(annee))], mode):
            d = await construire_declaration(eid, p["annee"], mode, p["numero"])
            declarations.append({**p, "periodicite": mode, "libelle": d["libelle_periode"]})
    return {"mois": mois, "declarations": declarations}


@router.get("/bulletins")
async def mes_bulletins(period_month: str, user: dict = Depends(get_current_user)):
    """Bulletins VALIDÉS du mois : salarié, brut, net à payer."""
    eid = _employeur(user)
    items = await db.paie_bulletins.find({"employer_id": eid, "period_month": _mois_ok(period_month), "status": "validated"},
                                         {"_id": 0, "id": 1, "employee": 1, "result": 1}).to_list(2000)
    out = [{"id": b["id"], "full_name": (b.get("employee") or {}).get("full_name") or "", "gross": float((b.get("result") or {}).get("gross") or 0),
            "net_to_pay": float((b.get("result") or {}).get("net_to_pay") or 0)} for b in items]
    out.sort(key=lambda x: x["full_name"])
    return {"items": out}


async def _bulletin_du_client(bid: str, eid: str) -> dict:
    b = await db.paie_bulletins.find_one({"id": bid, "employer_id": eid, "status": "validated"}, {"_id": 0})
    if not b:
        raise HTTPException(status_code=404, detail="Bulletin introuvable")           # même réponse pour « autre employeur » et « brouillon »
    return b


def _nom(prefixe: str, texte: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", f"{prefixe}_{texte}")[:90] + ".pdf"


@router.get("/bulletins/{bid}/pdf")
async def mon_bulletin_pdf(bid: str, user: dict = Depends(get_current_user)):
    b = await _bulletin_du_client(bid, _employeur(user))
    pdf = await asyncio.to_thread(build_bulletin_pdf, b, await _bulletin_pdf_context(b))
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{_nom("bulletin", b["period_month"] + "_" + ((b.get("employee") or {}).get("full_name") or "salarie"))}"'})


@router.get("/bulletins-pdf")
async def mes_bulletins_pdf(period_month: str, user: dict = Depends(get_current_user)):
    """Tous les bulletins VALIDÉS du mois dans un seul PDF."""
    import fitz  # PyMuPDF, déjà utilisé par le portail
    eid = _employeur(user)
    items = await db.paie_bulletins.find({"employer_id": eid, "period_month": _mois_ok(period_month), "status": "validated"}, {"_id": 0}).to_list(2000)
    if not items:
        raise HTTPException(status_code=404, detail="Aucun bulletin validé pour ce mois")
    items.sort(key=lambda b: (b.get("employee") or {}).get("full_name") or "")
    ctxs = [await _bulletin_pdf_context(b) for b in items]

    def fusion() -> bytes:
        sortie = fitz.open()
        for b, ctx in zip(items, ctxs):
            with fitz.open(stream=build_bulletin_pdf(b, ctx), filetype="pdf") as un:
                sortie.insert_pdf(un)
        return sortie.tobytes()
    pdf = await asyncio.to_thread(fusion)
    return Response(pdf, media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{_nom("bulletins", period_month)}"'})


@router.get("/cnss/pdf")
async def ma_declaration_cnss_pdf(annee: int, numero: int, user: dict = Depends(get_current_user)):
    """Déclaration CNSS complète (BTN puis DECLARATION) de SON entreprise — bulletins validés seulement, jamais de brouillon."""
    eid = _employeur(user)
    return await declaration_pdf(employer_id=eid, annee=annee, numero=numero, periodicite="auto", inclure_brouillons=False, user=user)
