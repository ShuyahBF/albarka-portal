"""Lot 13 (migration Render) — sauvegarde quotidienne de la base dans Cloudflare R2.

Comme pour SAWALI : chaque jour (02h00 UTC, par le planificateur interne), toute
la base MongoDB est exportée en JSON (types MongoDB conservés : dates, ObjectId…),
compressée (gzip) puis CHIFFRÉE (Fernet, clé dérivée de SAUVEGARDE_AUTO_PHRASE, sinon
de SAUVEGARDE_PHRASE, sinon de JWT_SECRET_KEY) et déposée dans R2 :
    albarka/sauvegardes/AAAA-MM-JJ.json.gz.chiffre

Variables : MÊMES NOMS QUE SAWALI (le propriétaire recopie les mêmes valeurs) :
    R2_SAUVEGARDES_ACCOUNT_ID, R2_SAUVEGARDES_ACCESS_KEY_ID,
    R2_SAUVEGARDES_SECRET_ACCESS_KEY, R2_SAUVEGARDES_BUCKET (sawali-sauvegardes
    par défaut), R2_SAUVEGARDES_PREFIXE (albarka/sauvegardes/ par défaut : les
    sauvegardes d'ALBARKA ne se mélangent jamais à celles de SAWALI).
Sans ces variables, la sauvegarde va dans le bucket des fichiers (R2_ENDPOINT…).
Les 30 dernières sont gardées, les plus anciennes supprimées.

Routes (superviseur / direction) :
    GET  /api/_admin/sauvegardes           liste et date de la dernière sauvegarde
    POST /api/_admin/sauvegardes/maintenant lancer une sauvegarde tout de suite
La restauration se fait avec `restaurer_depuis_octets` (outil d'administration),
jamais automatiquement.
"""
from __future__ import annotations

import base64
import gzip
import hashlib
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from bson import json_util
from fastapi import APIRouter, Depends, HTTPException

from albarka_auth import require_roles

logger = logging.getLogger("albarka.sauvegarde")

router = APIRouter(prefix="/_admin/sauvegardes", tags=["Sauvegardes (lot 13)"])

PREFIXE_PAR_DEFAUT = "albarka/sauvegardes/"
BUCKET_SAUVEGARDES_PAR_DEFAUT = "sawali-sauvegardes"   # comme SAWALI
CONSERVATION = 30                 # nombre de sauvegardes gardées dans R2
HEURE_SAUVEGARDE_UTC = 2          # sauvegarde quotidienne à 02h00 UTC
COLLECTIONS_IGNOREES = {"otps"}   # codes de connexion temporaires : inutiles à sauvegarder


def _fernet():
    """Chiffrement : clé Fernet dérivée de la phrase.
    Ordre : SAUVEGARDE_AUTO_PHRASE (nom SAWALI), puis SAUVEGARDE_PHRASE, puis JWT_SECRET_KEY."""
    from cryptography.fernet import Fernet
    phrase = (os.environ.get("SAUVEGARDE_AUTO_PHRASE") or os.environ.get("SAUVEGARDE_PHRASE")
              or os.environ.get("JWT_SECRET_KEY") or "")
    if not phrase:
        raise RuntimeError("SAUVEGARDE_AUTO_PHRASE (ou JWT_SECRET_KEY) absente : sauvegarde impossible")
    cle = base64.urlsafe_b64encode(hashlib.sha256(("albarka-sauvegarde:" + phrase).encode("utf-8")).digest())
    return Fernet(cle)


async def exporter_base(db) -> bytes:
    """Toutes les collections -> JSON étendu MongoDB -> gzip -> chiffré."""
    contenu: Dict[str, List[Any]] = {}
    for nom in sorted(await db.list_collection_names()):
        if nom in COLLECTIONS_IGNOREES or nom.startswith("system."):
            continue
        contenu[nom] = await db[nom].find({}).to_list(None)
    brut = json_util.dumps({"date": datetime.now(timezone.utc), "collections": contenu}).encode("utf-8")
    return _fernet().encrypt(gzip.compress(brut))


def lire_sauvegarde(octets: bytes) -> Dict[str, Any]:
    """Déchiffre et relit une sauvegarde (pour une restauration manuelle ou un contrôle)."""
    return json_util.loads(gzip.decompress(_fernet().decrypt(octets)).decode("utf-8"))


async def restaurer_depuis_octets(db, octets: bytes) -> Dict[str, int]:
    """Remplace le contenu des collections par celui de la sauvegarde (action manuelle)."""
    donnees = lire_sauvegarde(octets)
    bilan = {}
    for nom, docs in donnees["collections"].items():
        await db[nom].delete_many({})
        if docs:
            await db[nom].insert_many(docs)
        bilan[nom] = len(docs)
    return bilan


def prefixe_r2() -> str:
    """Dossier des sauvegardes dans le bucket (R2_SAUVEGARDES_PREFIXE, sinon albarka/sauvegardes/)."""
    prefixe = (os.environ.get("R2_SAUVEGARDES_PREFIXE") or PREFIXE_PAR_DEFAUT).strip().strip("/")
    return prefixe + "/"


def _r2():
    """Client R2 et bucket des sauvegardes.
    1) Variables R2_SAUVEGARDES_* (mêmes noms et mêmes valeurs que SAWALI) ;
    2) sinon, le bucket des fichiers du portail (R2_ENDPOINT, R2_ACCESS_KEY_ID…)."""
    compte = os.environ.get("R2_SAUVEGARDES_ACCOUNT_ID")
    cle = os.environ.get("R2_SAUVEGARDES_ACCESS_KEY_ID")
    secret = os.environ.get("R2_SAUVEGARDES_SECRET_ACCESS_KEY")
    if compte and cle and secret:
        import boto3
        from botocore.client import Config
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{compte}.r2.cloudflarestorage.com",
            aws_access_key_id=cle,
            aws_secret_access_key=secret,
            config=Config(signature_version="s3v4"),
            region_name="auto",
        )
        return client, os.environ.get("R2_SAUVEGARDES_BUCKET") or BUCKET_SAUVEGARDES_PAR_DEFAUT
    # Repli : bucket des fichiers du portail
    from albarka_storage import _get_r2_client, _r2_configured
    if not _r2_configured():
        raise RuntimeError("R2 non configuré (ni R2_SAUVEGARDES_*, ni R2_ENDPOINT…) : sauvegarde impossible")
    return _get_r2_client(), os.environ["R2_BUCKET_NAME"]


def _lister_sync() -> List[Dict[str, Any]]:
    client, bucket = _r2()
    rep = client.list_objects_v2(Bucket=bucket, Prefix=prefixe_r2())
    objets = [{"cle": o["Key"], "taille": o["Size"], "date": o["LastModified"].isoformat()} for o in rep.get("Contents", [])]
    return sorted(objets, key=lambda o: o["cle"], reverse=True)


async def sauvegarder_maintenant(db) -> Dict[str, Any]:
    """Exporte la base, dépose la sauvegarde dans R2, supprime les plus anciennes."""
    import asyncio
    octets = await exporter_base(db)
    cle = f"{prefixe_r2()}{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.json.gz.chiffre"
    client, bucket = _r2()
    await asyncio.to_thread(client.put_object, Bucket=bucket, Key=cle, Body=octets, ContentType="application/octet-stream")
    # Rotation : on ne garde que les CONSERVATION plus récentes
    anciennes = (await asyncio.to_thread(_lister_sync))[CONSERVATION:]
    for o in anciennes:
        await asyncio.to_thread(client.delete_object, Bucket=bucket, Key=o["cle"])
    await db.sauvegardes_journal.insert_one({"cle": cle, "taille": len(octets), "date": datetime.now(timezone.utc).isoformat(), "statut": "ok"})
    logger.info("Sauvegarde déposée : %s (%d octets)", cle, len(octets))
    return {"cle": cle, "taille": len(octets)}


async def sauvegarde_du_jour(db, maintenant: datetime) -> bool:
    """Appelée chaque minute par le planificateur : une sauvegarde par jour, à partir de 02h00 UTC."""
    if maintenant.hour < HEURE_SAUVEGARDE_UTC:
        return False
    run_id = f"planif-sauvegarde-{maintenant.date().isoformat()}"
    if await db.cron_runs.find_one({"run_id": run_id}):
        return False
    await db.cron_runs.insert_one({"run_id": run_id, "job": "sauvegarde", "received_at": maintenant.isoformat()})
    try:
        await sauvegarder_maintenant(db)
    except Exception as exc:  # noqa: BLE001
        await db.sauvegardes_journal.insert_one({"date": maintenant.isoformat(), "statut": "erreur", "erreur": str(exc)[:300]})
        raise
    return True


@router.get("")
async def lister_sauvegardes(user: dict = Depends(require_roles(["superviseur", "direction"]))):
    """Sauvegardes présentes dans R2 et date de la dernière réussie."""
    import asyncio
    from db import db
    derniere = await db.sauvegardes_journal.find_one({"statut": "ok"}, {"_id": 0}, sort=[("date", -1)])
    try:
        objets = await asyncio.to_thread(_lister_sync)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)[:200])
    return {"derniere_reussie": derniere, "sauvegardes": objets}


@router.post("/maintenant")
async def lancer_sauvegarde(user: dict = Depends(require_roles(["superviseur", "direction"]))):
    """Sauvegarde immédiate (par exemple juste après la migration)."""
    from db import db
    try:
        return await sauvegarder_maintenant(db)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=str(exc)[:200])
