"""MOTEUR DE PAIE — Burkina Faso, entièrement paramétrable (lot 8).

Module pur : aucune base de données, aucun accès réseau. Il reçoit la fiche
d'un salarié et un jeu de PARAMÈTRES, et rend le bulletin calculé ligne par
ligne. Les paramètres viennent d'un MODÈLE de configuration (ou de sa version
personnalisée pour un employeur) ; DEFAULT_PARAMS sert de « valeurs par défaut »
(bouton « Restaurer les valeurs par défaut »).

Calcul (repris du fichier Excel « Assistante_cardi_pro_ESSAI.xlsx ») :
  1. prime d'ancienneté  : à partir de N années de service (3 par défaut),
     taux de départ + un pas par année supplémentaire, plafonné ;
  2. salaire brut        : base + ancienneté + indemnités + primes du mois ;
  3. CNSS salariale      : taux × brut plafonné (5,5 % × 600 000 = 33 000 max) ;
  4. CNSS « fiscale »    : CNSS retenue, limitée à 8 % du salaire de base ;
  5. imposable IUTS      : brut − CNSS fiscale ;
  6. exonérations        : par indemnité, min(montant versé, taux × imposable,
     plafond) — logement 20 %/75 000, transport 5 %/30 000, fonction 5 %/50 000 ;
     une indemnité peut être déclarée « non exonérée » sur la fiche ;
  7. abattement forfaitaire : taux × salaire de base, unique (25 %) ou selon
     la catégorie du salarié (ex. cadre 20 %, non cadre 25 %) ;
  8. base IUTS           : imposable − exonérations − abattement (arrondie) ;
  9. IUTS brut           : barème progressif par tranches ;
 10. abattement charges de famille : % de l'IUTS selon le nombre de charges
     (table libre : nombre de charges → taux, la dernière ligne vaut au-delà) ;
 11. IUTS net, salaire net (brut − CNSS − IUTS), arrondi (centaine par défaut) ;
 12. soutien patriotique : 1 % du salaire net ;
 13. net à payer         : net − soutien patriotique − retenues (acomptes, prêts…).
Charges patronales (pour le livre de paie) : CNSS employeur par branche et
taxes patronales (TPA…), sur le brut plafonné ou non.

Arrondis : règle { step, mode } — step 0 = pas d'arrondi, 1 = au franc,
5, 10, 25, 50, 100… ; mode « nearest » (au plus proche, 0,5 vers le haut),
« down » (inférieur) ou « up » (supérieur).
"""
from __future__ import annotations

import copy
import math
from datetime import date
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Valeurs par défaut (Burkina Faso). Toutes modifiables dans les modèles.
# ---------------------------------------------------------------------------
DEFAULT_PARAMS: Dict[str, Any] = {
    "country": "Burkina Faso",
    # Rubriques d'indemnités proposées sur la fiche salarié.
    # « exemption » : clé de la règle d'exonération qui s'y applique (ou None).
    "allowances": [
        {"key": "housing", "label": "Indemnité de logement", "exemption": "housing"},
        {"key": "transport", "label": "Indemnité de transport", "exemption": "transport"},
        {"key": "function", "label": "Indemnité de fonction", "exemption": "function"},
        {"key": "responsibility", "label": "Indemnité de responsabilité", "exemption": None},
        {"key": "risk", "label": "Indemnité de risque", "exemption": None},
        {"key": "subjection", "label": "Indemnité de sujétion", "exemption": None},
        {"key": "guard", "label": "Indemnité de garde", "exemption": None},
        {"key": "other", "label": "Autre indemnité", "exemption": None},
    ],
    "exemptions": [
        {"key": "housing", "label": "Logement", "rate": 20.0, "cap": 75000},
        {"key": "transport", "label": "Transport", "rate": 5.0, "cap": 30000},
        {"key": "function", "label": "Fonction", "rate": 5.0, "cap": 50000},
    ],
    "cnss": {
        "employee_rate": 5.5,           # % du brut
        "ceiling": 600000,              # brut plafonné (5,5 % × 600 000 = 33 000)
        "fiscal_cap_enabled": True,     # CNSS déductible de l'IUTS limitée…
        "fiscal_cap_rate": 8.0,         # … à 8 % du salaire de base
        "employer_ceiling": 600000,
        "employer_lines": [             # CNSS patronale (livre de paie)
            {"label": "Prestations familiales", "rate": 7.0},
            {"label": "Risques professionnels", "rate": 3.5},
            {"label": "Pension vieillesse", "rate": 5.5},
        ],
    },
    "employer_taxes": [                 # taxes patronales sur le brut (non plafonné)
        {"label": "Taxe patronale d'apprentissage (TPA)", "rate": 3.0},
    ],
    "flat_abatement": {
        "mode": "single",               # single | by_category
        "rate": 25.0,                   # % du salaire de base (mode single)
        "categories": [
            {"key": "cadre", "label": "Cadre", "rate": 20.0},
            {"key": "non_cadre", "label": "Non cadre", "rate": 25.0},
        ],
    },
    "iuts_brackets": [                  # up_to = borne haute ; None = au-delà
        {"up_to": 30000, "rate": 0.0},
        {"up_to": 50000, "rate": 12.1},
        {"up_to": 80000, "rate": 13.9},
        {"up_to": 120000, "rate": 15.7},
        {"up_to": 170000, "rate": 18.4},
        {"up_to": 250000, "rate": 21.7},
        {"up_to": None, "rate": 25.0},
    ],
    "family_abatement": [               # nombre de charges → % de l'IUTS ; la dernière ligne vaut au-delà
        {"charges": 1, "rate": 8.0},
        {"charges": 2, "rate": 10.0},
        {"charges": 3, "rate": 12.0},
        {"charges": 4, "rate": 14.0},
        {"charges": 5, "rate": 16.0},
        {"charges": 6, "rate": 18.0},
        {"charges": 7, "rate": 20.0},
        {"charges": 8, "rate": 22.0},
    ],
    "seniority": {
        "enabled": True,
        "start_years": 3,               # la prime commence à 3 ans de service
        "start_rate": 5.0,              # % du salaire de base à 3 ans
        "step_rate": 1.0,               # + 1 point par année supplémentaire
        "max_rate": 25.0,
    },
    "patriotic_support": {"enabled": True, "rate": 1.0, "label": "Soutien patriotique"},
    "rounding": {
        "amounts": {"step": 1, "mode": "nearest"},      # CNSS, IUTS, primes… : au franc
        "iuts_base": {"step": 100, "mode": "down"},     # base IUTS : centaine inférieure
        "net": {"step": 100, "mode": "nearest"},        # salaire net : centaine la plus proche
    },
}

ROUND_MODES = {"nearest", "down", "up"}


# ---------------------------------------------------------------------------
# Outils
# ---------------------------------------------------------------------------
def round_rule(value: float, rule: Optional[Dict[str, Any]]) -> float:
    """Arrondit selon {step, mode}. step 0 (ou absent) : valeur inchangée."""
    step = float((rule or {}).get("step") or 0)
    if step <= 0:
        return value
    mode = (rule or {}).get("mode") or "nearest"
    q = value / step
    if mode == "down":
        n = math.floor(q + 1e-9)
    elif mode == "up":
        n = math.ceil(q - 1e-9)
    else:
        n = math.floor(q + 0.5 + 1e-9)          # 0,5 vers le haut (pas l'arrondi « bancaire »)
    out = n * step
    return int(out) if float(out).is_integer() else out


def _num(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return float(default)


def merged_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Complète un jeu de paramètres avec les valeurs par défaut (clés absentes)."""
    base = copy.deepcopy(DEFAULT_PARAMS)
    if not params:
        return base
    for k, v in params.items():
        if v is None:                       # section vide : valeurs par défaut
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            base[k] = {**base[k], **v}
            if k == "rounding":
                for rk in DEFAULT_PARAMS["rounding"]:
                    base[k][rk] = {**DEFAULT_PARAMS["rounding"][rk], **(v.get(rk) or {})}
        else:
            base[k] = copy.deepcopy(v)
    return base


def normalize_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Contrôle et nettoie un jeu de paramètres ; lève ValueError (message clair)."""
    p = merged_params(params)

    def pct(v, what):
        x = _num(v, -1)
        if not 0 <= x <= 100:
            raise ValueError(f"{what} : taux entre 0 et 100 %")
        return round(x, 4)

    def amount(v, what, allow_none=False):
        if v in (None, "") and allow_none:
            return None
        x = _num(v, -1)
        if x < 0:
            raise ValueError(f"{what} : montant positif attendu")
        return x

    # Indemnités et exonérations
    ex_keys = []
    exemptions = []
    for i, e in enumerate(p.get("exemptions") or [], start=1):
        key = str(e.get("key") or f"ex{i}").strip()[:40]
        if key in ex_keys:
            raise ValueError(f"Exonération « {key} » en double")
        ex_keys.append(key)
        exemptions.append({"key": key, "label": str(e.get("label") or key).strip()[:80],
                           "rate": pct(e.get("rate"), f"Exonération {key}"), "cap": amount(e.get("cap"), f"Plafond {key}")})
    allowances, seen = [], set()
    for i, a in enumerate(p.get("allowances") or [], start=1):
        key = str(a.get("key") or f"a{i}").strip()[:40]
        if key in seen:
            raise ValueError(f"Indemnité « {key} » en double")
        seen.add(key)
        ex = a.get("exemption") or None
        if ex and ex not in ex_keys:
            raise ValueError(f"Indemnité « {a.get('label') or key} » : exonération inconnue « {ex} »")
        allowances.append({"key": key, "label": str(a.get("label") or key).strip()[:80], "exemption": ex})
    # CNSS
    c = p["cnss"]
    cnss = {"employee_rate": pct(c.get("employee_rate"), "CNSS salariale"),
            "ceiling": amount(c.get("ceiling"), "Plafond CNSS"),
            "fiscal_cap_enabled": bool(c.get("fiscal_cap_enabled", True)),
            "fiscal_cap_rate": pct(c.get("fiscal_cap_rate"), "Plafond fiscal CNSS"),
            "employer_ceiling": amount(c.get("employer_ceiling"), "Plafond CNSS patronale"),
            "employer_lines": [{"label": str(x.get("label") or "CNSS patronale").strip()[:80],
                                "rate": pct(x.get("rate"), "CNSS patronale")} for x in (c.get("employer_lines") or [])]}
    employer_taxes = [{"label": str(x.get("label") or "Taxe").strip()[:80], "rate": pct(x.get("rate"), "Taxe patronale")}
                      for x in (p.get("employer_taxes") or [])]
    # Abattement forfaitaire
    f = p["flat_abatement"]
    mode = f.get("mode") if f.get("mode") in ("single", "by_category") else "single"
    cats, ck = [], set()
    for i, cat in enumerate(f.get("categories") or [], start=1):
        key = str(cat.get("key") or f"cat{i}").strip()[:40]
        if key in ck:
            raise ValueError(f"Catégorie « {key} » en double")
        ck.add(key)
        cats.append({"key": key, "label": str(cat.get("label") or key).strip()[:80], "rate": pct(cat.get("rate"), f"Catégorie {key}")})
    if mode == "by_category" and not cats:
        raise ValueError("Abattement par catégorie : ajoutez au moins une catégorie")
    flat = {"mode": mode, "rate": pct(f.get("rate"), "Abattement forfaitaire"), "categories": cats}
    # Barème IUTS : bornes croissantes, dernière tranche ouverte
    brackets, last = [], -1.0
    raw_b = p.get("iuts_brackets") or []
    if not raw_b:
        raise ValueError("Barème IUTS : au moins une tranche")
    for i, b in enumerate(raw_b):
        up = b.get("up_to")
        is_last = i == len(raw_b) - 1
        if up in (None, "") and not is_last:
            raise ValueError("Barème IUTS : seule la dernière tranche peut être « au-delà »")
        if up not in (None, ""):
            up = _num(up, -1)
            if up <= last:
                raise ValueError("Barème IUTS : les bornes doivent être croissantes")
            last = up
        brackets.append({"up_to": None if up in (None, "") else up, "rate": pct(b.get("rate"), "Tranche IUTS")})
    if brackets[-1]["up_to"] is not None:
        brackets.append({"up_to": None, "rate": brackets[-1]["rate"]})
    # Charges de famille : nombres croissants, sans doublon
    fam, prev = [], 0
    for row in sorted(p.get("family_abatement") or [], key=lambda r: int(_num(r.get("charges")))):
        n = int(_num(row.get("charges"), 0))
        if n < 1 or n == prev:
            raise ValueError("Charges de famille : nombres de charges à partir de 1, sans doublon")
        prev = n
        fam.append({"charges": n, "rate": pct(row.get("rate"), f"Charges de famille ({n})")})
    s = p["seniority"]
    seniority = {"enabled": bool(s.get("enabled", True)), "start_years": int(_num(s.get("start_years"), 3)),
                 "start_rate": pct(s.get("start_rate"), "Ancienneté (taux de départ)"),
                 "step_rate": pct(s.get("step_rate"), "Ancienneté (pas annuel)"),
                 "max_rate": pct(s.get("max_rate"), "Ancienneté (plafond)")}
    if seniority["start_years"] < 0:
        raise ValueError("Ancienneté : nombre d'années positif")
    ps = p["patriotic_support"]
    patriotic = {"enabled": bool(ps.get("enabled", True)), "rate": pct(ps.get("rate"), "Soutien patriotique"),
                 "label": str(ps.get("label") or "Soutien patriotique").strip()[:80]}
    rounding = {}
    for rk, rv in p["rounding"].items():
        if rk not in DEFAULT_PARAMS["rounding"]:
            continue
        step = _num((rv or {}).get("step"), 0)
        if step < 0:
            raise ValueError("Arrondi : pas positif")
        m = (rv or {}).get("mode") or "nearest"
        if m not in ROUND_MODES:
            raise ValueError(f"Arrondi : mode inconnu « {m} »")
        rounding[rk] = {"step": int(step) if float(step).is_integer() else step, "mode": m}
    return {"country": str(p.get("country") or "Burkina Faso")[:60], "allowances": allowances, "exemptions": exemptions,
            "cnss": cnss, "employer_taxes": employer_taxes, "flat_abatement": flat, "iuts_brackets": brackets,
            "family_abatement": fam, "seniority": seniority, "patriotic_support": patriotic, "rounding": rounding}


def years_of_service(hire_date: Optional[str], period_month: Optional[str]) -> int:
    """Années complètes de service à la fin du mois de paie."""
    if not hire_date or not period_month:
        return 0
    try:
        h = date.fromisoformat(str(hire_date)[:10])
        y, m = map(int, period_month.split("-"))
        from datetime import timedelta
        end = date(y + (m == 12), 1 if m == 12 else m + 1, 1) - timedelta(days=1)   # dernier jour du mois de paie
    except ValueError:
        return 0
    years = end.year - h.year - ((end.month, end.day) < (h.month, h.day))
    return max(0, years)


def seniority_rate(years: int, s: Dict[str, Any]) -> float:
    if not s.get("enabled") or years < s["start_years"]:
        return 0.0
    return min(s["max_rate"], s["start_rate"] + (years - s["start_years"]) * s["step_rate"])


def progressive_tax(base: float, brackets: List[Dict[str, Any]]) -> float:
    """Impôt par tranches (taux marginaux)."""
    tax, lower = 0.0, 0.0
    for b in brackets:
        upper = b["up_to"] if b["up_to"] is not None else float("inf")
        if base > lower:
            tax += (min(base, upper) - lower) * b["rate"] / 100
        lower = upper
        if base <= upper:
            break
    return tax


def family_rate(charges: int, table: List[Dict[str, Any]]) -> float:
    """Taux de l'abattement pour charges de famille ; au-delà du tableau : dernière ligne."""
    if charges <= 0 or not table:
        return 0.0
    rate = 0.0
    for row in table:
        if charges >= row["charges"]:
            rate = row["rate"]
    return rate


def flat_rate(category: Optional[str], f: Dict[str, Any]) -> float:
    if f["mode"] == "by_category":
        for c in f["categories"]:
            if c["key"] == category:
                return c["rate"]
        return f["rate"]                 # sans catégorie connue : taux général
    return f["rate"]


# ---------------------------------------------------------------------------
# Calcul du bulletin
# ---------------------------------------------------------------------------
def compute_payslip(employee: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
                    period_month: Optional[str] = None) -> Dict[str, Any]:
    """Bulletin calculé.

    `employee` : base_salary, allowances {clé: montant}, non_exempt [clés],
    category, dependents, hire_date, seniority_amount (facultatif : saisi),
    extras [{label, amount}] (primes du mois, imposables),
    deductions [{label, amount}] (acomptes, prêts, autres retenues).
    """
    p = normalize_params(params)
    R = lambda v, k="amounts": round_rule(v, p["rounding"].get(k))  # noqa: E731
    base = _num(employee.get("base_salary"))
    allow_in = employee.get("allowances") or {}
    non_exempt = set(employee.get("non_exempt") or [])
    lines: List[Dict[str, Any]] = []

    def line(code, label, amount, kind, base_=None, rate=None):
        lines.append({"code": code, "label": label, "base": base_, "rate": rate, "amount": amount, "kind": kind})

    line("base", "Salaire de base", base, "gain")
    # 1. Ancienneté
    years = years_of_service(employee.get("hire_date"), period_month)
    s_rate = seniority_rate(years, p["seniority"])
    if employee.get("seniority_amount") not in (None, ""):
        seniority = _num(employee.get("seniority_amount"))
    else:
        seniority = R(base * s_rate / 100)
    if seniority:
        line("seniority", f"Prime d'ancienneté ({years} an{'s' if years > 1 else ''})", seniority, "gain", base, s_rate or None)
    # 2. Indemnités (dans l'ordre du modèle) et primes du mois
    allowances = []
    for a in p["allowances"]:
        amt = _num(allow_in.get(a["key"]))
        if amt:
            allowances.append({**a, "amount": amt})
            line(f"allow_{a['key']}", a["label"], amt, "gain")
    known = {a["key"] for a in p["allowances"]}
    for k, v in allow_in.items():                       # rubrique retirée du modèle : gardée
        if k not in known and _num(v):
            allowances.append({"key": k, "label": k, "exemption": None, "amount": _num(v)})
            line(f"allow_{k}", k, _num(v), "gain")
    extras_total = 0.0
    for i, x in enumerate(employee.get("extras") or []):
        amt = _num(x.get("amount"))
        if amt:
            extras_total += amt
            line(f"extra_{i}", str(x.get("label") or "Prime"), amt, "gain")
    gross = base + seniority + sum(a["amount"] for a in allowances) + extras_total
    # 3. CNSS
    c = p["cnss"]
    cnss_base = min(gross, c["ceiling"]) if c["ceiling"] else gross
    cnss = R(cnss_base * c["employee_rate"] / 100)
    line("cnss", "CNSS (part salariale)", cnss, "deduction", cnss_base, c["employee_rate"])
    # 4-5. CNSS fiscale et imposable
    cnss_fiscal = min(cnss, R(base * c["fiscal_cap_rate"] / 100)) if c["fiscal_cap_enabled"] else cnss
    taxable = gross - cnss_fiscal
    # 6. Exonérations
    ex_rules = {e["key"]: e for e in p["exemptions"]}
    exemptions = []
    for a in allowances:
        rule = ex_rules.get(a.get("exemption"))
        if not rule or a["key"] in non_exempt:
            continue
        amt = min(a["amount"], R(taxable * rule["rate"] / 100), rule["cap"] if rule["cap"] else float("inf"))
        exemptions.append({"key": a["key"], "label": a["label"], "amount": amt, "rate": rule["rate"], "cap": rule["cap"]})
    ex_total = sum(e["amount"] for e in exemptions)
    # 7. Abattement forfaitaire
    f_rate = flat_rate(employee.get("category"), p["flat_abatement"])
    flat = R(base * f_rate / 100)
    # 8-10. IUTS
    iuts_base = max(0, round_rule(taxable - ex_total - flat, p["rounding"].get("iuts_base")))
    iuts_gross = R(progressive_tax(iuts_base, p["iuts_brackets"]))
    charges = int(_num(employee.get("dependents")))
    fam_rate = family_rate(charges, p["family_abatement"])
    fam = R(iuts_gross * fam_rate / 100)
    iuts = max(0, iuts_gross - fam)
    line("iuts", "IUTS", iuts_gross, "deduction", iuts_base, None)
    if fam:
        line("iuts_family", f"Abattement charges de famille ({charges})", -fam, "deduction", iuts_gross, fam_rate)
    # 11. Salaire net (arrondi)
    net_raw = gross - cnss - iuts
    net = round_rule(net_raw, p["rounding"].get("net"))
    rounding_diff = net - net_raw
    # 12. Soutien patriotique
    ps = p["patriotic_support"]
    patriotic = R(net * ps["rate"] / 100) if ps["enabled"] else 0
    if patriotic:
        line("patriotic", ps["label"], patriotic, "deduction", net, ps["rate"])
    # 13. Retenues et net à payer
    ded_total = 0.0
    for i, d in enumerate(employee.get("deductions") or []):
        amt = _num(d.get("amount"))
        if amt:
            ded_total += amt
            line(f"ded_{i}", str(d.get("label") or "Retenue"), amt, "deduction")
    net_to_pay = net - patriotic - ded_total
    # Charges patronales (livre de paie)
    emp_base = min(gross, c["employer_ceiling"]) if c["employer_ceiling"] else gross
    employer = [{"label": x["label"], "base": emp_base, "rate": x["rate"], "amount": R(emp_base * x["rate"] / 100)}
                for x in c["employer_lines"]]
    employer += [{"label": x["label"], "base": gross, "rate": x["rate"], "amount": R(gross * x["rate"] / 100)}
                 for x in p["employer_taxes"]]
    employer_total = sum(x["amount"] for x in employer)
    return {
        "lines": lines,
        "years_of_service": years, "seniority_rate": s_rate, "seniority": seniority,
        "gross": gross, "cnss": cnss, "cnss_base": cnss_base, "cnss_fiscal": cnss_fiscal,
        "taxable": taxable, "exemptions": exemptions, "exemptions_total": ex_total,
        "flat_abatement_rate": f_rate, "flat_abatement": flat,
        "iuts_base": iuts_base, "iuts_gross": iuts_gross, "family_charges": charges,
        "family_rate": fam_rate, "family_abatement": fam, "iuts": iuts,
        "net_raw": net_raw, "rounding_diff": rounding_diff, "net": net,
        "patriotic_support": patriotic, "deductions_total": ded_total, "net_to_pay": net_to_pay,
        "employer_charges": employer, "employer_total": employer_total, "employer_cost": gross + employer_total,
    }


def base_for_net(employee: Dict[str, Any], target_net: float, params: Optional[Dict[str, Any]] = None,
                 period_month: Optional[str] = None) -> float:
    """Mode « net négocié → brut » : plus petit salaire de base (au franc) dont le
    salaire net (avant arrondi du net, soutien patriotique et retenues) atteint
    `target_net`, les indemnités de la fiche restant fixes."""
    target = _num(target_net)
    if target <= 0:
        return 0.0

    def net_of(b):
        return compute_payslip({**employee, "base_salary": b, "seniority_amount": None}, params, period_month)["net_raw"]
    lo, hi = 0, max(1000, int(target * 3))
    while net_of(hi) < target:          # agrandit l'intervalle si besoin (très fortes indemnités négatives impossibles)
        hi *= 2
        if hi > 10**10:
            raise ValueError("Net demandé impossible à atteindre")
    while lo < hi:                      # le net croît avec le salaire de base
        mid = (lo + hi) // 2
        if net_of(mid) >= target:
            hi = mid
        else:
            lo = mid + 1
    return float(lo)
