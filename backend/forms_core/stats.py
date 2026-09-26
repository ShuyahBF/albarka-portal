"""Statistiques d'un formulaire (aucune base de données : on reçoit des listes).

- `form_stats(pages, submissions, views=0, invitations=None)` : indicateurs,
  réponses par jour, et un bloc par question :
    * choix (liste, choix unique, oui/non) : nombre et % par option ;
    * choix multiples / cases à cocher : nombre et % de répondants par option ;
    * nombres, notes, échelles : moyenne, min, max, médiane (+ répartition
      des notes) ;
    * textes : nombre de réponses et 5 dernières réponses ;
    * fichiers / signatures / tableaux : nombre de réponses.
- `invitation_stats(invitations)` : envoyés, ouverts, répondus, taux.
- `in_period(iso, date_from, date_to)` : filtre de dates INCLUSIF (la journée
  de `date_to` compte entière).
"""
from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Any, Dict, List, Optional

from .fields import FIELD_TYPES, value_fields


def in_period(iso: Optional[str], date_from: Optional[str], date_to: Optional[str]) -> bool:
    day = (iso or "")[:10]
    if date_from and day < date_from[:10]:
        return False
    if date_to and day > date_to[:10]:
        return False
    return True


def _pct(n: int, total: int) -> float:
    return round(n * 100.0 / total, 1) if total else 0.0


def question_stats(field: Dict[str, Any], values: List[Any], total: int) -> Dict[str, Any]:
    """Bloc statistique d'une question à partir de ses valeurs non vides."""
    family = FIELD_TYPES.get(field["type"], {}).get("family")
    out: Dict[str, Any] = {"id": field["id"], "label": field.get("label"), "type": field["type"],
                           "family": family, "answered": len(values), "answered_pct": _pct(len(values), total)}
    if family in ("choice", "boolean"):
        if family == "boolean":
            labels = ["Oui", "Non"]
            counts = Counter("Oui" if v is True else "Non" for v in values if isinstance(v, bool))
        else:
            labels = list(field.get("options") or [])
            counts = Counter(str(v) for v in values)
        out["options"] = [{"label": o, "count": counts.get(o, 0), "pct": _pct(counts.get(o, 0), len(values))} for o in labels]
    elif family == "multi":
        counts = Counter(o for v in values if isinstance(v, list) for o in v)
        out["options"] = [{"label": o, "count": counts.get(o, 0), "pct": _pct(counts.get(o, 0), len(values))}
                          for o in field.get("options") or []]
    elif family == "number":
        nums = [float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if nums:
            out.update(avg=round(sum(nums) / len(nums), 2), min=min(nums), max=max(nums), median=median(nums))
        if field["type"] in ("rating", "scale"):
            top = (field.get("max") or 5) if field["type"] == "rating" else 10
            low = 1 if field["type"] == "rating" else 0
            c = Counter(int(n) for n in nums)
            out["distribution"] = [{"label": str(i), "count": c.get(i, 0)} for i in range(low, int(top) + 1)]
    elif family in ("text", "date"):
        out["samples"] = [str(v)[:300] for v in values[-5:]][::-1]
    return out


def form_stats(pages: List[Dict[str, Any]], submissions: List[Dict[str, Any]], views: int = 0,
               invitations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    subs = sorted(submissions, key=lambda s: s.get("created_at") or "")
    total = len(subs)
    per_day = Counter((s.get("created_at") or "")[:10] for s in subs if s.get("created_at"))
    by_source = Counter(s.get("source") or "public" for s in subs)
    questions = []
    for field in value_fields(pages):
        vals = [s.get("data", {}).get(field["id"]) for s in subs]
        vals = [v for v in vals if v not in (None, "", [], {})]
        questions.append(question_stats(field, vals, total))
    out = {
        "total_submissions": total,
        "views": int(views or 0),
        "conversion_pct": _pct(total, views) if views else None,
        "first_at": subs[0].get("created_at") if subs else None,
        "last_at": subs[-1].get("created_at") if subs else None,
        "series": [{"date": d, "count": per_day[d]} for d in sorted(per_day)],
        "by_source": [{"source": k, "count": v} for k, v in by_source.most_common()],
        "questions": questions,
    }
    if invitations is not None:
        out["invitations"] = invitation_stats(invitations)
    return out


def invitation_stats(invitations: List[Dict[str, Any]]) -> Dict[str, Any]:
    active = [i for i in invitations if not i.get("revoked")]
    sent = len(active)
    opened = sum(1 for i in active if i.get("opened_at") or i.get("answered_at"))
    answered = sum(1 for i in active if i.get("answered_at"))
    return {"sent": sent, "opened": opened, "answered": answered, "pending": sent - answered,
            "open_pct": _pct(opened, sent), "response_pct": _pct(answered, sent)}
