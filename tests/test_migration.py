"""Only temporary synthetic databases are used for legacy migration tests."""

import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stylemate_memory import contracts as c
from stylemate_memory.errors import StyleMateError
from stylemate_memory.store import MemoryStore


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "synthetic-legacy.sqlite3"
        self.now = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        self.request = self.store.start_request("u1", input_id="legacy-input", text="old input", timezone="UTC")
        self.store.apply_batch("u1", self.request["id"], batch_id="old-create", actions=[{
            "op": "create", "feature": "fit", "values": ["Relaxed"],
            "content": "발표 때 여유로운 핏을 선호", "confirmed": True,
            "conditions": {"occasion": "발표"}, "selector": {"garment_type": "Pants"},
            "valid_from": (self.now - timedelta(days=1)).isoformat(),
            "valid_until": (self.now + timedelta(days=3)).isoformat(),
            "retention_until": (self.now + timedelta(days=4)).isoformat(),
            "evidence_ref": "old-input-reference",
        }])
        short = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.store.apply_batch("u1", self.request["id"], batch_id="old-promote", actions=[{
            "op": "promote", "memory_id": short["id"], "expected_version": short["version"],
            "evidence_ref": "old-review-reference", "consent_ref": "consent-for-presentation-only",
        }])
        self.store.apply_batch("u1", self.request["id"], batch_id="old-material", actions=[{
            "op": "create", "feature": "material", "values": ["Knit"],
            "content": "니트 소재 느낌", "origin": "inferred", "evidence_ref": "missing-quote",
            "conditions": {"activity": "산책", "weather": "맑음"},
            "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
        }])
        self.original = self.store.snapshot("u1", self.request["id"])

    def migrate(self):
        return self.store.migrate_legacy("u1", self.request["id"], registry_version=c.V1_REGISTRY_VERSION)

    def snapshot(self, request):
        return self.store.snapshot("u1", request["id"], contract_version=c.CONTRACT_VERSION)

    def make_pre_v1_schema(self):
        """Remove only empty v1 additions from this test's synthetic database."""
        self.store.close()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name GLOB 'v1_*'"
            )]
            for table in tables:
                conn.execute(f"DROP TABLE {table}")
            conn.execute("DROP INDEX requests_owner_idx")
            for column in ("contract_version", "registry_version", "mode", "targets_json", "final_selection_json"):
                conn.execute(f"ALTER TABLE requests DROP COLUMN {column}")
            conn.execute("PRAGMA user_version=0")

    def test_semantics_consent_periods_references_and_families_are_preserved(self):
        self.make_pre_v1_schema()
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        request = self.migrate()
        self.assertNotEqual(request["id"], self.request["id"])
        migrated = self.snapshot(request)
        self.assertEqual(len(migrated["memories"]), len(self.original["memories"]))
        original_by_id = {item["id"]: item for item in self.original["memories"]}
        for item in migrated["memories"]:
            original = original_by_id[item["id"]]
            self.assertEqual(item["legacy"]["original"], original)
            for field in ("content", "confirmed", "origin", "status", "version", "family_id", "scope",
                          "valid_from", "valid_until", "created_at", "retention_until", "polarity", "strength"):
                self.assertEqual(item[field], original[field], field)
            self.assertEqual(item["legacy"]["registry_version"], c.LEGACY_REGISTRY_VERSION)
            self.assertEqual(item["legacy"]["mapping_status"], "requires_review")
            self.assertEqual(item["legacy"]["evidence_status"], "reference_only")
            self.assertIsNone(item["confirmation_ref"])
            self.assertIsNone(item["consent_ref"])
            self.assertEqual(item["source_refs"], [])
            self.assertEqual(set(item), set(c.MemoryItem.__required_keys__) | {"legacy"})
            self.assertEqual(item["request_id"], request["id"] if item["scope"] == "short_term" else None)
        # No new quote, binding, consent, confirmation or trusted user event is fabricated.
        for key in ("evidence", "bindings", "confirmations", "consents", "links"):
            self.assertEqual(migrated[key], [])
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_user_events").fetchone()[0], 0)
        for field in ("created_at", "updated_at", "retention_until", "revision", "status", "timezone"):
            self.assertEqual(request[field], self.original["request"][field])
        self.assertEqual(self.store.snapshot("u1", self.request["id"]), self.original)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_restart_reexecution_and_shared_long_term_rows_are_idempotent(self):
        request = self.migrate()
        before = self.snapshot(request)
        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.migrate(), request)
        self.assertEqual(self.snapshot(request), before)
        second = self.store.start_request("u1", input_id="other-request", text="new purpose", timezone="UTC")
        second_v1 = self.store.migrate_legacy("u1", second["id"], registry_version=c.V1_REGISTRY_VERSION)
        second_snapshot = self.snapshot(second_v1)
        self.assertEqual(len(second_snapshot["memories"]), 1)
        self.assertEqual(second_snapshot["memories"][0]["scope"], "long_term")
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_memories").fetchone()[0], 3)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_legacy_migrations").fetchone()[0], 2)
        other = self.store.start_request("u2", input_id="other-user", text="different user", timezone="UTC")
        other_v1 = self.store.migrate_legacy("u2", other["id"], registry_version=c.V1_REGISTRY_VERSION)
        self.assertEqual(self.store.snapshot("u2", other_v1["id"], contract_version=c.CONTRACT_VERSION)["memories"], [])

    def test_mid_migration_failures_rollback_all_copies_and_retry(self):
        original_requests = self.store.connection.execute("SELECT count(*) FROM requests").fetchone()[0]
        for fail_at in ("migration_after_memory", "migration_before_commit"):
            def fail(stage):
                if stage == fail_at:
                    raise RuntimeError("synthetic migration failure")
            self.store._failure_hook = fail
            with self.subTest(stage=fail_at):
                with self.assertRaises(StyleMateError) as caught:
                    self.migrate()
                self.assertEqual(caught.exception.code, "storage_failed")
                self.assertEqual(self.store.connection.execute("SELECT count(*) FROM requests").fetchone()[0], original_requests)
                self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_objects").fetchone()[0], 0)
                self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_legacy_migrations").fetchone()[0], 0)
                self.assertEqual(self.store.snapshot("u1", self.request["id"]), self.original)
        self.store._failure_hook = None
        self.assertEqual(len(self.snapshot(self.migrate())["memories"]), 3)

    def test_schema_failure_rollback_preserves_old_database(self):
        self.make_pre_v1_schema()
        def fail(stage):
            if stage == "v1_schema_before_commit":
                raise RuntimeError("synthetic DDL failure")
        with self.assertRaisesRegex(RuntimeError, "DDL failure"):
            MemoryStore(self.path, clock=lambda: self.now, failure_hook=fail)
        with closing(sqlite3.connect(self.path)) as conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(requests)")}
            self.assertNotIn("contract_version", columns)
            self.assertEqual(conn.execute("PRAGMA user_version").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT count(*) FROM memories").fetchone()[0], 3)
            self.assertIsNone(conn.execute("SELECT name FROM sqlite_master WHERE name='v1_objects'").fetchone())
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.assertEqual(len(self.snapshot(self.migrate())["memories"]), 3)

    def test_changed_source_requires_explicit_reconciliation(self):
        request = self.migrate()
        before = self.snapshot(request)
        self.store.apply_batch("u1", self.request["id"], batch_id="later", actions=[{
            "op": "create", "feature": "color", "values": ["Navy"],
            "content": "다른 내용", "evidence_ref": "later-input",
        }])
        with self.assertRaises(StyleMateError) as caught:
            self.migrate()
        self.assertEqual(caught.exception.code, "version_conflict")
        self.assertEqual(self.snapshot(request), before)

    def test_unavailable_original_evidence_never_becomes_a_user_quote(self):
        missing = self.original["memories"][0]["id"]
        self.store.connection.execute("UPDATE memories SET evidence_ref='' WHERE id=?", (missing,))
        migrated = self.snapshot(self.migrate())
        item = next(item for item in migrated["memories"] if item["id"] == missing)
        self.assertEqual(item["legacy"]["evidence_status"], "missing")
        self.assertEqual(item["legacy"]["original"]["evidence_ref"], "")
        self.assertEqual(migrated["evidence"], [])
        # Out-of-contract legacy conditions remain intact in original, never
        # presented as newly verified conditions in the v1 projection.
        material = next(item for item in migrated["memories"] if item["legacy"]["original"]["feature"] == "material")
        self.assertEqual(material["legacy"]["original"]["values"], ["Knit"])
        self.assertEqual(material["legacy"]["original"]["conditions"]["weather"], "맑음")
        self.assertNotIn("weather", material["conditions"])
        self.assertEqual(migrated["bindings"], [])

    def test_ownership_and_contract_are_checked_before_copying(self):
        with self.assertRaises(StyleMateError) as caught:
            self.store.migrate_legacy("u2", self.request["id"], registry_version=c.V1_REGISTRY_VERSION)
        self.assertEqual(caught.exception.code, "not_found")
        with self.assertRaises(StyleMateError) as caught:
            self.store.migrate_legacy("u1", self.request["id"], registry_version=c.LEGACY_REGISTRY_VERSION)
        self.assertEqual(caught.exception.code, "unsupported_contract")
        request = self.migrate()
        with self.assertRaises(StyleMateError) as caught:
            self.store.migrate_legacy("u1", request["id"], registry_version=c.V1_REGISTRY_VERSION)
        self.assertEqual(caught.exception.code, "unsupported_contract")


if __name__ == "__main__":
    unittest.main()
