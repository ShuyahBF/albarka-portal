"""Lot 23 — Pictogramme « Assistance » : discussion avec le support SAWALI depuis le portail ALBARKA.

Demande du propriétaire (09/10/2026) : comme sur bfmobility, un petit pictogramme d'assistance (casque) dans
l'en-tête du portail ouvre une fenêtre de discussion avec le support SAWALI. Côté SAWALI, les messages arrivent
dans le chat de l'équipe, espace « ALBARKA - Support », avec un numéro de requête (SUP-…).

En résumé (pour un développeur WinDev) :
  - le NAVIGATEUR ne parle jamais directement à SAWALI : il appelle CE serveur (utilisateur connecté : personnel
    du cabinet OU client), qui relaie vers SAWALI une requête SIGNÉE avec la clé déjà utilisée pour la
    transmission WhatsApp universelle (variables Render LILUVINE_WA_HMAC et LILUVINE_WA_EMETTEUR, « albarka »
    par défaut) : en-têtes X-Emetteur, X-Timestamp, X-Signature = hex(HMAC-SHA256(clé, « <horodatage>.<corps> »)) ;
    aucune nouvelle variable d'environnement n'est nécessaire ;
  - adresse de SAWALI : SAWALI_API_URL si elle existe, sinon schéma + hôte de LILUVINE_WA_URL, sinon
    https://api.sawalismartsystems.com ;
  - routes (utilisateur connecté) :
      GET  /api/support-sawali/etat      → pictogramme affiché ou non (clé présente)
      POST /api/support-sawali/messages  {texte}               → message envoyé au support
      POST /api/support-sawali/fil       {depuis, marquer_lu}  → messages et réponses du support, état de la requête
  - aucun secret n'est renvoyé au navigateur ; l'identifiant envoyé à SAWALI est celui du compte ALBARKA (SAWALI
    le transforme en identifiant interne).
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from albarka_auth import get_current_user
# Mêmes règles que la transmission WhatsApp : code émetteur (« albarka » par défaut) et calcul de la signature
from albarka_transmission_wa import emetteur, signer

DELAI_SECONDES = 15                                  # délai maximal d'un appel à SAWALI
SAWALI_PAR_DEFAUT = "https://api.sawalismartsystems.com"

# Transport HTTP de remplacement (tests) : None en production
_transport: Optional[httpx.AsyncBaseTransport] = None

router = APIRouter(prefix="/support-sawali", tags=["Support SAWALI"])


# ---------------------------------------------------------------------------
# Configuration (variables d'environnement saisies sur Render par le propriétaire)
# ---------------------------------------------------------------------------
def cle() -> str:
    """Clé HMAC d'ALBARKA chez SAWALI (secrète : jamais affichée ni renvoyée au navigateur)."""
    return (os.environ.get("LILUVINE_WA_HMAC") or "").strip()


def url_sawali() -> str:
    """Adresse de SAWALI : SAWALI_API_URL, sinon schéma + hôte de LILUVINE_WA_URL, sinon l'adresse par défaut."""
    direct = (os.environ.get("SAWALI_API_URL") or "").strip().rstrip("/")
    if direct:
        return direct
    lu = urlparse((os.environ.get("LILUVINE_WA_URL") or "").strip())
    if lu.scheme and lu.netloc:
        return f"{lu.scheme}://{lu.netloc}"
    return SAWALI_PAR_DEFAUT


def configure() -> bool:
    """Vrai si la clé est saisie (sinon le pictogramme reste caché)."""
    return bool(cle())


# ---------------------------------------------------------------------------
# Identité de l'utilisateur envoyée à SAWALI (affichée à l'équipe du support)
# ---------------------------------------------------------------------------
def identite(user: Dict[str, Any]) -> Dict[str, str]:
    """{id, nom, role, contexte, email, telephone} — contexte = « Cabinet ALBARKA » pour le personnel,
    « Client ALBARKA — <société> » pour un client (le support sait ainsi à qui il répond)."""
    roles = [r for r in (user.get("roles") or []) if r]
    client_seul = roles == ["client"]
    if client_seul:
        societe = (user.get("company") or "").strip()
        contexte = f"Client ALBARKA — {societe}" if societe else "Client ALBARKA"
    else:
        contexte = "Cabinet ALBARKA"
    return {
        "id": str(user.get("id") or ""),
        "nom": user.get("full_name") or user.get("email") or "",
        "role": ", ".join(r.replace("_", " ") for r in roles)[:40],
        "contexte": contexte,
        "email": user.get("email") or "",
        "telephone": user.get("whatsapp_number") or user.get("phone") or "",
    }


# ---------------------------------------------------------------------------
# Relais signé vers SAWALI
# ---------------------------------------------------------------------------
async def appeler_sawali(chemin: str, corps: Dict[str, Any]) -> Dict[str, Any]:
    """POST signé vers SAWALI ; renvoie le JSON ou lève une HTTPException lisible pour l'utilisateur."""
    if not configure():
        raise HTTPException(status_code=503, detail="Support SAWALI non configuré sur cette plateforme")
    # Le corps brut signé est EXACTEMENT celui envoyé (même chaîne)
    brut = json.dumps(corps, ensure_ascii=False)
    ts = str(int(time.time()))
    entetes = {"Content-Type": "application/json", "X-Emetteur": emetteur(), "X-Timestamp": ts,
               "X-Signature": signer(cle(), ts, brut)}
    try:
        async with httpx.AsyncClient(timeout=DELAI_SECONDES, transport=_transport) as client:
            r = await client.post(f"{url_sawali()}/api{chemin}", content=brut.encode("utf-8"), headers=entetes)
    except httpx.HTTPError:
        raise HTTPException(status_code=503, detail="Support SAWALI injoignable : réessayez dans un instant")
    # Erreurs de SAWALI traduites en messages clairs (jamais la clé ni le détail technique)
    if r.status_code == 403:
        raise HTTPException(status_code=503, detail="Support SAWALI pas encore activé pour cette plateforme")
    if r.status_code >= 500:
        raise HTTPException(status_code=503, detail="Support SAWALI momentanément indisponible : réessayez dans un instant")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail="Le support SAWALI a refusé la demande")
    try:
        return r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Réponse illisible du support SAWALI")


# ---------------------------------------------------------------------------
# Routes (tout utilisateur connecté : personnel du cabinet et clients)
# ---------------------------------------------------------------------------
class MessageEntree(BaseModel):
    """Message tapé par l'utilisateur dans la fenêtre d'assistance."""
    texte: str = Field(..., min_length=1, max_length=2000)


class FilEntree(BaseModel):
    """Lecture du fil : `depuis` = date du dernier message déjà affiché (lecture incrémentale)."""
    depuis: Optional[str] = Field(None, max_length=40)
    marquer_lu: bool = True   # faux : simple vérification des non-lus (fenêtre fermée), rien n'est marqué lu


@router.get("/etat")
async def etat(user: dict = Depends(get_current_user)):
    """Pictogramme affiché seulement si ALBARKA est relié à SAWALI (clé présente)."""
    return {"actif": configure()}


@router.post("/messages")
async def envoyer(entree: MessageEntree, user: dict = Depends(get_current_user)):
    """Message de l'utilisateur vers le support SAWALI."""
    texte = entree.texte.strip()
    if not texte:
        raise HTTPException(status_code=422, detail="Message vide")
    return await appeler_sawali("/support-plateforme/messages", {"utilisateur": identite(user), "texte": texte})


@router.post("/fil")
async def fil(entree: FilEntree, user: dict = Depends(get_current_user)):
    """Messages de l'utilisateur et réponses du support (depuis une date), état de sa requête."""
    corps: Dict[str, Any] = {"utilisateur": identite(user), "marquer_lu": entree.marquer_lu}
    if entree.depuis:
        corps["depuis"] = entree.depuis
    return await appeler_sawali("/support-plateforme/fil", corps)
