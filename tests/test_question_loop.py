"""Question loop seam (graph/questions.py): candidates, mode choice, answer validation and reflection. No langgraph."""

import unittest

from stylemate_memory.graph import questions as q
from stylemate_memory.graph.intent import new_intent


def product(pid, **facts):
    return {"product_id": pid, "target_id": "t", "facts": {k: [v] for k, v in facts.items()}}


POOL = [product("a", Color="Navy", Fit="Slim", Brand="X"), product("b", Color="Black", Fit="Slim", Brand="Y"),
        product("c", Color="Navy", Fit="Slim", Brand="Z")]
LABELS = {"Color": "색상", "Fit": "핏(여유)"}


class QuestionLoopTests(unittest.TestCase):
    def intent(self):
        intent = new_intent("r1", [{"target_id": "t", "garment_type": "Top"}])
        intent["turn"] = 1
        return intent

    def test_candidates_skip_brand_single_value_fixed_and_asked_axes(self):
        intent = self.intent()
        self.assertEqual([c["axis"] for c in q.candidates(intent, {"t": POOL}, {})], ["Color"])
        self.assertEqual(q.candidates(intent, {"t": POOL}, {"t": ["Color"]}), [])
        intent["asked"] = [{"target_id": "t", "axis": "Color", "turn": 0}]
        self.assertEqual(q.candidates(intent, {"t": POOL}, {}), [])

    def test_plan_falls_back_to_text_options_and_logs_the_decision(self):
        intent = self.intent()
        question = q.plan(intent, {"t": POOL}, {}, LABELS)
        self.assertEqual((question["mode"], question["axis"]), ("text_options", "Color"))
        self.assertEqual([o["value"] for o in question["options"]], ["Navy", "Black"])
        self.assertEqual(intent["question_log"][-1]["decision"]["decided_by"], "rule")
        intent["ask"] = question
        self.assertIsNone(q.plan(intent, {"t": POOL}, {}, LABELS))  # one open question at a time
        intent["ask"] = None
        self.assertIsNone(q.plan(intent, {"t": POOL}, {}, LABELS))  # ASK_GAP turns between questions

    def test_answer_validation_and_text_option_pins_the_value(self):
        intent = self.intent()
        question = q.plan(intent, {"t": POOL}, {}, LABELS)
        answer = {"question_id": question["question_id"], "choice": "options", "option_ids": ["o1"], "switch_to": None}
        self.assertFalse(q.valid_answer(question, answer | {"option_ids": ["o9"]}))
        self.assertFalse(q.valid_answer(question, answer | {"option_ids": ["o0", "o1"]}))  # single choice
        self.assertFalse(q.valid_answer(question, answer | {"choice": "switch", "option_ids": [], "switch_to": "contrast_pair"}))
        self.assertTrue(q.valid_answer(question, answer))
        changed = q.interpret(intent, question, answer, "request")
        self.assertEqual(changed, ["t|request|Color|Black"])
        self.assertEqual(intent["pinned"], [{"key": "t|request|Color|Black"}])
        unsure = {"question_id": question["question_id"], "choice": "unsure", "option_ids": [], "switch_to": None}
        self.assertEqual(q.interpret(intent, question, unsure, "request"), [])
        self.assertEqual(intent["question_log"][-1]["choice"], "unsure")

    def test_public_view_hides_stored_values(self):
        question = q.plan(self.intent(), {"t": POOL}, {}, LABELS)
        self.assertNotIn("value", q.public(question)["options"][0])


if __name__ == "__main__":
    unittest.main()
