"""Lot 12 — papier à en-tête « PAGE ENTIÈRE » (fond A4).

Le cabinet a chargé comme image « en-tête » une page A4 complète (logo en haut
sur ~15 % de la hauteur, blanc au milieu, coordonnées / RCCM / IFU en bas sur
~10 %). Depuis le lot 11 l'en-tête est plafonné à 40 % de la page : vignette
en haut et page 2 vide. Le lot 12 ajoute le type « page » : l'image est posée
en fond de chaque page, pleine page, et le texte s'écrit entre deux marges
détectées automatiquement sur l'image.
Sont couverts : détection du type et des marges, routes admin, PDF des
documents à modèles (fond sur chaque page, texte dans la zone utile, aucune
page vide), mode « bandes » inchangé, facture, tableau de paie, version Word.
Tests autonomes : MongoDB simulé (mongomock-motor), stockage local temporaire.
"""
from __future__ import annotations

import asyncio
import io
import os
import random
import sys
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
Image = pytest.importorskip("PIL.Image")
ImageDraw = pytest.importorskip("PIL.ImageDraw")

import db as db_module  # noqa: E402
import albarka_docgen  # noqa: E402
import albarka_letters  # noqa: E402
import albarka_storage  # noqa: E402
from albarka_auth import get_current_user  # noqa: E402

USERS = {
    "dir": {"id": "u-dir", "email": "dg@albarka.bf", "full_name": "Direction", "roles": ["direction"], "is_active": True},
    "secr": {"id": "u-secr", "email": "s@albarka.bf", "full_name": "Secrétaire", "roles": ["secretariat"], "is_active": True},
    "c1": {"id": "c1", "email": "ct1@exemple.bf", "full_name": "Client Test 1", "roles": ["client"], "is_active": True},
}

# Marges attendues pour l'image synthétique : bande haute 15 % et bande basse
# 10 % de 297 mm, plus 6 mm de respiration
TOP_EXPECTED = 0.15 * 297 + 6       # 50,55 mm
BOTTOM_EXPECTED = 0.10 * 297 + 6    # 35,7 mm
PT_MM = 72 / 25.4
# Tolérance (points) : la boîte d'une ligne inclut le jambage haut de la police,
# qui peut dépasser de ~1 pt l'interligne placé par le moteur de mise en page
TOL = 2.0


# ---------------------------------------------------------------- images de test
def _a4_page(size=(2480, 3508), fmt="PNG", noise=True) -> bytes:
    """Page A4 complète synthétique : bande colorée en haut (15 %, avec un
    « logo »), milieu blanc avec quelques pixels parasites (poussières du
    scanner), bande colorée en bas (10 %, « coordonnées / RCCM / IFU »)."""
    w, h = size
    im = Image.new("RGB", size, (255, 255, 255))
    d = ImageDraw.Draw(im)
    top, bottom = round(h * 0.15), round(h * 0.10)
    d.rectangle([0, 0, w - 1, top - 1], fill=(226, 236, 246))
    d.ellipse([w // 10, top // 6, w // 10 + top // 2, top // 6 + top // 2], fill=(20, 90, 160))   # logo
    d.rectangle([0, h - bottom, w - 1, h - 1], fill=(240, 228, 210))
    d.rectangle([w // 8, h - bottom + bottom // 3, w - w // 8, h - bottom + bottom // 3 + 20], fill=(60, 60, 60))
    if noise:
        rnd = random.Random(12)
        for _ in range(40):
            x, y = rnd.randrange(w), rnd.randrange(top + 50, h - bottom - 50)
            im.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def _band(size=(1240, 200), color=(20, 90, 160)) -> bytes:
    """Bandeau classique (type « bandes »)."""
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- environnement
@pytest.fixture()
def env(monkeypatch, tmp_path):
    mock_db = mongomock_motor.AsyncMongoMockClient()["albarka_lot12_test"]
    real_db = db_module.db
    for mod in list(sys.modules.values()):
        if getattr(mod, "db", None) is real_db and getattr(mod, "__name__", "").startswith(("albarka_", "db")):
            monkeypatch.setattr(mod, "db", mock_db)
    monkeypatch.setattr(albarka_storage, "UPLOAD_DIR", tmp_path)
    albarka_docgen._DETECT_CACHE.clear()
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
    with TestClient(app, raise_server_exceptions=False) as client:
        yield type("Env", (), {"c": client, "db": mock_db})


def _h(u):
    return {"X-User": u}


def _stored_letterhead(env, header: bytes | None, footer: bytes | None = None, lh_id: str = "lh-a4", **extra) -> str:
    """Papier « par défaut » enregistré directement (comme un papier créé
    avant le lot 12 : sans champ `mode`, sauf si `extra` le précise)."""
    doc = {"id": lh_id, "name": "ALBARKA A4", "is_default": True, "top_margin_cm": 4.8, "bottom_margin_cm": 2.0,
           "header_path": None, "footer_path": None, **extra}
    for part, data in (("header", header), ("footer", footer)):
        if data is None:
            continue
        path = f"albarka/cabinet/letterheads/{lh_id}_{part}.png"
        asyncio.run(albarka_storage.put_object(path, data, "image/png"))
        doc[f"{part}_path"] = path
    asyncio.run(env.db.letterheads.insert_one(doc))
    return lh_id


def _avis(env) -> dict:
    tpls = env.c.get("/api/letters/templates", headers=_h("secr")).json()
    return next(t for t in tpls if t["name"] == "Avis de mission")


def _make_avis_long(env) -> None:
    """Allonge le texte du modèle « Avis de mission » pour qu'il tienne sur
    deux pages (paragraphes ajoutés à la fin)."""
    avis = asyncio.run(env.db.doc_templates.find_one({"name": "Avis de mission"}))
    extra = "".join(f"<p>Paragraphe complémentaire n° {i} : les pièces justificatives de la paie, les contrats "
                    "de travail, les déclarations sociales et fiscales du trimestre seront présentés à "
                    "l'équipe du cabinet lors de son passage.</p>" for i in range(1, 11))
    asyncio.run(env.db.doc_templates.update_one({"id": avis["id"]},
                                                {"$set": {"body_html": avis["body_html"] + extra}}))


def _payload(**over) -> dict:
    per = {"destinataire_titre": "Pharmacien Gérant", "ville_destinataire": "OUAGADOUGOU",
           "civilite": "Docteur", "civilite_min": "docteur"}
    out = {"tenant_ids": ["c1"], "doc_date": "2026-10-01", "letterhead_id": None, "mission_id": None,
           "deposit": False, "notify": False,
           "common_values": {"objet_mission": "traitement des dossiers ressources humaines de vos entreprises",
                             "periode_mission": "du mardi 18 au vendredi 21 août 2026"},
           "recipient_values": {"c1": dict(per)}}
    out.update(over)
    return out


def _generate_pdf(env) -> tuple[dict, bytes]:
    avis = _avis(env)
    r = env.c.post(f"/api/letters/templates/{avis['id']}/generate", headers=_h("secr"), json=_payload())
    assert r.status_code == 200, r.text
    out = r.json()
    pdf = env.c.get(f"/api/letters/documents/{out['items'][0]['id']}/pdf", headers=_h("secr"))
    assert pdf.status_code == 200
    return out, pdf.content


def _full_page_images(page) -> int:
    """Nombre d'images posées sur toute la page (fond)."""
    r = page.rect
    return sum(1 for info in page.get_image_info()
               if abs(info["bbox"][0]) < 1 and abs(info["bbox"][1]) < 1
               and abs(info["bbox"][2] - r.width) < 1 and abs(info["bbox"][3] - r.height) < 1)


# ---------------------------------------------------------------- détection
def test_detect_mode_and_margins_on_a4_page():
    det = albarka_docgen.detect_page_letterhead(_a4_page())
    assert det["a4_like"] and det["found"] and det["warnings"] == []
    assert abs(det["top_mm"] - TOP_EXPECTED) <= 1.5
    assert abs(det["bottom_mm"] - BOTTOM_EXPECTED) <= 1.5
    # Même résultat en JPEG (bruit de compression) et sur une image plus petite
    for data in (_a4_page(fmt="JPEG"), _a4_page(size=(1240, 1754))):
        d = albarka_docgen.detect_page_letterhead(data)
        assert d["found"] and abs(d["top_mm"] - TOP_EXPECTED) <= 1.5 and abs(d["bottom_mm"] - BOTTOM_EXPECTED) <= 1.5


def test_detect_band_and_unusable_images():
    # Bandeau : pas une page A4
    assert albarka_docgen.detect_page_letterhead(_band())["a4_like"] is False
    # Page A4 unie (aucune zone blanche) : garde-fous -> 35 / 30 mm + avertissements
    plain = albarka_docgen.detect_page_letterhead(_band(size=(1240, 1754)))
    assert plain["a4_like"] and not plain["found"]
    assert (plain["top_mm"], plain["bottom_mm"]) == (35.0, 30.0) and len(plain["warnings"]) == 2
    # Image illisible : valeurs par défaut, pas d'exception
    bad = albarka_docgen.detect_page_letterhead(b"pas une image")
    assert not bad["found"] and bad["top_mm"] == 35.0


def test_page_bands_crop():
    top, bottom = albarka_docgen.page_bands(_a4_page(), 50.5, 35.5)
    t, b = Image.open(io.BytesIO(top)), Image.open(io.BytesIO(bottom))
    assert t.width == b.width == 2480
    assert abs(t.height - round((50.5 - 6) / 297 * 3508)) <= 1
    assert abs(b.height - round((35.5 - 6) / 297 * 3508)) <= 1


# ---------------------------------------------------------------- routes admin
def test_upload_a4_page_proposes_page_mode(env):
    files = {"header": ("papier.png", _a4_page(), "image/png")}
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "ALBARKA"}, files=files)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["mode"] == "page" and out["mode_auto"] is False
    assert abs(out["page_top_mm"] - TOP_EXPECTED) <= 1.5 and abs(out["page_bottom_mm"] - BOTTOM_EXPECTED) <= 1.5
    assert out["detection"]["suggested_mode"] == "page" and "Page entière" in out["detection"]["message"]
    stored = asyncio.run(env.db.letterheads.find_one({"id": out["id"]}))
    assert stored["mode"] == "page" and stored["page_top_mm"] == out["page_top_mm"]
    # L'admin corrige les marges ; elles sont plafonnées (garde-fous)
    r = env.c.put(f"/api/admin/letterheads/{out['id']}", headers=_h("dir"),
                  data={"page_top_mm": "55", "page_bottom_mm": "200", "page_left_mm": "25"})
    assert r.status_code == 200, r.text
    assert r.json()["page_top_mm"] == 55 and r.json()["page_bottom_mm"] <= 0.35 * 297 and r.json()["page_left_mm"] == 25
    # Retour au type « bandes » choisi par l'admin
    r = env.c.put(f"/api/admin/letterheads/{out['id']}", headers=_h("dir"), data={"mode": "bandes"})
    assert r.json()["mode"] == "bandes"
    assert env.c.put(f"/api/admin/letterheads/{out['id']}", headers=_h("dir"), data={"mode": "x"}).status_code == 400


def test_upload_band_stays_bandes_and_explicit_mode_wins(env):
    files = {"header": ("bandeau.png", _band(), "image/png"), "footer": ("pied.png", _band((1240, 120)), "image/png")}
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "BANDES"}, files=files)
    assert r.status_code == 200 and r.json()["mode"] == "bandes"
    assert r.json()["detection"]["suggested_mode"] == "bandes"
    # Image A4 mais type « bandes » choisi explicitement
    files = {"header": ("papier.png", _a4_page(), "image/png")}
    r = env.c.post("/api/admin/letterheads", headers=_h("dir"), data={"name": "FORCE", "mode": "bandes"}, files=files)
    assert r.json()["mode"] == "bandes"


def test_detect_route(env):
    # Image envoyée avant enregistrement
    r = env.c.post("/api/admin/letterheads/detect", headers=_h("dir"),
                   files={"header": ("p.png", _a4_page(), "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["suggested_mode"] == "page" and abs(r.json()["top_mm"] - TOP_EXPECTED) <= 1.5
    # Papier déjà enregistré
    _stored_letterhead(env, _a4_page())
    r = env.c.post("/api/admin/letterheads/detect", headers=_h("dir"), data={"letterhead_id": "lh-a4"})
    assert r.status_code == 200 and r.json()["suggested_mode"] == "page"
    assert env.c.post("/api/admin/letterheads/detect", headers=_h("dir"), data={"letterhead_id": "zz"}).status_code == 404
    # Réservé aux administrateurs des documents
    assert env.c.post("/api/admin/letterheads/detect", headers=_h("secr"), data={"letterhead_id": "lh-a4"}).status_code == 403


def test_existing_letterhead_without_mode_is_read_as_page(env):
    """Papier enregistré avant le lot 12 (pas de champ `mode`) : la page A4
    sans pied de page est lue comme « page entière » (proposée)."""
    _stored_letterhead(env, _a4_page())
    items = env.c.get("/api/admin/letterheads", headers=_h("dir")).json()
    assert items[0]["mode"] == "page" and items[0]["mode_auto"] is True
    lh = asyncio.run(albarka_docgen.load_letterhead(None))
    assert lh["mode"] == "page" and abs(lh["page_top_mm"] - TOP_EXPECTED) <= 1.5


# ---------------------------------------------------------------- PDF des documents à modèles
@pytest.mark.parametrize("stored_mode", [None, "page"])
def test_long_avis_de_mission_on_full_page_paper(env, stored_mode):
    extra = {"mode": stored_mode} if stored_mode else {}
    _stored_letterhead(env, _a4_page(), **extra)
    _make_avis_long(env)
    out, pdf = _generate_pdf(env)
    assert out["warnings"] == []          # plus d'avertissement « trop haute »
    lh = asyncio.run(albarka_docgen.load_letterhead(None))
    top = lh["page_top_mm"] * PT_MM
    bottom = lh["page_bottom_mm"] * PT_MM
    doc = fitz.open("pdf", pdf)
    assert doc.page_count == 2
    text = " ".join(" ".join(p.get_text() for p in doc).split())
    assert "Pharmacien Gérant" in text and "Paragraphe complémentaire n° 10" in text
    for page in doc:
        # Fond pleine page sur chaque page
        assert _full_page_images(page) == 1
        # Tous les blocs de texte dans la zone utile (à TOL près)
        blocks = [b for b in page.get_text("dict")["blocks"] if b["type"] == 0]
        assert blocks, "page sans texte"
        for b in blocks:
            assert b["bbox"][1] >= top - TOL and b["bbox"][3] <= page.rect.height - bottom + TOL, b["bbox"]
    # QR code de vérification : première page seulement, dans la zone utile
    qr = [i for i in doc[0].get_image_info() if i["bbox"][2] - i["bbox"][0] < 100]
    assert len(qr) == 1 and qr[0]["bbox"][1] >= top
    # L'image de fond n'est enregistrée qu'une fois dans le PDF
    assert len({x[0] for p in doc for x in p.get_images()}) == 2
    doc.close()


def test_bandes_mode_unchanged(env):
    """Papier en bandes : en-tête en haut, pied en bas, pas de fond pleine page."""
    _stored_letterhead(env, _band(), _band((1240, 120)), mode="bandes")
    out, pdf = _generate_pdf(env)
    assert out["warnings"] == []
    doc = fitz.open("pdf", pdf)
    page = doc[0]
    assert _full_page_images(page) == 0
    boxes = [i["bbox"] for i in page.get_image_info()]
    assert any(abs(b[1]) < 1 and abs(b[2] - 595) < 1 for b in boxes)          # en-tête en haut
    assert any(abs(b[3] - 842) < 1 for b in boxes)                           # pied en bas
    doc.close()


def test_a4_image_in_bandes_mode_advises_page_type(env):
    """Image A4 forcée en « bandes » : avertissement « trop haute » avec le
    conseil de choisir le type « Page entière »."""
    _stored_letterhead(env, _a4_page(), mode="bandes")
    out, _pdf = _generate_pdf(env)
    warns = " ".join(out["warnings"])
    assert "trop haute" in warns and "Page entière" in warns and "Papiers à en-tête" in warns


def test_word_version_with_full_page_paper(env):
    _stored_letterhead(env, _a4_page(), mode="page")
    out, _pdf = _generate_pdf(env)
    r = env.c.get(f"/api/letters/documents/{out['items'][0]['id']}/word", headers=_h("secr"))
    assert r.status_code == 200
    html = r.content.decode("utf-8")
    assert "Pharmacien Gérant" in html and html.count("data:image/png;base64,") == 2   # bande haute + bande basse


# ---------------------------------------------------------------- factures et paie (reportlab)
def test_invoice_with_full_page_paper(env):
    from albarka_invoice_layout import build_invoice_model_pdf
    _stored_letterhead(env, _a4_page(), mode="page")
    lh = asyncio.run(albarka_docgen.load_letterhead(None))
    items = [{"label": f"Prestation n° {i}", "detail": "Tenue de la comptabilité\nDéclarations", "quantity": 1,
              "unit_price": 150000, "tax_rate": 18} for i in range(1, 31)]
    invoice = {"document_type": "facture", "number": "F-2026-001", "issue_date": "2026-10-01", "items": items,
               "subtotal": 4500000, "tax": 810000, "total": 5310000}
    pdf = build_invoice_model_pdf(invoice=invoice, client={"full_name": "Client Test 1"}, kyc=None, letterhead=lh,
                                  settings={"signatory_name": "M. le DG"}, qr_bytes=albarka_docgen.qr_png("x"))
    doc = fitz.open("pdf", pdf)
    assert doc.page_count >= 2
    top, bottom = lh["page_top_mm"] * PT_MM, lh["page_bottom_mm"] * PT_MM
    for page in doc:
        assert _full_page_images(page) == 1
        for b in page.get_text("dict")["blocks"]:
            if b["type"] == 0:
                assert b["bbox"][1] >= top - TOL and b["bbox"][3] <= page.rect.height - bottom + TOL, b["bbox"]
    doc.close()


def test_payroll_with_full_page_paper(env):
    import albarka_payroll
    _stored_letterhead(env, _a4_page(), mode="page")
    lh = asyncio.run(albarka_docgen.load_letterhead(None))
    table = {"period_label": "OCTOBRE 2026", "company": "PHARMACIE TEST", "rows": [],
             "totals": {**{k: 0 for k, _ in albarka_payroll.AMOUNT_COLUMNS}, "gross": 0, "net": 0}}
    pdf = albarka_payroll.build_payroll_pdf(table, lh, True, "https://exemple.bf/v/x")
    doc = fitz.open("pdf", pdf)
    land, port = doc[0], doc[-1]
    assert land.rect.width > land.rect.height and port.rect.width < port.rect.height
    # Paysage : bandes haute et basse découpées ; portrait : fond pleine page
    assert _full_page_images(land) == 0 and len(land.get_image_info()) >= 2
    assert _full_page_images(port) == 1
    doc.close()
