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

    def test_unique_fea_tag_under_wrong_subcategory_is_moved_unknown_tag_dropped(self):
        body, registry = payload()
        raw = {"situations": [], "wishes": [
            wish(fea=[{"category": "Functional", "subcategory": "Comfort", "tag": "Ease"}],
                 applies={"mode": "request", "situation_ids": []}),
            wish(key="w2", fea=[{"category": "Functional", "subcategory": "Comfort", "tag": "Softness"}],
                 applies={"mode": "request", "situation_ids": []}),
            wish(key="w3", fea=[{"category": "Functional", "subcategory": "Donning", "tag": "착용 여유와 편안함"}],
                 applies={"mode": "request", "situation_ids": []})], "questions": []}
        parsed = validate_parse_v2(raw, body, registry, [])
        ease = [{"category": "Functional", "subcategory": "Donning", "tag": "Ease"}]
        self.assertEqual(parsed["wishes"][0]["fea"], ease)
        self.assertEqual(parsed["wishes"][1]["fea"], [])
        self.assertEqual(parsed["wishes"][2]["fea"], ease)  # the copied label_ko maps to its tag
        self.assertIn("fea_path_repaired", parsed["warnings"])
        self.assertIn("fea_binding_dropped", parsed["warnings"])

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


# ---- ADR 0015: consented-memory warm start, novelty, taste change, end summary -------------------
from stylemate_memory.graph import memory as mem  # noqa: E402

TOP = [{"target_id": "top", "garment_type": "Top"}]


def lt(mid, content, conditions=None, bindings=(("Color", "Navy"),), polarity="prefer"):
    return {"memory_id": mid, "content": content, "conditions": conditions or {}, "garment_type": "Top",
            "polarity": polarity, "bindings": [{"feature": a, "values": [v], "polarity": polarity} for a, v in bindings],
            "created_at": mid}


def top_intent(memories, situation=None):
    state = it.new_intent("r1", TOP)
    if situation:
        state["situations"] = [situation]
    state["lt_memories"] = memories
    mem.refresh_priors(state, it.fixed_axes(state))
    return state


def view(pid, gender="men", **facts):
    return {"product_id": pid, "target_id": "top", "product_map_version": 1, "image_id": f"i-{pid}", "image_version": 1,
            "facts": {k: [v] for k, v in facts.items()}, "price": None, "gender": gender}


class MemoryWarmStartTests(unittest.TestCase):
    def test_start_situation_chip_free_and_invalid(self):
        self.assertEqual(mem.start_situation({"kind": "chip", "value": "주말"})["value"], "주말 외출")
        free = mem.start_situation({"kind": "free", "text": " 팀 회식 "})
        self.assertEqual((free["value"], free["raw"]), ("기타", "팀 회식"))
        self.assertIsNone(mem.start_situation(None))
        for bad in ({"kind": "chip", "value": "면접"}, {"kind": "free", "text": " "}, {"kind": "other"}):
            with self.assertRaises(StyleMateError):
                mem.start_situation(bad)

    def test_situation_memory_wins_on_its_axis_and_baseline_fills_the_rest(self):
        memories = [lt("m1", "평소 네이비 레귤러", bindings=(("Color", "Navy"), ("Fit", "Regular"))),
                    lt("m2", "출근엔 슬림", {"occasion": "출근"}, bindings=(("Fit", "Slim"),)),
                    lt("m3", "데이트엔 핑크", {"occasion": "데이트"}, bindings=(("Color", "Pink"),))]
        state = top_intent(memories, mem.start_situation({"kind": "chip", "value": "출근"}))
        self.assertEqual([c["memory_id"] for c in state["memory_chips"]], ["m2", "m1"])
        self.assertEqual(sorted((p["memory_id"], p["axis"], p["value"]) for p in state["priors"]),
                         [("m1", "Color", "Navy"), ("m2", "Fit", "Slim")])
        # No situation: the usual taste applies in full; situation memories do not.
        state = top_intent(memories)
        self.assertEqual(sorted((p["axis"], p["value"]) for p in state["priors"]), [("Color", "Navy"), ("Fit", "Regular")])

    def test_chips_are_capped_and_memory_off_and_dim_change_the_prior(self):
        memories = [lt(f"m{i}", f"취향 {i}", bindings=((["Color", "Fit", "Type", "Tone"][i], ["Navy", "Slim", "Shirt", "Dark"][i]),))
                    for i in range(4)]
        state = top_intent(memories)
        self.assertEqual(len(state["memory_chips"]), mem.MAX_MEMORY_CHIPS)
        self.assertEqual(len(state["priors"]), mem.MAX_MEMORY_CHIPS)  # only what is shown is applied
        key = scoring.score_key("top", it.scope_of(state), "Tone", "Dark")
        self.assertEqual(mem.effective(state, key)["a"], 1.0 + mem.PRIOR_WEIGHT)
        state["memory_mode"] = "dim"
        self.assertAlmostEqual(mem.effective(state, key)["a"], 1.0 + mem.PRIOR_WEIGHT * mem.DIM_FACTOR)
        state["memory_off"] = ["m3"]
        self.assertEqual(mem.effective(state, key)["a"], 1.0)
        self.assertEqual(state["scores"], {})  # priors never write learned scores

    def test_grid_gender_filter_and_novelty_slots_without_memory_values(self):
        products = [view(f"n{i}", Color="Navy", Fit="Regular") for i in range(8)]
        products += [view(f"o{i}", Color="Black", Fit="Oversized") for i in range(4)]
        products += [view(f"w{i}", gender="women", Color="Pink", Fit="Slim") for i in range(4)]
        state = top_intent([lt("m1", "평소 네이비", bindings=(("Color", "Navy"),))])
        state["gender"] = "men"
        plan = grid.plan_grid(products, TOP, state, it.scope_of(state), 1, seed="s")
        self.assertEqual(len(plan["cards"]), 8)
        self.assertTrue(all(c["gender"] == "men" for c in plan["cards"]))
        novel = [c for c in plan["cards"] if c["slot"] == "novel"]
        self.assertEqual(len(novel), mem.NOVEL_SLOTS)
        self.assertTrue(all(c["facts"]["Color"] == ["Black"] for c in novel))
        state["memory_mode"] = "dim"
        plan = grid.plan_grid(products, TOP, state, it.scope_of(state), 1, seed="s")
        self.assertEqual([c["slot"] for c in plan["cards"]].count("novel"), mem.NOVEL_SLOTS_DIM)
        state["memory_off"] = ["m1"]
        plan = grid.plan_grid(products, TOP, state, it.scope_of(state), 1, seed="s")
        self.assertNotIn("novel", [c["slot"] for c in plan["cards"]])

    def test_novelty_prompt_after_repeated_novel_picks_only_once(self):
        state = top_intent([lt("m1", "평소 네이비")])
        cards = [{"candidate_id": "a", "slot": "novel"}, {"candidate_id": "b", "slot": "converge"}]
        mem.note_novel_pick(state, cards, {"a"}, 1)
        self.assertIsNone(state["novelty_prompt"])
        mem.note_novel_pick(state, cards, {"a"}, 1)  # same turn counts once
        self.assertIsNone(state["novelty_prompt"])
        mem.note_novel_pick(state, cards, {"a"}, 2)
        self.assertEqual(state["novelty_prompt"], "ask")
        state["novelty_prompt"] = "done"
        mem.ask_novelty(state)
        self.assertEqual(state["novelty_prompt"], "done")
        cold = top_intent([])
        mem.ask_novelty(cold)  # no memory applied: nothing to make "new"
        self.assertIsNone(cold["novelty_prompt"])

    def test_taste_change_question_after_two_contrary_turns(self):
        state = top_intent([lt("m1", "평소 네이비")])
        scope = it.scope_of(state)
        key = scoring.score_key("top", scope, "Color", "Navy")
        for turn in (1, 2):
            before = {k: dict(v) for k, v in state["scores"].items()}
            entry = scoring.get(state["scores"], key)
            state["scores"][key] = entry | {"b": entry["b"] + scoring.MISS_PENALTY, "n": entry["n"] + 1}
            mem.note_contra(state, before, scope, turn)
            if turn == 1:
                self.assertIsNone(state["taste_prompt"])
        self.assertEqual(state["taste_prompt"], {"memory_id": "m1", "text": "평소 네이비"})


class SummaryProposalTests(unittest.TestCase):
    def test_order_dedupe_cap_and_sentences(self):
        state = it.new_intent("r1", TOP)
        base = {"target_id": "top", "origin": "explicit", "applies": {"mode": "baseline", "situation_ids": []},
                "evidence_ids": ["ev1"], "fea": [], "price": None}
        state["wishes"] = [
            base | {"key": "w1", "content": "네이비가 좋아요.", "polarity": "prefer", "pi": [{"feature": "Color", "values": ["Navy"]}]},
            base | {"key": "w2", "content": "후드는 싫어요.", "polarity": "avoid", "pi": [{"feature": "Type", "values": ["Hoodie"]}]},
            base | {"key": "w3", "content": "추정", "polarity": "prefer", "origin": "inferred", "pi": [{"feature": "Fit", "values": ["Slim"]}]}]
        scope = it.scope_of(state)
        state["scores"] = {scoring.score_key("top", scope, "Color", "Navy"): {"a": 4.0, "b": 1.0, "n": 3},
                           scoring.score_key("top", scope, "Fit", "Relaxed"): {"a": 4.0, "b": 1.0, "n": 3},
                           scoring.score_key("top", scope, "Tone", "Dark"): {"a": 3.0, "b": 1.0, "n": 2}}
        labels = {"Color": "색상", "Fit": "핏(여유)", "Tone": "색 톤"}
        items = mem.proposals(state, None, labels)
        self.assertEqual([(p["source"], p["text"]) for p in items],
                         [("wish", "네이비가 좋아요."), ("reject", "후드는 싫어요."), ("chip", "여유 핏 쪽이 좋아요.")])
        self.assertEqual([p["id"] for p in items], ["p1", "p2", "p3"])
        self.assertEqual(mem.chip_sentence("색 톤", "어두운 톤"), "어두운 톤 쪽이 좋아요.")
        self.assertEqual(mem.chip_sentence("색상", "네이비"), "네이비 쪽이 좋아요.")

    def test_conditions_keep_free_situation_raw(self):
        state = it.new_intent("r1", TOP)
        state["situations"] = [mem.start_situation({"kind": "free", "text": "팀 회식"})]
        self.assertEqual(mem.situation_conditions(state), {"occasion": "팀 회식"})
        self.assertEqual(mem.past_free_situations([lt("m1", "x", {"occasion": "팀 회식"}), lt("m2", "y", {"occasion": "출근"})]),
                         ["팀 회식"])

    def test_link_and_profile_outputs_are_validated(self):
        self.assertEqual(mem.validate_link({"match": "팀 회식"}, ["팀 회식"]), "팀 회식")
        self.assertIsNone(mem.validate_link({"match": "지어낸 상황"}, ["팀 회식"]))
        with self.assertRaises(StyleMateError):
            mem.validate_link({"match": None, "extra": 1}, [])
        memories = [lt("m1", "평소 네이비를 좋아해요."), lt("m2", "출근엔 슬림", {"occasion": "출근"})]
        raw = {"lines": [{"memory_id": "m1", "text": "네이비를 좋아해요."}, {"memory_id": "m2", "text": "출근엔 슬림"},
                         {"memory_id": "ghost", "text": "지어낸 취향"}, {"memory_id": "m1", "text": "중복"}]}
        changed = mem.validate_profile(raw, memories)
        self.assertEqual([(c["memory_id"], c["old"], c["text"]) for c in changed], [("m1", "평소 네이비를 좋아해요.", "네이비를 좋아해요.")])
        view_ = mem.profile_view(memories)
        self.assertEqual(view_, {"usual": ["평소 네이비를 좋아해요."], "situations": [{"situation": "출근", "lines": ["출근엔 슬림"]}]})


if __name__ == "__main__":
    unittest.main()


class ImprovementLogicTests(unittest.TestCase):
    """jaehyun_work F1-F5, F10, F11: code still decides; model text is validated or dropped."""

    def need_state(self, strength="soft"):
        state = it.new_intent("r1", TOP)
        state["fea_needs"] = [{"key": "t1-w1", "target_id": "top", "fea": [], "quote": "단정하게", "content": "단정한 상의",
                               "strength": strength}]
        state["hypotheses"] = [{"id": "h1", "target_id": "top", "axis": "Fit", "values": ["Regular"], "reason": "단정",
                                "fea_keys": ["t1-w1"]}]
        return state

    def test_f1_refresh_waits_and_needs_a_shared_unexplored_value(self):
        from stylemate_memory.graph.hypotheses import refresh_selection
        state = self.need_state()
        state["pick_history"] = [{"turn": t, "target_id": "top", "facts": {"Pattern": ["Stripe"], "Fit": ["Regular"],
                                                                           "Fabric": ["Cotton"]}} for t in (1, 2, 3)]
        state["turn"] = 2
        self.assertIsNone(refresh_selection(state))  # too early
        state["turn"] = 3
        summary = refresh_selection(state)
        self.assertEqual([(v["axis"], v["value"]) for v in summary["common_values"]], [("Pattern", "Stripe")])  # Fit explored, Fabric blind
        state["fea_needs"] = []
        self.assertIsNone(refresh_selection(state))

    def test_f2_polish_keeps_values_and_negation(self):
        from stylemate_memory.graph.summary_text import validate_polish
        items = [{"id": "p1", "pi": [("Fit", ["Relaxed"])], "polarity": "prefer"},
                 {"id": "p2", "pi": [("Detail", ["Hood"])], "polarity": "avoid"}]
        ok = validate_polish({"sentences": [{"id": "p1", "text": "출근할 땐 여유 핏 셔츠가 좋아요"},
                                            {"id": "p2", "text": "후드 달린 옷이 좋아요"}]}, items)
        self.assertEqual(ok, {"p1": "출근할 땐 여유 핏 셔츠가 좋아요"})  # p2 lost its negation -> rule text stays
        self.assertEqual(validate_polish({"sentences": [{"id": "p1", "text": "편한 옷이 좋아요"}]}, items), {})
        with self.assertRaises(StyleMateError):
            validate_polish({"bogus": []}, items)

    def test_f4_clarify_only_offers_differing_axes(self):
        from stylemate_memory.graph.clarify import validate_clarify
        labels = {"Fit": "핏", "Color": "색상"}
        raw = {"question": "핏 때문에 고르셨나요?", "options": [{"axis": "Fit", "label": "넉넉한 품"},
                                                         {"axis": "Pattern", "label": "줄무늬"}, {"axis": "Color", "label": "밝은 색"}]}
        result = validate_clarify(raw, ["Fit", "Color"], labels)
        self.assertEqual([o["feature"] for o in result["options"]], ["Fit", "Color"])
        self.assertIsNone(validate_clarify({"question": "?", "options": [{"axis": "Fit", "label": "핏"}]}, ["Fit"], labels))

    def test_f5_must_values_come_only_from_hard_needs(self):
        self.assertEqual(grid.must_values(self.need_state("soft")), set())
        self.assertEqual(grid.must_values(self.need_state("hard")), {("top", "Fit", "Regular")})

    def test_f10_notice_and_f11_evidence(self):
        from stylemate_memory.graph.service import _chip_evidence, _memory_notice, profile_rewrite_enabled
        state = top_intent([lt("m1", "출근엔 네이비", {"occasion": "출근"})], situation=mem.start_situation({"kind": "chip", "value": "출근"}))
        state["turn"] = 1
        notice = _memory_notice(state)
        self.assertEqual((notice["lines"], notice["situations"]), (["출근엔 네이비"], ["출근"]))
        state["turn"] = 2
        self.assertIsNone(_memory_notice(state))
        state["pick_history"] = [{"turn": 1, "target_id": "top", "facts": {"Fit": ["Relaxed"]}},
                                 {"turn": 2, "target_id": "top", "facts": {"Fit": ["Regular"]}},
                                 {"turn": 2, "target_id": "top", "facts": {"Color": ["Navy"]}}]
        self.assertEqual(_chip_evidence(state, {"target_id": "top", "feature": "Fit", "value": "Relaxed"}), {"with": 1, "of": 2})
        self.assertIsNone(_chip_evidence(state, {"target_id": "top", "feature": "Pattern", "value": "Solid"}))
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"STYLEMATE_PROFILE_REWRITE": "off"}):
            self.assertFalse(profile_rewrite_enabled())
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertTrue(profile_rewrite_enabled())
