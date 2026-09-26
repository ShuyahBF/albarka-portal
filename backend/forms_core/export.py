"""Export des réponses.

- `readable_value(field, value)` : valeur lisible (listes jointes, oui/non,
  nom du fichier au lieu de l'objet, tableau ligne par ligne…).
- `submissions_rows(pages, submissions)` : en-tête + lignes.
- `to_csv(rows)` : CSV UTF-8 avec BOM et séparateur « ; » — s'ouvre
  directement dans Excel en français (accents et colonnes corrects).
"""
from __future__ import annotations

import csv
import io
from typing import Any, Dict, List

from .fields import value_fields


def readable_value(field: Dict[str, Any], value: Any) -> str:
    if value is None or value == "":
        return ""
    t = field.get("type")
    if t == "boolean":
        return "Oui" if value is True else "Non" if value is False else str(value)
    if isinstance(value, list) and t == "table":
        cols = field.get("columns") or []
        return " | ".join(", ".join(f"{c['label']}: {row.get(c['key'], '')}" for c in cols) for row in value if isinstance(row, dict))
    if isinstance(value, list):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        if t == "signature":
            return "Signé"
        return str(value.get("filename") or value.get("file_id") or "")
    return str(value)


def submissions_rows(pages: List[Dict[str, Any]], submissions: List[Dict[str, Any]]) -> List[List[str]]:
    fields = value_fields(pages)
    header = ["N°", "Date", "Répondant", "E-mail", "Origine"] + [f.get("label") or f["id"] for f in fields]
    rows = [header]
    source_labels = {"invitation": "Invitation", "public": "Lien public", "portal": "Espace client"}
    for i, s in enumerate(sorted(submissions, key=lambda x: x.get("created_at") or ""), start=1):
        data = s.get("data") or {}
        rows.append([
            str(i),
            (s.get("created_at") or "")[:16].replace("T", " "),
            s.get("respondent_name") or "",
            s.get("respondent_email") or "",
            source_labels.get(s.get("source") or "public", s.get("source") or ""),
        ] + [readable_value(f, data.get(f["id"])) for f in fields])
    return rows


def to_csv(rows: List[List[str]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";", quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    for row in rows:
        writer.writerow(row)
    return ("﻿" + buf.getvalue()).encode("utf-8")
