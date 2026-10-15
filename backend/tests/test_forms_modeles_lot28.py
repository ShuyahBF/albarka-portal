"""Lot 28 — modèle de formulaire « Vérification de la paie » : définition valide pour forms_core."""
import albarka_forms_modeles as mod
from forms_core import normalize_pages, normalize_settings, value_fields


def _modele():
    return mod._modeles()["verification-paie"]


def test_le_modele_passe_la_normalisation_sans_perte():
    # Le constructeur nettoie les pages ; aucun champ ne doit disparaître (type inconnu, etc.)
    brut = _modele()["pages"]
    propre = normalize_pages(brut)
    assert sum(len(p["fields"]) for p in propre) == sum(len(p["fields"]) for p in brut)


def test_identifiants_uniques_et_fixes():
    # Les identifiants sont les clés des réponses : uniques, et conservés par la normalisation
    ids = [f["id"] for p in _modele()["pages"] for f in p["fields"]]
    assert len(ids) == len(set(ids))
    propres = [f["id"] for p in normalize_pages(_modele()["pages"]) for f in p["fields"]]
    assert propres == ids


def test_chaque_question_a_choix_propose_a_verifier():
    # Le cabinet ne doit jamais être obligé de deviner : « À vérifier » toujours disponible
    for p in normalize_pages(_modele()["pages"]):
        for f in p["fields"]:
            if f["type"] in ("radio", "checkbox") and f["id"] != "convention":
                assert mod.A_VERIFIER in f["options"], f["id"]


def test_identite_du_repondant_obligatoire():
    # Il faut savoir quelle personne du cabinet a répondu
    assert normalize_settings(_modele()["settings"])["respondent_info"] == "required"


def test_limites_du_module_respectees():
    assert len(normalize_pages(_modele()["pages"])) <= 20
    assert len(value_fields(normalize_pages(_modele()["pages"]))) <= 150


def test_valeurs_du_texte_reglementaire_citees_dans_les_questions():
    # Les écarts à vérifier sont bien posés (plafonds CNSS / exonérations / abattement / FSP)
    texte = str(_modele()["pages"])
    for attendu in ("600 000", "800 000", "75 000", "30 000", "50 000", "15 %", "1 %"):
        assert attendu in texte
