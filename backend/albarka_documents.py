"""Documents (pièces client) — upload, listing, download, analyse IA.

Mesure et optimisation de l'OCR (staff uniquement) :
  - choix du modèle Claude avant téléversement (Opus / Sonnet / Haiku) ;
  - chaque analyse est une « exécution » conservée dans `document_ocr_runs`
    (une pièce peut être relancée avec un autre modèle pour comparer), avec
    son coût réel en FCFA (tokens réellement consommés) ;
  - `document_syntheses` garde, comme avant, UNE synthèse par pièce (la plus
    récente) : les rapports PDF qui la lisent ne changent pas ;
  - évaluation humaine : 1 à 5 étoiles + corrections des champs → précision
    réelle, distincte de la confiance que le modèle s'attribue ;
  - tableau de bord par période et par modèle.
Les clients ne voient jamais le modèle, le coût ni les évaluations.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from html import escape as _esc
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, Field

from albarka_ai import DEFAULT_MODEL_ID, OCR_MODELS, analyze_document, get_model, usd_to_xof_rate
from albarka_auth import get_current_user, require_staff
from albarka_models import (
    DOCS_DELETE_ROLES,
    DOCS_PRIVILEGED_ROLES,
    DOCUMENT_KINDS,
    is_client,
    is_whatsapp_verified,
    tenant_id_of,
    whatsapp_number_of,
)
from albarka_notifications import notify_upload, send_email
from albarka_storage import get_object, guess_content_type, presigned_url, save_and_log, storage_mode
from db import db, serialize, serialize_many

logger = logging.getLogger("albarka.documents")

router = APIRouter(prefix="/documents", tags=["Pièces client"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 Mo
ALLOWED_EXTENSIONS = {"pdf", "jpg", "jpeg", "png", "webp", "doc", "docx", "xls", "xlsx", "txt", "csv"}

# Rôle "telechargement" : cumulable, accordé en plus du métier principal pour
# autoriser le téléchargement des pièces sans dépendre du rôle hiérarchique.
# DOCS_PRIVILEGED_ROLES/DOCS_DELETE_ROLES (albarka_models.py) sont partagés
# avec le Chat interne et le module Clients — ne pas dupliquer ces listes.
DOWNLOAD_ROLES = [*DOCS_PRIVILEGED_ROLES, "telechargement"]


def _has_download_access(user: dict) -> bool:
    return bool(set(user.get("roles") or []) & set(DOWNLOAD_ROLES))


def _require_download_access(user: dict) -> None:
    """Le client garde toujours accès à ses propres pièces ; côté staff,
    seuls DOWNLOAD_ROLES peuvent télécharger celles des clients."""
    if is_client(user):
        return
    if not _has_download_access(user):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")


def _require_delete_access(user: dict) -> None:
    """Suppression plus sensible que le téléchargement : jamais le rôle
    "telechargement" seul, jamais "secretariat" seul — voir DOCS_DELETE_ROLES."""
    if is_client(user):
        return
    if not set(user.get("roles") or []) & set(DOCS_DELETE_ROLES):
        raise HTTPException(status_code=403, detail="Action réservée aux rôles autorisés")


def _can_send_whatsapp(user: dict, owner: dict) -> bool:
    """Un collaborateur privilégié (DOCS_PRIVILEGED_ROLES) peut toujours
    envoyer. Les autres ne le peuvent que s'ils portent le rôle
    "communication" ET que le numéro WhatsApp du client est attesté
    "vérifié" — voir albarka_clients.py pour l'endpoint qui pose ce statut,
    et is_whatsapp_verified() dans albarka_models.py pour le repli sur
    phone_verified quand aucun numéro WhatsApp distinct n'est renseigné."""
    roles = set(user.get("roles") or [])
    if roles & set(DOCS_PRIVILEGED_ROLES):
        return True
    return "communication" in roles and is_whatsapp_verified(owner)


def _ext_of(filename: str) -> str:
    return (filename.rsplit(".", 1)[-1] if "." in filename else "").lower()


def _resolve_tenant_id(user: dict, requested: Optional[str]) -> str:
    if is_client(user):
        return tenant_id_of(user)
    if not requested:
        raise HTTPException(status_code=400, detail="tenant_id requis pour un compte cabinet")
    return requested


def _resolve_model_id(user: dict, requested: Optional[str]) -> str:
    """Le staff choisit le modèle d'IA ; un client utilise toujours le modèle par défaut."""
    if is_client(user) or not requested:
        return DEFAULT_MODEL_ID
    if not get_model(requested):
        raise HTTPException(status_code=400, detail=f"Modèle d'IA inconnu : {requested}")
    return requested


# Champs internes au cabinet, jamais renvoyés à un compte client.
_INTERNAL_SYNTHESIS_FIELDS = {
    "run_id", "model", "input_mode", "input_tokens", "output_tokens", "cost_usd", "cost_xof",
    "pages_analyzed", "duration_ms", "confidence", "uncertain_fields", "error", "requested_by",
}


def _for_client(synthesis: Optional[dict]) -> Optional[dict]:
    if not synthesis:
        return synthesis
    return {k: v for k, v in synthesis.items() if k not in _INTERNAL_SYNTHESIS_FIELDS}


@router.post("")
async def upload_document(
    file: UploadFile = File(...),
    kind: str = Form("piece_comptable"),
    tenant_id: Optional[str] = Form(None),
    model: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
):
    if kind not in DOCUMENT_KINDS:
        raise HTTPException(status_code=400, detail=f"kind invalide (attendu : {DOCUMENT_KINDS})")
    ext = _ext_of(file.filename or "")
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail=f"Extension non autorisée : .{ext}")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux (max 20 Mo)")

    resolved_tenant_id = _resolve_tenant_id(user, tenant_id)
    model_id = _resolve_model_id(user, model)
    content_type = guess_content_type(ext, file.content_type or "application/octet-stream")

    stored = await save_and_log(
        db, data=data, kind=kind, tenant_id=resolved_tenant_id,
        ext=ext, content_type=content_type,
        original_filename=file.filename, user_id=user["id"],
    )

    doc = {
        "id": stored["id"],
        "tenant_id": resolved_tenant_id,
        "uploaded_by": user["id"],
        "kind": kind,
        "storage_path": stored["path"],
        "original_filename": file.filename,
        "content_type": content_type,
        "size": stored["size"],
        "status": "en_analyse",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db.documents.insert_one(doc.copy())

    # Point 2 — capture automatique dans la bibliothèque d'archives.
    try:
        from albarka_phase_c import _auto_archive
        await _auto_archive(
            title=f"Pièce {kind} — {file.filename or doc['id']}",
            category="pieces_client",
            tags=[kind, resolved_tenant_id],
            source={"kind": "document", "id": doc["id"],
                    "tenant_id": resolved_tenant_id,
                    "storage_path": stored["path"]},
            user=user,
        )
    except Exception:  # noqa: BLE001
        pass  # best-effort

    # Notify staff (fire-and-forget) whenever a **client** deposits a piece.
    if is_client(user):
        tenant = await db.users.find_one({"id": resolved_tenant_id}, {"_id": 0, "password_hash": 0})
        if tenant:
            asyncio.create_task(notify_upload(db, document=doc, tenant=tenant))

    asyncio.create_task(_analyze_and_store(
        doc["id"], data, content_type, file.filename or "", resolved_tenant_id, model_id, user["id"],
    ))
    return serialize(doc.copy())


async def _analyze_and_store(
    document_id: str, data: bytes, content_type: str, filename: str, tenant_id: str,
    model_id: Optional[str] = None, requested_by: Optional[str] = None,
) -> None:
    try:
        result = await analyze_document(data, content_type, filename, model_id)
        now = datetime.now(timezone.utc).isoformat()
        synthesis = {
            "id": document_id,
            "document_id": document_id,
            "tenant_id": tenant_id,
            "summary": result.get("summary", ""),
            "extracted_fields": result.get("extracted_fields", {}),
            "document_type_guess": result.get("document_type"),
            "flags": result.get("flags", []),
            "model": result.get("model"),
            "created_at": now,
            # Mesure OCR (interne au cabinet, masquée aux clients)
            "confidence": result.get("confidence"),
            "uncertain_fields": result.get("uncertain_fields", []),
            "input_mode": result.get("input_mode"),
            "input_tokens": result.get("input_tokens", 0),
            "output_tokens": result.get("output_tokens", 0),
            "cost_usd": result.get("cost_usd", 0.0),
            "cost_xof": result.get("cost_xof", 0.0),
            "pages_analyzed": result.get("pages_analyzed", 0),
            "duration_ms": result.get("duration_ms", 0),
            "error": result.get("error"),
            "requested_by": requested_by,
        }
        # 1. Historique : chaque analyse est une exécution conservée (id propre),
        #    pour comparer les modèles et porter l'évaluation humaine.
        run = {**synthesis, "id": str(uuid.uuid4()), "review": None}
        await db.document_ocr_runs.insert_one(run.copy())
        # 2. Synthèse « courante » : toujours UNE par pièce (id = document_id),
        #    exactement comme avant ce lot — lue par les rapports PDF.
        synthesis["run_id"] = run["id"]
        await db.document_syntheses.update_one(
            {"id": document_id}, {"$set": synthesis}, upsert=True,
        )
        new_status = "erreur_analyse" if result.get("error") or (result.get("flags") and not result.get("summary")) else "analyse"
        await db.documents.update_one({"id": document_id}, {"$set": {"status": new_status}})
    except Exception:
        logger.exception("Échec analyse IA pour %s", document_id)
        await db.documents.update_one({"id": document_id}, {"$set": {"status": "erreur_analyse"}})


@router.get("")
async def list_documents(tenant_id: Optional[str] = None, user: dict = Depends(get_current_user)):
    query: dict = {}
    if is_client(user):
        query["tenant_id"] = tenant_id_of(user)
    elif tenant_id:
        query["tenant_id"] = tenant_id
    docs = await db.documents.find(query, {"_id": 0}).sort("created_at", -1).to_list(500)
    docs = serialize_many(docs)

    # Vue staff : résout le propriétaire (client) de chaque pièce en une seule
    # requête groupée, pour affichage dans la colonne "Entreprise" du tableau
    # et pour déterminer si l'action WhatsApp est proposée (numéro vérifié).
    if not is_client(user) and docs:
        tenant_ids = sorted({d["tenant_id"] for d in docs if d.get("tenant_id")})
        clients = await db.users.find(
            {"id": {"$in": tenant_ids}},
            {"_id": 0, "id": 1, "full_name": 1, "company": 1, "phone_verified": 1,
             "whatsapp_number": 1, "whatsapp_verified": 1},
        ).to_list(len(tenant_ids))
        by_id = {c["id"]: c for c in clients}
        for d in docs:
            c = by_id.get(d.get("tenant_id"))
            d["client_name"] = (c or {}).get("full_name")
            d["client_company"] = (c or {}).get("company")
            d["client_whatsapp_verified"] = is_whatsapp_verified(c or {})

        # Résumé des analyses IA (modèle, coût, note) affiché dans le tableau.
        runs = await db.document_ocr_runs.find(
            {"document_id": {"$in": [d["id"] for d in docs]}},
            {"_id": 0, "id": 1, "document_id": 1, "model": 1, "cost_xof": 1, "review": 1, "created_at": 1},
        ).sort("created_at", 1).to_list(5000)
        runs_by_doc: Dict[str, List[dict]] = {}
        for r in runs:
            runs_by_doc.setdefault(r["document_id"], []).append({
                "id": r["id"], "model": r.get("model"), "cost_xof": r.get("cost_xof"),
                "rating": (r.get("review") or {}).get("rating"),
            })
        for d in docs:
            d["ocr_runs"] = runs_by_doc.get(d["id"], [])

    return docs


# ---------------------------------------------------------------------
# Mesure OCR : modèles, tableau de bord, évaluation humaine (staff).
# Déclarés AVANT /{document_id} pour ne pas être capturés par cette route.
# ---------------------------------------------------------------------
_OCR_PERIODS = {"today", "7d", "30d", "all"}


@router.get("/ocr-models")
async def list_ocr_models(user: dict = Depends(require_staff())):
    """Liste déroulante des modèles + taux USD→FCFA appliqué aux coûts."""
    return {
        "models": [m.public() for m in OCR_MODELS.values()],
        "default_model": DEFAULT_MODEL_ID,
        "usd_to_xof_rate": usd_to_xof_rate(),
    }


def _period_start(period: str) -> Optional[str]:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    if period == "7d":
        return (now - timedelta(days=7)).isoformat()
    if period == "30d":
        return (now - timedelta(days=30)).isoformat()
    return None


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 4) if values else None


def _ocr_stats_block(rows: List[dict]) -> Dict[str, Any]:
    """Indicateurs d'un groupe d'analyses (un modèle, ou le total)."""
    reviews = [r["review"] for r in rows if r.get("review")]
    ok_rows = [r for r in rows if not r.get("error")]
    total_cost = sum(float(r.get("cost_xof") or 0) for r in rows)
    return {
        "runs": len(rows),
        "errors": len(rows) - len(ok_rows),
        "total_cost_xof": round(total_cost, 2),
        "avg_cost_xof": round(total_cost / len(rows), 2) if rows else None,
        "total_input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "avg_duration_ms": _avg([float(r.get("duration_ms") or 0) for r in ok_rows]),
        # Confiance auto-déclarée par le modèle — indicative seulement
        "avg_confidence": _avg([float(r["confidence"]) for r in ok_rows if r.get("confidence") is not None]),
        # Mesures humaines (seules à faire foi)
        "reviewed": len(reviews),
        "avg_rating": _avg([float(rv["rating"]) for rv in reviews if rv.get("rating")]),
        "avg_accuracy": _avg([float(rv["accuracy"]) for rv in reviews if rv.get("accuracy") is not None]),
    }


@router.get("/ocr-stats")
async def ocr_stats(period: str = "30d", user: dict = Depends(require_staff())):
    """Coût cumulé/moyen, note et précision moyennes, par modèle et au total."""
    if period not in _OCR_PERIODS:
        raise HTTPException(status_code=400, detail=f"period invalide (attendu : {sorted(_OCR_PERIODS)})")
    query: dict = {}
    start = _period_start(period)
    if start:
        query["created_at"] = {"$gte": start}
    rows = await db.document_ocr_runs.find(
        query, {"_id": 0, "extracted_fields": 0, "summary": 0},
    ).to_list(20000)
    by_model: Dict[str, List[dict]] = {}
    for r in rows:
        by_model.setdefault(r.get("model") or "inconnu", []).append(r)
    models = []
    for model_id, model_rows in by_model.items():
        cfg = get_model(model_id)
        models.append({"model": model_id, "label": cfg.label if cfg else model_id, **_ocr_stats_block(model_rows)})
    models.sort(key=lambda m: m["runs"], reverse=True)
    return {"period": period, "usd_to_xof_rate": usd_to_xof_rate(), "models": models, "total": _ocr_stats_block(rows)}


class OcrReviewPayload(BaseModel):
    rating: int = Field(..., ge=1, le=5, description="Note de 1 à 5 étoiles")
    comment: Optional[str] = Field(None, max_length=2000)
    # Valeurs corrigées, clé = nom du champ extrait. Une clé absente de
    # l'extraction = champ oublié par le modèle (compte comme une erreur).
    corrected_fields: Dict[str, Any] = Field(default_factory=dict)


def _normalize_value(value: Any) -> Any:
    """Forme comparable : ignore espaces, casse et format des nombres
    ("150 000", "150000" et 150000.0 sont égaux)."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    text = " ".join(str(value).split())
    compact = text.replace(" ", "").replace("\u202f", "").replace(",", ".")
    try:
        return float(compact)
    except ValueError:
        return text.lower()


def compute_accuracy(extracted: Dict[str, Any], corrected: Dict[str, Any]) -> Dict[str, Any]:
    """Précision réelle = part des champs que le comptable n'a PAS eu à corriger."""
    changed = {
        k: v for k, v in corrected.items()
        if k not in extracted or _normalize_value(v) != _normalize_value(extracted.get(k))
    }
    total = len(set(extracted) | set(corrected))
    accuracy = round((total - len(changed)) / total, 4) if total else None
    return {"changed": changed, "fields_total": total, "fields_corrected": len(changed), "accuracy": accuracy}


@router.post("/ocr-runs/{run_id}/review")
async def review_ocr_run(run_id: str, payload: OcrReviewPayload, user: dict = Depends(require_staff())):
    run = await db.document_ocr_runs.find_one({"id": run_id}, {"_id": 0})
    if not run:
        raise HTTPException(status_code=404, detail="Analyse introuvable")
    acc = compute_accuracy(run.get("extracted_fields") or {}, payload.corrected_fields)
    review = {
        "rating": payload.rating,
        "comment": (payload.comment or "").strip() or None,
        "corrected_fields": acc["changed"],      # seulement ce qui a vraiment changé
        "fields_total": acc["fields_total"],
        "fields_corrected": acc["fields_corrected"],
        "accuracy": acc["accuracy"],
        "reviewed_by": user["id"],
        "reviewed_by_name": user.get("full_name"),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    # Une nouvelle évaluation remplace la précédente (correction d'une erreur de saisie).
    await db.document_ocr_runs.update_one({"id": run_id}, {"$set": {"review": review}})
    return review


async def _get_owned_document(document_id: str, user: dict) -> dict:
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    if is_client(user) and doc["tenant_id"] != tenant_id_of(user):
        raise HTTPException(status_code=403, detail="Accès refusé")
    return doc


@router.get("/{document_id}")
async def get_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    synthesis = await db.document_syntheses.find_one({"document_id": document_id}, {"_id": 0})
    if is_client(user):
        # Le client ne voit que la synthèse, sans modèle/coût/évaluation.
        doc["synthesis"] = _for_client(synthesis)
        return doc
    doc["synthesis"] = synthesis
    # Staff : toutes les analyses de la pièce, pour comparer les modèles.
    doc["ocr_runs"] = await db.document_ocr_runs.find(
        {"document_id": document_id}, {"_id": 0},
    ).sort("created_at", 1).to_list(200)
    return doc


class ReanalyzePayload(BaseModel):
    model: str


@router.post("/{document_id}/reanalyze")
async def reanalyze_document(document_id: str, payload: ReanalyzePayload, user: dict = Depends(require_staff())):
    """Relance l'analyse de la même pièce avec un autre modèle (comparaison)."""
    doc = await _get_owned_document(document_id, user)
    model_id = _resolve_model_id(user, payload.model)
    try:
        data, _ct = await get_object(doc["storage_path"])
    except Exception as exc:  # noqa: BLE001
        logger.exception("Lecture de la pièce impossible pour %s", document_id)
        raise HTTPException(status_code=502, detail=f"Pièce introuvable dans le stockage : {exc}") from exc
    await db.documents.update_one({"id": document_id}, {"$set": {"status": "en_analyse"}})
    asyncio.create_task(_analyze_and_store(
        document_id, data, doc.get("content_type") or "application/octet-stream",
        doc.get("original_filename") or "", doc["tenant_id"], model_id, user["id"],
    ))
    return {"status": "en_analyse", "model": model_id}


@router.get("/{document_id}/download-url")
async def get_download_url(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    _require_download_access(user)
    url = await presigned_url(doc["storage_path"], expires_in=300)
    if url:
        return {"url": url, "expires_in": 300, "mode": "r2"}
    # Local mode: caller should hit /documents/{id}/download
    return {"url": None, "mode": "local"}


@router.get("/{document_id}/download")
async def download_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    _require_download_access(user)
    data, ct = await get_object(doc["storage_path"])
    filename = doc.get("original_filename") or "document"
    return Response(
        content=data,
        media_type=ct or doc.get("content_type", "application/octet-stream"),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("/{document_id}")
async def delete_document(document_id: str, user: dict = Depends(get_current_user)):
    doc = await _get_owned_document(document_id, user)
    _require_delete_access(user)
    await db.documents.delete_one({"id": document_id})
    await db.document_syntheses.delete_one({"document_id": document_id})
    await db.document_ocr_runs.delete_many({"document_id": document_id})
    return {"ok": True, "id": document_id}


@router.get("/_meta/storage-mode")
async def _meta_storage_mode(user: dict = Depends(get_current_user)):
    return {"mode": storage_mode()}


class SendDocumentEmailPayload(BaseModel):
    to: Optional[str] = None
    subject: Optional[str] = None
    message: Optional[str] = None


class SendDocumentWhatsAppPayload(BaseModel):
    to: Optional[str] = None
    message: Optional[str] = None


async def _fetch_document_and_owner(document_id: str) -> tuple[dict, dict]:
    doc = await db.documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document introuvable")
    owner = await db.users.find_one({"id": doc["tenant_id"]}, {"_id": 0, "password_hash": 0})
    if not owner:
        raise HTTPException(status_code=404, detail="Client propriétaire introuvable")
    return doc, owner


@router.post("/{document_id}/send-email")
async def send_document_email(
    document_id: str, payload: SendDocumentEmailPayload, user: dict = Depends(require_staff()),
):
    """Envoie la pièce brute (pas un rapport signé) par email, en réutilisant
    `send_email` comme déjà fait pour les rapports dans albarka_reports_mgmt.py."""
    doc, owner = await _fetch_document_and_owner(document_id)
    recipient = (payload.to or owner.get("email") or "").strip()
    if not recipient:
        raise HTTPException(status_code=400, detail="Aucune adresse email destinataire disponible")

    subject = payload.subject or f"Pièce — {doc.get('original_filename') or doc['id']}"
    owner_label = _esc(owner.get("company") or owner.get("full_name", ""))
    msg_body = payload.message or ""
    html = f"""
<div style="font-family:Arial,sans-serif;color:#0F172A;padding:16px;">
  <p>Bonjour,</p>
  <p>Veuillez trouver ci-joint la pièce <strong>{_esc(doc.get('original_filename') or '')}</strong>
     concernant <strong>{owner_label}</strong>.</p>
  {"<p>" + _esc(msg_body).replace(chr(10), '<br/>') + "</p>" if msg_body else ""}
</div>
"""
    data, ct = await get_object(doc["storage_path"])
    attachment = {
        "filename": doc.get("original_filename") or "document",
        "content": base64.b64encode(data).decode("ascii"),
        "content_type": ct or doc.get("content_type", "application/octet-stream"),
    }
    message_id = await send_email(to=[recipient], subject=subject, html=html, attachments=[attachment])
    if not message_id:
        raise HTTPException(status_code=502, detail="Échec envoi email (proxy indisponible ou rejeté)")

    await db.documents.update_one(
        {"id": document_id},
        {"$set": {
            "email_sent_at": datetime.now(timezone.utc).isoformat(),
            "email_sent_to": recipient,
            "email_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": message_id, "to": recipient}


@router.post("/{document_id}/send-whatsapp")
async def send_document_whatsapp(
    document_id: str, payload: SendDocumentWhatsAppPayload, user: dict = Depends(require_staff()),
):
    """Envoie la pièce brute par WhatsApp, en réutilisant l'upload média Meta
    et `send_whatsapp_document` comme déjà fait pour les rapports."""
    from albarka_admin_settings import get_settings_doc
    from albarka_notifications import (
        _wa_upload_media, send_whatsapp, send_whatsapp_document, send_whatsapp_image,
    )

    doc, owner = await _fetch_document_and_owner(document_id)
    if not _can_send_whatsapp(user, owner):
        raise HTTPException(
            status_code=403,
            detail="Envoi WhatsApp réservé au rôle Communication sur un numéro attesté vérifié "
                   "(ou aux rôles superviseur/direction/DG/administrateur/secrétariat)",
        )
    phone = (payload.to or whatsapp_number_of(owner) or "").strip()
    if not phone.startswith("+"):
        raise HTTPException(status_code=400, detail="Aucun numéro WhatsApp éligible (format +226…)")

    settings = await get_settings_doc()
    if not settings.get("wa_enabled"):
        raise HTTPException(status_code=400, detail="WhatsApp désactivé dans les paramètres")

    filename = doc.get("original_filename") or "document"
    caption = (payload.message or "").strip() or f"Pièce — {filename}"
    data, _ct = await get_object(doc["storage_path"])
    content_type = doc.get("content_type") or "application/octet-stream"
    is_image = content_type.startswith("image/")

    result: dict = {}
    media_id = await _wa_upload_media(pdf_bytes=data, filename=filename, content_type=content_type)
    if media_id:
        if is_image:
            result = await send_whatsapp_image(to_phone=phone, media_id=media_id, caption=caption)
        else:
            result = await send_whatsapp_document(to_phone=phone, media_id=media_id, filename=filename, caption=caption)
    if not result.get("ok"):
        url = await presigned_url(doc["storage_path"], expires_in=604800)
        if url:
            fallback_msg = f"{caption}\n\nTéléchargement (lien sécurisé, 7 jours) :\n{url}"
            result = await send_whatsapp(to_phone=phone, message=fallback_msg)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Échec envoi WhatsApp ({result.get('error') or result.get('kind') or 'inconnu'})")

    await db.documents.update_one(
        {"id": document_id},
        {"$set": {
            "wa_sent_at": datetime.now(timezone.utc).isoformat(),
            "wa_sent_to": phone,
            "wa_sent_by": user["id"],
        }},
    )
    return {"ok": True, "message_id": result.get("message_id"), "to": phone}
