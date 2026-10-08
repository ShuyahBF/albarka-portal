"""Lot 20 — ENVOIS DE TEST du super-admin : jamais vers les clients.

Règle du propriétaire (08/10/2026) : « Quand le super-admin fait des tests d'envoi, seuls son numéro WA ou son adresse
e-mail (définis dans les Paramètres) sont utilisés. Jamais ceux des clients. »

En résumé (pour un développeur WinDev) :
  - à chaque requête authentifiée, get_current_user() note QUI agit (variable de contexte de la requête) ;
  - si c'est le compte super-admin du portail (admin@sawalismartsystems.com), TOUT envoi déclenché par cette requête
    (facture par WhatsApp ou e-mail, documents, notifications…) est redirigé vers le numéro WhatsApp de test et
    l'adresse e-mail de test saisis dans Paramètres → « Envois de test du super-admin », à défaut vers le numéro et
    l'e-mail de SON propre compte (« ce sont ses propres informations qui sont utilisées, pas celles du client ») ;
  - s'il n'y a ni l'un ni l'autre, l'envoi est REFUSÉ (message clair) : on ne retombe jamais sur le client ;
  - la redirection est faite au plus bas niveau (envoi Meta, transmission universelle SAWALI, SMTP) : aucun chemin
    d'envoi ne peut l'oublier.
"""
from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import List, Optional, Tuple

logger = logging.getLogger("albarka.envoi_test")

# Vrai pendant une requête faite par le compte super-admin du portail
_super_admin: ContextVar[bool] = ContextVar("albarka_envoi_test_super_admin", default=False)
# Ses propres coordonnées (repli quand les contacts de test des Paramètres sont vides) : (numéro +226…, e-mail)
_coordonnees: ContextVar[Tuple[str, str]] = ContextVar("albarka_envoi_test_coordonnees", default=("", ""))

MESSAGE_WA_NON_CONFIGURE = ("Envoi de test du super-admin : renseignez votre numéro WhatsApp de test dans Paramètres "
                            "(« Envois de test du super-admin ») ou sur votre compte — l'envoi n'est jamais fait vers le client.")


def marquer_acteur(user: Optional[dict]) -> None:
    """Note, pour la requête en cours, si l'acteur est le compte super-admin du portail."""
    from albarka_models import is_admin_account, whatsapp_number_of
    actif = bool(user) and is_admin_account(user)
    _super_admin.set(actif)
    # Message du propriétaire (08/10/2026) : « ce sont ses propres informations qui sont utilisées, pas celles du
    # client » — à défaut de contacts de test dans les Paramètres, ceux de SON compte.
    _coordonnees.set(((whatsapp_number_of(user) or "") if actif else "", (user.get("email") or "") if actif else ""))


def mode_test_actif() -> bool:
    """Vrai si la requête en cours est faite par le super-admin (envois redirigés)."""
    return _super_admin.get()


async def _reglages() -> Tuple[str, str]:
    """(numéro WhatsApp de test au format +226…, e-mail de test) lus dans les Paramètres ; "" si absents."""
    try:
        from albarka_admin_settings import get_settings_doc
        from albarka_models import numero_international_wa
        s = await get_settings_doc()
    except Exception:  # noqa: BLE001 — paramètres illisibles : rien de configuré (donc envoi refusé)
        return "", ""
    propre_wa, propre_email = _coordonnees.get()
    return (numero_international_wa(s.get("test_envoi_whatsapp")) or numero_international_wa(propre_wa),
            (s.get("test_envoi_email") or "").strip() or propre_email)


async def numero_effectif(numero: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """(numéro à utiliser, erreur). Hors mode test : le numéro reçu, sans erreur. En mode test : le numéro de test,
    ou (None, message) s'il n'est pas configuré — l'appelant n'envoie alors RIEN.
    Lot 22 : (None, message) aussi quand le service WhatsApp est suspendu (contrat SAWALI échu)."""
    from albarka_suspension import refus_envoi
    suspendu = await refus_envoi("wa")
    if suspendu:
        return None, suspendu
    if not mode_test_actif():
        return numero, None
    test_wa, _ = await _reglages()
    if not test_wa:
        logger.warning("Envoi WhatsApp du super-admin refusé : numéro de test absent des Paramètres")
        return None, MESSAGE_WA_NON_CONFIGURE
    if test_wa != numero:
        logger.info("Envoi de test du super-admin : WhatsApp redirigé vers le numéro de test")
    return test_wa, None


async def emails_effectifs(destinataires: List[str]) -> List[str]:
    """Destinataires e-mail à utiliser : inchangés hors mode test ; en mode test, la SEULE adresse de test
    (liste vide si elle n'est pas configurée : aucun e-mail ne part).
    Lot 22 : liste vide aussi quand le service e-mail est suspendu (contrat SAWALI échu)."""
    from albarka_suspension import refus_envoi
    if await refus_envoi("email"):
        return []
    if not mode_test_actif():
        return destinataires
    _, test_email = await _reglages()
    if not test_email:
        logger.warning("E-mail du super-admin non envoyé : adresse de test absente des Paramètres")
        return []
    return [test_email]


def echec_wa(message: str) -> dict:
    """Résultat d'échec au format de send_whatsapp() (envoi refusé avant tout appel)."""
    return {"ok": False, "message_id": None, "message_ids": [], "status": None, "error": message,
            "kind": "test_non_configure", "outside_24h_window": None}
