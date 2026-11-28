"""Question loop v1 (graph/questions.py, ADR 0020): candidates, mode builds, rule/LLM choice and every answer row.

Pure logic over plain dicts: no LangGraph, no SQLite, no model. Numbers are pilot assumptions, so the tests check
the order of strength levels and which keys change or stay, not tuned values.
"""

import unittest

from stylemate_memory.graph import grid, intent as it, questions as q, scoring
from stylemate_memory.graph.intent import new_intent as _new_intent

LABELS = {"Type": "종류", "Fit": "핏", "Color": "색상", "Style": "스타일", "Fabric": "소재", "Tone": "톤", "Pattern": "무늬"}


def view(pid, facts, v3=None, target="t"):
    return {"product_id": pid, "target_id": target, "image_id": f"img-{pid}", "image_version": 1, "facts": facts,
            "v3": v3, "price": None, "gender": "men", "product_map_version": 1}


def shirts():
    fits = ["Slim", "Regular", "Relaxed", "Oversized"]
    return [view(f"s{i}", {"Type": ["Shirt"], "Fit": [fits[i % 4]], "Color": ["Navy"], "Style": ["Minimal" if i % 2 else "Casual"],
                           "Fabric": ["Cotton" if i % 2 else "Linen"]},
                 {"price_krw": 50000, "axes": {"Fit": {"score": float(i % 4 + 1)}, "Tone": {"score": 30.0}}}) for i in range(8)]


def mixed():
    kinds = ["Shirt", "Knit", "Hoodie"]
    return [view(f"m{i}", {"Type": [kinds[i % 3]], "Fit": ["Relaxed" if i % 2 else "Slim"], "Style": ["Casual"]}) for i in range(9)]


def new_intent():
    intent = it.new_intent("r", [{"target_id": "t", "garment_type": "Top"}])
    intent["turn"] = 1
    return intent


def question(mode, axis, options, multi=False, kind="gap", **extra):
    return {"question_id": "q1", "mode": mode, "kind": kind, "target_id": "t", "axis": axis, "prompt": "p", "multi": multi,
            "options": options, "allow": ["unsure", "neither", "skip"], "strengths": extra.pop("strengths", []),
            "switch_to": [], **extra}


def answer(ids, choice="options", strengths=None):
    result = {"question_id": "q1", "choice": choice, "option_ids": ids, "switch_to": None}
    if strengths:
        result["strengths"] = strengths
    return result


def key(axis, value):
    return scoring.score_key("t", "request", axis, value)


class CandidateTests(unittest.TestCase):
    def test_ranking_filters_and_orders_axes(self):
        intent = new_intent()
        ranked = q.axis_ranking(intent, "t", shirts(), [], "request")
        axes = [c["axis"] for c in ranked]
        self.assertNotIn("Type", axes)  # one value only
        self.assertNotIn("Color", axes)
        self.assertEqual(axes[0], "Fit")  # importance x even split x no knowledge
        self.assertNotIn("Fit", [c["axis"] for c in q.axis_ranking(intent, "t", shirts(), ["Fit"], "request")])
        intent["asked"] = [{"target_id": "t", "axis": "Fit", "turn": 0, "kind": "gap"}]
        intent["skipped_axes"] = [["t", "Style"]]
        self.assertEqual([c["axis"] for c in q.axis_ranking(intent, "t", shirts(), [], "request")], ["Fabric"])

    def test_known_preference_lowers_uncertainty_and_a_mention_raises_importance(self):
        intent = new_intent()
        base = {c["axis"]: c["score"] for c in q.axis_ranking(intent, "t", shirts(), [], "request")}
        intent["scores"][key("Fit", "Relaxed")] = {"a": 9.0, "b": 1.0, "n": 4}
        intent["soft"] = [{"target_id": "t", "feature": "Fabric", "values": ["Linen"], "polarity": "prefer"}]
        after = {c["axis"]: c["score"] for c in q.axis_ranking(intent, "t", shirts(), [], "request")}
        self.assertLess(after["Fit"], base["Fit"])
        self.assertGreater(after["Fabric"], base["Fabric"])

    def test_reactive_shared_values_need_two_and_come_first(self):
        intent = new_intent()
        pool = shirts()
        chosen = [pool[1]["facts"], pool[3]["facts"]]  # Regular/Oversized, both Minimal + Cotton
        intent["trigger"] = {"selection": {"target_id": "t", "product_ids": ["s1", "s3"], "chosen": chosen,
                                           "shown": [p["facts"] for p in pool]}}
        found = q.candidates(intent, {"t": pool}, {"t": []}, pool)
        self.assertEqual(found[0]["trigger"], "shared_values")
        self.assertEqual({(c["axis"], c["value"]) for c in found[0]["chips"]}, {("Style", "Minimal"), ("Fabric", "Cotton")})
        intent["trigger"]["selection"]["chosen"] = [pool[0]["facts"], pool[3]["facts"]]  # nothing shared but Navy/Shirt
        self.assertNotIn("shared_values", [c.get("trigger") for c in q.candidates(intent, {"t": pool}, {"t": []}, pool)])

    def test_gap_rest_cap_and_comparison_offer(self):
        intent = new_intent()
        intent["ignored_turn"] = 1
        self.assertEqual(q.candidates(intent, {"t": shirts()}, {"t": []}), [])  # rest after an unanswered question
        intent["turn"] = 3
        self.assertTrue(q.candidates(intent, {"t": shirts()}, {"t": []}))
        intent["asked"] = [{"target_id": "t", "axis": a, "turn": 0, "kind": "gap"} for a in ("A", "B", "C", "D")]
        self.assertEqual(q.candidates(intent, {"t": shirts()}, {"t": []}), [])
        intent["shortlist"] = [{"product_id": "s1"}, {"product_id": "s2"}]
        intent["turn"] = q.ENOUGH_TURNS
        self.assertEqual([c["kind"] for c in q.candidates(intent, {"t": shirts()}, {"t": []})], ["flow"])
        intent["compare_offered"] = q.ENOUGH_TURNS - 1
        self.assertEqual(q.candidates(intent, {"t": shirts()}, {"t": []}), [])


class BuildTests(unittest.TestCase):
    def gap(self, axis, pool):
        return next(c for c in q.axis_ranking(new_intent(), "t", pool, [], "request") if c["axis"] == axis)

    def test_photo_chips_multi_for_style_single_for_fit_and_never_fabric(self):
        modes, built = q.allowed(self.gap("Style", mixed() + shirts()), mixed() + shirts(), LABELS)
        self.assertIn("photo_chips", modes)
        self.assertTrue(built["photo_chips"]["multi"])
        self.assertTrue(all(o["image_id"] for o in built["photo_chips"]["options"]))
        modes, built = q.allowed(self.gap("Fit", mixed()), mixed(), LABELS)
        self.assertFalse(built["photo_chips"]["multi"])
        self.assertNotIn("select_images", modes)  # Type not settled: photos would mix garments
        modes, _ = q.allowed(self.gap("Fabric", shirts()), shirts(), LABELS)
        self.assertEqual(modes, ["text_options"])

    def test_select_images_one_type_up_to_four_and_pair_layout(self):
        _, built = q.allowed(self.gap("Fit", shirts()), shirts(), LABELS)
        options = built["select_images"]["options"]
        self.assertEqual(len(options), 4)
        self.assertEqual(len({o["value"] for o in options}), 4)
        self.assertEqual(built["select_images"]["layout"], "grid")
        two = shirts()[:2]
        _, built = q.allowed(self.gap("Fit", two), two, LABELS)
        self.assertEqual(built["select_images"]["layout"], "pair")
        self.assertIn("neither", built["select_images"]["allow"])

    def test_text_prompt_particle(self):
        _, built = q.allowed(self.gap("Fit", shirts()), shirts(), LABELS)
        self.assertEqual(built["text_options"]["prompt"], "핏은 어떤 쪽이 좋으세요?")
        self.assertEqual((q.josa("핏"), q.josa("스타일"), q.josa("색상")), ("은", "은", "은"))
        self.assertEqual((q.josa("소재"), q.josa("톤")), ("는", "은"))

    def test_explain_images_needs_a_picture_for_every_reading(self):
        candidate = {"id": "t:Style:term", "target_id": "t", "axis": "Style", "kind": "reactive", "trigger": "ambiguous_term",
                     "values": ["Minimal", "Casual"], "term": "깔끔한"}
        modes, built = q.allowed(candidate, shirts(), LABELS)
        self.assertEqual(modes, ["explain_images"])
        self.assertEqual(built["explain_images"]["prompt"], "'깔끔한'은 어느 쪽에 가까워요?")
        self.assertEqual(q.allowed(candidate | {"values": ["Minimal", "Street"]}, shirts(), LABELS)[0], [])

    def test_relative_adjust_offers_directions_inside_the_scale(self):
        base = shirts()[3]  # Fit score 4.0 = Oversized: no "더 여유롭게"
        candidate = {"id": "t:relative", "target_id": "t", "axis": None, "kind": "reactive", "trigger": "near_match",
                     "values": [], "base": base}
        _, built = q.allowed(candidate, shirts(), LABELS)
        labels = [o["label"] for o in built["relative_adjust"]["options"]]
        self.assertIn("조금 더 슬림하게", labels)
        self.assertNotIn("조금 더 여유롭게", labels)
        self.assertIn("조금 더 밝게", labels)
        self.assertEqual(q.allowed(candidate | {"base": view("x", {}, None)}, shirts(), LABELS)[0], [])


class ChooseTests(unittest.TestCase):
    def options(self):
        pool = shirts()
        ranking = q.axis_ranking(new_intent(), "t", pool, [], "request")
        return [{"candidate": c, **dict(zip(("modes", "built"), q.allowed(c, pool, LABELS)))} for c in ranking]

    def test_rule_defaults(self):
        options = self.options()
        picked, decision = q.choose(options, new_intent())
        self.assertEqual((picked["candidate"]["axis"], decision["mode"], decision["decided_by"]), ("Fit", "select_images", "rule"))
        intent = new_intent()
        intent["mode_pref"] = {"t:Fit": "text_options"}
        self.assertEqual(q.choose(options, intent)[1]["mode"], "text_options")
        fabric = next(o for o in options if o["candidate"]["axis"] == "Fabric")
        self.assertEqual(q.choose([fabric], new_intent())[1]["mode"], "text_options")

    def test_llm_inside_allowed_with_true_signals_only(self):
        options = self.options()
        intent = new_intent()
        ok = lambda *_: {"candidate_id": "t:Fit", "mode": "photo_chips", "signals": [], "reason": "사진이 쉬워요"}
        picked, decision = q.choose(options, intent, ok)
        self.assertEqual((decision["mode"], decision["decided_by"], decision["shadow"]["mode"], decision["agree"]),
                         ("photo_chips", "llm", "select_images", False))
        outside = lambda *_: {"candidate_id": "t:Fit", "mode": "relative_adjust", "signals": [], "reason": ""}
        self.assertEqual(q.choose(options, intent, outside)[1]["decided_by"], "rule")
        lie = lambda *_: {"candidate_id": "t:Fit", "mode": "text_options", "signals": ["unsure_repeat"], "reason": ""}
        self.assertTrue(q.choose(options, intent, lie)[1]["reason"].endswith("rejected_llm"))
        second = lambda *_: {"candidate_id": options[1]["candidate"]["id"], "mode": "text_options", "signals": [], "reason": ""}
        self.assertEqual(q.choose(options, intent, second)[0], options[0])  # a non-first axis needs a signal
        second_ok = lambda *_: {"candidate_id": options[1]["candidate"]["id"], "mode": "text_options", "signals": ["split"], "reason": ""}
        self.assertEqual(q.choose(options, intent, second_ok)[0], options[1])

        def broken(*_):
            raise RuntimeError("down")
        self.assertTrue(q.choose(options, intent, broken)[1]["reason"].endswith("llm_unavailable"))
        skip = lambda *_: {"candidate_id": None, "mode": None, "signals": [], "reason": ""}
        self.assertIsNone(q.choose(options, intent, skip)[0])


class InterpretTests(unittest.TestCase):
    def test_text_and_single_photo_pin_multi_photo_confirms(self):
        intent = new_intent()
        options = [{"id": "o0", "label": "a", "value": "Slim"}, {"id": "o1", "label": "b", "value": "Relaxed"}]
        self.assertEqual(q.interpret(intent, question("text_options", "Fit", options), answer(["o0"]), "request"), [key("Fit", "Slim")])
        self.assertEqual(intent["pinned"], [{"key": key("Fit", "Slim")}])
        intent = new_intent()
        q.interpret(intent, question("photo_chips", "Fit", options), answer(["o1"]), "request")
        self.assertEqual(intent["pinned"], [{"key": key("Fit", "Relaxed")}])
        intent = new_intent()
        style = [{"id": f"o{i}", "label": v, "value": v} for i, v in enumerate(["Minimal", "Casual", "Street"])]
        changed = q.interpret(intent, question("photo_chips", "Style", style, multi=True), answer(["o0", "o1"]), "request")
        self.assertEqual(sorted(changed), sorted([key("Style", "Minimal"), key("Style", "Casual")]))
        self.assertEqual(intent["pinned"], [])  # L3, not "이 값들만"
        self.assertNotIn(key("Style", "Street"), intent["scores"])  # unchosen = L0, not L-1
        chips = scoring.chips(intent, "request", LABELS)
        self.assertTrue(all(c["confirmed"] and not c["pinned"] for c in chips))
        self.assertEqual(q.interpret(new_intent(), question("photo_chips", "Style", style, multi=True),
                                     answer(["o0", "o1", "o2"]), "request"), [])  # all chosen = L0

    def test_explain_images_confirms_and_trims_the_word_readings(self):
        intent = new_intent()
        intent["hypotheses"] = [{"target_id": "t", "axis": "Style", "values": ["Minimal", "Casual"], "fea_keys": ["f"], "reason": ""}]
        options = [{"id": "o0", "label": "a", "value": "Minimal"}, {"id": "o1", "label": "b", "value": "Casual"}]
        q.interpret(intent, question("explain_images", "Style", options, kind="reactive"), answer(["o1"]), "request")
        self.assertEqual(intent["hypotheses"][0]["values"], ["Casual"])
        self.assertNotIn(key("Style", "Minimal"), intent["scores"])
        self.assertIn(key("Style", "Casual"), intent["confirmed"])

    def test_select_images_contrast_on_the_asked_axis_only(self):
        intent = new_intent()
        options = [{"id": f"o{i}", "label": v, "value": v, "product_id": f"s{i}"} for i, v in enumerate(["Slim", "Regular", "Relaxed"])]
        changed = q.interpret(intent, question("select_images", "Fit", options, multi=True), answer(["o2"]), "request")
        self.assertEqual(len(changed), 3)
        self.assertGreater(scoring.mean(intent["scores"][key("Fit", "Relaxed")]), 0.5)
        self.assertLess(scoring.mean(intent["scores"][key("Fit", "Slim")]), 0.5)
        self.assertEqual(intent["miss_streak"].get(key("Fit", "Slim"), 0), 0)  # L-1 never counts toward auto exclusion
        self.assertEqual(intent["trigger"]["base"], {"target_id": "t", "product_id": "s2", "reason": "single_pick"})
        self.assertEqual(q.interpret(new_intent(), question("select_images", "Fit", options, multi=True),
                                     answer(["o0", "o1", "o2"]), "request"), [])
        intent = new_intent()
        self.assertEqual(q.interpret(intent, question("select_images", "Fit", options, multi=True), answer([], "neither"), "request"), [])
        self.assertEqual(intent["requeue"]["prefer"], "text_options")
        fabric = [{"id": "o0", "label": "a", "value": "Linen", "product_id": "a"}, {"id": "o1", "label": "b", "value": "Wool", "product_id": "b"}]
        self.assertEqual(q.interpret(new_intent(), question("select_images", "Fabric", fabric, multi=True), answer(["o0"]), "request"), [])

    def test_reason_chips_only_pins_more_raises_and_asks_relative(self):
        intent = new_intent()
        options = [{"id": "o0", "label": "a", "value": "Minimal", "axis": "Style"}, {"id": "o1", "label": "b", "value": "Cotton", "axis": "Fabric"}]
        quest = question("reason_chips", None, options, multi=True, kind="reactive", strengths=["only", "more"], products=["s1", "s3"])
        self.assertFalse(q.valid_answer(quest, answer(["o0"], strengths={"o1": "only"})))
        self.assertFalse(q.valid_answer(quest, answer(["o0"], strengths={"o0": "never"})))
        self.assertTrue(q.valid_answer(quest, answer(["o0", "o1"], strengths={"o0": "only", "o1": "more"})))
        q.interpret(intent, quest, answer(["o0", "o1"], strengths={"o0": "only", "o1": "more"}), "request")
        self.assertEqual(intent["pinned"], [{"key": key("Style", "Minimal")}])
        self.assertEqual(intent["scores"][key("Fabric", "Cotton")]["a"], 1.0 + scoring.REASON_GAIN)
        self.assertEqual(intent["trigger"]["base"]["reason"], "more")

    def test_relative_adjust_moves_the_v3_target(self):
        intent = new_intent()
        base = shirts()[2]  # Fit 3.0 = Relaxed
        options = [{"id": "o0", "label": "조금 더 여유롭게", "axis": "Fit", "value": "+step_small", "direction": 1, "step": "step_small"}]
        quest = question("relative_adjust", None, options, kind="reactive", base={"product_id": "s2", "image_id": "i", "image_version": 1})
        changed = q.interpret(intent, quest, answer(["o0"]), "request", base)
        self.assertIn(key("Fit", "Oversized"), changed)
        self.assertEqual(intent["v3_targets"], [{"target_id": "t", "axis": "Fit", "score": 3.5}])
        self.assertEqual(intent["anchor"]["product_id"], "s2")
        self.assertEqual(q.interpret(new_intent(), quest, answer(["o0"]), "request", view("x", {}, None)), [])
        self.assertEqual(q.relative_values("Fit", 4.0, 1, "step_large"), (4.0, []))
        self.assertEqual(q.relative_values("Tone", 30.0, 1, "step_large"), (45.0, ["Medium"]))

    def test_progress_answers_change_no_value(self):
        options = [{"id": "o0", "label": "a", "value": "Slim"}, {"id": "o1", "label": "b", "value": "Relaxed"}]
        intent = new_intent()
        self.assertEqual(q.interpret(intent, question("text_options", "Fit", options), answer([], "unsure"), "request"), [])
        self.assertEqual(intent["requeue"], {"target_id": "t", "axis": "Fit", "prefer": "image"})
        self.assertEqual(q.interpret(intent, question("text_options", "Fit", options), answer([], "skip"), "request"), [])
        self.assertEqual(intent["skipped_axes"], [["t", "Fit"]])
        self.assertEqual((intent["scores"], intent["pinned"], intent["excluded"]), ({}, [], []))
        compare = question("propose_compare", None, [{"id": "compare", "label": "c", "value": "compare"},
                                                     {"id": "continue", "label": "d", "value": "continue"}], kind="flow")
        self.assertEqual(q.interpret(intent, compare, answer(["continue"]), "request"), [])
        self.assertEqual(q.interpret(intent, compare, answer(["compare"]), "request"), ["compare"])
        self.assertTrue(intent["compare_mode"])

    def test_strength_order(self):
        self.assertGreater(scoring.CONFIRM_GAIN, scoring.REASON_GAIN)
        self.assertGreater(scoring.REASON_GAIN, scoring.SELECT_GAIN)
        self.assertGreater(scoring.SELECT_GAIN, 0)
        self.assertGreater(scoring.MISS_PENALTY, 0)


class PlanTests(unittest.TestCase):
    def test_plan_logs_rule_decision_and_records_the_axis(self):
        intent = new_intent()
        question_ = q.plan(intent, {"t": shirts()}, {"t": []}, LABELS, shirts())
        self.assertEqual((question_["mode"], question_["axis"], question_["kind"]), ("select_images", "Fit", "gap"))
        self.assertIn("photo_chips", question_["switch_to"])
        entry = intent["question_log"][-1]
        self.assertEqual((entry["event"], entry["decision"]["decided_by"]), ("ask", "rule"))
        self.assertEqual(intent["asked"][-1]["axis"], "Fit")
        public = q.public(question_)
        self.assertNotIn("value", public["options"][0])

    def test_reason_banner_blocks_proactive_questions(self):
        intent = new_intent()
        intent["reason_prompt"] = {"set_id": "x", "selected": [], "axes": ["Fit"]}
        self.assertIsNone(q.plan(intent, {"t": shirts()}, {"t": []}, LABELS, shirts()))

    def test_loop_default_on(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("STYLEMATE_QUESTION_LOOP", None)
            self.assertTrue(q.loop_enabled())
        with mock.patch.dict(os.environ, {"STYLEMATE_QUESTION_LOOP": "off"}):
            self.assertFalse(q.loop_enabled())


class V3RuntimeTests(unittest.TestCase):
    def test_ciede2000_matches_sharma_pairs(self):
        pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                 ((50, 0, 0), (50, -1, 2), 2.3669),
                 ((50, 2.5, 0), (73, 25, -18), 27.1492),
                 ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082)]
        for lab1, lab2, want in pairs:
            self.assertAlmostEqual(scoring.delta_e2000(lab1, lab2), want, places=3)

    def test_budget_uses_price_krw_and_unknown_price_fails(self):
        budget = {"op": "lte", "min_krw": None, "max_krw": 60000}
        self.assertTrue(grid.price_ok(view("a", {}, {"price_krw": 59000, "axes": {}}), budget))
        self.assertFalse(grid.price_ok(view("a", {}, {"price_krw": None, "axes": {}}), budget))
        self.assertFalse(grid.price_ok(view("a", {}, {"price_krw": 61000, "axes": {}}) | {"price": 1}, budget))
        self.assertTrue(grid.price_ok(view("a", {}) | {"price": 1000}, budget))  # pre-v3 catalogs keep price_amount

    def test_relative_target_and_colour_closeness_rank_products(self):
        intent = new_intent()
        intent["v3_targets"] = [{"target_id": "t", "axis": "Fit", "score": 3.5}]
        near, far = shirts()[3], shirts()[0]  # 4.0 vs 1.0
        self.assertGreater(grid._v3_target(near, intent, "t"), grid._v3_target(far, intent, "t"))
        navy = {"axes": {"Color": {"colors": [{"lab": [11.2, 1.8, -7.6]}]}}}
        anchor = view("a", {}, navy)
        same, other = view("b", {}, navy), view("c", {}, {"axes": {"Color": {"colors": [{"lab": [80.0, 0.0, 30.0]}]}}})
        self.assertGreater(grid._similar(same, anchor), grid._similar(other, anchor))


def product(pid, **facts):  # v0 tests (kept)
    return {"product_id": pid, "target_id": "t", "facts": {k: [v] for k, v in facts.items()}}


POOL = [  # no images: only text_options can ask (the v0 path kept by v1)
       product("a", Color="Navy", Fit="Slim", Brand="X"), product("b", Color="Black", Fit="Slim", Brand="Y"),
        product("c", Color="Navy", Fit="Slim", Brand="Z")]
V0_LABELS = {"Color": "색상", "Fit": "핏(여유)"}


class QuestionLoopTests(unittest.TestCase):
    def intent(self):
        intent = _new_intent("r1", [{"target_id": "t", "garment_type": "Top"}])
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
        question = q.plan(intent, {"t": POOL}, {}, V0_LABELS)
        self.assertEqual((question["mode"], question["axis"]), ("text_options", "Color"))
        self.assertEqual([o["value"] for o in question["options"]], ["Navy", "Black"])
        self.assertEqual(intent["question_log"][-1]["decision"]["decided_by"], "rule")
        intent["ask"] = question
        self.assertIsNone(q.plan(intent, {"t": POOL}, {}, V0_LABELS))  # the axis is asked once per request
        intent["ask"] = None
        self.assertIsNone(q.plan(intent, {"t": POOL}, {}, V0_LABELS))

    def test_answer_validation_and_text_option_pins_the_value(self):
        intent = self.intent()
        question = q.plan(intent, {"t": POOL}, {}, V0_LABELS)
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
        question = q.plan(self.intent(), {"t": POOL}, {}, V0_LABELS)
        self.assertNotIn("value", q.public(question)["options"][0])


if __name__ == "__main__":
    unittest.main()
