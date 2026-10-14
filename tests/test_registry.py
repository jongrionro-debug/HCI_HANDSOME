import json
import unittest

from stylemate_memory.errors import StyleMateError
from stylemate_memory.registry import FEATURES, REGISTRY_VERSION, registry_metadata, validate_values


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


if __name__ == "__main__":
    unittest.main()
