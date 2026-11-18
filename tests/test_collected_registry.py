"""lumi-29cm-v1: collected PI value dictionary, complete-record filter, inferred matching."""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unittest.mock

from scripts import build_29cm_registry as build
from stylemate_memory.catalog_mapping import build_product_map
from stylemate_memory.contracts import COLLECTED_29CM_REGISTRY_VERSION, V1_REGISTRY_VERSION
from stylemate_memory.errors import StyleMateError
from stylemate_memory.product_search import _evaluate
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

    def test_only_records_with_all_seven_axes_are_exported(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            rows = [record("1"), record("2", color="상세설명참조")]
            (root / "lumi-catalog-v1.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                                                        encoding="utf-8")
            argv = ["build", "--catalog-dir", str(root), "--registry", str(root / "registry.json")]
            with unittest.mock.patch("sys.argv", argv), unittest.mock.patch("builtins.print"):
                self.assertEqual(build.main(), 0)
            report = json.loads((root / "complete_report.json").read_text(encoding="utf-8"))
            self.assertEqual((report["input_records"], report["complete_records"]), (2, 1))
            self.assertEqual(report["missing_by_axis"]["Color"], 1)
            exported = [json.loads(line) for line in (root / "lumi-catalog-complete-v1.jsonl").read_text().splitlines()]
            self.assertEqual([r["product_id"] for r in exported], ["29cm-1"])
            raw = exported[0]["raw_metadata"]
            self.assertEqual((raw["color"], raw["color_text"], raw["price_range"]), (["차콜", "블랙"], "Charcoal / Black", ["4만~6만원"]))
            self.assertNotIn("fit", raw)  # model value stays a labelled inference
            label = exported[0]["labels"][0]
            self.assertEqual((label["observation"]["feature"], label["status"], label["provenance"][0]["kind"]),
                             ("Fit", "inferred", "model_interpretation"))
            registry = json.loads((root / "registry.json").read_text(encoding="utf-8"))
            self.assertEqual(registry["product_information"]["Brand"]["values"], ["합성브랜드"])


class CollectedRegistryTests(unittest.TestCase):
    def setUp(self):
        self.registry = load_registry(COLLECTED_29CM_REGISTRY_VERSION)
        self.pi = self.registry.describe()["product_information"]

    def test_axes_fea_and_garment_scoped_type(self):
        description = self.registry.describe()
        self.assertEqual(list(self.pi), ["Type", "Brand", "Price", "Color", "Fit", "Fabric", "Detail"])
        self.assertIn("Knit/Sweater", description["execution"]["supported_garment_types"])
        self.assertTrue(description["execution"]["accept_inferred_product_pi"])
        pants_type = self.pi["Type"]["values_by_garment_type"]["Pants"][0]
        binding = {"domain": "PI", "feature": "Type", "values": [pants_type], "match": "any",
                   "polarity": "prefer", "strength": "soft"}
        self.registry.validate_binding(binding, "Pants")
        with self.assertRaises(StyleMateError):
            self.registry.validate_binding(binding, "Knit/Sweater")
        with self.assertRaises(StyleMateError):
            self.registry.validate_binding(binding | {"feature": "Color", "values": ["Navy"]}, "Pants")
        # The Park dictionary and its confirmed-only matching are unchanged.
        self.assertEqual(load_registry(V1_REGISTRY_VERSION).describe()["execution"]["supported_garment_types"], ["Pants"])
        self.assertEqual(product_fact_statuses(V1_REGISTRY_VERSION), ("confirmed",))
        self.assertEqual(product_fact_statuses(COLLECTED_29CM_REGISTRY_VERSION), ("confirmed", "inferred"))

    def test_exported_record_imports_maps_and_inferred_fit_matches(self):
        row = record("1")
        resolved = build.resolve(row)
        exported = build.export_record(row, resolved)
        brand = self.pi["Brand"]["values"][0]
        exported["raw_metadata"]["brand"] = [brand]
        product_map = build_product_map(deepcopy(exported), raw_version=1, registry=self.registry, pi_only=True)
        statuses = {a["observation"]["feature"]: (a["status"], a["observation"]["values"]) for a in product_map["assertions"]}
        self.assertEqual(statuses["Color"], ("confirmed", ["차콜", "블랙"]))
        self.assertEqual(statuses["Brand"], ("confirmed", [brand]))
        self.assertEqual(statuses["Fit"], ("inferred", ["와이드", "루즈·릴랙스"]))
        constraint = {"id": "fit", "confirmed": True, "binding": {"domain": "PI", "feature": "Fit", "values": ["와이드"],
                      "match": "any", "polarity": "prefer", "strength": "soft"}}
        hit = _evaluate(product_map, [constraint], self.registry, "Pants")
        self.assertEqual((hit["matched_constraint_ids"], hit["score"]), (["fit"], 1.0))


if __name__ == "__main__":
    unittest.main()
