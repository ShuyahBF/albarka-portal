"""Analyse IA des pièces — adaptateur Albarka du module commun `ocr_core`.

Toute la logique d'OCR (catalogue Opus 5 / Sonnet 5 / Haiku 4.5, préparation
des pièces — PDF texte, PDF scanné converti en images, photo redressée et
réduite —, appel à Claude via EMERGENT_LLM_KEY, coût réel en FCFA) vit dans
`backend/ocr_core/`, COPIE IDENTIQUE du module commun maintenu dans le dépôt
ShuyahBF/Claude (dossier ocr-core/) et partagé avec la plateforme Sawali.
Ne pas modifier `ocr_core/` ici : corriger dans ocr-core puis resynchroniser.

Ce fichier ne garde que ce qui est propre à Albarka :
  - la consigne système (qui est le cabinet, quelles pièces il reçoit) ;
  - le modèle par défaut (variable ALBARKA_OCR_DEFAULT_MODEL, puis
    OCR_DEFAULT_MODEL, sinon Sonnet 5) ;
  - la même interface qu'au lot 1, pour que `albarka_documents.py` et
    `albarka_myaccount.py` (pré-remplissage KYC) n'aient rien à changer.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import ocr_core
from ocr_core import OCR_MODELS, OcrModel, compute_cost, get_model, usd_to_xof_rate  # noqa: F401 — réexportés
from ocr_core.prepare import MAX_IMAGE_EDGE_PX, MAX_PDF_PAGES, prepare_pdf  # noqa: F401 — réexportés

# Consigne système propre au cabinet (le format de réponse JSON est commun, dans ocr_core).
SYSTEM_PROMPT = ocr_core.build_system_prompt(
    organisation="l'équipe du cabinet ALBARKA (cabinet d'assistance fiscale et comptable au Burkina Faso)",
    documents=(
        "par un client du cabinet : facture, reçu, relevé bancaire, contrat de bail, déclaration "
        "fiscale, bulletin de paie, pièce d'identité, registre du commerce, etc."
    ),
)


def _default_model_id() -> str:
    """Modèle par défaut (dépôts des clients, pré-remplissage KYC).

    ALBARKA_OCR_DEFAULT_MODEL (nom du lot 1) reste prioritaire s'il est défini,
    puis OCR_DEFAULT_MODEL (nom commun à tous les sites), sinon Sonnet 5."""
    if os.environ.get("ALBARKA_OCR_DEFAULT_MODEL"):
        return ocr_core.default_model_id("ALBARKA_OCR_DEFAULT_MODEL")
    return ocr_core.default_model_id()


DEFAULT_MODEL_ID = _default_model_id()
MODEL_ID = DEFAULT_MODEL_ID  # compatibilité avec l'ancien nom de constante


async def analyze_document(
    data: bytes, content_type: str, filename: str, model_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Même signature qu'au lot 1 ; ne lève jamais — retourne toujours un dict.

    Sans `model_id` (appel de albarka_myaccount.py), le modèle par défaut est utilisé."""
    return await ocr_core.analyze_document(
        data, content_type, filename, model_id,
        system_prompt=SYSTEM_PROMPT, default_model=DEFAULT_MODEL_ID,
    )
