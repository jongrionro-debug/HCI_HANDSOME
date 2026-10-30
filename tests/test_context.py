import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest

from stylemate_memory import contracts as c
from stylemate_memory.context import build_context, build_context_v1
from stylemate_memory.errors import StyleMateError
from stylemate_memory.model_io import FakeModelGateway
from stylemate_memory.registry import load_registry
from stylemate_memory.store import MemoryStore


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


class V1Fixture:
    """Synthetic snapshots, including separate content/binding proofs."""

    def __init__(self, targets=None):
        self.targets = targets or [{"target_id": "pants-1", "garment_type": "Pants"}]
        self.data = {key: [] for key in ("memories", "evidence", "bindings", "confirmations", "consents",
                                        "links", "feedback", "interpretations", "rounds", "candidate_sets", "questions")}
        self.data.update({"contract_version": c.CONTRACT_VERSION, "registry_version": c.V1_REGISTRY_VERSION,
                          "now": "2026-10-29T12:00:00+00:00", "profile_revision": 7,
                          "request": {"id": "private-request", "user_id": "private-user", "revision": 3,
                                      "contract_version": c.CONTRACT_VERSION, "registry_version": c.V1_REGISTRY_VERSION,
                                      "timezone": "UTC", "status": "open", "mode": "shopping",
                                      "targets": deepcopy(self.targets), "final_selection": None,
                                      "created_at": "2026-10-29T09:00:00+00:00", "updated_at": "2026-10-29T09:00:00+00:00",
                                      "retention_until": "2026-11-05T12:00:00+00:00", "max_until": "2026-11-12T12:00:00+00:00"}})

    def meta(self, identifier, request_id=None):
        return {"id": identifier, "user_id": "private-user", "request_id": request_id,
                "version": 1, "contract_version": c.CONTRACT_VERSION,
                "created_at": "2026-10-29T09:00:00+00:00", "retention_until": "2026-11-04T12:00:00+00:00"}

    @staticmethod
    def ref(kind, obj):
        return {"type": kind, "id": obj["id"], "version": obj["version"]}

    def add(self, identifier, text="빈티지한 느낌", *, scope="long_term", confirmed=True, origin="explicit",
            selector=None, conditions=None, fact=None, strength="soft", polarity="prefer", family=None):
        request_id = "private-request" if scope == "short_term" else None
        m = self.meta(identifier, request_id) | {
            "kind": "situation" if fact else "preference", "content": text, "fact": deepcopy(fact),
            "scope": scope, "selector": selector or {"garment_type": "Pants", "slot_id": None},
            "conditions": conditions or {}, "polarity": polarity, "strength": strength,
            "valid_from": None, "valid_until": None, "origin": origin, "confirmed": confirmed,
            "status": "active" if confirmed else "candidate", "family_id": family or "family-" + identifier,
            "source_refs": [], "confirmation_ref": None, "consent_ref": None,
        }
        meaning = {key: deepcopy(m[key]) for key in c.MemoryMeaning.__required_keys__}
        evidence = self.meta("e-" + identifier, request_id) | {
            "kind": "consent_snapshot" if scope == "long_term" else "user_text", "quote": text,
            "context": None, "selector": deepcopy(m["selector"]), "selection": None, "display_ref": None,
            "snapshot": deepcopy(meaning) if scope == "long_term" else None,
        }
        m["source_refs"] = [self.ref("evidence", evidence)]
        self.data["evidence"].append(evidence)
        if confirmed:
            review = {"meaning": deepcopy(meaning), "bindings": [], "subject_refs": [self.ref("memory", m)]}
            confirmation = self.meta("cf-" + identifier, request_id) | {
                "memory_id": identifier, "snapshot": review, "source_refs": deepcopy(m["source_refs"]),
                "event_ref": {"type": "event", "id": "event-" + identifier, "version": 1},
                "confirmed_at": "2026-10-29T10:00:00+00:00",
            }
            self.data["confirmations"].append(confirmation)
            m["confirmation_ref"] = self.ref("confirmation", confirmation)
            if scope == "long_term":
                consent = self.meta("cs-" + identifier) | {
                    "memory_id": identifier, "purpose": "future_reuse", "snapshot": deepcopy(review),
                    "source_refs": deepcopy(m["source_refs"]), "event_ref": confirmation["event_ref"].copy(),
                    "consented_at": "2026-10-29T10:00:00+00:00", "status": "active",
                }
                self.data["consents"].append(consent)
                m["consent_ref"] = self.ref("consent", consent)
        self.data["memories"].append(m)
        return m

    def bind(self, m, value="Slim", *, feature="Fit", confirmed=True, origin="explicit", strength=None, spec=None):
        spec = spec or {"domain": "PI", "feature": feature, "values": [value], "match": "any",
                        "polarity": m["polarity"], "strength": strength or m["strength"]}
        b = self.meta("b-" + m["id"] + "-" + str(len(self.data["bindings"])), m["request_id"]) | deepcopy(spec) | {
            "subject": "user_target", "memory_id": m["id"], "registry_version": c.V1_REGISTRY_VERSION,
            "origin": origin, "confirmed": confirmed, "status": "active" if confirmed else "candidate",
            "source_refs": deepcopy(m["source_refs"]), "confirmation_ref": None,
        }
        if confirmed:
            cf = self.meta("cf-" + b["id"], m["request_id"]) | {
                "memory_id": m["id"], "source_refs": deepcopy(m["source_refs"]),
                "event_ref": {"type": "event", "id": "event-" + b["id"], "version": 1},
                "confirmed_at": "2026-10-29T10:00:00+00:00",
                "snapshot": {"meaning": {k: deepcopy(m[k]) for k in c.MemoryMeaning.__required_keys__},
                             "bindings": [deepcopy(spec)], "subject_refs": [self.ref("binding", b)]},
            }
            b["confirmation_ref"] = self.ref("confirmation", cf)
            self.data["confirmations"].append(cf)
        self.data["bindings"].append(b)
        return b


class FakeSemantic:
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []

    def search(self, query, eligible_refs, *, index_version):
        self.calls.append((query, deepcopy(eligible_refs), index_version))
        if self.error:
            raise self.error
        return deepcopy(self.reply) if self.reply is not None else list(reversed(eligible_refs))


class V1ContextTests(unittest.TestCase):
    def setUp(self):
        self.fixture = V1Fixture()
        self.registry = load_registry(c.V1_REGISTRY_VERSION)

    def build(self, **kwargs):
        return build_context_v1(self.fixture.data, self.fixture.targets, registry=self.registry, **kwargs)

    def text(self, context):
        return "\n".join(source["content"] for source in context["model_input"]["sources"])

    def ids(self, context):
        return {ref["id"] for bundle in context["source_refs"].values() for ref in bundle if ref["type"] == "memory"}

    def test_free_expression_and_private_bundle_fit_fixed_model_contract(self):
        m = self.fixture.add("private-memory", origin="inferred", conditions={})
        before = deepcopy(self.fixture.data)
        result = self.build()
        self.assertEqual(set(result), c.MemoryContext.__required_keys__)
        self.assertEqual(result["retrieval_status"], "complete")
        self.assertFalse(result["blocked"])
        self.assertIn("빈티지한 느낌", self.text(result))
        self.assertIn("원출처=inferred", self.text(result))
        self.assertEqual(result["constraints"], [])
        bundle = next(iter(result["source_refs"].values()))
        self.assertTrue({"memory", "evidence", "confirmation", "consent"} <= {r["type"] for r in bundle})
        self.assertIn(V1Fixture.ref("memory", m), bundle)
        model_json = json.dumps(result["model_input"], ensure_ascii=False)
        for private in ("private-user", "private-request", "private-memory", "cf-private-memory", "future_reuse"):
            self.assertNotIn(private, model_json)
        self.assertEqual(FakeModelGateway().propose(result["model_input"]), {"suggestions": [], "questions": []})
        self.assertEqual(self.fixture.data, before)
        self.assertEqual(self.build(), result)

    def test_current_exception_overrides_only_conflicting_long_binding(self):
        base = self.fixture.add("usual-fit", "평소 넉넉한 바지")
        self.fixture.bind(base, "Wide")
        color = self.fixture.add("usual-color", "남색 선호")
        self.fixture.bind(color, "Navy", feature="Color")
        current = self.fixture.add("today-fit", "이번에는 슬림", scope="short_term", strength="hard")
        self.fixture.bind(current, "Slim")
        before = deepcopy(self.fixture.data)
        result = self.build(char_budget=16000)
        self.assertFalse(result["blocked"])
        self.assertEqual({(x["binding"]["feature"], tuple(x["binding"]["values"])) for x in result["constraints"]},
                         {("Fit", ("Slim",)), ("Color", ("Navy",))})
        self.assertIn("이번 요청 예외", self.text(result))
        self.assertTrue({"usual-fit", "today-fit"} <= self.ids(result))
        self.assertEqual(self.fixture.data, before)

    def test_same_priority_conflict_is_a_question_even_when_one_is_newer(self):
        left = self.fixture.add("left", "슬림", scope="short_term")
        right = self.fixture.add("right", "와이드", scope="short_term")
        right["created_at"] = "2026-10-29T11:00:00+00:00"
        self.fixture.bind(left, "Slim")
        self.fixture.bind(right, "Wide")
        result = self.build(char_budget=16000)
        self.assertEqual(result["constraints"], [])
        self.assertTrue(result["blocked"])
        self.assertTrue(any("same_priority_conflict" in q for q in result["questions"]))
        self.assertEqual(self.ids(result), {"left", "right"})

    def test_target_local_confirmed_facts_gate_conditions_and_hypotheses_do_not(self):
        self.fixture = V1Fixture([{"target_id": "pants-1", "garment_type": "Pants"},
                                  {"target_id": "pants-2", "garment_type": "Pants"}])
        self.fixture.add("occasion", "첫 바지는 발표용", scope="short_term", fact={"key": "occasion", "value": "발표"},
                         selector={"garment_type": "Pants", "slot_id": "pants-1"})
        self.fixture.add("conditional", "발표 때 빈티지", conditions={"occasion": "발표"})
        self.fixture.add("guess", "산책할 듯함", scope="short_term", confirmed=False, origin="inferred",
                         fact={"key": "activity", "value": "산책"})
        self.fixture.add("not-grounded", "산책에는 편한 옷", conditions={"activity": "산책"})
        result = self.build(char_budget=16000)
        conditional_sources = [s for s in result["model_input"]["sources"] if "발표 때 빈티지" in s["content"]]
        self.assertEqual([s["selector"]["slot_id"] for s in conditional_sources], ["pants-1"])
        self.assertNotIn("not-grounded", self.ids(result))
        self.assertNotIn("산책할 듯함", self.text(result))
        self.assertTrue(any("unconfirmed_hypothesis" in q for q in result["questions"]))
        self.assertEqual(sum("unconfirmed_hypothesis" in q for q in result["questions"]), 2)
        conditional_bundle = result["source_refs"][conditional_sources[0]["source_id"]]
        self.assertIn("occasion", {r["id"] for r in conditional_bundle})

    def test_fact_conflicts_do_not_satisfy_conditional_memory(self):
        self.fixture.add("fact-a", "발표", scope="short_term", fact={"key": "occasion", "value": "발표"})
        self.fixture.add("fact-b", "여행", scope="short_term", fact={"key": "occasion", "value": "여행"})
        self.fixture.add("conditional", "발표 때만", conditions={"occasion": "발표"})
        result = self.build(char_budget=16000)
        self.assertNotIn("conditional", self.ids(result))
        self.assertTrue(result["blocked"])
        self.assertTrue(any("same_priority_fact_conflict" in q for q in result["questions"]))

    def test_content_confirmation_does_not_confirm_binding_or_make_hard(self):
        m = self.fixture.add("free", "빈티지한 느낌")
        b = self.fixture.bind(m, "Brown", feature="Color", confirmed=False, origin="inferred")
        result = self.build()
        self.assertEqual(result["constraints"], [])
        self.assertIn("미확인 soft 매핑", self.text(result))
        self.assertIn(V1Fixture.ref("binding", b), next(iter(result["source_refs"].values())))
        hard = self.fixture.add("hard", "따뜻해야 함", scope="short_term", strength="hard")
        self.fixture.bind(hard, "Wool", feature="Fabric", confirmed=False, origin="inferred", strength="soft")
        result = self.build(char_budget=16000)
        self.assertTrue(result["blocked"])
        self.assertTrue(any("unmapped_hard_requirement" in q for q in result["questions"]))
        self.assertFalse(any(x["binding"]["strength"] == "hard" for x in result["constraints"]))

    def test_confirmation_proof_must_cover_exact_binding_and_meaning(self):
        m = self.fixture.add("mapped", "슬림")
        b = self.fixture.bind(m)
        original = deepcopy(self.fixture.data)
        for change in ("binding-version", "binding-value", "meaning"):
            with self.subTest(change=change):
                self.fixture.data = deepcopy(original)
                proof = self.fixture.data["confirmations"][-1]
                if change == "binding-version":
                    proof["snapshot"]["subject_refs"][0]["version"] += 1
                elif change == "binding-value":
                    proof["snapshot"]["bindings"][0]["values"] = ["Wide"]
                else:
                    proof["snapshot"]["meaning"]["conditions"] = {"occasion": "발표"}
                result = self.build()
                self.assertTrue(result["blocked"])
                self.assertFalse(result["constraints"])
        self.fixture.data = original
        result = self.build()
        self.assertEqual(result["constraints"][0]["binding_ref"], V1Fixture.ref("binding", b))

    def test_binding_confirmation_transition_keeps_displayed_previous_version(self):
        m = self.fixture.add("confirmed", scope="short_term")
        b = self.fixture.bind(m, origin="inferred")
        b["version"] = 2  # v1 was displayed; confirmation changed only authority state
        result = self.build()
        self.assertFalse(result["blocked"])
        self.assertEqual(result["constraints"][0]["origin"], "inferred")
        self.assertEqual(result["constraints"][0]["binding_ref"]["version"], 2)
        self.fixture.data["confirmations"][-1]["snapshot"]["subject_refs"] = [V1Fixture.ref("memory", m)]
        result = self.build()
        self.assertTrue(result["blocked"])
        self.assertFalse(result["constraints"])

    def test_owner_state_scope_consent_and_half_open_validity_filter_before_search(self):
        keep = self.fixture.add("keep")
        for identifier in ("foreign", "other-request", "withdrawn", "expired", "future", "wrong-target", "conditional", "no-consent"):
            m = self.fixture.add(identifier, scope="short_term" if identifier == "other-request" else "long_term")
            if identifier == "foreign":
                m["user_id"] = "other-private-user"
            elif identifier == "other-request":
                m["request_id"] = "other-private-request"
            elif identifier == "withdrawn":
                m["status"] = "withdrawn"
            elif identifier == "expired":
                m["valid_until"] = self.fixture.data["now"]
            elif identifier == "future":
                m["valid_from"] = "2026-10-30T12:00:00+00:00"
            elif identifier == "wrong-target":
                m["selector"]["garment_type"] = "Shirt"
            elif identifier == "conditional":
                m["conditions"] = {"occasion": "여행"}
            elif identifier == "no-consent":
                self.fixture.data["consents"][-1]["status"] = "withdrawn"
        semantic = FakeSemantic()
        result = self.build(semantic=semantic)
        self.assertEqual(semantic.calls[0][1], [V1Fixture.ref("memory", keep)])
        self.assertEqual(self.ids(result), {"keep"})
        self.assertNotIn("other-private", json.dumps(result, ensure_ascii=False))
        self.assertEqual(result["basis"]["valid_until"], "2026-10-30T12:00:00+00:00")

    def test_fake_semantic_cannot_bypass_permissions_hypothesis_or_scope(self):
        m = self.fixture.add("allowed", scope="short_term", strength="hard")
        self.fixture.bind(m)
        denied = self.fixture.add("denied", confirmed=False, scope="short_term", origin="inferred")
        reply = [V1Fixture.ref("memory", denied), {"type": "memory", "id": "foreign-private-id", "version": 1},
                 V1Fixture.ref("memory", m)]
        semantic = FakeSemantic(reply)
        result = self.build(semantic=semantic, char_budget=16000)
        self.assertEqual(semantic.calls[0][1], [V1Fixture.ref("memory", m)])
        self.assertEqual(len(result["constraints"]), 1)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["retrieval_status"], "partial")
        self.assertNotIn("foreign-private-id", json.dumps(result, ensure_ascii=False))
        self.assertTrue(any("semantic_ineligible_ref" in q for q in result["questions"]))

    def test_semantic_channel_failure_and_stale_index_are_explicit(self):
        m = self.fixture.add("keep")
        cases = [(FakeSemantic(error=RuntimeError("private provider body")), "semantic_unavailable"),
                 (FakeSemantic(error=StyleMateError("stale_context", "private index")), "semantic_stale_index"),
                 (FakeSemantic([V1Fixture.ref("memory", m) | {"version": 2}]), "semantic_stale_index")]
        for semantic, reason in cases:
            with self.subTest(reason=reason):
                result = self.build(semantic=semantic)
                self.assertTrue(result["blocked"])
                self.assertEqual(result["retrieval_status"], "partial")
                self.assertTrue(any(reason in q for q in result["questions"]))
                self.assertNotIn("private provider body", json.dumps(result))
                self.assertEqual(result["basis"]["index_version"], semantic.calls[0][2])

    def test_required_material_is_not_trimmed_when_budget_fails(self):
        m = self.fixture.add("hard", "울 소재가 반드시 필요", strength="hard")
        self.fixture.bind(m, "Wool", feature="Fabric")
        result = self.build(char_budget=256)
        self.assertTrue(result["blocked"])
        self.assertEqual(result["retrieval_status"], "partial")
        self.assertEqual(len(result["constraints"]), 1)
        self.assertIn(m["content"], self.text(result))
        self.assertTrue(any("context_budget_insufficient" in q for q in result["questions"]))

    def test_keyword_alias_finds_unmapped_expression_under_optional_budget(self):
        self.fixture.add("a-unrelated", "장식 없는 차분한 분위기")
        self.fixture.add("z-related", "복고풍 느낌")
        evidence = self.fixture.meta("query", "private-request") | {
            "kind": "user_text", "quote": "레트로한 팬츠를 찾아요", "context": None,
            "selector": {"garment_type": "Pants", "slot_id": None}, "selection": None,
            "display_ref": None, "snapshot": None,
        }
        self.fixture.data["evidence"].append(evidence)
        result = self.build(char_budget=900)
        self.assertIn("z-related", self.ids(result))
        self.assertNotIn("a-unrelated", self.ids(result))
        self.assertEqual(result["constraints"], [])
        self.assertEqual(result["retrieval_status"], "partial")

    def test_same_family_and_same_evidence_are_one_bundle_and_one_constraint(self):
        current = self.fixture.add("short", "슬림 바지", scope="short_term", family="promoted-family")
        long = self.fixture.add("long", "슬림 바지", family="promoted-family")
        self.fixture.bind(current)
        self.fixture.bind(long)
        result = self.build(char_budget=16000)
        self.assertEqual(len(result["model_input"]["sources"]), 1)
        self.assertEqual(len(result["constraints"]), 1)
        self.assertEqual(self.ids(result), {"short", "long"})
        self.fixture = V1Fixture()
        first = self.fixture.add("summary-one", "가벼운 느낌", scope="short_term")
        second = self.fixture.add("summary-two", "산뜻한 느낌", scope="short_term")
        second["source_refs"] = deepcopy(first["source_refs"])
        self.fixture.bind(first, "Slim")
        self.fixture.bind(second, "Navy", feature="Color")
        result = self.build(char_budget=16000)
        self.assertEqual(len(result["model_input"]["sources"]), 1)
        self.assertEqual(len(result["constraints"]), 2)
        self.assertEqual(self.ids(result), {"summary-one", "summary-two"})

    def test_shared_condition_is_not_a_duplicate_preference_origin(self):
        self.fixture.add("occasion", "발표", scope="short_term", fact={"key": "occasion", "value": "발표"})
        self.fixture.add("one", "차분한 느낌", conditions={"occasion": "발표"})
        self.fixture.add("two", "가벼운 느낌", conditions={"occasion": "발표"})
        result = self.build(char_budget=16000)
        self.assertEqual(len(result["model_input"]["sources"]), 3)

    def test_new_request_excludes_old_short_term_and_hypotheses(self):
        self.fixture.add("baseline")
        self.fixture.add("old-short", "오늘 요구", scope="short_term")
        self.fixture.add("old-guess", "선택 이유 추측", scope="short_term", confirmed=False, origin="inferred")
        self.fixture.data["request"]["id"] = "new-private-request"
        result = self.build()
        self.assertEqual(self.ids(result), {"baseline"})
        self.assertFalse(any("old-guess" in q for q in result["questions"]))
        self.assertFalse(result["blocked"])

    def test_fake_semantic_ranks_optional_memory_without_changing_authority(self):
        self.fixture.add("a-structural", "차분한 느낌")
        wanted = self.fixture.add("z-semantic", "색다른 분위기")
        semantic = FakeSemantic([V1Fixture.ref("memory", wanted)])
        result = self.build(semantic=semantic, char_budget=900)
        self.assertEqual(self.ids(result), {"z-semantic"})
        self.assertEqual(result["constraints"], [])
        self.assertFalse(result["blocked"])
        self.assertEqual(result["retrieval_status"], "partial")

    def test_missing_expired_and_wrong_version_source_never_become_facts(self):
        m = self.fixture.add("dependent", "발표", scope="short_term", fact={"key": "occasion", "value": "발표"})
        self.fixture.add("conditional", "발표 때만", conditions={"occasion": "발표"})
        original = deepcopy(self.fixture.data)
        for mode in ("missing", "expired", "wrong-version", "foreign"):
            with self.subTest(mode=mode):
                self.fixture.data = deepcopy(original)
                evidence = self.fixture.data["evidence"][0]
                if mode == "missing":
                    self.fixture.data["evidence"].pop(0)
                elif mode == "expired":
                    evidence["retention_until"] = self.fixture.data["now"]
                elif mode == "wrong-version":
                    evidence["version"] += 1
                else:
                    evidence["user_id"] = "foreign-private-user"
                result = self.build()
                self.assertTrue(result["blocked"])
                self.assertNotIn(m["id"], self.ids(result))
                self.assertNotIn("conditional", self.ids(result))
                self.assertNotIn("foreign-private-user", json.dumps(result))

    def test_actual_store_binding_confirmation_ref_is_resolved_after_version_increment(self):
        with tempfile.TemporaryDirectory() as directory:
            with MemoryStore(Path(directory) / "synthetic.sqlite3",
                             clock=lambda: datetime(2026, 10, 29, 12, tzinfo=timezone.utc)) as store:
                request = store.start_request("local-test", input_id="input", text=None, timezone="UTC",
                                              contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION,
                                              targets=self.fixture.targets)

                def snap():
                    return store.snapshot("local-test", request["id"], contract_version=c.CONTRACT_VERSION)

                def expected():
                    data = snap()
                    return {"request_revision": data["request"]["revision"], "profile_revision": data["profile_revision"],
                            "object_versions": [V1Fixture.ref("memory", m) for m in data["memories"]]
                                + [V1Fixture.ref("binding", b) for b in data["bindings"]]}

                def batch(identifier, actions):
                    return store.apply_batch("local-test", request["id"], batch_id=identifier, actions=actions,
                                             contract_version=c.CONTRACT_VERSION, expected=expected())

                source = batch("intake", [{"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
                                          "reaction": "text_only", "selections": [], "text": "슬림한 바지", "question_id": None}])["evidence_refs"][0]
                m = self.fixture.add("synthetic", "슬림한 바지", scope="short_term", confirmed=False)
                spec = {"domain": "PI", "feature": "Fit", "values": ["Slim"], "match": "any",
                        "polarity": "prefer", "strength": "soft"}
                batch("create", [{"op": "create", "memory": {k: m[k] for k in c.MemoryContent.__required_keys__},
                                  "source_refs": [source], "bindings": [spec],
                                  "confirmation_event_ref": None, "consent_event_ref": None}])
                data = snap()
                memory, binding = data["memories"][0], data["bindings"][0]
                context = build_context_v1(data, request["targets"], registry=self.registry)
                display = store.issue_display("local-test", request["id"], purpose="confirm_content", basis=context["basis"],
                    snapshot={"meaning": {k: memory[k] for k in c.MemoryMeaning.__required_keys__}, "bindings": [spec],
                              "subject_refs": [V1Fixture.ref("memory", memory), V1Fixture.ref("binding", binding)]})
                event = store.record_user_event("local-test", request["id"], command_id="accept",
                                               display_ref=V1Fixture.ref("display", display), purpose="confirm_content", expected=expected())
                batch("confirm", [{"op": "confirm", "memory_id": memory["id"], "expected_version": memory["version"],
                                   "binding_confirmations": [V1Fixture.ref("binding", binding)], "confirmation_event_ref": event}])
                data = snap()
                result = build_context_v1(data, request["targets"], registry=self.registry)
                self.assertEqual(result["constraints"][0]["binding_ref"], V1Fixture.ref("binding", data["bindings"][0]))
                self.assertEqual(result["constraints"][0]["origin"], "inferred")
                self.assertNotIn("binding_unavailable", result["questions"])

    def test_snapshot_order_is_irrelevant_and_index_freshness_tracks_proofs(self):
        self.fixture.add("one")
        self.fixture.add("two", "격식 있는 분위기")
        semantic = FakeSemantic()
        first = self.build(semantic=semantic, char_budget=16000)
        for key in ("memories", "evidence", "confirmations", "consents"):
            self.fixture.data[key].reverse()
        self.assertEqual(self.build(semantic=semantic, char_budget=16000), first)
        proof = self.fixture.data["consents"][0]
        proof["version"] += 1
        self.fixture.data["memories"][0]["consent_ref"]["version"] += 1
        revised = self.build(semantic=semantic, char_budget=16000)
        self.assertNotEqual(first["basis"]["index_version"], revised["basis"]["index_version"])
        self.assertNotEqual(first["context_id"], revised["context_id"])

    def test_missing_channel_empty_evidence_and_closed_request_are_not_success(self):
        empty = self.build()
        self.assertEqual(empty["retrieval_status"], "unavailable")
        self.assertTrue(empty["blocked"])
        self.fixture.add("memory")
        del self.fixture.data["evidence"]
        missing = self.build()
        self.assertEqual(missing["retrieval_status"], "unavailable")
        self.assertTrue(any("snapshot_incomplete" in q for q in missing["questions"]))
        self.fixture.data["request"]["status"] = "closed"
        with self.assertRaises(StyleMateError) as caught:
            self.build()
        self.assertEqual(caught.exception.code, "request_closed")

    def test_b1_sqlite_snapshot_candidate_stays_a_question_without_network(self):
        with tempfile.TemporaryDirectory() as directory:
            clock = lambda: datetime(2026, 10, 29, 12, tzinfo=timezone.utc)
            with MemoryStore(Path(directory) / "synthetic.sqlite3", clock=clock) as store:
                request = store.start_request("local-test", input_id="input", text="빈티지한 느낌", timezone="UTC",
                                              contract_version=c.CONTRACT_VERSION, registry_version=c.V1_REGISTRY_VERSION,
                                              targets=self.fixture.targets)
                snap = store.snapshot("local-test", request["id"], contract_version=c.CONTRACT_VERSION)
                store.apply_batch("local-test", request["id"], batch_id="input-text", contract_version=c.CONTRACT_VERSION,
                                  expected={"request_revision": snap["request"]["revision"], "profile_revision": snap["profile_revision"],
                                            "object_versions": []}, actions=[{
                                      "op": "submit_feedback", "round_id": None, "candidate_set_id": None,
                                      "reaction": "text_only", "selections": [], "text": "빈티지한 느낌", "question_id": None}])
                snap = store.snapshot("local-test", request["id"], contract_version=c.CONTRACT_VERSION)
                example = self.fixture.add("example", scope="short_term", confirmed=False)
                meaning = {k: deepcopy(example[k]) for k in c.MemoryContent.__required_keys__}
                store.apply_batch("local-test", request["id"], batch_id="candidate", contract_version=c.CONTRACT_VERSION,
                                  expected={"request_revision": snap["request"]["revision"], "profile_revision": snap["profile_revision"],
                                            "object_versions": []}, actions=[{
                                      "op": "create", "memory": meaning,
                                      "source_refs": [V1Fixture.ref("evidence", snap["evidence"][0])], "bindings": [],
                                      "confirmation_event_ref": None, "consent_event_ref": None}])
                snap = store.snapshot("local-test", request["id"], contract_version=c.CONTRACT_VERSION)
                result = build_context_v1(snap, request["targets"], registry=self.registry)
                self.assertTrue(result["blocked"])
                self.assertEqual(result["retrieval_status"], "unavailable")
                self.assertEqual(result["constraints"], [])
                self.assertTrue(any("unconfirmed_hypothesis" in q for q in result["questions"]))


if __name__ == "__main__":
    unittest.main()
