import unittest

from stylemate_memory.context import build_context
from stylemate_memory.errors import StyleMateError
from stylemate_memory.inference import RuleAdapter, infer
from tests.test_context import memory, snapshot


class OmitDirectAdapter:
    VERSION = "test-omit-v1"

    def propose(self, context):
        return {"suggestions": [], "questions": []}


class FakeAdapter:
    def __init__(self, proposal):
        self.proposal = proposal

    def propose(self, context):
        return self.proposal


class InferenceTests(unittest.TestCase):
    def context(self, memories=None):
        return build_context(snapshot(memories or []), [{"id": "pants-1", "garment_type": "Pants"}])

    def test_direct_binding_is_restored_when_model_omits_it(self):
        current = memory("m-fit", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"})
        profile = infer(self.context([current]), OmitDirectAdapter())
        fit = profile["targets"][0]["features"]["fit"]
        self.assertEqual(fit["status"], "specified")
        self.assertEqual(fit["values"], ["Slim"])
        self.assertEqual(profile["suggestions"][0]["source_ids"], ["m-fit"])
        self.assertEqual(profile["targets"][0]["features"]["garment_type"]["values"], ["Pants"])

    def test_model_suggestion_is_checked_and_unresolved_attributes_stay_unspecified(self):
        source = memory("m-goal", request_id="r1", scope="short_term", feature="style", values=["Classic"], selector={"garment_type": "Pants"})
        context = self.context([source])
        profile = infer(context, FakeAdapter({"suggestions": [{
            "target_id": "pants-1", "feature": "formality", "values": [3], "match": "any", "source_ids": ["m-goal"], "reason": "단정한 쇼핑 목표",
        }], "questions": []}))
        self.assertEqual(profile["targets"][0]["features"]["formality"]["status"], "inferred")
        self.assertEqual(profile["targets"][0]["features"]["color"]["status"], "unspecified")
        self.assertEqual(set(profile["suggestions"][0]), {"target_id", "feature", "values", "match", "source_ids", "reason"})

    def test_invalid_model_keys_values_and_source_are_rejected(self):
        context = self.context([memory("source", request_id="r1", scope="short_term", feature="style", values=["Classic"], selector={"garment_type": "Pants"})])
        invalids = [
            {"suggestions": [{"target_id": "pants-1", "feature": "fit", "values": ["Slim"], "match": "any", "source_ids": ["source"], "reason": "ok", "strength": "hard"}], "questions": []},
            {"suggestions": [{"target_id": "pants-1", "feature": "fit", "values": ["Unknown"], "match": "any", "source_ids": ["source"], "reason": "ok"}], "questions": []},
            {"suggestions": [{"target_id": "pants-1", "feature": "fit", "values": ["Slim"], "match": "any", "source_ids": ["not-current"], "reason": "ok"}], "questions": []},
        ]
        for proposal in invalids:
            with self.subTest(proposal=proposal):
                with self.assertRaises(StyleMateError):
                    infer(context, FakeAdapter(proposal))

    def test_avoid_and_hard_constraints_cannot_be_overridden(self):
        avoid = memory("avoid-black", request_id="r1", scope="short_term", feature="color", values=["Black"], polarity="avoid", strength="hard", selector={"garment_type": "Pants"})
        context = self.context([avoid])
        proposal = {"suggestions": [{"target_id": "pants-1", "feature": "color", "values": ["Black"], "match": "any", "source_ids": ["avoid-black"], "reason": "bad"}], "questions": []}
        with self.assertRaises(StyleMateError):
            infer(context, FakeAdapter(proposal))

    def test_model_cannot_reuse_other_target_memory_or_fill_conflict(self):
        source = memory("shirt-color", request_id="r1", scope="short_term", feature="color", values=["White"], selector={"garment_type": "Shirt"})
        context = build_context(snapshot([source]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}])
        wrong_target = {"suggestions": [{"target_id": "pants-1", "feature": "color", "values": ["White"], "match": "any", "source_ids": ["shirt-color"], "reason": "wrong target"}], "questions": []}
        with self.assertRaises(StyleMateError):
            infer(context, FakeAdapter(wrong_target))

        left = memory("left", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"})
        right = memory("right", request_id="r1", scope="short_term", feature="fit", values=["Relaxed"], selector={"garment_type": "Pants"})
        conflict = build_context(snapshot([left, right]), [{"id": "pants-1", "garment_type": "Pants"}])
        filling = {"suggestions": [{"target_id": "pants-1", "feature": "fit", "values": ["Slim"], "match": "any", "source_ids": ["left"], "reason": "fill"}], "questions": []}
        with self.assertRaises(StyleMateError):
            infer(conflict, FakeAdapter(filling))

    def test_not_applicable_and_rule_adapter_are_safe(self):
        context = build_context(snapshot([]), [{"id": "pants-1", "garment_type": "Pants"}])
        profile = infer(context, RuleAdapter())
        self.assertEqual(profile["targets"][0]["features"]["neckline"]["status"], "not_applicable")
        self.assertEqual(profile["targets"][0]["features"]["fit"]["status"], "unspecified")
        self.assertEqual(profile["inference"]["adapter"], "RuleAdapter")

    def test_rule_adapter_uses_goal_fact_reference(self):
        goal = memory("goal-memory", request_id="r1", scope="short_term", feature="goal", values=["business casual"], selector={})
        context = self.context([goal])
        proposal = RuleAdapter().propose(context)
        self.assertTrue(proposal["suggestions"])
        self.assertEqual(proposal["suggestions"][0]["source_ids"], ["goal-memory"])

        external = build_context(snapshot([]), [{"id": "pants-1", "garment_type": "Pants"}], facts={"goal": "business casual"})
        proposal = RuleAdapter().propose(external)
        self.assertEqual(proposal["suggestions"][0]["source_ids"], ["fact:goal"])

        scoped = memory("pants-goal", request_id="r1", scope="short_term", feature="goal", values=["business casual"], selector={"slot_id": "pants-1"})
        scoped_context = build_context(snapshot([scoped]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}])
        scoped_suggestions = RuleAdapter().propose(scoped_context)["suggestions"]
        self.assertEqual({suggestion["target_id"] for suggestion in scoped_suggestions}, {"pants-1"})

        shirt_goal = memory("shirt-goal", request_id="r1", scope="short_term", feature="goal", values=["formal"], selector={"slot_id": "shirt-1"})
        per_target = build_context(snapshot([scoped, shirt_goal]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}])
        per_target_suggestions = RuleAdapter().propose(per_target)["suggestions"]
        self.assertEqual({(item["target_id"], item["source_ids"][0]) for item in per_target_suggestions}, {("pants-1", "pants-goal"), ("shirt-1", "shirt-goal")})

        avoid_text = build_context(snapshot([]), [{"id": "pants-1", "garment_type": "Pants"}], facts={"goal": "not formal"})
        self.assertEqual(RuleAdapter().propose(avoid_text)["suggestions"], [])

        conflict = build_context(
            snapshot([
                memory("business", request_id="r1", scope="short_term", feature="goal", values=["business casual"], selector={"garment_type": "Pants"}),
                memory("formal", request_id="r1", scope="short_term", feature="goal", values=["formal"], selector={"garment_type": "Pants"}),
            ]),
            [{"id": "pants-1", "garment_type": "Pants"}],
        )
        self.assertEqual(RuleAdapter().propose(conflict)["suggestions"], [])

    def test_multiple_direct_style_values_survive_profile_projection(self):
        classic = memory("classic", request_id="r1", scope="short_term", feature="style", values=["Classic"], selector={"garment_type": "Pants"})
        minimal = memory("minimal", request_id="r1", scope="short_term", feature="style", values=["Minimal"], selector={"garment_type": "Pants"})
        profile = infer(self.context([classic, minimal]), OmitDirectAdapter())
        style = profile["targets"][0]["features"]["style"]
        self.assertEqual(style["values"], ["Classic", "Minimal"])
        self.assertEqual({item["source_ids"][0] for item in style["suggestions"]}, {"classic", "minimal"})

    def test_mixed_multi_style_match_is_preserved_as_constraints_not_flattened(self):
        classic = memory("classic", request_id="r1", scope="short_term", feature="style", values=["Classic"], selector={"garment_type": "Pants"}, match="any")
        minimal = memory("minimal", request_id="r1", scope="short_term", feature="style", values=["Minimal"], selector={"garment_type": "Pants"}, match="all")
        profile = infer(self.context([classic, minimal]), OmitDirectAdapter())
        style = profile["targets"][0]["features"]["style"]
        self.assertIsNone(style.get("match"))
        self.assertEqual([(item["values"], item["match"]) for item in style["constraints"]], [(["Classic"], "any"), (["Minimal"], "all")])

    def test_model_same_scalar_feature_conflict_is_rejected(self):
        source = memory("source", request_id="r1", scope="short_term", feature="style", values=["Classic"], selector={"garment_type": "Pants"})
        context = self.context([source])
        proposal = {
            "suggestions": [
                {"target_id": "pants-1", "feature": "formality", "values": [3], "match": "any", "source_ids": ["source"], "reason": "a"},
                {"target_id": "pants-1", "feature": "formality", "values": [4], "match": "any", "source_ids": ["source"], "reason": "b"},
            ],
            "questions": [],
        }
        with self.assertRaises(StyleMateError) as raised:
            infer(context, FakeAdapter(proposal))
        self.assertEqual(raised.exception.code, "model_conflict")

    def test_range_current_exception_replaces_long_range_and_match_cannot_change(self):
        base = memory("base-range", feature="formality", values=[1, 2], match="range", selector={"garment_type": "Pants"})
        current = memory("current-range", request_id="r1", scope="short_term", feature="formality", values=[3, 4], match="range", selector={"garment_type": "Pants"})
        context = self.context([base, current])
        self.assertEqual(context["bindings"][0]["values"], [3, 4])
        self.assertEqual(context["bindings"][0]["match"], "range")
        proposal = {"suggestions": [{"target_id": "pants-1", "feature": "formality", "values": [3, 4], "match": "any", "source_ids": ["current-range"], "reason": "rewrite"}], "questions": []}
        with self.assertRaises(StyleMateError) as raised:
            infer(context, FakeAdapter(proposal))
        self.assertEqual(raised.exception.code, "model_constraint_violation")

    def test_long_hard_or_avoid_is_overridden_only_when_current_explicit_conflicts(self):
        base_fit = memory("base-fit", feature="fit", values=["Relaxed"], strength="hard", selector={"garment_type": "Pants"})
        today_fit = memory("today-fit", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"})
        fit_context = self.context([base_fit, today_fit])
        self.assertEqual(fit_context["bindings"][0]["values"], ["Slim"])
        self.assertIn({"source_id": "base-fit", "reason": "short_term_override"}, fit_context["overridden"])

        base_avoid = memory("base-avoid", feature="color", values=["Black"], polarity="avoid", strength="hard", selector={"garment_type": "Pants"})
        today_color = memory("today-color", request_id="r1", scope="short_term", feature="color", values=["Navy"], selector={"garment_type": "Pants"})
        color_context = self.context([base_avoid, today_color])
        self.assertEqual({(binding["polarity"], binding["values"][0]) for binding in color_context["bindings"]}, {("avoid", "Black"), ("prefer", "Navy")})

    def test_blocked_context_skips_adapter_and_marks_questions(self):
        hard = memory("hard", request_id="r1", scope="short_term", feature="fit", values=["Slim"], strength="hard", selector={"garment_type": "Pants"}, conditions={"goal": "x" * 1000})
        context = build_context(snapshot([hard]), [{"id": "pants-1", "garment_type": "Pants"}], facts={"goal": "x" * 1000}, char_budget=1200)
        with self.assertRaises(StyleMateError) as raised:
            infer(context, OmitDirectAdapter())
        self.assertEqual(raised.exception.code, "context_blocked")


if __name__ == "__main__":
    unittest.main()
