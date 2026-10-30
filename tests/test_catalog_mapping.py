from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stylemate_memory.catalog import Catalog
from stylemate_memory.catalog_io import import_file, load_records
from stylemate_memory.catalog_mapping import build_product_map, map_catalog, review_product_map
from stylemate_memory.contracts import V1_REGISTRY_VERSION
from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import OpenAIResponsesGateway
from stylemate_memory.model_io import FakeModelGateway
from stylemate_memory.registry import load_registry


FIXTURES = Path(__file__).parent / "fixtures" / "catalog"


def pi(feature, values):
    return {"domain": "PI", "feature": feature, "values": values}


def warmth(present=True):
    return {"domain": "FEA", "category": "Functional", "subcategory": "Protection",
            "tag": "Warmth", "present": present}


def provenance(kind="verified_label", source_field=None, quote=None, evidence_ref="synthetic-lab-check"):
    return {"kind": kind, "source_field": source_field, "quote": quote,
            "verifier": "synthetic-verifier" if kind in ("provided_label", "verified_label") else None,
            "evidence_ref": evidence_ref,
            "verified_at": "2026-10-29T12:00:00+09:00" if kind == "verified_label" else None}


def assertion(observation, status="confirmed", evidence=None):
    return {"observation": observation, "status": status,
            "provenance": [provenance() if evidence is None else evidence]}


def lookup(product_map, *path):
    for a in product_map["assertions"]:
        o = a["observation"]
        key = ("PI", o["feature"]) if o["domain"] == "PI" else ("FEA", o["category"], o["subcategory"], o["tag"])
        if key == path:
            return a
    raise AssertionError(path)


class RecordingGateway(FakeModelGateway):
    def __init__(self, factory):
        super().__init__()
        self.factory = factory
        self.calls = []

    def complete(self, instructions, payload, schema):
        self.calls.append(deepcopy((instructions, payload, schema)))
        return self.factory(payload)


def suggestion(payload, observation, field="description", quote="주름"):
    source = next(s for s in payload["sources"] if s["source_field"] == field)
    return {"observation": observation, "citations": [{"source_id": source["source_id"], "quote": quote}]}


class ProductMappingTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(V1_REGISTRY_VERSION)
        self.records = load_records(FIXTURES / "mapping.json")
        self.record = self.records[0]

    def build(self, record=None, gateway=None, raw_version=1):
        return build_product_map(self.record if record is None else record, raw_version=raw_version,
                                 registry=self.registry, gateway=gateway)

    def assert_error(self, code, operation, *args, **kwargs):
        with self.assertRaises(StyleMateError) as caught:
            operation(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)
        return caught.exception

    def test_canonical_technical_metadata_is_confirmed_with_exact_sources(self):
        original = deepcopy(self.record)
        mapped = self.build(raw_version=7)
        self.assertEqual((mapped["subject"], mapped["product_id"], mapped["raw_version"], mapped["map_version"]),
                         ("product", self.record["product_id"], 7, 1))
        self.assertEqual(len(mapped["assertions"]), 37)
        for feature, expected in (("Type", ["Slacks"]), ("Color", ["Navy"]),
                                  ("Fit", ["Wide"]), ("Fabric", ["Cotton", "Polyester"])):
            with self.subTest(feature=feature):
                a = lookup(mapped, "PI", feature)
                self.assertEqual(a["status"], "confirmed")
                self.assertEqual(a["observation"]["values"], expected)
                self.assertEqual(a["provenance"][0]["kind"], "raw_metadata")
                self.assertEqual(a["provenance"][0]["source_field"], "raw_metadata.supplier_" + feature.lower())
        self.assertEqual(self.record, original)

    def test_case_normalization_is_inferred_and_missing_values_remain_null(self):
        mapped = self.build(self.records[1])
        color = lookup(mapped, "PI", "Color")
        self.assertEqual((color["status"], color["observation"]["values"]), ("inferred", ["Navy"]))
        self.assertEqual(color["provenance"][0]["quote"], " navy ")
        for feature in ("Type", "Fit", "Fabric", "Brand", "Price", "Detail"):
            self.assertEqual(lookup(mapped, "PI", feature)["observation"]["values"], None)
        self.assertEqual(lookup(mapped, "PI", "Fit")["status"], "unknown")

    def test_price_boundaries_brand_examples_reviews_and_need_tags_are_not_facts(self):
        for price in (43899, 43900, 54360, 69000, 89000, "KRW 43900"):
            with self.subTest(price=price):
                record = deepcopy(self.record)
                record["raw_metadata"]["supplier_price"] = price
                mapped = self.build(record)
                self.assertEqual(lookup(mapped, "PI", "Price")["status"], "unknown")
                self.assertEqual(lookup(mapped, "PI", "Brand")["status"], "unknown")
                self.assertTrue(all(a["status"] == "unknown" for a in mapped["assertions"]
                                    if a["observation"]["domain"] == "FEA"))
        record["raw_metadata"]["supplier_price"] = "43,900~54,360"
        self.assertEqual(lookup(self.build(record), "PI", "Price")["status"], "confirmed")
        review = review_product_map(mapped)
        self.assertIn("Brand", {item["path"][-1] for item in review})

    def test_supplied_verified_labels_and_unverified_labels_keep_authority_separate(self):
        record = deepcopy(self.record)
        record["labels"] = [assertion(warmth()), assertion(pi("Detail", ["Pleats"]), "inferred",
                            provenance("provided_label", evidence_ref="synthetic-stylist-note"))]
        mapped = self.build(record)
        self.assertEqual(lookup(mapped, "FEA", "Functional", "Protection", "Warmth")["status"], "confirmed")
        self.assertEqual(lookup(mapped, "PI", "Detail")["status"], "inferred")
        record["labels"][1]["status"] = "confirmed"
        self.assert_error("invalid_input", self.build, record)

    def test_direct_metadata_must_use_the_matching_technical_axis(self):
        record = deepcopy(self.record)
        record["raw_metadata"]["review"] = "Navy"
        record["labels"] = [assertion(pi("Color", ["Navy"]), evidence=provenance(
            "raw_metadata", "raw_metadata.review", "Navy", None))]
        self.assert_error("invalid_input", self.build, record)
        record["labels"][0]["provenance"][0]["source_field"] = "raw_metadata.supplier_color"
        self.assertEqual(lookup(self.build(record), "PI", "Color")["status"], "confirmed")

    def test_direct_field_and_value_must_be_supported_by_the_same_citation(self):
        record = deepcopy(self.record)
        record["raw_metadata"]["review"] = "Navy"
        record["raw_metadata"]["supplier_color"] = "color undecided"
        record["labels"] = [{"observation": pi("Color", ["Navy"]), "status": "confirmed", "provenance": [
            provenance("raw_metadata", "raw_metadata.review", "Navy", None),
            provenance("raw_metadata", "raw_metadata.supplier_color", "color", None),
        ]}]
        self.assert_error("invalid_input", self.build, record)

    def test_label_and_raw_conflict_is_preserved_and_not_hard_eligible(self):
        record = deepcopy(self.record)
        record["labels"] = [assertion(pi("Color", ["Black"]))]
        color = lookup(self.build(record), "PI", "Color")
        self.assertEqual(color["status"], "conflict")
        self.assertEqual(set(color["observation"]["values"]), {"Black", "Navy"})
        self.assertEqual(len(color["provenance"]), 2)

    def test_unknown_label_does_not_hide_direct_metadata(self):
        record = deepcopy(self.record)
        record["labels"] = [{"observation": pi("Color", None), "status": "unknown", "provenance": []}]
        self.assertEqual(lookup(self.build(record), "PI", "Color")["status"], "confirmed")

    def test_invalid_label_enum_quote_and_source_are_rejected(self):
        base = load_records(FIXTURES / "valid.json")[0]
        cases = []
        invalid = deepcopy(base)
        invalid["labels"][0]["observation"]["values"] = ["Invisible blue"]
        cases.append(("unsupported_mapping", invalid))
        for key, value in (("quote", "not in raw record"), ("source_field", "raw_metadata.missing"),
                           ("verified_at", None), ("verifier", None), ("evidence_ref", None)):
            invalid = deepcopy(base)
            invalid["labels"][0]["provenance"][0][key] = value
            cases.append(("invalid_input", invalid))
        for code, record in cases:
            with self.subTest(record=record["labels"][0]):
                self.assert_error(code, self.build, record)

    def test_other_garments_do_not_reuse_pants_values_or_call_model(self):
        record = deepcopy(self.record)
        record["garment_type"] = "Shirt"
        gateway = RecordingGateway(lambda _: self.fail("unsupported garment called model"))
        mapped = self.build(record, gateway)
        self.assertTrue(all(a["status"] == "unknown" for a in mapped["assertions"]))
        self.assertEqual(gateway.calls, [])
        record["labels"] = [assertion(pi("Fit", ["Wide"]))]
        self.assert_error("unsupported_mapping", self.build, record, gateway)

    def test_invalid_raw_versions_are_rejected(self):
        for value in (True, 0, -1, "1", None):
            with self.subTest(raw_version=value):
                self.assert_error("invalid_input", self.build, raw_version=value)

    def test_model_normalization_is_cited_inferred_and_does_not_fill_other_paths(self):
        gateway = RecordingGateway(lambda p: {"assertions": [suggestion(p, pi("Detail", ["Pleats"]), quote="주름")]})
        mapped = self.build(self.records[1], gateway)
        detail = lookup(mapped, "PI", "Detail")
        self.assertEqual((detail["status"], detail["observation"]["values"]), ("inferred", ["Pleats"]))
        self.assertEqual(detail["provenance"][0]["source_field"], "description")
        self.assertEqual(detail["provenance"][0]["quote"], "주름")
        self.assertIsNone(detail["provenance"][0]["verified_at"])
        self.assertEqual(lookup(mapped, "PI", "Fabric")["status"], "unknown")

    def test_model_review_interpretation_is_never_confirmed_performance(self):
        gateway = RecordingGateway(lambda p: {"assertions": [suggestion(p, warmth(), "raw_metadata.review", "따뜻한 느낌")]})
        mapped = self.build(gateway=gateway)
        a = lookup(mapped, "FEA", "Functional", "Protection", "Warmth")
        self.assertEqual(a["status"], "inferred")
        self.assertEqual(a["provenance"][0]["kind"], "model_interpretation")
        self.assertEqual(lookup(mapped, "FEA", "Functional", "Comfort", "Waterproof")["status"], "unknown")

    def test_model_invalid_quote_enum_source_and_duplicate_path_are_rejected(self):
        def valid(payload):
            return {"assertions": [suggestion(payload, pi("Detail", ["Pleats"]), quote="주름")]}

        def changed(mutation):
            def output(payload):
                result = valid(payload)
                mutation(result)
                return result
            return RecordingGateway(output)

        cases = [
            lambda r: r["assertions"][0]["citations"][0].update(quote="invented quote"),
            lambda r: r["assertions"][0]["citations"][0].update(source_id="other-product-source"),
            lambda r: r["assertions"][0]["observation"].update(values=["Regular"]),
            lambda r: r["assertions"][0].update(status="confirmed"),
            lambda r: r["assertions"][0].update(version=7),
            lambda r: r["assertions"][0].update(citations=[]),
            lambda r: r["assertions"].append(deepcopy(r["assertions"][0])),
            lambda r: r.update(save=True),
        ]
        for mutation in cases:
            with self.subTest(mutation=mutation):
                self.assert_error("invalid_output", self.build, self.records[1], changed(mutation))

    def test_model_cannot_override_direct_fact_map_price_or_brand(self):
        for observation in (pi("Color", ["Black"]), pi("Brand", ["1989STANDARD"]), pi("Price", ["0~43,900"])):
            gateway = RecordingGateway(lambda p: {"assertions": [suggestion(p, observation, "title", "합성")]})
            with self.subTest(observation=observation):
                self.assert_error("invalid_output", self.build, gateway=gateway)

    def test_image_labels_remain_inferred_and_reference_supplied_image_revision(self):
        record = deepcopy(self.record)
        record["labels"] = [assertion(warmth(), "inferred", provenance(
            "model_interpretation", evidence_ref=record["images"][0]["image_id"]))]
        first = self.build(record)
        record["images"][0]["source_revision"] = "synthetic-image-v2"
        second = self.build(record)
        a = lookup(first, "FEA", "Functional", "Protection", "Warmth")
        b = lookup(second, "FEA", "Functional", "Protection", "Warmth")
        self.assertEqual(a["status"], "inferred")
        self.assertNotEqual(a["provenance"][0]["evidence_ref"], b["provenance"][0]["evidence_ref"])
        record["labels"][0]["provenance"][0]["evidence_ref"] = "missing-image"
        self.assert_error("invalid_input", self.build, record)

    def test_photo_cannot_be_a_performance_verification_even_with_verifier_fields(self):
        record = deepcopy(self.record)
        record["labels"] = [assertion(warmth(), evidence=provenance(
            evidence_ref=record["images"][0]["image_id"]))]
        self.assert_error("invalid_input", self.build, record)

    def test_no_image_io_url_or_path_is_sent_to_model(self):
        gateway = RecordingGateway(lambda _: {"assertions": []})
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
                patch("pathlib.Path.read_bytes", side_effect=AssertionError("image I/O forbidden")), \
                patch("os.getenv", side_effect=AssertionError("environment forbidden")):
            self.build(gateway=gateway)
        instructions, payload, schema = gateway.calls[0]
        serialized = json.dumps(payload)
        self.assertNotIn(self.record["product_id"], serialized)
        self.assertNotIn("https://", serialized)
        self.assertNotIn("images", payload)
        self.assertIn("DATA", instructions)
        self.assertFalse(schema["additionalProperties"])

    def test_openai_gateway_fake_transport_accepts_product_json_schema(self):
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append(payload)
            return {"status": "completed", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": '{"assertions": []}'}]}]}

        gateway = OpenAIResponsesGateway(api_key="synthetic-key-only", transport=transport)
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")):
            mapped = self.build(gateway=gateway)
        self.assertEqual(lookup(mapped, "PI", "Detail")["status"], "unknown")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["text"]["format"]["type"], "json_schema")


class CatalogMappingPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="lumi-product-mapping-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.registry = load_registry(V1_REGISTRY_VERSION)
        self.catalog = Catalog(self.root / "catalog.sqlite3")
        self.addCleanup(self.catalog.close)
        import_file(self.catalog, FIXTURES / "mapping.json")
        self.records = self.catalog.export_records()
        self.pid = self.records[0]["product_id"]

    def run_mapping(self, **kwargs):
        return map_catalog(self.catalog, registry=self.registry, **kwargs)

    def test_import_map_save_retry_and_restart_are_idempotent(self):
        first = self.run_mapping()
        self.assertEqual(first["status"], "complete")
        self.assertEqual(first["failures"], [])
        before = self.catalog.current_versions([r["product_id"] for r in self.records], [])
        second = self.run_mapping()
        self.assertEqual(second, first)
        self.assertEqual(self.catalog.current_versions([self.pid], ["synthetic-mapping-image"])["products"][0]["map_version"], 1)
        with Catalog(self.root / "catalog.sqlite3") as reopened:
            self.assertEqual(map_catalog(reopened, registry=self.registry), first)
            self.assertEqual(reopened.current_versions([r["product_id"] for r in self.records], []), before)

    def test_partial_model_failure_identifies_retry_product_without_saving_failed_map(self):
        def partial(payload):
            if "자유 표현" in payload["sources"][0]["content"]:
                raise StyleMateError("provider_timeout", "model timeout")
            return {"assertions": []}

        report = self.run_mapping(gateway=RecordingGateway(partial))
        failed_id = self.records[1]["product_id"]
        self.assertEqual(report["status"], "partial")
        self.assertEqual([e["product_id"] for e in report["failures"]], [failed_id])
        self.assertEqual(report["failures"][0]["code"], "provider_timeout")
        with self.assertRaises(StyleMateError) as caught:
            self.catalog.get_product_map(failed_id)
        self.assertEqual(caught.exception.code, "context_blocked")
        retry = self.run_mapping(product_ids=[failed_id], gateway=FakeModelGateway({"assertions": []}))
        self.assertEqual(retry["status"], "complete")
        self.assertEqual(len(self.catalog.export_records()), 2)

    def test_map_change_and_raw_change_update_freshness_and_reject_old_writes(self):
        first = self.run_mapping()
        before = self.catalog.current_versions([self.pid], ["synthetic-mapping-image"])
        gateway = RecordingGateway(lambda p: {"assertions": [suggestion(p, warmth(), "raw_metadata.review", "따뜻한 느낌")]})
        changed = self.run_mapping(product_ids=[self.pid], gateway=gateway)
        self.assertEqual(changed["maps"][0]["map_version"], 2)
        self.assertNotEqual(before, self.catalog.current_versions([self.pid], ["synthetic-mapping-image"]))
        record = deepcopy(self.records[0])
        record["raw_metadata"]["supplier_color"] = "Black"
        self.catalog.import_records([record])
        blocked = self.run_mapping(product_ids=[self.pid])
        self.assertEqual(blocked["status"], "failed")
        self.assertEqual(blocked["failures"][0]["code"], "version_conflict")
        stale = self.run_mapping(product_ids=[self.pid], expected_map_versions={self.pid: 1})
        self.assertEqual(stale["status"], "failed")
        updated = self.run_mapping(product_ids=[self.pid], expected_map_versions={self.pid: 2})
        self.assertEqual(updated["status"], "complete")
        self.assertEqual((updated["maps"][0]["raw_version"], updated["maps"][0]["map_version"]), (2, 3))
        self.assertEqual(lookup(updated["maps"][0], "PI", "Color")["observation"]["values"], ["Black"])
        self.assertEqual(first["maps"][0]["map_version"], 1)

    def test_image_only_change_is_visible_in_candidate_dependencies(self):
        self.run_mapping()
        before = self.catalog.current_versions([self.pid], ["synthetic-mapping-image"])
        record = deepcopy(self.records[0])
        record["images"][0]["source_revision"] = "synthetic-image-v2"
        self.catalog.import_records([record])
        after = self.catalog.current_versions([self.pid], ["synthetic-mapping-image"])
        self.assertEqual(before["products"], after["products"])
        self.assertNotEqual(before["images"], after["images"])

    def test_raw_change_during_model_call_cannot_be_saved(self):
        def mutate(_):
            record = deepcopy(self.records[0])
            record["description"] = "동시 수정된 합성 원자료"
            self.catalog.import_records([record])
            return {"assertions": []}

        report = self.run_mapping(product_ids=[self.pid], gateway=RecordingGateway(mutate))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failures"][0]["code"], "version_conflict")

    def test_image_change_during_model_call_cannot_be_saved(self):
        def mutate(_):
            record = deepcopy(self.records[0])
            record["images"][0]["source_revision"] = "synthetic-image-v2"
            self.catalog.import_records([record])
            return {"assertions": []}

        report = self.run_mapping(product_ids=[self.pid], gateway=RecordingGateway(mutate))
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["failures"][0]["code"], "version_conflict")

    def test_rebuilding_image_interpretation_changes_map_version(self):
        record = deepcopy(self.records[0])
        record["labels"] = [assertion(warmth(), "inferred", provenance(
            "model_interpretation", evidence_ref=record["images"][0]["image_id"]))]
        self.catalog.import_records([record])
        first = self.run_mapping(product_ids=[self.pid])["maps"][0]
        record["images"][0]["source_revision"] = "synthetic-image-v2"
        self.catalog.import_records([record])
        second = self.run_mapping(product_ids=[self.pid])["maps"][0]
        self.assertEqual(first["raw_version"], second["raw_version"])
        self.assertEqual(second["map_version"], first["map_version"] + 1)

    def test_invalid_model_result_does_not_replace_previous_map(self):
        self.run_mapping()
        before = self.catalog.get_product_map(self.pid)
        failed = self.run_mapping(product_ids=[self.pid], gateway=FakeModelGateway({"assertions": [], "confirmed": True}))
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(self.catalog.get_product_map(self.pid), before)


if __name__ == "__main__":
    unittest.main()
