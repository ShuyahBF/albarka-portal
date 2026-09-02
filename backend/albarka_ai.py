"""Extraction et synthèse IA des pièces client — via l'API Claude (Anthropic).

Un document téléversé (PDF ou photo) est envoyé à Claude (vision native pour
les PDF et images) qui répond en JSON strict : type de document, synthèse en
langage clair, champs clés extraits (montants, dates, IFU/RCCM, etc.) et
alertes éventuelles (pièce illisible, information manquante...).

Modèle : claude-opus-5 — le plus capable, adapté à un usage où la précision
d'extraction compte (données fiscales/comptables réelles de clients).
"""
from __future__ import annotations

import base64
import json
import logging
import os
from typing import Any, Dict

import anthropic

logger = logging.getLogger("albarka.ai")

MODEL_ID = "claude-opus-5"

SYSTEM_PROMPT = (
    "Tu es l'assistant d'analyse documentaire du cabinet ALBARKA, cabinet "
    "d'assistance fiscale et comptable au Burkina Faso. On te soumet une pièce "
    "téléversée par un client (facture, relevé bancaire, contrat de bail, "
    "déclaration fiscale, bulletin de paie, pièce d'identité, registre du "
    "commerce, etc.). Analyse le document et réponds UNIQUEMENT avec un objet "
    "JSON strict, sans aucun texte avant ou après ni bloc de code, au format "
    "suivant :\n"
    "{\n"
    '  "document_type": "<type précis du document, en français>",\n'
    '  "summary": "<synthèse claire en 3-6 phrases, en français, des informations utiles au cabinet>",\n'
    '  "extracted_fields": { <champs clés/valeurs pertinents extraits : montants, dates, numéros '
    "IFU/RCCM, noms de personnes ou d'entreprises, périodes concernées, etc. — adapte les clés "
    'au type de document réellement identifié> },\n'
    '  "flags": ["<alerte éventuelle : pièce illisible, information manquante, incohérence, etc.>"]\n'
    "}\n"
    "Si le document est illisible ou d'un type non reconnaissable, dis-le dans \"flags\" plutôt que "
    "d'inventer des informations."
)

SUPPORTED_IMAGE_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _client() -> anthropic.Anthropic:
    return anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


def _content_block(data: bytes, content_type: str) -> Dict[str, Any]:
    b64 = base64.standard_b64encode(data).decode("utf-8")
    if content_type == "application/pdf":
        return {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}}
    if content_type in SUPPORTED_IMAGE_TYPES:
        return {"type": "image", "source": {"type": "base64", "media_type": content_type, "data": b64}}
    raise ValueError(f"Type de fichier non pris en charge pour l'analyse IA : {content_type}")


def _parse_json_response(text: str) -> Dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end == -1:
            raise
        return json.loads(text[start:end + 1])


def _empty_result(flag: str, error: str | None = None) -> Dict[str, Any]:
    result = {
        "summary": "",
        "extracted_fields": {},
        "document_type": None,
        "flags": [flag],
        "model": MODEL_ID,
    }
    if error:
        result["error"] = error
    return result


def extract_and_synthesize(data: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    """Envoie le document à Claude pour extraction + synthèse.

    Ne lève jamais d'exception : les erreurs d'analyse sont renvoyées comme
    une entrée `flags` afin que le flux d'upload se termine toujours proprement
    (le document reste consultable même si l'analyse IA échoue).
    """
    try:
        block = _content_block(data, content_type)
    except ValueError as exc:
        return _empty_result(str(exc))

    try:
        client = _client()
        response = client.messages.create(
            model=MODEL_ID,
            max_tokens=4096,
            output_config={"effort": "high"},
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": [
                    block,
                    {"type": "text", "text": f"Nom du fichier : {filename}. Analyse ce document."},
                ],
            }],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        parsed = _parse_json_response(text)
        return {
            "summary": parsed.get("summary", ""),
            "extracted_fields": parsed.get("extracted_fields", {}),
            "document_type": parsed.get("document_type"),
            "flags": parsed.get("flags", []),
            "model": MODEL_ID,
        }
    except anthropic.APIStatusError as exc:
        logger.exception("Erreur API Claude lors de l'analyse de %s", filename)
        return _empty_result(f"Erreur d'analyse IA : {exc.message}", error=str(exc))
    except json.JSONDecodeError as exc:
        logger.exception("Réponse IA non-JSON pour %s", filename)
        return _empty_result("Réponse de l'IA illisible (format inattendu)", error=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erreur inattendue lors de l'analyse de %s", filename)
        return _empty_result(f"Erreur inattendue : {exc}", error=str(exc))
