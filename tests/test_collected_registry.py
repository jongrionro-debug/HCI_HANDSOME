"""29CM normalization rules and the lumi-pi-v3 runtime dictionary (ADR 0014, 0016)."""

from copy import deepcopy
import unittest

from scripts import build_29cm_registry as build
from stylemate_memory.catalog_mapping import build_product_map
from stylemate_memory.contracts import LUMI_PI_V3_REGISTRY_VERSION, V1_REGISTRY_VERSION
from stylemate_memory.graph.hypotheses import HYPOTHESIS_AXES, hypothesis_axes
from stylemate_memory.errors import StyleMateError
from stylemate_memory.registry import load_registry, product_fact_statuses


def record(pid, *, color="Charcoal / Black", fit_model="여유 있는 와이드 핏"):
    return {
        "format_version": "lumi-catalog-v1", "product_id": f"29cm-{pid}",
        "source": {"source_id": "29cm", "url": f"https://www.29cm.co.kr/products/{pid}",
                   "collected_at": "2026-11-17T12:00:00.000Z"},
        "title": "합성 슬랙스", "description": None, "garment_type": "Pants",
        "raw_metadata": {
            "group": "bottom", "brand": "합성브랜드", "price": 59000, "currency": "KRW",
            "color": color, "fabric": "Polyester 65%, Cotton 35%",
            "pi_raw": {"Type": {"source": "structured", "value": "슬랙스"},
                       "Brand": {"source": "structured", "value": "합성브랜드"},
                       "Price": {"source": "structured", "value": "59000 KRW"},
                       "Color": {"source": "text", "value": color}, "Fit": {"source": "none"},
                       "Fabric": {"source": "text", "value": "Polyester 65%, Cotton 35%"},
                       "Detail": {"source": "text", "value": "투턱, 밴딩 허리, 백 포켓"}},
            "pi_model_interpretation": {"Fit": {"value": fit_model, "evidence_type": "image_visual",
                                                "provenance": "model_interpretation"}},
        },
        "images": [], "labels": [],
    }


class NormalizationTests(unittest.TestCase):
    def test_rules_keep_only_dictionary_values(self):
        self.assertEqual(build.normalize("Color", "Charcoal / Black", "Pants"), ["차콜", "블랙"])
        self.assertEqual(build.normalize("Color", "LIGHT BLUE, NAVY", "Pants"), ["스카이블루", "네이비"])
        for placeholder in ("상세설명참조", "차이의 경우", ")"):
            self.assertEqual(build.normalize("Color", placeholder, "Pants"), [])
        self.assertEqual(build.normalize("Detail", "DETAIL INFO", "Pants"), [])
        self.assertEqual(build.normalize("Fit", "자연스럽게 떨어지는 실루엣", "Pants"), [])
        self.assertEqual(build.normalize("Fit", "세미 오버핏", "Hoodie"), ["세미오버"])
        self.assertEqual(build.normalize("Fabric", "Polyester 65%, Cotton 35%", "Pants"), ["면", "폴리에스터"])
        self.assertEqual(build.normalize("Detail", "타이트 핏", "Pants"), [])
        self.assertEqual(build.normalize("Type", "기타 팬츠", "Pants"), [])
        self.assertEqual(build.normalize("Type", "데님", "Skirt"), ["데님 스커트"])
        self.assertEqual([build.price_bucket(v) for v in (39999, 40000, 129999, 130000)],
                         ["4만원 미만", "4만~6만원", "9만~13만원", "13만원 이상"])


class PIV3MappingTests(unittest.TestCase):
    """lumi-pi-v3 (ADR 0014, 0016): English PI axes read from the registry, inferred model values kept apart."""

    @classmethod
    def setUpClass(cls):
        cls.registry = load_registry(LUMI_PI_V3_REGISTRY_VERSION)
        cls.pi = cls.registry.describe()["product_information"]

    def test_axes_and_hypothesis_space_follow_the_registry(self):
        self.assertEqual(hypothesis_axes(self.registry), tuple(a for a in self.pi if a != "Brand"))
        self.assertEqual(hypothesis_axes(load_registry(V1_REGISTRY_VERSION)), HYPOTHESIS_AXES)
        binding = {"domain": "PI", "feature": "Pattern", "values": ["Stripe"], "match": "any",
                   "polarity": "prefer", "strength": "soft"}
        self.registry.validate_binding(binding, "Top")
        with self.assertRaises(StyleMateError):
            self.registry.validate_binding(binding | {"values": ["줄무늬"]}, "Top")
        with self.assertRaises(StyleMateError):
            self.registry.validate_binding(binding, "Pants")

    def test_export_shape_maps_confirmed_metadata_and_inferred_labels(self):
        evidence = "Wide, square body with dropped shoulders in photo"
        row = {"format_version": "lumi-catalog-v1", "product_id": "shop-1",
               "source": {"source_id": "shop", "url": "https://example.invalid/products/1",
                          "collected_at": "2026-11-19T07:45:50+00:00"},
               "title": "SYNTHETIC TEE", "description": None, "garment_type": "Top",
               "raw_metadata": {"type": ["T-shirt"], "pattern": ["Stripe"], "tone": ["Dark"], "price_text": "75.00",
                                "pi_inferred": {"Fit": {"values": ["Oversized"], "method": "image_model",
                                                        "evidence": evidence}}},
               "images": [],
               "labels": [{"observation": {"domain": "PI", "feature": "Fit", "values": ["Oversized"]},
                           "status": "inferred",
                           "provenance": [{"kind": "model_interpretation",
                                           "source_field": "raw_metadata.pi_inferred.Fit.evidence", "quote": evidence,
                                           "verifier": None, "evidence_ref": None, "verified_at": None}]}]}
        product_map = build_product_map(deepcopy(row), raw_version=1, registry=self.registry, pi_only=True)
        statuses = {a["observation"]["feature"]: (a["status"], a["observation"]["values"]) for a in product_map["assertions"]
                    if a["observation"]["values"]}
        self.assertEqual(statuses["Pattern"], ("confirmed", ["Stripe"]))
        self.assertEqual(statuses["Tone"], ("confirmed", ["Dark"]))
        self.assertEqual(statuses["Fit"], ("inferred", ["Oversized"]))
        self.assertNotIn("Price", statuses)


class PIV3RegistryTests(unittest.TestCase):
    """lumi-pi-v3 (ADR 0016): tops and bottoms, Weight added, Silhouette for bottoms only."""

    def test_axes_garments_and_type_split(self):
        registry = load_registry(LUMI_PI_V3_REGISTRY_VERSION)
        description = registry.describe()
        pi = description["product_information"]
        self.assertEqual(list(pi), ["Type", "Brand", "Color", "Tone", "Pattern", "Fit", "Silhouette", "Length", "Weight",
                                    "Texture", "Fabric", "Detail", "Style"])
        self.assertEqual(description["execution"]["supported_garment_types"], ["Top", "Bottom"])
        self.assertEqual(pi["Silhouette"]["value_shape"]["groups"], ["bottom"])
        by_type = pi["Type"]["values_by_garment_type"]
        self.assertIn("Jeans", by_type["Bottom"])
        self.assertNotIn("Jeans", by_type["Top"])
        binding = {"domain": "PI", "feature": "Weight", "values": ["Light"], "match": "any",
                   "polarity": "prefer", "strength": "soft"}
        registry.validate_binding(binding, "Bottom")
        with self.assertRaises(StyleMateError):
            registry.validate_binding(binding, "Pants")
        self.assertEqual(product_fact_statuses(LUMI_PI_V3_REGISTRY_VERSION), ("confirmed", "inferred"))


if __name__ == "__main__":
    unittest.main()
