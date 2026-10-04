"""Lot 13 — migration vers Render : indépendance d'Emergent.

Couvre : appel IA par le SDK officiel anthropic (transport simulé), dictée
Whisper par le SDK openai (simulé), e-mails par SMTP (serveur simulé, pièces
jointes), certificats P12 recopiés dans R2 et relus après effacement du disque,
planificateur interne (rappels du jour une seule fois, envois WhatsApp),
compteur de déploiements et GET /api/version, sauvegarde chiffrée de la base
(export -> relecture -> restauration) et absence de toute dépendance Emergent.
Tests autonomes : MongoDB simulé (mongomock-motor), aucun appel réseau.
"""
from __future__ import annotations

import asyncio
import base64
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
mongomock_motor = pytest.importorskip("mongomock_motor")

RACINE = Path(__file__).resolve().parents[2]


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture()
def base(monkeypatch):
    """Base MongoDB simulée, branchée à la place de la vraie (module db)."""
    import db as db_module
    client = mongomock_motor.AsyncMongoMockClient()
    base_test = client["albarka_lot13"]
    monkeypatch.setattr(db_module, "db", base_test)
    return base_test


# ---------------------------------------------------------------------------
# 1. Plus aucune dépendance Emergent dans le code exécuté
# ---------------------------------------------------------------------------
def test_aucune_dependance_emergent():
    backend = RACINE / "backend"
    fautifs = []
    for f in backend.rglob("*.py"):
        if "tests" in f.parts or f.name == "ia_client.py":
            continue
        texte = f.read_text(encoding="utf-8")
        for ligne in texte.splitlines():
            l = ligne.strip()
            if l.startswith(("import ", "from ")) and "emergentintegrations" in l:
                fautifs.append(f"{f.name}: {l}")
            if "storage_r2" in l and l.startswith("from "):
                fautifs.append(f"{f.name}: {l}")
    assert fautifs == []
    req = (backend / "requirements.txt").read_text()
    assert "emergentintegrations" not in req and "anthropic==" in req and "openai==" in req
    for paquet in ("reportlab", "openpyxl", "pyHanko"):
        assert paquet in req
    index = (RACINE / "frontend/public/index.html").read_text()
    assert "emergent.sh" not in index and "posthog.init" not in index
    assert "emergentbase" not in (RACINE / "frontend/package.json").read_text()


# ---------------------------------------------------------------------------
# 2. IA : OCR par le SDK officiel anthropic
# ---------------------------------------------------------------------------
def test_ocr_par_sdk_anthropic(monkeypatch):
    import ia_client
    from ocr_core import engine
    vu = {}

    async def faux_appel(cle, modele, systeme, messages, params):
        vu.update(cle=cle, modele=modele, systeme=systeme, messages=messages, params=params)
        return SimpleNamespace(content='{"summary": "ok"}', usage=SimpleNamespace(input_tokens=11, output_tokens=7))

    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setattr(ia_client, "_appel_anthropic", faux_appel, raising=False)
    modele = SimpleNamespace(id="claude-test")
    texte, tin, tout = _run(engine.call_llm(modele, "Consigne ALBARKA", "texte", [], "f.txt"))
    assert (texte, tin, tout) == ('{"summary": "ok"}', 11, 7)
    assert vu["cle"] == "sk-ant-test" and vu["modele"] == "claude-test" and vu["systeme"] == "Consigne ALBARKA"


def test_ocr_sans_cle_message_clair(monkeypatch):
    from ocr_core import engine
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        _run(engine.call_llm(SimpleNamespace(id="x"), "s", "t", [], "f"))


# ---------------------------------------------------------------------------
# 3. Dictée (Whisper) par le SDK openai
# ---------------------------------------------------------------------------
def test_dictee_whisper(monkeypatch):
    import ia_client
    import albarka_chat_extra as ce

    async def faux_reglages():
        return {"voice_notes_enabled": True}

    async def fausse_transcription(self, file, **kw):
        assert kw["model"] == "whisper-1" and kw["response_format"] == "text"
        return ia_client._Texte("  Bonjour le cabinet  ")

    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setattr(ce, "get_settings_doc", faux_reglages, raising=False)
    monkeypatch.setattr(ia_client.OpenAISpeechToText, "transcribe", fausse_transcription)
    fonction = ce.transcribe_audio_bytes
    texte = _run(fonction(b"OggS-faux-audio", mime="audio/ogg", language="fr"))
    assert texte == "Bonjour le cabinet"
    monkeypatch.delenv("OPENAI_API_KEY")
    assert _run(fonction(b"OggS", mime="audio/ogg", language="fr")) is None


# ---------------------------------------------------------------------------
# 4. E-mails par SMTP
# ---------------------------------------------------------------------------
class FauxSMTP:
    envois = []

    def __init__(self, hote, port, timeout=None, context=None):
        self.hote, self.port, self.tls, self.login_fait = hote, port, False, None

    def starttls(self, context=None):
        self.tls = True

    def login(self, u, p):
        self.login_fait = (u, p)

    def send_message(self, msg):
        FauxSMTP.envois.append((self, msg))

    def quit(self):
        pass


def test_email_smtp_avec_piece_jointe(monkeypatch):
    import smtplib
    import albarka_notifications as notif

    async def faux_config():
        return {"from_name": "Cabinet ALBARKA", "from_email": None, "reply_to": "contact@albarka-bf.com"}

    FauxSMTP.envois.clear()
    monkeypatch.setattr(smtplib, "SMTP", FauxSMTP)
    monkeypatch.setattr(notif, "_get_email_config", faux_config)
    for k, v in {"SMTP_HOST": "smtp.exemple.bf", "SMTP_PORT": "587", "SMTP_USER": "u@albarka-bf.com",
                 "SMTP_PASSWORD": "mdp-test", "SMTP_FROM": "contact@albarka-bf.com"}.items():
        monkeypatch.setenv(k, v)
    pj = {"filename": "rapport.pdf", "content": base64.b64encode(b"%PDF-1.4 test").decode(), "content_type": "application/pdf"}
    mid = _run(notif.send_email(to=["a@exemple.bf", "b@exemple.bf"], subject="Rappel d'échéance",
                                html="<p>Bonjour, votre échéance approche.</p>", attachments=[pj]))
    assert mid and len(FauxSMTP.envois) == 1
    serveur, msg = FauxSMTP.envois[0]
    assert serveur.tls and serveur.login_fait == ("u@albarka-bf.com", "mdp-test")
    assert "contact@albarka-bf.com" in msg["From"] and "Cabinet ALBARKA" in msg["From"]
    assert msg["To"] == "a@exemple.bf, b@exemple.bf" and msg["Reply-To"] == "contact@albarka-bf.com"
    pieces = [p for p in msg.iter_attachments()]
    assert pieces[0].get_filename() == "rapport.pdf" and pieces[0].get_content() == b"%PDF-1.4 test"
    # Sans SMTP ni ancien service : rien n'est envoyé, sans erreur
    monkeypatch.delenv("SMTP_HOST")
    monkeypatch.setattr(notif, "EMAIL_KEY", "")
    assert _run(notif.send_email(to="a@exemple.bf", subject="x", html="<p>x</p>")) is None


# ---------------------------------------------------------------------------
# 5. Certificats de signature : copie R2 et relecture après effacement du disque
# ---------------------------------------------------------------------------
def test_certificat_recopie_depuis_r2(monkeypatch, tmp_path):
    pytest.importorskip("pyhanko")
    import albarka_signing as sig
    import albarka_storage as st
    stock = {}
    monkeypatch.setattr(st, "_r2_configured", lambda: True)
    monkeypatch.setattr(st, "_r2_put_sync", lambda chemin, data, ct: stock.__setitem__(chemin, data) or {"path": chemin})
    monkeypatch.setattr(st, "_r2_get_sync", lambda chemin: (stock[chemin], "application/x-pkcs12"))
    monkeypatch.setattr(sig, "CERT_DIR", tmp_path)
    meta = sig.create_cabinet_certificate(common_name="Cabinet ALBARKA", organization="ALBARKA", country="BF",
                                          email=None, valid_years=1, passphrase="phrase-test")
    assert f"albarka/certs/{meta['id']}.p12" in stock
    # Redéploiement Render : disque effacé ; le chemin enregistré venait de l'ancien hébergement
    Path(meta["p12_path"]).unlink()
    signataire = sig.load_signer(f"/app/backend/uploads/certs/{meta['id']}.p12", "phrase-test")
    assert signataire is not None and (tmp_path / f"{meta['id']}.p12").exists()


# ---------------------------------------------------------------------------
# 6. Planificateur interne
# ---------------------------------------------------------------------------
def test_planificateur_actif_seulement_sur_render(monkeypatch):
    import albarka_planificateur as pl
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("PLANIFICATEUR_INTERNE", raising=False)
    assert pl.planificateur_actif() is False
    monkeypatch.setenv("RENDER", "true")
    assert pl.planificateur_actif() is True
    monkeypatch.setenv("PLANIFICATEUR_INTERNE", "0")
    assert pl.planificateur_actif() is False


def test_rappels_une_seule_fois_par_jour(monkeypatch, base):
    import albarka_planificateur as pl
    import albarka_reports_router as rr
    appels = []

    async def faux_rappels():
        appels.append(1)
        return {"processed": 3}

    monkeypatch.setattr(rr, "_run_daily_notifications", faux_rappels)
    matin = datetime(2026, 10, 5, 6, 59, tzinfo=timezone.utc)
    assert _run(pl.lancer_rappels_echeances_du_jour(matin)) is False        # avant 07h00
    sept = datetime(2026, 10, 5, 7, 0, tzinfo=timezone.utc)
    assert _run(pl.lancer_rappels_echeances_du_jour(sept)) is True
    assert _run(pl.lancer_rappels_echeances_du_jour(sept.replace(hour=15))) is False  # redémarrage
    assert _run(pl.lancer_rappels_echeances_du_jour(sept.replace(day=6))) is True     # lendemain
    assert len(appels) == 2


def test_envois_wa_planifies_appelle_la_meme_fonction(monkeypatch):
    import albarka_planificateur as pl
    import albarka_reports_mgmt as rm
    vu = {}

    async def faux_dispatch(authorization=None, x_webhook_id=None):
        vu["auth"] = authorization
        return {"ok": True}

    monkeypatch.setenv("WEBHOOK_CRON_SECRET", "secret-cron")
    monkeypatch.setattr(rm, "cron_dispatch_scheduled_wa", faux_dispatch)
    _run(pl.lancer_envois_wa_planifies())
    assert vu["auth"] == "Bearer secret-cron"


# ---------------------------------------------------------------------------
# 7. Version « 1.N » et lot (règle permanente)
# ---------------------------------------------------------------------------
def test_compteur_de_deploiements(monkeypatch, base):
    import lot
    import version_deploiement as vd
    monkeypatch.setenv("RENDER_GIT_COMMIT", "aaaaaaa1111111")
    v1 = _run(vd.infos_version(base))
    assert v1["version"] == "1.1" and v1["git_sha"] == "aaaaaaa" and v1["lot"] == lot.LOT
    assert _run(vd.infos_version(base))["version"] == "1.1"            # même commit : inchangé
    monkeypatch.setenv("RENDER_GIT_COMMIT", "bbbbbbb2222222")
    assert _run(vd.infos_version(base))["version"] == "1.2"            # nouveau déploiement


# ---------------------------------------------------------------------------
# 8. Sauvegarde chiffrée de la base
# ---------------------------------------------------------------------------
def test_sauvegarde_export_relecture_restauration(monkeypatch, base):
    import albarka_sauvegarde as sv
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", "phrase-sauvegarde")
    date = datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)
    _run(base.users.insert_one({"id": "u1", "email": "a@albarka.bf", "created": date}))
    _run(base.client_reports.insert_one({"id": "r1", "number": "R-1"}))
    _run(base.otps.insert_one({"code": "123456"}))
    octets = _run(sv.exporter_base(base))
    assert b"a@albarka.bf" not in octets                                   # chiffré
    donnees = sv.lire_sauvegarde(octets)
    assert set(donnees["collections"]) == {"users", "client_reports"}    # codes OTP exclus
    assert donnees["collections"]["users"][0]["created"].replace(tzinfo=timezone.utc) == date
    _run(base.users.delete_many({}))
    bilan = _run(sv.restaurer_depuis_octets(base, octets))
    assert bilan["users"] == 1 and _run(base.users.count_documents({})) == 1
    # Mauvaise phrase : relecture refusée
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", "autre-phrase")
    with pytest.raises(Exception):
        sv.lire_sauvegarde(octets)


def test_blueprint_render():
    yaml = (RACINE / "render.yaml").read_text()
    for attendu in ("albarka-backend", "albarka-frontend", "render-production", "api.albarka-bf.com",
                    "DB_NAME", "value: albarka", "ANTHROPIC_API_KEY", "SMTP_HOST", "WEBHOOK_CRON_SECRET",
                    "SAUVEGARDE_AUTO_PHRASE", "R2_SAUVEGARDES_ACCOUNT_ID", "PLANIFICATEUR_INTERNE", "healthCheckPath: /api/health"):
        assert attendu in yaml, attendu
    # Aucun secret écrit en clair dans le Blueprint
    assert "mongodb+srv://" not in yaml and "sk-ant" not in yaml


# ---------------------------------------------------------------------------
# 9. Sauvegardes : mêmes noms de variables que SAWALI (R2_SAUVEGARDES_*)
# ---------------------------------------------------------------------------
def test_sauvegarde_variables_sawali(monkeypatch):
    import albarka_sauvegarde as sv
    # Variables SAWALI présentes : compte R2 de SAWALI, bucket par défaut, dossier ALBARKA séparé
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "compte123")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret")
    monkeypatch.delenv("R2_SAUVEGARDES_BUCKET", raising=False)
    monkeypatch.delenv("R2_SAUVEGARDES_PREFIXE", raising=False)
    client, bucket = sv._r2()
    assert bucket == "sawali-sauvegardes"
    assert client.meta.endpoint_url == "https://compte123.r2.cloudflarestorage.com"
    assert sv.prefixe_r2() == "albarka/sauvegardes/"
    monkeypatch.setenv("R2_SAUVEGARDES_PREFIXE", "/albarka-prod/")
    assert sv.prefixe_r2() == "albarka-prod/"
    # Sans variables SAWALI ni R2 des fichiers : erreur claire
    for nom in ("R2_SAUVEGARDES_ACCOUNT_ID", "R2_ENDPOINT", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET_NAME"):
        monkeypatch.delenv(nom, raising=False)
    with pytest.raises(RuntimeError):
        sv._r2()


# ---------------------------------------------------------------------------
# 10. Page « Sauvegardes » (lot 13.2) : super-admin seulement, état sans secret,
#     sauvegarde nocturne active même quand les envois sont suspendus
# ---------------------------------------------------------------------------
def test_sauvegardes_super_admin_et_reglages(monkeypatch):
    import albarka_sauvegarde as sv
    from fastapi import HTTPException
    # Superviseur / Direction refusés, compte admin du portail accepté
    with pytest.raises(HTTPException) as refus:
        _run(sv.require_super_admin(user={"email": "dg@albarka.bf", "roles": ["superviseur", "direction"]}))
    assert refus.value.status_code == 403
    assert _run(sv.require_super_admin(user={"email": "Admin@SawaliSmartSystems.com", "roles": []}))
    # Réglages : noms seulement, jamais les valeurs
    monkeypatch.setenv("R2_SAUVEGARDES_ACCOUNT_ID", "compte123")
    monkeypatch.setenv("R2_SAUVEGARDES_ACCESS_KEY_ID", "cle-tres-secrete")
    monkeypatch.setenv("R2_SAUVEGARDES_SECRET_ACCESS_KEY", "secret-tres-secret")
    monkeypatch.setenv("SAUVEGARDE_AUTO_PHRASE", "phrase-tres-secrete")
    r = sv.reglages()
    assert r["configuree"] and r["bucket"] == "sawali-sauvegardes" and r["phrase"] == "SAUVEGARDE_AUTO_PHRASE"
    assert "secret" not in repr(r) and "compte123" not in repr(r)
    # Prochaine sauvegarde : 02h00 UTC le jour même ou le lendemain
    assert sv.prochaine_sauvegarde(datetime(2026, 10, 4, 1, 0, tzinfo=timezone.utc)).startswith("2026-10-04T02:00")
    assert sv.prochaine_sauvegarde(datetime(2026, 10, 4, 12, 0, tzinfo=timezone.utc)).startswith("2026-10-05T02:00")


def test_sauvegarde_nocturne_independante_des_envois(monkeypatch):
    import albarka_planificateur as pl
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("PLANIFICATEUR_INTERNE", "0")
    monkeypatch.delenv("SAUVEGARDE_AUTO", raising=False)
    assert not pl.planificateur_actif() and pl.sauvegarde_auto_active() and pl.boucle_necessaire()
    monkeypatch.setenv("SAUVEGARDE_AUTO", "0")
    assert not pl.boucle_necessaire()


def test_sauvegarde_du_jour_nouvel_essai_apres_echec(monkeypatch, base):
    import albarka_sauvegarde as sv
    appels = []

    async def echec(db, **_):
        appels.append(1)
        raise RuntimeError("R2 indisponible")
    monkeypatch.setattr(sv, "sauvegarder_maintenant", echec)
    t0 = datetime(2026, 10, 4, 3, 0, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError):
        _run(sv.sauvegarde_du_jour(base, t0))
    # 10 minutes plus tard : on attend ; 1 h plus tard : nouvel essai
    assert _run(sv.sauvegarde_du_jour(base, t0.replace(minute=10))) is False
    with pytest.raises(RuntimeError):
        _run(sv.sauvegarde_du_jour(base, t0.replace(hour=4, minute=1)))
    assert len(appels) == 2
