"""Un destinataire WhatsApp doit d'abord exister dans nos répertoires de
contacts (annuaire `contacts` ou compte client) avant qu'on puisse lui
écrire — voir albarka_wa_inbox.send_reply.

Ne teste QUE le chemin de refus (numéro inconnu) : le chemin accepté
déclenche un envoi WhatsApp réel via Meta, qu'on ne veut jamais provoquer
depuis une suite de tests automatisée."""
from conftest import API, CREDENTIALS, make_session

# Improbable qu'un vrai contact utilise ce numéro — évite un faux positif si
# jamais un contact avec ce numéro existait déjà en base.
UNKNOWN_PHONE = "+22600009999"


class TestWhatsAppContactRequired:
    def test_reply_to_unknown_number_is_rejected(self):
        s, _ = make_session(*CREDENTIALS["superviseur"])

        convs = s.get(f"{API}/whatsapp/conversations", timeout=60).json()
        assert not any(c["phone"] == UNKNOWN_PHONE for c in convs), (
            f"{UNKNOWN_PHONE} existe déjà dans les conversations — choisir un autre numéro de test"
        )

        r = s.post(
            f"{API}/whatsapp/conversations/{UNKNOWN_PHONE}/reply",
            json={"body": "Test automatisé — ne doit jamais partir"},
            timeout=60,
        )
        assert r.status_code == 404, r.text[:300]
        assert "contact" in r.json()["detail"].lower()

        # Rien n'a dû être inséré (pas de conversation fantôme créée par le refus).
        convs_after = s.get(f"{API}/whatsapp/conversations", timeout=60).json()
        assert not any(c["phone"] == UNKNOWN_PHONE for c in convs_after)
