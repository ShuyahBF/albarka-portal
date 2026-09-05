"""Endpoints publics (sans authentification) — Partie 0.

Contient uniquement des informations non sensibles destinées au site vitrine
(bouton wa.me pour convertir des prospects avant validation WABA).
"""
from __future__ import annotations

from fastapi import APIRouter

from albarka_admin_settings import get_settings_doc

router = APIRouter(prefix="/public", tags=["Public"])


@router.get("/whatsapp-contact")
async def whatsapp_contact():
    """Retourne le numéro et message pré-rempli à afficher sur le site public.

    Si aucun numéro n'est configuré, le champ `number` est vide et le
    frontend doit masquer le bouton — pas afficher un lien cassé.
    """
    settings = await get_settings_doc()
    number = (settings.get("whatsapp_contact_number") or "").strip()
    message = (
        settings.get("whatsapp_contact_message")
        or "Bonjour, je souhaite en savoir plus sur vos services comptables."
    )
    return {"number": number, "message": message}
