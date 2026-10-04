"""Lot 13 — numéro de version affiché « Version 1.N · Lot L (commit) ».

N = compteur de déploiements : +1 chaque fois que le serveur démarre sur un
commit différent du précédent (commit donné par Render dans RENDER_GIT_COMMIT,
sinon lu dans .git). Le compteur est gardé dans MongoDB (collection
`app_deploiements`, document « compteur ») : il survit aux redémarrages et ne
change pas tant que le code déployé reste le même.
"""
from __future__ import annotations

import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import lot as _lot


def commit_deploye() -> str:
    """Hash du commit déployé (Render : RENDER_GIT_COMMIT ; sinon git ; sinon « inconnu »)."""
    sha = (os.environ.get("RENDER_GIT_COMMIT") or "").strip()
    if sha:
        return sha
    try:
        racine = Path(__file__).resolve().parent.parent
        return subprocess.run(["git", "-C", str(racine), "rev-parse", "HEAD"], capture_output=True,
                              text=True, timeout=5).stdout.strip() or "inconnu"
    except Exception:  # noqa: BLE001
        return "inconnu"


async def compteur_deploiements(db) -> dict:
    """Incrémente le compteur si le commit a changé depuis le dernier démarrage ; renvoie l'état."""
    sha = commit_deploye()
    doc = await db.app_deploiements.find_one({"_id": "compteur"}) or {}
    if doc.get("git_head") != sha:
        doc = {"_id": "compteur", "seq": int(doc.get("seq") or 0) + 1, "git_head": sha,
               "deployed_at": datetime.now(timezone.utc).isoformat()}
        await db.app_deploiements.replace_one({"_id": "compteur"}, doc, upsert=True)
    return doc


async def infos_version(db) -> dict:
    """Réponse de GET /api/version (aucun secret)."""
    etat = await compteur_deploiements(db)
    base = (os.environ.get("APP_VERSION") or "1").strip() or "1"
    seq = int(etat.get("seq") or 0)
    return {
        "version": f"{base}.{seq}",
        "git_sha": (etat.get("git_head") or "")[:7],
        "deploy_seq": seq,
        "deployed_at": etat.get("deployed_at"),
        "lot": _lot.LOT,
        "lot_libelle": _lot.LOT_LIBELLE,
    }
