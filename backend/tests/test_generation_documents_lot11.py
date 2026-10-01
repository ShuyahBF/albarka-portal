"""Lot 11 — génération de documents depuis un modèle (« Documents & modèles »).

Incident du 01/10/2026 : modèle « Avis de mission », 2 destinataires, papier
à en-tête « Celui du modèle » -> « Request failed with status code 500 ».
Cause reproduite : l'image du papier à en-tête par défaut en WEBP (format
accepté au chargement) que le moteur PDF (PyMuPDF) ne sait pas lire
(« unknown image file format »). Sont aussi couverts : image absente du
stockage ou illisible, papier du modèle supprimé, image d'en-tête plus haute
que la page, texte avec accents / apostrophes typographiques / « & » / « < »,
date JJ/MM/AAAA, erreurs lisibles (422 / 503) au lieu d'une erreur 500.
Tests autonomes : MongoDB simulé (mongomock-motor), stockage local temporaire.
"""
from __future__ import annotations

import asyncio
import io
import os
import sys
from pathlib import Path
from urllib.parse import unquote

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest
from fastapi import APIRouter, FastAPI, Header, HTTPException
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

mongomock_motor = pytest.importorskip("mongomock_motor")
fitz = pytest.importorskip("fitz")
Image = pytest.importorskip("PIL.Image")

import db as db_module  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_letters  # noqa: E402
import albarka_storage  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "dir": {"id": "u-dir", "email": "dg@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "c1": {"id": "c1", "email": "ct1@exemple.bf", "full_name": "Client Test 1", "roles": ["client"], "is_active": True},
    "c2": {"id": "c2", "email": "ct2@exemple.bf", "full_name": "Client Test 2", "roles": ["client"], "is_active": True},
}


# ---------------------------------------------------------------- images de test
def _img(fmt: str, mode: str = "RGB", size=(1240, 200), **kw) -> bytes:
    """Image unie au format demandé (bandeau d'en-tête par défaut)."""
    colors = {"RGB": (20, 90, 160), "RGBA": (20, 90, 160, 120), "LA": (90, 120), "L": 90, "P": 3,
              "CMYK": (80, 20, 0, 10), "I;16": 30000}
    im = Image.new(mode, size, colors[mode])
    if mode == "P":
        kw.setdefault("transparency", 0)
    buf = io.BytesIO()
    im.save(buf, format=fmt, **kw)
    return buf.getvalue()


FORMATS = {
    "webp": lambda: _img("WEBP"),
    "webp_transparent": lambda: _img("WEBP", "RGBA"),
    "png": lambda: _img("PNG"),
    "jpeg": lambda: _img("JPEG"),
    "png_rgba": lambda: _img("PNG", "RGBA"),
    "png_palette": lambda: _img("PNG", "P"),
    "png_la": lambda: _img("PNG", "LA"),
    "jpeg_cmyk": lambda: _img("JPEG", "CMYK"),
    "png_16bits": lambda: _img("PNG", "I;16"),
    "tres_grande": lambda: _img("PNG", size=(6000, 900)),
}


# ---------------------------------------------------------------- environnement
@pytest.fixture()
def env(monkeypatch, tmp_path):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot11_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_storage, "UPLOAD_DIR", tmp_path)
    asyncio.run(mock_db.users.insert_many([dict(u) for u in USERS.values()]))

    app = FastAPI()
    api = APIRouter(prefix="/api")
    for r in (albarka_docgen.router, albarka_docgen.public_router, albarka_letters.router):
        api.include_router(r)
    app.include_router(api)

    async def fake_user(x_user: str = Header(default="")):
        if x_user not in USERS:
            raise HTTPException(status_code=401, detail="Non connecté")
        return await mock_db.users.find_one({"id": USERS[x_user]["id"]}, {"_id": 0})
    app.dependency_overrides[get_current_user] = fake_user
    asyncio.run(albarka_letters.ensure_letters_setup())
    # raise_server_exceptions=False : une erreur non gérée donne une vraie 500,
    # comme en production (et non une exception dans le test)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _h(u):
    return {"X-User": u}


def _default_letterhead(env, header: bytes | None, footer: bytes | None = None, ext: str = "webp",
                        store: bool = True, lh_id: str = "lh-gesp") -> str:
    """Papier « par défaut » enregistré tel qu'en production (fichiers déjà
    stockés, sans passer par le chargement qui convertit désormais en PNG)."""
    doc = {"id": lh_id, "name": "GESPHARM", "is_default": True, "top_margin_cm": 4.8, "bottom_margin_cm": 2.0,
           "header_path": None, "footer_path": None}
    for part, data in (("header", header), ("footer", footer)):
        if data is None:
            continue
        path = f"albarka/cabinet/letterheads/{lh_id}_{part}.{ext}"
        if store:
            asyncio.run(albarka_storage.put_object(path, data, f"image/{ext}"))
        doc[f"{part}_path"] = path
    asyncio.run(env.db.letterheads.insert_one(doc))
    return lh_id


def _avis(env) -> dict:
    tpls = env.c.get("/api/letters/templates", headers=_h("secr")).json()
    return next(t for t in tpls if t["name"] == "Avis de mission")


# La saisie exacte de l'incident du 01/10/2026
def _prod_payload(**over) -> dict:
    per = {"destinataire_titre": "Pharmacien Gérant", "ville_destinataire": "OUAGADOUGOU",
           "civilite": "Docteur", "civilite_min": "docteur"}
    out = {"tenant_ids": ["c1", "c2"], "doc_date": "2026-10-01", "letterhead_id": None, "mission_id": None,
           "deposit": False, "notify": False,
           "common_values": {"objet_mission": "traitement des dossiers ressources humaines de vos entreprises",
                             "periode_mission": "du mardi 18 au vendredi 21 août 2026"},
           "recipient_values": {"c1": dict(per), "c2": dict(per)}}
    out.update(over)
    return out


def _pdf(data: bytes):
    d = fitz.open("pdf", data)
    text = " ".join(" ".join(p.get_text() for p in d).split())
    images = sum(len(p.get_images()) for p in d)
    pages = d.page_count
    d.close()
    return text, images, pages


# ---------------------------------------------------------------- normalisation des images
@pytest.mark.parametrize("name", list(FORMATS))
def test_normalize_image_gives_png_or_jpeg(name):
    data, ct = albarka_docgen.normalize_image(FORMATS[name]())
    im = Image.open(io.BytesIO(data))
    assert im.format in ("PNG", "JPEG") and ct in ("image/png", "image/jpeg")
    assert im.mode in ("RGB", "RGBA", "L") and im.width <= 2480
    # PyMuPDF sait l'insérer (c'était l'échec du WEBP)
    doc = fitz.open()
    doc.new_page().insert_image(fitz.Rect(0, 0, 595, 100), stream=data)
    doc.close()


def test_normalize_image_rejects_garbage():
    for bad in (b"", b"pas une image", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40):
        with pytest.raises(albarka_docgen.ImageIllisible):
            albarka_docgen.normalize_image(bad)


# ---------------------------------------------------------------- l'incident lui-même
@pytest.mark.parametrize("name", list(FORMATS))
def test_generate_avis_de_mission_celui_du_modele(env, name):
    """« Celui du modèle » (modèle sans papier -> papier par défaut) avec une
    image d'en-tête ET de pied de page de chaque format : 200, 2 documents."""
    data = FORMATS[name]()
    _default_letterhead(env, data, data, ext="webp" if name.startswith("webp") else "png")
    avis = _avis(env)
    pv = env.c.post(f"/api/letters/templates/{avis['id']}/preview", headers=_h("secr"), json=_prod_payload())
    assert pv.status_code == 200, pv.text
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["count"] == 2 and out["warnings"] == []
    assert [d["number"] for d in out["items"]] == ["1/GESP/DG/2026", "2/GESP/DG/2026"]
    for d in out["items"]:
        text, images, _ = _pdf(env.c.get(f"/api/letters/documents/{d['id']}/pdf", headers=_h("secr")).content)
        assert "Ouagadougou, le 1 octobre 2026" in text and "Pharmacien Gérant" in text and "Docteur," in text
        assert "du mardi 18 au vendredi 21 août 2026" in text and "{{" not in text
        assert images >= 3            # en-tête + pied de page + QR code
        word = env.c.get(f"/api/letters/documents/{d['id']}/word", headers=_h("secr"))
        assert word.status_code == 200 and "data:image/webp" not in word.content.decode("utf-8")
    merged = env.c.post("/api/letters/documents/merged-pdf", headers=_h("secr"), json={"batch_id": out["batch_id"]})
    assert merged.status_code == 200 and _pdf(merged.content)[2] >= 2


def test_upload_webp_letterhead_is_stored_as_png(env):
    files = {"header": ("entete.webp", _img("WEBP", "RGBA"), "image/webp")}
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "ALBARKA"}, files=files)
    assert r.status_code == 200, r.text
    lh = asyncio.run(env.db.letterheads.find_one({"id": r.json()["id"]}))
    assert lh["header_path"].endswith(".png")
    img = env.c.get(f"/api/admin/letterheads/{lh['id']}/header", headers=_h("dir"))
    assert Image.open(io.BytesIO(img.content)).format == "PNG"
    # Fichier qui n'est pas une image : refus clair dès le chargement
    bad = {"header": ("x.png", b"pas une image", "image/png")}
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "X"}, files=bad)
    assert r.status_code == 400 and "illisible" in r.json()["detail"]


# ---------------------------------------------------------------- images absentes / illisibles
def test_missing_letterhead_image_still_generates_with_warning(env):
    _default_letterhead(env, _img("PNG"), _img("PNG"), ext="png", store=False)   # fichiers perdus (R2)
    avis = _avis(env)
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 200, r.text
    warns = " ".join(r.json()["warnings"])
    assert "introuvable" in warns and "Papiers à en-tête" in warns
    pv = env.c.post(f"/api/letters/templates/{avis['id']}/preview", headers=_h("secr"), json=_prod_payload())
    assert pv.status_code == 200 and "introuvable" in unquote(pv.headers.get("x-avertissements", ""))
    # L'aperçu de l'image dans les réglages : 404 lisible, pas 500
    img = env.c.get("/api/admin/letterheads/lh-gesp/header", headers=_h("dir"))
    assert img.status_code == 404 and "rechargez" in img.json()["detail"]


def test_unreadable_letterhead_image_still_generates_with_warning(env):
    _default_letterhead(env, b"<svg>pas une image matricielle</svg>", ext="png")
    avis = _avis(env)
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 200, r.text
    assert "illisible" in " ".join(r.json()["warnings"])


def test_template_letterhead_deleted_or_absent(env):
    _default_letterhead(env, _img("PNG"), ext="png")
    avis = _avis(env)
    # Le modèle pointe vers un papier supprimé depuis -> papier par défaut + avertissement
    asyncio.run(env.db.doc_templates.update_one({"id": avis["id"]}, {"$set": {"letterhead_id": "supprime"}}))
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 200, r.text
    assert "n'existe plus" in " ".join(r.json()["warnings"]) and "GESPHARM" in " ".join(r.json()["warnings"])
    # Champ letterhead_id absent du modèle (anciens enregistrements)
    asyncio.run(env.db.doc_templates.update_one({"id": avis["id"]}, {"$unset": {"letterhead_id": ""}}))
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 200 and r.json()["warnings"] == []
    # Aucun papier du tout et « Aucun en-tête »
    asyncio.run(env.db.letterheads.delete_many({}))
    for lh in (None, "none"):
        r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload(letterhead_id=lh))
        assert r.status_code == 200, r.text


def test_full_page_header_image_leaves_room_for_text(env):
    """Feuille A4 entière chargée comme « en-tête » : avant, 60 pages blanches
    sans texte ; maintenant l'image est plafonnée et le texte imprimé."""
    _default_letterhead(env, _img("PNG", size=(1240, 1754)), ext="png")
    avis = _avis(env)
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload(tenant_ids=["c1"]))
    assert r.status_code == 200, r.text
    assert "trop haute" in " ".join(r.json()["warnings"])
    text, _, pages = _pdf(env.c.get(f"/api/letters/documents/{r.json()['items'][0]['id']}/pdf", headers=_h("secr")).content)
    assert "Pharmacien Gérant" in text and pages <= 4


# ---------------------------------------------------------------- texte du modèle
def test_template_text_with_special_characters(env):
    _default_letterhead(env, _img("WEBP"), _img("WEBP"))
    body = ("<p>Objet : {{objet}} — R&amp;D &lt;cabinet&gt;&nbsp;n° 3</p><p>{{ville}}<br>{{vide}}</p>"
            "<p>L’entreprise « Élite » {{inconnue}}<b><i>gras non fermé<ul><li>un<li>deux</ul>"
            "<table border='1' style='width: 100%'><tr><td colspan='2'>cellule</td></tr></table>"
            "<p style=\"font-family: 'Times New Roman'; margin-left: 230px; font-size: 400px\">x</p>")
    t = env.c.post("/api/letters/templates", headers=_h("secr"), json={
        "name": "Courrier spécial", "category": "courrier", "body_html": body, "number_format": "{n:03}/{annee}",
        "variables": [{"key": "objet", "label": "Objet", "scope": "common"},
                      {"key": "ville", "label": "Ville", "scope": "recipient"},
                      {"key": "vide", "label": "Non renseignée", "scope": "recipient"}]}).json()
    payload = {"tenant_ids": ["c1", "c2"], "doc_date": "01/10/2026",
               "common_values": {"objet": "Dossiers RH & paie <2026> de l’été"},
               "recipient_values": {"c1": {"ville": "BOBO-DIOULASSO\nSecteur 22"}}}
    r = env.c.post(f"/api/letters/templates/{t['id']}/generate", headers=_h("secr"), json=payload)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [d["number"] for d in items] == ["001/2026", "002/2026"]
    assert items[0]["doc_date"] == "2026-10-01"
    text, _, _ = _pdf(env.c.get(f"/api/letters/documents/{items[0]['id']}/pdf", headers=_h("secr")).content)
    assert "Dossiers RH & paie <2026> de l’été" in text and "R&D <cabinet>" in text
    assert "L’entreprise « Élite »" in text and "BOBO-DIOULASSO" in text and "cellule" in text


def test_invalid_date_gives_clear_error(env):
    avis = _avis(env)
    for route in ("preview", "generate"):
        r = env.c.post(f"/api/letters/templates/{avis['id']}/{route}", headers=_h("secr"), json=_prod_payload(doc_date="32/13/2026"))
        assert r.status_code == 422 and "Date du document invalide" in r.json()["detail"]
    assert asyncio.run(env.db.doc_templates.find_one({"id": avis["id"]}))["next_number"] == 1


# ---------------------------------------------------------------- erreurs lisibles
def test_pdf_failure_gives_readable_error_and_keeps_counter(env, monkeypatch):
    avis = _avis(env)

    def boom(*a, **kw):
        raise RuntimeError("code=7: unknown image file format")
    monkeypatch.setattr(albarka_letters, "html_to_pdf", boom)
    for route in ("preview", "generate"):
        r = env.c.post(f"/api/letters/templates/{avis['id']}/{route}", headers=_h("secr"), json=_prod_payload())
        assert r.status_code == 422, r.text
        assert "Le PDF n'a pas pu être produit" in r.json()["detail"] and "PNG ou JPG" in r.json()["detail"]
    # Le numéro non utilisé est rendu : la prochaine génération reprend au n° 1
    tpl = asyncio.run(env.db.doc_templates.find_one({"id": avis["id"]}))
    assert tpl["next_number"] == 1 and tpl["generated_count"] == 0
    assert asyncio.run(env.db.generated_documents.count_documents({})) == 0


def test_storage_failure_gives_503(env, monkeypatch):
    avis = _avis(env)

    async def down(*a, **kw):
        raise ConnectionError("R2 indisponible")
    monkeypatch.setattr(albarka_storage, "save_and_log", down)
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_prod_payload())
    assert r.status_code == 503 and "réessayez" in r.json()["detail"]
    assert asyncio.run(env.db.doc_templates.find_one({"id": avis["id"]}))["next_number"] == 1
