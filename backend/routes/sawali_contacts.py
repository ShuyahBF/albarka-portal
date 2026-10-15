"""Lot ALBARKA — CONTACTS D'ALBARKA LUS PAR SAWALI (groupe « Plateforme ALBARKA » : messages WhatsApp de masse, carrousels).

Pour un développeur WinDev : UNE route de lecture seule, GET /api/sawali/contacts?limite=500&page=1, appelée par SAWALI
chaque nuit. Pas d'utilisateur connecté : la requête est SIGNÉE avec la clé partagée SAWALI_CONTACTS_HMAC (variable
d'environnement saisie par le propriétaire sur Render, même valeur que CONTACTS_HMAC_ALBARKA côté SAWALI) :
    X-Timestamp = horodatage Unix (secondes), valable 5 minutes ;
    X-Signature = HMAC-SHA256(clé, "<horodatage>.GET <chemin>?<requête>") en hexadécimal.
Clé absente → 503 (route désactivée) ; signature absente, périmée ou fausse → 401.

Contenu : les COMPTES CLIENTS actifs (rôle « client », compte principal) avec nom, société et numéro WhatsApp ou téléphone.
Jamais les contacts de l'annuaire des clients (leurs propres clients), ni les utilisateurs suivis, ni e-mail, contrat, paiement
ou mot de passe. Lot 28 : le consentement WhatsApp (accord ou retrait, avec sa date) est transmis SEULEMENT si la personne l'a
donné elle-même (case cochée à l'inscription) ; les OFFICINES inscrites ne sont transmises que si elles ont coché la case.
SAWALI ne diffuse un carrousel qu'aux personnes qui ont donné leur accord elles-mêmes.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import re
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request

VALIDITE_SECONDES = 300
LIMITE_DEFAUT = 500
LIMITE_MAX = 1000
VARIABLE_CLE = "SAWALI_CONTACTS_HMAC"
CHEMIN = "/api/sawali/contacts"


def cle_partagee() -> str:
    return (os.environ.get(VARIABLE_CLE) or "").strip()


def signer(cle: str, horodatage: str, chemin: str, requete: str) -> str:
    """HMAC-SHA256 hexadécimal de « <horodatage>.GET <chemin>?<requête> » (même calcul que SAWALI)."""
    cible = f"{chemin}?{requete}" if requete else chemin
    return hmac.new(cle.encode("utf-8"), f"{horodatage}.GET {cible}".encode("utf-8"), hashlib.sha256).hexdigest()


def signature_valide(cle: str, horodatage: str, signature: str, chemin: str, requete: str, maintenant: Optional[float] = None) -> bool:
    """Vrai si l'horodatage est récent (± 5 minutes) et la signature exacte (comparaison à temps constant)."""
    try:
        ecart = abs((maintenant if maintenant is not None else time.time()) - int(horodatage))
    except (TypeError, ValueError):
        return False
    return ecart <= VALIDITE_SECONDES and hmac.compare_digest(signer(cle, horodatage, chemin, requete), signature or "")


async def tous_les_contacts(db) -> List[Dict[str, Any]]:
    """Comptes clients actifs (compte principal) avec un numéro, un contact par numéro, triés de façon stable."""
    contacts, vus = [], set()
    filtre = {"role": "client", "account_status": {"$in": ["active", None]},
              "$or": [{"parent_client_id": {"$exists": False}}, {"parent_client_id": {"$in": [None, ""]}}]}
    async for u in db.users.find(filtre, {"_id": 0, "id": 1, "full_name": 1, "company": 1, "whatsapp_number": 1, "phone": 1,
                                       "accepte_whatsapp": 1, "accepte_whatsapp_le": 1}):
        tel = re.sub(r"\D", "", u.get("whatsapp_number") or u.get("phone") or "")
        if len(tel) < 8 or tel in vus:
            continue
        vus.add(tel)
        contact = {"id": u["id"], "nom": u.get("full_name") or u.get("company") or "", "telephone": tel, "role": "client",
                   "societe": f"ALBARKA · {u['company']}" if u.get("company") else "ALBARKA"}
        if isinstance(u.get("accepte_whatsapp"), bool):      # lot 28 : accord (ou retrait) donné par la personne elle-même
            contact.update({"accepte_whatsapp": u["accepte_whatsapp"], "accepte_le": u.get("accepte_whatsapp_le")})
        contacts.append(contact)
    # Lot 28 : officines inscrites (portail des officines) — seulement celles qui ont coché la case WhatsApp, non suspendues
    async for o in db.officines.find({"accepte_whatsapp": True, "status": {"$ne": "suspended"}},
                                     {"_id": 0, "id": 1, "name": 1, "phone": 1, "accepte_whatsapp_le": 1}):
        tel = re.sub(r"\D", "", o.get("phone") or "")
        if len(tel) < 8 or tel in vus:
            continue
        vus.add(tel)
        contacts.append({"id": o["id"], "nom": o.get("name") or "", "telephone": tel, "role": "officine",
                         "societe": f"ALBARKA · {o['name']}" if o.get("name") else "ALBARKA",
                         "accepte_whatsapp": True, "accepte_le": o.get("accepte_whatsapp_le")})
    return sorted(contacts, key=lambda c: c["id"])


async def page_de_contacts(db, page: int, limite: int) -> Dict[str, Any]:
    limite = max(1, min(int(limite or LIMITE_DEFAUT), LIMITE_MAX))
    tous = await tous_les_contacts(db)
    pages = max(1, -(-len(tous) // limite))
    page = max(1, min(int(page or 1), pages))
    return {"plateforme": "ALBARKA", "page": page, "pages": pages, "total": len(tous),
            "contacts": tous[(page - 1) * limite: page * limite]}


def setup_sawali_contacts_routes(*, db, api) -> None:
    """Branche GET /api/sawali/contacts (appelée par server.py avant app.include_router(api))."""
    @api.get("/sawali/contacts", tags=["SAWALI"])
    async def contacts(request: Request, limite: int = LIMITE_DEFAUT, page: int = 1):
        """Une page de contacts pour SAWALI. 503 si la clé n'est pas saisie, 401 si la signature est absente, périmée ou fausse."""
        cle = cle_partagee()
        if not cle:
            raise HTTPException(status_code=503, detail="Export des contacts désactivé : saisir SAWALI_CONTACTS_HMAC sur le serveur")
        en = request.headers
        if not signature_valide(cle, en.get("X-Timestamp", ""), en.get("X-Signature", ""), request.url.path, request.url.query):
            raise HTTPException(status_code=401, detail="Signature invalide ou périmée")
        return await page_de_contacts(db, page, limite)
