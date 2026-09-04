"""Iteration 6/7 — MongoDB reconciliation endpoints.

Covers:
  * GET  /api/_diag/db                       (staff only since iteration 7 fix)
  * GET  /api/_admin/migrate-mongo/inventory (staff only)
  * POST /api/_admin/migrate-mongo           (guards, dry-run, selective,
                                              idempotence, admin protection,
                                              ephemeral-collection skip,
                                              redacted /tmp backups)

Safety: the target is always the SAME Atlas cluster but db_name='albarka_dryrun'.
The production db 'albarka' is never written to by these tests.
"""
import json
import os
from pathlib import Path

import pytest
import requests
from dotenv import dotenv_values
from pymongo import MongoClient

from tests.conftest import API

_backend_env = dotenv_values("/app/backend/.env")
MONGO_URL = os.environ.get("MONGO_URL") or _backend_env.get("MONGO_URL")
SOURCE_DB = os.environ.get("DB_NAME") or _backend_env.get("DB_NAME")
TARGET_DB = "albarka_dryrun"
CONFIRM = (os.environ.get("MIGRATE_CONFIRM_TOKEN")
           or _backend_env.get("MIGRATE_CONFIRM_TOKEN")
           or "MIGRATE-EMERGENT-TO-ATLAS-2026")
MIGRATE = f"{API}/_admin/migrate-mongo"
BACKUP_ROOT = Path("/tmp/albarka-migrate-backups")
TIMEOUT = 150


def _payload(**over):
    body = {
        "target_mongo_url": MONGO_URL,
        "target_db_name": TARGET_DB,
        "confirm_token": CONFIRM,
        "dry_run": False,
        "backup": False,
    }
    body.update(over)
    return body


@pytest.fixture(scope="module")
def target_client():
    if not MONGO_URL:
        pytest.skip("MONGO_URL missing in /app/backend/.env")
    c = MongoClient(MONGO_URL, serverSelectionTimeoutMS=20000)
    yield c
    c.close()


# ---------- /api/_diag/db (now protected) ----------
class TestDiagDb:
    def test_no_token_rejected(self):
        r = requests.get(f"{API}/_diag/db", timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"
        blob = r.text.lower()
        for leak in ("mongo_host", "collections", "db_name", "mongodb+srv"):
            assert leak not in blob, f"'{leak}' leaked in unauthenticated /_diag/db"

    def test_bad_token_rejected(self):
        r = requests.get(f"{API}/_diag/db",
                         headers={"Authorization": "Bearer not-a-jwt"}, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:300]}"

    def test_client_forbidden(self, client1):
        s, _ = client1
        r = s.get(f"{API}/_diag/db", timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:300]}"

    def test_superviseur_gets_same_payload(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{API}/_diag/db", timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in ("mongo_scheme", "mongo_host", "db_name", "collections"):
            assert key in d, f"missing {key} in {d}"
        assert isinstance(d["collections"], dict) and d["collections"]
        assert d["db_name"] == SOURCE_DB
        host = d["mongo_host"]
        assert "@" not in host and ":" not in host and "//" not in host, host
        blob = r.text.lower()
        for secret in ("password", "albarka_app_user", "mongodb+srv://"):
            assert secret not in blob, f"'{secret}' leaked in /_diag/db response"
        assert d["mongo_scheme"].startswith("mongodb")


# ---------- inventory RBAC ----------
class TestInventoryRbac:
    def test_no_token_rejected(self):
        r = requests.get(f"{MIGRATE}/inventory", timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

    def test_bad_token_rejected(self):
        r = requests.get(f"{MIGRATE}/inventory",
                         headers={"Authorization": "Bearer not-a-jwt"}, timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

    def test_client_forbidden(self, client1):
        s, _ = client1
        r = s.get(f"{MIGRATE}/inventory", timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"

    def test_superviseur_inventory(self, superviseur):
        s, _ = superviseur
        r = s.get(f"{MIGRATE}/inventory", timeout=90)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["db_name"] == SOURCE_DB
        assert "@" not in d["mongo_host"]
        assert isinstance(d["collections"], dict) and d["collections"].get("users", 0) >= 1
        assert isinstance(d["users_preview"], list) and d["users_preview"]
        for u in d["users_preview"]:
            assert "email" in u
            assert "password_hash" not in u and "_id" not in u


# ---------- POST guards ----------
class TestMigrateGuards:
    def test_no_token_rejected(self):
        r = requests.post(MIGRATE, json=_payload(dry_run=True), timeout=60)
        assert r.status_code in (401, 403), f"{r.status_code} {r.text[:200]}"

    def test_client_forbidden(self, client1):
        s, _ = client1
        r = s.post(MIGRATE, json=_payload(dry_run=True), timeout=60)
        assert r.status_code == 403, f"{r.status_code} {r.text[:200]}"

    def test_wrong_confirm_token(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(confirm_token="WRONG-TOKEN-123",
                                          dry_run=True), timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        assert "confirm_token" in r.json().get("detail", "")

    def test_target_same_as_source(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(target_db_name=SOURCE_DB, dry_run=True), timeout=60)
        assert r.status_code == 400, f"{r.status_code} {r.text[:300]}"
        assert "identique" in r.json().get("detail", "").lower()

    def test_invalid_payload_422(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json={"confirm_token": CONFIRM}, timeout=60)
        assert r.status_code == 422, f"{r.status_code} {r.text[:200]}"

    def test_unreachable_target_502(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(
            target_mongo_url="mongodb://127.0.0.1:59999/?directConnection=true",
            dry_run=True), timeout=120)
        assert r.status_code == 502, f"{r.status_code} {r.text[:300]}"


# ---------- dry-run ----------
class TestDryRun:
    def test_dry_run_writes_nothing(self, superviseur, target_client):
        s, _ = superviseur
        col = target_client[TARGET_DB]["contact_groups"]
        col.drop()
        r = s.post(MIGRATE, json=_payload(dry_run=True, backup=False,
                                          only_collections=["contact_groups", "users"]),
                   timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        rep = r.json()
        assert rep["dry_run"] is True
        assert rep["backup_dir"] is None
        assert rep["target"]["db"] == TARGET_DB
        assert rep["source"]["db"] == SOURCE_DB
        assert rep["collections"], "empty collections report"
        for name, st in rep["collections"].items():
            assert st["inserted"] == 0 and st["updated"] == 0, (name, st)
            assert st["errors"] == 0
            assert st["total_source"] >= 0
        assert col.count_documents({}) == 0, "dry_run wrote documents into target"


# ---------- ephemeral collections skipped by default ----------
class TestEphemeralSkip:
    def test_default_run_skips_otps_and_cron_runs(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(dry_run=True, backup=False), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        keys = set(r.json()["collections"].keys())
        assert "otps" not in keys, "otps must be skipped by default"
        assert "cron_runs" not in keys, "cron_runs must be skipped by default"
        assert "users" in keys, keys

    def test_explicit_only_collections_overrides_skip(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(dry_run=True, backup=False,
                                          only_collections=["otps"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        rep = r.json()["collections"]
        assert list(rep.keys()) == ["otps"], rep
        assert rep["otps"]["total_source"] >= 0


# ---------- selective + idempotence ----------
class TestSelectiveAndIdempotence:
    def test_only_collections_scope(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(dry_run=True, backup=False,
                                          only_collections=["users"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        assert list(r.json()["collections"].keys()) == ["users"]

    def test_skip_collections_scope(self, superviseur):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(dry_run=True, backup=False,
                                          skip_collections=["users"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        keys = r.json()["collections"].keys()
        assert "users" not in keys and len(keys) > 1

    def test_real_migration_idempotent(self, superviseur, target_client):
        s, _ = superviseur
        target_client[TARGET_DB]["report_templates"].drop()
        src_count = target_client[SOURCE_DB]["report_templates"].count_documents({})

        r1 = s.post(MIGRATE, json=_payload(only_collections=["report_templates"]),
                    timeout=TIMEOUT)
        assert r1.status_code == 200, r1.text
        st1 = r1.json()["collections"]["report_templates"]
        assert st1["total_source"] == src_count
        assert st1["inserted"] == src_count, st1
        assert st1["errors"] == 0
        assert target_client[TARGET_DB]["report_templates"].count_documents({}) == src_count

        r2 = s.post(MIGRATE, json=_payload(only_collections=["report_templates"]),
                    timeout=TIMEOUT)
        assert r2.status_code == 200, r2.text
        st2 = r2.json()["collections"]["report_templates"]
        assert st2["inserted"] == 0, f"second run re-inserted: {st2}"
        assert st2["skipped"] == src_count, st2
        assert target_client[TARGET_DB]["report_templates"].count_documents({}) == src_count
        ids = [d.get("id") for d in target_client[TARGET_DB]["report_templates"].find({}, {"id": 1})]
        assert len(ids) == len(set(ids))


# ---------- backups: /tmp location + password_hash redaction ----------
class TestBackupRedaction:
    def test_users_backup_in_tmp_and_redacted(self, superviseur, target_client):
        s, _ = superviseur
        r = s.post(MIGRATE, json=_payload(backup=True, only_collections=["users"]),
                   timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        rep = r.json()
        bdir = rep.get("backup_dir")
        assert bdir, "backup=True should produce a backup_dir"
        assert bdir.startswith(str(BACKUP_ROOT)), f"backup outside /tmp: {bdir}"
        assert "/app/" not in bdir, f"backup written inside repo: {bdir}"
        assert rep["collections"]["users"]["errors"] == 0

        f = Path(bdir) / "users.json"
        assert f.exists(), f"missing {f}"
        docs = json.loads(f.read_text(encoding="utf-8"))
        assert isinstance(docs, list) and docs
        for d in docs:
            assert "password_hash" in d, f"user doc without password_hash key: {d.get('email')}"
            assert d["password_hash"] == "[REDACTED]", (
                f"clear password_hash in backup for {d.get('email')}")
        raw = f.read_text(encoding="utf-8")
        assert "$2b$" not in raw and "$2a$" not in raw, "bcrypt hash present in backup file"

    def test_no_backups_left_inside_repo(self):
        repo_backups = Path("/app/backend/backups")
        leftovers = sorted(p.name for p in repo_backups.glob("mongo-*")) if repo_backups.exists() else []
        assert not leftovers, f"backups still inside repo: {leftovers}"


# ---------- admin/superviseur protection ----------
class TestAdminProtection:
    def test_protected_password_hash_preserved(self, superviseur, target_client):
        s, _ = superviseur
        src_users = target_client[SOURCE_DB]["users"]
        tgt_users = target_client[TARGET_DB]["users"]
        protected_email = "admin@sawalismartsystems.com"
        src = src_users.find_one({"email": protected_email})
        if not src:
            pytest.fail(f"source db has no {protected_email} user — cannot test protection")

        sentinel = "$2b$12$SENTINEL_TARGET_HASH_DO_NOT_OVERWRITE_0000000000"
        assert src.get("password_hash") != sentinel
        tgt_users.update_one(
            {"email": protected_email},
            {"$set": {"email": protected_email, "password_hash": sentinel,
                      "is_active": False, "full_name": "STALE"}},
            upsert=True,
        )

        r = s.post(MIGRATE, json=_payload(only_collections=["users"]), timeout=TIMEOUT)
        assert r.status_code == 200, r.text
        st = r.json()["collections"]["users"]
        assert st["errors"] == 0, st
        assert st["protected_partial"] >= 1, st

        after = tgt_users.find_one({"email": protected_email})
        assert after["password_hash"] == sentinel, "protected password_hash was overwritten"
        assert after["is_active"] is False, "protected is_active was overwritten"
        assert after["full_name"] == src.get("full_name"), "non-protected field not migrated"

        other = src_users.find_one({"email": {"$nin": list(
            ["admin@sawalismartsystems.com", "superviseur@albarka-demo.bf"])}})
        if other:
            t_other = tgt_users.find_one({"email": other["email"]})
            assert t_other is not None
            assert t_other.get("password_hash") == other.get("password_hash")
