from contextlib import redirect_stdout
from copy import deepcopy
from importlib import resources
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from stylemate_memory.contracts import CONTRACT_VERSION, V1_REGISTRY_VERSION
from stylemate_memory.errors import StyleMateError
from stylemate_memory.registry import FEATURES, REGISTRY_VERSION, load_registry, registry_metadata, validate_values


class RegistryTests(unittest.TestCase):
    def test_consumer_registry_has_seventeen_features_and_json_metadata(self):
        self.assertEqual(len(FEATURES), 17)
        self.assertEqual(REGISTRY_VERSION, "consumer-17-v1")
        payload = registry_metadata()
        json.dumps(payload, ensure_ascii=False)
        self.assertIn("PDF", FEATURES["logo"]["notes"])
        self.assertIn("Garment-specific Length", FEATURES["length"]["pdf"]["attribute"])

    def test_canonical_values_and_length_are_target_specific(self):
        self.assertTrue(validate_values("fit", ["Slim"]))
        self.assertTrue(validate_values("formality", [3, 4], match="range"))
        self.assertTrue(validate_values("length", ["Ankle-length"], garment_type="Pants"))
        with self.assertRaises(StyleMateError):
            validate_values("length", ["Maxi"], garment_type="Pants")
        with self.assertRaises(StyleMateError):
            validate_values("fit", ["Very loose"])

    def test_match_and_none_are_distinct_contract_values(self):
        self.assertTrue(validate_values("logo", ["None"]))
        with self.assertRaises(StyleMateError):
            validate_values("logo", [None])
        with self.assertRaises(StyleMateError):
            validate_values("fit", ["Slim", "Regular"], match="range")

    def test_pdf_sources_are_feature_specific(self):
        self.assertEqual(FEATURES["texture"]["source"], ["Image"])
        self.assertEqual(FEATURES["functions"]["source"], ["Metadata"])
        self.assertEqual(FEATURES["season"]["source"], ["Metadata", "Inference"])
        self.assertEqual(FEATURES["logo"]["pdf"]["extraction_source"], ["Image"])


def pi_binding(feature="Color", values=None, match="any", polarity="prefer", strength="soft"):
    return {"domain": "PI", "feature": feature, "values": ["Navy"] if values is None else values,
            "match": match, "polarity": polarity, "strength": strength}


def fea_binding(**overrides):
    result = {"domain": "FEA", "category": "Functional", "subcategory": "Protection",
              "tag": "Warmth", "polarity": "require", "strength": "hard"}
    result.update(overrides)
    return result


class ParkRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(V1_REGISTRY_VERSION)
        self.source_path = Path(__file__).resolve().parents[1] / "output/feature-map/park-2025-feature-map.json"

    def assert_code(self, code, function, *args):
        with self.assertRaises(StyleMateError) as caught:
            function(*args)
        self.assertEqual(caught.exception.code, code)

    def test_source_resource_and_description_preserve_all_values_hierarchy_and_provenance(self):
        packaged = resources.files("stylemate_memory").joinpath("resources/park-2025-feature-map.json").read_bytes()
        self.assertEqual(packaged, self.source_path.read_bytes())
        source = json.loads(packaged)
        description = self.registry.describe()
        execution = description.pop("execution")
        self.assertEqual(description, source)
        self.assertNotEqual(CONTRACT_VERSION, self.registry.version)
        self.assertFalse(execution["range_supported"])
        self.assertIsNone(execution["price_currency"])
        self.assertIsNone(execution["price_boundary_inclusion"])
        description["product_information"]["Color"]["values"].clear()
        self.registry.validate_binding(pi_binding(), "Pants")

    def test_every_published_pi_value_and_any_all_bindings(self):
        for feature, meta in self.registry.describe()["product_information"].items():
            if meta["values"] is None:
                continue
            for value in meta["values"]:
                with self.subTest(feature=feature, value=value):
                    self.registry.validate_binding(pi_binding(feature, [value]), "Pants")
                    self.registry.validate_observation({"domain": "PI", "feature": feature, "values": [value]}, "Pants")
        self.registry.validate_binding(pi_binding("Fabric", ["Cotton", "Wool"], "all"), "Pants")
        self.registry.validate_binding(pi_binding("Fit", ["Wide", "Slim"], "any", "avoid", "hard"), "Pants")

    def test_all_thirty_fea_paths_and_product_presence_are_separate(self):
        count = 0
        for category, subcategories in self.registry.describe()["consumer_needs_taxonomy"].items():
            for subcategory, entries in subcategories.items():
                for entry in entries:
                    path = {"domain": "FEA", "category": category, "subcategory": subcategory, "tag": entry["attribute"]}
                    self.registry.validate_binding({**path, "polarity": "avoid", "strength": "soft"}, "Pants")
                    for present in (True, False, None):
                        self.registry.validate_observation({**path, "present": present}, "Pants")
                    count += 1
        self.assertEqual(count, 30)
        self.assert_code("unsupported_mapping", self.registry.validate_binding, fea_binding(subcategory="Comfort"), "Pants")
        self.assert_code("unsupported_mapping", self.registry.validate_binding, fea_binding(tag="waterproof"), "Pants")

    def test_brand_examples_are_not_enum_and_prices_are_labels_without_range_semantics(self):
        for example in self.registry.describe()["product_information"]["Brand"]["published_examples"] + ["Invented brand"]:
            self.assert_code("unsupported_mapping", self.registry.validate_binding, pi_binding("Brand", [example]), "Pants")
        self.registry.validate_binding(pi_binding("Price", ["43,900~54,360"]), "Pants")
        self.assert_code("unsupported_mapping", self.registry.validate_binding, pi_binding("Price", ["43900"]), "Pants")
        self.assert_code("unsupported_mapping", self.registry.validate_binding, pi_binding("Price", ["0~43,900", "89,000~"], "range"), "Pants")
        self.assert_code("invalid_input", self.registry.validate_binding, pi_binding("Price", [43900]), "Pants")

    def test_unknown_values_do_not_convert_legacy_meanings_or_selector_types(self):
        for feature, values in (("Fit", ["Relaxed"]), ("Fabric", ["Denim"]), ("Type", ["Pants"]), ("Color", ["navy"])):
            self.assert_code("unsupported_mapping", self.registry.validate_binding, pi_binding(feature, values), "Pants")
        for values in ([], ["Navy", "Navy"], [True], [None], "Navy", [["Navy"]]):
            self.assert_code("invalid_input", self.registry.validate_binding, pi_binding(values=values), "Pants")
        self.assert_code("unsupported_mapping", self.registry.validate_binding, pi_binding("fit", ["Slim"]), "Pants")
        self.assertTrue(validate_values("fit", ["Relaxed"]))
        self.assertTrue(validate_values("fabric", ["Denim"]))

    def test_unsupported_targets_do_not_gain_values_from_pi_type(self):
        for garment in (None, "Shirt", "Jacket", "Dress", "Jeans", "pants"):
            for binding in (pi_binding("Type", ["Jeans"]), fea_binding()):
                self.assert_code("unsupported_mapping", self.registry.validate_binding, binding, garment)
            self.assert_code("unsupported_mapping", self.registry.validate_observation,
                             {"domain": "PI", "feature": "Color", "values": ["Navy"]}, garment)
        # Null is an unknown observation, not a claim of support/compliance.
        self.registry.validate_observation({"domain": "PI", "feature": "Brand", "values": None}, "Pants")
        self.registry.validate_observation({"domain": "PI", "feature": "Type", "values": None}, "Shirt")

    def test_bindings_reject_authority_fields_and_observations_reject_user_preferences(self):
        for extra in ({"confirmed": True}, {"registry_version": V1_REGISTRY_VERSION}, {"present": True}):
            self.assert_code("invalid_input", self.registry.validate_binding, {**fea_binding(), **extra}, "Pants")
        invalid = pi_binding()
        del invalid["strength"]
        self.assert_code("invalid_input", self.registry.validate_binding, invalid, "Pants")
        path = {"domain": "FEA", "category": "Functional", "subcategory": "Protection", "tag": "Warmth"}
        for value in (1, "true", "require", []):
            self.assert_code("invalid_input", self.registry.validate_observation, {**path, "present": value}, "Pants")
        self.assert_code("invalid_input", self.registry.validate_observation,
                         {**path, "present": True, "polarity": "require"}, "Pants")
        self.assert_code("invalid_input", self.registry.validate_binding, {"domain": "other"}, "Pants")

    def test_indifference_keeps_null_and_does_not_claim_hard_values(self):
        binding = {**pi_binding(), "values": None, "match": None, "polarity": "indifferent"}
        self.registry.validate_binding(binding, "Pants")
        self.registry.validate_binding(fea_binding(polarity="indifferent", strength="soft"), "Pants")
        for changes in ({"values": []}, {"values": ["Navy"]}, {"match": "any"}, {"strength": "hard"}):
            self.assert_code("invalid_input", self.registry.validate_binding, {**binding, **changes}, "Pants")
        self.assert_code("invalid_input", self.registry.validate_binding, {**pi_binding(), "values": None}, "Pants")

    def test_empty_target_includes_all_fields_and_keeps_unsupported_separate(self):
        target = self.registry.empty_target("pants-1", "Pants")
        self.assertEqual(len(target["product_information"]), 7)
        self.assertEqual(target["product_information"]["Brand"]["status"], "unsupported")
        self.assertEqual(target["product_information"]["Fit"]["status"], "unspecified")
        self.assertTrue(all(v["values"] is None for v in target["product_information"].values()))
        count = 0
        for category, subcategories in target["consumer_needs"].items():
            for subcategory, tags in subcategories.items():
                for tag, value in tags.items():
                    self.assertIsNone(value["preference"])
                    self.registry.validate_target_value({"domain": "FEA", "category": category, "subcategory": subcategory, "tag": tag}, value, "Pants")
                    count += 1
        self.assertEqual(count, 30)
        shirt = self.registry.empty_target("shirt-1", "Shirt")
        self.assertEqual(shirt["garment_type"], "Shirt")
        self.assertTrue(all(v["status"] == "unsupported" for v in shirt["product_information"].values()))
        target["product_information"]["Color"]["constraint_ids"].append("c-1")
        self.assertEqual(target["product_information"]["Fit"]["constraint_ids"], [])
        self.assertEqual(self.registry.empty_target("pants-2", "Pants")["product_information"]["Color"]["constraint_ids"], [])

    def test_target_status_and_null_value_shapes_do_not_infer_confirmation(self):
        path = {"domain": "PI", "feature": "Fit"}
        fea_path = {k: v for k, v in fea_binding().items() if k not in ("polarity", "strength")}
        for status in self.registry.describe()["execution"]["target_statuses"]:
            known = status in ("specified", "inferred")
            pi = {"status": status, "values": ["Wide"] if known else None, "constraint_ids": [], "source_refs": []}
            fea = {"status": status, "preference": "avoid" if known else None, "constraint_ids": [], "source_refs": []}
            self.registry.validate_target_value(path, pi, "Pants")
            self.registry.validate_target_value(fea_path, fea, "Pants")
            self.assert_code("invalid_input", self.registry.validate_target_value, path, {**pi, "values": None if known else ["Wide"]}, "Pants")
        value = {"status": "unspecified", "values": None, "constraint_ids": [], "source_refs": []}
        self.assert_code("invalid_input", self.registry.validate_target_value, path, {**value, "status": "confirmed"}, "Pants")
        self.assert_code("invalid_input", self.registry.validate_target_value, path, {**value, "source_refs": [{"id": "missing-type-version"}]}, "Pants")

    def test_unavailable_or_corrupt_resource_has_stable_error(self):
        resource = json.loads(self.source_path.read_text(encoding="utf-8"))
        wrong_count = deepcopy(resource)
        wrong_count["counts"]["consumer_needs_attributes"] = 29
        wrong_hierarchy = deepcopy(resource)
        wrong_hierarchy["consumer_needs_taxonomy"]["Functional"]["Protection"] = []
        for raw in ("{", "[]", json.dumps({**resource, "version": REGISTRY_VERSION}), json.dumps(wrong_count), json.dumps(wrong_hierarchy)):
            with patch("stylemate_memory.registry.resources.files") as files:
                files.return_value.joinpath.return_value.read_text.return_value = raw
                self.assert_code("registry_unavailable", load_registry, V1_REGISTRY_VERSION)
        with patch("stylemate_memory.registry.resources.files", side_effect=FileNotFoundError):
            self.assert_code("registry_unavailable", load_registry, V1_REGISTRY_VERSION)
            self.assertEqual(registry_metadata()["version"], REGISTRY_VERSION)

    def test_explicit_cli_registry_selection_preserves_the_legacy_default(self):
        from stylemate_memory.cli import main
        for args, expected in ((["features"], REGISTRY_VERSION), (["features", "--registry", REGISTRY_VERSION], REGISTRY_VERSION),
                               (["features", "--registry", V1_REGISTRY_VERSION], V1_REGISTRY_VERSION)):
            output = io.StringIO()
            with redirect_stdout(output):
                self.assertEqual(main(args), 0)
            self.assertEqual(json.loads(output.getvalue())["version"], expected)
        self.assertEqual(registry_metadata(V1_REGISTRY_VERSION)["version"], V1_REGISTRY_VERSION)
        self.assert_code("unsupported_contract", load_registry, REGISTRY_VERSION)
        self.assert_code("unsupported_contract", registry_metadata, "unknown-registry")


if __name__ == "__main__":
    unittest.main()
