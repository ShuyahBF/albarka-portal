"""Authentification ALBARKA — login/mot de passe + OTP obligatoire + JWT.

Flux : POST /auth/login (email+mdp) -> génère un OTP à 6 chiffres, valable
10 min -> POST /auth/verify-otp (code) -> JWT (7 jours).

Si l'envoi d'email échoue (SMTP non configuré, ex. pendant le pilote), le
code est renvoyé directement dans la réponse (`dev_otp`) plutôt que de
bloquer la démo — à désactiver avant mise en production réelle.
"""
from __future__ import annotations

import logging
import os
import random
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt

from albarka_models import (
    AuthTokenResponse,
    LoginRequest,
    LoginResponse,
    OtpVerifyRequest,
    User,
)
from db import db

logger = logging.getLogger("albarka.auth")

SECRET_KEY = os.environ["JWT_SECRET_KEY"]
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7 jours
OTP_EXPIRE_MINUTES = 10

_security = HTTPBearer()

router = APIRouter(prefix="/auth", tags=["Authentification"])


# ---------------------------------------------------------------------
# Password / OTP / JWT helpers
# ---------------------------------------------------------------------
def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def generate_otp() -> str:
    return f"{random.randint(0, 999999):06d}"


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def create_access_token(user_id: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


async def send_otp_email(to_email: str, full_name: str, code: str) -> bool:
    """Best-effort OTP email. Returns False (never raises) when SMTP isn't
    configured — the caller falls back to displaying the code directly."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    if not (smtp_host and smtp_user and smtp_password):
        return False
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Votre code de connexion — Portail ALBARKA"
        msg["From"] = smtp_user
        msg["To"] = to_email
        msg.attach(MIMEText(
            f"Bonjour {full_name},\n\nVotre code de connexion est : {code}\n"
            f"Il est valable {OTP_EXPIRE_MINUTES} minutes.\n\nCabinet ALBARKA",
            "plain",
        ))
        with smtplib.SMTP(smtp_host, int(os.environ.get("SMTP_PORT", 587))) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True
    except Exception:
        logger.exception("Échec envoi OTP par email")
        return False


def _to_user_public(user_doc: dict) -> User:
    return User(**user_doc)


# ---------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------
async def get_current_user(creds: HTTPAuthorizationCredentials = Depends(_security)) -> dict:
    try:
        payload = jwt.decode(creds.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token invalide")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token invalide")
    user = await db.users.find_one({"id": user_id}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")
    return user


def require_roles(allowed: list[str]):
    """FastAPI dependency: allows `superviseur` unconditionally, plus anyone
    holding at least one role in `allowed`."""
    async def _checker(user: dict = Depends(get_current_user)) -> dict:
        roles = set(user.get("roles") or [])
        if "superviseur" in roles or (roles & set(allowed)):
            return user
        raise HTTPException(status_code=403, detail="Permission refusée")
    return _checker


# ---------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------
@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    user = await db.users.find_one({"email": payload.email.lower()})
    if not user or not verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    if not user.get("is_active", True):
        raise HTTPException(status_code=403, detail="Compte désactivé")

    code = generate_otp()
    session_token = generate_session_token()
    expires_at = (datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES)).isoformat()
    await db.otps.insert_one({
        "id": secrets.token_urlsafe(12),
        "user_id": user["id"],
        "session_token": session_token,
        "code": code,
        "expires_at": expires_at,
        "used": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })

    sent = await send_otp_email(user["email"], user["full_name"], code)
    dev_otp = None if sent else code
    message = (
        "Un code de vérification a été envoyé à votre adresse email."
        if sent
        else "Service email non configuré (pilote) : code affiché ci-dessous."
    )
    return LoginResponse(needs_otp=True, session_token=session_token, message=message, dev_otp=dev_otp)


@router.post("/verify-otp", response_model=AuthTokenResponse)
async def verify_otp(payload: OtpVerifyRequest):
    otp = await db.otps.find_one({"session_token": payload.session_token, "used": False})
    if not otp:
        raise HTTPException(status_code=400, detail="Session invalide ou expirée")
    if datetime.fromisoformat(otp["expires_at"]) < datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="Code expiré")
    if otp["code"] != payload.code.strip():
        raise HTTPException(status_code=400, detail="Code incorrect")

    await db.otps.update_one({"id": otp["id"]}, {"$set": {"used": True}})
    user = await db.users.find_one({"id": otp["user_id"]}, {"_id": 0, "password_hash": 0})
    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_login": datetime.now(timezone.utc).isoformat()}},
    )
    token = create_access_token(user["id"])
    return AuthTokenResponse(access_token=token, user=_to_user_public(user))


@router.get("/me", response_model=User)
async def me(user: dict = Depends(get_current_user)):
    return User(**user)
