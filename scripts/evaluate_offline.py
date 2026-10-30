#!/usr/bin/env python3
"""D4 development checks, using only frozen synthetic inputs and local fakes.

Run: python3 -B scripts/evaluate_offline.py [--output /external/report.json]
Input: tests/fixtures/evaluation/{memory_cases, catalog_replacement}.jsonl and
product_cases.json. --fixtures selects another directory with the same schema.
Output: JSON with separate memory/product metrics, per-stage calls/local elapsed
milliseconds, input hashes, invariant checks, and an external-file CLI rehearsal.
Exit 1 means an invariant failed; recall differences between ranking baselines
are observations, except explicit fixture minimums. Temporary DBs/files are
private to this invocation and removed before returning, including on failure.

All three memory runs receive the same snapshot/targets/budget. The structural
ablation disables only retrieval._terms in this single-threaded evaluator; the
keyword baseline is the actual structural+keyword implementation, and the third
run adds scripted semantic hits. No keyword-only production mode exists. This
private instrumentation is not a product option or an embedding evaluation.
Snapshots exercise read-side replay, not SQLite restart/consent transitions.
No provider, credentials, network, participant records, or research plan changes.
Transport usage is observed before gateway parsing; fake counters, if supplied,
stay labelled fake. Actual API tokens/cost remain null, never estimated as zero.
"""

from __future__ import annotations

import argparse
from collections import Counter
from contextlib import nullcontext
from copy import deepcopy
import hashlib
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from time import perf_counter
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from stylemate_memory import contracts as c, retrieval
from stylemate_memory.catalog import Catalog
from stylemate_memory.catalog_io import import_file
from stylemate_memory.catalog_mapping import map_catalog, review_product_map
from stylemate_memory.comparison import build_candidate_cards
from stylemate_memory.inference import infer_v1
from stylemate_memory.llm import OpenAIResponsesGateway
from stylemate_memory.product_search import search_products
from stylemate_memory.registry import load_registry


FIXTURES = ROOT / "tests" / "fixtures" / "evaluation"
MODES = ("structural_ablation", "structural_keyword", "scripted_semantic")
FIXTURE_FILES = ("memory_cases.jsonl", "catalog_replacement.jsonl", "product_cases.json")


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ratio(numerator, denominator):
    return numerator / denominator if denominator else None


class CallMeter:
    """Local observations only; never retain request bodies/headers or secrets."""

    def __init__(self):
        self.events = []

    def call(self, stage, operation):
        started = perf_counter()
        event = {"stage": stage, "outcome": "error", "fake_usage": None}
        try:
            result = operation()
            event["outcome"] = "returned"
            if stage == "fake_transport" and isinstance(result, dict):
                usage = result.get("usage")
                if isinstance(usage, dict):
                    values = {key: usage.get(key) for key in ("input_tokens", "output_tokens")}
                    details = usage.get("input_tokens_details")
                    values["cached_input_tokens"] = details.get("cached_tokens") if isinstance(details, dict) else None
                    event["fake_usage"] = {key: value if type(value) is int and value >= 0 else None
                                           for key, value in values.items()}
            return result
        finally:
            event["elapsed_ms"] = round((perf_counter() - started) * 1000, 4)
            self.events.append(event)

    def transport(self, transport):
        def measured(url, headers, payload, timeout):
            return self.call("fake_transport", lambda: transport(url, headers, payload, timeout))
        return measured

    def report(self):
        stages = sorted({event["stage"] for event in self.events})
        return {
            "calls": dict(Counter(event["stage"] for event in self.events)),
            "elapsed_ms": {stage: round(sum(e["elapsed_ms"] for e in self.events if e["stage"] == stage), 4)
                           for stage in stages},
            "latency_scope": "observed local wall time; nested stages overlap; not provider latency",
            "usage_boundary": "raw transport response.usage before gateway parsing",
            "fake_usage_reports": [e["fake_usage"] for e in self.events if e["fake_usage"] is not None],
            "actual_api_calls": 0, "actual_api_tokens": None, "actual_cost_usd": None,
        }


class ScriptedSemantic:
    def __init__(self, specification, meter):
        self.specification, self.meter = specification, meter
        self.eligible_refs = []

    def search(self, query, eligible_refs, *, index_version):
        self.eligible_refs = deepcopy(eligible_refs)
        def reply():
            if self.specification.get("error"):
                raise RuntimeError("synthetic semantic failure")
            return deepcopy(self.specification["hits"])
        return self.meter.call("fake_semantic", reply)


def fake_transport(url, headers, payload, timeout):
    # Fixed empty proposal: the code must preserve direct constraints itself.
    return {"status": "completed", "output": [{"type": "message", "content": [
        {"type": "output_text", "text": '{"suggestions": [], "questions": []}'}]}]}


def projection(constraints):
    return {canonical({key: clause[key] for key in ("target_id", "binding")}) for clause in constraints}


def memory_metrics(case, context, target_map=None):
    """Score against frozen reference labels, independently of retrieval ranks."""
    expected = case["expect"]
    sources = context["model_input"]["sources"]
    bundles = [(source, context["source_refs"][source["source_id"]]) for source in sources]
    found = {ref["id"] for _, refs in bundles for ref in refs if ref["type"] == "memory"}
    relevant = set(expected["relevant_ids"])
    labelled = {memory["id"] for memory in case["snapshot"]["memories"]}
    missing_refs, required_refs = 0, 0
    for _, refs in bundles:
        actual = {canonical(ref) for ref in refs}
        required = {canonical(ref) for mid in found if any(r["type"] == "memory" and r["id"] == mid for r in refs)
                    for ref in expected["bundles"].get(mid, [])}
        required_refs += len(required)
        missing_refs += len(required - actual)
    wanted = projection(expected["constraints"])
    observed = projection(context["constraints"])
    hard = projection([clause for clause in expected["constraints"] if clause["binding"]["strength"] == "hard"])
    mandatory = set(expected["mandatory_ids"])
    checks = {
        "excluded_memories_absent": not found.intersection(expected["excluded_ids"]),
        "mandatory_memories_preserved": mandatory <= found,
        "complete_evidence_bundles": missing_refs == 0,
        "exact_direct_constraints": observed == wanted,
        "required_questions_present": all(any(reason in q for q in context["questions"]) for reason in expected["questions"]),
    }
    objects = {(kind, obj["id"]): obj for kind, collection in (
        ("memory", "memories"), ("evidence", "evidence"), ("binding", "bindings"),
        ("confirmation", "confirmations"), ("consent", "consents"), ("question", "questions"))
        for obj in case["snapshot"][collection]}
    checks["all_bundle_refs_resolve"] = all(
        objects.get((ref["type"], ref["id"]), {}).get("version") == ref["version"] for _, refs in bundles for ref in refs)
    for mid, target_ids in expected.get("source_targets", {}).items():
        actual_targets = {source["selector"]["slot_id"] for source, refs in bundles
                          if any(ref["type"] == "memory" and ref["id"] == mid for ref in refs)}
        checks[f"target_isolation:{mid}"] = actual_targets == set(target_ids)
    if target_map is not None:
        checks["goal_preserves_constraints"] = projection(target_map["constraints"]) == wanted
        expected_values = expected["values"]
        if expected_values is not None:
            checks["no_invented_values"] = all(
                field["values"] == expected_values.get(target["target_id"], {}).get(feature)
                for target in target_map["targets"] for feature, field in target["product_information"].items())
            checks["no_invented_needs"] = all(
                field["preference"] is None for target in target_map["targets"]
                for category in target["consumer_needs"].values() for subcategory in category.values()
                for field in subcategory.values())
    return {
        "retrieved_ids": sorted(found), "relevant_count": len(relevant), "recalled_count": len(found & relevant),
        "recall": ratio(len(found & relevant), len(relevant)),
        "false_positive_count": len(found - relevant), "negative_count": len(labelled - relevant),
        "false_positive_rate": ratio(len(found - relevant), len(labelled - relevant)),
        "required_bundle_ref_count": required_refs, "missing_bundle_ref_count": missing_refs,
        "bundle_completeness": ratio(required_refs - missing_refs, required_refs),
        "mandatory_memory_count": len(mandatory), "mandatory_memory_preserved_count": len(mandatory & found),
        "mandatory_memory_preservation": ratio(len(mandatory & found), len(mandatory)),
        "hard_condition_count": len(hard), "hard_condition_preserved_count": len(hard & observed),
        "hard_condition_preservation": ratio(len(hard & observed), len(hard)),
        "direct_constraint_count": len(wanted), "direct_constraint_preserved_count": len(wanted & observed),
        "direct_constraint_preservation": ratio(len(wanted & observed), len(wanted)),
        "blocked": context["blocked"], "retrieval_status": context["retrieval_status"], "checks": checks,
    }


def evaluate_memory(case, mode, registry):
    # The JSON roundtrip also ensures the evaluator never relies on live objects.
    snapshot = json.loads(canonical(case["snapshot"]))
    before = digest(snapshot)
    meter = CallMeter()
    semantic = ScriptedSemantic(case["semantic"], meter) if mode == MODES[2] else None
    ablation = patch.object(retrieval, "_terms", return_value=set()) if mode == MODES[0] else nullcontext()
    with ablation:
        context = meter.call("memory_context", lambda: retrieval.build_context_v1(
            snapshot, case["targets"], registry=registry, semantic=semantic, char_budget=case["char_budget"]))
    target_map = None
    if not context["blocked"]:
        gateway = OpenAIResponsesGateway(model="synthetic-d4-model", api_key="dummy-d4-key",
                                         transport=meter.transport(fake_transport))
        target_map = meter.call("target_generation", lambda: infer_v1(context, gateway, registry=registry))
    result = memory_metrics(case, context, target_map)
    expected_blocked = case["expect"]["semantic_blocked" if semantic is not None else "blocked"]
    result["checks"].update({"blocked_as_expected": context["blocked"] == expected_blocked,
                              "input_unchanged": before == digest(snapshot)})
    if semantic is not None:
        result["checks"]["semantic_errors_visible"] = all(
            any(reason in q for q in context["questions"]) for reason in case["expect"].get("semantic_questions", []))
    minimum = case["expect"].get("minimum_recall", {}).get(mode)
    if minimum is not None:
        result["checks"]["fixture_recall_minimum"] = result["recall"] >= minimum
    return {"case": case["id"], "mode": mode,
            "input_sha256": digest({"snapshot": snapshot, "targets": case["targets"], "char_budget": case["char_budget"]}),
            "metrics": result, "instrumentation": meter.report()}


def make_target_map(case, registry):
    target_ids = case.get("target_ids", ["pants"])
    goal = {"contract_version": c.CONTRACT_VERSION, "registry_version": registry.version,
            "context_id": "synthetic-d4-" + case["id"],
            "targets": [registry.empty_target(tid, "Pants") for tid in target_ids],
            "constraints": [], "questions": [],
            "basis": {"request_id": "synthetic-d4-request", "request_revision": 1, "profile_revision": 0,
                      "object_versions": [], "contract_version": c.CONTRACT_VERSION,
                      "registry_version": registry.version, "index_version": None, "catalog": None, "valid_until": None}}
    for number, clause in enumerate(case["constraints"], 1):
        ref = {"type": "memory", "id": f"synthetic-d4-memory-{number}", "version": 1}
        goal["basis"]["object_versions"].append(ref)
        goal["constraints"].append({"id": f"constraint-{number}", **deepcopy(clause), "binding_ref": None,
            "selector": {"garment_type": "Pants", "slot_id": clause["target_id"]}, "conditions": {},
            "origin": "explicit", "confirmed": True, "source_refs": [ref]})
    return goal


def product_metrics(case, results, plan, records):
    by_id = {record["product_id"]: record for record in records}
    hits = [(result["target_id"], hit["product_id"]) for result in results for hit in result["hits"]]
    unexpected = [(tid, pid) for tid, pid in hits if pid not in case["allowed"][tid]]
    hard_targets = {clause["target_id"] for clause in case["constraints"] if clause["binding"]["strength"] == "hard"}
    unknown = set(case.get("unknown_for_hard", []))
    cards = plan["cards"]
    duplicate_count = len(cards) - len({(card["target_id"], card["product_id"]) for card in cards})
    for tid in case["allowed"]:
        displayed = {card["product_id"] for card in cards if card["target_id"] == tid}
        for group in case.get("duplicate_groups", []):
            duplicate_count += max(0, len(displayed.intersection(group)) - 1)
    nonexistent = sum(card["product_id"] not in by_id for card in cards)
    axes = [path["feature"] for path in plan["compared_features"] if path["domain"] == "PI"]
    if case.get("mode") == "two_axis" and len(axes) == 2:
        for tid in case["allowed"]:
            displayed = [by_id[card["product_id"]] for card in cards if card["target_id"] == tid and card["product_id"] in by_id]
            cells = {tuple(record["raw_metadata"].get("supplier_" + axis.lower()) for axis in axes) for record in displayed}
            a, b = ({cell[index] for cell in cells} for index in range(2))
            nonexistent += len(set(product(a, b)) - cells)
            if len(a) < 2 or len(b) < 2 or any(None in cell for cell in cells):
                nonexistent += 1
    checks = {
        "exact_eligible_products": all({hit["product_id"] for hit in result["hits"]} == set(case["allowed"][result["target_id"]]) for result in results),
        "status_as_expected": all(result["status"] == case.get("status", "results") for result in results),
        "candidate_ids_unique": len({card["candidate_id"] for card in cards}) == len(cards),
        "candidate_target_isolation": all(card["target_id"] in case["allowed"] and card["product_id"] in case["allowed"][card["target_id"]] for card in cards),
        "no_duplicate_candidates": duplicate_count == 0,
        "no_invented_combinations": nonexistent == 0,
        "unknown_not_accepted_as_hard": not any(pid in unknown and tid in hard_targets for tid, pid in hits),
    }
    if "first" in case:
        checks["soft_ranking"] = bool(hits) and hits[0][1] == case["first"]
    if "card_count" in case:
        checks["candidate_count"] = len(cards) == case["card_count"]
    if "axis_count" in case:
        checks["axis_count"] = len(axes) == case["axis_count"]
    if "max_axis_count" in case:
        checks["axis_count"] = len(axes) <= case["max_axis_count"]
    if not any(case["allowed"].values()):
        checks["no_results_choices"] = not cards and any(set(q["options"]) == {"조건 유지", "조건 조정", "탐색 종료"} for q in plan["questions"])
    hard_hits = [(tid, pid) for tid, pid in hits if tid in hard_targets]
    violations = sum(tid in hard_targets for tid, _ in unexpected)
    unknown_count = len(unknown) * len(hard_targets)
    unknown_accepted = sum(pid in unknown for _, pid in hard_hits)
    return {"hit_ids": {result["target_id"]: [hit["product_id"] for hit in result["hits"]] for result in results},
            "hard_returned_count": len(hard_hits), "hard_violation_count": violations,
            "hard_violation_rate": ratio(violations, len(hard_hits)),
            "unknown_opportunity_count": unknown_count, "unknown_false_satisfaction_count": unknown_accepted,
            "unknown_false_satisfaction_rate": ratio(unknown_accepted, unknown_count),
            "candidate_count": len(cards), "candidate_duplicate_count": duplicate_count,
            "candidate_duplicate_rate": ratio(duplicate_count, len(cards)),
            "nonexistent_combination_count": nonexistent, "checks": checks}


def evaluate_products(case, records, directory, registry):
    selected = [record for record in records if record["product_id"] in case.get("record_ids", [r["product_id"] for r in records])]
    source = directory / "products.jsonl"
    source.write_text("".join(canonical(record) + "\n" for record in selected), encoding="utf-8")
    meter = CallMeter()
    with Catalog(directory / "catalog.sqlite3") as catalog:
        meter.call("catalog_import", lambda: import_file(catalog, source))
        mapped = meter.call("catalog_map", lambda: map_catalog(catalog, registry=registry))
        goal = make_target_map(case, registry)
        before = digest(goal)
        results = [meter.call("product_search", lambda tid=tid: search_products(goal, tid, catalog)) for tid in case["allowed"]]
        plan = meter.call("comparison", lambda: build_candidate_cards(results, goal, catalog, mode=case.get("mode", "default")))
        metrics = product_metrics(case, results, plan, selected)
        metrics["checks"].update({"input_unchanged": before == digest(goal),
                                  "maps_built": mapped["status"] == "complete" and not mapped["failures"]})
    return {"case": case["id"], "metrics": metrics, "instrumentation": meter.report()}


def cli_call(arguments, meter):
    # A minimal environment prevents incidental settings/credential access.
    command = [sys.executable, "-B", "-m", "stylemate_memory.cli", *arguments]
    result = meter.call("cli_" + arguments[0], lambda: subprocess.run(
        command, cwd=ROOT, env={"PYTHONPATH": str(ROOT / "src")}, capture_output=True, text=True, timeout=30))
    return result.returncode, json.loads(result.stdout)


def rehearse_replacement(fixtures, directory, registry):
    meter = CallMeter()
    replacement = read_jsonl(fixtures / "catalog_replacement.jsonl")
    source = directory / "replacement.jsonl"
    source.write_text("".join(canonical(record) + "\n" for record in replacement), encoding="utf-8")
    flags = ["--db", str(directory / "memory.sqlite3"), "--catalog-db", str(directory / "catalog.sqlite3"), "--user", "synthetic-d4"]
    imported, _ = cli_call(["catalog-import", *flags, "--file", str(source)], meter)
    mapped, map_report = cli_call(["catalog-map", *flags], meter)
    maps = map_report if isinstance(map_report, list) else []
    checks = {"cli_import_and_map": imported == mapped == 0 and len(maps) == len(replacement)}
    with Catalog(directory / "catalog.sqlite3") as catalog:
        goal = make_target_map({"id": "replacement-rehearsal", "constraints": []}, registry)
        result = meter.call("product_search", lambda: search_products(goal, "pants", catalog))
        checks["replacement_search_uses_supplied_ids"] = result["status"] == "results" and {
            hit["product_id"] for hit in result["hits"]} == {r["product_id"] for r in replacement if r["garment_type"] == "Pants"}
        checks["different_from_default_fixture"] = not {r["product_id"] for r in replacement}.intersection(
            r["product_id"] for r in read_jsonl(ROOT / "tests/fixtures/catalog/valid.jsonl"))
        before = catalog.export_records()
    diagnostics = []
    for name, field, value, location, reason in (
        ("timestamp", "collected_at", "yesterday", "JSONL line 2.source.collected_at", "ISO 8601 timestamp with timezone required"),
        ("source_url", "url", "file:///synthetic", "JSONL line 2.source.url", "supplier HTTP(S) URL required"),
        ("verified_label", "verifier", None, "JSONL line 2.labels[0].provenance[0]", "verified label needs verifier, verified_at, and supplier evidence_ref"),
    ):
        bad = deepcopy(replacement[:2])
        bad[0]["title"] = "이 변경도 잘못된 배치와 함께 rollback되어야 함"
        if name == "verified_label":
            bad[1]["labels"][0]["provenance"][0][field] = value
        else:
            bad[1]["source"][field] = value
        invalid = directory / ("invalid-" + name + ".jsonl")
        invalid.write_text("".join(canonical(record) + "\n" for record in bad), encoding="utf-8")
        code, response = cli_call(["catalog-import", *flags, "--file", str(invalid)], meter)
        error = response.get("error", {})
        message = error.get("message", "")
        checks["diagnostic:" + name] = code != 0 and location in message and reason in message
        with Catalog(directory / "catalog.sqlite3") as catalog:
            checks["rollback:" + name] = catalog.export_records() == before
        diagnostics.append({"case": name, "error": error, "expected_location": location, "required_reason": reason})
    # A2 CLI returns ProductMap[], while the lower-level map_catalog has a report.
    # Call the existing review function explicitly; do not pretend CLI emitted it.
    review = [{"product_id": mapped["product_id"], "items": review_product_map(mapped)} for mapped in maps]
    review = [item for item in review if item["items"]]
    checks["unverified_attributes_require_review"] = bool(review)
    return {"external_temporary_files": True, "records": len(replacement), "checks": checks,
            "invalid_input_diagnostics": diagnostics, "review_product_count": len(review),
            "review_source": "review_product_map applied explicitly to CLI-returned maps",
            "review_examples": [item for product_review in review if product_review["product_id"] == "alt-unknown"
                                for item in product_review["items"] if item["path"] in (
                                    ["PI", "Color"], ["FEA", "Functional", "Protection", "Warmth"])],
            "instrumentation": meter.report()}


def run_evaluation(fixtures=FIXTURES):
    registry = load_registry(c.V1_REGISTRY_VERSION)
    cases = read_jsonl(fixtures / "memory_cases.jsonl")
    records = read_jsonl(fixtures / "catalog_replacement.jsonl")
    product_cases = json.loads((fixtures / "product_cases.json").read_text(encoding="utf-8"))
    memory = [evaluate_memory(case, mode, registry) for case in cases for mode in MODES]
    with tempfile.TemporaryDirectory(prefix="lumi-d4-", dir="/private/tmp" if Path("/private/tmp").is_dir() else None) as temporary:
        root = Path(temporary)
        products = []
        for case in product_cases:
            directory = root / case["id"]
            directory.mkdir()
            products.append(evaluate_products(case, records, directory, registry))
        replacement = root / "replacement-rehearsal"
        replacement.mkdir()
        rehearsal = rehearse_replacement(fixtures, replacement, registry)
    failures = [f"memory/{row['case']}/{row['mode']}/{key}" for row in memory
                for key, passed in row["metrics"]["checks"].items() if not passed]
    failures += [f"products/{row['case']}/{key}" for row in products
                 for key, passed in row["metrics"]["checks"].items() if not passed]
    failures += ["replacement/" + key for key, passed in rehearsal["checks"].items() if not passed]
    by_mode = {}
    for mode in MODES:
        rows = [row["metrics"] for row in memory if row["mode"] == mode]
        by_mode[mode] = {name: ratio(sum(row[numerator] for row in rows), sum(row[denominator] for row in rows))
                        for name, numerator, denominator in (
                            ("micro_recall", "recalled_count", "relevant_count"),
                            ("micro_false_positive_rate", "false_positive_count", "negative_count"),
                            ("micro_mandatory_memory_preservation", "mandatory_memory_preserved_count", "mandatory_memory_count"),
                            ("micro_hard_condition_preservation", "hard_condition_preserved_count", "hard_condition_count"),
                            ("micro_direct_constraint_preservation", "direct_constraint_preserved_count", "direct_constraint_count"))}
        ref_count = sum(row["required_bundle_ref_count"] for row in rows)
        by_mode[mode]["micro_bundle_completeness"] = ratio(ref_count - sum(row["missing_bundle_ref_count"] for row in rows), ref_count)
    product_rows = [row["metrics"] for row in products]
    product_summary = {name: ratio(sum(row[numerator] for row in product_rows), sum(row[denominator] for row in product_rows))
                       for name, numerator, denominator in (
                           ("hard_violation_rate", "hard_violation_count", "hard_returned_count"),
                           ("unknown_false_satisfaction_rate", "unknown_false_satisfaction_count", "unknown_opportunity_count"),
                           ("candidate_duplicate_rate", "candidate_duplicate_count", "candidate_count"))}
    product_summary["nonexistent_combination_count"] = sum(row["nonexistent_combination_count"] for row in product_rows)
    return {"evaluation": "lumi-d4-offline-v1", "scope": "synthetic development verification",
            "status": "pass" if not failures else "fail", "failures": failures,
            "fixture_sha256": {name: hashlib.sha256((fixtures / name).read_bytes()).hexdigest() for name in FIXTURE_FILES},
            "modes": {MODES[0]: "structural ranking; lexical channel disabled only in evaluator",
                      MODES[1]: "production structural + keyword/alias fusion",
                      MODES[2]: "production fusion + scripted semantic reference order; no embeddings"},
            "metric_units": {"memory": "unique memory IDs per case; false positive denominator is all fixture-labelled negative IDs, including ineligible IDs",
                             "bundles": "required versioned references per emitted source bundle, including irrelevant retrieved memories",
                             "preservation": "memory items, hard binding conditions, and all direct constraints have separate denominators",
                             "products": "returned product per target; unknown opportunities are labelled unknown product x hard target; cards count separately"},
            "memory_summary": by_mode, "memory_retrieval": memory,
            "product_summary": product_summary, "product_retrieval": products,
            "data_replacement": rehearsal, "actual_api_calls": 0, "actual_api_tokens": None, "actual_cost_usd": None,
            "limits": ["Fixture recall/false positives do not estimate real retrieval or model quality.",
                       "Wall times measure this local fake run; timings are not deterministic or additive across nested stages.",
                       "A null rate has no denominator; it is not a zero error rate.",
                       "Memory snapshots cover read-side scenarios; SQLite transitions, UI and research effects are outside D4.",
                       "No images are fetched; supplied example.invalid references establish identity only.",
                       "No actual API usage or billing is observed; transport counters, if any, are fake fixture values."]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--fixtures", type=Path, default=FIXTURES)
    parser.add_argument("--output", type=Path, help="JSON report path; default stdout")
    args = parser.parse_args(argv)
    report = run_evaluation(args.fixtures)
    output = json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(output, encoding="utf-8")
    else:
        print(output, end="")
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
