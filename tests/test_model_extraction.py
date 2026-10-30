"""Synthetic wire/authority regressions, not Korean semantic quality tests."""
from copy import deepcopy
import json
import subprocess
import unittest
from unittest.mock import patch

from stylemate_memory.codex_llm import CodexGateway
from stylemate_memory.contracts import ExtractedCandidate, V1_REGISTRY_VERSION
from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import OpenAIResponsesGateway, create_model_gateway
from stylemate_memory.model_io import FakeModelGateway, extraction_schema_v1, proposal_schema_v1
from stylemate_memory.registry import load_registry


def inputs():
    return {
        "sources": [{"source_id": "s1", "kind": "user_text",
                     "content": "출근할 때 와이드 바지, 허리가 들뜨지 않았으면 좋겠어요.",
                     "selector": {"garment_type": "Pants", "slot_id": "pants-1"}}],
        "targets": [{"target_id": "pants-1", "garment_type": "Pants"}],
        "registry": load_registry(V1_REGISTRY_VERSION).describe(),
    }


def candidate():
    return {
        "candidate_key": "c1", "content": "허리가 들뜨지 않는 바지를 선호함",
        "kind": "preference", "fact": None,
        "selector": {"garment_type": "Pants", "slot_id": "pants-1"},
        "conditions": {"occasion": "출근", "activity": None, "goal": None},
        "condition_quotes": {"occasion": "출근할 때", "activity": None, "goal": None},
        "polarity": "prefer", "strength": "soft", "origin_hint": "explicit",
        "scope_hint": "current", "source_ids": ["s1"],
        "quote": "허리가 들뜨지 않았으면 좋겠어요.", "bindings": [],
    }


def binding():
    return {"domain": "PI", "feature": "Fit", "values": ["Wide"], "match": "any",
            "polarity": "prefer", "strength": "soft"}


def extraction(value=None):
    return {"candidates": [candidate() if value is None else value], "questions": []}


def proposal():
    return {"suggestions": [{"target_id": "pants-1", "binding": binding(), "source_ids": ["s1"],
                             "reason": "현재 발화의 와이드 바지 표현을 soft 후보로 제안함"}], "questions": []}


class ReplyTransport:
    def __init__(self, value, *, error=None):
        self.value, self.error, self.calls = value, error, []

    def __call__(self, url, headers, payload, timeout):
        self.calls.append((url, headers, deepcopy(payload), timeout))
        if self.error:
            raise self.error
        return {"status": "completed", "output": [{"type": "reasoning", "summary": []},
            {"type": "message", "role": "assistant", "status": "completed", "content": [
                {"type": "output_text", "text": json.dumps(self.value, ensure_ascii=False)}]}]}


class ExtractionTests(unittest.TestCase):
    def extract(self, result, data=None):
        transport = ReplyTransport(result)
        gateway = OpenAIResponsesGateway(api_key="dummy-c1-key", transport=transport)
        return gateway.extract(inputs() if data is None else data), transport

    def assert_rejected(self, result, data=None):
        with self.assertRaises(StyleMateError) as caught:
            self.extract(result, data)
        self.assertEqual(caught.exception.code, "invalid_extraction")
        return caught.exception

    def test_unmapped_content_and_condition_quotes_survive_without_authority(self):
        data, raw = inputs(), extraction()
        before = deepcopy((data, raw))
        result, transport = self.extract(raw, data)
        c = result["candidates"][0]
        self.assertEqual(c["bindings"], [])
        self.assertEqual(c["content"], candidate()["content"])
        self.assertEqual(c["conditions"], {"occasion": "출근"})
        self.assertEqual(c["condition_quotes"], {"occasion": "출근할 때"})
        self.assertEqual(c["scope_hint"], "current")
        self.assertNotIn("confirmed", c)
        self.assertEqual((data, raw), before)
        request = transport.calls[0][2]
        self.assertFalse(request["store"])
        self.assertTrue(request["text"]["format"]["strict"])
        self.assertEqual(set(request["text"]["format"]["schema"]["properties"]), {"candidates", "questions"})

    def test_dictionary_projection_cannot_forward_private_metadata(self):
        data = inputs()
        data["registry"]["user_id"] = "private-user-marker"
        data["registry"]["raw_db"] = {"token": "private-db-marker"}
        data["registry"]["product_information"]["Fit"]["values"].append("private-value-marker")
        result, transport = self.extract(extraction(), data)
        sent = json.loads(transport.calls[0][2]["input"])
        encoded = json.dumps(sent, ensure_ascii=False)
        for private in ("private-user-marker", "private-db-marker", "private-value-marker", "source_refs", "retention_until"):
            self.assertNotIn(private, encoded)
        self.assertEqual(set(sent), {"sources", "targets", "registry"})
        self.assertNotIn("source", sent["registry"])
        self.assertEqual(sent["registry"]["version"], V1_REGISTRY_VERSION)
        self.assertIn("Wide", sent["registry"]["product_information"]["Fit"]["values"])
        self.assertEqual(result["candidates"][0]["source_ids"], ["s1"])

    def test_false_quote_wrong_source_and_normalized_conditions_are_rejected(self):
        cases = []
        for quote in ("없는 발화", "", None):
            c = candidate()
            c["quote"] = quote
            cases.append(c)
        for changes in ({"conditions": {"occasion": "office"}},
                        {"condition_quotes": {"occasion": "회사에 가면"}},
                        {"condition_quotes": {}}, {"source_ids": ["invented-source"]},
                        {"source_ids": ["s1", "s1"]}):
            c = candidate()
            c.update(changes)
            cases.append(c)
        for c in cases:
            with self.subTest(candidate=c):
                self.assert_rejected(extraction(c))
        data = inputs()
        data["sources"].append({**deepcopy(data["sources"][0]), "source_id": "s2", "content": "다른 근거의 문장"})
        c = candidate()
        c["quote"] = "다른 근거의 문장"
        self.assert_rejected(extraction(c), data)

    def test_unknown_authority_and_write_fields_are_rejected_at_each_boundary(self):
        for field, value in (("confirmed", True), ("consent", True), ("user_id", "made-up-owner"),
                             ("scope", "long_term"), ("op", "create"), ("version", 1), ("status", "active")):
            with self.subTest(field=field):
                c = candidate()
                c[field] = value
                self.assert_rejected(extraction(c))
        for path in ("root", "selector", "conditions", "binding"):
            raw = extraction()
            c = raw["candidates"][0]
            if path == "root":
                raw["commands"] = [{"op": "create_long_term"}]
            elif path == "binding":
                c["bindings"] = [{**binding(), "confirmed": True}]
            else:
                c[path]["consent"] = "yes"
            with self.subTest(path=path):
                self.assert_rejected(raw)

    def test_image_selection_reason_is_only_an_unconfirmed_soft_hypothesis(self):
        data = inputs()
        data["sources"][0].update({"kind": "image_selection", "content": "제시된 카드 A를 선택함"})
        c = candidate()
        c.update({"content": "와이드 핏 때문에 선택했을 가능성 (미확인)", "origin_hint": "inferred",
                  "quote": None, "conditions": {}, "condition_quotes": {}, "bindings": [binding()]})
        result, _ = self.extract({"candidates": [c], "questions": ["와이드 핏 때문에 고르셨나요?"]}, data)
        self.assertEqual(result["candidates"][0]["origin_hint"], "inferred")
        for changes in ({"origin_hint": "explicit"}, {"quote": "제시된 카드 A를 선택함"},
                        {"strength": "hard"}, {"polarity": "avoid"}, {"kind": "requirement"},
                        {"polarity": "indifferent"}):
            bad = {**c, **changes}
            with self.subTest(changes=changes):
                self.assert_rejected(extraction(bad), data)

    def test_explicit_reason_can_cite_text_together_with_selection(self):
        data = inputs()
        data["sources"].append({"source_id": "selected", "kind": "image_selection",
            "content": "카드 A 선택", "selector": {"garment_type": "Pants", "slot_id": "pants-1"}})
        c = candidate()
        c["source_ids"] = ["s1", "selected"]
        self.assertEqual(self.extract(extraction(c), data)[0]["candidates"][0]["origin_hint"], "explicit")

    def test_targets_are_isolated_and_unsupported_garments_can_remain_unmapped(self):
        data = inputs()
        data["targets"].append({"target_id": "pants-2", "garment_type": "Pants"})
        c = candidate()
        c["selector"]["slot_id"] = "pants-2"
        self.assert_rejected(extraction(c), data)
        c["selector"] = {"garment_type": None, "slot_id": None}
        self.assert_rejected(extraction(c), data)
        data["targets"] = [{"target_id": "skirt-1", "garment_type": "Skirt"}]
        data["sources"][0]["selector"] = {"garment_type": "Skirt", "slot_id": "skirt-1"}
        c["selector"] = deepcopy(data["sources"][0]["selector"])
        self.assertEqual(self.extract(extraction(c), data)[0]["candidates"][0]["bindings"], [])
        c["bindings"] = [binding()]
        self.assert_rejected(extraction(c), data)

    def test_registry_values_and_direction_are_checked_without_forcing_mapping(self):
        c = candidate()
        c.update({"quote": "와이드 바지", "bindings": [binding()]})
        self.assertEqual(self.extract(extraction(c))[0]["candidates"][0]["bindings"], [binding()])
        for change in ({"values": ["Invented"]}, {"feature": "Brand", "values": ["1989STANDARD"]},
                       {"strength": "hard"}, {"polarity": "avoid"}, {"values": [True]}, {"match": "range"}):
            c["bindings"] = [{**binding(), **change}]
            with self.subTest(change=change):
                self.assert_rejected(extraction(c))
        c["bindings"] = [binding(), binding()]
        self.assert_rejected(extraction(c))

    def test_situation_fact_stays_separate_from_feature_bindings(self):
        c = candidate()
        c.update({"kind": "situation", "content": "출근 상황", "fact": {"key": "occasion", "value": "출근"},
                  "quote": "출근할 때", "conditions": {}, "condition_quotes": {}})
        self.assertEqual(self.extract(extraction(c))[0]["candidates"][0]["fact"], c["fact"])
        for fact in ({"key": "occasion", "value": "결혼식"}, {"key": "occasion", "value": "출근", "confirmed": True}):
            self.assert_rejected(extraction({**c, "fact": fact}))
        self.assert_rejected(extraction({**c, "bindings": [binding()]}))

    def test_fea_binding_and_explicit_indifference_keep_their_distinct_meanings(self):
        data, c = inputs(), candidate()
        data["sources"][0]["content"] = "착용감이 편한 바지가 좋아요."
        c.update({"content": "편한 착용감 선호", "quote": "착용감이 편한 바지가 좋아요.",
                  "conditions": {}, "condition_quotes": {}, "bindings": [{
                      "domain": "FEA", "category": "Functional", "subcategory": "Donning",
                      "tag": "Ease", "polarity": "prefer", "strength": "soft"}]})
        self.assertEqual(self.extract(extraction(c), data)[0]["candidates"][0]["bindings"], c["bindings"])
        data["sources"][0]["content"] = "핏은 상관없어요."
        c.update({"content": "핏은 상관없음", "quote": "핏은 상관없어요.", "polarity": "indifferent",
                  "bindings": [{**binding(), "values": None, "match": None, "polarity": "indifferent"}]})
        result = self.extract(extraction(c), data)[0]["candidates"][0]
        self.assertEqual(result["polarity"], "indifferent")
        self.assertIsNone(result["bindings"][0]["values"])

    def test_invalid_input_and_resource_limits_fail_before_any_model_call(self):
        mutations = [
            lambda d: d.update({"user_id": "private"}),
            lambda d: d["sources"][0].update({"version": 4}),
            lambda d: d["targets"][0].update({"raw_db": {}}),
            lambda d: d["sources"].append(deepcopy(d["sources"][0])),
            lambda d: d["sources"][0].update({"content": "가" * 4001}),
            lambda d: d["sources"][0].update({"kind": "image_selection", "content": "가" * 90000}),
            lambda d: d["sources"][0]["selector"].update({"slot_id": "unknown"}),
            lambda d: d["registry"].update({"unused": "x" * (256 * 1024)}),
        ]
        for mutate in mutations:
            data, transport = inputs(), ReplyTransport(extraction())
            mutate(data)
            with self.subTest(mutation=mutate), self.assertRaises(StyleMateError) as caught:
                OpenAIResponsesGateway(api_key="dummy-c1-key", transport=transport).extract(data)
            self.assertEqual(caught.exception.code, "invalid_input")
            self.assertEqual(transport.calls, [])
        for field in ("kind", "polarity", "strength", "origin_hint", "scope_hint"):
            c = candidate()
            c[field] = []
            self.assert_rejected(extraction(c))
        self.assert_rejected({"candidates": [candidate()] * 17, "questions": []})
        self.assert_rejected({"candidates": [], "questions": ["질문"] * 4})
        self.assert_rejected({"candidates": [candidate(), candidate()], "questions": []})

    def test_provider_failure_is_an_interpretation_error_and_does_not_change_sources(self):
        data = inputs()
        before = deepcopy(data)
        transport = ReplyTransport(None, error=TimeoutError("dummy-c1-key provider body"))
        with self.assertRaises(StyleMateError) as caught:
            OpenAIResponsesGateway(api_key="dummy-c1-key", transport=transport).extract(data)
        self.assertEqual(caught.exception.code, "provider_timeout")
        self.assertEqual(set(caught.exception.as_dict()), {"code", "message"})
        self.assertNotIn("dummy-c1-key", str(caught.exception))
        self.assertEqual(data, before)

    def test_fake_and_codex_share_v1_validation_without_cli_dependency_for_api(self):
        with patch("shutil.which", side_effect=AssertionError("CLI lookup")):
            self.assertEqual(create_model_gateway().extract(inputs()), {"candidates": [], "questions": []})
            self.extract(extraction())
        raw = extraction()
        events = [
            {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(raw)}},
            {"type": "turn.completed", "usage": {"input_tokens": 5, "private": "provider-body-marker"}},
        ]
        runner = lambda *a, **kw: subprocess.CompletedProcess([], 0, "\n".join(map(json.dumps, events)), "")
        gateway = CodexGateway(executable="fake-codex", runner=runner)
        self.assertEqual(gateway.extract(inputs())["candidates"][0]["conditions"], {"occasion": "출근"})
        self.assertEqual(gateway.last_metadata["usage"], {"input_tokens": 5})
        self.assertNotIn("provider-body-marker", json.dumps(gateway.last_metadata))

    def test_strict_wire_schema_requires_all_object_fields_including_nullable_conditions(self):
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    self.assertEqual(set(node["required"]), set(node["properties"]))
                    self.assertFalse(node["additionalProperties"])
                for child in node.values():
                    check(child)
            elif isinstance(node, list):
                for child in node:
                    check(child)
        for schema in (extraction_schema_v1(), proposal_schema_v1()):
            check(schema)
        self.assertEqual(set(extraction_schema_v1()["properties"]["candidates"]["items"]["properties"]),
                         set(ExtractedCandidate.__required_keys__))


class ProposalTests(unittest.TestCase):
    def inputs(self):
        return {**inputs(), "constraints": []}

    def test_soft_proposal_uses_same_gateway_and_preserves_direct_constraints(self):
        data = self.inputs()
        hard = {**binding(), "strength": "hard", "polarity": "require"}
        data["constraints"] = [{"id": "direct1", "target_id": "pants-1", "binding": hard,
            "selector": {"garment_type": "Pants", "slot_id": "pants-1"}, "conditions": {}, "source_ids": ["s1"]}]
        before, transport = deepcopy(data), ReplyTransport(proposal())
        gateway = OpenAIResponsesGateway(api_key="dummy-c1-key", transport=transport)
        self.assertEqual(gateway.propose(data), proposal())
        self.assertEqual(json.loads(transport.calls[0][2]["input"])["constraints"], data["constraints"])
        self.assertEqual(data, before)
        self.assertEqual(create_model_gateway().propose(data), {"suggestions": [], "questions": []})

    def test_proposal_rejects_hard_states_unknown_sources_targets_and_cross_target_evidence(self):
        data = self.inputs()
        data["targets"].append({"target_id": "pants-2", "garment_type": "Pants"})
        for changes in ({"source_ids": ["invented"]}, {"target_id": "unknown"}, {"target_id": "pants-2"},
                        {"confirmed": True}, {"binding": {**binding(), "strength": "hard"}},
                        {"binding": {**binding(), "present": True}}):
            raw = proposal()
            raw["suggestions"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(StyleMateError) as caught:
                FakeModelGateway(raw).propose(data)
            self.assertEqual(caught.exception.code, "invalid_output")

    def test_proposal_schema_and_runtime_never_generate_hard_or_indifference_authority(self):
        branches = proposal_schema_v1()["properties"]["suggestions"]["items"]["properties"]["binding"]["anyOf"]
        for branch in branches:
            self.assertEqual(branch["properties"]["strength"]["enum"], ["soft"])
            self.assertNotIn("indifferent", branch["properties"]["polarity"]["enum"])
        self.assertEqual(branches[0]["properties"]["match"]["enum"], ["any", "all"])
        raw = proposal()
        raw["suggestions"][0]["binding"].update({"polarity": "indifferent", "values": None, "match": None})
        with self.assertRaises(StyleMateError) as caught:
            FakeModelGateway(raw).propose(self.inputs())
        self.assertEqual(caught.exception.code, "invalid_output")


if __name__ == "__main__":
    unittest.main()
