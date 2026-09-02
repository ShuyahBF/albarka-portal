"""Analyse IA des pièces via Claude Sonnet 5 (clé LLM universelle Emergent).

Pour les PDF : extraction texte via PyMuPDF puis analyse Claude (texte).
Pour les images : envoi direct à Claude via ImageContent (vision multi-modale).
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import secrets
from typing import Any, Dict

from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage

logger = logging.getLogger("albarka.ai")

MODEL_PROVIDER = "anthropic"
MODEL_ID = "claude-sonnet-5"
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

SYSTEM_PROMPT = (
    "Tu es l'assistant d'analyse documentaire du cabinet ALBARKA (cabinet "
    "d'assistance fiscale et comptable au Burkina Faso). On te soumet une pièce "
    "téléversée par un client : facture, relevé bancaire, contrat de bail, "
    "déclaration fiscale, bulletin de paie, pièce d'identité, registre du "
    "commerce, etc. Analyse le document et réponds UNIQUEMENT avec un objet "
    "JSON strict, sans aucun texte avant ou après ni bloc de code, au format :\n"
    "{\n"
    '  "document_type": "<type précis en français>",\n'
    '  "summary": "<synthèse claire en 3-6 phrases, en français>",\n'
    '  "extracted_fields": { <clés/valeurs pertinents : montants, dates, IFU/RCCM, noms, périodes...> },\n'
    '  "flags": ["<alerte éventuelle : pièce illisible, information manquante, incohérence...>"]\n'
    "}\n"
    "Si le document est illisible ou d'un type non reconnaissable, dis-le dans \"flags\" plutôt que d'inventer."
)

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}


def _extract_pdf_text(data: bytes, max_chars: int = 20000) -> str:
    """Best-effort PDF text extraction with PyMuPDF; empty on failure."""
    try:
        import fitz  # PyMuPDF

        buf = []
        with fitz.open(stream=data, filetype="pdf") as doc:
            for page in doc:
                buf.append(page.get_text())
                if sum(len(b) for b in buf) > max_chars:
                    break
        return "\n".join(buf)[:max_chars].strip()
    except Exception:
        logger.exception("Échec extraction texte PDF")
        return ""


def _empty(flag: str) -> Dict[str, Any]:
    return {
        "summary": "",
        "extracted_fields": {},
        "document_type": None,
        "flags": [flag],
        "model": MODEL_ID,
    }


def _parse_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
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


async def _analyze_text(text: str, filename: str) -> Dict[str, Any]:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"albarka-doc-{secrets.token_urlsafe(8)}",
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_ID)
    prompt = (
        f"Nom du fichier : {filename}\n\n"
        f"Contenu extrait du document :\n---\n{text}\n---\n\n"
        "Analyse ce document et réponds uniquement en JSON strict."
    )
    reply = await chat.send_message(UserMessage(text=prompt))
    reply_text = getattr(reply, "text", None) or str(reply)
    return _parse_json(reply_text)


async def _analyze_image(data: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    chat = LlmChat(
        api_key=EMERGENT_LLM_KEY,
        session_id=f"albarka-img-{secrets.token_urlsafe(8)}",
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, MODEL_ID)
    b64 = base64.standard_b64encode(data).decode("utf-8")
    image = ImageContent(image_base64=b64)
    reply = await chat.send_message(UserMessage(
        text=f"Nom du fichier : {filename}. Analyse cette image comme pièce comptable.",
        file_contents=[image],
    ))
    reply_text = getattr(reply, "text", None) or str(reply)
    return _parse_json(reply_text)


async def analyze_document(data: bytes, content_type: str, filename: str) -> Dict[str, Any]:
    """Router principal ; ne lève jamais — retourne toujours un dict."""
    if not EMERGENT_LLM_KEY:
        return _empty("Clé LLM non configurée")

    try:
        if content_type == "application/pdf":
            text = _extract_pdf_text(data)
            if not text:
                return _empty("PDF illisible (extraction texte vide)")
            parsed = await _analyze_text(text, filename)
        elif content_type in IMAGE_MIMES:
            parsed = await _analyze_image(data, content_type, filename)
        else:
            # Best-effort for text-like files
            try:
                text = data.decode("utf-8", errors="ignore")[:20000]
            except Exception:
                return _empty(f"Type non pris en charge pour l'analyse : {content_type}")
            if not text.strip():
                return _empty("Contenu vide")
            parsed = await _analyze_text(text, filename)

        return {
            "summary": parsed.get("summary", ""),
            "extracted_fields": parsed.get("extracted_fields", {}) or {},
            "document_type": parsed.get("document_type"),
            "flags": parsed.get("flags", []) or [],
            "model": MODEL_ID,
        }
    except json.JSONDecodeError:
        logger.exception("Réponse IA non-JSON")
        return _empty("Réponse de l'IA au format inattendu")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Erreur analyse IA")
        result = _empty(f"Erreur d'analyse : {exc}")
        result["error"] = str(exc)
        return result
