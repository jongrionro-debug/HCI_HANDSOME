from copy import deepcopy
from datetime import datetime, timedelta
import json
import unittest

from stylemate_memory import contracts as c
from stylemate_memory.context import build_context, build_context_v1
from stylemate_memory.errors import StyleMateError
from stylemate_memory.inference import RuleAdapter, infer, infer_v1, validate_target_map_basis
from stylemate_memory.model_io import FakeModelGateway
from stylemate_memory.registry import load_registry
from tests.test_context import FakeSemantic, V1Fixture, memory, snapshot


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


class V1InferenceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = V1Fixture()
        self.registry = load_registry(c.V1_REGISTRY_VERSION)

    def context(self, **kwargs):
        return build_context_v1(self.fixture.data, self.fixture.targets, registry=self.registry,
                                char_budget=32000, **kwargs)

    def infer(self, context=None, proposal=None):
        return infer_v1(context or self.context(), FakeModelGateway(proposal), registry=self.registry)

    def pi(self, result, feature, target=0):
        return result["targets"][target]["product_information"][feature]

    def fea_spec(self, tag="Warmth", **kwargs):
        for category, subcategories in self.registry.describe()["consumer_needs_taxonomy"].items():
            for subcategory, tags in subcategories.items():
                if any(entry["attribute"] == tag for entry in tags):
                    return {"domain": "FEA", "category": category, "subcategory": subcategory, "tag": tag,
                            "polarity": "prefer", "strength": "soft", **kwargs}
        self.fail("missing canonical FEA test path")

    def proposal(self, context, spec, *, target="pants-1", alias=None):
        return {"suggestions": [{"target_id": target, "binding": spec,
                                 "source_ids": [alias or context["model_input"]["sources"][0]["source_id"]],
                                 "reason": "공급된 근거의 soft 해석"}], "questions": []}

    def assert_error(self, code, call):
        with self.assertRaises(StyleMateError) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    def combine(self, left, right):
        """A0 context fixture with independently validated, unsuppressed clauses.

        C2 currently withholds conflicting clauses. This exercises C3's own
        conflict/indifference behavior without bypassing any source proof.
        """
        result = deepcopy(left)
        aliases = {alias: "extra-" + alias for alias in right["source_refs"]}
        for source in right["model_input"]["sources"]:
            result["model_input"]["sources"].append({**deepcopy(source), "source_id": aliases[source["source_id"]]})
        result["source_refs"].update({aliases[alias]: deepcopy(refs) for alias, refs in right["source_refs"].items()})
        for constraint in right["constraints"]:
            result["constraints"].append({**deepcopy(constraint), "id": "extra-" + constraint["id"]})
        for constraint in right["model_input"]["constraints"]:
            result["model_input"]["constraints"].append({**deepcopy(constraint), "id": "extra-" + constraint["id"],
                "source_ids": [aliases[alias] for alias in constraint["source_ids"]]})
        for ref in right["basis"]["object_versions"]:
            if ref not in result["basis"]["object_versions"]:
                result["basis"]["object_versions"].append(deepcopy(ref))
        result["context_id"] = "unsuppressed-contract-fixture"
        return result

    def test_current_slim_overrides_only_long_wide_and_new_request_restores_long(self):
        wide = self.fixture.add("usual-fit", "평소 Wide")
        self.fixture.bind(wide, "Wide")
        navy = self.fixture.add("usual-color", "평소 Navy")
        self.fixture.bind(navy, "Navy", feature="Color")
        slim = self.fixture.add("today-fit", "이번에는 Slim", scope="short_term", strength="hard")
        self.fixture.bind(slim, "Slim")
        before = deepcopy(self.fixture.data)
        context = self.context(semantic=FakeSemantic())
        result = self.infer(context)
        self.assertEqual((self.pi(result, "Color")["values"], self.pi(result, "Fit")["values"]), (["Navy"], ["Slim"]))
        self.assertEqual(self.pi(result, "Fit")["status"], "specified")
        fit_refs = self.pi(result, "Fit")["source_refs"]
        self.assertTrue({"usual-fit", "today-fit"} <= {ref["id"] for ref in fit_refs})
        self.assertEqual(result["basis"], context["basis"])
        self.assertIsNot(result["basis"], context["basis"])
        self.assertEqual(self.fixture.data, before)
        self.fixture.data["request"]["id"] = "new-private-request"
        self.fixture.data["request"]["revision"] = 1
        renewed = self.infer()
        self.assertEqual((self.pi(renewed, "Color")["values"], self.pi(renewed, "Fit")["values"]), (["Navy"], ["Wide"]))
        self.assertNotIn("today-fit", {ref["id"] for ref in renewed["basis"]["object_versions"]})
        self.assertEqual(wide["status"], "active")

    def test_vintage_leaves_all_37_values_null_with_exact_contract_shape(self):
        self.fixture.add("vintage", "빈티지한 느낌")
        result = self.infer()
        self.assertEqual(set(result), c.TargetMap.__required_keys__)
        target = result["targets"][0]
        self.assertEqual(set(target), c.Target.__required_keys__)
        self.assertEqual(set(target["product_information"]), set(self.registry.describe()["product_information"]))
        self.assertEqual(self.pi(result, "Brand")["status"], "unsupported")
        for feature, value in target["product_information"].items():
            self.assertIsNone(value["values"])
            self.registry.validate_target_value({"domain": "PI", "feature": feature}, value, "Pants")
        count = 0
        for category, subcategories in target["consumer_needs"].items():
            for subcategory, tags in subcategories.items():
                for tag, value in tags.items():
                    count += 1
                    self.assertIsNone(value["preference"])
                    self.registry.validate_target_value({"domain": "FEA", "category": category,
                        "subcategory": subcategory, "tag": tag}, value, "Pants")
        self.assertEqual(count, 30)
        self.assertEqual(result["constraints"], [])

    def test_vague_style_cannot_fill_physical_color_or_fabric(self):
        self.fixture.add("vintage", "빈티지한 느낌")
        context = self.context()
        for feature, value in (("Color", "Navy"), ("Fabric", "Wool"), ("Fit", "Wide")):
            with self.subTest(feature=feature):
                spec = {"domain": "PI", "feature": feature, "values": [value], "match": "any",
                        "polarity": "prefer", "strength": "soft"}
                self.assert_error("invalid_output", lambda: self.infer(context, self.proposal(context, spec)))

    def test_content_confirmation_keeps_mapping_inferred_until_binding_confirmation(self):
        m = self.fixture.add("unmapped", "빈티지한 느낌")
        binding = self.fixture.bind(m, "Brown", feature="Color", confirmed=False, origin="inferred")
        context = self.context()
        spec = {key: binding[key] for key in c.PIBindingSpec.__required_keys__}
        result = self.infer(context, self.proposal(context, spec))
        self.assertEqual(self.pi(result, "Color")["status"], "inferred")
        self.assertEqual(self.pi(result, "Color")["values"], ["Brown"])
        self.assertFalse(result["constraints"][0]["confirmed"])
        self.assertIsNone(result["constraints"][0]["binding_ref"])
        self.assertEqual(result["constraints"][0]["binding"]["strength"], "soft")
        self.assertEqual(self.pi(self.infer(context), "Color")["status"], "unspecified")
        self.fixture = V1Fixture()
        m = self.fixture.add("confirmed", "Brown")
        self.fixture.bind(m, "Brown", feature="Color", origin="inferred")
        result = self.infer()
        self.assertEqual(self.pi(result, "Color")["status"], "specified")
        self.assertEqual(result["constraints"][0]["origin"], "inferred")

    def test_avoid_only_never_becomes_positive_and_model_cannot_erase_hard(self):
        m = self.fixture.add("avoid", "Black 피함", scope="short_term", polarity="avoid", strength="hard")
        self.fixture.bind(m, "Black", feature="Color")
        context = self.context()
        result = self.infer(context)
        self.assertIsNone(self.pi(result, "Color")["values"])
        self.assertEqual(self.pi(result, "Color")["status"], "unspecified")
        self.assertEqual(result["constraints"], context["constraints"])
        spec = {"domain": "PI", "feature": "Color", "values": ["Black"], "match": "any",
                "polarity": "prefer", "strength": "soft"}
        self.assert_error("invalid_output", lambda: self.infer(context, self.proposal(context, spec)))

    def test_indifferent_retains_hard_require_and_hard_avoid_clauses(self):
        for polarity in ("require", "avoid"):
            with self.subTest(polarity=polarity):
                self.fixture = V1Fixture()
                hard = self.fixture.add("hard", "Slim 조건", strength="hard", polarity=polarity)
                self.fixture.bind(hard, "Slim")
                hard_context = self.context()
                self.fixture = V1Fixture()
                indifferent = self.fixture.add("indifferent", "핏은 상관없음", scope="short_term", polarity="indifferent")
                self.fixture.bind(indifferent, spec={"domain": "PI", "feature": "Fit", "values": None, "match": None,
                    "polarity": "indifferent", "strength": "soft"})
                combined = self.combine(hard_context, self.context())
                result = self.infer(combined)
                self.assertEqual(result["constraints"], combined["constraints"])
                self.assertEqual(self.pi(result, "Fit")["values"], ["Slim"] if polarity == "require" else None)
                self.assertEqual(self.pi(result, "Fit")["status"], "specified" if polarity == "require" else "indifferent")
                self.assertEqual(result["constraints"][0]["binding"]["strength"], "hard")

    def test_any_all_are_independent_executable_clauses_and_not_a_flat_operator(self):
        m = self.fixture.add("cotton", "Cotton Polyester 혼방")
        self.fixture.bind(m, spec={"domain": "PI", "feature": "Fabric", "values": ["Cotton"], "match": "any",
            "polarity": "prefer", "strength": "soft"})
        self.fixture.bind(m, spec={"domain": "PI", "feature": "Fabric", "values": ["Cotton", "Polyester"], "match": "all",
            "polarity": "prefer", "strength": "soft"})
        result = self.infer()
        self.assertEqual([(x["binding"]["values"], x["binding"]["match"]) for x in result["constraints"]],
                         [(["Cotton"], "any"), (["Cotton", "Polyester"], "all")])
        self.assertEqual(len(self.pi(result, "Fabric")["constraint_ids"]), 2)
        self.assertNotIn("match", self.pi(result, "Fabric"))

    def test_explicit_indifference_is_null_and_cannot_hide_a_long_hard_condition(self):
        m = self.fixture.add("indifferent", "핏은 상관없음", scope="short_term", polarity="indifferent")
        self.fixture.bind(m, spec={"domain": "PI", "feature": "Fit", "values": None, "match": None,
                                  "polarity": "indifferent", "strength": "soft"})
        result = self.infer()
        self.assertEqual(self.pi(result, "Fit")["status"], "indifferent")
        self.assertIsNone(self.pi(result, "Fit")["values"])
        hard = self.fixture.add("long-hard", "Slim 필수", strength="hard", polarity="require")
        self.fixture.bind(hard, "Slim")
        # A corrected C2 may retain the hard clause. Until then C3 must defer;
        # neither behavior may produce an apparently unconstrained target.
        try:
            result = self.infer()
        except StyleMateError as error:
            self.assertEqual(error.code, "context_blocked")
        else:
            self.assertTrue(any(clause["binding"]["strength"] == "hard" for clause in result["constraints"]))

    def test_same_priority_conflict_has_null_values_proofs_and_question(self):
        left = self.fixture.add("left", "Slim", scope="short_term")
        self.fixture.bind(left, "Slim")
        first = self.context()
        self.fixture = V1Fixture()
        right = self.fixture.add("right", "Wide", scope="short_term")
        self.fixture.bind(right, "Wide")
        result = self.infer(self.combine(first, self.context()))
        self.assertEqual(self.pi(result, "Fit")["status"], "conflict")
        self.assertIsNone(self.pi(result, "Fit")["values"])
        self.assertEqual(len(self.pi(result, "Fit")["constraint_ids"]), 2)
        self.assertTrue({"left", "right"} <= {ref["id"] for ref in self.pi(result, "Fit")["source_refs"]})
        self.assertTrue(any("same_priority_conflict" in q and "PI/Fit" in q for q in result["questions"]))

    def test_fea_is_a_user_need_with_soft_inference_or_separate_confirmed_binding(self):
        self.fixture.add("need", "따뜻한 옷이 좋아요")
        context = self.context()
        spec = self.fea_spec()
        result = self.infer(context, self.proposal(context, spec))
        value = result["targets"][0]["consumer_needs"][spec["category"]][spec["subcategory"]][spec["tag"]]
        self.assertEqual((value["status"], value["preference"]), ("inferred", "prefer"))
        self.assertEqual(result["constraints"][0]["binding"]["strength"], "soft")
        self.assertNotIn("present", value)
        self.fixture = V1Fixture()
        m = self.fixture.add("warmth", "따뜻해야 함", scope="short_term", strength="hard", polarity="require")
        self.fixture.bind(m, spec=self.fea_spec(polarity="require", strength="hard"))
        result = self.infer()
        value = result["targets"][0]["consumer_needs"][spec["category"]][spec["subcategory"]][spec["tag"]]
        self.assertEqual((value["status"], value["preference"]), ("specified", "require"))

    def test_targets_and_unconfirmed_condition_facts_cannot_leak_into_goals(self):
        self.fixture = V1Fixture([{"target_id": "pants-1", "garment_type": "Pants"},
                                  {"target_id": "pants-2", "garment_type": "Pants"}])
        self.fixture.add("one", "따뜻한 느낌", scope="short_term",
                         selector={"garment_type": "Pants", "slot_id": "pants-1"})
        self.fixture.add("unconfirmed-fact", "발표인 듯함", scope="short_term", confirmed=False, origin="inferred",
                         fact={"key": "occasion", "value": "발표"})
        conditional = self.fixture.add("conditional", "Slim", conditions={"occasion": "발표"})
        self.fixture.bind(conditional, "Slim")
        context = self.context()
        result = self.infer(context)
        self.assertTrue(all(self.pi(result, "Fit", index)["values"] is None for index in (0, 1)))
        self.assertNotIn("conditional", {ref["id"] for ref in result["basis"]["object_versions"]})
        self.assert_error("invalid_output", lambda: self.infer(context, self.proposal(context, self.fea_spec(), target="pants-2")))
        alias = next(alias for alias in context["source_refs"] if alias not in {s["source_id"] for s in context["model_input"]["sources"]})
        self.assert_error("invalid_output", lambda: self.infer(context, self.proposal(context, self.fea_spec(), alias=alias)))

    def test_matched_condition_proofs_and_scope_are_retained(self):
        fact = self.fixture.add("occasion", "발표", scope="short_term", fact={"key": "occasion", "value": "발표"})
        m = self.fixture.add("conditional", "Slim", conditions={"occasion": "발표"})
        self.fixture.bind(m, "Slim")
        result = self.infer()
        self.assertEqual(result["constraints"][0]["conditions"], {"occasion": "발표"})
        self.assertIn(V1Fixture.ref("memory", fact), result["constraints"][0]["source_refs"])

    def test_model_authority_unknown_keys_sources_values_and_scope_are_rejected(self):
        self.fixture.add("one", "따뜻한 느낌")
        context = self.context()
        valid = self.proposal(context, self.fea_spec())
        invalid = []
        for field, value in (("confirmed", True), ("consent", True), ("status", "specified"), ("commands", [])):
            raw = deepcopy(valid)
            raw["suggestions"][0][field] = value
            invalid.append(raw)
        raw = deepcopy(valid)
        raw["actions"] = [{"op": "create_long_term"}]
        invalid.append(raw)
        for changes in ({"strength": "hard"}, {"polarity": "indifferent"}, {"tag": "invented"}, {"confirmed": True}):
            raw = deepcopy(valid)
            raw["suggestions"][0]["binding"].update(changes)
            invalid.append(raw)
        for changes in ({"source_ids": ["absent"]}, {"target_id": "absent"}):
            raw = deepcopy(valid)
            raw["suggestions"][0].update(changes)
            invalid.append(raw)
        for raw in invalid:
            with self.subTest(raw=raw):
                self.assert_error("invalid_output", lambda: self.infer(context, raw))

    def test_invalid_internal_source_or_projection_is_rejected_before_adapter(self):
        m = self.fixture.add("hard", "Slim", strength="hard")
        self.fixture.bind(m, "Slim")
        context = self.context()
        invalid = []
        for kind in ("memory", "evidence", "binding", "confirmation"):
            changed = deepcopy(context)
            ref = next(ref for ref in changed["basis"]["object_versions"] if ref["type"] == kind)
            changed["basis"]["object_versions"].remove(ref)
            invalid.append(changed)
        changed = deepcopy(context)
        changed["model_input"]["constraints"] = []
        invalid.append(changed)
        changed = deepcopy(context)
        changed["constraints"][0]["source_refs"][0]["version"] += 1
        invalid.append(changed)
        class NeverAdapter:
            def propose(self, inputs):
                raise AssertionError("invalid context reached model")
        for changed in invalid:
            with self.subTest(context=changed):
                self.assert_error("invalid_input", lambda: infer_v1(changed, NeverAdapter(), registry=self.registry))

    def test_blocked_or_unavailable_context_does_not_call_adapter(self):
        m = self.fixture.add("left", "Slim", scope="short_term")
        self.fixture.bind(m, "Slim")
        other = self.fixture.add("right", "Wide", scope="short_term")
        self.fixture.bind(other, "Wide")
        class NeverAdapter:
            def propose(self, inputs):
                raise AssertionError("blocked context reached model")
        self.assert_error("context_blocked", lambda: infer_v1(self.context(), NeverAdapter(), registry=self.registry))
        self.fixture = V1Fixture()
        self.assert_error("context_blocked", lambda: infer_v1(self.context(), NeverAdapter(), registry=self.registry))

    def test_model_receives_only_minimal_input_and_cannot_mutate_internal_basis(self):
        self.fixture.add("private-memory", "빈티지")
        context = self.context()
        before = deepcopy(context)
        class MutatingAdapter:
            def propose(inner, inputs):
                self.assertEqual(set(inputs), c.ProposalInput.__required_keys__)
                encoded = json.dumps(inputs, ensure_ascii=False)
                for forbidden in ("private-user", "private-request", "private-memory", "object_versions", "future_reuse"):
                    self.assertNotIn(forbidden, encoded)
                inputs["sources"].clear()
                return {"suggestions": [], "questions": []}
        result = infer_v1(context, MutatingAdapter(), registry=self.registry)
        self.assertEqual(context, before)
        self.assertEqual(result["basis"], before["basis"])

    def test_unsupported_garment_is_not_misrepresented_as_not_applicable(self):
        self.fixture = V1Fixture([{"target_id": "skirt-1", "garment_type": "Skirt"}])
        self.fixture.add("skirt", "빈티지한 느낌", selector={"garment_type": "Skirt", "slot_id": None})
        result = self.infer()
        target = result["targets"][0]
        self.assertEqual(target["garment_type"], "Skirt")
        values = list(target["product_information"].values()) + [value
            for subcategories in target["consumer_needs"].values() for tags in subcategories.values() for value in tags.values()]
        self.assertEqual(len(values), 37)
        self.assertEqual({value["status"] for value in values}, {"unsupported"})

    def test_stale_helper_rechecks_every_basis_component_context_and_deadline(self):
        m = self.fixture.add("one", "Slim")
        self.fixture.bind(m)
        context = self.context(semantic=FakeSemantic())
        result = self.infer(context)
        now = datetime.fromisoformat(self.fixture.data["now"])
        validate_target_map_basis(result, context, registry=self.registry, now=now)
        for key, value in (("request_id", "another"), ("request_revision", 99), ("profile_revision", 99),
                           ("registry_version", "other"), ("index_version", "stale-index"),
                           ("catalog", {"catalog_version": 2, "products": [], "images": []})):
            changed = deepcopy(context)
            changed["basis"][key] = value
            with self.subTest(key=key):
                self.assert_error("stale_context", lambda: validate_target_map_basis(result, changed, registry=self.registry, now=now))
        changed = deepcopy(context)
        changed["context_id"] = "changed-context"
        self.assert_error("stale_context", lambda: validate_target_map_basis(result, changed, registry=self.registry, now=now))
        changed = deepcopy(context)
        changed["basis"]["object_versions"][0]["version"] += 1
        self.assert_error("stale_context", lambda: validate_target_map_basis(result, changed, registry=self.registry, now=now))
        deadline = datetime.fromisoformat(result["basis"]["valid_until"])
        validate_target_map_basis(result, context, registry=self.registry, now=deadline - timedelta(microseconds=1))
        self.assert_error("stale_context", lambda: validate_target_map_basis(result, context, registry=self.registry, now=deadline))


if __name__ == "__main__":
    unittest.main()
