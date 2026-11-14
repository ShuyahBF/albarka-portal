"""Lot 113 — NOM de famille (majuscules) + Prénoms (initiales) ; le Nom complet est leur concaténation."""
import os
import sys
from pathlib import Path

os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "albarka_test")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from albarka_noms import assembler, formater_nom, formater_prenoms, separer, completer_document  # noqa: E402
from albarka_clients import ClientCreate, StaffCreate, UserUpdate  # noqa: E402
from albarka_contacts import ContactCreate, ContactUpdate  # noqa: E402


def test_orthographe_nom_et_prenoms():
    assert formater_nom("  sana  ") == "SANA"
    assert formater_prenoms("aZIZE  jean-paul") == "Azize Jean-Paul"
    assert formater_prenoms("n'dour") == "N'Dour"
    assert assembler("badini", "AWA marie") == "BADINI Awa Marie"


def test_separation_des_anciens_noms_complets():
    assert separer("SANA Azize") == ("SANA", "Azize")
    assert separer("sana azize") == ("SANA", "Azize")
    assert separer("OUEDRAOGO KABORE Awa Marie") == ("OUEDRAOGO KABORE", "Awa Marie")
    assert separer("") == ("", "")
    assert completer_document({"full_name": "SANA Azize"})["prenoms"] == "Azize"


def test_les_formulaires_assemblent_le_nom_complet():
    c = ClientCreate(nom="sana", prenoms="azize", email="a@b.com")
    assert (c.nom, c.prenoms, c.full_name) == ("SANA", "Azize", "SANA Azize")
    s = StaffCreate(nom="badini", prenoms="awa", roles=["comptable"], phone="+22670000000")
    assert s.full_name == "BADINI Awa"
    assert UserUpdate(nom="x", prenoms="y z").full_name == "X Y Z"
    ct = ContactCreate(scope="cabinet", nom="kaboré", prenoms="ISSA", email="k@b.com")
    assert ct.full_name == "KABORÉ Issa"
    assert ContactUpdate(nom="a", prenoms="b").full_name == "A B"


def test_ancien_format_sans_nom_ni_prenoms_inchange():
    assert ClientCreate(full_name="sana azize", email="a@b.com").full_name == "sana azize"
    assert ContactUpdate(function="autre").full_name is None
