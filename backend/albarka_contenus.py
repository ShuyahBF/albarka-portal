"""Lot 54 — « Infos » (contenu utile hebdomadaire) et « Formations » (gratuites ou payantes via PawaPay).

Un contenu = un titre, une description, un thème, un format (vidéo en lien externe, audio, PDF ou lien) et
une vignette. Le stockage est économe : les vidéos restent chez YouTube / Vimeo (lien « non répertorié »),
seuls les PDF (10 Mo au plus), les audios (15 Mo au plus) et de petites vignettes (1 Mo au plus) sont gardés.
Aucune nouvelle collection MongoDB (cluster Atlas plein) :
  - chaque contenu est un document de `settings` dont l'_id est « contenu:<id> » ;
  - chaque achat de formation est un document de `payment_links` (kind « formation »), ce qui réutilise le
    webhook PawaPay existant pour passer le statut à « completed ».
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from urllib.parse import parse_qs, urlparse

import httpx
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from albarka_admin_settings import get_settings_doc
from albarka_auth import get_current_user, require_roles
from albarka_models import is_client, tenant_id_of, whatsapp_number_of
from albarka_payments import PAWAPAY_HOSTS, _active_token, _currency_for_country, _pawapay_str
from albarka_storage import delete_object, get_object, save_and_log
from db import db

logger = logging.getLogger("albarka.contenus")
router = APIRouter(prefix="/contenus", tags=["Infos et formations"])

# Listes finies -> menus déroulants côté écran.
TYPES = ["info", "formation"]
THEMES = [("comptabilite", "Comptabilité"), ("fiscalite", "Fiscalité"), ("rh", "Ressources humaines"),
          ("cnss", "CNSS"), ("autre", "Autre")]
FORMATS = [("video", "Vidéo (lien YouTube / Vimeo)"), ("audio", "Audio"), ("pdf", "Document PDF"), ("lien", "Lien web"),
           ("serie", "Série de leçons")]
CODES_THEMES = {c for c, _ in THEMES}
CODES_FORMATS = {c for c, _ in FORMATS}
GESTION = ["direction", "secretariat", "administrateur"]    # + superviseur (toujours admis)
GESTION_DEP = require_roles(GESTION)                          # dépendance unique (réutilisée par toutes les routes de gestion)

MAX_PDF = 10 * 1024 * 1024
MAX_AUDIO = 15 * 1024 * 1024
MAX_VIGNETTE = 1 * 1024 * 1024
EXT_AUDIO = {"mp3", "m4a", "ogg", "wav", "aac", "webm"}
EXT_IMAGE = {"jpg", "jpeg", "png", "webp"}
PREFIXE = "contenu:"


def _ext(nom: str) -> str:
    return nom.rsplit(".", 1)[-1].lower() if "." in (nom or "") else ""


def _id_video(url: str) -> Dict[str, str]:
    """Reconnaît YouTube / Vimeo : renvoie {fournisseur, id} ou {}."""
    u = urlparse(url or "")
    h = (u.hostname or "").lower().removeprefix("www.")
    if h == "youtu.be":
        return {"fournisseur": "youtube", "id": u.path.strip("/")}
    if h in ("youtube.com", "m.youtube.com"):
        if u.path == "/watch":
            return {"fournisseur": "youtube", "id": (parse_qs(u.query).get("v") or [""])[0]}
        m = re.match(r"^/(embed|shorts)/([\w-]+)", u.path)
        if m:
            return {"fournisseur": "youtube", "id": m.group(2)}
    if h in ("vimeo.com", "player.vimeo.com"):
        m = re.search(r"(\d{6,})", u.path)
        if m:
            return {"fournisseur": "vimeo", "id": m.group(1)}
    return {}


def _url_ok(url: str) -> str:
    url = (url or "").strip()
    if not url.lower().startswith("https://"):
        raise HTTPException(status_code=400, detail="Le lien doit commencer par https://")
    return url


def _lien(url: str) -> Dict[str, str]:
    """Adresse de lecture intégrée (YouTube / Vimeo) d'un lien vidéo, sinon vide."""
    vid = _id_video(url or "")
    if vid.get("fournisseur") == "youtube":
        return {"embed_url": f"https://www.youtube-nocookie.com/embed/{vid['id']}"}
    if vid.get("fournisseur") == "vimeo":
        return {"embed_url": f"https://player.vimeo.com/video/{vid['id']}"}
    return {}


def _vue(doc: dict, *, acces: bool, gestion: bool = False) -> dict:
    """Vue d'un contenu : le lien / fichier n'est révélé qu'à qui y a accès ; jamais de chemin de stockage."""
    v = {k: doc.get(k) for k in ("id", "type", "titre", "description", "theme", "format", "prix", "publie_le", "publie", "created_at")}
    v["gratuit"] = float(doc.get("prix") or 0) <= 0
    v["acces"] = acces
    vid = _id_video(doc.get("url") or "")
    v["a_vignette"] = bool(doc.get("vignette") or vid.get("fournisseur") == "youtube")
    if vid.get("fournisseur") == "youtube":
        v["vignette_externe"] = f"https://img.youtube.com/vi/{vid['id']}/hqdefault.jpg"   # aperçu fourni par YouTube
    # Leçons : le plan (titres, formats) est toujours visible ; liens et fichiers seulement avec l'accès
    v["lecons"] = []
    for l in doc.get("lecons") or []:
        lv = {"id": l["id"], "titre": l["titre"], "format": l["format"], "a_fichier": bool(l.get("fichier"))}
        if acces or gestion:
            lv["url"] = l.get("url") or ""
            lv.update(_lien(l.get("url") or ""))
        v["lecons"].append(lv)
    if doc.get("diffusion"):
        v["diffusion"] = doc["diffusion"]
    if gestion and doc.get("derniere_relance"):
        v["derniere_relance"] = doc["derniere_relance"]
    if acces:
        v["a_fichier"] = bool(doc.get("fichier"))
        if doc.get("format") in ("video", "lien"):
            v["url"] = doc.get("url")
            v.update(_lien(doc.get("url") or ""))
    if gestion:
        v["url"] = doc.get("url")
        v["a_fichier"] = bool(doc.get("fichier"))
    return v


async def _lire(contenu_id: str) -> dict:
    doc = await db.settings.find_one({"_id": PREFIXE + contenu_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Contenu introuvable")
    return doc


async def _a_acces(doc: dict, user: dict) -> bool:
    """Gratuit, cabinet, ou achat terminé (paiement PawaPay confirmé ou accès accordé par le cabinet)."""
    if float(doc.get("prix") or 0) <= 0 or not is_client(user):
        return True
    achat = await db.payment_links.find_one({"kind": "formation", "contenu_id": doc["id"],
                                             "tenant_id": tenant_id_of(user), "status": "completed"})
    return bool(achat)


async def _stocker(f: UploadFile, *, extensions: set, limite: int, kind: str) -> Dict[str, Any]:
    ext = _ext(f.filename or "")
    if ext not in extensions:
        raise HTTPException(status_code=400, detail=f"Type de fichier non autorisé : .{ext or '?'}")
    data = await f.read()
    if not data or len(data) > limite:
        raise HTTPException(status_code=413, detail=f"Fichier vide ou trop volumineux (max {limite // (1024 * 1024)} Mo)")
    st = await save_and_log(db, data=data, kind=kind, tenant_id="contenus", ext=ext,
                            content_type=f.content_type or None, original_filename=f.filename, user_id=None)
    return {"path": st["path"], "nom": f.filename, "content_type": st["content_type"], "size": st["size"]}


@router.get("/options")
async def options():
    """Listes finies pour les menus déroulants."""
    return {"types": TYPES, "themes": [{"code": c, "libelle": l} for c, l in THEMES],
            "formats": [{"code": c, "libelle": l} for c, l in FORMATS]}


@router.get("")
async def lister(type: str = "info", user: dict = Depends(get_current_user)):
    """Contenus publiés (les plus récents d'abord) ; le cabinet voit aussi les brouillons."""
    if type not in TYPES:
        raise HTTPException(status_code=400, detail="Type inconnu")
    q: Dict[str, Any] = {"_id": {"$regex": f"^{PREFIXE}"}, "type": type}
    if is_client(user):
        q["publie"] = True
    docs = await db.settings.find(q).to_list(500)
    docs.sort(key=lambda d: (d.get("publie_le") or "", d.get("created_at") or ""), reverse=True)
    prog = await _progressions_du_client(user) if is_client(user) else {}
    sortie = []
    for d in docs:
        v = _vue(d, acces=await _a_acces(d, user))
        if is_client(user):
            v["progression"] = _resume_progression(d, prog.get(d["id"]))
        sortie.append(v)
    return sortie


@router.get("/{contenu_id}/vignette")
async def vignette(contenu_id: str):
    """Image d'aperçu (publique : identifiant imprévisible, aucune donnée sensible)."""
    doc = await _lire(contenu_id)
    if not doc.get("vignette"):
        raise HTTPException(status_code=404, detail="Pas de vignette")
    data, ct = await get_object(doc["vignette"]["path"])
    return Response(content=data, media_type=doc["vignette"].get("content_type") or ct,
                    headers={"Cache-Control": "public, max-age=86400"})


@router.get("/{contenu_id}/fichier")
async def fichier(contenu_id: str, user: dict = Depends(get_current_user)):
    """PDF ou audio du contenu — réservé à qui y a accès."""
    doc = await _lire(contenu_id)
    if is_client(user) and not doc.get("publie"):
        raise HTTPException(status_code=404, detail="Contenu introuvable")
    if not await _a_acces(doc, user):
        raise HTTPException(status_code=402, detail="Formation payante : réglez-la pour y accéder")
    if not doc.get("fichier"):
        raise HTTPException(status_code=404, detail="Aucun fichier")
    data, ct = await get_object(doc["fichier"]["path"])
    return Response(content=data, media_type=doc["fichier"].get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{doc["fichier"].get("nom") or "contenu"}"'})


# ----------------------------------------------------------------- achat (PawaPay)
class AchatIn(BaseModel):
    msisdn: Optional[str] = None


@router.post("/{contenu_id}/acheter")
async def acheter(contenu_id: str, request: Request, payload: AchatIn = AchatIn(), user: dict = Depends(get_current_user)):
    """Crée la page de paiement PawaPay d'une formation payante ; renvoie l'adresse où envoyer le client."""
    doc = await _lire(contenu_id)
    prix = float(doc.get("prix") or 0)
    if doc.get("type") != "formation" or prix <= 0 or not doc.get("publie"):
        raise HTTPException(status_code=400, detail="Cette formation est gratuite ou indisponible")
    tenant = tenant_id_of(user)
    if await db.payment_links.find_one({"kind": "formation", "contenu_id": contenu_id, "tenant_id": tenant, "status": "completed"}):
        return {"ok": True, "deja_achete": True}
    s = await get_settings_doc()
    token = _active_token(s)
    if not s.get("pawapay_enabled") or not token:
        raise HTTPException(status_code=503, detail="Le paiement en ligne n'est pas encore activé. Contactez le cabinet.")
    country = (s.get("pawapay_country") or "BFA").upper()
    env = (s.get("pawapay_environment") or "sandbox").lower()
    deposit_id = secrets.token_urlsafe(16)
    origin = (request.headers.get("origin") or "https://albarka-bf.com").rstrip("/")
    retour = f"{origin}/portal/formations?depositId={deposit_id}&formation={contenu_id}"
    msisdn = "".join(c for c in (payload.msisdn or whatsapp_number_of(user) or "") if c.isdigit())
    corps: Dict[str, Any] = {"depositId": deposit_id, "returnUrl": retour, "country": country,
                             "amountDetails": {"amount": str(int(prix)), "currency": _currency_for_country(country)},
                             "reason": f"Formation {doc.get('titre', '')}"[:50]}
    if len(msisdn) >= 8:
        corps["phoneNumber"] = msisdn
    now = datetime.now(timezone.utc).isoformat()
    # Enregistré AVANT l'appel PawaPay (bonne pratique) : l'achat reste traçable même en cas d'erreur réseau.
    await db.payment_links.insert_one({
        "id": secrets.token_urlsafe(12), "deposit_id": deposit_id, "kind": "formation", "contenu_id": contenu_id,
        "tenant_id": tenant, "client_label": user.get("company") or user.get("full_name"), "created_by": user["id"],
        "amount": prix, "currency": _currency_for_country(country), "country": country, "reason": corps["reason"],
        "environment": env, "status": "initiated", "created_at": now, "updated_at": now,
    })
    try:
        async with httpx.AsyncClient(timeout=20) as http:
            r = await http.post(f"{PAWAPAY_HOSTS.get(env, PAWAPAY_HOSTS['sandbox'])}/v2/paymentpage",
                                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}, json=corps)
            rep = r.json() if r.content else {}
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Délai dépassé lors de l'appel à PawaPay")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Erreur PawaPay : {str(exc)[:200]}") from exc
    url = (rep or {}).get("redirectUrl")
    if not url:
        await db.payment_links.update_one({"deposit_id": deposit_id}, {"$set": {"status": "failed", "api_message": _pawapay_str(rep)}})
        raise HTTPException(status_code=502, detail="PawaPay n'a pas renvoyé de page de paiement.")
    await db.payment_links.update_one({"deposit_id": deposit_id}, {"$set": {"redirect_url": url}})
    return {"ok": True, "redirect_url": url, "deposit_id": deposit_id}


@router.get("/{contenu_id}/statut-achat")
async def statut_achat(contenu_id: str, user: dict = Depends(get_current_user)):
    """Dernier achat du client pour cette formation. Si le webhook est en retard, interroge PawaPay."""
    doc = await _lire(contenu_id)
    achat = await db.payment_links.find_one({"kind": "formation", "contenu_id": contenu_id, "tenant_id": tenant_id_of(user)},
                                            sort=[("created_at", -1)])
    if not achat:
        return {"statut": "aucun", "acces": float(doc.get("prix") or 0) <= 0}
    if achat["status"] in ("initiated", "pending"):
        s = await get_settings_doc()
        token = _active_token(s)
        if token:
            try:
                host = PAWAPAY_HOSTS.get((s.get("pawapay_environment") or "sandbox").lower(), PAWAPAY_HOSTS["sandbox"])
                async with httpx.AsyncClient(timeout=10) as http:
                    r = await http.get(f"{host}/v2/deposits/{achat['deposit_id']}", headers={"Authorization": f"Bearer {token}"})
                rep = r.json() if r.content else {}
                st = ((rep.get("data") or rep).get("status") or "").upper()
                nouveau = {"COMPLETED": "completed", "FAILED": "failed", "REJECTED": "failed"}.get(st)
                if nouveau:
                    await db.payment_links.update_one({"deposit_id": achat["deposit_id"]}, {"$set": {"status": nouveau, "api_status": st}})
                    achat["status"] = nouveau
            except Exception:  # noqa: BLE001
                logger.warning("Vérification PawaPay impossible pour %s", achat.get("deposit_id"))
    return {"statut": achat["status"], "acces": achat["status"] == "completed"}


# ----------------------------------------------------------------- gestion (cabinet)
@router.get("/admin/tout")
async def admin_liste(user: dict = Depends(GESTION_DEP)):
    """Tous les contenus (brouillons compris) avec le nombre d'achats confirmés."""
    docs = await db.settings.find({"_id": {"$regex": f"^{PREFIXE}"}}).to_list(1000)
    docs.sort(key=lambda d: (d.get("publie_le") or "", d.get("created_at") or ""), reverse=True)
    sortie = []
    for d in docs:
        v = _vue(d, acces=True, gestion=True)
        v["achats"] = await db.payment_links.count_documents({"kind": "formation", "contenu_id": d["id"], "status": "completed"})
        sortie.append(v)
    return sortie


def _champs(type_: str, titre: str, description: str, theme: str, format_: str, url: str, prix: float, publie_le: str) -> dict:
    """Valide les champs communs (listes finies) d'un contenu."""
    if type_ not in TYPES:
        raise HTTPException(status_code=400, detail="Type inconnu")
    if theme not in CODES_THEMES or format_ not in CODES_FORMATS:
        raise HTTPException(status_code=400, detail="Thème ou format inconnu : choisissez dans la liste")
    if not titre.strip():
        raise HTTPException(status_code=400, detail="Titre obligatoire")
    if format_ in ("video", "lien"):
        url = _url_ok(url)
    # (« serie » : le contenu n'a ni lien ni fichier propre, tout est dans ses leçons)
    if prix < 0:
        raise HTTPException(status_code=400, detail="Prix invalide")
    if type_ == "info":
        prix = 0                                   # les infos sont toujours gratuites
    if publie_le and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", publie_le):
        raise HTTPException(status_code=400, detail="Date de publication invalide (AAAA-MM-JJ)")
    return {"type": type_, "titre": titre.strip()[:150], "description": description.strip()[:3000], "theme": theme,
            "format": format_, "url": url.strip() if format_ in ("video", "lien") else "", "prix": prix,
            "publie_le": publie_le or datetime.now(timezone.utc).strftime("%Y-%m-%d")}


@router.post("")
async def creer(
    type: str = Form(...), titre: str = Form(...), description: str = Form(""), theme: str = Form("autre"),
    format: str = Form(...), url: str = Form(""), prix: float = Form(0), publie_le: str = Form(""), publie: bool = Form(True),
    fichier: Optional[UploadFile] = File(None), vignette: Optional[UploadFile] = File(None),
    user: dict = Depends(GESTION_DEP),
):
    """Ajoute une info ou une formation (fichier PDF / audio et vignette facultative)."""
    champs = _champs(type, titre, description, theme, format, url, prix, publie_le)
    doc: Dict[str, Any] = {"_id": "", "id": secrets.token_urlsafe(10), **champs, "publie": bool(publie),
                           "fichier": None, "vignette": None, "lecons": [], "created_by": user["id"],
                           "created_at": datetime.now(timezone.utc).isoformat()}
    doc["_id"] = PREFIXE + doc["id"]
    if format in ("pdf", "audio"):
        if fichier is None or not fichier.filename:
            raise HTTPException(status_code=400, detail="Joignez le fichier du contenu")
        doc["fichier"] = await _stocker(fichier, extensions={"pdf"} if format == "pdf" else EXT_AUDIO,
                                        limite=MAX_PDF if format == "pdf" else MAX_AUDIO, kind="contenu")
    if vignette is not None and vignette.filename:
        doc["vignette"] = await _stocker(vignette, extensions=EXT_IMAGE, limite=MAX_VIGNETTE, kind="contenu_vignette")
    if doc["type"] == "info" and doc["publie"] and await _diffusion_active():
        doc["diffusion"] = {"statut": "a_envoyer"}           # envoyée par WhatsApp dès la date de publication
    await db.settings.insert_one(doc.copy())
    return _vue(doc, acces=True, gestion=True)


class MajIn(BaseModel):
    titre: Optional[str] = None
    description: Optional[str] = None
    theme: Optional[str] = None
    url: Optional[str] = None
    prix: Optional[float] = None
    publie_le: Optional[str] = None
    publie: Optional[bool] = None


@router.patch("/{contenu_id}")
async def modifier(contenu_id: str, p: MajIn, user: dict = Depends(GESTION_DEP)):
    """Modifie les textes, le prix, la date ou la publication d'un contenu."""
    doc = await _lire(contenu_id)
    maj = {k: v for k, v in p.model_dump(exclude_none=True).items()}
    fusion = {**doc, **maj}
    if "prix" in maj or "theme" in maj or "titre" in maj or "url" in maj or "publie_le" in maj:
        _champs(fusion["type"], fusion["titre"], fusion.get("description") or "", fusion["theme"], fusion["format"],
                fusion.get("url") or "", float(fusion.get("prix") or 0), fusion.get("publie_le") or "")
    if fusion["type"] == "info":
        maj.pop("prix", None)
    if not maj:
        raise HTTPException(status_code=400, detail="Rien à modifier")
    if maj.get("publie") and fusion["type"] == "info" and not doc.get("diffusion") and await _diffusion_active():
        maj["diffusion"] = {"statut": "a_envoyer"}
    await db.settings.update_one({"_id": PREFIXE + contenu_id}, {"$set": maj})
    return _vue(await _lire(contenu_id), acces=True, gestion=True)


@router.delete("/{contenu_id}")
async def supprimer(contenu_id: str, user: dict = Depends(GESTION_DEP)):
    """Supprime le contenu et libère son espace de stockage."""
    doc = await _lire(contenu_id)
    for cle in ("fichier", "vignette"):
        if doc.get(cle):
            try:
                await delete_object(doc[cle]["path"])
            except Exception:  # noqa: BLE001
                logger.warning("Fichier %s non supprimé", doc[cle].get("path"))
    await db.settings.delete_one({"_id": PREFIXE + contenu_id})
    return {"ok": True}


class AccesIn(BaseModel):
    tenant_id: str


@router.post("/{contenu_id}/acces")
async def accorder_acces(contenu_id: str, p: AccesIn, user: dict = Depends(GESTION_DEP)):
    """Accorde l'accès à une formation payante à un client (paiement reçu hors PawaPay, geste commercial…)."""
    doc = await _lire(contenu_id)
    client = await db.users.find_one({"id": p.tenant_id, "roles": "client"}, {"_id": 0, "id": 1, "company": 1, "full_name": 1})
    if not client:
        raise HTTPException(status_code=404, detail="Client introuvable")
    now = datetime.now(timezone.utc).isoformat()
    await db.payment_links.insert_one({
        "id": secrets.token_urlsafe(12), "deposit_id": "manuel-" + secrets.token_urlsafe(8), "kind": "formation",
        "contenu_id": doc["id"], "tenant_id": p.tenant_id, "client_label": client.get("company") or client.get("full_name"),
        "created_by": user["id"], "amount": 0, "status": "completed", "api_status": "MANUEL", "created_at": now, "updated_at": now,
    })
    return {"ok": True}


# ----------------------------------------------------------------- leçons multiples (lot 55)
MAX_LECONS = 60


@router.post("/{contenu_id}/lecons")
async def ajouter_lecon(
    contenu_id: str, titre: str = Form(...), format: str = Form(...), url: str = Form(""),
    fichier: Optional[UploadFile] = File(None), user: dict = Depends(GESTION_DEP),
):
    """Ajoute une leçon (vidéo en lien, audio, PDF ou lien) à la fin du contenu."""
    doc = await _lire(contenu_id)
    if format not in ("video", "audio", "pdf", "lien"):
        raise HTTPException(status_code=400, detail="Format de leçon inconnu : choisissez dans la liste")
    if not titre.strip():
        raise HTTPException(status_code=400, detail="Titre de la leçon obligatoire")
    if len(doc.get("lecons") or []) >= MAX_LECONS:
        raise HTTPException(status_code=400, detail=f"{MAX_LECONS} leçons au plus")
    lecon: Dict[str, Any] = {"id": secrets.token_urlsafe(6), "titre": titre.strip()[:150], "format": format, "url": "", "fichier": None}
    if format in ("video", "lien"):
        lecon["url"] = _url_ok(url)
    else:
        if fichier is None or not fichier.filename:
            raise HTTPException(status_code=400, detail="Joignez le fichier de la leçon")
        lecon["fichier"] = await _stocker(fichier, extensions={"pdf"} if format == "pdf" else EXT_AUDIO,
                                          limite=MAX_PDF if format == "pdf" else MAX_AUDIO, kind="contenu")
    await db.settings.update_one({"_id": PREFIXE + contenu_id}, {"$push": {"lecons": lecon}})
    return _vue(await _lire(contenu_id), acces=True, gestion=True)


@router.delete("/{contenu_id}/lecons/{lecon_id}")
async def retirer_lecon(contenu_id: str, lecon_id: str, user: dict = Depends(GESTION_DEP)):
    """Retire une leçon et libère son fichier."""
    doc = await _lire(contenu_id)
    lecon = next((l for l in doc.get("lecons") or [] if l["id"] == lecon_id), None)
    if not lecon:
        raise HTTPException(status_code=404, detail="Leçon introuvable")
    if lecon.get("fichier"):
        try:
            await delete_object(lecon["fichier"]["path"])
        except Exception:  # noqa: BLE001
            logger.warning("Fichier de leçon non supprimé")
    await db.settings.update_one({"_id": PREFIXE + contenu_id}, {"$pull": {"lecons": {"id": lecon_id}}})
    return _vue(await _lire(contenu_id), acces=True, gestion=True)


@router.get("/{contenu_id}/lecons/{lecon_id}/fichier")
async def fichier_lecon(contenu_id: str, lecon_id: str, user: dict = Depends(get_current_user)):
    """PDF ou audio d'une leçon — même contrôle d'accès que le contenu."""
    doc = await _lire(contenu_id)
    if is_client(user) and not doc.get("publie"):
        raise HTTPException(status_code=404, detail="Contenu introuvable")
    if not await _a_acces(doc, user):
        raise HTTPException(status_code=402, detail="Formation payante : réglez-la pour y accéder")
    lecon = next((l for l in doc.get("lecons") or [] if l["id"] == lecon_id), None)
    if not lecon or not lecon.get("fichier"):
        raise HTTPException(status_code=404, detail="Fichier introuvable")
    data, ct = await get_object(lecon["fichier"]["path"])
    return Response(content=data, media_type=lecon["fichier"].get("content_type") or ct,
                    headers={"Content-Disposition": f'inline; filename="{lecon["fichier"].get("nom") or "lecon"}"'})


# ----------------------------------------------------------------- accès manuel (lot 55)
@router.get("/{contenu_id}/acces")
async def liste_acces(contenu_id: str, user: dict = Depends(GESTION_DEP)):
    """Clients ayant accès à la formation (achat PawaPay confirmé ou accès accordé par le cabinet)."""
    await _lire(contenu_id)
    achats = await db.payment_links.find({"kind": "formation", "contenu_id": contenu_id, "status": "completed"},
                                         {"_id": 0}).sort("created_at", -1).to_list(500)
    return [{"tenant_id": a["tenant_id"], "client": a.get("client_label") or a["tenant_id"],
             "source": "manuel" if a.get("api_status") == "MANUEL" else "paiement",
             "date": a.get("created_at"), "montant": a.get("amount") or 0} for a in achats]


@router.delete("/{contenu_id}/acces/{tenant_id}")
async def retirer_acces(contenu_id: str, tenant_id: str, user: dict = Depends(GESTION_DEP)):
    """Retire un accès accordé à la main (un achat payé par PawaPay ne se retire pas ici)."""
    res = await db.payment_links.update_many(
        {"kind": "formation", "contenu_id": contenu_id, "tenant_id": tenant_id, "status": "completed", "api_status": "MANUEL"},
        {"$set": {"status": "revoked", "updated_at": datetime.now(timezone.utc).isoformat()}})
    if not res.modified_count:
        raise HTTPException(status_code=404, detail="Aucun accès manuel à retirer pour ce client")
    return {"ok": True}


# ----------------------------------------------------------------- diffusion WhatsApp de l'info de la semaine (lot 55)
REGLAGES_ID = "contenus_reglages"
HEURE_DEBUT_UTC, HEURE_FIN_UTC = 7, 18          # jamais d'envoi de nuit (Burkina Faso = UTC)
PAUSE_ENVOI = 0.3                                # secondes entre deux messages
MODELE_PAR_DEFAUT = "message_cabinet"            # modèle Meta approuvé à 1 variable


async def _reglages() -> dict:
    d = await db.settings.find_one({"_id": REGLAGES_ID}) or {}
    return {"diffusion_wa": d.get("diffusion_wa", True), "modele": d.get("modele") or MODELE_PAR_DEFAUT}


async def _diffusion_active() -> bool:
    return bool((await _reglages())["diffusion_wa"])


class ReglagesIn(BaseModel):
    diffusion_wa: Optional[bool] = None
    modele: Optional[str] = None


@router.get("/admin/reglages")
async def lire_reglages(user: dict = Depends(GESTION_DEP)):
    return await _reglages()


@router.put("/admin/reglages")
async def ecrire_reglages(p: ReglagesIn, user: dict = Depends(GESTION_DEP)):
    """Active / coupe la diffusion WhatsApp automatique et règle le modèle Meta utilisé hors fenêtre de 24 h."""
    maj = {k: v for k, v in p.model_dump(exclude_none=True).items()}
    if "modele" in maj:
        maj["modele"] = maj["modele"].strip()[:80] or MODELE_PAR_DEFAUT
    if maj:
        await db.settings.update_one({"_id": REGLAGES_ID}, {"$set": maj}, upsert=True)
    return await _reglages()


@router.post("/{contenu_id}/diffuser")
async def rearmer_diffusion(contenu_id: str, user: dict = Depends(GESTION_DEP)):
    """Programme (ou reprogramme) l'envoi WhatsApp d'une info : il part au prochain passage du planificateur."""
    doc = await _lire(contenu_id)
    if doc.get("type") != "info" or not doc.get("publie"):
        raise HTTPException(status_code=400, detail="Seule une info publiée peut être diffusée")
    await db.settings.update_one({"_id": PREFIXE + contenu_id}, {"$set": {"diffusion": {"statut": "a_envoyer"}}})
    return {"ok": True}


async def _envoyer_wa(phone: str, texte: str, modele: str) -> dict:
    """Un message WhatsApp : libre si la fenêtre de 24 h est ouverte, sinon modèle Meta à 1 variable."""
    from albarka_notifications import send_whatsapp, send_whatsapp_template, wa_window_state
    if await wa_window_state(phone) is True:
        return await send_whatsapp(to_phone=phone, message=texte)
    return await send_whatsapp_template(to_phone=phone, template_name=modele, body_params=[texte], texte_rendu=texte)


def _message_diffusion(doc: dict, lien: str) -> str:
    return f"Info de la semaine : {doc['titre']}. Retrouvez-la dans votre espace : {lien}"


async def diffuser_infos_dues(maintenant: Optional[datetime] = None) -> Dict[str, int]:
    """Envoie par WhatsApp les infos publiées dont la date est arrivée et dont la diffusion est « à envoyer ».
    Appelée par le planificateur. Une info n'est jamais envoyée deux fois : elle est « réservée » (en_cours)
    avant l'envoi. Pas d'envoi la nuit. Message libre si la fenêtre de 24 h est ouverte, sinon modèle Meta."""
    maintenant = maintenant or datetime.now(timezone.utc)
    bilan = {"infos": 0, "envoyes": 0, "echecs": 0}
    if not (HEURE_DEBUT_UTC <= maintenant.hour < HEURE_FIN_UTC):
        return bilan
    reglages = await _reglages()
    if not reglages["diffusion_wa"]:
        return bilan
    aujourdhui = maintenant.strftime("%Y-%m-%d")
    dues = await db.settings.find({"_id": {"$regex": f"^{PREFIXE}"}, "type": "info", "publie": True,
                                   "publie_le": {"$lte": aujourdhui}, "diffusion.statut": "a_envoyer"}).to_list(20)
    if not dues:
        return bilan
    from albarka_client_space import DEFAULT_BASE_URL   # adresse du site
    lien = DEFAULT_BASE_URL + "/portal/infos"
    clients = await db.users.find({"roles": "client", "is_active": True, "is_test_account": {"$ne": True},
                                   "can_receive_notifications": {"$ne": False}}, {"_id": 0, "password_hash": 0}).to_list(2000)
    for doc in dues:
        # Réservation atomique : un seul passage du planificateur envoie cette info
        res = await db.settings.update_one({"_id": doc["_id"], "diffusion.statut": "a_envoyer"},
                                           {"$set": {"diffusion.statut": "en_cours"}})
        if not res.modified_count:
            continue
        bilan["infos"] += 1
        texte = _message_diffusion(doc, lien)
        ok = ko = 0
        for c in clients:
            phone = whatsapp_number_of(c) or ""
            if not phone.startswith("+"):
                continue
            try:
                r = await _envoyer_wa(phone, texte, reglages["modele"])
                ok, ko = (ok + 1, ko) if r.get("ok") else (ok, ko + 1)
            except Exception:  # noqa: BLE001 — un échec n'arrête pas la diffusion
                ko += 1
            await asyncio.sleep(PAUSE_ENVOI)                       # cadence douce, sans saturer WhatsApp
        bilan["envoyes"] += ok
        bilan["echecs"] += ko
        await db.settings.update_one({"_id": doc["_id"]}, {"$set": {"diffusion": {
            "statut": "envoyee", "envoyee_le": datetime.now(timezone.utc).isoformat(), "nb_envoyes": ok, "nb_echecs": ko}}})
    return bilan


# ----------------------------------------------------------------- ordre des leçons (lot 56)
class OrdreIn(BaseModel):
    ids: list


@router.put("/{contenu_id}/lecons-ordre")
async def ordonner_lecons(contenu_id: str, p: OrdreIn, user: dict = Depends(GESTION_DEP)):
    """Réordonne les leçons : `ids` doit contenir exactement les identifiants des leçons existantes."""
    doc = await _lire(contenu_id)
    lecons = doc.get("lecons") or []
    if sorted(p.ids) != sorted(l["id"] for l in lecons):
        raise HTTPException(status_code=400, detail="La liste doit contenir toutes les leçons, une seule fois chacune")
    par_id = {l["id"]: l for l in lecons}
    await db.settings.update_one({"_id": PREFIXE + contenu_id}, {"$set": {"lecons": [par_id[i] for i in p.ids]}})
    return _vue(await _lire(contenu_id), acces=True, gestion=True)


# ----------------------------------------------------------------- progression de lecture (lot 56)
# Un document `settings` par client et par contenu : _id « progression:<client>:<contenu> » (aucune nouvelle collection).
PREFIXE_PROG = "progression:"
PRINCIPAL = "principal"          # contenu sans leçons : une seule « étape »


async def _progressions_du_client(user: dict) -> Dict[str, dict]:
    """Toutes les progressions d'un client en une lecture, indexées par identifiant de contenu."""
    tid = tenant_id_of(user)
    docs = await db.settings.find({"_id": {"$regex": f"^{re.escape(PREFIXE_PROG + tid)}:"}}).to_list(1000)
    return {d["contenu_id"]: d for d in docs}


def _resume_progression(contenu: dict, prog: Optional[dict]) -> dict:
    """Étapes terminées / total, pourcentage et dernière étape consultée (étapes disparues ignorées)."""
    etapes = [l["id"] for l in contenu.get("lecons") or []] or [PRINCIPAL]
    faites = [e for e in (prog or {}).get("terminees", []) if e in etapes]
    return {"terminees": faites, "total": len(etapes), "pct": round(100 * len(faites) / len(etapes)),
            "derniere": (prog or {}).get("derniere")}


class ProgressionIn(BaseModel):
    lecon_id: Optional[str] = None       # None = le contenu lui-même (sans leçons)
    fait: Optional[bool] = None          # True / False : marquer terminée / non terminée ; None : simple consultation


@router.post("/{contenu_id}/progression")
async def enregistrer_progression(contenu_id: str, p: ProgressionIn, user: dict = Depends(get_current_user)):
    """Enregistre la consultation ou la fin d'une leçon pour le client connecté (accès requis)."""
    doc = await _lire(contenu_id)
    if not await _a_acces(doc, user):
        raise HTTPException(status_code=402, detail="Formation payante : réglez-la pour y accéder")
    etape = p.lecon_id or PRINCIPAL
    if etape not in ([l["id"] for l in doc.get("lecons") or []] or [PRINCIPAL]):
        raise HTTPException(status_code=404, detail="Leçon introuvable")
    _id = f"{PREFIXE_PROG}{tenant_id_of(user)}:{contenu_id}"
    maj: Dict[str, Any] = {"$set": {"contenu_id": contenu_id, "tenant_id": tenant_id_of(user), "derniere": etape,
                                    "maj": datetime.now(timezone.utc).isoformat()}}
    if p.fait is True:
        maj["$addToSet"] = {"terminees": etape}
    elif p.fait is False:
        maj["$pull"] = {"terminees": etape}
    await db.settings.update_one({"_id": _id}, maj, upsert=True)
    return _resume_progression(doc, await db.settings.find_one({"_id": _id}))


@router.get("/{contenu_id}/progression")
async def progression_clients(contenu_id: str, user: dict = Depends(GESTION_DEP)):
    """Cabinet : avancement de chaque client sur ce contenu (lecture en bloc, pas de boucle par client)."""
    doc = await _lire(contenu_id)
    progs = await db.settings.find({"_id": {"$regex": f"^{PREFIXE_PROG}"}, "contenu_id": contenu_id}).to_list(2000)
    users = await db.users.find({"id": {"$in": [p["tenant_id"] for p in progs]}},
                                {"_id": 0, "id": 1, "company": 1, "full_name": 1}).to_list(2000)
    noms = {u["id"]: u.get("company") or u.get("full_name") or u["id"] for u in users}
    sortie = []
    for p in progs:
        r = _resume_progression(doc, p)
        sortie.append({"tenant_id": p["tenant_id"], "client": noms.get(p["tenant_id"], p["tenant_id"]),
                       "terminees": len(r["terminees"]), "total": r["total"], "pct": r["pct"], "maj": p.get("maj")})
    sortie.sort(key=lambda x: (-x["pct"], x["client"]))
    return sortie


# ----------------------------------------------------------------- relance WhatsApp des formations payantes (lot 57)
CIBLES_RELANCE = ["non_achetes", "inacheves"]
DELAI_ENTRE_RELANCES_JOURS = 14          # un client n'est relancé qu'une fois par période pour une même formation
INACTIVITE_JOURS = 7                     # « inachevée » = pas d'activité depuis 7 jours et leçons restantes


class RelanceIn(BaseModel):
    cible: str
    simuler: bool = True                 # True : compte seulement, n'envoie rien


async def _destinataires_relance(doc: dict, cible: str, maintenant: datetime) -> Dict[str, Any]:
    """Clients à relancer (lecture en bloc) : éligibles WhatsApp, pas relancés récemment."""
    clients = await db.users.find({"roles": "client", "is_active": True, "is_test_account": {"$ne": True},
                                   "can_receive_notifications": {"$ne": False}}, {"_id": 0, "password_hash": 0}).to_list(2000)
    achats = {a["tenant_id"] for a in await db.payment_links.find(
        {"kind": "formation", "contenu_id": doc["id"], "status": "completed"}, {"_id": 0, "tenant_id": 1}).to_list(2000)}
    progs = {p["tenant_id"]: p for p in await db.settings.find(
        {"_id": {"$regex": f"^{PREFIXE_PROG}"}, "contenu_id": doc["id"]}).to_list(2000)}
    recents = {r["tenant_id"] for r in await db.settings.find(
        {"_id": {"$regex": "^relance:"}, "contenu_id": doc["id"], "cible": cible,
         "date": {"$gte": (maintenant - timedelta(days=DELAI_ENTRE_RELANCES_JOURS)).isoformat()}}).to_list(2000)}
    limite = (maintenant - timedelta(days=INACTIVITE_JOURS)).isoformat()
    sans_numero = deja = 0
    cibles = []
    for c in clients:
        if cible == "non_achetes" and c["id"] in achats:
            continue
        if cible == "inacheves":
            if c["id"] not in achats:
                continue
            resume = _resume_progression(doc, progs.get(c["id"]))
            if resume["pct"] >= 100 or ((progs.get(c["id"]) or {}).get("maj") or "") > limite:
                continue
        phone = whatsapp_number_of(c) or ""
        if not phone.startswith("+"):
            sans_numero += 1
        elif c["id"] in recents:
            deja += 1
        else:
            cibles.append((c["id"], phone))
    return {"cibles": cibles, "sans_numero": sans_numero, "deja_relances": deja}


async def _envoyer_relances(doc: dict, cible: str, cibles: list) -> None:
    """Envoi en arrière-plan (jamais dans la requête) ; chaque relance est notée pour ne pas la répéter."""
    from albarka_client_space import DEFAULT_BASE_URL
    lien = DEFAULT_BASE_URL + "/portal/formations"
    if cible == "non_achetes":
        texte = f"Formation « {doc['titre']} » ({int(doc.get('prix') or 0)} FCFA) : découvrez-la dans votre espace : {lien}"
    else:
        texte = f"Il vous reste des leçons à suivre dans la formation « {doc['titre']} ». Reprenez où vous en étiez : {lien}"
    modele = (await _reglages())["modele"]
    ok = ko = 0
    for tid, phone in cibles:
        try:
            r = await _envoyer_wa(phone, texte, modele)
            if r.get("ok"):
                ok += 1
                await db.settings.update_one({"_id": f"relance:{tid}:{doc['id']}:{cible}"}, {"$set": {
                    "tenant_id": tid, "contenu_id": doc["id"], "cible": cible,
                    "date": datetime.now(timezone.utc).isoformat()}}, upsert=True)
            else:
                ko += 1
        except Exception:  # noqa: BLE001
            ko += 1
        await asyncio.sleep(PAUSE_ENVOI)
    await db.settings.update_one({"_id": PREFIXE + doc["id"]}, {"$set": {"derniere_relance": {
        "cible": cible, "date": datetime.now(timezone.utc).isoformat(), "nb_envoyes": ok, "nb_echecs": ko}}})


@router.post("/{contenu_id}/relance")
async def relancer(contenu_id: str, p: RelanceIn, user: dict = Depends(GESTION_DEP)):
    """Relance WhatsApp d'une formation payante. `simuler` (par défaut) compte les destinataires sans rien envoyer."""
    doc = await _lire(contenu_id)
    if doc.get("type") != "formation" or float(doc.get("prix") or 0) <= 0 or not doc.get("publie"):
        raise HTTPException(status_code=400, detail="Seule une formation payante publiée peut être relancée")
    if p.cible not in CIBLES_RELANCE:
        raise HTTPException(status_code=400, detail="Cible inconnue : choisissez dans la liste")
    res = await _destinataires_relance(doc, p.cible, datetime.now(timezone.utc))
    sortie = {"destinataires": len(res["cibles"]), "sans_numero": res["sans_numero"], "deja_relances": res["deja_relances"]}
    if not p.simuler and res["cibles"]:
        asyncio.create_task(_envoyer_relances(doc, p.cible, res["cibles"]))
        sortie["programme"] = True
    return sortie
