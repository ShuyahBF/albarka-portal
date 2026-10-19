"""Lot 41 — envoi d'un PDF de paie au responsable de la société (WhatsApp ou e-mail).
Tests unitaires (base simulée, envois simulés) : aucun appel réseau."""
import asyncio
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("MONGO_URL", "mongodb://localhost:1")
os.environ.setdefault("DB_NAME", "albarka_test_lot41")
os.environ.setdefault("JWT_SECRET_KEY", "cle-de-test-lot41")
mongomock_motor = pytest.importorskip("mongomock_motor")

from fastapi import HTTPException  # noqa: E402

import albarka_paie as paie  # noqa: E402
import albarka_wa_inbox as inbox  # noqa: E402


def _base(monkeypatch):
    """Base simulée avec une société cliente et son responsable ; envois WhatsApp / e-mail simulés."""
    db = mongomock_motor.AsyncMongoMockClient()["test"]
    monkeypatch.setattr(paie, "db", db)
    monkeypatch.setattr(inbox, "db", db)
    asyncio.run(db.users.insert_one({"id": "c1", "roles": ["client"], "company": "Société Test", "full_name": "Mme Responsable",
                                     "email": "resp@test.bf", "whatsapp_number": "70 11 22 33"}))
    envois = []

    async def faux_fichier(**kw):
        envois.append(("wa", kw["to_phone"], kw["filename"]))
        return {"ok": True, "message_id": "wamid.X"}

    async def faux_email(**kw):
        envois.append(("email", kw["to"], kw["attachments"][0]["filename"]))
        return "mail-1"
    import albarka_notifications as notif
    monkeypatch.setattr(notif, "send_whatsapp_fichier", faux_fichier)
    monkeypatch.setattr(notif, "send_email", faux_email)
    return db, envois


def test_le_responsable_est_lu_sur_la_fiche_de_la_societe(monkeypatch):
    _base(monkeypatch)
    r = asyncio.run(paie._responsable("c1"))
    assert r["nom"] == "Mme Responsable" and r["whatsapp"] == "+22670112233" and r["email"] == "resp@test.bf"


def test_envoi_par_email_au_responsable(monkeypatch):
    _, envois = _base(monkeypatch)
    res = asyncio.run(paie._envoyer_pdf_responsable("c1", b"%PDF", "b.pdf", "Bulletin", paie.EnvoiPaieIn(canal="email")))
    assert res["ok"] and res["to"] == "resp@test.bf" and envois == [("email", ["resp@test.bf"], "b.pdf")]


def test_envoi_whatsapp_hors_fenetre_demande_l_accord_puis_part(monkeypatch):
    _, envois = _base(monkeypatch)
    # Contact jamais venu : fenêtre de 24 h fermée → 409 sans accord, rien d'envoyé
    with pytest.raises(HTTPException) as e:
        asyncio.run(paie._envoyer_pdf_responsable("c1", b"%PDF", "b.pdf", "Bulletin", paie.EnvoiPaieIn(canal="whatsapp")))
    assert e.value.status_code == 409 and e.value.detail["code"] == "hors_fenetre_24h" and envois == []
    # Avec l'accord du cabinet → envoyé au numéro du responsable
    res = asyncio.run(paie._envoyer_pdf_responsable("c1", b"%PDF", "b.pdf", "Bulletin",
                                                    paie.EnvoiPaieIn(canal="whatsapp", confirmer_modele=True)))
    assert res["ok"] and envois == [("wa", "+22670112233", "b.pdf")]


def test_sans_adresse_ou_numero_message_clair(monkeypatch):
    db, _ = _base(monkeypatch)
    asyncio.run(db.users.update_one({"id": "c1"}, {"$set": {"email": "", "whatsapp_number": "", "phone": ""}}))
    with pytest.raises(HTTPException) as e:
        asyncio.run(paie._envoyer_pdf_responsable("c1", b"%PDF", "b.pdf", "B", paie.EnvoiPaieIn(canal="email")))
    assert e.value.status_code == 400 and "e-mail" in e.value.detail
    with pytest.raises(HTTPException) as e:
        asyncio.run(paie._envoyer_pdf_responsable("c1", b"%PDF", "b.pdf", "B", paie.EnvoiPaieIn(canal="whatsapp")))
    assert e.value.status_code == 400 and "WhatsApp" in e.value.detail
