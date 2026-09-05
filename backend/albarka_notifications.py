"""Notifications ALBARKA — email (Resend Emergent-managed) + WhatsApp (Meta Cloud API).

Le WhatsApp utilise l'API WhatsApp Business officielle (Meta Graph). La config
est stockée dans la collection `settings` (`_id="global"`) via l'écran
Paramètres Admin : `wa_enabled`, `wa_access_token`, `wa_phone_number_id`,
`wa_business_account_id`, `wa_graph_version`.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
from html import escape
from html.parser import HTMLParser
from typing import Optional
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("albarka.notifications")

EMAIL_BASE_URL = "https://integrations.emergentagent.com"
EMAIL_KEY = os.environ.get("EMERGENT_EMAIL_KEY", "")
EMAIL_FROM_NAME_DEFAULT = os.environ.get("EMAIL_FROM_NAME", "Cabinet ALBARKA")
EMAIL_REPLY_TO = os.environ.get("EMAIL_REPLY_TO")

# --- Guardrail helpers (from Resend playbook) ---------------------------
_SHORTENERS = ("bit.ly", "tinyurl.com", "t.co", "is.gd", "cutt.ly", "goo.gl", "rebrand.ly")
_CRED_ASK = (
    "reply with your password", "reply with the code", "send your password", "cvv",
    "send us your password", "enter your password below", "confirm your card number",
    "your full card number", "seed phrase", "recovery phrase", "verify your card",
    "social security number", "confirm your bank details",
)
_HOSTISH = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+[a-z]{2,})", re.I)


def _host_ok(host: str) -> bool:
    if not host or "xn--" in host:
        return False
    try:
        ipaddress.ip_address(host)
        return False
    except ValueError:
        pass
    return not any(host == s or host.endswith("." + s) for s in _SHORTENERS)


def _same_site(shown: str, real: str) -> bool:
    return shown == real or real.endswith("." + shown) or shown.endswith("." + real)


class _EmailScan(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.urls, self.anchors = set(), [], []
        self._href, self._text = None, []
    def handle_starttag(self, tag, attrs):
        self.tags.add(tag.lower())
        self.urls += [v for k, v in attrs if k.lower() in ("href", "src") and v]
        if tag.lower() == "a":
            self._href = dict((k.lower(), v) for k, v in attrs).get("href")
            self._text = []
    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)
    def handle_endtag(self, tag):
        if tag.lower() == "a" and self._href is not None:
            self.anchors.append((self._href, "".join(self._text)))
            self._href, self._text = None, []


def _assert_safe_email(subject: str, html: str) -> None:
    scan = _EmailScan(); scan.feed(html)
    if scan.tags & {"form", "input", "textarea", "select"}:
        raise ValueError("No forms or input fields in email (G2)")
    body = f"{subject}\n{html}".lower()
    for p in _CRED_ASK:
        if p in body:
            raise ValueError(f"Email asks the recipient for credentials: {p!r} (G2)")
    for url in scan.urls:
        low = url.strip().lower()
        if low.startswith(("mailto:", "tel:", "cid:", "#")):
            continue
        if not low.startswith("https://"):
            raise ValueError(f"Email links/assets must be absolute https: {url!r} (G3)")
        host = urlparse(low).hostname or ""
        if not _host_ok(host) or urlparse(low).username is not None:
            raise ValueError(f"Shortened, numeric-host or credential-bearing URL: {url!r} (G3)")
    for href, text in scan.anchors:
        real = urlparse(href.strip().lower()).hostname or ""
        if not real:
            continue
        for m in _HOSTISH.finditer(text):
            if not _same_site(m.group(1).lower(), real):
                raise ValueError(f"Anchor text {m.group(1)!r} ≠ real link host {real!r} (G3)")


async def _get_email_config() -> dict:
    """Loads from_name / from_email / reply_to from settings, with env fallback."""
    try:
        from albarka_admin_settings import get_settings_doc
        s = await get_settings_doc()
    except Exception:
        s = {}
    return {
        "from_name": (s.get("cabinet_name") or EMAIL_FROM_NAME_DEFAULT).strip() or EMAIL_FROM_NAME_DEFAULT,
        "from_email": (s.get("email_from_address") or "").strip() or None,
        "reply_to": (s.get("email_reply_to") or EMAIL_REPLY_TO or "").strip() or None,
    }


async def _get_from_name() -> str:
    cfg = await _get_email_config()
    return cfg["from_name"]


async def send_email(*, to, subject: str, html: str, reply_to: Optional[str] = None,
                    attachments: Optional[list] = None) -> Optional[str]:
    """Non-blocking send via the Emergent-managed Resend proxy.

    `to` accepts a string or a list of recipients (single call with multi-to).
    `attachments` optionnel : liste de {filename, content (base64), content_type}.
    """
    if not EMAIL_KEY:
        logger.info("EMERGENT_EMAIL_KEY absent — envoi email ignoré (dev/pilote).")
        return None
    _assert_safe_email(subject, html)
    cfg = await _get_email_config()
    to_list = [to] if isinstance(to, str) else [t for t in to if t]
    if not to_list:
        return None
    payload = {"to": to_list, "subject": subject, "html": html, "from_name": cfg["from_name"]}
    if cfg["from_email"]:
        payload["from_email"] = cfg["from_email"]
    effective_reply = reply_to or cfg["reply_to"]
    if effective_reply:
        payload["contact_email"] = effective_reply
    if attachments:
        payload["attachments"] = attachments
    try:
        async with httpx.AsyncClient(timeout=45) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        logger.exception("Échec envoi email à %s", to_list)
        return None


# --- WhatsApp via Meta Cloud API (config depuis settings) ---------------
async def _get_wa_config() -> Optional[dict]:
    try:
        from albarka_admin_settings import get_settings_doc
        s = await get_settings_doc()
    except Exception:
        return None
    if not s.get("wa_enabled"):
        return None
    token = (s.get("wa_access_token") or "").strip()
    phone_id = (s.get("wa_phone_number_id") or "").strip()
    if not token or not phone_id:
        return None
    return {
        "access_token": token,
        "phone_number_id": phone_id,
        "graph_version": (s.get("wa_graph_version") or "v22.0").strip(),
    }


def _wa_split_long_text(text: str, max_len: int = 4096) -> list[str]:
    """Découpe un message trop long en segments <= max_len sans couper de mot
    quand c'est possible. Renvoie toujours au moins un segment.
    """
    if not text:
        return [""]
    if len(text) <= max_len:
        return [text]
    segments: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        # Cherche le dernier espace/retour ligne avant max_len pour ne pas
        # couper un mot au milieu.
        cut = remaining.rfind("\n", 0, max_len)
        if cut <= 0:
            cut = remaining.rfind(" ", 0, max_len)
        if cut <= 0:
            cut = max_len  # rien à faire — on coupe brutalement
        segments.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    if remaining:
        segments.append(remaining)
    return segments


async def _wa_last_inbound_iso(phone: str) -> Optional[str]:
    """Retourne l'ISO datetime du dernier message entrant reçu de ce numéro
    (via webhook Meta), ou None si aucun.
    """
    from db import db  # local import to avoid cycles
    doc = await db.wa_messages.find_one(
        {"phone": phone, "direction": "inbound"},
        {"_id": 0, "created_at": 1},
        sort=[("created_at", -1)],
    )
    return doc.get("created_at") if doc else None


def _wa_window_open(last_inbound_iso: Optional[str], window_seconds: int = 86400) -> Optional[bool]:
    """La fenêtre WhatsApp de 24h est-elle ouverte ?

    Retourne True si le dernier message entrant est plus récent que
    (now - window_seconds), False sinon, None si l'information n'est pas
    disponible (webhook pas encore configuré ou aucun message reçu).
    """
    if not last_inbound_iso:
        return None
    from datetime import datetime, timezone
    try:
        # Support ISO 8601 avec ou sans microsecondes / Z suffix
        s = last_inbound_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        elapsed = (datetime.now(timezone.utc) - dt).total_seconds()
        return elapsed < window_seconds
    except (ValueError, TypeError):
        return None


async def send_whatsapp(*, to_phone: str, message: str) -> dict:
    """Envoie un WhatsApp via l'API Meta Graph.

    Retourne un dictionnaire structuré :
      { ok: bool, message_id: str|None, message_ids: list[str] (segments),
        status: int|None, error: str|None,
        kind: "success"|"http_error"|"silent_drop"|"not_configured"|"invalid_phone",
        outside_24h_window: bool|None }

    Un message > 4096 caractères est **découpé** en plusieurs envois
    séquentiels (jamais tronqué silencieusement — cf. Partie 2.A).
    """
    cfg = await _get_wa_config()
    if not cfg:
        logger.info("WhatsApp non configuré — envoi vers %s ignoré.", to_phone)
        return {"ok": False, "message_id": None, "message_ids": [],
                "status": None, "error": "wa_not_configured",
                "kind": "not_configured", "outside_24h_window": None}
    if not to_phone or not to_phone.startswith("+"):
        logger.warning("Téléphone WA invalide (attendu +226…) : %r", to_phone)
        return {"ok": False, "message_id": None, "message_ids": [],
                "status": None, "error": "invalid_phone",
                "kind": "invalid_phone", "outside_24h_window": None}
    window_state = _wa_window_open(await _wa_last_inbound_iso(to_phone))
    outside = (window_state is False)  # False = fermée ; None = indéterminée
    to = to_phone.lstrip("+")
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/messages"
    headers = {
        "Authorization": f"Bearer {cfg['access_token']}",
        "Content-Type": "application/json",
    }
    segments = _wa_split_long_text(message)
    message_ids: list[str] = []
    last_status = None
    last_error = None
    async with httpx.AsyncClient(timeout=30) as client:
        for i, segment in enumerate(segments):
            payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": to,
                "type": "text",
                "text": {"preview_url": False, "body": segment},
            }
            try:
                resp = await client.post(url, json=payload, headers=headers)
                last_status = resp.status_code
                if resp.status_code >= 300:
                    last_error = resp.text[:400]
                    logger.warning(
                        "WA HTTP %s vers %s (segment %d/%d) : %s",
                        resp.status_code, to_phone, i + 1, len(segments), last_error,
                    )
                    return {"ok": False, "message_id": None,
                            "message_ids": message_ids, "status": last_status,
                            "error": last_error, "kind": "http_error",
                            "outside_24h_window": outside if window_state is not None else None}
                data = resp.json()
                messages = data.get("messages") or []
                mid = messages[0].get("id") if messages else None
                if not mid:
                    # 2xx sans message_id — Meta a "accepté" mais rejeté sans le dire.
                    last_error = str(data)[:400]
                    logger.warning(
                        "WA silent drop vers %s (segment %d/%d) : %s",
                        to_phone, i + 1, len(segments), last_error,
                    )
                    return {"ok": False, "message_id": None,
                            "message_ids": message_ids, "status": last_status,
                            "error": "silent_drop", "kind": "silent_drop",
                            "outside_24h_window": outside if window_state is not None else None}
                message_ids.append(mid)
            except httpx.HTTPError as exc:
                logger.exception("Échec envoi WA à %s", to_phone)
                return {"ok": False, "message_id": None,
                        "message_ids": message_ids, "status": last_status,
                        "error": str(exc)[:400], "kind": "http_error",
                        "outside_24h_window": outside if window_state is not None else None}
    return {
        "ok": True, "message_id": message_ids[0] if message_ids else None,
        "message_ids": message_ids, "status": last_status, "error": None,
        "kind": "success", "outside_24h_window": outside if window_state is not None else None,
    }


async def _wa_upload_media(*, pdf_bytes: bytes, filename: str, content_type: str = "application/pdf") -> Optional[str]:
    """Upload un fichier à la Media API Meta, retourne le media_id ou None.

    `content_type` par défaut à "application/pdf" pour ne pas changer le
    comportement des appelants historiques (rapports, toujours des PDF) ;
    les pièces client de type image/Office doivent passer leur vrai type MIME,
    sinon Meta reçoit un contenu mal étiqueté."""
    cfg = await _get_wa_config()
    if not cfg:
        return None
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/media"
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                headers={"Authorization": f"Bearer {cfg['access_token']}"},
                data={"messaging_product": "whatsapp", "type": content_type},
                files={"file": (filename, pdf_bytes, content_type)},
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        logger.exception("Upload media WA échoué (%s)", filename)
        return None


async def _wa_send_media_message(*, to_phone: str, msg_type: str, media_payload: dict) -> dict:
    """Cœur partagé d'envoi d'un message média (document ou image) déjà
    uploadé — même contrat de retour que send_whatsapp."""
    cfg = await _get_wa_config()
    if not cfg:
        return {"ok": False, "message_id": None, "status": None,
                "error": "wa_not_configured", "kind": "not_configured",
                "outside_24h_window": None}
    if not to_phone or not to_phone.startswith("+"):
        return {"ok": False, "message_id": None, "status": None,
                "error": "invalid_phone", "kind": "invalid_phone",
                "outside_24h_window": None}
    window_state = _wa_window_open(await _wa_last_inbound_iso(to_phone))
    outside = (window_state is False)
    to = to_phone.lstrip("+")
    url = f"https://graph.facebook.com/{cfg['graph_version']}/{cfg['phone_number_id']}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": msg_type,
        msg_type: media_payload,
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                url, json=payload,
                headers={"Authorization": f"Bearer {cfg['access_token']}", "Content-Type": "application/json"},
            )
        if resp.status_code >= 300:
            return {"ok": False, "message_id": None, "status": resp.status_code,
                    "error": resp.text[:400], "kind": "http_error",
                    "outside_24h_window": outside if window_state is not None else None}
        data = resp.json()
        messages = data.get("messages") or []
        mid = messages[0].get("id") if messages else None
        if not mid:
            return {"ok": False, "message_id": None, "status": resp.status_code,
                    "error": "silent_drop", "kind": "silent_drop",
                    "outside_24h_window": outside if window_state is not None else None}
        return {"ok": True, "message_id": mid, "status": resp.status_code,
                "error": None, "kind": "success",
                "outside_24h_window": outside if window_state is not None else None}
    except httpx.HTTPError as exc:
        logger.exception("Envoi média WA (%s) échoué vers %s", msg_type, to_phone)
        return {"ok": False, "message_id": None, "status": None,
                "error": str(exc)[:400], "kind": "http_error",
                "outside_24h_window": outside if window_state is not None else None}


async def send_whatsapp_document(
    *, to_phone: str, media_id: str, filename: str, caption: str = "",
) -> dict:
    """Envoie un document (PDF, Office…) déjà uploadé."""
    return await _wa_send_media_message(
        to_phone=to_phone, msg_type="document",
        media_payload={"id": media_id, "filename": filename, "caption": caption[:1024]},
    )


async def send_whatsapp_image(
    *, to_phone: str, media_id: str, caption: str = "",
) -> dict:
    """Envoie une image déjà uploadée. Meta n'accepte pas les images via le
    type de message "document" — elles doivent passer par le type "image"."""
    return await _wa_send_media_message(
        to_phone=to_phone, msg_type="image",
        media_payload={"id": media_id, "caption": caption[:1024]},
    )



# --- Email templates ----------------------------------------------------
def _echeance_email_html(*, full_name: str, echeance: dict, days_left: int, cabinet_name: str) -> str:
    if days_left < 0:
        urgency_color = "#B91C1C"
        urgency_text = f"Cette échéance est en retard de {-days_left} jour{'s' if -days_left > 1 else ''}."
    elif days_left == 0:
        urgency_color = "#B91C1C"
        urgency_text = "Cette échéance est à traiter aujourd'hui."
    else:
        urgency_color = "#B45309" if days_left > 1 else "#B91C1C"
        urgency_text = f"Cette échéance arrive dans {days_left} jour{'s' if days_left > 1 else ''}."
    period = echeance.get("period") or "—"
    amount = f"{int(echeance['amount']):,} FCFA".replace(",", " ") if echeance.get("amount") else "—"
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBFAF4;padding:24px 0;font-family:Arial,sans-serif;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="background:#0B1912;padding:24px 32px;color:#ffffff;">
        <div style="font-size:12px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">{escape(cabinet_name)}</div>
        <div style="font-size:22px;margin-top:4px;font-family:Georgia,serif;">Rappel d'échéance</div>
      </td></tr>
      <tr><td style="padding:32px;color:#0F172A;">
        <p style="margin:0 0 12px 0;">Bonjour {escape(full_name)},</p>
        <p style="margin:0 0 16px 0;">{urgency_text}</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F8FAF7;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:16px 0;">
          <tr><td>
            <div style="font-size:14px;color:#64748B;">{escape(echeance.get('type', '').upper())}</div>
            <div style="font-size:18px;font-weight:600;color:#0F6B4A;margin-top:4px;">{escape(echeance.get('title', ''))}</div>
            <div style="margin-top:12px;font-size:14px;color:#0F172A;">
              <div><strong>Date limite :</strong> {escape(str(echeance.get('due_date', '')))}</div>
              <div><strong>Période :</strong> {escape(period)}</div>
              <div><strong>Montant :</strong> {amount}</div>
            </div>
          </td></tr>
        </table>
        <p style="margin:16px 0 0 0;color:{urgency_color};font-weight:600;">
          Merci de préparer les pièces nécessaires et de contacter votre gestionnaire au cabinet.
        </p>
        <p style="margin:24px 0 0 0;font-size:13px;color:#64748B;">
          Ce message est envoyé automatiquement par {escape(cabinet_name)}.
          Nous ne vous demanderons jamais votre mot de passe par email.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
"""


def _echeance_whatsapp_text(*, full_name: str, echeance: dict, days_left: int, cabinet_name: str) -> str:
    if days_left < 0:
        urgency = f"⚠️ En retard de {-days_left} jour{'s' if -days_left > 1 else ''}"
    elif days_left == 0:
        urgency = "⚠️ Échéance aujourd'hui"
    else:
        urgency = f"⏰ Rappel — {days_left} jour{'s' if days_left > 1 else ''} avant échéance"
    period = echeance.get("period") or "—"
    amount = f"{int(echeance['amount']):,} FCFA".replace(",", " ") if echeance.get("amount") else "—"
    return (
        f"*{cabinet_name}*\n"
        f"{urgency}\n\n"
        f"Bonjour {full_name},\n\n"
        f"*{echeance.get('title', '')}*\n"
        f"Type : {echeance.get('type', '').upper()}\n"
        f"Date limite : {echeance.get('due_date', '')}\n"
        f"Période : {period}\n"
        f"Montant : {amount}\n\n"
        f"Merci de préparer les pièces et de nous contacter."
    )


async def notify_echeance(user: dict, echeance: dict, days_left: int) -> dict:
    """Envoie email + WA (si téléphone dispo et notifications activées).

    Destinataires =
      - le compte client si `is_active` et `can_receive_notifications`,
      - + tous les contacts client actifs autorisés (email + WA selon channels).
    Renvoie {email_id, wa_sid, sent_email, sent_wa} agrégés.
    """
    from albarka_contacts import notifiable_contacts_for  # local import: circular safe

    cabinet_name = await _get_from_name()
    if days_left < 0:
        subject = f"Échéance en retard — {echeance.get('title', 'Échéance')} (J+{-days_left})"
    elif days_left == 0:
        subject = f"Échéance aujourd'hui — {echeance.get('title', 'Échéance')}"
    else:
        subject = f"Rappel d'échéance — {echeance.get('title', 'Échéance')} (J-{days_left})"

    # Email recipients: main user account (if opted-in) + email contacts of tenant
    email_recipients: set = set()
    if user.get("is_active", True) and user.get("can_receive_notifications") is not False and user.get("email"):
        email_recipients.add(user["email"])
    for c in await notifiable_contacts_for(user["id"], channel="email"):
        if c.get("email"):
            email_recipients.add(c["email"])

    email_id = None
    if email_recipients:
        html = _echeance_email_html(
            full_name=user.get("full_name", ""), echeance=echeance,
            days_left=days_left, cabinet_name=cabinet_name,
        )
        email_id = await send_email(to=list(email_recipients), subject=subject, html=html)

    # WhatsApp: main user's phone + WA-opted contacts
    wa_phones: set = set()
    if user.get("is_active", True) and user.get("can_receive_notifications") is not False and (user.get("phone") or "").startswith("+"):
        wa_phones.add(user["phone"])
    for c in await notifiable_contacts_for(user["id"], channel="whatsapp"):
        if (c.get("phone") or "").startswith("+"):
            wa_phones.add(c["phone"])

    wa_sent = 0
    wa_last_id = None
    if wa_phones:
        wa_text = _echeance_whatsapp_text(
            full_name=user.get("full_name", ""), echeance=echeance,
            days_left=days_left, cabinet_name=cabinet_name,
        )
        for phone in wa_phones:
            result = await send_whatsapp(to_phone=phone, message=wa_text)
            if result.get("ok"):
                wa_sent += 1
                wa_last_id = result.get("message_id")

    return {
        "email_id": email_id, "wa_sid": wa_last_id,
        "sent_email": bool(email_id), "sent_wa": bool(wa_sent),
        "email_recipients": list(email_recipients), "wa_recipients": list(wa_phones),
    }


# --- Upload notification (staff-side) ------------------------------------
async def notify_upload(db, *, document: dict, tenant: dict) -> dict:
    """Notifie tous les collaborateurs actifs autorisés lorsqu'un client dépose une pièce."""
    try:
        from albarka_admin_settings import get_settings_doc
        settings = await get_settings_doc()
    except Exception:
        settings = {}
    if not settings.get("notif_upload_enabled", True):
        return {"targets": 0, "sent": 0}
    cabinet_name = (settings.get("cabinet_name") or EMAIL_FROM_NAME_DEFAULT).strip()
    # Load active staff who accept notifications.
    staff = await db.users.find(
        {
            "roles": {"$nin": ["client"]},
            "is_active": True,
            "$or": [
                {"can_receive_notifications": {"$exists": False}},
                {"can_receive_notifications": True},
            ],
        },
        {"_id": 0, "password_hash": 0},
    ).to_list(500)
    subject = f"Nouvelle pièce déposée — {tenant.get('company') or tenant.get('full_name') or ''}"
    html = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBFAF4;padding:24px 0;font-family:Arial,sans-serif;">
  <tr><td align="center">
    <table role="presentation" width="580" cellpadding="0" cellspacing="0" style="max-width:580px;background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="background:#0B1912;padding:20px 28px;color:#ffffff;">
        <div style="font-size:11px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">{escape(cabinet_name)} · Portail</div>
        <div style="font-size:20px;margin-top:4px;font-family:Georgia,serif;">Nouvelle pièce à traiter</div>
      </td></tr>
      <tr><td style="padding:24px 28px;color:#0F172A;">
        <p style="margin:0 0 12px 0;font-size:14px;">Un client vient de déposer une nouvelle pièce sur le portail :</p>
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F8FAF7;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:12px 0;">
          <tr><td style="font-size:14px;color:#0F172A;">
            <div><strong>Client :</strong> {escape(tenant.get('full_name', ''))}
              {("· " + escape(tenant.get('company'))) if tenant.get('company') else ""}</div>
            <div><strong>Fichier :</strong> {escape(document.get('original_filename', ''))}</div>
            <div><strong>Type :</strong> {escape(document.get('kind', '').replace('_', ' '))}</div>
            <div><strong>Statut :</strong> Analyse IA en cours</div>
          </td></tr>
        </table>
        <p style="margin:16px 0 0 0;font-size:12px;color:#64748B;">
          Connectez-vous à votre espace cabinet pour consulter et catégoriser la pièce.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
"""
    sent = 0
    recipients = [s["email"] for s in staff if s.get("email")]
    if recipients:
        message_id = await send_email(to=recipients, subject=subject, html=html)
        if message_id:
            sent = len(recipients)

    # WhatsApp fan-out to active staff with phone (opt-in via settings.notif_upload_wa)
    wa_sent = 0
    if settings.get("notif_upload_wa", True):
        wa_text = (
            f"*{cabinet_name}* — Portail\n"
            f"Nouvelle pièce reçue.\n"
            f"Client : {tenant.get('company') or tenant.get('full_name', '')}\n"
            f"Fichier : {document.get('original_filename', '')}\n"
            f"Type : {document.get('kind', '').replace('_', ' ')}\n"
            f"Statut : analyse en cours."
        )
        for s in staff:
            phone = (s.get("phone") or "").strip()
            if phone.startswith("+"):
                result = await send_whatsapp(to_phone=phone, message=wa_text)
                if result.get("ok"):
                    wa_sent += 1
    return {"targets": len(staff), "sent": sent, "wa_sent": wa_sent}
