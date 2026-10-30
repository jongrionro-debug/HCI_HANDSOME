"""D4 evaluator regressions: detect bad results without changing product policy."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import socket
import tempfile
import unittest
from unittest.mock import patch

from scripts import evaluate_offline as evaluation
from stylemate_memory import contracts as c, retrieval
from stylemate_memory.registry import load_registry


class OfflineEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(c.V1_REGISTRY_VERSION)
        cls.memory_cases = evaluation.read_jsonl(evaluation.FIXTURES / "memory_cases.jsonl")
        cls.product_cases = json.loads((evaluation.FIXTURES / "product_cases.json").read_text(encoding="utf-8"))
        cls.records = evaluation.read_jsonl(evaluation.FIXTURES / "catalog_replacement.jsonl")
        cls.temporary_paths = []
        original_temporary = tempfile.TemporaryDirectory

        def owned_temporary(*args, **kwargs):
            temporary = original_temporary(*args, **kwargs)
            cls.temporary_paths.append(Path(temporary.name))
            return temporary

        with patch.object(evaluation.tempfile, "TemporaryDirectory", side_effect=owned_temporary), \
             patch.object(socket, "create_connection", side_effect=AssertionError("network is outside D4")):
            cls.report = evaluation.run_evaluation()

    def memory_case(self, identifier):
        return next(case for case in self.memory_cases if case["id"] == identifier)

    def product_case(self, identifier):
        return next(case for case in self.product_cases if case["id"] == identifier)

    def context(self, case):
        return retrieval.build_context_v1(deepcopy(case["snapshot"]), case["targets"],
                                          registry=self.registry, char_budget=case["char_budget"])

    def test_frozen_cases_pass_and_owned_runtime_files_are_removed(self):
        self.assertEqual(self.report["status"], "pass", self.report["failures"])
        self.assertEqual(len(self.report["memory_retrieval"]), 13 * 3)
        self.assertEqual(len(self.report["product_retrieval"]), 12)
        self.assertTrue(self.temporary_paths)
        self.assertTrue(all(not path.exists() for path in self.temporary_paths))
        self.assertEqual(len(self.report["fixture_sha256"]), 3)

    def test_same_inputs_and_explicit_channel_differences(self):
        rows = self.report["memory_retrieval"]
        for case in self.memory_cases:
            with self.subTest(case=case["id"]):
                variants = [row for row in rows if row["case"] == case["id"]]
                self.assertEqual({row["mode"] for row in variants}, set(evaluation.MODES))
                self.assertEqual({row["input_sha256"] for row in variants}, {evaluation.digest(
                    {key: case[key] for key in ("snapshot", "targets", "char_budget")})})
        recall = lambda identifier: {row["mode"]: row["metrics"]["recall"] for row in rows if row["case"] == identifier}
        self.assertEqual(list(recall("keyword_alias").values()), [0.0, 1.0, 1.0])
        self.assertEqual(list(recall("scripted_paraphrase").values()), [0.0, 0.0, 1.0])
        for row in rows:
            calls = row["instrumentation"]["calls"]
            self.assertEqual(calls.get("fake_semantic", 0), int(row["mode"] == evaluation.MODES[2]))
            self.assertEqual(calls.get("fake_transport", 0), int(not row["metrics"]["blocked"]))

    def test_blocking_does_not_drop_hard_conditions_or_call_model(self):
        rows = [row for row in self.report["memory_retrieval"] if row["case"] == "mandatory_budget_overflow"]
        for row in rows:
            self.assertTrue(row["metrics"]["blocked"])
            self.assertEqual(row["metrics"]["mandatory_memory_preservation"], 1.0)
            self.assertEqual(row["metrics"]["hard_condition_preservation"], 1.0)
            self.assertEqual(row["metrics"]["bundle_completeness"], 1.0)
            self.assertNotIn("target_generation", row["instrumentation"]["calls"])

    def test_scoring_detects_missing_proof_and_dropped_mandatory_binding(self):
        case = self.memory_case("unmapped_expression_snapshot_replay")
        context = self.context(case)
        alias = context["model_input"]["sources"][0]["source_id"]
        context["source_refs"][alias] = [ref for ref in context["source_refs"][alias] if ref["type"] != "evidence"]
        metrics = evaluation.memory_metrics(case, context)
        self.assertFalse(metrics["checks"]["complete_evidence_bundles"])
        self.assertGreater(metrics["missing_bundle_ref_count"], 0)
        case = self.memory_case("mandatory_budget_overflow")
        context = self.context(case)
        context["constraints"] = []
        metrics = evaluation.memory_metrics(case, context)
        self.assertLess(metrics["hard_condition_preservation"], 1.0)
        self.assertFalse(metrics["checks"]["exact_direct_constraints"])

    def test_scoring_detects_scope_leak_and_false_positive(self):
        case = self.memory_case("selection_reason_stays_hypothesis")
        context = self.context(case)
        alias = context["model_input"]["sources"][0]["source_id"]
        context["source_refs"][alias].append({"type": "memory", "id": "selection-guess", "version": 1})
        metrics = evaluation.memory_metrics(case, context)
        self.assertEqual(metrics["false_positive_count"], 1)
        self.assertFalse(metrics["checks"]["excluded_memories_absent"])

    def test_product_oracle_detects_unknown_accepted_as_hard(self):
        case = self.product_case("hard_navy_soft_straight")
        results = [{"target_id": "pants", "status": "results", "hits": [{"product_id": "alt-unknown"}]}]
        plan = {"cards": [], "compared_features": [], "questions": []}
        metrics = evaluation.product_metrics(case, results, plan, self.records)
        self.assertEqual(metrics["hard_violation_rate"], 1.0)
        self.assertEqual(metrics["unknown_false_satisfaction_count"], 1)
        self.assertFalse(metrics["checks"]["exact_eligible_products"])

    def test_product_oracle_detects_invented_rectangle_and_duplicate_photos(self):
        case = self.product_case("missing_rectangle")
        ids = case["record_ids"]
        results = [{"target_id": "pants", "status": "results", "hits": [{"product_id": pid} for pid in ids]}]
        cards = [{"candidate_id": str(index), "product_id": pid, "target_id": "pants"} for index, pid in enumerate(ids)]
        plan = {"cards": cards, "compared_features": [{"domain": "PI", "feature": feature} for feature in ("Color", "Fit")], "questions": []}
        metrics = evaluation.product_metrics(case, results, plan, self.records)
        self.assertGreater(metrics["nonexistent_combination_count"], 0)
        self.assertFalse(metrics["checks"]["no_invented_combinations"])
        case = self.product_case("duplicate_photos")
        plan["cards"] = [{"candidate_id": str(i), "product_id": pid, "target_id": "pants"} for i, pid in enumerate(case["record_ids"])]
        plan["compared_features"] = []
        metrics = evaluation.product_metrics(case, results, plan, self.records)
        self.assertEqual(metrics["candidate_duplicate_count"], 1)
        self.assertFalse(metrics["checks"]["no_duplicate_candidates"])

    def test_usage_boundary_keeps_fake_usage_separate_from_actual_billing(self):
        meter = evaluation.CallMeter()
        response = {"usage": {"input_tokens": 11, "output_tokens": 7, "input_tokens_details": {"cached_tokens": 3}}}
        transport = meter.transport(lambda *args: response)
        self.assertIs(transport("unused", {"Authorization": "dummy-test-secret"}, {}, 1), response)
        report = meter.report()
        self.assertEqual(report["fake_usage_reports"], [{"input_tokens": 11, "output_tokens": 7, "cached_input_tokens": 3}])
        self.assertEqual(report["actual_api_calls"], 0)
        self.assertIsNone(report["actual_api_tokens"])
        self.assertIsNone(report["actual_cost_usd"])
        self.assertNotIn("dummy-test-secret", json.dumps(report))
        with self.assertRaises(TimeoutError):
            meter.call("fake_semantic", lambda: (_ for _ in ()).throw(TimeoutError()))
        self.assertEqual(meter.events[-1]["outcome"], "error")
        self.assertEqual(meter.report()["calls"]["fake_semantic"], 1)

    def test_zero_denominator_and_actual_usage_are_never_claimed_as_zero(self):
        self.assertIsNone(evaluation.ratio(0, 0))
        for row in self.report["memory_retrieval"] + self.report["product_retrieval"]:
            meter = row["instrumentation"]
            self.assertEqual(meter["actual_api_calls"], 0)
            self.assertIsNone(meter["actual_api_tokens"])
            self.assertIsNone(meter["actual_cost_usd"])
        self.assertIsNone(self.report["actual_api_tokens"])
        self.assertIsNone(self.report["actual_cost_usd"])

    def test_external_cli_rehearsal_reports_actionable_errors_and_review(self):
        rehearsal = self.report["data_replacement"]
        self.assertTrue(all(rehearsal["checks"].values()))
        self.assertEqual(rehearsal["records"], 10)
        self.assertEqual(rehearsal["instrumentation"]["calls"]["cli_catalog-map"], 1)
        self.assertEqual(rehearsal["instrumentation"]["calls"]["cli_catalog-import"], 4)
        for diagnostic in rehearsal["invalid_input_diagnostics"]:
            self.assertIn(diagnostic["expected_location"], diagnostic["error"]["message"])
            self.assertEqual(diagnostic["error"]["code"], "invalid_input")
        self.assertTrue(all(item["required"] and item["path"] for item in rehearsal["review_examples"]))

    def test_cli_writes_failure_report_and_returns_failure_without_weakening_oracle(self):
        with tempfile.TemporaryDirectory(prefix="lumi-d4-negative-") as temporary:
            directory = Path(temporary)
            for path in evaluation.FIXTURES.iterdir():
                shutil.copyfile(path, directory / path.name)
            cases = deepcopy(self.product_cases)
            cases[0]["allowed"]["pants"] = []  # Deliberately wrong reference labels.
            (directory / "product_cases.json").write_text(json.dumps(cases), encoding="utf-8")
            output = directory / "report.json"
            self.assertEqual(evaluation.main(["--fixtures", str(directory), "--output", str(output)]), 1)
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["status"], "fail")
            self.assertIn("products/hard_navy_soft_straight/exact_eligible_products", report["failures"])


if __name__ == "__main__":
    unittest.main()
