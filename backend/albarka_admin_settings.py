"""Paramètres administrateur (settings globaux) — WABA config, notifications, etc.

Document unique en base : `settings` avec `_id="global"` (compatible avec le
pattern du repo d'origine). Seul le Superviseur peut lire/écrire les
paramètres (SETTINGS_ROLES).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import re
from albarka_models import SETTINGS_ROLES
from albarka_auth import get_current_user, require_roles
from db import db

logger = logging.getLogger("albarka.admin_settings")

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

router = APIRouter(prefix="/admin", tags=["Admin"])

# Paramètres : superviseur uniquement (SETTINGS_ROLES, albarka_models.py)
_ADMIN_ROLES = SETTINGS_ROLES

# Champs sensibles : masqués sur lecture (******** = présent).
SENSITIVE_FIELDS = {"wa_access_token", "wa_webhook_verify_token", "recaptcha_secret_key", "pawapay_api_token_sandbox", "pawapay_api_token_production"}

# Valeurs par défaut.
DEFAULT_SETTINGS: Dict[str, Any] = {
    "cabinet_name": "Cabinet ALBARKA",
    "cabinet_email": "contact@albarka-bf.com",
    "cabinet_phone": "",
    "cabinet_address": "Ouagadougou, Burkina Faso",
    # Email — expéditeur & domaine
    "email_from_address": "",   # ex noreply@albarka-bf.com — nécessite domaine vérifié Resend
    "email_reply_to": "",
    # WhatsApp Business Cloud API (Meta Graph)
    "wa_enabled": False,
    "wa_access_token": "",
    "wa_phone_number_id": "",
    "wa_business_account_id": "",
    "wa_graph_version": "v22.0",
    # Notifications
    "notif_reminder_days": [7, 1],
    "notif_overdue": True,
    "notif_upload_enabled": True,
    "notif_upload_wa": True,   # notifier aussi les collaborateurs par WA
    # Auto WA after signing (Phase B — Feature 3)
    "auto_wa_after_sign_enabled": False,
    "auto_wa_after_sign_days": 1,
    # Report numbering
    "report_prefix": "RAP",
    # WhatsApp click-to-chat public (Partie 0 — prospects, avant WABA validé)
    "whatsapp_contact_number": "",
    # Lot 20 : envois de test du super-admin — TOUT envoi qu'il déclenche part vers ces contacts, jamais vers un client
    "test_envoi_whatsapp": "",
    "test_envoi_email": "",
    "whatsapp_contact_message": "Bonjour, je souhaite en savoir plus sur vos services comptables.",
    # Chat interne
    "voice_notes_enabled": True,
    # WhatsApp inbox (Partie 2.D)
    "wa_webhook_verify_token": "",
    "wa_voice_transcribe_enabled": True,
    # RGPD — masquage des numéros de téléphone client pour les collaborateurs
    # non-privilégiés (voir albarka_clients.py:_apply_rgpd_masking). Activer
    # ou désactiver ce réglage est réservé au rôle "administrateur" seul —
    # même le superviseur ne peut pas le changer, voir update_settings ci-dessous.
    "rgpd_masking_enabled": True,
    # Filigrane + QR sur les documents envoyés par WhatsApp (voir albarka_wa_stamp.py).
    # Les deux s'activent indépendamment. wa_watermark_text accepte {cabinet} et {date}.
    "wa_watermark_enabled": False,
    "wa_watermark_text": "{cabinet} — {date}",
    "wa_qr_enabled": False,
    "wa_qr_content": "",
    # reCAPTCHA v2 sur la page de connexion (voir albarka_recaptcha.py).
    # Désactivé par défaut : n'a d'effet qu'une fois une paire clé site/clé
    # secrète Google renseignée.
    "recaptcha_enabled": False,
    "recaptcha_site_key": "",
    "recaptcha_secret_key": "",
    # PawaPay (mobile money — Orange/Moov/Telecel) : liens de paiement du
    # module Paiements, réservé au rôle "caissier" (voir albarka_payments.py).
    # Porté depuis ShuyahBF/Emergent — deux jetons distincts sandbox/prod,
    # le jeu actif dépend de pawapay_environment.
    "pawapay_enabled": False,
    "pawapay_environment": "sandbox",  # "sandbox" | "production"
    "pawapay_api_token_sandbox": "",
    "pawapay_api_token_production": "",
    "pawapay_country": "BFA",  # ISO-3
    "pawapay_callback_secret": "",
    # Espace client — notification WhatsApp au client quand le cabinet dépose
    # ou met à disposition un document (voir albarka_client_space.py).
    #  - client_docs_templates : texte du message par catégorie
    #    ("default" + facture, proforma, recu, rapport…) ; vide = texte par défaut.
    #    Variables : {client} {entreprise} {cabinet} {nombre} {liste} {titre}
    #    {categorie} {reference} {montant} {lien}.
    #  - modèle Meta (hors fenêtre de 24 h) : nom, langue et variables
    #    envoyées dans l'ordre pour {{1}}, {{2}}… (liste séparée par des virgules).
    #  - repli e-mail si WhatsApp est impossible.
    "client_docs_notify_enabled": True,
    "client_docs_templates": {},
    "client_docs_wa_template_name": "",
    "client_docs_wa_template_lang": "fr",
    "client_docs_wa_template_params": "client,nombre,lien",
    "client_docs_email_fallback": True,
    # Notification push (navigateur / téléphone du client, voir albarka_push.py)
    "client_docs_push_enabled": True,
    # Déconnexion automatique après N minutes sans activité (clavier, souris,
    # défilement, toucher) — clients et collaborateurs. 0 = désactivée.
    # Jamais pendant une tâche en cours (envoi, enregistrement…). Repris de Sawali.
    "auto_logout_minutes": 30,
    # Accès du personnel (albarka_access.py). Désactivée par défaut : le
    # superviseur enregistre d'abord les appareils / IP du cabinet, puis active.
    "staff_whitelist_enabled": False,
    "staff_ip_whitelist": [],            # adresses ou plages CIDR (ex. 41.207.12.0/24)
    # Adresses e-mail autorisées, en plus d'admin, à créer des jetons d'accès
    # temporaires. Modifiable par admin (admin@sawalismartsystems.com) seulement.
    "access_token_issuer_emails": [],
}


async def _load_settings() -> Dict[str, Any]:
    doc = await db.settings.find_one({"_id": "global"})
    if not doc:
        doc = {"_id": "global", **DEFAULT_SETTINGS,
               "created_at": datetime.now(timezone.utc).isoformat(),
               "updated_at": datetime.now(timezone.utc).isoformat()}
        await db.settings.insert_one(doc)
    # Ensure every default key is present (forward-compat).
    changed = False
    for k, v in DEFAULT_SETTINGS.items():
        if k not in doc:
            doc[k] = v
            changed = True
    if changed:
        await db.settings.update_one(
            {"_id": "global"}, {"$set": {k: doc[k] for k in DEFAULT_SETTINGS}},
        )
    doc.pop("_id", None)
    return doc


async def get_settings_doc() -> Dict[str, Any]:
    """Used internally by other modules (no masking)."""
    return await _load_settings()


def _mask(doc: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(doc)
    for k in SENSITIVE_FIELDS:
        if out.get(k):
            out[k] = "********"
    return out


class SettingsUpdate(BaseModel):
    # Lot 20 : contacts de test du super-admin (voir albarka_envoi_test.py)
    test_envoi_whatsapp: Optional[str] = Field(None, max_length=40)
    test_envoi_email: Optional[str] = Field(None, max_length=200)
    # Cabinet
    cabinet_name: Optional[str] = None
    cabinet_email: Optional[str] = None
    cabinet_phone: Optional[str] = None
    cabinet_address: Optional[str] = None
    # Email
    email_from_address: Optional[str] = None
    email_reply_to: Optional[str] = None
    # WA
    wa_enabled: Optional[bool] = None
    wa_access_token: Optional[str] = None
    wa_phone_number_id: Optional[str] = None
    wa_business_account_id: Optional[str] = None
    wa_graph_version: Optional[str] = None
    # Notifs
    notif_reminder_days: Optional[list[int]] = None
    notif_overdue: Optional[bool] = None
    notif_upload_enabled: Optional[bool] = None
    notif_upload_wa: Optional[bool] = None
    # Auto WA after signing (Phase B — Feature 3)
    auto_wa_after_sign_enabled: Optional[bool] = None
    auto_wa_after_sign_days: Optional[int] = None
    # Reports
    report_prefix: Optional[str] = Field(None, max_length=10)
    # Partie 0 — bouton wa.me public
    whatsapp_contact_number: Optional[str] = Field(None, max_length=20)
    whatsapp_contact_message: Optional[str] = Field(None, max_length=500)
    # Partie 1.A — chat voice notes
    voice_notes_enabled: Optional[bool] = None
    # Partie 2.D — webhook WhatsApp entrant
    wa_webhook_verify_token: Optional[str] = Field(None, max_length=200)
    wa_voice_transcribe_enabled: Optional[bool] = None
    # RGPD — administrateur uniquement, voir update_settings
    rgpd_masking_enabled: Optional[bool] = None
    # Filigrane/QR WhatsApp
    wa_watermark_enabled: Optional[bool] = None
    wa_watermark_text: Optional[str] = Field(None, max_length=120)
    wa_qr_enabled: Optional[bool] = None
    wa_qr_content: Optional[str] = Field(None, max_length=500)
    # reCAPTCHA v2 (page de connexion)
    recaptcha_enabled: Optional[bool] = None
    recaptcha_site_key: Optional[str] = Field(None, max_length=200)
    recaptcha_secret_key: Optional[str] = Field(None, max_length=200)
    # PawaPay (module Paiements)
    pawapay_enabled: Optional[bool] = None
    pawapay_environment: Optional[str] = None
    pawapay_api_token_sandbox: Optional[str] = Field(None, max_length=500)
    pawapay_api_token_production: Optional[str] = Field(None, max_length=500)
    pawapay_country: Optional[str] = Field(None, max_length=3)
    pawapay_callback_secret: Optional[str] = Field(None, max_length=200)
    # Espace client — modèles de notification (voir DEFAULT_SETTINGS)
    client_docs_notify_enabled: Optional[bool] = None
    client_docs_templates: Optional[Dict[str, str]] = None
    client_docs_wa_template_name: Optional[str] = Field(None, max_length=120)
    client_docs_wa_template_lang: Optional[str] = Field(None, max_length=10)
    client_docs_wa_template_params: Optional[str] = Field(None, max_length=200)
    client_docs_email_fallback: Optional[bool] = None
    client_docs_push_enabled: Optional[bool] = None
    # Déconnexion automatique (minutes d'inactivité, 0 = désactivée, 120 max)
    auto_logout_minutes: Optional[int] = Field(None, ge=0, le=120)
    # Accès du personnel
    staff_whitelist_enabled: Optional[bool] = None
    staff_ip_whitelist: Optional[list[str]] = None
    access_token_issuer_emails: Optional[list[str]] = None


@router.get("/settings")
async def get_settings(user: dict = Depends(require_roles(_ADMIN_ROLES))):
    return _mask(await _load_settings())


@router.put("/settings")
async def update_settings(payload: SettingsUpdate, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    changes = {k: v for k, v in payload.model_dump(exclude_none=True).items()}
    # RGPD : les Paramètres étant réservés au Superviseur (SETTINGS_ROLES), il
    # est le seul à pouvoir activer/désactiver le masquage des numéros.
    # Never persist the masked sentinel back.
    for k in SENSITIVE_FIELDS:
        if changes.get(k) == "********":
            changes.pop(k, None)
    # Validate email address fields; empty string clears the setting.
    # Lot 20 : contacts de test du super-admin (numéro normalisé +226…, e-mail vérifié)
    if "test_envoi_whatsapp" in changes:
        from albarka_models import numero_international_wa
        brut = (changes["test_envoi_whatsapp"] or "").strip()
        changes["test_envoi_whatsapp"] = numero_international_wa(brut) if brut else ""
        if brut and not changes["test_envoi_whatsapp"]:
            raise HTTPException(status_code=400, detail="Numéro WhatsApp de test invalide (ex. +226 70 00 00 00)")
    for k in ("email_from_address", "email_reply_to", "test_envoi_email"):
        if k in changes:
            val = (changes[k] or "").strip()
            if val and not _EMAIL_RE.match(val):
                raise HTTPException(status_code=400, detail=f"{k} : adresse email invalide")
            changes[k] = val
    # Modèles de notification de l'espace client : clés connues uniquement,
    # 1000 caractères max ; un texte vide revient au texte par défaut.
    if "client_docs_templates" in changes:
        from albarka_client_space import TEMPLATE_KEYS
        tpl = changes["client_docs_templates"]
        unknown = set(tpl) - set(TEMPLATE_KEYS)
        if unknown:
            raise HTTPException(status_code=400, detail=f"Modèle inconnu : {', '.join(sorted(unknown))}")
        changes["client_docs_templates"] = {k: (v or "").strip()[:1000] for k, v in tpl.items() if (v or "").strip()}
    if "client_docs_wa_template_params" in changes:
        from albarka_client_space import TEMPLATE_VARIABLES
        params = [p.strip() for p in (changes["client_docs_wa_template_params"] or "").split(",") if p.strip()]
        bad = [p for p in params if p not in TEMPLATE_VARIABLES]
        if bad:
            raise HTTPException(status_code=400, detail=f"Variable inconnue pour le modèle Meta : {', '.join(bad)}")
        changes["client_docs_wa_template_params"] = ",".join(params)
    # Accès du personnel : IP validées ; émetteurs de jetons = admin seul
    if "staff_ip_whitelist" in changes:
        from albarka_access import normalize_ip_list
        changes["staff_ip_whitelist"] = normalize_ip_list(changes["staff_ip_whitelist"])
    if "access_token_issuer_emails" in changes:
        from albarka_models import is_admin_account
        if not is_admin_account(user):
            raise HTTPException(status_code=403, detail="Seul admin peut désigner qui crée les accès temporaires")
        emails = [e.strip().lower() for e in changes["access_token_issuer_emails"] if (e or "").strip()]
        bad = [e for e in emails if not _EMAIL_RE.match(e)]
        if bad:
            raise HTTPException(status_code=400, detail=f"Adresse e-mail invalide : {bad[0]}")
        changes["access_token_issuer_emails"] = list(dict.fromkeys(emails))
    if not changes:
        return _mask(await _load_settings())
    await _load_settings()
    changes["updated_at"] = datetime.now(timezone.utc).isoformat()
    changes["updated_by"] = user["id"]
    await db.settings.update_one({"_id": "global"}, {"$set": changes})
    return _mask(await _load_settings())


# Explications en français des refus les plus fréquents de Meta (code d'erreur → conseil)
_CONSEILS_META = {
    190: "Le jeton d'accès est invalide ou expiré : générez un jeton permanent (utilisateur système) et enregistrez-le.",
    100: "Phone Number ID incorrect (ou non rattaché à ce jeton) : vérifiez-le dans Meta → API WhatsApp.",
    10: "Autorisation manquante : le jeton doit avoir whatsapp_business_messaging et whatsapp_business_management.",
    131030: "Numéro destinataire non autorisé : tant que l'app Meta est en mode développement, ajoutez-le dans la liste des destinataires de test (API WhatsApp, étape 1).",
    131047: "Fenêtre de 24 h fermée : le destinataire doit vous écrire d'abord, ou utilisez le test « Modèle ».",
    131026: "Message non délivrable : ce numéro n'a pas WhatsApp, ou n'a pas accepté les conditions.",
    132001: "Modèle introuvable ou non approuvé pour cette langue.",
    133010: "Numéro d'envoi non enregistré : terminez l'enregistrement du numéro dans Meta.",
    131056: "Trop de messages vers ce numéro en peu de temps : réessayez plus tard.",
}


def _lire_erreur_meta(brut: Optional[str]) -> Dict[str, Any]:
    """Extrait (code, message, conseil) du texte d'erreur renvoyé par Meta (JSON) ; jamais d'exception."""
    import json
    try:
        err = (json.loads(brut or "{}") or {}).get("error") or {}
    except Exception:  # noqa: BLE001 — texte non JSON : renvoyé tel quel
        return {"code": None, "message": (brut or "")[:300], "conseil": None}
    code = err.get("code")
    return {"code": code, "message": (err.get("message") or "")[:300], "conseil": _CONSEILS_META.get(code)}


@router.post("/settings/wa/test")
async def wa_test_send(
    payload: Dict[str, str],  # {"to": "+226…", "mode": "modele"|"texte", "message": "…" (texte libre, facultatif)}
    user: dict = Depends(require_roles(_ADMIN_ROLES)),
):
    """Envoi de TEST par le compte WhatsApp Business d'ALBARKA lui-même (jamais par le repli SAWALI : on teste
    la configuration Meta saisie ici). Modes : « modele » (modèle Meta `hello_world`, part même hors fenêtre de 24 h)
    ou « texte » (texte libre, accepté seulement si le destinataire a écrit depuis moins de 24 h).
    Renvoie toujours un diagnostic lisible : résultat, destinataire réel, code d'erreur Meta et conseil."""
    from albarka_envoi_test import numero_effectif
    from albarka_notifications import _get_wa_config, _send_template_waba, _send_whatsapp_waba
    to = (payload.get("to") or "").strip()
    mode = (payload.get("mode") or "modele").strip()
    if not to.startswith("+"):
        raise HTTPException(status_code=400, detail="Numéro attendu au format international (+226…)")
    if mode not in ("modele", "texte"):
        raise HTTPException(status_code=400, detail="Mode attendu : « modele » ou « texte »")
    settings = await _load_settings()
    if not settings.get("wa_enabled"):
        return {"ok": False, "message_id": None, "diagnostic": "WhatsApp désactivé : activez l'interrupteur de la carte WhatsApp Business Cloud API, puis Enregistrer."}
    cfg = await _get_wa_config()
    if not cfg:
        return {"ok": False, "message_id": None, "diagnostic": "Jeton d'accès ou Phone Number ID manquant : renseignez-les puis Enregistrer."}
    # Destinataire réel : le compte super-admin est redirigé vers son numéro de test (règle du lot 20)
    reel, refus = await numero_effectif(to)
    if refus:
        return {"ok": False, "message_id": None, "diagnostic": refus}
    if mode == "texte":
        msg = payload.get("message") or "Test — Cabinet ALBARKA. Configuration WhatsApp opérationnelle."
        resultat = await _send_whatsapp_waba(cfg, to, msg)
    else:
        corps = {"messaging_product": "whatsapp", "recipient_type": "individual", "to": (reel or to).lstrip("+"),
                 "type": "template", "template": {"name": "hello_world", "language": {"code": "en_US"}}}
        resultat = await _send_template_waba(cfg, corps, "hello_world", to)
    sortie = {"ok": bool(resultat.get("ok")), "message_id": resultat.get("message_id"), "kind": resultat.get("kind"),
              "mode": mode, "destinataire": f"{(reel or to)[:4]}…{(reel or to)[-3:]}",
              "redirige": bool(reel and reel != to)}
    if resultat.get("ok"):
        sortie["diagnostic"] = "Message accepté par Meta. S'il n'arrive pas, regardez l'état du webhook (statuts de livraison)."
        return sortie
    erreur = _lire_erreur_meta(resultat.get("error"))
    sortie["meta"] = erreur
    sortie["diagnostic"] = erreur["conseil"] or erreur["message"] or resultat.get("error") or "Meta a rejeté l'envoi — consulter les logs serveur"
    return sortie
