# albarka_noms.py — NOM de famille + Prénoms : règle d'écriture et assemblage du « Nom complet ».
#
# Règle du propriétaire (14/11/2026) : dans la fiche d'un contact, d'un client ou d'un membre du
# personnel, le « Nom complet » est remplacé par DEUX champs :
#   - NOM de famille : TOUT en majuscules ;
#   - Prénoms        : première lettre de chaque mot en majuscule, le reste en minuscules.
# Le « Nom complet » (champ `full_name`, utilisé partout ailleurs : listes, e-mails, journaux…)
# reste enregistré : c'est la CONCATÉNATION « NOM Prénoms ». Les utilisateurs ne respectent pas
# toujours les conventions d'orthographe : c'est le serveur qui corrige à l'enregistrement.
from __future__ import annotations

import re
from typing import Any, Optional


def formater_nom(nom: Optional[str]) -> str:
    """NOM de famille : espaces nettoyés, tout en MAJUSCULES (« de la Fontaine » -> « DE LA FONTAINE »)."""
    return re.sub(r"\s+", " ", (nom or "").strip()).upper()


def _majuscule_mot(mot: str) -> str:
    """Un mot de prénom : première lettre en majuscule, le reste en minuscules ; gère « Jean-Paul » et « D'Arc »."""
    if not mot:
        return mot
    # Les séparateurs « - » et « ' » donnent chacun une nouvelle majuscule (Jean-Paul, N'Dour).
    parties = re.split(r"([-'’])", mot.lower())
    return "".join(p[:1].upper() + p[1:] if p not in ("-", "'", "’") else p for p in parties)


def formater_prenoms(prenoms: Optional[str]) -> str:
    """Prénoms : première lettre de CHAQUE mot en majuscule, le reste en minuscules."""
    return " ".join(_majuscule_mot(m) for m in re.sub(r"\s+", " ", (prenoms or "").strip()).split(" ") if m)


def assembler(nom: Optional[str], prenoms: Optional[str]) -> str:
    """Nom complet = NOM + espace + Prénoms (l'un ou l'autre peut manquer)."""
    return " ".join(x for x in (formater_nom(nom), formater_prenoms(prenoms)) if x)


def separer(nom_complet: Optional[str]) -> tuple[str, str]:
    """Découpe un ancien « Nom complet » en (NOM, Prénoms) : les mots TOUT en majuscules du début forment le
    NOM ; sinon, le premier mot est le NOM. Sert à pré-remplir la fiche des comptes créés avant cette règle."""
    mots = re.sub(r"\s+", " ", (nom_complet or "").strip()).split(" ")
    mots = [m for m in mots if m]
    if not mots:
        return "", ""
    i = 0
    while i < len(mots) and mots[i].upper() == mots[i] and any(c.isalpha() for c in mots[i]):
        i += 1
    if i == 0:
        i = 1
    return formater_nom(" ".join(mots[:i])), formater_prenoms(" ".join(mots[i:]))


def normaliser_entree(data: Any) -> Any:
    """Pré-validateur Pydantic (mode « before ») des formulaires de création / modification.
    Si `nom` ou `prenoms` est fourni : on corrige l'orthographe des deux champs ET on recalcule
    `full_name` (concaténation). Sinon rien ne change (anciens clients de l'API)."""
    if isinstance(data, dict) and (data.get("nom") is not None or data.get("prenoms") is not None):
        data = dict(data)
        data["nom"] = formater_nom(data.get("nom"))
        data["prenoms"] = formater_prenoms(data.get("prenoms"))
        data["full_name"] = assembler(data["nom"], data["prenoms"])
    return data


def completer_document(doc: dict) -> dict:
    """Ajoute `nom` / `prenoms` à un document lu en base s'ils manquent (comptes anciens), sans l'écrire."""
    if doc is not None and "full_name" in doc and not (doc.get("nom") or doc.get("prenoms")):
        doc["nom"], doc["prenoms"] = separer(doc.get("full_name"))
    return doc
