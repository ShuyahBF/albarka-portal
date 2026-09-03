"""Signature électronique des rapports (sceau du cabinet) via pyHanko.

Sans certificat externe payant : le cabinet dispose de son propre certificat
auto-signé (P12), utilisé pour horodater et sceller chaque rapport au format
PAdES-B. Vérifiable dans Adobe Reader (avec ajout du certificat à la liste
des émetteurs de confiance de l'utilisateur).

Certificats stockés dans `<UPLOAD_DIR>/certs/` (jamais commit) et référencés
par la collection `cabinet_certificates` (pointeur + métadonnées).
"""
from __future__ import annotations

import io
import logging
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("albarka.signing")

CERT_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads")) / "certs"
CERT_DIR.mkdir(parents=True, exist_ok=True)


def _generate_self_signed_p12(
    *, common_name: str, organization: str, country: str = "BF",
    email: Optional[str] = None, valid_years: int = 5, passphrase: str,
) -> bytes:
    """Génère un P12 auto-signé RSA 3072 SHA-256."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12

    key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    subject_bits = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, country),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ]
    if email:
        subject_bits.append(x509.NameAttribute(NameOID.EMAIL_ADDRESS, email))
    subject = issuer = x509.Name(subject_bits)
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now.replace(year=now.year + valid_years))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True, content_commitment=True, key_encipherment=False,
                data_encipherment=False, key_agreement=False, key_cert_sign=False,
                crl_sign=False, encipher_only=False, decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.CODE_SIGNING,
                                   x509.ExtendedKeyUsageOID.EMAIL_PROTECTION]),
            critical=False,
        )
        .sign(private_key=key, algorithm=hashes.SHA256())
    )
    p12 = pkcs12.serialize_key_and_certificates(
        name=common_name.encode("utf-8"),
        key=key,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    return p12


def _extract_public_pem(p12_bytes: bytes, passphrase: str) -> str:
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.serialization import pkcs12
    _, cert, _ = pkcs12.load_key_and_certificates(p12_bytes, passphrase.encode("utf-8"))
    if cert is None:
        raise ValueError("Certificat introuvable dans le P12")
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def create_cabinet_certificate(
    *, common_name: str, organization: str, country: str, email: Optional[str],
    valid_years: int, passphrase: str,
) -> dict:
    """Crée le P12, le stocke sur disque, retourne les métadonnées à archiver."""
    from cryptography.hazmat.primitives.serialization import pkcs12
    p12_bytes = _generate_self_signed_p12(
        common_name=common_name, organization=organization, country=country,
        email=email, valid_years=valid_years, passphrase=passphrase,
    )
    cert_id = secrets.token_urlsafe(8)
    p12_path = CERT_DIR / f"{cert_id}.p12"
    with open(p12_path, "wb") as f:
        f.write(p12_bytes)
    os.chmod(p12_path, 0o600)
    # Extraire pour métadonnées + validité
    _, cert, _ = pkcs12.load_key_and_certificates(p12_bytes, passphrase.encode("utf-8"))
    return {
        "id": cert_id,
        "p12_path": str(p12_path),
        "common_name": common_name,
        "organization": organization,
        "country": country,
        "email": email,
        "serial_number": f"{cert.serial_number:x}",
        "not_valid_before": cert.not_valid_before_utc.isoformat(),
        "not_valid_after": cert.not_valid_after_utc.isoformat(),
        "public_pem": _extract_public_pem(p12_bytes, passphrase),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def load_signer(p12_path: str, passphrase: str):
    """Charge un pyhanko signers.SimpleSigner à partir du P12."""
    from pyhanko.sign.signers import SimpleSigner
    return SimpleSigner.load_pkcs12(pfx_file=p12_path, passphrase=passphrase.encode("utf-8"))


def sign_pdf_bytes(
    pdf_bytes: bytes, *, signer, signature_name: str,
    reason: str = "Sceau du cabinet ALBARKA",
    location: str = "Ouagadougou, Burkina Faso",
    visible_stamp: Optional[dict] = None,
) -> bytes:
    """Renvoie les octets d'un PDF scellé PAdES-B.

    Si `visible_stamp` est fourni, on ajoute d'abord :
      - un petit cachet dans le coin bas droit de CHAQUE page,
      - un bloc signature complet sur la DERNIÈRE page.
    Puis pyHanko applique la signature cryptographique invisible.

    `visible_stamp` schema :
      { 'cabinet_name': str, 'signature_number': str, 'signer_name': str,
        'cert_common_name': str, 'cert_serial': str, 'signed_at': str,
        'dg_image_bytes': Optional[bytes] }
    """
    # -------- 1. Apposer le tampon visuel avec PyMuPDF --------
    if visible_stamp:
        try:
            pdf_bytes = _apply_visible_stamp(pdf_bytes, visible_stamp)
        except Exception:
            logger.exception("Apposition du cachet visuel échouée — signature invisible seulement")

    # -------- 2. Signature cryptographique invisible (PAdES-B) --------
    from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
    from pyhanko.sign import PdfSignatureMetadata, sign_pdf
    from pyhanko.sign.fields import SigFieldSpec

    src = io.BytesIO(pdf_bytes)
    out = io.BytesIO()
    writer = IncrementalPdfFileWriter(src)
    signature_meta = PdfSignatureMetadata(
        field_name=f"AlbarkaSeal-{secrets.token_hex(4)}",
        reason=reason,
        location=location,
        name=signature_name,
        subfilter=None,
    )
    sign_pdf(
        writer,
        signature_meta=signature_meta,
        signer=signer,
        output=out,
        new_field_spec=SigFieldSpec(
            sig_field_name=signature_meta.field_name,
            on_page=0, box=(0, 0, 0, 0),  # invisible field
        ),
    )
    return out.getvalue()


def _apply_visible_stamp(pdf_bytes: bytes, meta: dict) -> bytes:
    """Overlay a small corner stamp on every page + a full signature block on last page."""
    import fitz  # PyMuPDF

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        emerald = (0.058, 0.42, 0.29)   # #0F6B4A
        amber = (0.898, 0.635, 0.294)   # #E5A24B
        muted = (0.39, 0.45, 0.55)
        pages = doc.page_count
        sig_num = meta.get("signature_number") or ""
        # Compact number for corner stamp (last segment kept: sequence only)
        short_num = sig_num.split("-")[-1] if "-" in sig_num else sig_num[-8:]

        # -------- Petit cachet coin bas-droit sur chaque page --------
        for i in range(pages):
            page = doc[i]
            w, h = page.rect.width, page.rect.height
            box_w, box_h = 160, 32
            x0 = w - box_w - 18
            y0 = h - box_h - 18
            rect = fitz.Rect(x0, y0, x0 + box_w, y0 + box_h)
            # Amber border + light fill
            page.draw_rect(rect, color=amber, fill=(0.99, 0.96, 0.90), width=0.7)
            page.insert_textbox(
                fitz.Rect(x0 + 6, y0 + 4, x0 + box_w - 6, y0 + box_h - 4),
                f"Signe electroniquement\nRef. {short_num}",
                fontsize=7, fontname="helv", color=emerald, align=0,
            )

        # -------- Bloc complet sur la dernière page --------
        last = doc[pages - 1]
        w, h = last.rect.width, last.rect.height
        block_w, block_h = 260, 130
        # Position: bottom-left with margin
        bx0 = 60
        by0 = h - block_h - 60
        rect = fitz.Rect(bx0, by0, bx0 + block_w, by0 + block_h)
        last.draw_rect(rect, color=emerald, fill=(0.988, 0.98, 0.957), width=1.0)
        # Title bar
        title_rect = fitz.Rect(bx0, by0, bx0 + block_w, by0 + 20)
        last.draw_rect(title_rect, color=emerald, fill=emerald, width=0)
        last.insert_textbox(
            fitz.Rect(bx0 + 8, by0 + 5, bx0 + block_w - 8, by0 + 18),
            "SCEAU DU CABINET - SIGNATURE ELECTRONIQUE",
            fontsize=7.5, fontname="hebo", color=(1, 1, 1), align=0,
        )
        # Optional DG signature image on the right side
        text_left_end = bx0 + block_w - 12
        dg_bytes = meta.get("dg_image_bytes")
        if dg_bytes:
            try:
                img_rect = fitz.Rect(bx0 + block_w - 80, by0 + 26, bx0 + block_w - 10, by0 + 76)
                last.insert_image(img_rect, stream=dg_bytes, keep_proportion=True)
                text_left_end = bx0 + block_w - 90
            except Exception:
                pass
        # Body
        body = (
            f"{meta.get('cabinet_name', 'Cabinet ALBARKA')}\n"
            f"Signataire : {meta.get('signer_name', '')}\n"
            f"Certificat : {meta.get('cert_common_name', '')}\n"
            f"N° série : {(meta.get('cert_serial') or '')[:16]}…\n"
            f"Horodaté : {meta.get('signed_at', '')}\n"
            f"Réf. rapport : {meta.get('signature_number', '')}"
        )
        last.insert_textbox(
            fitz.Rect(bx0 + 10, by0 + 26, text_left_end, by0 + block_h - 8),
            body, fontsize=7.5, fontname="helv", color=muted, align=0,
        )

        buf = io.BytesIO()
        doc.save(buf, deflate=True, garbage=3)
        return buf.getvalue()
    finally:
        doc.close()


# --- Fernet-based passphrase encryption (uses JWT_SECRET_KEY as material) ---
def _fernet():
    import base64
    import hashlib
    from cryptography.fernet import Fernet
    key_material = os.environ["JWT_SECRET_KEY"].encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(key_material).digest())
    return Fernet(key)


def encrypt_passphrase(plain: str) -> str:
    return _fernet().encrypt(plain.encode("utf-8")).decode("ascii")


def decrypt_passphrase(cipher: str) -> str:
    return _fernet().decrypt(cipher.encode("ascii")).decode("utf-8")


# --- FastAPI router for cabinet certificate management ---
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import require_roles
from db import db, serialize, serialize_many

router = APIRouter(prefix="/admin/certificates", tags=["Signature électronique"])

_ADMIN_ROLES = ["superviseur", "direction"]


class CertificateCreate(BaseModel):
    common_name: str = Field(..., min_length=2, max_length=120)
    organization: str = Field(..., min_length=2, max_length=200)
    country: str = Field("BF", min_length=2, max_length=2)
    email: Optional[str] = None
    valid_years: int = Field(5, ge=1, le=15)
    passphrase: str = Field(..., min_length=8, max_length=200)
    activate: bool = True


@router.get("")
async def list_certificates(user: dict = Depends(require_roles(_ADMIN_ROLES))):
    docs = await db.cabinet_certificates.find(
        {}, {"_id": 0, "encrypted_passphrase": 0, "p12_path": 0}
    ).sort("created_at", -1).to_list(50)
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0, "cabinet_certificate": 1}) or {}
    active_id = (settings.get("cabinet_certificate") or {}).get("id")
    for d in docs:
        d["is_active"] = d["id"] == active_id
    return serialize_many(docs)


@router.post("")
async def create_certificate(
    payload: CertificateCreate, user: dict = Depends(require_roles(_ADMIN_ROLES))
):
    meta = create_cabinet_certificate(
        common_name=payload.common_name, organization=payload.organization,
        country=payload.country.upper(), email=payload.email,
        valid_years=payload.valid_years, passphrase=payload.passphrase,
    )
    # Store metadata + encrypted passphrase (never plain).
    encrypted_pp = encrypt_passphrase(payload.passphrase)
    doc = {
        **meta,
        "encrypted_passphrase": encrypted_pp,
        "created_by": user["id"],
    }
    await db.cabinet_certificates.insert_one(doc.copy())
    if payload.activate:
        await db.settings.update_one(
            {"_id": "global"},
            {"$set": {"cabinet_certificate": {
                "id": meta["id"],
                "p12_path": meta["p12_path"],
                "common_name": meta["common_name"],
                "serial_number": meta["serial_number"],
                "not_valid_after": meta["not_valid_after"],
            }}},
            upsert=True,
        )
    public = {k: v for k, v in doc.items() if k not in ("encrypted_passphrase", "p12_path")}
    public["is_active"] = payload.activate
    return serialize(public)


@router.post("/{cert_id}/activate")
async def activate_certificate(cert_id: str, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    cert = await db.cabinet_certificates.find_one({"id": cert_id}, {"_id": 0})
    if not cert:
        raise HTTPException(status_code=404, detail="Certificat introuvable")
    await db.settings.update_one(
        {"_id": "global"},
        {"$set": {"cabinet_certificate": {
            "id": cert["id"],
            "p12_path": cert["p12_path"],
            "common_name": cert["common_name"],
            "serial_number": cert["serial_number"],
            "not_valid_after": cert["not_valid_after"],
        }}},
        upsert=True,
    )
    return {"ok": True, "id": cert_id}


@router.delete("/{cert_id}")
async def delete_certificate(cert_id: str, user: dict = Depends(require_roles(_ADMIN_ROLES))):
    cert = await db.cabinet_certificates.find_one({"id": cert_id}, {"_id": 0})
    if not cert:
        raise HTTPException(status_code=404, detail="Certificat introuvable")
    # If active, deactivate. Auto-promote the most recent remaining cert (if any).
    settings = await db.settings.find_one({"_id": "global"}, {"_id": 0}) or {}
    was_active = (settings.get("cabinet_certificate") or {}).get("id") == cert_id
    if was_active:
        await db.settings.update_one(
            {"_id": "global"}, {"$unset": {"cabinet_certificate": ""}},
        )
    # Best-effort remove file
    try:
        p = Path(cert["p12_path"])
        if p.exists():
            p.unlink()
    except Exception:
        logger.exception("Suppression P12 échouée (poursuite)")
    await db.cabinet_certificates.delete_one({"id": cert_id})
    # Auto-activate next available cert
    if was_active:
        remaining = await db.cabinet_certificates.find_one(
            {}, {"_id": 0}, sort=[("created_at", -1)],
        )
        if remaining:
            await db.settings.update_one(
                {"_id": "global"},
                {"$set": {"cabinet_certificate": {
                    "id": remaining["id"],
                    "p12_path": remaining["p12_path"],
                    "common_name": remaining["common_name"],
                    "serial_number": remaining["serial_number"],
                    "not_valid_after": remaining["not_valid_after"],
                }}},
                upsert=True,
            )
    return {"ok": True, "id": cert_id, "auto_activated": bool(was_active)}


async def resolve_passphrase(cert_id: str) -> Optional[str]:
    """Retrieve and decrypt the passphrase stored for this cert_id."""
    cert = await db.cabinet_certificates.find_one(
        {"id": cert_id}, {"_id": 0, "encrypted_passphrase": 1}
    )
    if not cert or not cert.get("encrypted_passphrase"):
        return None
    try:
        return decrypt_passphrase(cert["encrypted_passphrase"])
    except Exception:
        logger.exception("Déchiffrement passphrase échoué pour cert %s", cert_id)
        return None

