"""ADR 0013 pure graph logic: parse_turn v2, hypotheses, route, scoring, grid. No langgraph needed."""

import random
import unittest

from stylemate_memory import contracts as c
from stylemate_memory.errors import StyleMateError
from stylemate_memory.graph import grid, intent as it, scoring
from stylemate_memory.graph.hypotheses import build_hypothesis_payload, validate_hypotheses
from stylemate_memory.graph.parse import build_payload, to_v1_extraction, validate_parse_v2
from stylemate_memory.registry import load_registry

REGISTRY = load_registry(c.V1_REGISTRY_VERSION)
TARGETS = [{"target_id": "pants", "garment_type": "Pants"}]
TEXT = "회사 발표 때 입을 편한 슬랙스, 원래 와이드핏 좋아해요"


def payload(text=TEXT):
    sources = [{"source_id": "e001", "kind": "user_text", "content": text,
                "selector": {"garment_type": None, "slot_id": None}}]
    return build_payload(sources, TARGETS, REGISTRY, [])


def situation(**kw):
    return {"id": "s1", "key": "occasion", "value": "발표/미팅", "raw": "회사 발표", "quote": "회사 발표 때",
            "source_ids": ["e001"]} | kw


def wish(**kw):
    return {"key": "w1", "content": "발표 때 편한 슬랙스를 원한다.", "target_id": "pants", "source_ids": ["e001"],
            "quote": "편한 슬랙스", "origin": "explicit", "polarity": "prefer", "strength": "soft",
            "applies": {"mode": "situations", "situation_ids": ["s1"]},
            "pi": [{"feature": "Type", "values": ["Slacks"], "match": "any"}],
            "fea": [{"category": "Functional", "subcategory": "Donning", "tag": "Ease"}], "price": None} | kw


class ParseTurnTests(unittest.TestCase):
    def test_valid_items_and_v1_conversion(self):
        body, registry = payload()
        raw = {"situations": [situation()], "wishes": [wish(), wish(key="w2", content="평소 와이드핏을 좋아한다.",
               quote="원래 와이드핏 좋아해요", applies={"mode": "baseline", "situation_ids": []},
               pi=[{"feature": "Fit", "values": ["Wide"], "match": "any"}], fea=[])],
               "questions": [{"text": "편하다는 건 허리일까요?", "about": {"wish_keys": ["w1"], "situation_ids": []},
                              "reason": "ambiguous_need"}]}
        parsed = validate_parse_v2(raw, body, registry, [])
        self.assertEqual(len(parsed["situations"]), 1)
        self.assertEqual([w["key"] for w in parsed["wishes"]], ["w1", "w2"])
        self.assertEqual(len(parsed["questions"]), 1)
        v1, warnings = to_v1_extraction(parsed, body, registry, [])
        self.assertEqual(warnings, [])
        kinds = [c["kind"] for c in v1["candidates"]]
        self.assertEqual(kinds, ["situation", "preference", "preference"])
        self.assertEqual(v1["candidates"][0]["fact"], {"key": "occasion", "value": "회사 발표"})
        self.assertEqual(v1["candidates"][2]["scope_hint"], "baseline")
        # A single request situation is a fact; the wish keeps no condition.
        self.assertEqual(v1["candidates"][1]["conditions"], {})

    def test_forged_quote_or_authority_claim_rejects_whole_answer(self):
        body, registry = payload()
        with self.assertRaises(StyleMateError):
            validate_parse_v2({"situations": [], "wishes": [wish(quote="말하지 않은 문장")], "questions": []}, body, registry, [])
        with self.assertRaises(StyleMateError):
            validate_parse_v2({"situations": [], "wishes": [wish() | {"confirmed": True}], "questions": []}, body, registry, [])

    def test_faulty_item_is_dropped_alone(self):
        body, registry = payload()
        raw = {"situations": [situation(value="회의실")], "wishes": [wish(applies={"mode": "request", "situation_ids": []}),
               wish(key="w2", pi=[{"feature": "Fit", "values": ["Ultra"], "match": "any"}], fea=[],
                    applies={"mode": "request", "situation_ids": []})], "questions": []}
        parsed = validate_parse_v2(raw, body, registry, [])
        self.assertEqual(parsed["situations"], [])  # value outside the dictionary
        self.assertEqual(len(parsed["wishes"]), 2)
        self.assertEqual(parsed["wishes"][1]["pi"], [])  # only the bad binding is dropped
        self.assertIn("pi_binding_dropped", parsed["warnings"])

    def test_broken_situation_reference_is_held_not_widened(self):
        body, registry = payload()
        parsed = validate_parse_v2({"situations": [], "wishes": [wish(applies={"mode": "situations", "situation_ids": ["s9"]})],
                                    "questions": []}, body, registry, [])
        self.assertEqual(parsed["wishes"], [])
        self.assertEqual(len(parsed["held"]), 1)
        self.assertEqual(parsed["questions"][0]["reason"], "unclear_situation")

    def test_situation_rules_become_conditions(self):
        text = "출근할 땐 슬랙스, 주말 외출엔 청바지"
        body, registry = payload(text)
        raw = {"situations": [situation(raw="출근", quote="출근할 땐", value="출근"),
                              situation(id="s2", raw="주말 외출", quote="주말 외출엔", value="주말 외출")],
               "wishes": [wish(content="출근 때는 슬랙스.", quote="슬랙스", fea=[]),
                          wish(key="w2", content="주말에는 청바지.", quote="청바지", fea=[],
                               applies={"mode": "situations", "situation_ids": ["s2"]},
                               pi=[{"feature": "Type", "values": ["Jeans"], "match": "any"}])], "questions": []}
        parsed = validate_parse_v2(raw, body, registry, [])
        v1, _ = to_v1_extraction(parsed, body, registry, [])
        wishes = [c for c in v1["candidates"] if c["kind"] != "situation"]
        self.assertEqual(wishes[0]["conditions"], {"occasion": "출근"})
        self.assertEqual(wishes[1]["conditions"], {"occasion": "주말 외출"})

    def test_hard_requirement_and_numeric_price(self):
        body, registry = payload("슬랙스 5만원 이하로 꼭")
        parsed = validate_parse_v2({"situations": [], "wishes": [wish(quote="5만원 이하", strength="hard", fea=[],
            applies={"mode": "request", "situation_ids": []}, price={"op": "lte", "min_krw": None, "max_krw": 50000})],
            "questions": []}, body, registry, [])
        intent = it.new_intent("r", TARGETS)
        it.merge_parse(intent, parsed, "t1")
        self.assertEqual([h["kind"] for h in intent["hard"]], ["pi", "price"])


class HypothesisTests(unittest.TestCase):
    def test_recall_first_values_and_drops(self):
        needs = [{"key": "t1-w1", "target_id": "pants", "fea": [{"category": "Functional"}], "quote": "편한", "content": "편한"}]
        body = build_hypothesis_payload(needs, [], TARGETS, REGISTRY, {"pants": ["Type"]},
                                        [{"target_id": "pants", "axis": "Fit", "values": ["Skinny"]}])
        self.assertNotIn("candidates", body)  # no catalog distribution is sent
        raw = {"hypotheses": [
            {"id": "a", "target_id": "pants", "fea_keys": ["t1-w1"], "axis": "Fit", "values": ["Wide", "Skinny", "Nope"], "reason": "여유"},
            {"id": "b", "target_id": "pants", "fea_keys": ["t1-w1"], "axis": "Type", "values": ["Jogger"], "reason": "고정 축"},
            {"id": "c", "target_id": "pants", "fea_keys": ["t1-w1"], "axis": "Detail", "values": ["Banding"], "reason": "밴딩"}]}
        result, warnings = validate_hypotheses(raw, body, REGISTRY)
        self.assertEqual([(h["axis"], h["values"]) for h in result], [("Fit", ["Wide"]), ("Detail", ["Banding"])])
        self.assertIn("hypothesis_dropped", warnings)


def card(cid, fit, color="Black", target="pants"):
    return {"candidate_id": cid, "target_id": target, "product_id": "p-" + cid, "facts": {"Fit": [fit], "Color": [color]}}


def state_with(hypotheses):
    s = it.new_intent("r", TARGETS)
    s["hypotheses"] = hypotheses
    return s


HYP = [{"id": "h1", "target_id": "pants", "axis": "Fit", "values": ["Wide", "Straight"], "reason": "", "fea_keys": ["w"]}]


class ScoringTests(unittest.TestCase):
    def test_contrast_only_updates(self):
        s = state_with(HYP)
        cards = [card("a", "Wide"), card("b", "Slim"), card("c", "Straight")]
        changed = scoring.attribute_grid(s, cards, {"a"}, "request")
        wide = s["scores"][scoring.score_key("pants", "request", "Fit", "Wide")]
        straight = s["scores"][scoring.score_key("pants", "request", "Fit", "Straight")]
        self.assertEqual((wide["a"], wide["b"]), (2.0, 1.0))
        self.assertEqual((straight["a"], straight["b"]), (1.0, 1.3))
        self.assertEqual(len(changed), 2)

    def test_shared_value_all_selected_and_unknown_are_neutral(self):
        s = state_with(HYP)
        both = [card("a", "Wide"), card("b", "Wide")]
        self.assertEqual(scoring.attribute_grid(s, both, {"a"}, "request"), [])
        self.assertEqual(scoring.attribute_grid(s, [card("a", "Wide"), card("b", "Slim")], {"a", "b"}, "request"), [])
        unknown = [card("a", "Wide"), {"candidate_id": "u", "target_id": "pants", "product_id": "pu", "facts": {}}]
        self.assertEqual(scoring.attribute_grid(s, unknown, {"a"}, "request"), [])

    def test_fabric_only_via_reason(self):
        s = state_with([{"id": "h", "target_id": "pants", "axis": "Fabric", "values": ["Linen"], "reason": "", "fea_keys": ["w"]}])
        cards = [{"candidate_id": "a", "target_id": "pants", "product_id": "pa", "facts": {"Fabric": ["Linen"]}},
                 {"candidate_id": "b", "target_id": "pants", "product_id": "pb", "facts": {"Fabric": ["Wool"]}}]
        self.assertEqual(scoring.attribute_grid(s, cards, {"a"}, "request"), [])
        self.assertTrue(scoring.apply_reason_axis(s, cards, {"a"}, "Fabric", "request"))

    def test_dislike_is_product_level_and_miss_streak_excludes(self):
        s = state_with(HYP)
        scoring.apply_dislikes(s, ["p1"], 1)
        scoring.apply_dislikes(s, ["p1"], 1)  # same exposure counts once
        self.assertEqual(s["hidden"], [])
        scoring.apply_dislikes(s, ["p1"], 2)
        self.assertEqual(s["hidden"], ["p1"])
        self.assertEqual(s["scores"], {})  # no value change from "별로"
        for _ in range(3):
            scoring.attribute_grid(s, [card("a", "Wide"), card("b", "Straight")], {"a"}, "request")
        self.assertIn(scoring.score_key("pants", "request", "Fit", "Straight"), s["excluded"])


def product(pid, fit, color="Black", price=40000):
    return {"product_id": pid, "target_id": "pants", "product_map_version": 1, "image_id": "i" + pid, "image_version": 1,
            "facts": {"Fit": [fit], "Color": [color], "Type": ["Slacks"]}, "price": price}


class GridTests(unittest.TestCase):
    def test_eight_cards_with_control_and_exceptions(self):
        products = [product(f"w{i}", "Wide") for i in range(5)] + [product(f"s{i}", "Straight") for i in range(5)] + \
                   [product(f"k{i}", "Skinny") for i in range(3)]
        s = state_with(HYP)
        plan = grid.plan_grid(products, TARGETS, s, "request", 1, "seed")
        self.assertEqual(len(plan["cards"]), 8)
        self.assertEqual(len({c["product_id"] for c in plan["cards"]}), 8)
        self.assertIn("control", {c["slot"] for c in plan["cards"]})
        control = next(c for c in plan["cards"] if c["slot"] == "control")
        self.assertEqual(control["facts"]["Fit"], ["Skinny"])
        few = grid.plan_grid(products[:3], TARGETS, s, "request", 1, "seed")
        self.assertEqual(len(few["cards"]), 3)
        self.assertTrue(few["shortage"])

    def test_hard_price_pins_and_hidden_empty(self):
        products = [product("a", "Wide", price=30000), product("b", "Wide", price=90000)]
        s = state_with(HYP)
        s["hard"] = [{"kind": "price", "target_id": None, "price": {"op": "lte", "min_krw": None, "max_krw": 50000}}]
        self.assertEqual([c["product_id"] for c in grid.plan_grid(products, TARGETS, s, "request", 1, "x")["cards"]], ["a"])
        s["hidden"] = ["a"]
        self.assertEqual(grid.plan_grid(products, TARGETS, s, "request", 1, "x")["status"], "hidden_empty")
        s["hidden"], s["hard"] = [], []
        s["pinned"] = [{"key": scoring.score_key("pants", "request", "Fit", "Straight")}]
        self.assertEqual(grid.plan_grid(products, TARGETS, s, "request", 1, "x")["status"], "no_results")

    def test_convergence_ignores_shortage(self):
        self.assertTrue(grid.converged([["a"], ["a"], ["a"]], False))
        self.assertFalse(grid.converged([["a"], ["a"], ["a"]], True))
        self.assertFalse(grid.converged([["a"], ["b"], ["a"]], False))


class RouteTests(unittest.TestCase):
    def test_route_table(self):
        s = it.new_intent("r", TARGETS)
        self.assertEqual(it.route(s), "retrieve")
        s["hard"] = [{"kind": "pi", "target_id": "pants", "feature": "Type", "values": ["Slacks"], "match": "any", "polarity": "prefer"},
                     {"kind": "pi", "target_id": "pants", "feature": "Type", "values": ["Jeans"], "match": "any", "polarity": "prefer"}]
        self.assertEqual(it.route(s), "ask_clarify")
        s["hard"] = [s["hard"][0], s["hard"][0] | {"polarity": "avoid"}]
        self.assertEqual(it.route(s), "ask_clarify")
        self.assertEqual(it.route(it.new_intent("r", [])), "ask_clarify")

    def test_corrected_situation_starts_new_scope(self):
        s = it.new_intent("r", TARGETS)
        it.merge_parse(s, {"situations": [situation(value="출근", raw="출근")], "wishes": [], "held": [], "questions": [], "warnings": []}, "t1")
        first = it.scope_of(s)
        it.merge_parse(s, {"situations": [situation(id="s2", value="주말 외출", raw="주말")], "wishes": [], "held": [],
                           "questions": [], "warnings": []}, "t2")
        self.assertNotEqual(first, it.scope_of(s))
        self.assertEqual(len(s["situations"]), 1)


if __name__ == "__main__":
    unittest.main()
