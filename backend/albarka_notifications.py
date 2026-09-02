"""Notifications ALBARKA — email (Resend Emergent-managed) + WhatsApp (Twilio, optionnel).

L'email part toujours de l'adresse gérée par la plateforme, avec `EMAIL_FROM_NAME
= "Cabinet ALBARKA"`. Le WhatsApp est **guardé** : si `TWILIO_ACCOUNT_SID`,
`TWILIO_AUTH_TOKEN` et `TWILIO_WA_FROM` ne sont pas définis, l'envoi WA est
silencieusement ignoré (email seul).
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
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "Cabinet ALBARKA")
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


async def send_email(*, to: str, subject: str, html: str, reply_to: Optional[str] = None) -> Optional[str]:
    """Non-blocking send via the Emergent-managed Resend proxy."""
    if not EMAIL_KEY:
        logger.info("EMERGENT_EMAIL_KEY absent — envoi email ignoré (dev/pilote).")
        return None
    _assert_safe_email(subject, html)
    payload = {"to": [to], "subject": subject, "html": html, "from_name": EMAIL_FROM_NAME}
    if reply_to or EMAIL_REPLY_TO:
        payload["contact_email"] = reply_to or EMAIL_REPLY_TO
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{EMAIL_BASE_URL}/api/v1/email/send",
                headers={"X-Email-Key": EMAIL_KEY},
                json=payload,
            )
        resp.raise_for_status()
        return resp.json().get("id")
    except Exception:
        logger.exception("Échec envoi email à %s", to)
        return None


# --- WhatsApp via Twilio (guardé) ---------------------------------------
def _twilio_configured() -> bool:
    return all(os.environ.get(k) for k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WA_FROM"))


async def send_whatsapp(*, to_phone: str, message: str) -> Optional[str]:
    """Envoie un WhatsApp via Twilio; ignore silencieusement si Twilio n'est pas
    configuré (log INFO). `to_phone` doit être au format international +226..."""
    if not _twilio_configured():
        logger.info("Twilio non configuré — WA vers %s ignoré.", to_phone)
        return None
    if not to_phone or not to_phone.startswith("+"):
        logger.warning("Téléphone WA invalide (attendu +226…) : %r", to_phone)
        return None
    sid = os.environ["TWILIO_ACCOUNT_SID"]
    token = os.environ["TWILIO_AUTH_TOKEN"]
    wa_from = os.environ["TWILIO_WA_FROM"]
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    data = {
        "From": f"whatsapp:{wa_from}" if not wa_from.startswith("whatsapp:") else wa_from,
        "To": f"whatsapp:{to_phone}",
        "Body": message[:1500],
    }
    try:
        async with httpx.AsyncClient(timeout=30, auth=(sid, token)) as client:
            resp = await client.post(url, data=data)
        resp.raise_for_status()
        return resp.json().get("sid")
    except Exception:
        logger.exception("Échec envoi WA à %s", to_phone)
        return None


# --- Templates emails ----------------------------------------------------
def _echeance_email_html(*, full_name: str, echeance: dict, days_left: int) -> str:
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
        <div style="font-size:12px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">Cabinet Albarka</div>
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
          Ce message est envoyé par le Cabinet ALBARKA — assistance fiscale et comptable au Burkina Faso.
          Nous ne vous demanderons jamais de mot de passe par email.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
"""


def _echeance_whatsapp_text(*, full_name: str, echeance: dict, days_left: int) -> str:
    if days_left < 0:
        urgency = f"⚠️ En retard de {-days_left} jour{'s' if -days_left > 1 else ''}"
    elif days_left == 0:
        urgency = "⚠️ Échéance aujourd'hui"
    else:
        urgency = f"⏰ Rappel — {days_left} jour{'s' if days_left > 1 else ''} avant échéance"
    period = echeance.get("period") or "—"
    amount = f"{int(echeance['amount']):,} FCFA".replace(",", " ") if echeance.get("amount") else "—"
    return (
        f"*Cabinet ALBARKA*\n"
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
    """Envoie email + WA (si téléphone dispo) pour une échéance."""
    if days_left < 0:
        subject = f"Échéance en retard — {echeance.get('title', 'Échéance')} (J+{-days_left})"
    elif days_left == 0:
        subject = f"Échéance aujourd'hui — {echeance.get('title', 'Échéance')}"
    else:
        subject = f"Rappel d'échéance — {echeance.get('title', 'Échéance')} (J-{days_left})"
    html = _echeance_email_html(
        full_name=user.get("full_name", ""), echeance=echeance, days_left=days_left,
    )
    email_id = await send_email(to=user["email"], subject=subject, html=html)
    wa_sid = None
    phone = user.get("phone")
    if phone:
        msg = _echeance_whatsapp_text(
            full_name=user.get("full_name", ""), echeance=echeance, days_left=days_left,
        )
        wa_sid = await send_whatsapp(to_phone=phone, message=msg)
    return {"email_id": email_id, "wa_sid": wa_sid, "sent_email": bool(email_id), "sent_wa": bool(wa_sid)}
