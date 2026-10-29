"""A0 shape/fingerprint examples, not a claim that v1 policies are implemented."""
import copy
import unittest

from stylemate_memory.contracts import CONTRACT_VERSION, MemoryItem, batch_fingerprint, validate_ref
from stylemate_memory.errors import StyleMateError


class ContractTests(unittest.TestCase):
    def test_legacy_metadata_is_optional_for_new_v1_memories(self):
        self.assertIn("legacy", MemoryItem.__optional_keys__)
        self.assertNotIn("legacy", MemoryItem.__required_keys__)

    def feedback(self):
        return [{
            "op": "submit_feedback", "round_id": None, "candidate_set_id": None,
            "reaction": "text_only", "selections": [], "text": "빈티지한 느낌",
            "question_id": None,
        }]

    def assert_code(self, code, function, *args):
        with self.assertRaises(StyleMateError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)

    def test_reference_requires_real_positive_int_and_closed_fields(self):
        ref = {"type": "memory", "id": "mem-1", "version": 1}
        self.assertEqual(validate_ref(ref), ref)
        for bad in [True, False, 0, -1, 1.0, "1", None]:
            with self.subTest(version=bad):
                self.assert_code("invalid_input", validate_ref, {**ref, "version": bad})
        for bad in [{**ref, "user_id": "u1"}, {**ref, "id": ""},
                    {**ref, "type": "product"}, {**ref, "type": []}, None]:
            self.assert_code("invalid_input", validate_ref, bad)

    def test_canonical_retry_ignores_object_key_order(self):
        actions = self.feedback()
        reordered = [dict(reversed(list(actions[0].items())))]
        self.assertEqual(
            batch_fingerprint(CONTRACT_VERSION, "req-1", actions),
            batch_fingerprint(CONTRACT_VERSION, "req-1", reordered),
        )

    def test_request_action_content_and_order_change_identity(self):
        original = self.feedback()
        first = batch_fingerprint(CONTRACT_VERSION, "req-1", original)
        changed = copy.deepcopy(original)
        changed[0]["text"] = "네이비 바지"
        self.assertNotEqual(first, batch_fingerprint(CONTRACT_VERSION, "req-1", changed))
        self.assertNotEqual(first, batch_fingerprint(CONTRACT_VERSION, "req-2", original))
        end = {"op": "end_request"}
        self.assertNotEqual(
            batch_fingerprint(CONTRACT_VERSION, "req-1", original + [end]),
            batch_fingerprint(CONTRACT_VERSION, "req-1", [end] + original),
        )  # shape hash only; store separately rejects illegal action combinations

    def test_unsupported_contract_and_non_json_inputs_fail(self):
        self.assert_code("unsupported_contract", batch_fingerprint, "consumer-17-v1", "req-1", self.feedback())
        for request, actions in [("", self.feedback()), ("req-1", []), ("req-1", [None]),
                                 ("req-1", [{}] * 33), ("req-1", [{"x": float("nan")}]),
                                 ("req-1", [{"x": (1, 2)}]), ("req-1", [{1: "x"}]),
                                 ("req-1", [{"x": "\ud800"}])]:
            self.assert_code("invalid_input", batch_fingerprint, CONTRACT_VERSION, request, actions)

    def test_size_limit_measures_utf8_and_does_not_truncate(self):
        actions = [{"op": "create", "content": "가" * 90000}]
        self.assert_code("invalid_input", batch_fingerprint, CONTRACT_VERSION, "req-1", actions)
        self.assertEqual(len(actions[0]["content"]), 90000)


if __name__ == "__main__":
    unittest.main()
