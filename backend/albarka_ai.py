"""Analyse IA des pièces via Claude (clé LLM universelle Emergent).

Le cabinet choisit le modèle (Opus 5 / Sonnet 5 / Haiku 4.5) et chaque
analyse renvoie, en plus de l'extraction, son coût réel :
  - les tokens réellement consommés sont lus dans la réponse du proxy
    (`LlmChat.send_message_with_tools()` d'emergentintegrations 0.2.0 renvoie
    un `ChatResponse` avec `usage`), jamais estimés d'après la longueur du texte ;
  - coût = tokens × tarif officiel du modèle × taux USD→FCFA (USD_TO_XOF_RATE).

Préparation de la pièce (optimisation OCR) :
  - PDF avec une vraie couche texte (généré par un logiciel) : on envoie le
    texte extrait par PyMuPDF — le moins cher ;
  - PDF scanné (pas ou peu de texte) : chaque page est convertie en image et
    envoyée en vision — avant ce lot, ces pièces échouaient en « PDF illisible » ;
  - photo : redressée (EXIF) et réduite à 1568 px sur le grand côté, taille
    à laquelle Claude la réduit de toute façon (requête plus légère, même lisibilité).
"""
from __future__ import annotations

import base64
import io
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from emergentintegrations.llm.chat import ImageContent, LlmChat, UserMessage

logger = logging.getLogger("albarka.ai")

MODEL_PROVIDER = "anthropic"


# ---------------------------------------------------------------------
# Catalogue des modèles proposés au cabinet (liste déroulante).
# Tarifs officiels Anthropic en USD pour 1 million de tokens (2026-09).
# Ajouter un modèle = ajouter une entrée ici, rien d'autre à modifier.
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class OcrModel:
    id: str                       # identifiant exact transmis au proxy Emergent
    label: str                    # libellé affiché dans la liste déroulante
    price_input_per_mtok: float   # USD / 1M tokens en entrée (images/texte + consigne)
    price_output_per_mtok: float  # USD / 1M tokens en sortie (JSON + réflexion)
    note: str                     # conseil d'usage affiché sous la liste

    def public(self) -> Dict[str, Any]:
        """Version sérialisable renvoyée au frontend."""
        return {
            "id": self.id, "label": self.label, "note": self.note,
            "price_input_per_mtok": self.price_input_per_mtok,
            "price_output_per_mtok": self.price_output_per_mtok,
        }


OCR_MODELS: Dict[str, OcrModel] = {
    "claude-opus-5": OcrModel(
        id="claude-opus-5",
        label="Claude Opus 5 — le plus précis (manuscrit, tampons)",
        price_input_per_mtok=5.00, price_output_per_mtok=25.00,
        note="Meilleure précision, notamment sur l'écriture manuscrite. Coût le plus élevé.",
    ),
    "claude-sonnet-5": OcrModel(
        id="claude-sonnet-5",
        label="Claude Sonnet 5 — bon compromis coût/précision",
        price_input_per_mtok=2.00, price_output_per_mtok=10.00,
        note="Modèle utilisé jusqu'ici par le site. Environ 2,5x moins cher qu'Opus 5.",
    ),
    # Identifiant daté : c'est celui déjà utilisé et éprouvé en production via
    # le proxy Emergent sur la plateforme Sawali.
    "claude-haiku-4-5-20251001": OcrModel(
        id="claude-haiku-4-5-20251001",
        label="Claude Haiku 4.5 — le moins cher (imprimé net, gros volume)",
        price_input_per_mtok=1.00, price_output_per_mtok=5.00,
        note="Le plus économique. À réserver aux pièces imprimées nettes, sans manuscrit.",
    ),
}

# Modèle par défaut : dépôts des clients eux-mêmes et pré-remplissage KYC
# (albarka_myaccount.py). Inchangé par rapport à avant ce lot (Sonnet 5),
# surchargeable sans toucher au code via ALBARKA_OCR_DEFAULT_MODEL.
DEFAULT_MODEL_ID = os.environ.get("ALBARKA_OCR_DEFAULT_MODEL", "claude-sonnet-5")
if DEFAULT_MODEL_ID not in OCR_MODELS:
    DEFAULT_MODEL_ID = "claude-sonnet-5"
MODEL_ID = DEFAULT_MODEL_ID  # compatibilité avec l'ancien nom de constante

# Taux USD → FCFA (XOF). Le FCFA est arrimé à l'EURO (655,957 XOF/EUR), pas
# au dollar : ce taux suit l'EUR/USD et doit être ajusté périodiquement.
DEFAULT_USD_TO_XOF = 600.0

MAX_IMAGE_EDGE_PX = 1568       # au-delà, Claude réduit lui-même l'image : inutile d'envoyer plus
PDF_RENDER_DPI = 150           # suffisant pour lire un scan A4
MAX_PDF_PAGES = 10             # pages suivantes non analysées (une alerte le signale)
MIN_TEXT_CHARS_PER_PAGE = 200  # en dessous : PDF considéré comme scanné → envoi en images
MAX_TEXT_CHARS = 20000
JPEG_QUALITY = 85

IMAGE_MIMES = {"image/png", "image/jpeg", "image/webp", "image/gif"}

SYSTEM_PROMPT = (
    "Tu es l'assistant d'analyse documentaire du cabinet ALBARKA (cabinet "
    "d'assistance fiscale et comptable au Burkina Faso). On te soumet une pièce "
    "téléversée par un client : facture, reçu, relevé bancaire, contrat de bail, "
    "déclaration fiscale, bulletin de paie, pièce d'identité, registre du "
    "commerce, etc., souvent scannée ou photographiée, parfois manuscrite, avec "
    "tampon, cachet ou filigrane. Si le document a plusieurs pages, elles te sont "
    "transmises dans l'ordre. Analyse le document et réponds UNIQUEMENT avec un "
    "objet JSON strict, sans aucun texte avant ou après ni bloc de code, au format :\n"
    "{\n"
    '  "document_type": "<type précis en français>",\n'
    '  "summary": "<synthèse claire en 3-6 phrases, en français>",\n'
    '  "extracted_fields": { <clés/valeurs pertinents : numéro, date, émetteur, IFU, RCCM, client, '
    "lignes, sous-total, taxes, montant total, période... — montants en nombres sans séparateur "
    'de milliers, dates au format AAAA-MM-JJ> },\n'
    '  "flags": ["<alerte éventuelle : pièce illisible, information manquante, incohérence...>"],\n'
    '  "confidence": <nombre entre 0 et 1 : ta confiance globale dans l\'extraction>,\n'
    '  "uncertain_fields": ["<clés de extracted_fields dont tu n\'es pas sûr (écriture peu lisible, tampon...)>"]\n'
    "}\n"
    "Si une information est illisible, mets null plutôt que de la deviner et cite la clé dans "
    "\"uncertain_fields\". Si le document est illisible ou d'un type non reconnaissable, dis-le "
    "dans \"flags\" plutôt que d'inventer."
)


# ---------------------------------------------------------------------
# Helpers publics (utilisés aussi par albarka_documents.py)
# ---------------------------------------------------------------------
def get_model(model_id: Optional[str]) -> Optional[OcrModel]:
    """Modèle du catalogue, ou None si l'identifiant est inconnu."""
    return OCR_MODELS.get(model_id or "")


def usd_to_xof_rate() -> float:
    """Taux USD→XOF lu à chaque appel (modifiable sans toucher au code)."""
    try:
        rate = float(os.environ.get("USD_TO_XOF_RATE", DEFAULT_USD_TO_XOF))
        return rate if rate > 0 else DEFAULT_USD_TO_XOF
    except ValueError:
        return DEFAULT_USD_TO_XOF


def compute_cost(model: OcrModel, input_tokens: int, output_tokens: int) -> Tuple[float, float]:
    """Coût réel d'un appel : (USD, FCFA), à partir des tokens effectivement consommés."""
    cost_usd = (input_tokens * model.price_input_per_mtok + output_tokens * model.price_output_per_mtok) / 1_000_000
    return round(cost_usd, 6), round(cost_usd * usd_to_xof_rate(), 2)


# ---------------------------------------------------------------------
# Préparation de la pièce
# ---------------------------------------------------------------------
def _shrink_image(data: bytes) -> bytes:
    """Redresse (EXIF), réduit à MAX_IMAGE_EDGE_PX et ré-encode en JPEG."""
    from PIL import Image, ImageOps

    with Image.open(io.BytesIO(data)) as img:
        img = ImageOps.exif_transpose(img)          # photos de téléphone prises « de côté »
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")                # JPEG : ni transparence ni palette
        img.thumbnail((MAX_IMAGE_EDGE_PX, MAX_IMAGE_EDGE_PX))  # proportions gardées, jamais agrandie
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=JPEG_QUALITY, optimize=True)
        return out.getvalue()


def prepare_pdf(data: bytes) -> Tuple[str, List[bytes], List[str]]:
    """PDF → (texte, [], notes) si la couche texte est exploitable, sinon
    ("", [pages en JPEG], notes) pour un PDF scanné."""
    import fitz  # PyMuPDF

    notes: List[str] = []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        total = pdf.page_count
        pages = list(pdf.pages(0, min(total, MAX_PDF_PAGES)))
        if total > MAX_PDF_PAGES:
            notes.append(f"Seules les {MAX_PDF_PAGES} premières pages sur {total} ont été analysées.")
        text = "\n".join(p.get_text() for p in pages).strip()
        if pages and len(text) / len(pages) >= MIN_TEXT_CHARS_PER_PAGE:
            return text[:MAX_TEXT_CHARS], [], notes
        images = [_shrink_image(p.get_pixmap(dpi=PDF_RENDER_DPI).tobytes("png")) for p in pages]
    if not images:
        raise ValueError("PDF vide ou illisible")
    return "", images, notes


# ---------------------------------------------------------------------
# Lecture de la réponse du modèle
# ---------------------------------------------------------------------
def _parse_json(text: str) -> Dict[str, Any]:
    """Tolère un éventuel bloc ```json``` ou du texte parasite autour du JSON."""
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


def _clamp_confidence(value: Any) -> Optional[float]:
    """Ramène la confiance auto-déclarée dans [0, 1] (None si absente/illisible)."""
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return None


def _empty(model_id: str, flag: str, error: Optional[str] = None) -> Dict[str, Any]:
    """Résultat vide (analyse impossible) — même forme qu'un résultat normal."""
    result: Dict[str, Any] = {
        "summary": "", "extracted_fields": {}, "document_type": None, "flags": [flag],
        "confidence": None, "uncertain_fields": [], "model": model_id, "input_mode": None,
        "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "cost_xof": 0.0,
        "pages_analyzed": 0, "duration_ms": 0,
    }
    if error:
        result["error"] = error
    return result


# ---------------------------------------------------------------------
# Appel au modèle via le proxy Emergent
# ---------------------------------------------------------------------
async def _call_llm(model: OcrModel, text: str, images: List[bytes], filename: str) -> Tuple[str, int, int]:
    """Envoie texte ou images au modèle ; renvoie (réponse, tokens_entrée, tokens_sortie).

    `send_message_with_tools()` (sans outil déclaré) est la méthode publique
    d'emergentintegrations 0.2.0 qui expose l'usage réel en tokens ;
    `send_message()` ne renvoie que le texte."""
    api_key = os.environ.get("EMERGENT_LLM_KEY", "")
    if not api_key:
        raise RuntimeError("Clé LLM non configurée (EMERGENT_LLM_KEY)")
    chat = LlmChat(
        api_key=api_key,
        session_id=f"albarka-doc-{secrets.token_urlsafe(8)}",
        system_message=SYSTEM_PROMPT,
    ).with_model(MODEL_PROVIDER, model.id).with_params(max_tokens=8192)

    if images:
        message = UserMessage(
            text=f"Nom du fichier : {filename}. Analyse cette pièce ({len(images)} page(s)).",
            file_contents=[ImageContent(image_base64=base64.b64encode(img).decode("ascii")) for img in images],
        )
    else:
        message = UserMessage(text=(
            f"Nom du fichier : {filename}\n\nContenu extrait du document :\n---\n{text}\n---\n\n"
            "Analyse ce document et réponds uniquement en JSON strict."
        ))
    response = await chat.send_message_with_tools(message)
    usage = response.usage
    return response.content or "", int(usage.input_tokens or 0), int(usage.output_tokens or 0)


async def analyze_document(
    data: bytes, content_type: str, filename: str, model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Router principal ; ne lève jamais — retourne toujours un dict.

    Compatible avec les appels existants (albarka_myaccount.py) : sans
    `model_id`, le modèle par défaut est utilisé."""
    model = get_model(model_id) or OCR_MODELS[DEFAULT_MODEL_ID]

    # 1. Préparation : texte, images ou refus (format non analysable)
    notes: List[str] = []
    text, images = "", []
    try:
        if content_type == "application/pdf":
            text, images, notes = prepare_pdf(data)
        elif content_type in IMAGE_MIMES:
            images = [_shrink_image(data)]
        else:
            text = data.decode("utf-8", errors="ignore")[:MAX_TEXT_CHARS]   # txt / csv
            if not text.strip():
                return _empty(model.id, f"Type non pris en charge pour l'analyse : {content_type}")
    except Exception as exc:  # noqa: BLE001 — image corrompue, PDF protégé...
        logger.exception("Préparation impossible pour %s", filename)
        return _empty(model.id, f"Fichier illisible : {exc}", error=str(exc))
    input_mode = "images" if images else "texte"

    # 2. Appel au modèle
    started = time.monotonic()
    try:
        reply, input_tokens, output_tokens = await _call_llm(model, text, images, filename)
    except Exception as exc:  # noqa: BLE001 — réseau, quota, clé absente, modèle inconnu du proxy...
        logger.exception("Erreur analyse IA (%s) pour %s", model.id, filename)
        return _empty(model.id, f"Erreur d'analyse : {exc}", error=str(exc))

    # 3. Coût calculé AVANT le parsing : les tokens sont facturés même si la
    #    réponse est inexploitable.
    cost_usd, cost_xof = compute_cost(model, input_tokens, output_tokens)
    metrics = {
        "model": model.id, "input_mode": input_mode,
        "input_tokens": input_tokens, "output_tokens": output_tokens,
        "cost_usd": cost_usd, "cost_xof": cost_xof,
        "pages_analyzed": len(images) if images else 1,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    try:
        parsed = _parse_json(reply)
    except json.JSONDecodeError as exc:
        logger.exception("Réponse IA non-JSON (%s) pour %s", model.id, filename)
        result = _empty(model.id, "Réponse de l'IA au format inattendu", error=str(exc))
        result.update(metrics)
        return result

    fields = parsed.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {"valeur": fields}
    return {
        "summary": parsed.get("summary", ""),
        "extracted_fields": fields,
        "document_type": parsed.get("document_type"),
        "flags": list(parsed.get("flags") or []) + notes,
        "confidence": _clamp_confidence(parsed.get("confidence")),
        "uncertain_fields": [k for k in (parsed.get("uncertain_fields") or []) if isinstance(k, str)],
        **metrics,
    }
