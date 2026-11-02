"""Lot 84 — PDF d'archivage des réponses aux formulaires (albarka_forms_pdf.py).
Tests autonomes : MongoDB simulé (mongomock-motor), aucun réseau."""
from __future__ import annotations

import asyncio
import os
import struct
import sys
import zlib
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")
fitz = pytest.importorskip("fitz")
pytest.importorskip("reportlab")

import albarka_forms as af  # noqa: E402
import albarka_forms_pdf as afp  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "form": {"id": "u-form", "full_name": "Awa Formulaires", "roles": ["formulaires"], "is_active": True},
    "compta": {"id": "u-compta", "full_name": "Comptable seul", "roles": ["comptable"], "is_active": True},
}


def _png() -> bytes:
    """Petite image PNG valide (2×2 px, noire) pour simuler une signature."""
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + b"\x00\x00\x00" * 2 for _ in range(2))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


PAGES = [
    {"id": "p1", "title": "Identité", "fields": [
        {"id": "intro", "type": "section", "label": "Bienvenue au cabinet", "help": "Merci de remplir ce questionnaire."},
        {"id": "nom", "type": "text", "label": "Nom et prénoms", "required": True},
        {"id": "statut", "type": "radio", "label": "Statut juridique", "options": ["SARL", "SA", "Entreprise individuelle"]},
        {"id": "outils", "type": "checkbox", "label": "Outils utilisés", "options": ["Excel", "Sage", "Autre logiciel"]},
        {"id": "tva", "type": "boolean", "label": "Assujetti à la TVA ?"},
        {"id": "tva_num", "type": "text", "label": "Numéro de TVA", "show_if": {"field": "tva", "equals": "oui"}},
    ]},
    {"id": "p2", "title": "Activité", "fields": [
        {"id": "note", "type": "rating", "label": "Satisfaction", "max": 5},
        {"id": "clients", "type": "table", "label": "Principaux clients", "columns": [
            {"key": "c1", "label": "Client", "type": "text"}, {"key": "c2", "label": "CA", "type": "number"}]},
        {"id": "sign", "type": "signature", "label": "Signature"},
    ]},
]


@pytest.fixture()
def env(monkeypatch):
    db = mongomock_motor.AsyncMongoMockClient()["albarka_forms_pdf_test"]
    adapter = af.AlbarkaFormsAdapter(db)
    monkeypatch.setattr(afp, "adapter", adapter)
    stockage = {"sig1": _png()}

    async def fake_read(file_id):                               # signature relue du stockage (doublure)
        return (stockage[file_id], "image/png") if file_id in stockage else None
    monkeypatch.setattr(adapter, "read_file", fake_read)

    scope = adapter.scope_of(USERS["form"])
    asyncio.run(adapter.col("").insert_one({"id": "f1", "scope": scope, "number": "FORM-ALBARKA-0001", "title": "Dossier d'entrée client",
                                            "description": "Questionnaire d'accueil", "pages": PAGES, "archived_at": None}))
    asyncio.run(adapter.col("").insert_one({"id": "autre", "scope": "un-autre-cabinet", "number": "FORM-X", "title": "Autre", "pages": []}))
    asyncio.run(adapter.col("submissions").insert_many([
        {"id": "s1", "form_id": "f1", "created_at": "2026-10-01T09:00:00+00:00", "source": "invitation",
         "respondent_name": "KABORÉ Awa", "respondent_email": "awa@exemple.bf",
         "data": {"nom": "KABORÉ Awa", "statut": "SARL", "outils": ["Excel", "Autre logiciel"], "tva": True, "tva_num": "TVA-778",
                  "note": 4, "clients": [{"c1": "Pharmacie Soleil", "c2": 1500000}], "sign": {"file_id": "sig1"}}},
        {"id": "s2", "form_id": "f1", "created_at": "2026-10-15T10:30:00+00:00", "source": "public",
         "respondent_name": "OUEDRAOGO Paul", "data": {"nom": "OUEDRAOGO Paul", "statut": "SA", "tva": False, "tva_num": "NE-DOIT-PAS-APPARAITRE"}},
    ]))
    app = FastAPI()
    api = APIRouter(prefix="/api")
    api.include_router(afp.router)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return USERS[x_user]
    app.dependency_overrides[get_current_user] = fake_user
    with TestClient(app) as client:
        yield client


def _texte(content: bytes) -> str:
    with fitz.open("pdf", content) as d:
        return " ".join(" ".join(p.get_text() for p in d).split())


def test_pdf_de_toutes_les_reponses_suit_la_structure_du_formulaire(env):
    r = env.get("/api/forms/f1/submissions/pdf", headers={"X-User": "form"})
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert "FORM-ALBARKA-0001-reponses.pdf" in r.headers["content-disposition"]
    t = _texte(r.content)
    # Titre, pages, section, questions dans l'ordre, choix avec cases cochées, tableau, valeurs
    for needle in ("Dossier d'entrée client", "Réponse 1 sur 2", "Réponse 2 sur 2", "Identité", "Activité", "Bienvenue au cabinet",
                   "Merci de remplir ce questionnaire.", "Nom et prénoms *", "[X] SARL", "[ ] SA", "[ ] Entreprise individuelle",
                   "[X] Excel", "[ ] Sage", "[X] Autre logiciel", "[X] Oui", "[ ] Non", "TVA-778", "4 / 5", "Principaux clients",
                   "Pharmacie Soleil", "1500000", "KABORÉ Awa", "awa@exemple.bf", "Origine : Invitation", "Origine : Lien public", "Non renseigné"):
        assert needle in t, needle
    # Ordre des questions : le statut vient après le nom
    assert t.index("Nom et prénoms") < t.index("Statut juridique") < t.index("Outils utilisés")
    # Champ conditionnel : masqué quand la condition n'est pas remplie (réponse 2 : TVA = Non)
    assert "NE-DOIT-PAS-APPARAITRE" not in t
    # Une réponse commence sur sa propre page (2 réponses → au moins 2 pages)
    with fitz.open("pdf", r.content) as d:
        assert d.page_count >= 2


def test_pdf_dune_seule_reponse_et_signature_reproduite(env):
    r = env.get("/api/forms/f1/submissions/s1/pdf", headers={"X-User": "form"})
    assert r.status_code == 200
    t = _texte(r.content)
    assert "Réponse 1 sur 1" in t and "OUEDRAOGO" not in t
    with fitz.open("pdf", r.content) as d:
        assert sum(len(p.get_images()) for p in d) >= 1              # l'image de la signature est dans le PDF


def test_filtre_par_periode_et_erreurs(env):
    h = {"X-User": "form"}
    r = env.get("/api/forms/f1/submissions/pdf?date_from=2026-10-10", headers=h)
    assert "OUEDRAOGO" in _texte(r.content) and "Réponse 1 sur 1" in _texte(r.content)
    assert env.get("/api/forms/f1/submissions/pdf?date_from=2027-01-01", headers=h).status_code == 404
    assert env.get("/api/forms/f1/submissions/inconnue/pdf", headers=h).status_code == 404
    assert env.get("/api/forms/autre/submissions/pdf", headers=h).status_code == 404     # formulaire d'un autre espace
    assert env.get("/api/forms/f1/submissions/pdf", headers={"X-User": "compta"}).status_code == 403   # réservé au rôle formulaires
    assert env.get("/api/forms/f1/submissions/pdf").status_code == 401


def test_caracteres_hors_police_ne_font_pas_echouer_le_pdf(env):
    asyncio.run(afp.adapter.col("submissions").insert_one(
        {"id": "s3", "form_id": "f1", "created_at": "2026-10-20T08:00:00+00:00", "source": "public", "respondent_name": "Test 😀 <b>gras</b>",
         "data": {"nom": "Émoji 😀 & <script> « guillemets » €"}}))
    r = env.get("/api/forms/f1/submissions/s3/pdf", headers={"X-User": "form"})
    assert r.status_code == 200 and "<script>" in _texte(r.content)         # affiché tel quel, jamais interprété
