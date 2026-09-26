"""Formulaires ALBARKA — branchement du module commun forms_core.

Toute la logique (constructeur, validation, envois, suivi, statistiques,
export) vit dans `forms_core/` (copie du module commun, NE PAS MODIFIER ici).
Ce fichier ne contient que ce qui est propre à Albarka :
  - qui peut gérer les formulaires : le rôle "formulaires" (FORMS_ROLES),
    plus le passe-droit "superviseur" habituel de require_roles() ;
  - qui peut recevoir un formulaire : les comptes clients actifs ;
  - comment on les prévient : e-mail (send_email) et WhatsApp (send_whatsapp),
    en respectant leur choix « recevoir les notifications » ;
  - où sont rangés les fichiers joints : le stockage Albarka (R2 ou local).

Routes exposées (préfixe /api) :
  /forms/...            gestion (rôle formulaires)
  /public/forms/{jeton} remplissage sans connexion (client invité ou non-client)
  /me/forms             « Mes formulaires » dans l'espace client
"""
from __future__ import annotations

import logging
from html import escape
from typing import Any, Dict, List, Optional

from fastapi import Request

from albarka_auth import get_current_user, require_roles
from albarka_models import FORMS_ROLES, client_modules, whatsapp_number_of
from albarka_notifications import _get_from_name, send_email, send_whatsapp
from albarka_phase_c import _log_platform_event
import albarka_storage
from db import db
from forms_core import FormsAdapter, create_routers, ensure_indexes

logger = logging.getLogger("albarka.forms")

# Adresse du portail utilisée quand la requête n'indique pas son origine
# (même repli que les liens de paiement, voir albarka_payments.py).
DEFAULT_BASE_URL = "https://albarka-bf.com"

# Traduction des échecs WhatsApp techniques en messages compréhensibles par
# le personnel (affichés dans le suivi des envois).
_WA_ERRORS = {
    "not_configured": "WhatsApp n'est pas configuré dans les paramètres.",
    "invalid_phone": "Numéro WhatsApp absent ou invalide (format +226…).",
    "silent_drop": "WhatsApp n'a pas remis le message.",
}


def _accepts_notifications(user: Dict[str, Any]) -> bool:
    """Le client a-t-il accepté de recevoir des messages du cabinet ?
    (case « recevoir les notifications » de sa fiche, vraie par défaut)."""
    return user.get("is_active", True) and user.get("can_receive_notifications") is not False


def _invitation_email_html(*, cabinet: str, name: str, form: Dict[str, Any], url: str,
                           message: str, reminder: bool) -> str:
    """Corps de l'e-mail d'invitation, dans le style des autres e-mails Albarka.
    Contraintes de sécurité des e-mails (albarka_notifications) respectées :
    lien https uniquement, texte du bouton sans nom de domaine, aucun champ
    de saisie dans l'e-mail (on remplit sur le portail)."""
    title = escape(form.get("title") or "Formulaire")
    intro = ("Petit rappel : nous attendons encore votre réponse au formulaire ci-dessous."
             if reminder else "Nous vous invitons à remplir le formulaire ci-dessous.")
    # Message personnalisé saisi par le collaborateur (facultatif), sauts de ligne conservés
    custom = (f'<p style="margin:0 0 16px 0;white-space:pre-line;">{escape(message)}</p>' if message else "")
    desc = escape(form.get("description") or "")
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#FBFAF4;padding:24px 0;font-family:Arial,sans-serif;">
  <tr><td align="center">
    <table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;background:#ffffff;border-radius:12px;overflow:hidden;">
      <tr><td style="background:#0B1912;padding:24px 32px;color:#ffffff;">
        <div style="font-size:12px;letter-spacing:2px;color:#E5A24B;text-transform:uppercase;">{escape(cabinet)}</div>
        <div style="font-size:22px;margin-top:4px;font-family:Georgia,serif;">{"Rappel — " if reminder else ""}Formulaire à remplir</div>
      </td></tr>
      <tr><td style="padding:32px;color:#0F172A;">
        <p style="margin:0 0 12px 0;">Bonjour {escape(name or "")},</p>
        <p style="margin:0 0 16px 0;">{intro}</p>
        {custom}
        <div style="background:#F8FAF7;border:1px solid #E2E8F0;border-radius:8px;padding:16px;margin:16px 0;">
          <div style="font-size:18px;font-weight:600;color:#0F6B4A;">{title}</div>
          {f'<div style="margin-top:6px;font-size:14px;color:#475569;">{desc}</div>' if desc else ""}
        </div>
        <p style="margin:24px 0;text-align:center;">
          <a href="{escape(url)}" style="background:#0F6B4A;color:#ffffff;text-decoration:none;padding:12px 24px;border-radius:8px;font-weight:600;display:inline-block;">Remplir le formulaire</a>
        </p>
        <p style="margin:24px 0 0 0;font-size:13px;color:#64748B;">
          Ce lien vous est personnel : merci de ne pas le transférer.
          Aucune connexion ni mot de passe n'est demandé pour répondre.
        </p>
      </td></tr>
    </table>
  </td></tr>
</table>
"""


def _invitation_whatsapp_text(*, cabinet: str, name: str, form: Dict[str, Any], url: str,
                              message: str, reminder: bool) -> str:
    """Texte WhatsApp de l'invitation (le lien est cliquable dans WhatsApp)."""
    head = "⏰ Rappel — formulaire à remplir" if reminder else "📝 Formulaire à remplir"
    parts = [f"*{cabinet}*", head, "", f"Bonjour {name or ''},", ""]
    if message:
        parts += [message, ""]
    parts += [f"*{form.get('title') or 'Formulaire'}*", f"Pour répondre : {url}", "",
              "Ce lien vous est personnel, merci de ne pas le transférer."]
    return "\n".join(parts)


class AlbarkaFormsAdapter(FormsAdapter):
    """Branchement Albarka du module commun forms_core."""

    code_prefix = "FORM-ALBARKA"  # numérotation FORM-ALBARKA-0001, 0002…
    manager_dependency = staticmethod(require_roles(FORMS_ROLES))
    user_dependency = staticmethod(get_current_user)

    def __init__(self, database):
        self.db = database

    # ------------------------------------------------------------ identités
    def user_label(self, user: Dict[str, Any]) -> str:
        return user.get("full_name") or user.get("email") or "—"

    def recipient_id_of(self, user: Dict[str, Any]) -> Optional[str]:
        """Un client retrouve ses formulaires sous son propre identifiant
        (le locataire = le compte client, voir tenant_id_of)."""
        if "client" not in (user.get("roles") or []):
            return None
        # Module « Mes formulaires » fermé pour ce client : liste vide
        # (ses liens personnels déjà reçus restent utilisables).
        return user["id"] if "formulaires" in client_modules(user) else None

    @staticmethod
    def _as_recipient(u: Dict[str, Any]) -> Dict[str, Any]:
        """Fiche client → destinataire tel que l'attend le module commun."""
        ok = _accepts_notifications(u)
        wa = whatsapp_number_of(u) or ""
        return {
            "id": u["id"], "name": u.get("full_name") or u.get("email") or "Client",
            "company": u.get("company") or "", "email": u.get("email") or "",
            "can_email": bool(ok and u.get("email")),
            "can_whatsapp": bool(ok and wa.startswith("+")),
        }

    async def list_recipients(self, user: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Clients actifs proposés dans la liste d'envoi (triés par nom)."""
        cur = self.db.users.find({"roles": "client", "is_active": {"$ne": False}},
                                 {"_id": 0, "password_hash": 0}).sort("full_name", 1)
        return [self._as_recipient(u) for u in await cur.to_list(5000)]

    async def get_recipient(self, recipient_id: str) -> Optional[Dict[str, Any]]:
        """Fiche complète d'un client (avec son numéro WhatsApp) pour l'envoi."""
        u = await self.db.users.find_one({"id": recipient_id, "roles": "client"}, {"_id": 0, "password_hash": 0})
        if not u:
            return None
        return {**self._as_recipient(u), "_user": u}

    # ------------------------------------------------------------ envois
    async def send_invitation(self, *, recipient: Dict[str, Any], form: Dict[str, Any], url: str,
                              channels: List[str], message: str, reminder: bool) -> Dict[str, Dict[str, Any]]:
        """Envoie le lien de remplissage par e-mail et/ou WhatsApp.
        Chaque canal renvoie {ok, error} ; l'échec d'un canal n'empêche pas l'autre."""
        user = recipient.get("_user") or {}
        cabinet = await _get_from_name()
        results: Dict[str, Dict[str, Any]] = {}
        args = dict(cabinet=cabinet, name=recipient.get("name"), form=form, url=url, message=message, reminder=reminder)

        if "email" in channels:
            if not recipient.get("can_email"):
                results["email"] = {"ok": False, "error": "Pas d'e-mail ou notifications refusées par le client."}
            else:
                subject = f"{'Rappel — ' if reminder else ''}{form.get('title') or 'Formulaire'} — {cabinet}"
                try:
                    sent_id = await send_email(to=recipient["email"], subject=subject,
                                               html=_invitation_email_html(**args))
                    results["email"] = {"ok": bool(sent_id), "error": None if sent_id else "E-mail non envoyé (service indisponible ou non configuré)."}
                except ValueError as exc:  # garde-fous de sécurité des e-mails
                    results["email"] = {"ok": False, "error": f"E-mail refusé par les règles de sécurité : {exc}"[:200]}

        if "whatsapp" in channels:
            if not recipient.get("can_whatsapp"):
                results["whatsapp"] = {"ok": False, "error": "Pas de numéro WhatsApp ou notifications refusées par le client."}
            else:
                r = await send_whatsapp(to_phone=whatsapp_number_of(user), message=_invitation_whatsapp_text(**args))
                if r.get("ok"):
                    results["whatsapp"] = {"ok": True, "error": None}
                elif r.get("outside_24h_window"):
                    # Règle Meta : message libre impossible si le client n'a pas écrit depuis 24 h
                    results["whatsapp"] = {"ok": False, "error": "Hors fenêtre de 24 h WhatsApp : le client doit d'abord vous écrire. Utilisez l'e-mail."}
                else:
                    results["whatsapp"] = {"ok": False, "error": _WA_ERRORS.get(r.get("kind"), r.get("error") or "Échec WhatsApp.")}
        return results

    async def notify_submission(self, *, form: Dict[str, Any], submission: Dict[str, Any], emails: List[str]) -> None:
        """Prévient les adresses choisies dans les réglages qu'une réponse est arrivée."""
        cabinet = await _get_from_name()
        who = escape(submission.get("respondent_name") or submission.get("respondent_email") or "Un répondant")
        title = escape(form.get("title") or "Formulaire")
        html = (f'<div style="font-family:Arial,sans-serif;color:#0F172A;">'
                f'<p>Nouvelle réponse au formulaire <strong>{title}</strong> ({escape(form.get("number") or "")}).</p>'
                f'<p>Répondant : {who}</p>'
                f'<p style="color:#64748B;font-size:13px;">Consultez le détail dans le portail {escape(cabinet)}, menu Formulaires.</p></div>')
        try:
            await send_email(to=emails, subject=f"Nouvelle réponse — {form.get('title') or 'Formulaire'}", html=html)
        except ValueError:
            logger.exception("[forms] e-mail de notification refusé par les garde-fous")

    # ------------------------------------------------------------ fichiers
    async def store_file(self, *, data: bytes, filename: str, content_type: str, meta: Dict[str, Any]) -> Dict[str, Any]:
        """Range un fichier joint (ou une signature) dans le stockage Albarka.
        Rangé sous le dossier du client invité, ou « forms-public » pour un non-client."""
        ext = (filename.rsplit(".", 1)[-1] if "." in filename else "bin").lower()[:8] or "bin"
        rec = await albarka_storage.save_and_log(
            self.db, data=data, kind="form_upload", tenant_id=meta.get("recipient_id") or "forms-public",
            ext=ext, content_type=content_type, original_filename=filename, user_id=meta.get("recipient_id"))
        return {"file_id": rec["id"]}

    async def _stored(self, file_id: str) -> Optional[Dict[str, Any]]:
        return await self.db.stored_objects.find_one({"id": file_id, "kind": "form_upload", "is_deleted": {"$ne": True}}, {"_id": 0})

    async def file_url(self, file_id: str) -> Optional[str]:
        """Lien temporaire (R2) ; None en stockage local → le module lit le fichier."""
        rec = await self._stored(file_id)
        return await albarka_storage.presigned_url(rec["storage_path"]) if rec else None

    async def read_file(self, file_id: str):
        rec = await self._stored(file_id)
        if not rec:
            return None
        data, ct = await albarka_storage.get_object(rec["storage_path"])
        return data, rec.get("content_type") or ct

    # ------------------------------------------------------------ divers
    def public_base_url(self, request: Request) -> str:
        """Adresse du portail placée dans les liens envoyés. Uniquement en
        https : les garde-fous e-mail refusent tout lien http (poste local,
        aperçu non sécurisé…) — dans ce cas on utilise l'adresse officielle."""
        origin = (request.headers.get("origin") or "").rstrip("/")
        return origin if origin.startswith("https://") else DEFAULT_BASE_URL

    async def log_event(self, *, user: Optional[Dict[str, Any]], action: str, form: Dict[str, Any], meta: Dict[str, Any]) -> None:
        """Trace dans le journal de la plateforme (actions du personnel uniquement)."""
        if user:
            await _log_platform_event(user=user, action=action, entity_type="form",
                                      entity_id=form.get("id"), meta={"number": form.get("number"), **(meta or {})})


adapter = AlbarkaFormsAdapter(db)
_routers = create_routers(adapter)
staff_router = _routers["staff"]    # /forms
public_router = _routers["public"]  # /public/forms
portal_router = _routers["portal"]  # /me/forms


async def ensure_forms_indexes() -> None:
    """Index Mongo du module (appelé au démarrage, voir server.py)."""
    await ensure_indexes(adapter)
