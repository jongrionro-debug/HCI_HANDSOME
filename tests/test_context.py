import json
import unittest

from stylemate_memory.context import build_context
from stylemate_memory.errors import StyleMateError


def memory(
    mid,
    *,
    user_id="u1",
    request_id=None,
    scope="long_term",
    feature="fit",
    values=None,
    polarity="prefer",
    strength="soft",
    selector=None,
    conditions=None,
    status="active",
    family_id=None,
    valid_until=None,
    match="any",
    created_at=None,
):
    return {
        "id": mid,
        "user_id": user_id,
        "request_id": request_id,
        "scope": scope,
        "feature": feature,
        "values": values or ["Relaxed"],
        "polarity": polarity,
        "strength": strength,
        "match": match,
        "selector": selector or {},
        "conditions": conditions or {},
        "content": mid,
        "origin": "explicit",
        "confirmed": True,
        "status": status,
        "version": 1,
        "family_id": family_id,
        "valid_until": valid_until,
        "created_at": created_at,
    }


def snapshot(memories, *, request_id="r1", now="2026-10-14T00:00:00+00:00"):
    return {
        "request": {"id": request_id, "user_id": "u1", "revision": 4, "timezone": "Asia/Seoul", "status": "open"},
        "profile_revision": 9,
        "memories": memories,
        "now": now,
    }


class ContextTests(unittest.TestCase):
    def test_short_term_exception_and_new_request_boundary(self):
        base = memory("base", feature="fit", values=["Relaxed"], selector={"garment_type": "Pants"})
        current = memory("current", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants", "slot_id": "pants-1"})
        old = memory("old", request_id="r0", scope="short_term", feature="fit", values=["Oversized"], selector={"garment_type": "Pants"})
        context = build_context(snapshot([base, current, old]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertEqual(context["bindings"][0]["values"], ["Slim"])
        self.assertIn({"source_id": "base", "reason": "short_term_override"}, context["overridden"])
        self.assertIn({"source_id": "old", "reason": "different_request"}, context["excluded"])

        new_request = build_context(snapshot([base, current], request_id="r2"), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertEqual(new_request["bindings"][0]["values"], ["Relaxed"])
        self.assertTrue(any(item.get("source_id") == "current" for item in new_request["excluded"]))

    def test_targets_keep_pants_fit_and_shirt_color_separate(self):
        pants_fit = memory("pants-fit", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"})
        shirt_color = memory("shirt-color", request_id="r1", scope="short_term", feature="color", values=["White"], selector={"garment_type": "Shirt"})
        context = build_context(snapshot([pants_fit, shirt_color]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}])
        bindings = {(x["target_id"], x["feature"]): x["values"] for x in context["bindings"]}
        self.assertEqual(bindings[("pants-1", "fit")], ["Slim"])
        self.assertEqual(bindings[("shirt-1", "color")], ["White"])

    def test_unscoped_memory_can_bind_each_target_and_limits_count_memory_once(self):
        shared = memory("shared", request_id="r1", scope="short_term", feature="color", values=["Navy"], family_id="shared-family")
        context = build_context(snapshot([shared]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}], short_limit=1)
        self.assertEqual({binding["target_id"] for binding in context["bindings"]}, {"pants-1", "shirt-1"})
        self.assertEqual(len(context["memories"]), 1)

    def test_family_prefers_current_scope_and_newer_version_per_target(self):
        base = memory("base", scope="long_term", feature="fit", values=["Relaxed"], selector={"garment_type": "Pants"}, family_id="fit-family", status="active")
        current = memory("current", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"}, family_id="fit-family", status="active",)
        context = build_context(snapshot([base, current]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertEqual(context["bindings"][0]["values"], ["Slim"])
        self.assertTrue(any(item["source_id"] == "base" for item in context["overridden"]))

    def test_avoid_condition_expiration_foreign_and_unknown_condition_are_not_used(self):
        avoid = memory("avoid-black", request_id="r1", scope="short_term", feature="color", values=["Black"], polarity="avoid", selector={"garment_type": "Pants"})
        expired = memory("expired", feature="fit", valid_until="2026-10-13T00:00:00+00:00")
        foreign = memory("foreign", user_id="u2", feature="fit")
        conditional = memory("conditional", feature="fit", conditions={"occasion": "rain"})
        context = build_context(snapshot([avoid, expired, foreign, conditional]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertEqual(context["bindings"][0]["polarity"], "avoid")
        reasons = {(item.get("source_id"), item["reason"]) for item in context["excluded"] if item.get("source_id")}
        self.assertIn(("expired", "expired"), reasons)
        self.assertIn(("conditional", "condition_unknown"), reasons)
        self.assertNotIn("foreign", {item.get("source_id") for item in context["excluded"]})
        self.assertNotIn("u2", json.dumps(context, ensure_ascii=False))

    def test_empty_and_conflict_and_range_are_explicit(self):
        left = memory("left", request_id="r1", scope="short_term", feature="fit", values=["Slim"], selector={"garment_type": "Pants"})
        right = memory("right", request_id="r1", scope="short_term", feature="fit", values=["Relaxed"], selector={"garment_type": "Pants"})
        context = build_context(snapshot([left, right]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertFalse(context["bindings"])
        self.assertEqual(context["questions"][0]["reason"], "same_priority_conflict")
        self.assertEqual({item["id"] for item in context["memories"]}, {"left", "right"})
        self.assertEqual(build_context(snapshot([]), [{"id": "pants-1", "garment_type": "Pants"}])["bindings"], [])

    def test_budget_blocks_without_erasing_hard_current_conditions(self):
        hard = memory("hard", request_id="r1", scope="short_term", feature="fit", values=["Slim"], strength="hard", selector={"garment_type": "Pants"}, conditions={"goal": "x" * 1000})
        context = build_context(snapshot([hard]), [{"id": "pants-1", "garment_type": "Pants"}], facts={"goal": "x" * 1000}, char_budget=1200)
        self.assertTrue(context["blocked"])
        self.assertTrue(context["bindings"])

    def test_empty_context_does_not_block_just_because_registry_metadata_is_large(self):
        context = build_context(snapshot([]), [{"id": "pants-1", "garment_type": "Pants"}], char_budget=256)
        self.assertFalse(context["blocked"])

    def test_context_is_deterministic_and_has_no_user_id(self):
        item = memory("m", request_id="r1", scope="short_term", feature="color", values=["Navy"], selector={"garment_type": "Jacket"})
        a = build_context(snapshot([item]), [{"id": "jacket-1", "garment_type": "Jacket"}])
        b = build_context(snapshot([item]), [{"id": "jacket-1", "garment_type": "Jacket"}])
        self.assertEqual(a["context_hash"], b["context_hash"])
        encoded = json.dumps(a, ensure_ascii=False)
        self.assertNotIn('"user_id"', encoded)

    def test_situation_memory_keys_become_confirmed_facts_not_item_bindings(self):
        occasion = memory("occasion", feature="occasion", values=["presentation"], selector={"garment_type": "Pants"})
        context = build_context(snapshot([occasion]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertNotIn("occasion", context["facts"])
        self.assertEqual(context["facts_by_target"]["pants-1"]["occasion"], "presentation")
        self.assertFalse(context["bindings"])
        self.assertNotIn("occasion", [item["feature"] for item in context["memories"]])

    def test_external_and_memory_fact_conditions_are_checked_before_use(self):
        conditional_memory = memory(
            "conditional-goal",
            request_id="r1",
            scope="short_term",
            feature="goal",
            values=["business casual"],
            conditions={"occasion": "meeting"},
        )
        unknown = build_context(snapshot([conditional_memory]), [{"id": "p", "garment_type": "Pants"}])
        self.assertNotIn("goal", unknown["facts"])
        self.assertIn({"source_id": "conditional-goal", "reason": "condition_unknown"}, unknown["excluded"])

        mismatch = build_context(snapshot([conditional_memory]), [{"id": "p", "garment_type": "Pants"}], facts={"occasion": "rain"})
        self.assertNotIn("goal", mismatch["facts"])
        self.assertIn({"source_id": "conditional-goal", "reason": "condition_mismatch"}, mismatch["excluded"])

        matched = build_context(snapshot([conditional_memory]), [{"id": "p", "garment_type": "Pants"}], facts={"occasion": "meeting"})
        self.assertEqual(matched["facts"]["goal"], "business casual")
        self.assertIn(["fact:occasion"], [source["source_ids"] for source in matched["fact_sources"]])

        conditional_external = build_context(
            snapshot([]),
            [{"id": "p", "garment_type": "Pants"}],
            facts={"goal": {"value": "business casual", "confirmed": True, "conditions": {"occasion": "meeting"}}},
        )
        self.assertNotIn("goal", conditional_external["facts"])
        self.assertIn({"source_id": "fact:goal", "reason": "condition_unknown"}, conditional_external["excluded"])

    def test_fact_selector_provenance_is_kept_per_target(self):
        goal = memory(
            "pants-goal",
            request_id="r1",
            scope="short_term",
            feature="goal",
            values=["business casual"],
            selector={"slot_id": "pants-1"},
        )
        context = build_context(snapshot([goal]), [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}])
        self.assertEqual(context["fact_sources"][0]["target_scope"], {"slot_id": "pants-1"})
        self.assertEqual(context["fact_sources"][0]["source_versions"], [1])

    def test_current_explicit_can_temporarily_replace_long_hard_avoid_but_current_conflict_waits(self):
        base = memory("base-avoid", feature="color", values=["Black"], polarity="avoid", strength="hard", selector={"garment_type": "Pants"})
        current = memory("current-black", request_id="r1", scope="short_term", feature="color", values=["Black"], selector={"garment_type": "Pants"})
        replaced = build_context(snapshot([base, current]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertEqual([(item["polarity"], item["values"]) for item in replaced["bindings"]], [("prefer", ["Black"])])
        self.assertIn({"source_id": "base-avoid", "reason": "short_term_override"}, replaced["overridden"])

        today_prefer = memory("today-prefer", request_id="r1", scope="short_term", feature="color", values=["Black"], selector={"garment_type": "Pants"})
        today_avoid = memory("today-avoid", request_id="r1", scope="short_term", feature="color", values=["Black"], polarity="avoid", selector={"garment_type": "Pants"})
        conflict = build_context(snapshot([today_prefer, today_avoid]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertFalse(conflict["bindings"])
        self.assertEqual(conflict["questions"][0]["reason"], "same_priority_conflict")

    def test_target_scoped_fact_does_not_activate_condition_on_another_target(self):
        pants_goal = memory(
            "pants-goal", request_id="r1", scope="short_term", feature="goal",
            values=["business casual"], selector={"slot_id": "pants-1"},
        )
        shirt_goal = memory(
            "shirt-goal", request_id="r1", scope="short_term", feature="goal",
            values=["formal"], selector={"slot_id": "shirt-1"},
        )
        shirt_style = memory(
            "shirt-style", request_id="r1", scope="short_term", feature="style",
            values=["Classic"], selector={"slot_id": "shirt-1"},
            conditions={"goal": "business casual"},
        )
        context = build_context(
            snapshot([pants_goal, shirt_goal, shirt_style]),
            [{"id": "pants-1", "garment_type": "Pants"}, {"id": "shirt-1", "garment_type": "Shirt"}],
        )
        self.assertEqual(context["facts_by_target"]["pants-1"]["goal"], "business casual")
        self.assertEqual(context["facts_by_target"]["shirt-1"]["goal"], "formal")
        self.assertNotIn("shirt-style", {source_id for binding in context["bindings"] for source_id in binding["source_ids"]})
        self.assertIn({"source_id": "shirt-style", "reason": "condition_mismatch"}, context["excluded"])

    def test_same_target_fact_conflict_is_unresolved_and_memory_order_does_not_choose(self):
        business = memory("business", request_id="r1", scope="short_term", feature="goal", values=["business casual"], selector={"slot_id": "pants-1"})
        formal = memory("formal", request_id="r1", scope="short_term", feature="goal", values=["formal"], selector={"slot_id": "pants-1"})
        targets = [{"id": "pants-1", "garment_type": "Pants"}]
        first = build_context(snapshot([business, formal]), targets)
        reordered = build_context(snapshot([formal, business]), targets)
        self.assertNotIn("goal", first["facts_by_target"]["pants-1"])
        self.assertNotIn("goal", reordered["facts_by_target"]["pants-1"])
        self.assertEqual(first["questions"][0]["reason"], "same_priority_fact_conflict")
        self.assertEqual(first["questions"], reordered["questions"])
        self.assertEqual(first["context_hash"], reordered["context_hash"])

    def test_long_global_fact_and_current_scoped_fact_use_scope_priority_not_input_order(self):
        long_goal = memory("long-goal", feature="goal", values=["formal"])
        current_goal = memory("current-goal", request_id="r1", scope="short_term", feature="goal", values=["business casual"], selector={"slot_id": "pants-1"})
        targets = [{"id": "pants-1", "garment_type": "Pants"}]
        first = build_context(snapshot([long_goal, current_goal]), targets)
        reordered = build_context(snapshot([current_goal, long_goal]), targets)
        self.assertEqual(first["facts_by_target"]["pants-1"]["goal"], "business casual")
        self.assertEqual(first["facts_by_target"], reordered["facts_by_target"])

    def test_avoid_situation_memory_is_not_promoted_to_a_positive_fact(self):
        avoid = memory("avoid-goal", feature="goal", values=["formal"], polarity="avoid")
        context = build_context(snapshot([avoid]), [{"id": "pants-1", "garment_type": "Pants"}])
        self.assertNotIn("goal", context["facts"])
        self.assertTrue(any(item["source_id"] == "avoid-goal" and item["reason"] == "fact_avoid_unsupported" for item in context["excluded"]))


if __name__ == "__main__":
    unittest.main()
