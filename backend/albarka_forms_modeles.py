"""Modèles de formulaires prêts à l'emploi (Albarka).

Le constructeur de formulaires (forms_core) existe déjà : création, lien public de
remplissage SANS connexion, suivi, réponses, export CSV. Ce module n'ajoute qu'une
chose : des MODÈLES (titre, pages, champs, réglages) que le personnel crée en un clic
depuis « Formulaires » (voir AdminForms.jsx) au lieu de saisir les questions à la main.

Modèle actuel : « Vérification de la paie — Burkina Faso » (15/10/2026), à faire remplir
par le cabinet : il confirme, texte officiel à l'appui, les règles appliquées par le
logiciel de paie. AUCUN calcul de paie n'est modifié ici : on ne fait que collecter des
réponses (règle GRH_BURKINA.md : un écart se signale, le propriétaire arbitre).

Routes (préfixe /api, rôle « formulaires » comme le reste du module) :
  GET /forms-modeles          liste des modèles
  GET /forms-modeles/{code}   définition complète, à envoyer ensuite à POST /forms
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException

from albarka_auth import require_roles
from albarka_models import FORMS_ROLES

router = APIRouter(prefix="/forms-modeles", tags=["Formulaires — modèles"])

# Réponse « je ne sais pas » proposée à chaque question à choix : le cabinet n'a jamais
# à deviner (consigne : écrire « à vérifier », ne rien inventer).
A_VERIFIER = "À vérifier"


def _choix(fid: str, label: str, actuel: str, options: List[str], *, multiple: bool = False,
           texte_ref: bool = True) -> List[Dict[str, Any]]:
    """Une question = rappel de la situation actuelle (titre/texte) + choix + précisions
    + référence du texte + date d'effet. Les identifiants sont fixes (clés des réponses)."""
    champs: List[Dict[str, Any]] = [{
        "id": f"{fid}_titre", "type": "section", "label": label,
        "help": f"Situation actuelle dans le logiciel : {actuel}" if actuel else "",
    }, {
        "id": fid, "type": "checkbox" if multiple else "radio", "label": "Votre réponse",
        "required": True, "options": options + [A_VERIFIER],
    }, {
        "id": f"{fid}_precision", "type": "text", "label": "Précisions ou autre valeur (si besoin)",
        "width": "full",
    }]
    if texte_ref:
        champs += [{
            "id": f"{fid}_ref", "type": "text", "width": "half",
            "label": "Référence du texte (loi, décret, article)",
            "help": "Exemple : loi de finances 2023, article … Ne rien inventer : laisser vide si inconnu.",
        }, {
            "id": f"{fid}_date", "type": "date", "width": "half", "label": "En vigueur depuis le",
        }]
    return champs


# Pages du modèle « vérification de la paie » (regroupées par thème)
def _pages_verification_paie() -> List[Dict[str, Any]]:
    return [
        {"id": "p_identite", "title": "Identification", "fields": [
            {"id": "intro", "type": "section", "label": "Vérification des règles de paie",
             "help": "Pour chaque question : choisissez une réponse, indiquez la référence du texte (loi, décret, "
                     "article) et la date d'effet. En cas de doute, choisissez « À vérifier » : n'inventez rien. "
                     "Merci de joindre une copie des textes cités à la dernière page."},
        ]},
        {"id": "p_cnss", "title": "CNSS", "fields":
            _choix("cnss_plafond", "1. CNSS — plafond mensuel de l'assiette",
                   "plafond de 800 000 F (cotisation salariale maximale 44 000 F). Le document de cours indique 600 000 F.",
                   ["600 000 F", "800 000 F", "Autre (préciser)"])
            + _choix("cnss_8pct", "2. CNSS — plafond « 8 % » de la CNSS déductible de l'impôt",
                     "limitée à 8 % de (salaire de base + ancienneté + prime exceptionnelle).",
                     ["8 % du salaire de base seul", "8 % du salaire de base + ancienneté",
                      "8 % du salaire de base + ancienneté + prime exceptionnelle", "Autre (préciser)"])
            + _choix("cnss_assiette", "3. CNSS — sommes qui entrent dans l'assiette",
                     "prime exceptionnelle et avantage en nature EXCLUS de la base CNSS ; sursalaire inclus.",
                     ["Prime exceptionnelle incluse", "Prime exceptionnelle exclue", "Avantage en nature inclus",
                      "Avantage en nature exclu", "Sursalaire inclus", "Sursalaire exclu"], multiple=True)
            + _choix("cnss_employeur", "4. CNSS employeur 16 %",
                     "7 % prestations familiales + 3,5 % risques professionnels + 5,5 % vieillesse.",
                     ["Conforme", "Différent (préciser)"])},
        {"id": "p_exo", "title": "Exonérations de l'IUTS", "fields":
            _choix("exo_logement", "5. Indemnité de logement",
                   "20 % du brut, plafond 75 000 F (le cours : plafond 50 000 F).",
                   ["Plafond 50 000 F", "Plafond 75 000 F", "Autre (préciser taux et plafond)"])
            + _choix("exo_transport", "6. Indemnité de transport",
                     "5 %, plafond 30 000 F (le cours : plafond 20 000 F).",
                     ["Plafond 20 000 F", "Plafond 30 000 F", "Autre (préciser taux et plafond)"])
            + _choix("exo_fonction", "7. Indemnité de fonction",
                     "5 %, plafond 50 000 F (le cours : plafond 30 000 F).",
                     ["Plafond 30 000 F", "Plafond 50 000 F", "Autre (préciser taux et plafond)"])
            + _choix("exo_rattachees", "8. Indemnités rattachées à la « fonction » (plafond commun)",
                     "sujétion, représentation, caisse et responsabilité partagent le plafond de la fonction.",
                     ["Oui, toutes", "Seulement certaines (préciser)", "Non, chacune a son propre plafond"])
            + _choix("exo_transport_nature", "9. Prime / indemnité de transport",
                     "le cours la cite à la fois comme remboursement de frais (hors salaire) et comme indemnité "
                     "exonérée avec plafond.",
                     ["Indemnité plafonnée (exonération partielle)", "Remboursement de frais sur pièces (hors salaire)",
                      "Les deux, selon le cas (préciser)"])},
        {"id": "p_iuts", "title": "Abattement, barème et taxes patronales", "fields":
            _choix("abattement_taux", "10. Abattement forfaitaire (frais professionnels) de l'IUTS — taux",
                   "cadre 20 %, non-cadre 25 % (le cours : 15 % du salaire de base).",
                   ["15 % pour tous", "20 % cadre / 25 % non-cadre", "Autre (préciser)"])
            + _choix("abattement_assiette", "11. Abattement forfaitaire — assiette",
                     "salaire de base + ancienneté + avantage en nature.",
                     ["Salaire de base seul", "Salaire de base + ancienneté",
                      "Salaire de base + ancienneté + avantage en nature"])
            + _choix("bareme", "12. Barème IUTS et charges de famille",
                     "barème à 7 tranches (0 / 12,1 / 13,9 / 15,7 / 18,4 / 21,7 / 25 %) et abattement famille de 8 % "
                     "à 20 %. Date du cours : 01/10/2013.",
                     ["Inchangé, toujours en vigueur", "Modifié depuis (joindre le nouveau barème)"])
            + _choix("tpa", "13. Taxe patronale d'apprentissage (TPA) 3 %",
                     "calculée sur le brut, avantage en nature inclus (le cours : brut moins avantage en nature).",
                     ["Avantage en nature inclus", "Avantage en nature exclu"])},
        {"id": "p_fsp", "title": "FSP — prélèvement pour effort de paix", "fields":
            [{"id": "fsp_info", "type": "section", "label": "Déjà confirmé : 1 % du salaire net, obligatoire depuis 2023",
              "help": "Le logiciel applique 1 % du salaire net (après impôt et cotisations, avantage en nature retiré), "
                      "avant avances et prêts. Il reste à confirmer les détails ci-dessous."}]
            + _choix("fsp_net", "14. FSP — définition du « net » sur lequel il se calcule",
                     "net = brut − CNSS − IUTS net − avantage en nature (non versé en argent).",
                     ["Conforme", "Autre définition (préciser)"])
            + _choix("fsp_ordre", "15. FSP — ordre sur le bulletin",
                     "retenu après le calcul du net, avant les avances et prêts.",
                     ["Conforme", "Retenu après les avances (préciser)"], texte_ref=False)
            + _choix("fsp_arrondi", "16. FSP — arrondi et exclusions",
                     "arrondi au franc supérieur, aucun salarié exclu.",
                     ["Conforme", "Arrondi différent (préciser)", "Salariés non concernés (préciser)"])},
        {"id": "p_primes", "title": "Primes et autres éléments", "fields":
            _choix("sursalaire", "17. Sursalaire",
                   "traité comme une indemnité imposable et soumise à la CNSS.",
                   ["Conforme", "Autre traitement (préciser)"])
            + _choix("primes_officine", "18. Primes des officines (pharmacies) : hivernale et « para »",
                     "traitées comme primes imposables.",
                     ["Imposables et soumises à la CNSS", "Imposables, hors CNSS", "Autre (préciser)"])
            + _choix("heures_sup", "19. Heures supplémentaires",
                     "majorations du cours : 15 % (41e–48e h), 35 % (49e h et plus), 50 % nuit, 60 % dimanche/férié "
                     "jour, 120 % dimanche/férié nuit.",
                     ["Conformes", "Différentes (préciser)"])},
        {"id": "p_bulletin", "title": "Bulletin de paie et conclusion", "fields":
            _choix("num_employeur", "20. Numéro d'employeur",
                   "affiché « N° employeur » sur le bulletin.",
                   ["C'est le numéro CNSS de l'employeur", "Autre numéro (préciser)"], texte_ref=False)
            + _choix("mentions", "21. Mentions obligatoires du bulletin",
                     "le cours demande : situation matrimoniale, n° CNSS du salarié, signature et cachet de "
                     "l'employeur, mention « à conserver sans limitation de durée ».",
                     ["Toutes obligatoires", "Certaines facultatives (préciser)", "Autres mentions à ajouter (préciser)"],
                     texte_ref=False)
            + [{"id": "convention", "type": "radio", "label": "Une convention collective modifie-t-elle ces règles "
                "pour les clients du cabinet ?", "required": True, "options": ["Non", "Oui (préciser ci-dessous)", A_VERIFIER]},
               {"id": "convention_precision", "type": "text", "label": "Convention collective concernée"},
               {"id": "autres_taxes", "type": "textarea", "label": "Autres retenues ou taxes sur la paie à prévoir ?"},
               {"id": "textes_joints", "type": "file", "label": "Copie des textes cités (facultatif)",
                "accept": ".pdf,image/*"}]},
    ]


# Catalogue des modèles : code → définition (envoyée telle quelle à POST /forms)
def _modeles() -> Dict[str, Dict[str, Any]]:
    return {
        "verification-paie": {
            "title": "Vérification de la paie — Burkina Faso",
            "description": "À remplir par le cabinet : confirmer, textes officiels à l'appui, les règles de paie "
                           "appliquées par le logiciel (CNSS, IUTS, exonérations, FSP, primes).",
            "pages": _pages_verification_paie(),
            "settings": {
                "accepting_responses": True,
                "respondent_info": "required",      # nom et e-mail de la personne qui répond
                "public_multiple": True,            # plusieurs personnes du cabinet peuvent répondre
                "allow_edit": False,
                "confirmation_message": "Merci. Vos réponses ont été enregistrées ; elles serviront à vérifier les "
                                        "règles de paie avant toute modification du logiciel.",
                "notify_emails": [],
            },
        },
    }


@router.get("")
async def liste_modeles(user: dict = Depends(require_roles(FORMS_ROLES))):
    """Modèles disponibles (code, titre, description, nombre de questions)."""
    return {"modeles": [
        {"code": code, "title": m["title"], "description": m["description"],
         "questions": sum(1 for p in m["pages"] for f in p["fields"] if f["type"] not in ("section",))}
        for code, m in _modeles().items()]}


@router.get("/{code}")
async def lire_modele(code: str, user: dict = Depends(require_roles(FORMS_ROLES))):
    """Définition complète d'un modèle ; le portail l'envoie ensuite à POST /forms."""
    modele = _modeles().get(code)
    if not modele:
        raise HTTPException(status_code=404, detail="Modèle introuvable.")
    return modele
