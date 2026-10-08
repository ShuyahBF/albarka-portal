"""Lot 20 — Facture par WhatsApp universel (numéro non international) et envois de test du super-admin.

Couvre :
  - « 70 11 22 33 » devient « +22670112233 » avant tout envoi (cause du refus 400 du 08/10/2026) ;
  - sans WABA (Meta) mais avec la transmission universelle SAWALI, le PDF part bien par WhatsApp ;
  - super-admin : tout envoi part vers SON numéro / e-mail de test (Paramètres), jamais vers le client ;
    sans numéro de test, l'envoi est refusé et rien ne part ;
  - un autre utilisateur n'est pas concerné.
Réutilise les simulations du lot 13.9 (MongoDB simulé, httpx simulé, transmission universelle configurée).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_transmission_wa_v3_lot13_9 import _regler_waba, _run, base, liluvine, reseau  # noqa: E402,F401

import albarka_envoi_test as et  # noqa: E402
import albarka_notifications as notif  # noqa: E402
from albarka_models import numero_international_wa, whatsapp_number_of  # noqa: E402

ADMIN = {"id": "sa", "email": "admin@sawalismartsystems.com", "roles": ["superviseur"]}
DG = {"id": "dg", "email": "dg@albarka.bf", "roles": ["dg"]}


def _destinataire(appel) -> str:
    """Numéro « to » d'un envoi fait à SAWALI (transmission universelle)."""
    return json.loads(appel.content.decode())["to"]


def test_numero_rendu_international():
    assert numero_international_wa("70 11 22 33") == "+22670112233"
    assert numero_international_wa("00226 70-11-22-33") == "+22670112233"
    assert whatsapp_number_of({"phone": "70 11 22 33"}) == "+22670112233"
    assert whatsapp_number_of({"whatsapp_number": "76 12 34 56", "phone": "70 11 22 33"}) == "+22676123456"


def test_facture_part_par_whatsapp_universel_sans_waba(base, liluvine, reseau):
    async def scenario():
        await _regler_waba(base, False)
        et.marquer_acteur(DG)
        return await notif.send_whatsapp_fichier(to_phone=whatsapp_number_of({"phone": "70 11 22 33"}),
                                                 data=b"%PDF-1.4 facture", filename="facture.pdf",
                                                 content_type="application/pdf", caption="Facture F2026/015")
    r = _run(scenario())
    assert r["ok"] is True and r["canal"] == "liluvine"
    assert _destinataire(reseau.appels[-1]) == "+22670112233"


def test_super_admin_sans_numero_de_test_rien_ne_part(base, liluvine, reseau):
    async def scenario():
        await _regler_waba(base, False)
        et.marquer_acteur(ADMIN)
        return await notif.send_whatsapp_fichier(to_phone="+22670112233", data=b"%PDF", filename="f.pdf",
                                                 content_type="application/pdf", caption="Facture")
    r = _run(scenario())
    assert r["ok"] is False and "numéro WhatsApp de test" in (r.get("error") or r.get("erreur") or "")
    assert reseau.appels == []


def test_super_admin_envoi_redirige_vers_son_numero_de_test(base, liluvine, reseau):
    async def scenario():
        await _regler_waba(base, False)
        await base.settings.update_one({"_id": "global"}, {"$set": {"test_envoi_whatsapp": "+22677000001",
                                                                     "test_envoi_email": "moi@exemple.com"}}, upsert=True)
        et.marquer_acteur(ADMIN)
        r = await notif.send_whatsapp_fichier(to_phone="+22670112233", data=b"%PDF", filename="f.pdf",
                                              content_type="application/pdf", caption="Facture")
        emails = await et.emails_effectifs(["client@exemple.bf"])
        return r, emails
    r, emails = _run(scenario())
    assert r["ok"] is True and _destinataire(reseau.appels[-1]) == "+22677000001"
    assert emails == ["moi@exemple.com"]


def test_super_admin_avec_waba_aussi_redirige(base, liluvine, reseau):
    async def scenario():
        await _regler_waba(base, True)
        await base.settings.update_one({"_id": "global"}, {"$set": {"test_envoi_whatsapp": "77000001"}}, upsert=True)
        et.marquer_acteur(ADMIN)
        return await notif.send_whatsapp(to_phone="+22670112233", message="Bonjour")
    _run(scenario())
    corps = json.loads(reseau.appels_meta[-1].content.decode())
    assert corps["to"] == "22677000001"


def test_super_admin_sans_reglage_utilise_ses_propres_coordonnees(base, liluvine, reseau):
    async def scenario():
        await _regler_waba(base, False)
        et.marquer_acteur({**ADMIN, "phone": "71 22 33 44"})
        r = await notif.send_whatsapp_fichier(to_phone="+22670112233", data=b"%PDF", filename="f.pdf",
                                              content_type="application/pdf", caption="Facture")
        return r, await et.emails_effectifs(["client@exemple.bf"])
    r, emails = _run(scenario())
    assert r["ok"] is True and _destinataire(reseau.appels[-1]) == "+22671223344"
    assert emails == ["admin@sawalismartsystems.com"]


def test_autre_utilisateur_non_concerne(base, liluvine, reseau):
    async def scenario():
        et.marquer_acteur(DG)
        return et.mode_test_actif(), await et.emails_effectifs(["client@exemple.bf"])
    assert _run(scenario()) == (False, ["client@exemple.bf"])


def test_numero_de_lot():
    import lot
    assert float(lot.LOT.split(".")[0]) >= 20   # lots suivants : un numéro par déploiement
