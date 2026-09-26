"""Catalogue des types de champs et normalisation d'un formulaire.

Un formulaire est stocké sous la forme :
    {
      "title": str, "description": str,
      "pages": [ {"id": str, "title": str, "fields": [FIELD, ...]} ],
      "settings": {...}   # voir normalize_settings()
    }
et chaque champ (FIELD) :
    {
      "id": str,                 # identifiant stable (clé des réponses)
      "type": str,               # voir FIELD_TYPES
      "label": str,
      "help": str,               # texte d'aide sous le champ
      "required": bool,
      "width": "full" | "half",  # pleine largeur ou moitié
      "placeholder": str,
      "options": [str],          # select / radio / checkbox / multiselect
      "min": number, "max": number,   # number / rating / scale ; longueur pour text
      "columns": [{"key", "label", "type"}],  # table
      "accept": str,             # file : types acceptés (".pdf,image/*")
      "show_if": {"field": id, "equals": valeur} | None,   # affichage conditionnel
    }

Ce module ne connaît ni base de données, ni HTTP : il se contente de
décrire et de nettoyer.
"""
from __future__ import annotations

import re
import secrets
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Catalogue : type → libellé français, famille (pour les statistiques) et
# indication « porte une valeur » (un titre de section n'en porte pas).
# L'ordre est celui de la palette du constructeur.
# ---------------------------------------------------------------------------
FIELD_TYPES: Dict[str, Dict[str, Any]] = {
    "text":        {"label": "Texte court",            "family": "text",    "value": True},
    "textarea":    {"label": "Paragraphe",             "family": "text",    "value": True},
    "email":       {"label": "E-mail",                 "family": "text",    "value": True},
    "tel":         {"label": "Téléphone",              "family": "text",    "value": True},
    "number":      {"label": "Nombre",                 "family": "number",  "value": True},
    "date":        {"label": "Date",                   "family": "date",    "value": True},
    "datetime":    {"label": "Date et heure",          "family": "date",    "value": True},
    "select":      {"label": "Liste déroulante",       "family": "choice",  "value": True},
    "radio":       {"label": "Choix unique",           "family": "choice",  "value": True},
    "checkbox":    {"label": "Cases à cocher",         "family": "multi",   "value": True},
    "multiselect": {"label": "Choix multiples (liste)", "family": "multi",  "value": True},
    "boolean":     {"label": "Oui / Non",              "family": "boolean", "value": True},
    "rating":      {"label": "Note (étoiles)",         "family": "number",  "value": True},
    "scale":       {"label": "Échelle 0-10",           "family": "number",  "value": True},
    "url":         {"label": "Lien (URL)",             "family": "text",    "value": True},
    "table":       {"label": "Tableau",                "family": "table",   "value": True},
    "file":        {"label": "Fichier joint",          "family": "file",    "value": True},
    "signature":   {"label": "Signature",              "family": "file",    "value": True},
    "section":     {"label": "Titre / texte",          "family": "none",    "value": False},
}

CHOICE_TYPES = {"select", "radio", "checkbox", "multiselect"}
MAX_PAGES = 20
MAX_FIELDS = 150
MAX_OPTIONS = 60
MAX_LABEL = 300
MAX_HELP = 1000
TABLE_COLUMN_TYPES = {"text", "number", "date"}
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")


def new_id(prefix: str = "f") -> str:
    """Identifiant court et stable pour un champ ou une page."""
    return f"{prefix}_{secrets.token_hex(4)}"


def _s(value: Any, limit: int) -> str:
    """Texte nettoyé (espaces de début/fin retirés), tronqué à `limit`."""
    return str(value or "").strip()[:limit]


def _num(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        n = float(value)
        return int(n) if n.is_integer() else n
    except (TypeError, ValueError):
        return None


def normalize_field(raw: Dict[str, Any], seen_ids: set) -> Optional[Dict[str, Any]]:
    """Champ propre à partir de ce qu'envoie le constructeur ; None si le type
    est inconnu. Les identifiants sont conservés (clés des réponses déjà
    reçues) et rendus uniques si besoin."""
    ftype = str(raw.get("type") or "").strip()
    if ftype not in FIELD_TYPES:
        return None
    fid = str(raw.get("id") or "")
    if not _ID_RE.match(fid) or fid in seen_ids:
        fid = new_id()
    seen_ids.add(fid)
    field: Dict[str, Any] = {
        "id": fid,
        "type": ftype,
        "label": _s(raw.get("label"), MAX_LABEL) or FIELD_TYPES[ftype]["label"],
        "help": _s(raw.get("help"), MAX_HELP),
        "required": bool(raw.get("required")) and FIELD_TYPES[ftype]["value"],
        "width": "half" if raw.get("width") == "half" else "full",
        "placeholder": _s(raw.get("placeholder"), 200),
    }
    if ftype in CHOICE_TYPES:
        opts: List[str] = []
        for o in raw.get("options") or []:
            o = _s(o, 200)
            if o and o not in opts:
                opts.append(o)
        field["options"] = opts[:MAX_OPTIONS] or ["Option 1"]
    if ftype in {"number", "text", "textarea"}:
        field["min"] = _num(raw.get("min"))
        field["max"] = _num(raw.get("max"))
    if ftype == "rating":
        field["max"] = int(min(max(_num(raw.get("max")) or 5, 3), 10))
    if ftype == "table":
        cols = []
        for i, c in enumerate(raw.get("columns") or []):
            label = _s((c or {}).get("label"), 100)
            if not label:
                continue
            ctype = (c or {}).get("type") if (c or {}).get("type") in TABLE_COLUMN_TYPES else "text"
            key = str((c or {}).get("key") or "") if _ID_RE.match(str((c or {}).get("key") or "")) else f"c{i + 1}"
            cols.append({"key": key, "label": label, "type": ctype})
        field["columns"] = cols[:12] or [{"key": "c1", "label": "Colonne 1", "type": "text"}]
    if ftype == "file":
        field["accept"] = _s(raw.get("accept"), 200)
    cond = raw.get("show_if")
    if isinstance(cond, dict) and cond.get("field"):
        field["show_if"] = {"field": str(cond.get("field"))[:40], "equals": cond.get("equals")}
    else:
        field["show_if"] = None
    return field


def normalize_pages(raw_pages: Any) -> List[Dict[str, Any]]:
    """Pages propres : au moins une page, 150 champs au plus au total, et
    conditions d'affichage qui ne pointent que vers un champ précédent."""
    pages: List[Dict[str, Any]] = []
    seen_ids: set = set()
    count = 0
    for i, rp in enumerate((raw_pages or [])[:MAX_PAGES]):
        rp = rp or {}
        pid = str(rp.get("id") or "")
        page = {"id": pid if _ID_RE.match(pid) else new_id("p"), "title": _s(rp.get("title"), 120) or f"Page {i + 1}",
                "fields": []}
        for rf in rp.get("fields") or []:
            if count >= MAX_FIELDS:
                break
            field = normalize_field(rf or {}, seen_ids)
            if field:
                page["fields"].append(field)
                count += 1
        pages.append(page)
    if not pages:
        pages = [{"id": new_id("p"), "title": "Page 1", "fields": []}]
    # Une condition ne peut viser qu'un champ placé AVANT (pas de boucle).
    earlier: set = set()
    for page in pages:
        for field in page["fields"]:
            if field.get("show_if") and field["show_if"]["field"] not in earlier:
                field["show_if"] = None
            earlier.add(field["id"])
    return pages


DEFAULT_SETTINGS: Dict[str, Any] = {
    "accepting_responses": True,      # formulaire ouvert aux réponses
    "close_at": None,                 # date/heure ISO de fermeture automatique
    "confirmation_message": "Merci, votre réponse a bien été enregistrée.",
    "respondent_info": "optional",    # none | optional | required (nom + e-mail, lien public)
    "allow_edit": False,              # un destinataire invité peut modifier sa réponse
    "notify_emails": [],              # e-mails prévenus à chaque réponse
    "public_multiple": True,          # lien public : plusieurs réponses possibles
}


def normalize_settings(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_SETTINGS)
    out["accepting_responses"] = bool(raw.get("accepting_responses", True))
    close_at = raw.get("close_at")
    out["close_at"] = str(close_at)[:40] if close_at else None
    out["confirmation_message"] = _s(raw.get("confirmation_message"), 1000) or DEFAULT_SETTINGS["confirmation_message"]
    out["respondent_info"] = raw.get("respondent_info") if raw.get("respondent_info") in ("none", "optional", "required") else "optional"
    out["allow_edit"] = bool(raw.get("allow_edit"))
    out["public_multiple"] = bool(raw.get("public_multiple", True))
    emails = []
    for e in raw.get("notify_emails") or []:
        e = _s(e, 200).lower()
        if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", e) and e not in emails:
            emails.append(e)
    out["notify_emails"] = emails[:10]
    return out


def value_fields(pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Tous les champs qui portent une valeur, dans l'ordre (sans les sections)."""
    return [f for p in pages or [] for f in p.get("fields") or [] if FIELD_TYPES.get(f.get("type"), {}).get("value")]


def public_definition(form: Dict[str, Any]) -> Dict[str, Any]:
    """Ce qu'un répondant a le droit de voir du formulaire (pas les réglages
    internes, ni les e-mails prévenus, ni les compteurs)."""
    s = form.get("settings") or {}
    return {
        "id": form.get("id"), "number": form.get("number"),
        "title": form.get("title"), "description": form.get("description") or "",
        "pages": form.get("pages") or [],
        "settings": {
            "confirmation_message": s.get("confirmation_message") or DEFAULT_SETTINGS["confirmation_message"],
            "respondent_info": s.get("respondent_info") or "optional",
        },
    }


def field_catalog() -> List[Dict[str, Any]]:
    """Catalogue pour l'écran (palette du constructeur)."""
    return [{"type": t, "label": meta["label"], "family": meta["family"]} for t, meta in FIELD_TYPES.items()]
