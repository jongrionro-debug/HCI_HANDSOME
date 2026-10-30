"""B3 regression checks on temporary synthetic databases and a fake catalog."""

import copy
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from stylemate_memory import contracts as c
from stylemate_memory.errors import StyleMateError
from stylemate_memory.store import MemoryStore


def ref(kind, obj):
    return {"type": kind, "id": obj["id"], "version": obj["version"]}


class FakeCatalog:
    def __init__(self):
        self.version = 1
        self.products = {f"product-{i}": {"product_id": f"product-{i}", "raw_version": 1, "map_version": 1} for i in (1, 2)}
        self.images = {f"image-{i}": 1 for i in (1, 2)}
        self.calls = []

    def current_versions(self, product_ids, image_ids):
        self.calls.append((list(product_ids), list(image_ids)))
        return copy.deepcopy({"catalog_version": self.version,
            "products": [self.products[p] for p in product_ids],
            "images": [{"image_id": i, "version": self.images[i]} for i in image_ids]})

    def resolve_image(self, image_id, *, version):
        if self.images[image_id] != version:
            raise StyleMateError("version_conflict")
        return {"image_id": image_id, "kind": "remote", "location": "https://example.invalid/synthetic.png",
            "source_revision": "synthetic-v1", "sha256": None,
            "regions": [{"region_id": "pants", "garment_type": "Pants", "box": [0, 0, 1, 1]},
                        {"region_id": "shirt", "garment_type": "Shirt", "box": [0, 0, 1, 0.5]}]}


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite3"
        self.now = datetime(2026, 10, 29, 9, tzinfo=timezone.utc)
        self.store = MemoryStore(self.path, clock=lambda: self.now)
        self.addCleanup(lambda: self.store.close())
        self.catalog = FakeCatalog()
        self.serial = 0
        self.request = self.start("first")

    def nonce(self):
        self.serial += 1
        return f"b3-{self.serial}"

    def start(self, nonce, user="u1"):
        return self.store.start_request(user, input_id=nonce, text=None, timezone="UTC",
            contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION,
            targets=[{"target_id": "pants-1", "garment_type": "Pants"}, {"target_id": "pants-2", "garment_type": "Pants"}])

    def snapshot(self, request=None, user="u1"):
        return self.store.snapshot(user, (request or self.request)["id"], contract_version=c.CONTRACT_VERSION, include_closed=True)

    def expected(self, snapshot=None):
        s = snapshot or self.snapshot()
        pairs = (("memory", "memories"), ("binding", "bindings"), ("evidence", "evidence"),
            ("round", "rounds"), ("candidate_set", "candidate_sets"), ("question", "questions"),
            ("feedback", "feedback"), ("interpretation", "interpretations"))
        return {"request_revision": s["request"]["revision"], "profile_revision": s["profile_revision"],
                "object_versions": [ref(kind, obj) for kind, key in pairs for obj in s[key]]}

    def basis(self):
        return self.expected() | {"request_id": self.request["id"], "contract_version": c.CONTRACT_VERSION,
            "registry_version": c.V1_REGISTRY_VERSION, "index_version": None, "valid_until": None,
            "catalog": self.catalog.current_versions(list(self.catalog.products), list(self.catalog.images))}

    def plan(self, *, questions=True):
        return {"basis": self.basis(), "compared_features": [{"domain": "PI", "feature": "Color"}],
            "cards": [{"candidate_id": f"card-{i}", "target_id": "pants-1", "product_id": f"product-{i}",
                       "product_map_version": 1, "image_id": f"image-{i}", "image_version": 1, "position": i - 1} for i in (1, 2)],
            "questions": [{"text": "어떤 부분이 마음에 드나요?", "target_id": "pants-1", "subject_refs": [],
                           "options": ["색", "핏", "모르겠음"]}] if questions else []}

    def publish(self, plan=None, nonce=None):
        return self.store.publish_candidates("u1", self.request["id"], batch_id=nonce or self.nonce(),
            plan=self.plan() if plan is None else plan, catalog_freshness=self.catalog)

    def action(self, *, reaction="selected", text=None, selections=None, question=False):
        snapshot = self.snapshot()
        round_obj = next((r for r in snapshot["rounds"] if r["status"] == "active"), None)
        return {"op": "submit_feedback", "round_id": round_obj["id"] if round_obj else None,
            "candidate_set_id": round_obj["candidate_set_ref"]["id"] if round_obj else None,
            "reaction": reaction, "selections": ([{"target_id": "pants-1", "candidate_id": "card-1", "part_ref": None}]
                if selections is None and reaction == "selected" else selections or []), "text": text,
            "question_id": round_obj["question_refs"][0]["id"] if question else None}

    def batch(self, actions, *, nonce=None, expected=None, catalog=True):
        return self.store.apply_batch("u1", self.request["id"], batch_id=nonce or self.nonce(), actions=actions,
            contract_version=c.CONTRACT_VERSION, expected=self.expected() if expected is None else expected,
            catalog_freshness=self.catalog if catalog else None)

    def feedback_ref(self, receipt):
        return next(r for r in receipt["changed_refs"] if r["type"] == "feedback")

    def state(self, receipt):
        return self.store.interpretation_status("u1", self.request["id"], self.feedback_ref(receipt))

    def extraction(self, receipt, *, error=None):
        evidence = next(e for e in self.snapshot()["evidence"] if e["id"] in {r["id"] for r in receipt["evidence_refs"]} and e["kind"] == "user_text")
        return {"op": "record_extraction", "feedback_ref": self.feedback_ref(receipt), "extraction_key": "synthetic-adapter-v1-key",
            "error": error, "result": None if error else {"candidates": [{"candidate_key": "draft-1", "content": evidence["quote"],
                "kind": "preference", "fact": None, "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
                "conditions": {}, "condition_quotes": {}, "polarity": "prefer", "strength": "soft", "origin_hint": "explicit",
                "scope_hint": "baseline", "source_ids": [evidence["id"]], "quote": evidence["quote"], "bindings": []}],
                "questions": ["이 내용을 맞게 이해했나요?"]}}

    def assert_error(self, code, call):
        with self.assertRaises(StyleMateError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def reopen(self):
        self.store.close()
        self.store = MemoryStore(self.path, clock=lambda: self.now)

    def fail_at(self, failure_stage):
        def fail(stage):
            if stage == failure_stage:
                raise RuntimeError("synthetic B3 storage failure")
        self.store._failure_hook = fail

    def test_new_set_is_immutable_and_round_version_increases_with_durable_replay(self):
        plan = self.plan()
        first = self.publish(plan, "publish-1")
        before = self.snapshot()["candidate_sets"][0]
        second = self.publish()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["version"], first["version"] + 1)
        self.assertNotEqual(first["candidate_set_ref"], second["candidate_set_ref"])
        self.assertIn(before, self.snapshot()["candidate_sets"])
        self.reopen()
        self.assertEqual(self.publish(plan, "publish-1"), first)
        self.assertEqual(len(self.snapshot()["candidate_sets"]), 2)
        plan["cards"][0]["product_id"] = "injected-product"
        self.assert_error("idempotency_conflict", lambda: self.publish(plan, "publish-1"))
        self.assertIn(before, self.snapshot()["candidate_sets"])

    def test_publication_rejects_invalid_cards_targets_and_missing_versions_atomically(self):
        base = self.plan()
        cases = []
        for changes in ({"target_id": "other-target"}, {"position": True}, {"image_version": None},
                        {"product_map_version": True}, {"unexpected": True}):
            plan = copy.deepcopy(base)
            plan["cards"][0].update(changes)
            cases.append(plan)
        for field in ("candidate_id", "position", "product_id"):
            plan = copy.deepcopy(base)
            plan["cards"][1][field] = plan["cards"][0][field]
            cases.append(plan)
        for cards in ([], base["cards"] * 3):
            cases.append(base | {"cards": cards})
        before = self.snapshot()
        for plan in cases:
            with self.subTest(plan=plan):
                self.assert_error("invalid_input", lambda: self.publish(plan))
                self.assertEqual(before, self.snapshot())
        plan = copy.deepcopy(base)
        plan["basis"]["catalog"]["products"].pop()
        self.assert_error("stale_context", lambda: self.publish(plan))

    def test_publication_storage_failure_rolls_back_sets_rounds_questions_and_receipt(self):
        self.publish()
        before = self.snapshot()
        for stage in ("candidates_after_set", "candidates_before_commit"):
            self.fail_at(stage)
            self.assert_error("storage_failed", lambda: self.publish(nonce="retry-publication"))
            self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.publish(nonce="retry-publication")
        self.assertEqual(len(self.snapshot()["candidate_sets"]), 2)

    def test_selected_partial_and_text_are_stored_once_without_rank_or_confirmation(self):
        self.publish()
        part = {"image_id": "image-2", "image_version": 1, "region_id": None, "box": [0.1, 0.2, 0.8, 1]}
        action = self.action(text="  A의 색에 B의 핏  ", selections=[
            {"target_id": "pants-1", "candidate_id": "card-2", "part_ref": part},
            {"target_id": "pants-1", "candidate_id": "card-1", "part_ref": None}])
        before_expected = self.expected()
        receipt = self.batch([action], nonce="feedback-once", expected=before_expected)
        self.assertEqual(self.batch([action], nonce="feedback-once", expected=before_expected), receipt)
        s = self.snapshot()
        self.assertEqual(len(s["evidence"]), 3)
        text = next(e for e in s["evidence"] if e["kind"] == "user_text")
        self.assertEqual(text["quote"], action["text"])
        chosen = [e["selection"] for e in s["evidence"] if e["kind"] == "image_selection"]
        self.assertEqual({e["product_id"] for e in chosen}, {"product-1", "product-2"})
        self.assertIn(part, [e["part_ref"] for e in chosen])
        self.assertTrue(all("rank" not in e for e in chosen))
        self.assertNotIn("text", s["feedback"][0])
        for key in ("memories", "bindings", "confirmations", "consents"):
            self.assertEqual(s[key], [])
        self.assertEqual(self.state(receipt)["status"], "pending")
        self.assertIsNone(s["request"]["final_selection"])
        self.assertEqual(s["request"]["status"], "open")
        self.reopen()
        self.assertEqual(s, self.snapshot())
        self.assert_error("idempotency_conflict", lambda: self.batch([action | {"text": "다른 본문"}], nonce="feedback-once"))
        self.assert_error("idempotency_conflict", lambda: self.publish(nonce="feedback-once"))

    def test_selection_text_and_question_all_rollback_and_retry_after_failure(self):
        self.publish()
        before = self.snapshot()
        action = self.action(text="색을 바꿔 주세요", question=True)
        for stage in ("feedback_after_selection", "feedback_after_evidence", "after_action", "before_receipt", "commit"):
            self.fail_at(stage)
            self.assert_error("storage_failed", lambda: self.batch([action], nonce="rollback-feedback"))
            self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.batch([action], nonce="rollback-feedback")
        self.assertEqual(self.snapshot()["questions"][0]["status"], "answered")
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_reactions_and_null_empty_text_contract(self):
        self.publish()
        cases = [self.action(text=""), self.action(text="   "), self.action(text="가" * 4001),
                 self.action(selections=[{}]), self.action(reaction="text_only"),
                 self.action(reaction="question_skipped"), self.action(reaction="invented"),
                 self.action() | {"selections": []}, self.action() | {"candidate_set_id": None}]
        for reaction in ("none", "unsure", "text_only", "question_skipped"):
            cases.append(self.action(reaction=reaction, text="응답", question=True) | {
                "selections": [{"candidate_id": "card-1", "target_id": "pants-1", "part_ref": None}]})
        before = self.snapshot()
        for action in cases:
            with self.subTest(action=action):
                self.assert_error("invalid_input", lambda: self.batch([action]))
                self.assertEqual(before, self.snapshot())
        for reaction in ("none", "unsure", "text_only"):
            self.batch([self.action(reaction=reaction, text="설명" if reaction == "text_only" else None)])
        self.assertEqual({f["reaction"] for f in self.snapshot()["feedback"]}, {"none", "unsure", "text_only"})
        self.assertEqual(self.snapshot()["memories"], [])

    def test_initial_text_has_null_round_set_and_no_catalog_dependency(self):
        receipt = self.batch([self.action(reaction="text_only", text="빈티지한 느낌")], catalog=False)
        f = self.snapshot()["feedback"][0]
        self.assertIsNone(f["round_ref"])
        self.assertIsNone(f["candidate_set_ref"])
        self.assertEqual(len(receipt["evidence_refs"]), 1)
        for reaction in ("selected", "none", "unsure"):
            self.assert_error("invalid_input", lambda: self.batch([self.action(reaction=reaction)], catalog=False))

    def test_partial_boxes_regions_duplicate_selection_and_limits(self):
        self.publish()
        part = {"image_id": "image-1", "image_version": 1, "region_id": None, "box": [0, 0, 1, 1]}
        for box in ([0, 0, 0, 1], [-0.1, 0, 1, 1], [0, 0, 1.1, 1], [0, 0, 1], [0, 0, True, 1],
                    [0, 0, float("nan"), 1], [0, 0, float("inf"), 1], "box"):
            selection = {"candidate_id": "card-1", "target_id": "pants-1", "part_ref": part | {"box": box}}
            self.assert_error("invalid_input", lambda: self.batch([self.action(selections=[selection])]))
        for changes in ({"image_id": "image-2"}, {"image_version": 2}, {"image_version": True},
                        {"box": None}, {"region_id": "pants"}, {"region_id": "missing", "box": None},
                        {"region_id": "shirt", "box": None}):
            selection = {"candidate_id": "card-1", "target_id": "pants-1", "part_ref": part | changes}
            self.assert_error("invalid_input", lambda: self.batch([self.action(selections=[selection])]))
        selection = {"candidate_id": "card-1", "target_id": "pants-1", "part_ref": part | {"region_id": "pants", "box": None}}
        self.batch([self.action(selections=[selection])])
        for selections in ([selection, selection], [selection] * 5):
            self.assert_error("invalid_input", lambda: self.batch([self.action(selections=selections)]))

    def test_missing_image_still_allows_whole_card_but_rejects_partial_selection(self):
        plan = self.plan()
        plan["cards"][0].update(image_id=None, image_version=None)
        self.publish(plan)
        self.batch([self.action()])
        part = {"image_id": "image-1", "image_version": 1, "region_id": None, "box": [0, 0, 1, 1]}
        self.assert_error("invalid_input", lambda: self.batch([self.action(selections=[{
            "candidate_id": "card-1", "target_id": "pants-1", "part_ref": part}])]))

    def test_all_cards_map_raw_and_image_versions_are_checked_including_unselected(self):
        self.publish()
        for kind, key in (("product", "map_version"), ("product", "raw_version"), ("image", "version")):
            before = self.snapshot()
            if kind == "product":
                self.catalog.products["product-2"][key] += 1
            else:
                self.catalog.images["image-2"] += 1
            self.assert_error("stale_context", lambda: self.batch([self.action(text="함께 실패해야 하는 텍스트")]))
            self.assertEqual(before, self.snapshot())
            self.assertEqual(set(self.catalog.calls[-1][0]), {"product-1", "product-2"})
            self.assertEqual(set(self.catalog.calls[-1][1]), {"image-1", "image-2"})
            if kind == "product":
                self.catalog.products["product-2"][key] -= 1
            else:
                self.catalog.images["image-2"] -= 1
        self.assert_error("stale_context", lambda: self.batch([self.action()], catalog=False))
        del self.catalog.products["product-2"]
        self.assert_error("stale_context", lambda: self.batch([self.action()]))

    def test_stale_versions_replaced_sets_foreign_ownership_and_wrong_targets(self):
        first = self.publish()
        old_action, old_expected = self.action(), self.expected()
        self.publish()
        self.assert_error("version_conflict", lambda: self.batch([old_action], expected=old_expected))
        self.assert_error("stale_context", lambda: self.batch([old_action]))
        current = self.action()
        for selection in ({"candidate_id": "product-1", "target_id": "pants-1", "part_ref": None},
                          {"candidate_id": "card-1", "target_id": "pants-2", "part_ref": None}):
            self.assert_error("invalid_input", lambda: self.batch([current | {"selections": [selection]}]))
        missing = self.expected() | {"object_versions": []}
        self.assert_error("invalid_input", lambda: self.batch([current], expected=missing))
        for user in ("u1", "u2"):
            other = self.start(self.nonce(), user)
            self.assert_error("not_found", lambda: self.store.apply_batch(user, other["id"], batch_id=self.nonce(),
                actions=[current], contract_version=c.CONTRACT_VERSION,
                expected={"request_revision": 1, "profile_revision": 0, "object_versions": []}, catalog_freshness=self.catalog))
        self.assertEqual(first["version"], 1)

    def test_question_skip_is_only_a_skip_and_survives_restart(self):
        self.publish()
        action = self.action(reaction="question_skipped", question=True)
        receipt = self.batch([action])
        before = self.snapshot()
        self.assertEqual(before["questions"][0]["status"], "skipped")
        self.assertEqual(before["questions"][0]["version"], 2)
        self.assertEqual(before["evidence"][0]["kind"], "ui_response")
        self.assertIsNone(before["evidence"][0]["quote"])
        self.assertEqual(before["memories"], [])
        self.reopen()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.state(receipt)["status"], "pending")
        self.assert_error("stale_context", lambda: self.batch([action]))

    def test_question_from_previous_set_or_wrong_target_is_rejected(self):
        self.publish()
        old_question = self.action(question=True)["question_id"]
        self.publish()
        self.assert_error("invalid_input", lambda: self.batch([self.action(question=True) | {"question_id": old_question}]))
        self.assert_error("invalid_input", lambda: self.batch([self.action(reaction="question_skipped") | {
            "round_id": None, "candidate_set_id": None, "question_id": old_question}]))
        qid = self.action(question=True)["question_id"]
        action = self.action(reaction="question_skipped", question=True) | {"round_id": None, "candidate_set_id": None}
        self.assert_error("invalid_input", lambda: self.batch([action]))
        self.assert_error("not_found", lambda: self.batch([self.action(question=True) | {"question_id": "missing"}]))
        self.assertTrue(qid)
        plan = self.plan()
        plan["cards"][1]["target_id"] = "pants-2"
        self.publish(plan)
        action = self.action(question=True, selections=[{"candidate_id": "card-2", "target_id": "pants-2", "part_ref": None}])
        self.assert_error("invalid_input", lambda: self.batch([action]))

    def test_intake_success_model_failure_pending_reprocess_and_immutable_receipt(self):
        action = self.action(reaction="text_only", text="네이비를 좋아해요")
        receipt = self.batch([action], nonce="intake")
        evidence_before = self.snapshot()["evidence"]
        error = {"code": "provider_timeout", "message": "unsafe provider body should never persist"}
        self.batch([self.extraction(receipt, error=error)], nonce="model-error")
        failed = self.state(receipt)
        self.assertEqual(failed["status"], "pending")
        self.assertEqual(failed["error"]["code"], "provider_timeout")
        self.assertNotIn("unsafe", failed["error"]["message"])
        self.reopen()
        self.assertEqual(self.state(receipt), failed)
        extract = self.extraction(receipt)
        self.batch([extract], nonce="model-success")
        completed = self.state(receipt)
        self.assertEqual(completed["status"], "complete")
        self.assertIsNone(completed["error"])
        self.assertGreater(completed["version"], failed["version"])
        self.assertEqual(evidence_before, self.snapshot()["evidence"])
        memory = self.snapshot()["memories"][0]
        self.assertEqual((memory["scope"], memory["status"], memory["confirmed"], memory["origin"]),
                         ("short_term", "candidate", False, "inferred"))
        self.assertIsNone(memory["consent_ref"])
        self.assertEqual(self.batch([extract], nonce="same-extraction-new-batch")["outcome"], "unchanged")
        self.assertEqual(len(self.snapshot()["memories"]), 1)
        self.assertEqual(self.batch([action], nonce="intake"), receipt)
        different = copy.deepcopy(extract)
        different["result"]["questions"] = []
        self.assert_error("idempotency_conflict", lambda: self.batch([different]))
        # A late error cannot change a completed interpretation back to pending.
        self.assertEqual(self.batch([self.extraction(receipt, error=error)])["outcome"], "unchanged")

    def test_extraction_rollback_has_no_duplicate_candidates_or_copied_text(self):
        receipt = self.batch([self.action(reaction="text_only", text="네이비를 좋아해요")])
        action = self.extraction(receipt)
        before = self.snapshot()
        for stage in ("extraction_after_candidate", "extraction_before_complete", "before_receipt"):
            self.fail_at(stage)
            self.assert_error("storage_failed", lambda: self.batch([action], nonce="retry-extraction"))
            self.assertEqual(before, self.snapshot())
        self.store._failure_hook = None
        self.batch([action], nonce="retry-extraction")
        self.assertEqual(len(self.snapshot()["evidence"]), 1)
        self.assertEqual(len(self.snapshot()["questions"]), 1)
        self.assertEqual(self.store.connection.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_model_authority_invented_sources_and_false_quotes_do_not_write_candidates(self):
        receipt = self.batch([self.action(reaction="text_only", text="네이비를 좋아해요")])
        base = self.extraction(receipt)
        for changes in ({"confirmed": True}, {"scope": "long_term"}, {"source_ids": ["invented-source"]},
                        {"quote": "없는 발화"}, {"selector": {"garment_type": "Pants", "slot_id": "foreign-target"}}):
            action = copy.deepcopy(base)
            action["result"]["candidates"][0].update(changes)
            before = self.snapshot()
            self.assert_error("invalid_extraction", lambda: self.batch([action]))
            self.assertEqual(before, self.snapshot())
        self.assert_error("invalid_input", lambda: self.batch([base | {"result": None}]))
        self.assert_error("invalid_input", lambda: self.batch([base | {"error": {"code": "provider_error", "message": "error"}}]))

    def test_new_feedback_close_or_expiry_rejects_late_extraction(self):
        receipt = self.batch([self.action(reaction="text_only", text="네이비를 좋아해요")])
        old = self.extraction(receipt)
        next_receipt = self.batch([self.action(reaction="text_only", text="두 번째 입력")])
        self.assert_error("stale_context", lambda: self.batch([old]))
        latest = self.extraction(next_receipt)
        self.batch([{"op": "end_request"}])
        self.assert_error("request_closed", lambda: self.batch([latest]))
        self.now = datetime.fromisoformat(self.snapshot()["request"]["retention_until"]) + timedelta(microseconds=1)
        self.assert_error("request_expired", lambda: self.batch([latest]))

    def test_replaced_or_changed_catalog_prevents_late_selection_interpretation(self):
        self.publish()
        receipt = self.batch([self.action(text="색이 좋아요")])
        action = self.extraction(receipt)
        self.catalog.images["image-2"] += 1
        self.assert_error("stale_context", lambda: self.batch([action]))
        self.catalog.images["image-2"] -= 1
        self.publish()
        self.assert_error("stale_context", lambda: self.batch([action]))

    def test_extraction_questions_can_be_answered_without_a_round(self):
        receipt = self.batch([self.action(reaction="text_only", text="네이비를 좋아해요")])
        self.batch([self.extraction(receipt)])
        q = self.snapshot()["questions"][0]
        action = self.action(reaction="text_only", text="색만 맞아요") | {"question_id": q["id"]}
        self.batch([action])
        self.assertEqual(self.snapshot()["questions"][0]["status"], "answered")
        self.assertEqual(self.snapshot()["confirmations"], [])
        self.assertFalse(self.snapshot()["memories"][0]["confirmed"])

    def test_extracted_comparison_question_can_be_answered_and_reviewed_in_same_set(self):
        self.publish()
        receipt = self.batch([self.action(text="네이비 후보가 좋아요")])
        action = self.extraction(receipt)
        selection = next(e for e in self.snapshot()["evidence"] if e["kind"] == "image_selection")
        action["result"]["candidates"][0]["source_ids"].append(selection["id"])
        self.batch([action])
        s = self.snapshot()
        state = self.state(receipt)
        round_obj = s["rounds"][0]
        self.assertGreater(round_obj["version"], 1)
        self.assertIn(state["question_refs"][0], round_obj["question_refs"])
        # The Evidence's historical round version is preserved while the
        # reviewed cards remain the same, even after a new question was added.
        memory = s["memories"][0]
        self.accept(self.display(memory))
        question = state["question_refs"][0]
        response = self.action(reaction="text_only", text="색만 맞아요") | {"question_id": question["id"]}
        self.batch([response])
        updated = next(q for q in self.snapshot()["questions"] if q["id"] == question["id"])
        self.assertEqual(updated["status"], "answered")
        self.assertEqual(self.snapshot()["consents"], [])

    def test_real_catalog_port_metadata_freshness_and_named_region_stay_offline(self):
        from stylemate_memory.catalog import Catalog
        from stylemate_memory.catalog_io import load_records

        records = load_records(Path(__file__).parent / "fixtures" / "catalog" / "valid.json")
        records[0]["images"][0].update(kind="remote", location="https://images.example.invalid/synthetic.png")
        catalog = Catalog(Path(self.temp.name) / "separate-catalog.sqlite3", allowed_image_hosts=("images.example.invalid",))
        self.addCleanup(catalog.close)
        with patch("socket.create_connection", side_effect=AssertionError("B3 must stay offline")) as network:
            catalog.import_records(records)
            for record in records:
                catalog.save_product_map({"subject": "product", "product_id": record["product_id"], "raw_version": 1,
                    "map_version": 1, "registry_version": c.V1_REGISTRY_VERSION, "assertions": record["labels"]},
                    expected_raw_version=1, expected_map_version=None)
            plan = self.plan()
            plan["basis"]["catalog"] = catalog.current_versions([r["product_id"] for r in records],
                [r["images"][0]["image_id"] for r in records])
            for card, record in zip(plan["cards"], records):
                card.update(product_id=record["product_id"], image_id=record["images"][0]["image_id"])
            self.catalog = catalog
            self.publish(plan)
            part = {"image_id": records[0]["images"][0]["image_id"], "image_version": 1, "region_id": "pants", "box": None}
            self.batch([self.action(selections=[{"target_id": "pants-1", "candidate_id": "card-1", "part_ref": part}])])
            records[1]["images"][0]["source_revision"] = "supplied-2"
            catalog.import_records([records[1]])
            self.assert_error("stale_context", lambda: self.batch([self.action()]))
            network.assert_not_called()

    def test_image_selection_can_only_propose_unconfirmed_soft_hypotheses(self):
        self.publish()
        receipt = self.batch([self.action()])
        source_id = receipt["evidence_refs"][0]["id"]
        candidate = {"candidate_key": "image-hypothesis", "content": "이 후보의 색이 마음에 들 수 있음",
            "kind": "preference", "fact": None, "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
            "conditions": {}, "condition_quotes": {}, "polarity": "prefer", "strength": "soft", "origin_hint": "inferred",
            "scope_hint": "unknown", "source_ids": [source_id], "quote": None, "bindings": []}
        action = {"op": "record_extraction", "feedback_ref": self.feedback_ref(receipt), "extraction_key": "image-key",
                  "result": {"candidates": [candidate], "questions": []}, "error": None}
        for changes in ({"polarity": "avoid"}, {"origin_hint": "explicit"}, {"strength": "hard"}, {"kind": "requirement"}):
            invalid = copy.deepcopy(action)
            invalid["result"]["candidates"][0].update(changes)
            self.assert_error("invalid_extraction", lambda: self.batch([invalid]))
        self.batch([action])
        memory = self.snapshot()["memories"][0]
        self.assertEqual((memory["confirmed"], memory["origin"], memory["status"]), (False, "inferred", "candidate"))
        self.assertEqual(len(self.snapshot()["evidence"]), 1)

    def test_none_unsure_and_question_skip_cannot_supply_preference_sources(self):
        self.publish()
        for reaction in ("none", "unsure", "question_skipped"):
            receipt = self.batch([self.action(reaction=reaction, question=reaction == "question_skipped")])
            source = receipt["evidence_refs"][0]
            candidate = {"candidate_key": "invented-preference", "content": "모두 싫어함", "kind": "preference", "fact": None,
                "selector": {"garment_type": "Pants", "slot_id": "pants-1"}, "conditions": {}, "condition_quotes": {},
                "polarity": "avoid", "strength": "soft", "origin_hint": "inferred", "scope_hint": "unknown",
                "source_ids": [source["id"]], "quote": None, "bindings": []}
            action = {"op": "record_extraction", "feedback_ref": self.feedback_ref(receipt), "extraction_key": self.nonce(),
                      "result": {"candidates": [candidate], "questions": []}, "error": None}
            self.assert_error("invalid_extraction", lambda: self.batch([action]))
            self.batch([action | {"result": {"candidates": [], "questions": []}}])
        self.assertEqual(self.snapshot()["memories"], [])
        self.assertEqual(self.snapshot()["consents"], [])

    def image_memory(self):
        self.publish()
        receipt = self.batch([self.action()])
        content = {"kind": "preference", "content": "이 후보의 색이 마음에 들 수 있음", "fact": None,
            "selector": {"garment_type": "Pants", "slot_id": None}, "conditions": {}, "polarity": "prefer",
            "strength": "soft", "valid_from": None, "valid_until": None}
        self.batch([{"op": "create", "memory": content, "source_refs": receipt["evidence_refs"], "bindings": [],
                     "confirmation_event_ref": None, "consent_event_ref": None}])
        return self.snapshot()["memories"][0]

    def display(self, memory, purpose="confirm_content", *, basis=None):
        meaning = {key: memory[key] for key in c.MemoryContent.__required_keys__} | {
            "scope": "long_term" if purpose == "future_reuse" else memory["scope"]}
        return self.store.issue_display("u1", self.request["id"], purpose=purpose,
            snapshot={"meaning": meaning, "bindings": [], "subject_refs": [ref("memory", memory)]}, basis=self.basis() if basis is None else basis)

    def accept(self, display):
        return self.store.record_user_event("u1", self.request["id"], command_id=self.nonce(),
            display_ref=ref("display", display), purpose=display["purpose"], expected=self.expected())

    def test_review_cannot_omit_unselected_cards_or_comparison_dependencies(self):
        memory = self.image_memory()
        basis = self.basis()
        basis["catalog"]["images"].pop()
        self.assert_error("stale_context", lambda: self.display(memory, basis=basis))
        basis = self.basis()
        basis["object_versions"] = [r for r in basis["object_versions"] if r["type"] != "candidate_set"]
        self.assert_error("stale_context", lambda: self.display(memory, basis=basis))
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_displays").fetchone()[0], 0)

    def test_changed_unselected_image_rejects_confirmation_without_consuming_event(self):
        memory = self.image_memory()
        display = self.display(memory)
        event = self.accept(display)
        action = {"op": "confirm", "memory_id": memory["id"], "expected_version": memory["version"],
                  "confirmation_event_ref": event, "binding_confirmations": []}
        before = self.snapshot()
        self.catalog.images["image-2"] += 1
        self.assert_error("stale_context", lambda: self.batch([action], nonce="retry-confirm"))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.store.connection.execute("SELECT count(*) FROM v1_event_uses").fetchone()[0], 0)
        self.catalog.images["image-2"] -= 1
        self.batch([action], nonce="retry-confirm")
        self.assertTrue(self.snapshot()["memories"][0]["confirmed"])
        self.assertEqual(self.snapshot()["consents"], [])

    def test_future_reuse_is_separate_and_stale_comparison_rejects_consent(self):
        memory = self.image_memory()
        event = self.accept(self.display(memory))
        self.batch([{"op": "confirm", "memory_id": memory["id"], "expected_version": memory["version"],
                     "confirmation_event_ref": event, "binding_confirmations": []}])
        memory = self.snapshot()["memories"][0]
        display = self.display(memory, "future_reuse")
        consent_event = self.accept(display)
        action = {"op": "promote", "memory_id": memory["id"], "expected_version": memory["version"], "consent_event_ref": consent_event}
        self.catalog.products["product-2"]["map_version"] += 1
        self.assert_error("stale_context", lambda: self.batch([action]))
        self.assertEqual(self.snapshot()["consents"], [])
        self.assertEqual({m["scope"] for m in self.snapshot()["memories"]}, {"short_term"})
        self.catalog.products["product-2"]["map_version"] -= 1
        self.publish()
        self.assert_error("stale_context", lambda: self.accept(display))
        self.assert_error("stale_context", lambda: self.batch([action]))

    def test_closed_request_can_separately_reuse_already_confirmed_image_memory(self):
        memory = self.image_memory()
        event = self.accept(self.display(memory))
        self.batch([{"op": "confirm", "memory_id": memory["id"], "expected_version": memory["version"],
                     "confirmation_event_ref": event, "binding_confirmations": []}])
        memory = self.snapshot()["memories"][0]
        self.batch([{"op": "end_request"}])
        self.assertEqual(self.snapshot()["consents"], [])
        # Wrap-up can review the confirmed sentence independently of images.
        basis = self.basis() | {"catalog": None, "object_versions": [ref("memory", memory)]}
        display = self.display(memory, "future_reuse", basis=basis)
        event = self.accept(display)
        self.batch([{"op": "promote", "memory_id": memory["id"], "expected_version": memory["version"],
                     "consent_event_ref": event}], catalog=False)
        self.assertEqual(self.snapshot()["request"]["status"], "closed")
        self.assertEqual({m["scope"] for m in self.snapshot()["memories"]}, {"short_term", "long_term"})
        self.assertEqual(len(self.snapshot()["consents"]), 1)

    def test_final_selection_and_end_are_separate_from_feedback_confirmation_and_consent(self):
        self.publish()
        current = self.snapshot()["rounds"][0]
        self.batch([{"op": "select_final", "candidate_set_ref": current["candidate_set_ref"], "candidate_id": "card-2"}])
        s = self.snapshot()
        self.assertEqual(s["request"]["status"], "open")
        self.assertEqual(s["request"]["final_selection"]["product_id"], "product-2")
        self.batch([{"op": "select_final", "candidate_set_ref": current["candidate_set_ref"], "candidate_id": candidate}
                    for candidate in ("card-1", "card-2")])
        self.assertEqual(self.snapshot()["request"]["final_selection"], s["request"]["final_selection"])
        for key in ("evidence", "memories", "feedback", "confirmations", "consents"):
            self.assertEqual(s[key], [])
        self.batch([{"op": "end_request"}])
        ended = self.snapshot()
        self.assertEqual(ended["request"]["final_selection"], s["request"]["final_selection"])
        self.assertEqual(ended["rounds"][0]["status"], "closed")
        self.reopen()
        self.assertEqual(ended, self.snapshot())
        self.assert_error("request_closed", lambda: self.batch([self.action(reaction="text_only", text="늦은 입력")]))
        self.assert_error("request_closed", lambda: self.publish())

    def test_feedback_is_a_single_action_batch(self):
        action = self.action(reaction="text_only", text="원문")
        before = self.snapshot()
        self.assert_error("invalid_input", lambda: self.batch([action, {"op": "end_request"}]))
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
