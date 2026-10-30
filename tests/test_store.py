import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stylemate_memory import contracts as c
from stylemate_memory.errors import StyleMateError
from stylemate_memory.store import MemoryStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / "memory.sqlite3"
        self.current = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)

        def clock():
            return self.current

        self.store = MemoryStore(self.path, clock=clock)
        self.request = self.store.start_request(
            "u1", input_id="input-1", text="presentation outfit", timezone="Asia/Seoul"
        )

    def tearDown(self):
        self.store.close()
        self.tempdir.cleanup()

    def action(self, **extra):
        result = {
            "op": "create",
            "feature": "fit",
            "values": ["Relaxed"],
            "content": "여유로운 핏을 선호",
            "evidence_ref": "input-1",
        }
        result.update(extra)
        return result

    def test_empty_snapshot_and_reconnect(self):
        snapshot = self.store.snapshot("u1", self.request["id"])
        self.assertEqual(snapshot["memories"], [])
        self.assertEqual(snapshot["profile_revision"], 0)
        self.store.close()
        reopened = MemoryStore(self.path, clock=lambda: self.current)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.snapshot("u1", self.request["id"])["memories"], [])

    def test_create_confirm_promote_and_profile_revision(self):
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="b1",
            actions=[self.action(origin="inferred")],
            expected_request_revision=1,
            expected_profile_revision=0,
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.assertFalse(memory["confirmed"])
        self.assertEqual(memory["status"], "candidate")
        with self.assertRaisesRegex(StyleMateError, "inferred"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="bad-confirm",
                actions=[
                    self.action(
                        origin="inferred",
                        confirmed=True,
                    )
                ],
            )
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="b2",
            actions=[
                {
                    "op": "confirm",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "input-1-confirmed",
                }
            ],
            expected_request_revision=result["request_revision"],
            expected_profile_revision=0,
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="b3",
            actions=[
                {
                    "op": "promote",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "input-1-promote",
                    "consent_ref": "consent-1",
                }
            ],
            expected_request_revision=result["request_revision"],
            expected_profile_revision=0,
        )
        self.assertEqual(result["profile_revision"], 1)
        memory = next(
            item for item in self.store.snapshot("u1", self.request["id"])["memories"]
            if item["scope"] == "long_term"
        )
        self.assertIsNone(memory["request_id"])
        self.assertEqual(memory["scope"], "long_term")
        self.assertTrue(memory["confirmed"])

    def test_batch_is_atomic_and_failure_hook_rolls_back(self):
        def failure(stage):
            if stage == "after_action":
                raise RuntimeError("injected")

        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.current, failure_hook=failure)
        with self.assertRaisesRegex(StyleMateError, "rolled back"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="atomic",
                actions=[self.action(), self.action(feature="color", values=["Navy"])],
            )
        snapshot = self.store.snapshot("u1", self.request["id"])
        self.assertEqual(snapshot["memories"], [])
        self.assertEqual(snapshot["request"]["revision"], 1)

    def test_idempotent_replay_and_different_body_conflict(self):
        original = self.store.apply_batch(
            "u1", self.request["id"], batch_id="same", actions=[self.action()]
        )
        replay = self.store.apply_batch(
            "u1", self.request["id"], batch_id="same", actions=[self.action()]
        )
        self.assertEqual(original, replay)
        with self.assertRaisesRegex(StyleMateError, "different actions"):
            self.store.apply_batch(
                "u1", self.request["id"], batch_id="same", actions=[self.action(feature="color")]
            )

    def test_ownership_and_revision_boundaries(self):
        with self.assertRaisesRegex(StyleMateError, "not found"):
            self.store.get_request("u2", self.request["id"])
        other = self.store.start_request("u2", input_id="input-2", text="other", timezone="UTC")
        with self.assertRaisesRegex(StyleMateError, "not found"):
            self.store.snapshot("u1", other["id"])
        with self.assertRaisesRegex(StyleMateError, "revision"):
            self.store.apply_batch(
                "u1", self.request["id"], batch_id="stale", actions=[self.action()], expected_request_revision=99
            )
        self.assertEqual(self.store.snapshot("u1", self.request["id"])["memories"], [])

    def test_short_term_only_until_and_request_expiry(self):
        start = self.current
        valid_from = (start + timedelta(days=1)).isoformat()
        valid_until = (start + timedelta(days=2)).isoformat()
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="period",
            actions=[self.action(valid_from=valid_from, valid_until=valid_until)],
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.assertEqual(memory["valid_from"], valid_from)
        self.assertEqual(memory["valid_until"], valid_until)
        self.current = start + timedelta(days=31)
        with self.assertRaisesRegex(StyleMateError, "retention"):
            self.store.snapshot("u1", self.request["id"])

    def test_withdraw_and_delete_close_family_and_remove_rows(self):
        result = self.store.apply_batch(
            "u1", self.request["id"], batch_id="create", actions=[self.action()]
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        withdrawn = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="withdraw",
            actions=[
                {
                    "op": "withdraw",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "withdraw-1",
                }
            ],
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.assertEqual(memory["status"], "withdrawn")
        deleted = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="delete",
            actions=[
                {
                    "op": "delete",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "delete-1",
                }
            ],
        )
        self.assertIn(memory["id"], deleted["memory_ids"])
        self.assertEqual(self.store.snapshot("u1", self.request["id"])["memories"], [])
        with closing(sqlite3.connect(self.path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM memories").fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM events WHERE memory_id=?", (memory["id"],)).fetchone()[0], 0)

    def test_other_request_cannot_mutate_short_term_and_snapshot_is_request_local(self):
        other = self.store.start_request(
            "u1", input_id="input-2", text="another request", timezone="Asia/Seoul"
        )
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="short-create",
            actions=[self.action(confirmed=True, status="active")],
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        mutation_actions = [
            {
                "op": "confirm",
                "memory_id": memory["id"],
                "expected_version": memory["version"],
                "evidence_ref": "input-2-confirm",
            },
            {
                "op": "promote",
                "memory_id": memory["id"],
                "expected_version": memory["version"],
                "evidence_ref": "input-2-promote",
                "consent_ref": "consent-2",
            },
            {
                "op": "replace",
                "memory_id": memory["id"],
                "expected_version": memory["version"],
                "evidence_ref": "input-2-replace",
                "feature": "color",
                "values": ["Navy"],
                "content": "navy",
            },
            {
                "op": "withdraw",
                "memory_id": memory["id"],
                "expected_version": memory["version"],
                "evidence_ref": "input-2-withdraw",
            },
            {
                "op": "delete",
                "memory_id": memory["id"],
                "expected_version": memory["version"],
                "evidence_ref": "input-2-delete",
            },
        ]
        for index, action in enumerate(mutation_actions):
            with self.subTest(operation=action["op"]):
                with self.assertRaisesRegex(StyleMateError, "another request"):
                    self.store.apply_batch("u1", other["id"], batch_id=f"foreign-{index}", actions=[action])
        self.assertEqual(self.store.snapshot("u1", other["id"])["memories"], [])

    def test_promote_requires_confirmed_short_and_preserves_source(self):
        with self.assertRaisesRegex(StyleMateError, "direct long-term"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="long-candidate",
                actions=[
                    self.action(
                        scope="long_term",
                        consent_ref="consent",
                        confirmed=False,
                        status="candidate",
                    )
                ],
            )
        self.store.apply_batch(
            "u1", self.request["id"], batch_id="candidate", actions=[self.action(origin="inferred")]
        )
        candidate = self.store.snapshot("u1", self.request["id"])["memories"][0]
        with self.assertRaisesRegex(StyleMateError, "confirmed"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="candidate-promote",
                actions=[
                    {
                        "op": "promote",
                        "memory_id": candidate["id"],
                        "expected_version": candidate["version"],
                        "evidence_ref": "promote",
                        "consent_ref": "consent",
                    }
                ],
            )
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="confirmed",
            actions=[
                {
                    "op": "confirm",
                    "memory_id": candidate["id"],
                    "expected_version": candidate["version"],
                    "evidence_ref": "confirm",
                }
            ],
        )
        candidate = self.store.snapshot("u1", self.request["id"])["memories"][0]
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="promote",
            actions=[
                {
                    "op": "promote",
                    "memory_id": candidate["id"],
                    "expected_version": candidate["version"],
                    "evidence_ref": "promote",
                    "consent_ref": "consent",
                }
            ],
        )
        memories = self.store.snapshot("u1", self.request["id"])["memories"]
        source = next(item for item in memories if item["scope"] == "short_term")
        promoted = next(item for item in memories if item["scope"] == "long_term")
        self.assertNotEqual(source["id"], promoted["id"])
        self.assertEqual(source["family_id"], promoted["family_id"])
        self.assertEqual(source["status"], "active")
        self.assertEqual(source["request_id"], self.request["id"])
        self.assertEqual(result["memory_ids"], [promoted["id"]])

    def test_same_meaning_replace_is_noop_and_active_row_survives(self):
        self.store.apply_batch(
            "u1", self.request["id"], batch_id="replace-create", actions=[self.action(confirmed=True, status="active")]
        )
        before = self.store.snapshot("u1", self.request["id"])["memories"][0]
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="same-replace",
            actions=[
                {
                    "op": "replace",
                    "memory_id": before["id"],
                    "expected_version": before["version"],
                    "evidence_ref": "same",
                    "feature": before["feature"],
                    "values": before["values"],
                    "content": before["content"],
                }
            ],
        )
        after = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.assertEqual(result["memory_ids"], [before["id"]])
        self.assertEqual(after["id"], before["id"])
        self.assertEqual(after["version"], before["version"])
        self.assertEqual(after["status"], "active")

    def test_replace_existing_meaning_supersedes_source_atomically(self):
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="source-a",
            actions=[self.action(content="source A", confirmed=True, status="active")],
        )
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="target-b",
            actions=[self.action(content="target B", values=["Slim"], confirmed=True, status="active")],
        )
        memories = self.store.snapshot("u1", self.request["id"])["memories"]
        source = next(item for item in memories if item["content"] == "source A")
        target = next(item for item in memories if item["content"] == "target B")
        result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="replace-a-with-b",
            actions=[
                {
                    "op": "replace",
                    "memory_id": source["id"],
                    "expected_version": source["version"],
                    "evidence_ref": "replace",
                    "feature": target["feature"],
                    "values": target["values"],
                    "content": target["content"],
                }
            ],
        )
        memories = self.store.snapshot("u1", self.request["id"])["memories"]
        source_after = next(item for item in memories if item["id"] == source["id"])
        target_after = next(item for item in memories if item["id"] == target["id"])
        self.assertEqual(result["memory_ids"], [target["id"]])
        self.assertEqual(source_after["status"], "superseded")
        self.assertEqual(target_after["status"], "active")

    def test_replace_cannot_change_short_or_long_scope(self):
        self.store.apply_batch(
            "u1", self.request["id"], batch_id="scope-short", actions=[self.action(confirmed=True, status="active")]
        )
        short = self.store.snapshot("u1", self.request["id"])["memories"][0]
        with self.assertRaisesRegex(StyleMateError, "scope"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="scope-short-replace",
                actions=[
                    {
                        "op": "replace",
                        "memory_id": short["id"],
                        "expected_version": short["version"],
                        "evidence_ref": "scope",
                        "scope": "long_term",
                        "feature": "fit",
                        "values": ["Slim"],
                        "content": "long scope",
                        "consent_ref": "consent",
                    }
                ],
            )

    def test_delete_receipt_is_opaque_and_reusable_after_ttl(self):
        self.store.apply_batch("u1", self.request["id"], batch_id="create-for-delete", actions=[self.action()])
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        deleted = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="delete-once",
            actions=[
                {
                    "op": "delete",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "delete",
                }
            ],
        )
        self.assertEqual(deleted["memory_ids"], [memory["id"]])
        columns = [row[1] for row in self.store.connection.execute("PRAGMA table_info(deletion_receipts)")]
        self.assertNotIn("memory_ids_json", columns)
        self.assertNotIn("request_body_digest", columns)
        with self.assertRaisesRegex(StyleMateError, "different actions"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="delete-once",
                actions=[
                    {
                        "op": "delete",
                        "memory_id": memory["id"],
                        "expected_version": memory["version"],
                        "evidence_ref": "different-replay",
                    }
                ],
            )
        replay = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="delete-once",
            actions=[
                {
                    "op": "delete",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "delete",
                }
            ],
        )
        self.assertEqual(replay["memory_ids"], [])
        with self.assertRaisesRegex(StyleMateError, "recovery"):
            self.store.apply_batch(
                "u1", self.request["id"], batch_id="create-for-delete", actions=[self.action(feature="color")]
            )
        self.current += timedelta(hours=25)
        self.store.apply_batch(
            "u1", self.request["id"], batch_id="create-for-delete", actions=[self.action(feature="color")]
        )

    def test_delete_request_and_prune_reserve_input_for_ttl(self):
        self.store.apply_batch("u1", self.request["id"], batch_id="for-delete-request", actions=[self.action()])
        self.store.delete_request("u1", self.request["id"])
        with self.assertRaisesRegex(StyleMateError, "recovery"):
            self.store.start_request("u1", input_id="input-1", text="presentation outfit", timezone="Asia/Seoul")
        replacement_request = self.store.start_request(
            "u1", input_id="input-new", text="new request", timezone="Asia/Seoul"
        )
        with self.assertRaisesRegex(StyleMateError, "recovery"):
            self.store.apply_batch(
                "u1",
                replacement_request["id"],
                batch_id="for-delete-request",
                actions=[self.action(feature="color")],
            )
        self.store.delete_request("u1", replacement_request["id"])
        self.current += timedelta(hours=25)
        recreated = self.store.start_request(
            "u1", input_id="input-1", text="presentation outfit", timezone="Asia/Seoul"
        )
        self.assertNotEqual(recreated["id"], self.request["id"])
        self.store.apply_batch("u1", recreated["id"], batch_id="expire", actions=[self.action()])
        self.current += timedelta(days=31)
        self.assertEqual(self.store.prune_expired("u1")["requests"], 1)
        with self.assertRaisesRegex(StyleMateError, "recovery"):
            self.store.start_request("u1", input_id="input-1", text="presentation outfit", timezone="Asia/Seoul")

    def test_delete_receipt_batch_is_tombstoned_before_request_cascade(self):
        self.store.apply_batch("u1", self.request["id"], batch_id="delete-source", actions=[self.action()])
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="delete-receipt",
            actions=[
                {
                    "op": "delete",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "delete",
                }
            ],
        )
        self.store.delete_request("u1", self.request["id"])
        new_request = self.store.start_request(
            "u1", input_id="new-after-delete", text="new", timezone="Asia/Seoul"
        )
        with self.assertRaisesRegex(StyleMateError, "recovery"):
            self.store.apply_batch(
                "u1", new_request["id"], batch_id="delete-receipt", actions=[self.action()]
            )

    def test_expired_start_retry_is_safe_and_timezone_is_in_idempotency_digest(self):
        with self.assertRaisesRegex(StyleMateError, "different text or timezone"):
            self.store.start_request(
                "u1", input_id="input-1", text="presentation outfit", timezone="UTC"
            )
        self.current += timedelta(days=31)
        with self.assertRaisesRegex(StyleMateError, "expired"):
            self.store.start_request(
                "u1", input_id="input-1", text="presentation outfit", timezone="Asia/Seoul"
            )
        self.assertEqual(self.store.get_request("u1", self.request["id"])["status"], "expired")

    def test_unknown_fields_non_json_and_long_slot_are_safe_errors(self):
        with self.assertRaisesRegex(StyleMateError, "unknown"):
            self.store.apply_batch(
                "u1", self.request["id"], batch_id="unknown", actions=[self.action(unexpected="x")]
            )
        with self.assertRaises(StyleMateError):
            self.store.apply_batch(
                "u1", self.request["id"], batch_id="non-json", actions=[self.action(values=[object()])]
            )
        with self.assertRaisesRegex(StyleMateError, "slot_id"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="long-slot",
                actions=[
                    self.action(
                        scope="long_term",
                        confirmed=True,
                        status="active",
                        consent_ref="consent",
                        selector={"garment_type": "Pants", "slot_id": "pants-1"},
                    )
                ],
            )

    def test_confirmation_and_cas_numbers_have_strict_types(self):
        with self.assertRaisesRegex(StyleMateError, "boolean"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="string-confirmed",
                actions=[self.action(confirmed="false")],
            )
        self.assertEqual(self.store.snapshot("u1", self.request["id"])["memories"], [])
        self.store.apply_batch("u1", self.request["id"], batch_id="cas-source", actions=[self.action()])
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        for index, invalid_version in enumerate((True, 1.0, "1")):
            with self.subTest(expected_version=invalid_version):
                with self.assertRaisesRegex(StyleMateError, "expected_version"):
                    self.store.apply_batch(
                        "u1",
                        self.request["id"],
                        batch_id=f"bad-item-version-{index}",
                        actions=[
                            {
                                "op": "confirm",
                                "memory_id": memory["id"],
                                "expected_version": invalid_version,
                                "evidence_ref": "confirm",
                            }
                        ],
                    )
        for index, invalid_revision in enumerate((True, 1.0, "1")):
            with self.subTest(expected_revision=invalid_revision):
                with self.assertRaisesRegex(StyleMateError, "revision"):
                    self.store.apply_batch(
                        "u1",
                        self.request["id"],
                        batch_id=f"bad-request-revision-{index}",
                        actions=[self.action(feature="color")],
                        expected_request_revision=invalid_revision,
                    )
        short_slot_result = self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="short-slot",
            actions=[
                self.action(
                    confirmed=True,
                    status="active",
                    selector={"garment_type": "Pants", "slot_id": "pants-1"},
                )
            ],
        )
        short_slot_id = short_slot_result["memory_ids"][0]
        short_slot = next(
            item
            for item in self.store.snapshot("u1", self.request["id"])["memories"]
            if item["id"] == short_slot_id
        )
        with self.assertRaisesRegex(StyleMateError, "slot_id"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="promote-slot",
                actions=[
                    {
                        "op": "promote",
                        "memory_id": short_slot["id"],
                        "expected_version": short_slot["version"],
                        "evidence_ref": "promote-slot",
                        "consent_ref": "consent-slot",
                    }
                ],
            )
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="long-ok",
            actions=[
                self.action(
                    feature="color",
                    scope="long_term",
                    confirmed=True,
                    status="active",
                    consent_ref="consent-long",
                )
            ],
        )
        long_memory = next(
            item
            for item in self.store.snapshot("u1", self.request["id"])["memories"]
            if item["scope"] == "long_term"
        )
        with self.assertRaisesRegex(StyleMateError, "slot_id"):
            self.store.apply_batch(
                "u1",
                self.request["id"],
                batch_id="replace-long-slot",
                actions=[
                    {
                        "op": "replace",
                        "memory_id": long_memory["id"],
                        "expected_version": long_memory["version"],
                        "evidence_ref": "replace-long-slot",
                        "consent_ref": "consent-long-2",
                        "feature": "color",
                        "values": ["Navy"],
                        "content": "new long color",
                        "selector": {"slot_id": "pants-1"},
                    }
                ],
            )

    def test_closed_retention_never_extends_original_period(self):
        original_retention = (self.current + timedelta(days=2)).isoformat()
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="short-retention",
            actions=[self.action(retention_until=original_retention, confirmed=True, status="active")],
        )
        memory = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.current += timedelta(days=1)
        self.store.apply_batch(
            "u1",
            self.request["id"],
            batch_id="withdraw-short",
            actions=[
                {
                    "op": "withdraw",
                    "memory_id": memory["id"],
                    "expected_version": memory["version"],
                    "evidence_ref": "withdraw",
                }
            ],
        )
        withdrawn = self.store.snapshot("u1", self.request["id"])["memories"][0]
        self.assertLessEqual(
            datetime.fromisoformat(withdrawn["retention_until"]),
            datetime.fromisoformat(original_retention),
        )


class V1StoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.path = Path(self.tempdir.name) / "synthetic.sqlite3"
        self.current = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
        self.store = MemoryStore(self.path, clock=lambda: self.current)
        self.addCleanup(lambda: self.store.close())
        self.request = self.start("u1", "input-1")

    def start(self, user="u1", nonce="input-1"):
        return self.store.start_request(
            user, input_id=nonce, text=None, timezone="Asia/Seoul",
            contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION,
            targets=[{"target_id": "pants-1", "garment_type": "Pants"}],
        )

    def snapshot(self, user="u1", request=None, **kwargs):
        return self.store.snapshot(user, request or self.request["id"],
                                   contract_version=c.CONTRACT_VERSION, **kwargs)

    def batch(self, nonce, actions, *, user="u1", request=None, expected=None, **kwargs):
        request_id = request or self.request["id"]
        if expected is None:
            snapshot = self.snapshot(user, request_id)
            expected = {"request_revision": snapshot["request"]["revision"],
                        "profile_revision": snapshot["profile_revision"], "object_versions": []}
        return self.store.apply_batch(
            user, request_id, batch_id=nonce, actions=actions,
            contract_version=c.CONTRACT_VERSION, expected=expected, **kwargs,
        )

    @staticmethod
    def feedback(text="빈티지한 느낌"):
        return {"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
                "reaction": "text_only", "selections": [], "text": text, "question_id": None}

    def intake(self, text="빈티지한 느낌", nonce="text-1", **kwargs):
        return self.batch(nonce, [self.feedback(text)], **kwargs)["evidence_refs"][0]

    @staticmethod
    def candidate(source):
        return {
            "op": "create", "memory": {
                "kind": "preference", "content": "빈티지한 느낌", "fact": None,
                "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
                "conditions": {}, "polarity": "prefer", "strength": "soft",
                "valid_from": None, "valid_until": None,
            },
            "source_refs": [source], "bindings": [],
            "confirmation_event_ref": None, "consent_event_ref": None,
        }

    def test_unmapped_memory_evidence_and_restart(self):
        source = self.intake("  빈티지한 느낌 🌿  ")
        result = self.batch("candidate", [self.candidate(source)])
        before = self.snapshot()
        memory = before["memories"][0]
        self.assertEqual(memory["content"], "빈티지한 느낌")
        self.assertNotIn("feature", memory)
        self.assertNotIn("values", memory)
        self.assertEqual(before["bindings"], [])
        self.assertEqual((memory["origin"], memory["confirmed"], memory["status"]),
                         ("inferred", False, "candidate"))
        self.assertEqual(memory["source_refs"], [source])
        self.assertEqual(before["evidence"][0]["quote"], "  빈티지한 느낌 🌿  ")
        self.assertEqual(memory["contract_version"], c.CONTRACT_VERSION)
        self.assertEqual(before["registry_version"], c.V1_REGISTRY_VERSION)
        self.assertEqual(set(memory), set(c.MemoryItem.__required_keys__))
        self.assertEqual(set(before), set(c.MemorySnapshot.__required_keys__))
        self.assertEqual(result["changed_refs"][0]["id"], memory["id"])
        self.assertLessEqual(memory["retention_until"], before["evidence"][0]["retention_until"])
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])
        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.current)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.batch("candidate", [self.candidate(source)]), result)
        self.assertEqual(before, self.snapshot())

    def test_intake_receipt_pending_and_idempotency(self):
        action = self.feedback()
        expected = {"request_revision": 1, "profile_revision": 0, "object_versions": []}
        first = self.batch("intake", [action], expected=expected)
        replay = self.batch("intake", [action], expected=expected)
        self.assertEqual(first, replay)
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["evidence"]), 1)
        self.assertEqual(len(snapshot["feedback"]), 1)
        feedback = snapshot["feedback"][0]
        self.assertNotIn("text", feedback)
        state = self.store.interpretation_status("u1", self.request["id"],
                                               {"type": "feedback", "id": feedback["id"], "version": 1})
        self.assertEqual(state["status"], "pending")
        self.assertEqual(state["candidate_refs"], [])
        self.assertEqual(first["interpretation_ref"]["id"], state["id"])
        with self.assertRaises(StyleMateError) as caught:
            self.batch("intake", [self.feedback("다른 원문")])
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        with self.assertRaises(StyleMateError) as caught:
            self.batch("stale", [action], expected=expected)
        self.assertEqual(caught.exception.code, "version_conflict")

    def test_ownership_request_isolation_and_bad_versions(self):
        source = self.intake()
        other_request = self.start("u1", "new-request")
        other_user = self.start("u2", "other-user")
        for user, request in (("u1", other_request), ("u2", other_user)):
            with self.subTest(user=user):
                with self.assertRaises(StyleMateError) as caught:
                    self.batch("foreign-source", [self.candidate(source)], user=user, request=request["id"])
                self.assertEqual(caught.exception.code, "not_found")
                self.assertEqual(self.snapshot(user, request["id"])["evidence"], [])
        for version, code in ((True, "invalid_input"), (1.0, "invalid_input"),
                              (0, "invalid_input"), (2, "version_conflict")):
            with self.subTest(version=version):
                with self.assertRaises(StyleMateError) as caught:
                    self.batch("bad-version", [self.candidate(source | {"version": version})])
                self.assertEqual(caught.exception.code, code)
        with self.assertRaises(StyleMateError) as caught:
            self.snapshot("u2", self.request["id"])
        self.assertEqual(caught.exception.code, "not_found")

    def test_binding_storage_keeps_contract_and_registry_versions_separate(self):
        source = self.intake("네이비와 따뜻한 느낌")
        action = self.candidate(source)
        action["bindings"] = [
            {"domain": "PI", "feature": "Color", "values": ["Navy"], "match": "any",
             "polarity": "prefer", "strength": "soft"},
            {"domain": "FEA", "category": "Functional", "subcategory": "Protection", "tag": "Warmth",
             "polarity": "prefer", "strength": "soft"},
        ]
        self.batch("mapped", [action])
        snapshot = self.snapshot()
        self.assertEqual(len(snapshot["bindings"]), 2)
        for binding in snapshot["bindings"]:
            self.assertEqual(binding["memory_id"], snapshot["memories"][0]["id"])
            self.assertEqual(binding["registry_version"], c.V1_REGISTRY_VERSION)
            self.assertEqual(binding["contract_version"], c.CONTRACT_VERSION)
            self.assertFalse(binding["confirmed"])
            self.assertIsNone(binding["confirmation_ref"])
        self.assertEqual(self.store.connection.execute("PRAGMA user_version").fetchone()[0], 1)
        for bindings, code in (
            ([action["bindings"][0] | {"feature": "Fit", "values": ["Relaxed"]}], "unsupported_mapping"),
            ([action["bindings"][0] | {"strength": "hard"}], "confirmation_required"),
            ([action["bindings"][0] | {"polarity": "avoid"}], "invalid_input"),
        ):
            with self.subTest(bindings=bindings):
                with self.assertRaises(StyleMateError) as caught:
                    self.batch("bad-binding", [action | {"bindings": bindings}])
                self.assertEqual(caught.exception.code, code)
        self.assertEqual(len(self.snapshot()["memories"]), 1)

    def test_batch_rollback_at_storage_failure_points(self):
        source = self.intake()
        before = self.snapshot()
        for failure_stage in ("after_action", "before_receipt", "commit"):
            def fail(stage):
                if stage == failure_stage:
                    raise RuntimeError("synthetic write failure")
            self.store._failure_hook = fail
            with self.subTest(stage=failure_stage):
                with self.assertRaises(StyleMateError) as caught:
                    self.batch("failure", [self.candidate(source), self.candidate(source)])
                self.assertEqual(caught.exception.code, "storage_failed")
                self.assertEqual(self.snapshot(), before)
                self.assertIsNone(self.store.connection.execute(
                    "SELECT 1 FROM v1_batch_receipts WHERE batch_id='failure'"
                ).fetchone())
        self.store._failure_hook = None
        bad = self.candidate(source)
        bad["memory"]["content"] = ""
        with self.assertRaises(StyleMateError):
            self.batch("bad-second", [self.candidate(source), bad])
        self.assertEqual(self.snapshot(), before)
        self.batch("failure", [self.candidate(source)])

    def test_fixed_fields_resource_limits_and_trust_rejection(self):
        source = self.intake()
        for field, value in (("confirmed", True), ("origin", "explicit"), ("id", "injected"),
                             ("user_id", "u2"), ("retention_until", "2099-01-01T00:00:00Z"),
                             ("scope", "long_term"), ("feature", "Color")):
            action = self.candidate(source)
            action["memory"][field] = value
            with self.subTest(field=field):
                with self.assertRaises(StyleMateError) as caught:
                    self.batch("invalid-metadata", [action])
                self.assertEqual(caught.exception.code, "invalid_input")
        for text in ("", " ", "가" * 4001, None):
            with self.assertRaises(StyleMateError):
                self.batch("invalid-text", [self.feedback(text)])
        for modification in ({"confirmation_event_ref": source}, {"consent_event_ref": source},
                             {"op": "create_long_term"}, {"op": "confirm"}):
            with self.assertRaises(StyleMateError):
                self.batch("later-task", [self.candidate(source) | modification])
        action = self.candidate(source)
        action["memory"]["selector"]["garment_type"] = "Tops"
        with self.assertRaises(StyleMateError):
            self.batch("wrong-target", [action])
        self.assertEqual(self.snapshot()["memories"], [])

    def test_expected_references_and_legacy_arguments(self):
        source = self.intake()
        expected = {"request_revision": 2, "profile_revision": 0, "object_versions": [source]}
        for refs, code in (([source | {"version": 2}], "version_conflict"),
                           ([source | {"version": True}], "invalid_input"),
                           ([source, source], "invalid_input")):
            with self.assertRaises(StyleMateError) as caught:
                self.batch("bad-expected", [self.candidate(source)], expected=expected | {"object_versions": refs})
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(StyleMateError) as caught:
            self.batch("mixed-expected", [self.candidate(source)], expected=expected, expected_request_revision=1)
        self.assertEqual(caught.exception.code, "invalid_input")
        self.batch("matching-expected", [self.candidate(source)], expected=expected,
                   expected_request_revision=2, expected_profile_revision=0)

    def test_intake_rolls_back_with_later_action_and_contract_nonce_collisions(self):
        with self.assertRaises(StyleMateError):
            self.batch("intake-failed", [self.feedback(), {"op": "confirm"}])
        empty = self.snapshot()
        for key in ("evidence", "feedback", "interpretations"):
            self.assertEqual(empty[key], [])
        self.assertEqual(empty["request"]["revision"], 1)
        self.intake(nonce="shared-nonce")
        legacy = self.store.start_request("u1", input_id="legacy-input", text="old", timezone="UTC")
        old_action = {"op": "create", "feature": "fit", "values": ["Relaxed"],
                      "content": "legacy", "evidence_ref": "legacy-input"}
        with self.assertRaises(StyleMateError) as caught:
            self.store.apply_batch("u1", legacy["id"], batch_id="shared-nonce", actions=[old_action])
        self.assertEqual(caught.exception.code, "idempotency_conflict")
        self.store.apply_batch("u1", legacy["id"], batch_id="old-nonce", actions=[old_action])
        with self.assertRaises(StyleMateError) as caught:
            self.batch("old-nonce", [self.feedback()])
        self.assertEqual(caught.exception.code, "idempotency_conflict")

    def test_missing_expected_and_invalid_unicode_are_rejected_without_writes(self):
        with self.assertRaises(StyleMateError) as caught:
            self.store.apply_batch("u1", self.request["id"], batch_id="no-expected",
                                   actions=[self.feedback()], contract_version=c.CONTRACT_VERSION)
        self.assertEqual(caught.exception.code, "invalid_input")
        for user, text in (("\ud800", "valid"), ("u1", "\ud800")):
            with self.assertRaises(StyleMateError) as caught:
                self.store.start_request(user, input_id="bad-unicode", text=text, timezone="UTC",
                                         contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION)
            self.assertEqual(caught.exception.code, "invalid_input")
        self.assertEqual(self.snapshot()["request"]["revision"], 1)

    def test_snapshot_sql_validity_half_open_and_retention(self):
        source = self.intake()
        action = self.candidate(source)
        start = self.current + timedelta(microseconds=1)
        action["memory"].update(valid_from=start.isoformat(),
                                valid_until=(start + timedelta(microseconds=2)).isoformat())
        self.batch("future", [action])
        self.assertEqual(self.snapshot()["memories"], [])
        self.current = start
        self.assertEqual(len(self.snapshot()["memories"]), 1)
        self.current += timedelta(microseconds=2)
        self.assertEqual(self.snapshot()["memories"], [])
        self.current = datetime(2026, 11, 28, 9, tzinfo=timezone.utc)
        with self.assertRaises(StyleMateError) as caught:
            self.snapshot()
        self.assertEqual(caught.exception.code, "request_expired")

    def test_input_budget_includes_expected_references(self):
        source = self.intake()
        action = self.candidate(source)
        action["memory"].update(content="a" * 4000, conditions={"occasion": "b" * 2500})
        actions = [action] * 32
        # The actions fit; the complete input including expected exceeds the cap.
        c.batch_fingerprint(c.CONTRACT_VERSION, self.request["id"], actions)
        expected = {"request_revision": 2, "profile_revision": 0, "object_versions": [
            {"type": "evidence", "id": str(index).zfill(128), "version": 1} for index in range(256)
        ]}
        with self.assertRaises(StyleMateError) as caught:
            self.batch("oversized", actions, expected=expected)
        self.assertEqual(caught.exception.code, "invalid_input")
        self.assertIn("256 KiB", caught.exception.message)
        self.assertEqual(self.snapshot()["memories"], [])

    def test_explicit_contract_start_replay_and_closed_read(self):
        self.assertEqual(self.start(), self.request)
        self.assertEqual(self.snapshot()["evidence"], [])
        with self.assertRaises(StyleMateError) as caught:
            self.store.snapshot("u1", self.request["id"])
        self.assertEqual(caught.exception.code, "unsupported_contract")
        legacy = self.store.start_request("u1", input_id="legacy", text="legacy", timezone="UTC")
        with self.assertRaises(StyleMateError) as caught:
            self.snapshot(request=legacy["id"])
        self.assertEqual(caught.exception.code, "unsupported_contract")
        for method in (self.store.resume_request, self.store.close_request):
            with self.assertRaises(StyleMateError) as caught:
                method("u1", self.request["id"])
            self.assertEqual(caught.exception.code, "unsupported_contract")
        # Simulate a retained closed request; its transition belongs to B2.
        self.store.connection.execute("UPDATE requests SET status='closed' WHERE id=?", (self.request["id"],))
        with self.assertRaises(StyleMateError) as caught:
            self.snapshot()
        self.assertEqual(caught.exception.code, "request_closed")
        retained = self.snapshot(include_closed=True)
        self.assertEqual(retained["request"]["status"], "closed")
        self.assertEqual(retained["request"]["retention_until"], self.request["retention_until"])


if __name__ == "__main__":
    unittest.main()
