"""Jeton de vérification du webhook Meta : masqué à la lecture (jamais renvoyé en clair)."""
import albarka_admin_settings as mod


def test_jeton_de_verification_est_un_champ_sensible():
    # Le jeton est un secret : il doit être dans la liste des champs masqués
    assert "wa_webhook_verify_token" in mod.SENSITIVE_FIELDS


def test_lecture_masque_le_jeton():
    # Un jeton présent est remplacé par ******** dans la réponse des paramètres
    masque = mod._mask({"wa_webhook_verify_token": "secret-abc", "wa_phone_number_id": "123"})
    assert masque["wa_webhook_verify_token"] == "********"
    assert masque["wa_phone_number_id"] == "123"
