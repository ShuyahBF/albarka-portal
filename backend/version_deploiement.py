"""Lot 13 — numéro de version « 1.N » (affiché « Version 1.N · déployée le … »).

N = compteur de déploiements : chaque nouveau commit déployé reçoit le numéro
suivant, une seule fois (fiche `commit:<sha>`) (commit donné par Render dans RENDER_GIT_COMMIT,
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
    """Numéro de déploiement du commit en cours, attribué UNE SEULE FOIS par commit.

    Pendant un déploiement Render, l'ancienne et la nouvelle instance tournent un
    moment ensemble : l'ancienne méthode (comparer au « dernier commit ») faisait
    alors grimper le compteur à chaque appel de /api/version (1.6 -> 1.9).
    Désormais chaque commit a sa fiche `commit:<sha>` avec son numéro définitif ;
    un nouveau commit prend le numéro suivant (incrément atomique du compteur).
    """
    sha = commit_deploye()
    cle = f"commit:{sha}"
    fiche = await db.app_deploiements.find_one({"_id": cle})
    if fiche:
        return fiche
    # Reprise de l'ancien format : le commit déjà noté dans « compteur » garde son numéro
    ancien = await db.app_deploiements.find_one({"_id": "compteur"}) or {}
    if ancien.get("git_head") == sha and ancien.get("seq"):
        fiche = {"_id": cle, "seq": int(ancien["seq"]), "git_head": sha,
                 "deployed_at": ancien.get("deployed_at") or datetime.now(timezone.utc).isoformat()}
        try:
            await db.app_deploiements.insert_one(fiche)
        except Exception:  # noqa: BLE001
            fiche = await db.app_deploiements.find_one({"_id": cle}) or fiche
        return fiche
    # Nouveau commit : numéro suivant du compteur général (jamais de retour en arrière)
    compteur = await db.app_deploiements.find_one_and_update(
        {"_id": "compteur"}, {"$inc": {"seq": 1}}, upsert=True, return_document=True)
    if not isinstance(compteur, dict) or "seq" not in compteur:
        compteur = await db.app_deploiements.find_one({"_id": "compteur"}) or {"seq": 1}
    fiche = {"_id": cle, "seq": int(compteur["seq"]), "git_head": sha,
             "deployed_at": datetime.now(timezone.utc).isoformat()}
    try:
        await db.app_deploiements.insert_one(fiche)
    except Exception:  # noqa: BLE001 — deux instances en même temps : la première fiche gagne
        fiche = await db.app_deploiements.find_one({"_id": cle}) or fiche
    return fiche


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
