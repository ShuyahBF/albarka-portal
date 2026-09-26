"""Notifications push (Web Push) — navigateur du client, même portail fermé.

Standards : chiffrement du message RFC 8291 (aes128gcm) et identification du
serveur RFC 8292 (VAPID). Implémenté avec `cryptography` (déjà dans
requirements.txt) : aucune nouvelle dépendance.

Clés VAPID : variables d'environnement VAPID_PUBLIC_KEY / VAPID_PRIVATE_KEY
(base64url) si elles existent ; sinon une paire est générée au premier besoin
et gardée en base (document settings `_id="push_vapid"`, jamais renvoyé par
l'API des paramètres).

Routes (préfixe /api) :
  GET    /push/public-key   clé publique pour s'abonner (navigateur)
  POST   /push/subscribe    enregistrer l'abonnement de cet appareil
  POST   /push/unsubscribe  le retirer
  POST   /push/test         envoyer une notification d'essai à soi-même
Collection : push_subscriptions (un document par appareil abonné).
"""
from __future__ import annotations

import base64
import json
import logging
import os
import secrets
import struct
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from fastapi import APIRouter, Body, Depends, HTTPException

from albarka_auth import get_current_user
from db import db

logger = logging.getLogger("albarka.push")

router = APIRouter(prefix="/push", tags=["Notifications push"])

RECORD_SIZE = 4096


def b64u(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def b64u_dec(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _raw_public(key: ec.EllipticCurvePrivateKey) -> bytes:
    """Clé publique P-256 au format « non compressé » (65 octets)."""
    return key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


# ---------------------------------------------------------------- clés VAPID
async def vapid_keys() -> ec.EllipticCurvePrivateKey:
    """Clé privée VAPID (environnement, sinon générée une fois et gardée en base)."""
    env_priv = os.environ.get("VAPID_PRIVATE_KEY")
    if env_priv:
        d = int.from_bytes(b64u_dec(env_priv), "big")
        return ec.derive_private_key(d, ec.SECP256R1())
    doc = await db.settings.find_one({"_id": "push_vapid"})
    if not doc:
        key = ec.generate_private_key(ec.SECP256R1())
        d = key.private_numbers().private_value.to_bytes(32, "big")
        doc = {"_id": "push_vapid", "private_key": b64u(d), "public_key": b64u(_raw_public(key)),
               "created_at": datetime.now(timezone.utc).isoformat()}
        try:
            await db.settings.insert_one(doc)
        except Exception:  # noqa: BLE001 — créée entre-temps par un autre processus
            doc = await db.settings.find_one({"_id": "push_vapid"})
    return ec.derive_private_key(int.from_bytes(b64u_dec(doc["private_key"]), "big"), ec.SECP256R1())


def vapid_authorization(key: ec.EllipticCurvePrivateKey, endpoint: str, subject: str) -> str:
    """En-tête Authorization VAPID (RFC 8292) : jeton ES256 + clé publique."""
    u = urlparse(endpoint)
    header = b64u(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    claims = b64u(json.dumps({"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600,
                              "sub": subject}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}".encode()
    r, s = decode_dss_signature(key.sign(signing_input, ec.ECDSA(hashes.SHA256())))
    sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"vapid t={header}.{claims}.{b64u(sig)}, k={b64u(_raw_public(key))}"


# ---------------------------------------------------------------- chiffrement (RFC 8291)
def encrypt_payload(payload: bytes, p256dh: str, auth: str, *, salt: Optional[bytes] = None,
                    server_key: Optional[ec.EllipticCurvePrivateKey] = None) -> bytes:
    """Chiffre le message pour UN abonnement (clés p256dh + auth du navigateur)."""
    ua_public = b64u_dec(p256dh)
    auth_secret = b64u_dec(auth)
    as_key = server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(as_key)
    ua_key = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public)
    ecdh_secret = as_key.exchange(ec.ECDH(), ua_key)
    ikm = HKDF(algorithm=hashes.SHA256(), length=32, salt=auth_secret,
               info=b"WebPush: info\x00" + ua_public + as_public).derive(ecdh_secret)
    salt = salt or os.urandom(16)
    cek = HKDF(algorithm=hashes.SHA256(), length=16, salt=salt, info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(algorithm=hashes.SHA256(), length=12, salt=salt, info=b"Content-Encoding: nonce\x00").derive(ikm)
    ciphertext = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)  # \x02 = dernier (et seul) bloc
    header = salt + struct.pack("!L", RECORD_SIZE) + bytes([len(as_public)]) + as_public
    return header + ciphertext


async def _send_one(sub: Dict[str, Any], body: bytes, key: ec.EllipticCurvePrivateKey, subject: str) -> Dict[str, Any]:
    data = encrypt_payload(body, sub["keys"]["p256dh"], sub["keys"]["auth"])
    headers = {"Authorization": vapid_authorization(key, sub["endpoint"], subject), "Content-Encoding": "aes128gcm",
               "Content-Type": "application/octet-stream", "TTL": str(3 * 24 * 3600), "Urgency": "normal"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.post(sub["endpoint"], content=data, headers=headers)
        return {"ok": r.status_code < 300, "status": r.status_code, "error": None if r.status_code < 300 else r.text[:200]}
    except httpx.HTTPError as exc:
        return {"ok": False, "status": None, "error": str(exc)[:200]}


async def send_push_to_user(user_id: str, *, title: str, body: str, url: str = "/", tag: str = "albarka") -> Dict[str, Any]:
    """Envoie une notification à tous les appareils abonnés du compte.
    Les abonnements expirés (404/410) sont supprimés. Renvoie {sent, failed}."""
    subs = await db.push_subscriptions.find({"user_id": user_id}, {"_id": 0}).to_list(20)
    if not subs:
        return {"sent": 0, "failed": 0, "devices": 0}
    key = await vapid_keys()
    from albarka_admin_settings import get_settings_doc
    settings = await get_settings_doc()
    subject = f"mailto:{settings.get('cabinet_email') or 'contact@albarka-bf.com'}"
    payload = json.dumps({"title": title[:120], "body": body[:400], "url": url, "tag": tag}, ensure_ascii=False).encode()
    sent = failed = 0
    for sub in subs:
        r = await _send_one(sub, payload, key, subject)
        if r["ok"]:
            sent += 1
            await db.push_subscriptions.update_one({"id": sub["id"]}, {"$set": {"last_success_at": datetime.now(timezone.utc).isoformat()}})
        else:
            failed += 1
            if r["status"] in (404, 410):  # appareil désabonné ou abonnement expiré
                await db.push_subscriptions.delete_one({"id": sub["id"]})
            logger.warning("[push] échec %s pour %s : %s", r["status"], user_id, r["error"])
    return {"sent": sent, "failed": failed, "devices": len(subs)}


# ---------------------------------------------------------------- routes
@router.get("/public-key")
async def public_key(user: dict = Depends(get_current_user)):
    return {"public_key": b64u(_raw_public(await vapid_keys()))}


@router.post("/subscribe")
async def subscribe(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    """Enregistre l'abonnement push de cet appareil (fourni par le navigateur)."""
    sub = payload.get("subscription") or {}
    endpoint = str(sub.get("endpoint") or "")
    keys = sub.get("keys") or {}
    if not endpoint.startswith("https://") or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=400, detail="Abonnement invalide")
    now = datetime.now(timezone.utc).isoformat()
    await db.push_subscriptions.update_one({"endpoint": endpoint}, {"$set": {
        "user_id": user["id"], "endpoint": endpoint, "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
        "user_agent": str(payload.get("user_agent") or "")[:250], "updated_at": now},
        "$setOnInsert": {"id": secrets.token_urlsafe(10), "created_at": now}}, upsert=True)
    return {"ok": True}


@router.post("/unsubscribe")
async def unsubscribe(payload: Dict[str, Any] = Body(...), user: dict = Depends(get_current_user)):
    await db.push_subscriptions.delete_one({"endpoint": str(payload.get("endpoint") or ""), "user_id": user["id"]})
    return {"ok": True}


@router.post("/test")
async def test_push(user: dict = Depends(get_current_user)):
    """Notification d'essai sur les appareils abonnés du compte connecté."""
    r = await send_push_to_user(user["id"], title="Notifications activées",
                                body="Vous recevrez ici les documents que le cabinet met à votre disposition.",
                                url="/portal/documents-cabinet" if "client" in (user.get("roles") or []) else "/admin")
    if not r["devices"]:
        raise HTTPException(status_code=404, detail="Aucun appareil abonné pour ce compte")
    return r


async def ensure_push_indexes() -> None:
    await db.push_subscriptions.create_index("endpoint", unique=True)
    await db.push_subscriptions.create_index("user_id")
