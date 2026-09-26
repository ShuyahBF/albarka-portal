"""Validation d'une réponse côté serveur.

`validate_submission(pages, data)` renvoie `(propre, erreurs)` :
  - `propre` : les seules valeurs attendues, converties dans le bon type
    (nombre, booléen, liste…), champs cachés par une condition retirés ;
  - `erreurs` : {id_du_champ: message en français} — vide si tout va bien.

Les fichiers et signatures ne sont pas stockés ici : le site les enregistre
d'abord (route d'envoi de fichier) et la réponse ne contient que leur
référence {file_id, filename, size, content_type}.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Tuple

from .fields import FIELD_TYPES, value_fields

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_TEL_RE = re.compile(r"^\+?[\d\s().-]{6,20}$")
_URL_RE = re.compile(r"^https?://\S+$", re.I)
MAX_TEXT = 5000
MAX_TABLE_ROWS = 100


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def is_visible(field: Dict[str, Any], answers: Dict[str, Any]) -> bool:
    """Un champ avec `show_if` n'est affiché (donc attendu) que si le champ
    visé a la valeur indiquée (ou la contient, pour un choix multiple)."""
    cond = field.get("show_if")
    if not cond:
        return True
    target = answers.get(cond.get("field"))
    expected = cond.get("equals")
    if isinstance(target, list):
        return expected in target
    if isinstance(target, bool):
        return str(expected).lower() in (("true", "oui", "1") if target else ("false", "non", "0"))
    return str(target) == str(expected) if target is not None else False


def _clean_value(field: Dict[str, Any], v: Any) -> Tuple[Any, str]:
    """(valeur convertie, message d'erreur ou "")."""
    t = field["type"]
    if t in ("text", "textarea", "email", "tel", "url"):
        s = str(v).strip()[:MAX_TEXT]
        if t == "email" and not _EMAIL_RE.match(s):
            return s, "Adresse e-mail invalide."
        if t == "tel" and not _TEL_RE.match(s):
            return s, "Numéro de téléphone invalide."
        if t == "url" and not _URL_RE.match(s):
            return s, "Lien invalide (doit commencer par http:// ou https://)."
        if t in ("text", "textarea"):
            if field.get("min") and len(s) < field["min"]:
                return s, f"Au moins {int(field['min'])} caractères."
            if field.get("max") and len(s) > field["max"]:
                return s, f"Au plus {int(field['max'])} caractères."
        return s, ""
    if t in ("number", "rating", "scale"):
        try:
            n = float(str(v).replace(",", ".").replace(" ", ""))
        except (TypeError, ValueError):
            return v, "Nombre attendu."
        n = int(n) if n.is_integer() else n
        lo, hi = field.get("min"), field.get("max")
        if t == "rating":
            lo, hi = 1, field.get("max") or 5
        if t == "scale":
            lo, hi = 0, 10
        if lo is not None and n < lo:
            return n, f"Valeur minimale : {lo}."
        if hi is not None and n > hi:
            return n, f"Valeur maximale : {hi}."
        return n, ""
    if t in ("date", "datetime"):
        s = str(v).strip()
        try:
            datetime.fromisoformat(s.replace("Z", "+00:00") if t == "datetime" else s[:10])
        except ValueError:
            return s, "Date invalide."
        return (s[:10] if t == "date" else s[:25]), ""
    if t in ("select", "radio"):
        s = str(v)
        if s not in (field.get("options") or []):
            return s, "Choix non proposé."
        return s, ""
    if t in ("checkbox", "multiselect"):
        items = v if isinstance(v, list) else [v]
        items = [str(i) for i in items if not _empty(i)]
        bad = [i for i in items if i not in (field.get("options") or [])]
        if bad:
            return items, "Choix non proposé."
        return list(dict.fromkeys(items)), ""
    if t == "boolean":
        if isinstance(v, bool):
            return v, ""
        s = str(v).strip().lower()
        if s in ("true", "oui", "1", "yes"):
            return True, ""
        if s in ("false", "non", "0", "no"):
            return False, ""
        return v, "Répondez par oui ou non."
    if t == "table":
        if not isinstance(v, list):
            return v, "Tableau attendu."
        keys = [c["key"] for c in field.get("columns") or []]
        rows = []
        for row in v[:MAX_TABLE_ROWS]:
            if not isinstance(row, dict):
                continue
            clean = {k: str(row.get(k) or "").strip()[:500] for k in keys}
            if any(clean.values()):
                rows.append(clean)
        return rows, ""
    if t in ("file", "signature"):
        if not isinstance(v, dict) or not v.get("file_id"):
            return v, "Fichier manquant."
        return {k: v.get(k) for k in ("file_id", "filename", "size", "content_type")}, ""
    return v, ""


def validate_submission(pages: List[Dict[str, Any]], data: Any) -> Tuple[Dict[str, Any], Dict[str, str]]:
    data = data if isinstance(data, dict) else {}
    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}
    for field in value_fields(pages):
        if not FIELD_TYPES.get(field["type"], {}).get("value"):
            continue
        # La visibilité se calcule sur les réponses déjà nettoyées (champs précédents).
        if not is_visible(field, clean):
            continue
        raw = data.get(field["id"])
        if _empty(raw) or (field["type"] == "table" and isinstance(raw, list) and not any(
                any(str(x or "").strip() for x in (r or {}).values()) for r in raw if isinstance(r, dict))):
            if field.get("required"):
                errors[field["id"]] = "Ce champ est obligatoire."
            continue
        value, err = _clean_value(field, raw)
        if err:
            errors[field["id"]] = err
            continue
        if field.get("required") and _empty(value):
            errors[field["id"]] = "Ce champ est obligatoire."
            continue
        clean[field["id"]] = value
    return clean, errors
