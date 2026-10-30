"""D3 fixtures are synthetic supplier records and an A0-shaped TargetMap.

They deliberately do not call C3 inference, a real model or an image server.
"""

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stylemate_memory.catalog import Catalog
from stylemate_memory.catalog_mapping import build_product_map
from stylemate_memory.comparison import build_candidate_cards
from stylemate_memory.contracts import (
    CATALOG_FORMAT_VERSION, CONTRACT_VERSION, V1_REGISTRY_VERSION,
    CandidateCard, CandidatePlan, SearchResult,
)
from stylemate_memory.errors import StyleMateError
from stylemate_memory.product_search import search_products
from stylemate_memory.registry import load_registry


def synthetic_product(pid, color="Navy", fit="Wide", fabric=None, *, garment="Pants", image=True):
    metadata = {"supplier_type": "Slacks", "supplier_fit": fit,
                "supplier_fabric": ["Cotton"] if fabric is None else fabric}
    if color is not None:
        metadata["supplier_color"] = color
    if garment != "Pants":
        metadata = {}
    return {
        "format_version": CATALOG_FORMAT_VERSION, "product_id": pid,
        "source": {"source_id": "synthetic-d3", "url": f"https://example.invalid/d3/{pid}",
                   "collected_at": "2026-10-29T12:00:00+09:00"},
        "title": "검색 검증용 합성 상품", "description": "실제 판매 상품이 아닙니다.",
        "garment_type": garment, "raw_metadata": metadata, "labels": [],
        "images": [{"image_id": f"image-{pid}", "kind": "remote",
                    "location": f"https://images.example.invalid/d3/{pid}.png",
                    "source_revision": "synthetic-v1", "sha256": None, "regions": []}] if image else [],
    }


def verified(observation, *, inferred=False):
    return {"observation": observation, "status": "inferred" if inferred else "confirmed",
            "provenance": [{"kind": "provided_label" if inferred else "verified_label",
                            "source_field": None, "quote": None, "verifier": "synthetic-lab",
                            "evidence_ref": "synthetic-check", "verified_at": None if inferred else "2026-10-29T12:00:00+09:00"}]}


class CatalogFixture(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="lumi-d3-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.registry = load_registry(V1_REGISTRY_VERSION)
        self.sequence = 0
        self.rectangle = [
            synthetic_product("p1", "Navy", "Wide", ["Cotton", "Polyester"]),
            synthetic_product("p2", "Navy", "Straight", ["Wool"]),
            synthetic_product("p3", "Beige", "Wide", ["Cotton"]),
            synthetic_product("p4", "Beige", "Straight", ["Polyester"]),
        ]
        self.use_records(self.rectangle)

    def use_records(self, records):
        self.sequence += 1
        self.catalog = Catalog(self.root / f"catalog-{self.sequence}.sqlite3")
        self.addCleanup(self.catalog.close)
        self.records = deepcopy(records)
        self.maps = {}
        self.install(self.records)

    def install(self, records):
        self.catalog.import_records(records)
        for record in records:
            pid = record["product_id"]
            mapped = build_product_map(record, raw_version=self.catalog.raw_version(pid), registry=self.registry)
            previous = self.maps.get(pid)
            self.maps[pid] = self.catalog.save_product_map(
                mapped, expected_raw_version=mapped["raw_version"],
                expected_map_version=previous["map_version"] if previous else None)

    def target_map(self, *target_ids, garment="Pants"):
        return {"contract_version": CONTRACT_VERSION, "registry_version": V1_REGISTRY_VERSION,
                "context_id": "synthetic-d3-context",
                "targets": [self.registry.empty_target(tid, garment) for tid in target_ids or ("pants",)],
                "constraints": [], "questions": [],
                "basis": {"request_id": "synthetic-request", "request_revision": 1, "profile_revision": 0,
                          "object_versions": [], "contract_version": CONTRACT_VERSION,
                          "registry_version": V1_REGISTRY_VERSION, "index_version": None,
                          "catalog": None, "valid_until": None}}

    def add_constraint(self, target_map, feature="Color", values=None, *, target_id="pants", match="any",
                       polarity="require", strength="hard", confirmed=True, origin="explicit", fea=False):
        cid = f"constraint-{len(target_map['constraints']) + 1}"
        source = {"type": "memory", "id": f"memory-{cid}", "version": 1}
        binding = {"domain": "FEA", "category": "Functional", "subcategory": "Protection", "tag": "Warmth"} if fea else {
            "domain": "PI", "feature": feature, "values": ["Navy"] if values is None else values, "match": match}
        binding.update(polarity=polarity, strength=strength)
        constraint = {"id": cid, "target_id": target_id, "binding_ref": None, "binding": binding,
                      "selector": {"garment_type": "Pants", "slot_id": target_id}, "conditions": {},
                      "origin": origin, "confirmed": confirmed, "source_refs": [source]}
        target_map["constraints"].append(constraint)
        target_map["basis"]["object_versions"].append(source)
        # Deliberately leave display values null. Constraints alone execute.
        return constraint

    def search(self, target_map=None, target_id="pants"):
        return search_products(self.target_map() if target_map is None else target_map, target_id, self.catalog)

    def plan(self, target_map=None, **kwargs):
        target_map = self.target_map() if target_map is None else target_map
        results = [self.search(target_map, t["target_id"]) for t in target_map["targets"]]
        return build_candidate_cards(results, target_map, self.catalog, **kwargs)

    def assert_error(self, code, function, *args, **kwargs):
        with self.assertRaises(StyleMateError) as caught:
            function(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)


class ProductSearchTests(CatalogFixture):
    def test_hard_filter_excludes_unknown_inferred_and_wrong_target_before_soft_ranking(self):
        self.install([synthetic_product("unknown", None), synthetic_product("inferred", "navy"),
                      synthetic_product("wrong-target", garment="Shirt"), synthetic_product("soft-only", "Black", "Slim")])
        goal = self.target_map()
        self.add_constraint(goal)
        self.add_constraint(goal, "Fit", ["Wide"], polarity="prefer", strength="soft")
        before = deepcopy(goal)
        result = self.search(goal)
        self.assertEqual(result["status"], "results")
        self.assertEqual([h["product_id"] for h in result["hits"]], ["p1", "p2"])
        self.assertEqual([h["score"] for h in result["hits"]], [1.0, -1.0])
        self.assertEqual(goal, before)
        self.assertEqual(set(result), set(SearchResult.__required_keys__))

    def test_any_all_and_separate_clauses_execute_instead_of_flat_display(self):
        goal = self.target_map()
        self.add_constraint(goal, "Fabric", ["Cotton", "Polyester"], match="all")
        self.add_constraint(goal, "Fabric", ["Wool", "Polyester"], match="any")
        goal["targets"][0]["product_information"]["Fabric"].update(status="specified", values=["Wool"])
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p1"])
        self.assertEqual(len(self.search(goal)["hits"][0]["matched_constraint_ids"]), 2)
        goal["constraints"][0]["binding"]["match"] = "any"
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p1", "p4"])

    def test_avoid_any_all_preserves_unknown_and_combination_semantics(self):
        self.install([synthetic_product("unknown", None), synthetic_product("mixed", ["Navy", "Beige"])])
        goal = self.target_map()
        self.add_constraint(goal, values=["Navy", "Beige"], polarity="avoid", match="all")
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p1", "p2", "p3", "p4"])
        goal["constraints"][0]["binding"].update(values=["Navy"], match="any")
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p3", "p4"])

    def test_verified_fea_presence_and_absence_are_not_inferred_performance(self):
        observation = {"domain": "FEA", "category": "Functional", "subcategory": "Protection", "tag": "Warmth", "present": True}
        records = deepcopy(self.rectangle)
        records[0]["labels"] = [verified(observation)]
        records[1]["labels"] = [verified({**observation, "present": False})]
        records[2]["labels"] = [verified(observation, inferred=True)]
        records[3]["raw_metadata"]["review"] = "따뜻하다는 느낌"
        self.install(records)
        goal = self.target_map()
        self.add_constraint(goal, fea=True)
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p1"])
        goal["constraints"][0]["binding"]["polarity"] = "avoid"
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p2"])

    def test_numeric_prices_do_not_fill_unknown_buckets_and_range_is_blocked(self):
        records = deepcopy(self.rectangle)
        records[0]["raw_metadata"]["supplier_price"] = 43900
        records[1]["labels"] = [verified({"domain": "PI", "feature": "Price", "values": ["43,900~54,360"]})]
        self.install(records)
        goal = self.target_map()
        self.add_constraint(goal, "Price", ["43,900~54,360"])
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p2"])
        goal["constraints"][0]["binding"]["match"] = "range"
        self.assertEqual(self.search(goal)["status"], "blocked")

    def test_unconfirmed_hard_and_unsupported_brand_block_without_relaxation(self):
        for overrides in ({"confirmed": False, "origin": "inferred"},
                          {"feature": "Brand", "values": ["1989STANDARD"]}):
            with self.subTest(overrides=overrides):
                goal = self.target_map()
                self.add_constraint(goal, **overrides)
                result = self.search(goal)
                self.assertEqual((result["status"], result["hits"]), ("blocked", []))

    def test_soft_hypothesis_can_rank_but_cannot_exclude_other_hard_eligible_products(self):
        goal = self.target_map()
        self.add_constraint(goal)
        self.add_constraint(goal, "Fit", ["Wide"], polarity="prefer", strength="soft", confirmed=False, origin="inferred")
        self.assertEqual([h["product_id"] for h in self.search(goal)["hits"]], ["p1", "p2"])
        # Flat inferred values without a constraint are not filters or scores.
        bare = self.target_map()
        bare["targets"][0]["product_information"]["Color"].update(status="inferred", values=["Navy"])
        self.assertEqual(len(self.search(bare)["hits"]), 4)
        self.assertTrue(all(h["score"] == 0 for h in self.search(bare)["hits"]))

    def test_unknown_soft_is_not_a_match_and_indifference_does_not_cancel_hard(self):
        self.install([synthetic_product("unknown", None)])
        soft = self.target_map()
        constraint = self.add_constraint(soft, polarity="prefer", strength="soft")
        hit = next(h for h in self.search(soft)["hits"] if h["product_id"] == "unknown")
        self.assertEqual((hit["score"], hit["matched_constraint_ids"], hit["unknown_constraint_ids"]), (0.0, [], [constraint["id"]]))
        hard = self.target_map()
        self.add_constraint(hard)
        self.add_constraint(hard, values=None, match=None, polarity="indifferent", strength="soft")["binding"]["values"] = None
        hard["targets"][0]["product_information"]["Color"]["status"] = "indifferent"
        self.assertEqual([h["product_id"] for h in self.search(hard)["hits"]], ["p1", "p2"])

    def test_all_products_rejected_has_structured_choices_and_no_constraint_mutation(self):
        goal = self.target_map()
        self.add_constraint(goal, values=["Green"])
        before = deepcopy(goal)
        result = self.search(goal)
        self.assertEqual((result["status"], result["hits"]), ("no_results", []))
        plan = build_candidate_cards([result], goal, self.catalog)
        self.assertEqual(plan["cards"], [])
        self.assertEqual(plan["questions"][0]["options"], ["조건 유지", "조건 조정", "탐색 종료"])
        self.assertEqual(goal, before)

    def test_empty_catalog_and_unsupported_garment_do_not_claim_results(self):
        self.use_records([])
        self.assertEqual(self.search()["status"], "no_results")
        self.assertEqual(self.plan()["cards"], [])
        goal = self.target_map("shirt", garment="Shirt")
        self.assertEqual(self.search(goal, "shirt")["status"], "blocked")

    def test_unbuilt_and_raw_stale_maps_block_instead_of_returning_partial_success(self):
        self.catalog.import_records([synthetic_product("unbuilt")])
        self.assertEqual((self.search()["status"], self.search()["hits"]), ("blocked", []))
        self.install([synthetic_product("unbuilt")])
        changed = deepcopy(self.rectangle[0])
        changed["description"] = "새 합성 원자료"
        self.catalog.import_records([changed])
        self.assertEqual(self.search()["status"], "blocked")

    def test_product_search_metrics_are_separate_from_memory_search_and_result_contract(self):
        with self.assertLogs("stylemate_memory.product_search", level="INFO") as logs:
            result = self.search()
        self.assertEqual(set(result), set(SearchResult.__required_keys__))
        self.assertIn("product_search status=results scanned=4 eligible=4 elapsed_ms=", logs.output[0])

    def test_expired_basis_bool_revision_and_unknown_fields_are_rejected(self):
        for key, value, code in (("valid_until", "2000-01-01T00:00:00+00:00", "stale_context"),
                                 ("request_revision", True, "invalid_input")):
            goal = self.target_map()
            goal["basis"][key] = value
            self.assert_error(code, self.search, goal)
        goal = self.target_map()
        self.add_constraint(goal)["binding"]["confirmed"] = True
        self.assert_error("invalid_input", self.search, goal)

    def test_constraint_source_and_binding_versions_must_be_in_basis(self):
        goal = self.target_map()
        constraint = self.add_constraint(goal)
        goal["basis"]["object_versions"] = []
        self.assert_error("stale_context", self.search, goal)
        goal["basis"]["object_versions"] = deepcopy(constraint["source_refs"])
        constraint["binding_ref"] = {"type": "binding", "id": "binding-1", "version": 1}
        self.assert_error("stale_context", self.search, goal)
        goal["basis"]["object_versions"].append(deepcopy(constraint["binding_ref"]))
        self.assertEqual(self.search(goal)["status"], "results")

    def test_catalog_change_during_search_rejects_the_mixed_snapshot(self):
        original = self.catalog.get_product_map
        changed = False

        def read_and_change(pid):
            nonlocal changed
            mapped = original(pid)
            if not changed:
                changed = True
                record = self.catalog.get_record(pid)
                record["images"][0]["source_revision"] = "changed-during-search"
                self.catalog.import_records([record])
            return mapped

        with patch.object(self.catalog, "get_product_map", side_effect=read_and_change):
            self.assert_error("stale_context", self.search)


class ComparisonTests(CatalogFixture):
    def test_default_and_detail_sizes_and_contracts_are_adjustable(self):
        for mode, expected in (("default", 3), ("detail", 2)):
            with self.subTest(mode=mode):
                plan = self.plan(mode=mode)
                self.assertEqual(len(plan["cards"]), expected)
                self.assertEqual(set(plan), set(CandidatePlan.__required_keys__))
                self.assertTrue(all(set(card) == set(CandidateCard.__required_keys__) for card in plan["cards"]))
                self.assertEqual([c["position"] for c in plan["cards"]], list(range(1, expected + 1)))
        self.assertEqual(len(self.plan(size=1)["cards"]), 1)
        self.assert_error("invalid_input", self.plan, size=5)

    def test_two_axis_uses_four_actual_combinations_and_map_provenance(self):
        plan = self.plan(mode="two_axis")
        self.assertEqual(len(plan["cards"]), 4)
        self.assertEqual(plan["compared_features"], [{"domain": "PI", "feature": "Color"}, {"domain": "PI", "feature": "Fit"}])
        combinations = set()
        for card in plan["cards"]:
            mapped = self.catalog.get_product_map(card["product_id"])
            self.assertEqual(mapped["map_version"], card["product_map_version"])
            values = {}
            for a in mapped["assertions"]:
                if a["observation"]["domain"] == "PI" and a["observation"]["feature"] in ("Color", "Fit"):
                    self.assertEqual(a["status"], "confirmed")
                    self.assertTrue(a["provenance"])
                    values[a["observation"]["feature"]] = tuple(a["observation"]["values"])
            combinations.add((values["Color"], values["Fit"]))
        self.assertEqual(len(combinations), 4)
        self.assertIn("Color=Navy", plan["questions"][0]["text"])

    def test_missing_combination_reduces_axis_without_inventing_a_fourth_product(self):
        self.use_records(self.rectangle[:3])
        plan = self.plan(mode="two_axis")
        self.assertEqual(len(plan["cards"]), 3)
        self.assertEqual(plan["compared_features"], [{"domain": "PI", "feature": "Color"}])
        self.assertEqual({c["product_id"] for c in plan["cards"]}, {"p1", "p2", "p3"})
        self.assertIn("비교 축을 줄였습니다", plan["questions"][0]["text"])

    def test_few_eligible_candidates_are_not_filled_with_hard_violations(self):
        goal = self.target_map()
        self.add_constraint(goal)
        plan = self.plan(goal, mode="two_axis")
        self.assertEqual({c["product_id"] for c in plan["cards"]}, {"p1", "p2"})
        self.assertEqual(plan["compared_features"], [{"domain": "PI", "feature": "Fit"}])

    def test_duplicate_records_hits_and_identical_verified_photo_maps_are_collapsed(self):
        records = self.catalog.export_records()
        with patch.object(self.catalog, "export_records", return_value=records * 2):
            result = self.search()
        self.assertEqual(len(result["hits"]), 4)
        result["hits"] *= 2
        plan = build_candidate_cards([result], self.target_map(), self.catalog)
        self.assertEqual(len({c["product_id"] for c in plan["cards"]}), 3)
        duplicate = deepcopy(self.rectangle[0])
        original = deepcopy(self.rectangle[0])
        for record in (duplicate, original):
            record["images"][0]["sha256"] = "a" * 64
        duplicate["product_id"] = "copy"
        duplicate["source"]["url"] = "https://example.invalid/d3/copy"
        duplicate["images"][0]["image_id"] = "image-copy"
        self.use_records([original, duplicate, self.rectangle[1]])
        self.assertEqual(len(self.plan()["cards"]), 2)

    def test_missing_images_and_inferred_labels_do_not_establish_visual_axes(self):
        self.use_records([synthetic_product("a", "navy", "Wide", image=False),
                          synthetic_product("b", "beige", "Wide", image=False)])
        with patch.object(self.catalog, "resolve_image", side_effect=AssertionError("image I/O is forbidden")):
            plan = self.plan()
        self.assertEqual(len(plan["cards"]), 2)
        self.assertEqual(plan["compared_features"], [])
        self.assertTrue(all(c["image_id"] is None and c["image_version"] is None for c in plan["cards"]))
        self.use_records([synthetic_product("a", "navy"), synthetic_product("b", "beige")])
        self.assertEqual(self.plan()["compared_features"], [])

    def test_variants_on_the_same_supplier_page_keep_their_actual_differences(self):
        records = deepcopy(self.rectangle[:3])
        for record in records:
            record["source"]["url"] = "https://example.invalid/shared-variant-page"
        self.use_records(records)
        plan = self.plan()
        self.assertEqual(len(plan["cards"]), 3)
        self.assertIn({"domain": "PI", "feature": "Color"}, plan["compared_features"])

    def test_identical_values_do_not_claim_a_comparison_difference(self):
        self.use_records([synthetic_product("a"), synthetic_product("b"), synthetic_product("c")])
        self.assertEqual(self.plan()["compared_features"], [])

    def test_stable_ids_and_catalog_basis_survive_retry_and_restart(self):
        first = self.plan(mode="two_axis")
        self.assertEqual(first, self.plan(mode="two_axis"))
        with Catalog(self.catalog.db_path) as reopened:
            goal = self.target_map()
            result = search_products(goal, "pants", reopened)
            self.assertEqual(build_candidate_cards([result], goal, reopened, mode="two_axis"), first)
        goal = self.target_map()
        goal["basis"]["request_revision"] += 1
        self.assertNotEqual(first["cards"][0]["candidate_id"], self.plan(goal, mode="two_axis")["cards"][0]["candidate_id"])
        json.dumps(first, ensure_ascii=False, allow_nan=False)

    def test_map_and_image_changes_change_basis_and_reject_old_results(self):
        for change in ("map", "image"):
            with self.subTest(change=change):
                goal = self.target_map()
                result = self.search(goal)
                before = build_candidate_cards([result], goal, self.catalog, mode="two_axis")
                if change == "map":
                    mapped = self.catalog.get_product_map("p1")
                    color = next(a for a in mapped["assertions"] if a["observation"].get("feature") == "Color")
                    color["provenance"] = verified(color["observation"])["provenance"]
                    self.catalog.save_product_map(mapped, expected_raw_version=mapped["raw_version"], expected_map_version=mapped["map_version"])
                else:
                    record = self.catalog.get_record("p1")
                    record["images"][0]["source_revision"] = "synthetic-v2"
                    self.catalog.import_records([record])
                self.assert_error("stale_context", build_candidate_cards, [result], goal, self.catalog)
                after = self.plan(mode="two_axis")
                self.assertNotEqual(before["basis"], after["basis"])
                self.assertNotEqual(before["cards"][0]["candidate_id"], after["cards"][0]["candidate_id"])

    def test_every_card_has_map_image_and_raw_versions_and_expired_input_catalog_is_rejected(self):
        goal = self.target_map()
        plan = self.plan(goal)
        versions = plan["basis"]["catalog"]
        products = {p["product_id"]: p for p in versions["products"]}
        images = {i["image_id"]: i["version"] for i in versions["images"]}
        for card in plan["cards"]:
            self.assertEqual(products[card["product_id"]]["map_version"], card["product_map_version"])
            self.assertEqual(products[card["product_id"]]["raw_version"], 1)
            self.assertEqual(images[card["image_id"]], card["image_version"])
        goal["basis"]["catalog"] = deepcopy(versions)
        record = self.catalog.get_record("p4")
        record["images"][0]["source_revision"] = "new-version"
        self.catalog.import_records([record])
        self.assert_error("stale_context", self.search, goal)

    def test_multiple_targets_have_separate_filters_and_comparison_axes(self):
        goal = self.target_map("navy", "beige")
        self.add_constraint(goal, target_id="navy")
        self.add_constraint(goal, values=["Beige"], target_id="beige")
        plan = self.plan(goal, size=4)
        for card in plan["cards"]:
            expected = {"p1", "p2"} if card["target_id"] == "navy" else {"p3", "p4"}
            self.assertIn(card["product_id"], expected)
        self.assertEqual(plan["compared_features"], [{"domain": "PI", "feature": "Fit"}])
        self.assertEqual({q["target_id"] for q in plan["questions"]}, {"navy", "beige"})
        result = self.search(goal, "navy")
        result["hits"][0]["product_id"] = "p3"
        self.assert_error("invalid_output", build_candidate_cards, [result, self.search(goal, "beige")], goal, self.catalog)

    def test_a_target_without_results_stays_explicit_while_other_target_can_explore(self):
        goal = self.target_map("available", "missing")
        self.add_constraint(goal, target_id="available")
        self.add_constraint(goal, values=["Green"], target_id="missing")
        plan = self.plan(goal)
        self.assertEqual({c["target_id"] for c in plan["cards"]}, {"available"})
        self.assertEqual(plan["questions"][0]["target_id"], "missing")
        self.assertEqual(plan["questions"][0]["options"], ["조건 유지", "조건 조정", "탐색 종료"])

    def test_old_request_basis_tampered_hit_and_missing_image_dependency_are_rejected(self):
        goal = self.target_map()
        result = self.search(goal)
        other = deepcopy(goal)
        other["basis"]["request_id"] = "another-request"
        self.assert_error("stale_context", build_candidate_cards, [result], other, self.catalog)
        changed = deepcopy(result)
        changed["hits"][0]["score"] = 10
        self.assert_error("invalid_output", build_candidate_cards, [changed], goal, self.catalog)
        changed = deepcopy(result)
        changed["basis"]["catalog"]["images"] = []
        self.assert_error("stale_context", build_candidate_cards, [changed], goal, self.catalog)


if __name__ == "__main__":
    unittest.main()
