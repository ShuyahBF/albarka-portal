"""Actions PDF sur les documents Caisse (facture/reçu/proforma) : voir,
régénérer, envoyer par email/WhatsApp, supprimer le fichier stocké.

Le PDF est généré une première fois à la création du document (voir
albarka_phase_c.create_invoice — pas modifié ici pour éviter un import
circulaire, le point d'entrée est `ensure_invoice_pdf`) puis mis en cache
dans le stockage objet (R2 ou local, voir albarka_storage.py). Le fichier
stocké n'est jamais la source de vérité : "Régénérer" et l'auto-guérison en
lecture (fichier manquant/perdu) reconstruisent toujours le PDF depuis les
données Mongo de la facture — jamais l'inverse.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from albarka_auth import require_roles
from albarka_models import CAISSE_PDF_ACTION_ROLES
from albarka_storage import build_path, delete_object, get_object, put_object
from db import db

logger = logging.getLogger("albarka.billing_docs")

router = APIRouter(prefix="/billing/invoices", tags=["Caisse — actions PDF"])

# Le téléchargement du fichier brut est en plus soumis au rôle cumulable
# "telechargement" — mêmes conventions que DOWNLOAD_ROLES dans
# albarka_documents.py. Voir/régénérer/envoyer/supprimer restent ouverts aux
# CAISSE_PDF_ACTION_ROLES sans cette condition supplémentaire.
def _can_download(user: dict) -> bool:
    return "telechargement" in (user.get("roles") or [])


_DOC_LABEL = {"recu": "reçu", "proforma": "proforma", "facture": "facture"}


async def _get_invoice_or_404(invoice_id: str) -> dict:
    invoice = await db.invoices.find_one({"id": invoice_id}, {"_id": 0})
    if not invoice:
        raise HTTPException(status_code=404, detail="Document introuvable")
    return invoice


async def build_pdf_bytes(invoice: dict) -> bytes:
    from albarka_reports import build_invoice_document_pdf

    client = None
    if invoice.get("tenant_id"):
        client = await db.users.find_one({"id": invoice["tenant_id"]}, {"_id": 0, "password_hash": 0})
    payments = await db.payments.find(
        {"invoice_id": invoice["id"]}, {"_id": 0},
    ).sort("paid_at", 1).to_list(500)
    return build_invoice_document_pdf(invoice=invoice, client=client, payments=payments)


async def ensure_invoice_pdf(invoice: dict) -> dict:
    """Génère + stocke le PDF si absent, renvoie l'enregistrement invoice à
    jour (avec pdf_storage_path). Appelée à la création du document et en
    lecture (auto-guérison si le fichier a été perdu)."""
    if invoice.get("pdf_storage_path"):
        return invoice
    pdf_bytes = await build_pdf_bytes(invoice)
    path = build_path(f"{invoice['document_type']}_pdf", invoice["tenant_id"], "pdf")
    await put_object(path, pdf_bytes, "application/pdf")
    await db.invoices.update_one(
        {"id": invoice["id"]},
        {"$set": {"pdf_storage_path": path, "pdf_generated_at": datetime.now(timezone.utc).isoformat()}},
    )
    invoice["pdf_storage_path"] = path
    return invoice


@router.get("/{invoice_id}/pdf")
async def view_invoice_pdf(
    invoice_id: str,
    download: bool = False,
    user: dict = Depends(require_roles(CAISSE_PDF_ACTION_ROLES)),
):
    """Affichage inline par défaut (ouverture dans un nouvel onglet) ;
    `?download=true` force le téléchargement — réservé en plus au rôle
    cumulable "telechargement"."""
    from fastapi.responses import Response

    invoice = await _get_invoice_or_404(invoice_id)
    if download and not _can_download(user):
        raise HTTPException(status_code=403, detail="Téléchargement réservé au rôle Téléchargement")
    invoice = await ensure_invoice_pdf(invoice)
    try:
        data, _ct = await get_object(invoice["pdf_storage_path"])
    except Exception:  # noqa: BLE001 — fichier perdu malgré le pointeur : on régénère
        logger.warning("PDF manquant pour %s malgré pdf_storage_path, régénération", invoice_id)
        await db.invoices.update_one({"id": invoice_id}, {"$set": {"pdf_storage_path": None}})
        invoice["pdf_storage_path"] = None
        invoice = await ensure_invoice_pdf(invoice)
        data, _ct = await get_object(invoice["pdf_storage_path"])
    disposition = "attachment" if download else "inline"
    filename = f"{invoice['document_type']}_{invoice['number']}.pdf"
    return Response(
        content=data, media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.post("/{invoice_id}/pdf/regenerate")
async def regenerate_invoice_pdf(
    invoice_id: str, user: dict = Depends(require_roles(CAISSE_PDF_ACTION_ROLES)),
):
    """Reconstruit le PDF depuis les données actuelles de la facture — utile
    si le fichier stocké a été perdu, ou après une modification (paiement,
    etc.) qui rend le PDF caché obsolète."""
    invoice = await _get_invoice_or_404(invoice_id)
    pdf_bytes = await build_pdf_bytes(invoice)
    path = build_path(f"{invoice['document_type']}_pdf", invoice["tenant_id"], "pdf")
    await put_object(path, pdf_bytes, "application/pdf")
    await db.invoices.update_one(
        {"id": invoice_id},
        {"$set": {"pdf_storage_path": path, "pdf_generated_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {"ok": True, "id": invoice_id, "regenerated_at": datetime.now(timezone.utc).isoformat()}


@router.delete("/{invoice_id}/pdf")
async def delete_invoice_pdf(
    invoice_id: str, user: dict = Depends(require_roles(CAISSE_PDF_ACTION_ROLES)),
):
    """Supprime uniquement le fichier PDF mis en cache — jamais l'écriture
    comptable (facture/reçu) elle-même, qui reste dans `invoices`. Peut être
    régénéré à tout moment via /pdf/regenerate ou une simple lecture."""
    invoice = await _get_invoice_or_404(invoice_id)
    if not invoice.get("pdf_storage_path"):
        raise HTTPException(status_code=404, detail="Aucun PDF associé à ce document")
    try:
        await delete_object(invoice["pdf_storage_path"])
    except Exception:  # noqa: BLE001
        logger.warning("Échec suppression fichier PDF %s (poursuite)", invoice["pdf_storage_path"])
    await db.invoices.update_one({"id": invoice_id}, {"$set": {"pdf_storage_path": None}})
    return {"ok": True, "id": invoice_id}


class SendInvoicePayload(BaseModel):
    channel: str = "whatsapp"  # "whatsapp" | "email"


@router.post("/{invoice_id}/send")
async def send_invoice_document(
    invoice_id: str, payload: SendInvoicePayload,
    user: dict = Depends(require_roles(CAISSE_PDF_ACTION_ROLES)),
):
    from albarka_documents import _can_send_whatsapp
    from albarka_models import whatsapp_number_of
    from albarka_notifications import _wa_upload_media, send_email, send_whatsapp_document

    invoice = await _get_invoice_or_404(invoice_id)
    client = await db.users.find_one({"id": invoice.get("tenant_id")}, {"_id": 0, "password_hash": 0})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    invoice = await ensure_invoice_pdf(invoice)
    data, _ct = await get_object(invoice["pdf_storage_path"])
    filename = f"{invoice['document_type']}_{invoice['number']}.pdf"
    label = _DOC_LABEL.get(invoice["document_type"], "document")

    if payload.channel == "email":
        recipient = (client.get("email") or "").strip()
        if not recipient:
            raise HTTPException(status_code=400, detail="Aucune adresse email disponible pour ce client")
        client_label = client.get("company") or client.get("full_name", "")
        html = (
            f"<div style=\"font-family:Arial,sans-serif;color:#0F172A;padding:16px;\">"
            f"<p>Bonjour,</p><p>Veuillez trouver ci-joint votre {label} "
            f"<strong>{invoice['number']}</strong> ({client_label}).</p></div>"
        )
        attachment = {
            "filename": filename,
            "content": base64.b64encode(data).decode("ascii"),
            "content_type": "application/pdf",
        }
        message_id = await send_email(
            to=[recipient], subject=f"{label.capitalize()} {invoice['number']}", html=html, attachments=[attachment],
        )
        if not message_id:
            raise HTTPException(status_code=502, detail="Échec envoi email (proxy indisponible ou rejeté)")
        return {"ok": True, "channel": "email", "to": recipient}

    if not _can_send_whatsapp(user, client):
        raise HTTPException(
            status_code=403,
            detail="Envoi WhatsApp réservé au rôle Communication sur un numéro attesté vérifié "
                   "(ou aux rôles superviseur/direction/DG/administrateur/secrétariat)",
        )
    phone = whatsapp_number_of(client) or ""
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp éligible (format +226…) pour ce client")
    media_id = await _wa_upload_media(pdf_bytes=data, filename=filename)
    if not media_id:
        raise HTTPException(status_code=502, detail="Échec de l'envoi (WhatsApp non configuré ou upload refusé)")
    result = await send_whatsapp_document(
        to_phone=phone, media_id=media_id, filename=filename,
        caption=f"{label.capitalize()} {invoice['number']}",
    )
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp : {result.get('error') or 'erreur inconnue'}")
    return {"ok": True, "channel": "whatsapp", "to": phone, "message_id": result.get("message_id")}
