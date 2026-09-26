"""Contexte de la requête en cours (adresse IP, navigateur) — pour que le
Journal plateforme enregistre l'IP de chaque action sans passer la requête
à toutes les fonctions. Rempli par un middleware (server.py)."""
from __future__ import annotations

from contextvars import ContextVar
from typing import Dict

_request_info: ContextVar[Dict[str, str]] = ContextVar("albarka_request_info", default={})


def set_request_info(ip: str, user_agent: str) -> None:
    _request_info.set({"ip": ip or "", "user_agent": (user_agent or "")[:250]})


def request_info() -> Dict[str, str]:
    """{ip, user_agent} de la requête en cours ({} hors requête : tâches planifiées)."""
    return _request_info.get()
