"""Synthetic FEA->PI interaction, using real SQLite and issued display proofs."""
from copy import deepcopy
import json

from tests.test_consumer_service import ServiceFixture
from stylemate_memory.model_io import validate_proposal_v1
from stylemate_memory.errors import StyleMateError


class HypothesisGateway:
    model = "synthetic-hypothesis"

    def extract(self, inputs):
        self.extraction_inputs = getattr(self, "extraction_inputs", []) + [deepcopy(inputs)]
        source = next((s for s in inputs["sources"] if s["kind"] == "user_text"), None)
        if source is None:
            return {"candidates": [], "questions": []}
        if "허벅지" in source["content"]:
            if getattr(self, "fail_reason", False):
                raise StyleMateError("provider_timeout")
            base = {"selector": {"garment_type": "Pants", "slot_id": None}, "conditions": {}, "condition_quotes": {},
                    "strength": "soft", "origin_hint": "explicit", "scope_hint": "current", "bindings": []}
            result = {"candidates": [
                base | {"candidate_key": "reason", "kind": "preference", "content": "허벅지가 조이는 옷을 피하고 싶다", "fact": None,
                        "polarity": "avoid", "source_ids": [source["source_id"]], "quote": "허벅지가 조이는 건 싫어요."},
                base | {"candidate_key": "situation", "kind": "situation", "content": "오래 앉아 있는 상황에서 입는다",
                        "fact": {"key": "activity", "value": "오래 앉아"}, "polarity": "prefer",
                        "source_ids": [source["source_id"]], "quote": "오래 앉아 있어요."}], "questions": []}
            if getattr(self, "reason_slot", False):
                result["candidates"][0]["selector"] = {"garment_type": "Pants", "slot_id": "pants"}
                result["candidates"][0]["source_ids"] = [s["source_id"] for s in inputs["sources"]]
            return result
        result = {"candidates": [{"candidate_key": "ease", "content": source["content"], "kind": "preference", "fact": None,
            "selector": {"garment_type": "Pants", "slot_id": None}, "conditions": {}, "condition_quotes": {},
            "polarity": "prefer", "strength": "soft", "origin_hint": "explicit", "scope_hint": "current",
            "source_ids": [source["source_id"]], "quote": source["content"],
            "bindings": [{"domain": "FEA", "category": "Functional", "subcategory": "Donning", "tag": "Ease",
                          "polarity": "prefer", "strength": "soft"}]}], "questions": []}
        if getattr(self, "hard", False):
            result["candidates"][0].update(kind="requirement", polarity="require", strength="hard")
            result["candidates"][0]["bindings"][0].update(polarity="require", strength="hard")
        if getattr(self, "direct_fit", False):
            direct = deepcopy(result["candidates"][0])
            direct["candidate_key"] = "direct-fit"
            direct["bindings"] = [{"domain": "PI", "feature": "Fit", "values": ["Straight"], "match": "any", "polarity": "prefer", "strength": "soft"}]
            result["candidates"].append(direct)
        return result

    def propose(self, inputs):
        self.inputs = deepcopy(inputs)
        parent = next((c for c in inputs["constraints"] if c["binding"]["domain"] == "FEA"), None)
        self.proposal = {"suggestions": [{"target_id": parent["target_id"],
            "binding": {"domain": "PI", "feature": "Fit", "values": ["Wide"], "match": "any", "polarity": "prefer", "strength": "soft"},
            "source_ids": parent["source_ids"], "reason": "이번 편안함을 와이드핏으로 구체화할 수 있는지 비교", "fea_constraint_ids": [parent["id"]]}]
            if parent else [], "questions": []}
        return deepcopy(self.proposal)


class HypothesisTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.service.close()
        self.gateway = HypothesisGateway()
        self.service = self.open_service()
        self.records[1]["raw_metadata"]["supplier_color"] = "Navy"
        self.records[1]["raw_metadata"]["supplier_fit"] = "Straight"
        self.records[0]["title"] = "A · 합성 와이드핏 바지"
        self.records[1]["title"] = "B · 합성 스트레이트핏 바지"
        self.data.write_text(json.dumps(self.records))
        self.service.import_catalog(self.data)
        self.service.build_catalog_maps()

    def comparison(self):
        self.start("편안한 바지를 원해요")
        memory = next(m for m in self.state()["memories"] if m["scope"] == "short_term" and m["content"] == "편안한 바지를 원해요")
        self.review("confirm_content", memory)
        memory = next(m for m in self.state()["memories"] if m["ref"]["id"] == memory["ref"]["id"])
        self.review("confirm_bindings", memory)
        self.send({"op": "explore"})
        self.service.wait_idle()
        state = self.state()
        self.assertIsNotNone(state["comparison"], state)
        return state

    def answer(self, state, decision="choose", index=0, text=None, **kwargs):
        return self.send({"op": "respond_comparison", "candidate_set_ref": state["comparison"]["candidate_set_ref"], "text": text,
                          "candidate_id": state["comparison"]["options"][index]["candidate_id"] if decision == "choose" else None,
                          "decision": decision}, **kwargs)

    def test_product_maps_are_pi_only_and_comparison_does_not_fill_direct_pi(self):
        state = self.comparison()
        self.assertEqual(len(state["comparison"]["options"]), 2)
        self.assertIn("편안함", state["comparison"]["prompt"])
        for record in self.records:
            mapped = self.service._run(self.service._catalog.get_product_map, record["product_id"])
            self.assertEqual(len(mapped["assertions"]), 7)
            self.assertTrue(all(a["observation"]["domain"] == "PI" for a in mapped["assertions"]))
        self.assertFalse(any(b["domain"] == "PI" for b in self.snapshot()["bindings"]))
        self.assertFalse(state["reviews"], "comparison options must not appear as duplicate review dialogs")
        from stylemate_memory.hypotheses import load_comparison
        stored = self.service._run(load_comparison, self.service, state["comparison"]["candidate_set_ref"]["id"])
        self.assertEqual(stored["hypothesis"]["fea"][0]["tag"], "Ease")
        self.assertTrue(stored["hypothesis"]["reason"])
        self.assertTrue(stored["hypothesis"]["source_refs"])

    def test_choose_confirms_only_shown_pi_preserves_inferred_origin_and_replay(self):
        state = self.comparison()
        selected = state["comparison"]["options"][0]
        result, command = self.answer(state)
        self.assertNotEqual(result["outcome"], "rejected", result)
        self.service.wait_idle()
        bindings = [b for b in self.snapshot()["bindings"] if b["domain"] == "PI"]
        self.assertEqual(len(bindings), 1)
        self.assertTrue(bindings[0]["confirmed"])
        self.assertEqual(bindings[0]["origin"], "inferred")
        self.assertEqual(bindings[0]["strength"], "soft")
        self.assertIn(bindings[0]["values"][0], selected["label"])
        self.assertTrue(all(m["scope"] == "short_term" for m in self.snapshot()["memories"]))
        self.assertIsNone(self.state()["comparison"])
        self.assertEqual(self.state()["operation"], "idle")
        request_id = self.state()["request"]["id"]
        context = self.service._run(lambda: self.service._context(self.service._snapshot(request_id)))
        self.assertTrue(any(c["binding"]["domain"] == "PI" for c in context["constraints"]))
        self.send(None, command=command)
        self.assertEqual(len([b for b in self.snapshot()["bindings"] if b["domain"] == "PI"]), 1)

    def test_alternative_choice_changes_interpretation(self):
        state = self.comparison()
        index = next(i for i, o in enumerate(state["comparison"]["options"]) if "Straight" in o["label"])
        self.answer(state, index=index)
        self.service.wait_idle()
        self.assertEqual(next(b["values"] for b in self.snapshot()["bindings"] if b["domain"] == "PI"), ["Straight"])

    def test_unsure_and_neither_do_not_confirm_or_repeat_same_hypothesis(self):
        for decision in ("unsure", "neither"):
            with self.subTest(decision=decision):
                state = self.comparison()
                self.answer(state, decision)
                self.service.wait_idle()
                self.assertFalse(any(b["domain"] == "PI" for b in self.snapshot()["bindings"]))
                self.assertIsNone(self.state()["comparison"])

    def test_restart_preserves_issued_comparison(self):
        state = self.comparison()
        self.service.close()
        self.service = self.open_service()
        self.assertEqual(self.state()["comparison"], state["comparison"])
        self.answer(self.state())
        self.service.wait_idle()
        self.assertTrue(any(b["domain"] == "PI" and b["confirmed"] for b in self.snapshot()["bindings"]))

    def test_stale_catalog_and_foreign_candidate_cannot_confirm(self):
        state = self.comparison()
        action = {"op": "respond_comparison", "candidate_set_ref": state["comparison"]["candidate_set_ref"],
                  "candidate_id": "not-issued", "decision": "choose"}
        self.assertEqual(self.send(action, ok=False)[0]["outcome"], "rejected")
        self.records[0]["images"][0]["source_revision"] = "changed"
        self.data.write_text(json.dumps(self.records))
        self.service.import_catalog(self.data)
        self.assertEqual(self.answer(state, ok=False)[0]["outcome"], "rejected")
        self.assertFalse(any(b["domain"] == "PI" for b in self.snapshot()["bindings"]))

    def test_bad_fea_grounding_and_hard_hypotheses_are_rejected(self):
        self.comparison()
        proposal, inputs = self.gateway.proposal, self.gateway.inputs
        for change in ("unknown", "hard", "source"):
            bad = deepcopy(proposal)
            if change == "unknown":
                bad["suggestions"][0]["fea_constraint_ids"] = ["unknown"]
            elif change == "hard":
                bad["suggestions"][0]["binding"]["strength"] = "hard"
            else:
                bad["suggestions"][0]["source_ids"] = []
            with self.assertRaises(StyleMateError):
                validate_proposal_v1(bad, inputs, self.service.registry)

    def test_no_negative_example_when_fit_is_unknown(self):
        self.records[1]["raw_metadata"].pop("supplier_fit")
        self.data.write_text(json.dumps(self.records))
        self.service.import_catalog(self.data)
        self.service.build_catalog_maps()
        self.start("편안한 바지를 원해요")
        self.review("confirm_content")
        self.review("confirm_bindings")
        self.send({"op": "explore"})
        self.service.wait_idle()
        self.assertIsNone(self.state()["comparison"])
        self.assertFalse(any(b["domain"] == "PI" for b in self.snapshot()["bindings"]))

    def test_erasing_source_memory_cascades_comparison_payload(self):
        self.comparison()
        self.review("delete")
        count = self.service._run(lambda: self.service._store.connection.execute("SELECT count(*) FROM consumer_comparisons").fetchone()[0])
        self.assertEqual(count, 0)
        self.assertIsNone(self.state()["comparison"])

    def test_atomic_failure_keeps_selection_and_confirmation_unapplied(self):
        state = self.comparison()
        count = len(self.snapshot()["feedback"])
        def hook(point, info=None):
            if point == "after_action" and info and info.get("op") == "record_comparison":
                raise RuntimeError("synthetic rollback")
        self.service._run(setattr, self.service._store, "_failure_hook", hook)
        try:
            result, command = self.answer(state, ok=False)
            self.assertEqual(result["outcome"], "rejected")
            self.assertFalse(any(b["domain"] == "PI" for b in self.snapshot()["bindings"]))
            self.assertEqual(len(self.snapshot()["feedback"]), count)
        finally:
            self.service._run(setattr, self.service._store, "_failure_hook", None)
        self.send(None, command=command)
        self.service.wait_idle()
        self.assertTrue(any(b["domain"] == "PI" and b["confirmed"] for b in self.snapshot()["bindings"]))

    def test_direct_pi_does_not_get_overwritten_by_fea_hypothesis(self):
        self.gateway.direct_fit = True
        self.start("편안한 스트레이트핏 바지를 원해요")
        for index in range(2):
            self.review("confirm_content", self.state()["memories"][index])
            self.review("confirm_bindings", self.state()["memories"][index])
        self.send({"op": "explore"})
        self.service.wait_idle()
        self.assertIsNone(self.state()["comparison"])
        self.assertEqual([b["values"] for b in self.snapshot()["bindings"] if b["domain"] == "PI"], [["Straight"]])

    def test_hard_fea_can_be_explored_but_pi_choice_does_not_verify_performance(self):
        self.gateway.hard = True
        state = self.comparison()
        self.answer(state)
        self.service.wait_idle()
        state = self.state()
        active = next(r for r in self.snapshot()["rounds"] if r["status"] == "active")
        result, _ = self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"],
                               "candidate_id": state["cards"][0]["candidate_id"]}, ok=False)
        self.assertEqual(result["outcome"], "rejected")
        self.assertIsNone(self.state()["request"]["final_selection"])

    def test_optional_reason_is_received_with_image_and_becomes_unconfirmed_memories(self):
        state = self.comparison()
        reason = "오래 앉아 있어요. 허벅지가 조이는 건 싫어요."
        self.answer(state, text=reason)
        self.service.wait_idle()
        snapshot = self.snapshot()
        feedback = next(f for f in snapshot["feedback"] if f["reaction"] == "selected")
        evidence = [e for e in snapshot["evidence"] if e["id"] in {r["id"] for r in feedback["evidence_refs"]}]
        self.assertEqual({e["kind"] for e in evidence}, {"image_selection", "user_text"})
        self.assertEqual(next(e["quote"] for e in evidence if e["kind"] == "user_text"), reason)
        self.assertEqual(feedback["reaction"], "selected")
        self.assertFalse(any(b["domain"] == "PI" and b["confirmed"] for b in snapshot["bindings"]))
        learned = [m for m in snapshot["memories"] if "허벅지" in m["content"] or m["kind"] == "situation"]
        self.assertEqual(len(learned), 2)
        self.assertTrue(all(not m["confirmed"] and m["scope"] == "short_term" for m in learned))
        self.assertEqual({s["kind"] for s in self.gateway.extraction_inputs[-1]["sources"]}, {"image_selection", "user_text"})
        self.assertFalse(snapshot["consents"])
        self.assertIsNone(self.state()["comparison"])

    def test_consent_is_end_only_and_existing_reason_can_be_reviewed_after_close(self):
        state = self.comparison()
        original = self.state()["memories"][0]
        rejected, _ = self.send({"op": "prepare_review", "purpose": "future_reuse", "subject_refs": [original["ref"]], "proposed_text": None}, ok=False)
        self.assertEqual(rejected["error"]["code"], "consent_required")
        self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.")
        self.service.wait_idle()
        self.send({"op": "end_request"})
        self.assertFalse(self.snapshot()["consents"])
        memory = next(m for m in self.state()["memories"] if "허벅지" in m["content"])
        self.review("confirm_content", memory)
        memory = next(m for m in self.state()["memories"] if "허벅지" in m["content"])
        self.review("future_reuse", memory, accept=False)
        self.assertFalse(self.snapshot()["consents"])
        self.review("future_reuse", memory)
        long = [m for m in self.snapshot()["memories"] if m["scope"] == "long_term"]
        self.assertEqual(len(long), 1)
        self.assertEqual(long[0]["polarity"], "avoid")
        self.assertEqual(long[0]["content"], "허벅지가 조이는 옷을 피하고 싶다")

    def test_reason_failure_retry_preserves_both_evidence_parts_once(self):
        state = self.comparison()
        self.gateway.fail_reason = True
        _, command = self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.")
        self.service.wait_idle()
        snapshot = self.snapshot()
        feedback = next(f for f in snapshot["feedback"] if f["reaction"] == "selected")
        self.assertEqual(len(feedback["evidence_refs"]), 2)
        self.assertEqual(self.state()["operation"], "interpretation_pending")
        self.service.close()
        self.service = self.open_service()
        self.gateway.fail_reason = False
        self.send({"op": "retry_extraction", "feedback_ref": {"type": "feedback", "id": feedback["id"], "version": feedback["version"]}})
        self.service.wait_idle()
        self.assertEqual(len(self.snapshot()["feedback"]), len(snapshot["feedback"]))
        self.assertEqual(len(self.snapshot()["evidence"]), len(snapshot["evidence"]))
        self.assertEqual(sum("허벅지" in m["content"] for m in self.snapshot()["memories"]), 1)
        self.send(None, command=command)
        self.assertEqual(sum("허벅지" in m["content"] for m in self.snapshot()["memories"]), 1)

    def test_invalid_optional_text_does_not_partially_receive_an_image(self):
        state = self.comparison()
        before = self.snapshot()
        for text in (False, [], "", " ", "가" * 4001):
            with self.subTest(text_type=type(text).__name__):
                result, _ = self.answer(state, text=text, ok=False)
                self.assertEqual(result["error"]["code"], "invalid_input")
                self.assertEqual(len(self.snapshot()["evidence"]), len(before["evidence"]))
                self.assertEqual(len(self.snapshot()["feedback"]), len(before["feedback"]))

    def test_joint_feedback_rolls_back_as_one_intake(self):
        state = self.comparison()
        before = self.snapshot()
        def fail(point, info=None):
            if point == "after_action" and info and info.get("op") == "record_comparison":
                raise RuntimeError("synthetic joint-intake rollback")
        self.service._run(setattr, self.service._store, "_failure_hook", fail)
        try:
            result, _ = self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.", ok=False)
            self.assertEqual(result["error"]["code"], "storage_failed")
        finally:
            self.service._run(setattr, self.service._store, "_failure_hook", None)
        self.assertEqual(len(self.snapshot()["feedback"]), len(before["feedback"]))
        self.assertEqual(len(self.snapshot()["evidence"]), len(before["evidence"]))
        self.assertEqual(len(self.snapshot()["memories"]), len(before["memories"]))

    def test_closed_reason_review_cannot_reopen_intake(self):
        state = self.comparison()
        self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.")
        self.service.wait_idle()
        self.send({"op": "end_request"})
        count = len(self.snapshot()["feedback"])
        result, _ = self.send({"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
                               "reaction": "text_only", "selections": [], "text": "새 입력", "question_id": None}, ok=False)
        self.assertEqual(result["error"]["code"], "request_closed")
        self.assertEqual(len(self.snapshot()["feedback"]), count)

    def test_image_scoped_reason_can_be_reviewed_after_end_without_broadening_scope(self):
        self.gateway.reason_slot = True
        state = self.comparison()
        self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.")
        self.service.wait_idle()
        self.send({"op": "end_request"})
        memory = next(m for m in self.state()["memories"] if "허벅지" in m["content"])
        self.assertFalse(memory["reusable"])
        self.review("confirm_content", memory)
        memory = next(m for m in self.state()["memories"] if "허벅지" in m["content"])
        self.assertTrue(memory["confirmed"])
        rejected, _ = self.send({"op": "prepare_review", "purpose": "future_reuse", "subject_refs": [memory["ref"]], "proposed_text": None}, ok=False)
        self.assertEqual(rejected["error"]["code"], "consent_required")
        self.assertFalse(self.snapshot()["consents"])

    def test_closed_image_review_still_rejects_changed_product_evidence(self):
        self.gateway.reason_slot = True
        state = self.comparison()
        self.answer(state, text="오래 앉아 있어요. 허벅지가 조이는 건 싫어요.")
        self.service.wait_idle()
        self.send({"op": "end_request"})
        memory = next(m for m in self.state()["memories"] if "허벅지" in m["content"])
        self.send({"op": "prepare_review", "purpose": "confirm_content", "subject_refs": [memory["ref"]], "proposed_text": None})
        display_ref = self.state()["reviews"][0]["ref"]
        self.records[0]["images"][0]["source_revision"] = "changed-after-end"
        self.data.write_text(json.dumps(self.records))
        self.service.import_catalog(self.data)
        rejected, _ = self.send({"op": "respond_review", "display_ref": display_ref, "decision": "accept"}, ok=False)
        self.assertEqual(rejected["error"]["code"], "stale_context")
        self.assertFalse(next(m for m in self.state()["memories"] if m["ref"]["id"] == memory["ref"]["id"])["confirmed"])
