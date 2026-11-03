"""Lot 85 — Paie : DÉCLARATION des retenues SND, SFED et CENAMU.

État récapitulatif par rubrique et par période (mois ou trimestre), établi depuis les bulletins de paie VALIDÉS de l'employeur :
un salarié par ligne (matricule, base de calcul, taux ou valeur, montant retenu), total de la rubrique. Un agent exonéré d'une
rubrique (case cochée sur sa fiche) ou dont le montant est nul n'y figure pas.

Routes (préfixe /api, lecture seule, rôles RH) :
  GET /hr/paie/retenues/declaration   données pour l'écran
  GET /hr/paie/retenues/pdf           PDF (une section par rubrique)
  GET /hr/paie/retenues/csv           export CSV (Excel)
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response

from albarka_auth import require_roles
from albarka_paie import HR_ROLES, employer_config
from albarka_paie_cnss import _debut_fin, _fr, _libelle_periode, _mois_de_la_periode, _nombre, _taux
from db import db

router = APIRouter(prefix="/hr/paie/retenues", tags=["RH & Paie — retenues SND / SFED / CENAMU"])


async def construire(employer_id: str, annee: int, periodicite: str, numero: int, inclure_brouillons: bool = False,
                     rubrique: Optional[str] = None) -> Dict[str, Any]:
    """Données de la déclaration : une entrée par rubrique ayant au moins une retenue sur la période."""
    if periodicite not in ("mensuelle", "trimestrielle"):
        raise HTTPException(status_code=422, detail="Périodicité inconnue")
    if not 2000 <= annee <= 2100:
        raise HTTPException(status_code=422, detail="Année invalide")
    cfg = await employer_config(employer_id, strict=False)
    mois = _mois_de_la_periode(annee, periodicite, numero)
    debut, fin = _debut_fin(mois)
    bulletins = await db.paie_bulletins.find({"employer_id": employer_id, "period_month": {"$in": mois}}, {"_id": 0, "params": 0}).to_list(5000)
    retenus = [b for b in bulletins if inclure_brouillons or b.get("status") == "validated"]
    brouillons = sum(1 for b in bulletins if b.get("status") != "validated")

    # Cumul par rubrique puis par salarié (une ligne par salarié sur toute la période)
    rubriques: Dict[str, Dict[str, Any]] = {}
    for b in sorted(retenus, key=lambda x: x["period_month"]):
        r = b.get("result") or {}
        emp = b.get("employee") or {}
        bases = {ln["code"]: ln.get("base") for ln in (r.get("lines") or []) if str(ln.get("code") or "").startswith("spec_")}
        for s in r.get("special_deductions") or []:
            if rubrique and s["key"] != rubrique:
                continue
            rub = rubriques.setdefault(s["key"], {"key": s["key"], "label": s["label"], "salaries": {}})
            ligne = rub["salaries"].setdefault(b["employee_id"], {
                "full_name": emp.get("full_name") or "", "matricule": emp.get("matricule") or "", "base": 0.0, "montant": 0.0,
                "mode": s.get("mode"), "valeur": s.get("value"), "base_calcul": s.get("base"), "mois": 0})
            ligne["montant"] += float(s.get("amount") or 0)
            ligne["base"] += float(bases.get(f"spec_{s['key']}") or 0)
            ligne["mois"] += 1
    sortie: List[Dict[str, Any]] = []
    for rub in rubriques.values():
        lignes = sorted((l for l in rub["salaries"].values() if l["montant"]), key=lambda l: l["full_name"].lower())
        if not lignes:
            continue
        for i, l in enumerate(lignes, start=1):
            l["n"] = i
            l["base"] = int(round(l["base"])) if l["mode"] == "percent" else None
            l["montant"] = int(round(l["montant"]))
        sortie.append({"key": rub["key"], "label": rub["label"], "lignes": lignes, "total": sum(l["montant"] for l in lignes), "effectif": len(lignes)})
    sortie.sort(key=lambda x: x["label"])

    alertes: List[str] = []
    if not retenus:
        alertes.append("Aucun bulletin validé sur cette période : validez les bulletins du mois dans l'onglet « Bulletins de paie ».")
    elif not sortie:
        alertes.append("Aucune retenue SND, SFED ou CENAMU sur cette période (rubriques non réglées, ou agents exonérés).")
    if brouillons and not inclure_brouillons:
        alertes.append(f"{brouillons} bulletin(s) en brouillon ne sont pas comptés : validez-les ou cochez « Inclure les brouillons ».")
    return {"employer": {k: cfg.get(k) or "" for k in ("employer_id", "name", "address", "bp", "phone", "ifu", "rccm", "cnss_number")},
            "periodicite": periodicite, "annee": annee, "numero": numero, "mois": mois, "debut": debut, "fin": fin,
            "libelle_periode": _libelle_periode(periodicite, annee, numero), "rubriques": sortie,
            "total_general": sum(x["total"] for x in sortie), "inclure_brouillons": inclure_brouillons, "alertes": alertes}


def _detail(l: Dict[str, Any]) -> str:
    """« 1 % du salaire brut » / « valeur fixe » : comment la retenue a été calculée."""
    if l["mode"] != "percent":
        return "Valeur fixe"
    bases = {"gross": "du salaire brut", "base": "du salaire de base", "net": "du salaire net"}
    return f"{_taux(float(l['valeur'] or 0))} % {bases.get(l['base_calcul'], '')}".strip()


def construire_pdf(d: Dict[str, Any]) -> bytes:
    """PDF A4 : en-tête de l'employeur, puis une section (tableau et total) par rubrique."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    vert = colors.HexColor("#0F6B4A")
    h = ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=vert)
    s = ParagraphStyle("s", fontName="Helvetica", fontSize=8.5, leading=11, textColor=colors.HexColor("#475569"))
    rub_st = ParagraphStyle("r", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=vert)
    cell = ParagraphStyle("c", fontName="Helvetica", fontSize=8.5, leading=10.5)
    e = d["employer"]
    el: List[Any] = [Paragraph(escape(f"Retenues SND, SFED et CENAMU — {d['libelle_periode']}"), h),
                     Paragraph(escape(" · ".join(x for x in [e.get("name"), e.get("address"), f"BP {e['bp']}" if e.get("bp") else "",
                                                         f"IFU {e['ifu']}" if e.get("ifu") else "",
                                                         f"N° employeur {e['cnss_number']}" if e.get("cnss_number") else ""] if x)), s),
                     Paragraph(escape(f"Période du {_fr(d['debut'])} au {_fr(d['fin'])}"), s), Spacer(1, 8)]
    if not d["rubriques"]:
        el.append(Paragraph("Aucune retenue sur la période.", s))
    for rub in d["rubriques"]:
        rows = [["N°", "Salarié", "Matricule", "Calcul", "Base", "Montant retenu"]]
        for l in rub["lignes"]:
            rows.append([str(l["n"]), Paragraph(escape(l["full_name"]), cell), l["matricule"], Paragraph(escape(_detail(l)), cell),
                         _nombre(l["base"]) if l["base"] is not None else "", _nombre(l["montant"])])
        rows.append(["", "TOTAL " + rub["label"], "", "", "", _nombre(rub["total"])])
        t = Table(rows, colWidths=[9 * mm, 56 * mm, 22 * mm, 40 * mm, 24 * mm, 27 * mm], repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), vert), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                               ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5), ("FONT", (0, 1), (-1, -1), "Helvetica", 8.5),
                               ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 9), ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#F1F5F9")),
                               ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#CBD5E1")), ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                               ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        el.append(KeepTogether([Paragraph(escape(f"{rub['label']} — {rub['effectif']} salarié(s)"), rub_st), Spacer(1, 3), t, Spacer(1, 12)]))
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=A4, leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
                      title=f"Retenues SND SFED CENAMU {d['libelle_periode']}").build(el)
    return buf.getvalue()


def construire_csv(d: Dict[str, Any]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([f"Retenues SND, SFED et CENAMU — {d['employer'].get('name')} — {d['libelle_periode']}"])
    w.writerow(["Rubrique", "Salarié", "Matricule", "Calcul", "Base", "Montant retenu"])
    for rub in d["rubriques"]:
        for l in rub["lignes"]:
            w.writerow([rub["label"], l["full_name"], l["matricule"], _detail(l), l["base"] if l["base"] is not None else "", l["montant"]])
        w.writerow([rub["label"], "TOTAL", "", "", "", rub["total"]])
    return ("﻿" + buf.getvalue()).encode("utf-8")


@router.get("/declaration")
async def declaration(employer_id: str, annee: int, numero: int, periodicite: str = "mensuelle", inclure_brouillons: bool = False,
                      rubrique: Optional[str] = None, user: dict = Depends(require_roles(HR_ROLES))):
    return await construire(employer_id, annee, periodicite, numero, inclure_brouillons, rubrique)


@router.get("/pdf")
async def pdf(employer_id: str, annee: int, numero: int, periodicite: str = "mensuelle", inclure_brouillons: bool = False,
              rubrique: Optional[str] = None, user: dict = Depends(require_roles(HR_ROLES))):
    import asyncio
    d = await construire(employer_id, annee, periodicite, numero, inclure_brouillons, rubrique)
    contenu = await asyncio.to_thread(construire_pdf, d)
    return Response(contenu, media_type="application/pdf",
                    headers={"Content-Disposition": f'inline; filename="retenues_{annee}_{periodicite}_{numero}.pdf"'})


@router.get("/csv")
async def csv_export(employer_id: str, annee: int, numero: int, periodicite: str = "mensuelle", inclure_brouillons: bool = False,
                     rubrique: Optional[str] = None, user: dict = Depends(require_roles(HR_ROLES))):
    d = await construire(employer_id, annee, periodicite, numero, inclure_brouillons, rubrique)
    return Response(construire_csv(d), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="retenues_{annee}_{periodicite}_{numero}.csv"'})
