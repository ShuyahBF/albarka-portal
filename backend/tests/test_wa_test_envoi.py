"""Bouton « Tester l'envoi WhatsApp » : envoi direct par le WABA d'ALBARKA, diagnostic lisible en cas de refus."""
import asyncio

import albarka_admin_settings as mod
import albarka_notifications as notif
import albarka_envoi_test as envoi_test


def _lancer(payload, monkeypatch, *, wa_enabled=True, cfg=True, modele=None, texte=None):
    async def reglages():
        return {"wa_enabled": wa_enabled}

    async def config():
        return {"access_token": "t", "phone_number_id": "1", "graph_version": "v22.0"} if cfg else None

    async def effectif(numero):
        return numero, None

    async def envoi_modele(cfg_, corps, nom, to):
        return modele or {"ok": True, "message_id": "wamid.X", "kind": "success"}

    async def envoi_texte(cfg_, to, msg):
        return texte or {"ok": True, "message_id": "wamid.T", "kind": "success"}

    monkeypatch.setattr(mod, "_load_settings", reglages)
    monkeypatch.setattr(notif, "_get_wa_config", config)
    monkeypatch.setattr(notif, "_send_template_waba", envoi_modele)
    monkeypatch.setattr(notif, "_send_whatsapp_waba", envoi_texte)
    monkeypatch.setattr(envoi_test, "numero_effectif", effectif)
    return asyncio.get_event_loop().run_until_complete(mod.wa_test_send(payload, {"id": "u"}))


def test_modele_accepte(monkeypatch):
    r = _lancer({"to": "+22670000000", "mode": "modele"}, monkeypatch)
    assert r["ok"] and r["message_id"] == "wamid.X" and r["destinataire"].endswith("000")


def test_refus_meta_donne_un_conseil(monkeypatch):
    erreur = '{"error":{"message":"Invalid OAuth access token","code":190}}'
    r = _lancer({"to": "+22670000000", "mode": "texte"}, monkeypatch,
                texte={"ok": False, "error": erreur, "kind": "http_error"})
    assert not r["ok"] and r["meta"]["code"] == 190 and "jeton" in r["diagnostic"].lower()


def test_whatsapp_desactive(monkeypatch):
    r = _lancer({"to": "+22670000000"}, monkeypatch, wa_enabled=False)
    assert not r["ok"] and "désactivé" in r["diagnostic"]
