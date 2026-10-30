"""B2 storage transitions with synthetic evidence; no provider or consumer UI."""

import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from stylemate_memory import contracts as c
from stylemate_memory.errors import StyleMateError
from stylemate_memory.store import MemoryStore


def ref(kind, obj):
    return {"type": kind, "id": obj["id"], "version": obj["version"]}


class V1TransitionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        self.now = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        self.serial = 0
        self.request = self.start("first")

    def nonce(self):
        self.serial += 1
        return f"command-{self.serial}"

    def start(self, nonce, user="u1"):
        return self.store.start_request(user, input_id=nonce, text=None, timezone="UTC",
            contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION,
            targets=[{"target_id": "pants-1", "garment_type": "Pants"}])

    def snapshot(self, request=None, user="u1"):
        return self.store.snapshot(user, (request or self.request)["id"],
                                   contract_version=c.CONTRACT_VERSION, include_closed=True)

    def expected(self, snapshot=None):
        snapshot = snapshot or self.snapshot()
        return {"request_revision": snapshot["request"]["revision"], "profile_revision": snapshot["profile_revision"],
                "object_versions": [ref("memory", m) for m in snapshot["memories"]]
                    + [ref("binding", b) for b in snapshot["bindings"]]}

    def batch(self, actions, *, nonce=None, expected=None, request=None):
        return self.store.apply_batch("u1", (request or self.request)["id"], batch_id=nonce or self.nonce(),
            actions=actions, contract_version=c.CONTRACT_VERSION,
            expected=expected or self.expected(self.snapshot(request)))

    def intake(self, text="네이비를 좋아해요"):
        return self.batch([{"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
            "reaction": "text_only", "selections": [], "text": text, "question_id": None}])["evidence_refs"][0]

    @staticmethod
    def content(**changes):
        return {"kind": "preference", "content": "네이비를 좋아해요", "fact": None,
            "selector": {"garment_type": "Pants", "slot_id": None}, "conditions": {},
            "polarity": "prefer", "strength": "soft", "valid_from": None, "valid_until": None} | changes

    @staticmethod
    def binding(value="Navy"):
        return {"domain": "PI", "feature": "Color", "values": [value], "match": "any",
                "polarity": "prefer", "strength": "soft"}

    @staticmethod
    def meaning(memory, scope=None):
        return {k: memory[k] for k in c.MemoryContent.__required_keys__} | {"scope": scope or memory["scope"]}

    def candidate(self, *, bindings=None, content=None):
        source = self.intake()
        action = {"op": "create", "memory": content or self.content(), "source_refs": [source],
                  "bindings": bindings or [], "confirmation_event_ref": None, "consent_event_ref": None}
        result = self.batch([action])
        return next(m for m in self.snapshot()["memories"] if m["id"] == result["changed_refs"][0]["id"])

    def display(self, purpose, meaning, subjects, bindings=None, *, basis_changes=None):
        snapshot = self.snapshot()
        basis = self.expected(snapshot) | {"request_id": self.request["id"], "contract_version": c.CONTRACT_VERSION,
            "registry_version": c.V1_REGISTRY_VERSION, "index_version": None, "catalog": None, "valid_until": None}
        versions = {(r["type"], r["id"]): r for r in basis["object_versions"] + subjects}
        basis["object_versions"] = list(versions.values())
        basis.update(basis_changes or {})
        return self.store.issue_display("u1", self.request["id"], purpose=purpose,
            snapshot={"meaning": meaning, "bindings": bindings or [], "subject_refs": subjects}, basis=basis)

    def accept(self, display, *, command_id=None):
        return self.store.record_user_event("u1", self.request["id"], command_id=command_id or self.nonce(),
            display_ref=ref("display", display), purpose=display["purpose"], expected=self.expected())

    def review(self, memory, purpose="confirm_content", *, bindings=None, meaning=None, extra_refs=None):
        subjects = [ref("memory", memory)] + (extra_refs or [])
        if bindings:
            subjects += [ref("binding", b) for b in self.snapshot()["bindings"] if b["memory_id"] == memory["id"]
                         and any(all(b.get(k) == v for k, v in spec.items()) for spec in bindings)]
        return self.accept(self.display(purpose, meaning or self.meaning(memory,
            "long_term" if purpose == "future_reuse" else None), subjects, bindings))

    def confirm_action(self, memory, event, bindings=None, op="confirm"):
        return {"op": op, "memory_id": memory["id"], "expected_version": memory["version"],
                "confirmation_event_ref": event, "binding_confirmations": bindings or []}

    def confirm(self, memory, *, bindings=None):
        event = self.review(memory, bindings=bindings)
        refs = [ref("binding", b) for b in self.snapshot()["bindings"]] if bindings else []
        self.batch([self.confirm_action(memory, event, refs)])
        return next(m for m in self.snapshot()["memories"] if m["id"] == memory["id"])

    def promote_action(self, memory, event):
        return {"op": "promote", "memory_id": memory["id"], "expected_version": memory["version"],
                "consent_event_ref": event}

    def promote(self, memory, bindings=None):
        event = self.review(memory, "future_reuse", bindings=bindings)
        result = self.batch([self.promote_action(memory, event)])
        return next(m for m in self.snapshot()["memories"] if m["scope"] == "long_term"), result

    def assert_error(self, code, call):
        with self.assertRaises(StyleMateError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def test_content_and_binding_confirmation_are_separate_and_keep_origin(self):
        fea = {"domain": "FEA", "category": "Functional", "subcategory": "Protection", "tag": "Warmth",
               "polarity": "prefer", "strength": "soft"}
        memory = self.candidate(bindings=[self.binding(), fea])
        memory = self.confirm(memory)
        snapshot = self.snapshot()
        self.assertEqual((memory["confirmed"], memory["origin"], memory["status"]), (True, "inferred", "active"))
        binding = next(b for b in snapshot["bindings"] if b["domain"] == "PI")
        self.assertTrue(all(not b["confirmed"] and b["status"] == "candidate" for b in snapshot["bindings"]))
        event = self.review(memory, "confirm_bindings", bindings=[self.binding()])
        self.batch([self.confirm_action(memory, event, [ref("binding", binding)], op="confirm_bindings")])
        binding = next(b for b in self.snapshot()["bindings"] if b["domain"] == "PI")
        self.assertEqual((binding["confirmed"], binding["origin"], binding["status"]), (True, "inferred", "active"))
        self.assertEqual(binding["version"], 2)
        self.assertFalse(next(b for b in self.snapshot()["bindings"] if b["domain"] == "FEA")["confirmed"])
        self.assertEqual(len(self.snapshot()["confirmations"]), 2)
        self.assertEqual(self.snapshot()["consents"], [])

    def test_binding_confirmation_requires_exact_displayed_ids_and_values(self):
        memory = self.confirm(self.candidate(bindings=[self.binding()]))
        binding = self.snapshot()["bindings"][0]
        event = self.review(memory, "confirm_bindings")
        before = self.snapshot()
        self.assert_error("invalid_user_event", lambda: self.batch([
            self.confirm_action(memory, event, [ref("binding", binding)], op="confirm_bindings")]))
        self.assertEqual(self.snapshot(), before)
        # A content accept cannot stand in for a separate binding accept.
        event = self.review(memory)
        self.assert_error("invalid_user_event", lambda: self.batch([
            self.confirm_action(memory, event, [ref("binding", binding)], op="confirm_bindings")]))

    def test_confirm_then_promote_uses_start_expected_and_sequential_action_versions(self):
        memory = self.candidate(bindings=[self.binding()])
        confirmation = self.review(memory)
        consent = self.review(memory, "future_reuse", bindings=[self.binding()])
        expected = self.expected()
        actions = [self.confirm_action(memory, confirmation), self.promote_action(memory | {"version": 2}, consent)]
        result = self.batch(actions, nonce="confirm-promote", expected=expected)
        self.assertEqual(result["profile_revision"], 1)
        self.assertEqual(self.batch(actions, nonce="confirm-promote", expected=expected), result)
        snapshot = self.snapshot()
        short = next(m for m in snapshot["memories"] if m["scope"] == "short_term")
        long = next(m for m in snapshot["memories"] if m["scope"] == "long_term")
        self.assertEqual((short["version"], long["version"]), (2, 1))
        self.assertEqual((short["family_id"], long["origin"]), (long["family_id"], "inferred"))
        self.assertEqual(self.meaning(short, "long_term"), self.meaning(long))
        self.assertFalse(next(b for b in snapshot["bindings"] if b["memory_id"] == long["id"])["confirmed"])
        long_confirmation = next(p for p in snapshot["confirmations"] if p["memory_id"] == long["id"])
        self.assertEqual(long_confirmation["snapshot"]["bindings"], [])
        self.assertEqual(snapshot["request"]["final_selection"], None)
        self.assertEqual(snapshot["request"]["status"], "open")
        self.assert_error("idempotency_conflict", lambda: self.batch(actions[:1], nonce="confirm-promote"))
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_wrong_sequential_version_rolls_back_confirmation_and_event_consumption(self):
        memory = self.candidate()
        confirmation = self.review(memory)
        consent = self.review(memory, "future_reuse")
        before = self.snapshot()
        self.assert_error("version_conflict", lambda: self.batch([
            self.confirm_action(memory, confirmation), self.promote_action(memory, consent)]))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_event_uses").fetchone()[0], 0)
        self.batch([self.confirm_action(memory, confirmation), self.promote_action(memory | {"version": 2}, consent)])

    def test_missing_or_wrong_purpose_consent_does_not_create_long_term(self):
        memory = self.confirm(self.candidate())
        self.assert_error("consent_required", lambda: self.batch([self.promote_action(memory, None)]))
        content_event = self.review(memory)
        self.assert_error("invalid_user_event", lambda: self.batch([self.promote_action(memory, content_event)]))
        self.assertEqual(len(self.snapshot()["memories"]), 1)
        self.assertEqual(self.snapshot()["consents"], [])

    def test_consent_cannot_broaden_slot_or_conditions_or_change_content(self):
        memory = self.confirm(self.candidate(content=self.content(conditions={"occasion": "출근"})))
        source = memory["source_refs"][0]
        for changes in ({"conditions": {}}, {"content": "항상 네이비만"},
                        {"selector": {"garment_type": None, "slot_id": None}},
                        {"valid_until": "2027-01-01T00:00:00+00:00"}, {"strength": "hard"}):
            with self.subTest(changes=changes):
                meaning = self.meaning(memory, "long_term") | changes
                event = self.accept(self.display("future_reuse", meaning, [source]))
                self.assert_error("invalid_user_event", lambda: self.batch([self.promote_action(memory, event)]))
        slotted = self.confirm(self.candidate(content=self.content(selector={"garment_type": "Pants", "slot_id": "pants-1"})))
        broad = self.meaning(slotted, "long_term") | {"selector": {"garment_type": "Pants", "slot_id": None}}
        consent = self.accept(self.display("future_reuse", broad, slotted["source_refs"]))
        self.assert_error("invalid_input", lambda: self.batch([self.promote_action(slotted, consent)]))
        self.assertTrue(all(m["scope"] == "short_term" for m in self.snapshot()["memories"]))

    def test_direct_long_term_creation_requires_both_events_and_is_atomic(self):
        source = self.intake()
        content = self.content(conditions={"occasion": "출근"})
        meaning = content | {"scope": "long_term"}
        specs = [self.binding()]
        confirmation = self.accept(self.display("confirm_content", meaning, [source], specs))
        consent = self.accept(self.display("future_reuse", meaning, [source], specs))
        action = {"op": "create_long_term", "memory": content, "bindings": specs, "source_refs": [source],
                  "confirmation_event_ref": confirmation, "consent_event_ref": consent}
        before = self.snapshot()
        for modification, code in (({"consent_event_ref": None}, "consent_required"),
                                   ({"confirmation_event_ref": None}, "confirmation_required")):
            self.assert_error(code, lambda: self.batch([action | modification]))
            self.assertEqual(self.snapshot(), before)
        result = self.batch([action], nonce="direct")
        self.assertEqual(self.batch([action], nonce="direct"), result)
        long = self.snapshot()["memories"][0]
        self.assertEqual((long["scope"], long["request_id"], long["confirmed"]), ("long_term", None, True))
        self.assertTrue(self.snapshot()["bindings"][0]["confirmed"])
        self.assertEqual(long["conditions"], {"occasion": "출근"})
        self.assertEqual(datetime.fromisoformat(long["retention_until"]), self.now + timedelta(days=365))

    def test_independent_long_term_proof_survives_restart_and_new_request(self):
        memory = self.confirm(self.candidate(bindings=[self.binding()]), bindings=[self.binding()])
        long, _ = self.promote(memory, [self.binding()])
        old_snapshot = self.snapshot()
        independent = self.store.connection.execute(
            "SELECT id,object_type FROM v1_objects WHERE request_id IS NULL AND user_id='u1'").fetchall()
        self.assertEqual({r["object_type"] for r in independent}, {"memory", "binding", "evidence", "confirmation", "consent", "display", "event"})
        for row in independent:
            dependencies = self.store.connection.execute(
                """SELECT o.request_id FROM v1_object_refs r JOIN v1_objects o ON o.id=r.target_id
                    WHERE r.owner_id=?""", (row["id"],)).fetchall()
            self.assertTrue(all(d["request_id"] is None for d in dependencies))
        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.assertEqual(old_snapshot, self.snapshot())
        second = self.start("second")
        snapshot = self.snapshot(second)
        self.assertEqual([m["id"] for m in snapshot["memories"]], [long["id"]])
        self.assertTrue(snapshot["bindings"][0]["confirmed"])
        self.assertTrue(all(e["quote"] is None and e["selection"] is None for e in snapshot["evidence"]))
        self.assertEqual(snapshot["evidence"][0]["snapshot"], self.meaning(long))
        self.assertTrue(all(e["request_id"] is None for e in snapshot["evidence"]))

    def test_propose_bindings_is_soft_separate_and_invalidates_old_review(self):
        memory = self.confirm(self.candidate())
        stale = self.review(memory)
        action = {"op": "propose_bindings", "memory_id": memory["id"], "expected_version": memory["version"],
                  "bindings": [self.binding()], "source_refs": memory["source_refs"]}
        self.batch([action])
        snapshot = self.snapshot()
        updated = snapshot["memories"][0]
        self.assertTrue(updated["confirmed"])
        self.assertFalse(snapshot["bindings"][0]["confirmed"])
        self.assert_error("stale_context", lambda: self.batch([self.confirm_action(updated, stale)]))
        self.assert_error("confirmation_required", lambda: self.batch([action | {
            "expected_version": updated["version"], "bindings": [self.binding() | {"strength": "hard"}]}]))
        duplicate = self.batch([action | {"expected_version": updated["version"]}])
        self.assertEqual(duplicate["outcome"], "unchanged")
        self.assertEqual(len(self.snapshot()["bindings"]), 1)

    def test_short_replacement_needs_its_own_confirmation_and_keeps_active_on_failure(self):
        old = self.confirm(self.candidate())
        source = self.intake("검정을 좋아해요")
        content = self.content(content="검정을 좋아해요")
        proof = self.review(old, "replace", meaning=content | {"scope": "short_term"}, extra_refs=[source])
        action = {"op": "replace", "memory_id": old["id"], "expected_version": old["version"],
            "memory": content, "source_refs": [source], "bindings": [self.binding("Black")],
            "confirmation_event_ref": proof, "consent_event_ref": None}
        # The value was not displayed even though the replacement sentence was.
        before = self.snapshot()
        self.assert_error("invalid_user_event", lambda: self.batch([action]))
        self.assertEqual(self.snapshot(), before)
        action["bindings"] = []
        self.batch([action])
        memory = self.snapshot()["memories"][0]
        self.assertNotEqual(memory["id"], old["id"])
        self.assertEqual((memory["content"], memory["status"], memory["confirmed"]), (content["content"], "active", True))
        self.assertEqual(self.snapshot()["links"][0]["relation"], "supersedes")
        self.assertEqual(self.snapshot()["links"][0]["source_ref"]["id"], memory["id"])
        self.assertEqual(self.snapshot()["links"][0]["target_ref"]["id"], old["id"])

    def test_long_term_replacement_requires_new_consent_and_rolls_back(self):
        old, _ = self.promote(self.confirm(self.candidate()))
        source = self.intake("검정을 좋아해요")
        content = self.content(content="검정을 좋아해요")
        meaning = content | {"scope": "long_term"}
        proof = self.review(old, "replace", meaning=meaning, extra_refs=[source])
        consent = self.accept(self.display("future_reuse", meaning, [source]))
        action = {"op": "replace", "memory_id": old["id"], "expected_version": old["version"],
            "memory": content, "source_refs": [source], "bindings": [],
            "confirmation_event_ref": proof, "consent_event_ref": None}
        before = self.snapshot()
        self.assert_error("consent_required", lambda: self.batch([action]))
        self.assertEqual(before, self.snapshot())
        self.batch([action | {"consent_event_ref": consent}])
        longs = [m for m in self.snapshot()["memories"] if m["scope"] == "long_term"]
        self.assertEqual(len(longs), 1)
        self.assertEqual(longs[0]["content"], content["content"])
        self.assertNotEqual(longs[0]["consent_ref"], old["consent_ref"])
        self.assertTrue(all(m["content"] != old["content"] for m in self.snapshot()["memories"]))

    def test_failure_during_promotion_rolls_back_snapshots_bindings_revisions_and_receipt(self):
        memory = self.candidate(bindings=[self.binding()])
        confirmation = self.review(memory, bindings=[self.binding()])
        consent = self.review(memory, "future_reuse", bindings=[self.binding()])
        binding = self.snapshot()["bindings"][0]
        actions = [self.confirm_action(memory, confirmation, [ref("binding", binding)]),
                   self.promote_action(memory | {"version": 2}, consent)]
        before = self.snapshot()
        counts = [tuple(r) for r in self.store.connection.execute("SELECT object_type,count(*) FROM v1_objects GROUP BY object_type")]
        for failure in ("long_term_after_snapshots", "after_action", "before_receipt", "commit"):
            def fail(stage):
                if stage == failure:
                    raise RuntimeError("synthetic storage failure")
            self.store._failure_hook = fail
            self.assert_error("storage_failed", lambda: self.batch(actions, nonce="rollback"))
            self.assertEqual(before, self.snapshot())
            self.assertEqual(counts, [tuple(r) for r in self.store.connection.execute("SELECT object_type,count(*) FROM v1_objects GROUP BY object_type")])
        self.store._failure_hook = None
        self.batch(actions, nonce="rollback")

    def test_review_ownership_snapshot_and_basis_are_checked(self):
        memory = self.candidate()
        display = self.display("confirm_content", self.meaning(memory), [ref("memory", memory)])
        other = self.start("other-user", user="u2")
        self.assert_error("not_found", lambda: self.store.record_user_event("u2", other["id"], command_id="stolen",
            display_ref=ref("display", display), purpose="confirm_content", expected={
                "request_revision": 1, "profile_revision": 0, "object_versions": []}))
        injected = copy.deepcopy(display)
        injected["snapshot"]["meaning"]["content"] = "다른 내용"
        # A caller mutation of the returned value cannot alter the persisted display.
        event = self.accept(injected)
        self.batch([self.confirm_action(memory, event)])
        self.assertEqual(self.snapshot()["memories"][0]["content"], memory["content"])
        self.assert_error("stale_context", lambda: self.accept(display))

    def test_event_command_replay_conflict_and_consumption_are_durable(self):
        memory = self.candidate()
        display = self.display("confirm_content", self.meaning(memory), [ref("memory", memory)])
        event = self.accept(display, command_id="accept-once")
        self.assertEqual(self.accept(display, command_id="accept-once"), event)
        other = self.display("confirm_content", self.meaning(memory), [ref("memory", memory)])
        self.assert_error("idempotency_conflict", lambda: self.accept(other, command_id="accept-once"))
        self.batch([self.confirm_action(memory, event)], nonce="apply-once")
        memory = self.snapshot()["memories"][0]
        self.assert_error("invalid_user_event", lambda: self.batch([self.confirm_action(memory, event)]))
        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.assertEqual(self.accept(display, command_id="accept-once"), event)
        self.assert_error("invalid_user_event", lambda: self.batch([self.confirm_action(memory, event)]))

    def test_end_request_is_separate_and_closed_content_can_be_reused_with_new_consent(self):
        memory = self.confirm(self.candidate())
        self.batch([{"op": "end_request"}])
        closed = self.snapshot()
        self.assertEqual((closed["request"]["status"], closed["request"]["final_selection"]), ("closed", None))
        self.assertEqual(closed["consents"], [])
        self.assertEqual(len(closed["memories"]), 1)
        self.assert_error("request_closed", lambda: self.intake())
        long, _ = self.promote(memory)
        second = self.start("new-request")
        self.assertEqual([m["id"] for m in self.snapshot(second)["memories"]], [long["id"]])
        self.assertEqual(self.start("first")["status"], "closed")
        self.assertEqual(self.batch([{"op": "end_request"}])["outcome"], "unchanged")

    def test_withdraw_excludes_whole_promoted_family_and_revokes_consent_immediately(self):
        memory = self.confirm(self.candidate(bindings=[self.binding()]))
        long, _ = self.promote(memory, [self.binding()])
        event = self.review(long, "withdraw")
        self.batch([{"op": "withdraw", "memory_id": long["id"], "expected_version": long["version"], "user_event_ref": event}])
        self.assertEqual(self.snapshot()["memories"], [])
        second = self.start("after-withdraw")
        self.assertEqual(self.snapshot(second)["memories"], [])
        statuses = self.store.connection.execute("SELECT status FROM v1_memories").fetchall()
        self.assertTrue(all(row["status"] == "withdrawn" for row in statuses))
        consent = self.store.connection.execute("SELECT payload_json FROM v1_consents").fetchone()[0]
        self.assertIn('"status":"withdrawn"', consent)

    def test_stale_versions_and_expired_display_never_apply(self):
        memory = self.candidate()
        display = self.display("confirm_content", self.meaning(memory), [ref("memory", memory)],
            basis_changes={"valid_until": (self.now + timedelta(seconds=1)).isoformat()})
        event = self.accept(display)
        self.assert_error("version_conflict", lambda: self.batch([
            self.confirm_action(memory | {"version": 99}, event)]))
        self.now += timedelta(seconds=1)
        self.assert_error("stale_context", lambda: self.accept(display))
        self.assert_error("stale_context", lambda: self.batch([self.confirm_action(memory, event)]))
        self.assertFalse(self.snapshot()["memories"][0]["confirmed"])

    def test_long_term_binding_proposal_cannot_store_current_request_evidence(self):
        long, _ = self.promote(self.confirm(self.candidate()))
        source = self.intake("검정일지도 몰라요")
        action = {"op": "propose_bindings", "memory_id": long["id"], "expected_version": long["version"],
                  "bindings": [self.binding("Black")], "source_refs": [source]}
        self.assert_error("consent_required", lambda: self.batch([action]))
        self.batch([action | {"source_refs": long["source_refs"]}])
        self.assertFalse(self.snapshot()["bindings"][0]["confirmed"])

    def test_confirmed_short_creation_uses_review_proof_without_implicit_long_term_write(self):
        source = self.intake()
        content = self.content()
        event = self.accept(self.display("confirm_content", content | {"scope": "short_term"}, [source], [self.binding()]))
        action = {"op": "create", "memory": content, "source_refs": [source], "bindings": [self.binding()],
                  "confirmation_event_ref": event, "consent_event_ref": None}
        self.batch([action])
        snapshot = self.snapshot()
        self.assertEqual((snapshot["memories"][0]["confirmed"], snapshot["bindings"][0]["confirmed"]), (True, True))
        self.assertEqual(snapshot["consents"], [])
        self.assertEqual(snapshot["profile_revision"], 0)

    def test_direct_creation_and_long_replacement_storage_failures_preserve_old_state(self):
        source = self.intake()
        content = self.content()
        meaning = content | {"scope": "long_term"}
        confirmation = self.accept(self.display("confirm_content", meaning, [source]))
        consent = self.accept(self.display("future_reuse", meaning, [source]))
        action = {"op": "create_long_term", "memory": content, "source_refs": [source], "bindings": [],
                  "confirmation_event_ref": confirmation, "consent_event_ref": consent}

        def fail(stage):
            if stage == "long_term_after_snapshots":
                raise RuntimeError("synthetic long-term storage failure")

        before = self.snapshot()
        self.store._failure_hook = fail
        self.assert_error("storage_failed", lambda: self.batch([action], nonce="direct-failure"))
        self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.batch([action], nonce="direct-failure")
        old = self.snapshot()["memories"][0]
        source = self.intake("검정으로 변경")
        content = self.content(content="검정을 좋아해요")
        meaning = content | {"scope": "long_term"}
        confirmation = self.review(old, "replace", meaning=meaning, extra_refs=[source])
        consent = self.accept(self.display("future_reuse", meaning, [source]))
        action = {"op": "replace", "memory_id": old["id"], "expected_version": old["version"],
                  "memory": content, "source_refs": [source], "bindings": [],
                  "confirmation_event_ref": confirmation, "consent_event_ref": consent}
        before = self.snapshot()
        self.store._failure_hook = fail
        self.assert_error("storage_failed", lambda: self.batch([action], nonce="replacement-failure"))
        self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.batch([action], nonce="replacement-failure")

    def test_request_local_replacement_preserves_promoted_long_term_original(self):
        short = self.confirm(self.candidate())
        long, _ = self.promote(short)
        source = self.intake("이번에는 검정")
        content = self.content(content="이번에는 검정을 원해요")
        proof = self.review(short, "replace", meaning=content | {"scope": "short_term"}, extra_refs=[source])
        self.batch([{"op": "replace", "memory_id": short["id"], "expected_version": short["version"],
            "memory": content, "bindings": [], "source_refs": [source],
            "confirmation_event_ref": proof, "consent_event_ref": None}])
        self.assertEqual(next(m for m in self.snapshot()["memories"] if m["scope"] == "long_term"), long)
        next_request = self.start("after-exception")
        self.assertEqual(self.snapshot(next_request)["memories"], [long])

    def test_review_and_user_event_storage_failures_are_atomic(self):
        memory = self.candidate()
        for failure in ("review_before_commit", "user_event_before_commit"):
            def fail(stage):
                if stage == failure:
                    raise RuntimeError("synthetic review storage failure")
            if failure == "review_before_commit":
                action = lambda: self.display("confirm_content", self.meaning(memory), [ref("memory", memory)])
            else:
                display = self.display("confirm_content", self.meaning(memory), [ref("memory", memory)])
                action = lambda: self.accept(display, command_id="retry-event")
            count = self.store.connection.execute("SELECT count(*) FROM v1_objects").fetchone()[0]
            self.store._failure_hook = fail
            self.assert_error("storage_failed", action)
            self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_objects").fetchone()[0], count)
            self.store._failure_hook = None
            action()

    def test_closed_short_term_withdrawal_and_withdrawal_rollback(self):
        memory = self.confirm(self.candidate())
        self.batch([{"op": "end_request"}])
        event = self.review(memory, "withdraw")
        action = {"op": "withdraw", "memory_id": memory["id"], "expected_version": memory["version"], "user_event_ref": event}
        before = self.snapshot()

        def fail(stage):
            if stage == "after_action":
                raise RuntimeError("synthetic withdrawal failure")

        self.store._failure_hook = fail
        self.assert_error("storage_failed", lambda: self.batch([action], nonce="withdraw-retry"))
        self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.batch([action], nonce="withdraw-retry")
        self.assertEqual(self.snapshot()["memories"], [])

    def test_malformed_action_versions_and_missing_batch_object_versions_are_rejected(self):
        memory = self.candidate()
        event = self.review(memory)
        action = self.confirm_action(memory, event)
        empty = self.expected() | {"object_versions": []}
        self.assert_error("invalid_input", lambda: self.batch([action], expected=empty))
        for modification in ({"expected_version": True}, {"expected_version": 1.0},
                             {"binding_confirmations": None}, {"memory_id": []}):
            self.assert_error("invalid_input", lambda: self.batch([action | modification]))
        self.assertFalse(self.snapshot()["memories"][0]["confirmed"])


if __name__ == "__main__":
    unittest.main()
