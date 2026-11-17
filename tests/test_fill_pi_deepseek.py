"""29CM PI fill validation and lumi-catalog-v1 export; fake gateway, no network."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import unittest.mock

from scripts import fill_pi_deepseek as fill
from stylemate_memory.catalog_validation import validate_record
from stylemate_memory.errors import StyleMateError
from stylemate_memory.registry import ParkRegistry

RECORD = {
    "product_id": "2545554", "url": "https://www.29cm.co.kr/products/2545554", "group": "bottom", "gender": "men",
    "breadcrumb": ["남성의류", "하의", "쇼트"], "subcategory": "남성의류 > 하의 > 쇼트",
    "title": "Curtis Color Point Half Pants Charcoal", "brand": "홀리선",
    "price": {"amount": 92000, "currency": "KRW", "list_amount": 115000, "availability": "InStock"},
    "pi": {"Type": {"source": "structured", "value": "쇼트"}, "Brand": {"source": "structured", "value": "홀리선"},
           "Price": {"source": "structured", "value": "92000 KRW"}, "Color": {"source": "referred", "value": "상품상세 참조"},
           "Fit": {"source": "none"}, "Fabric": {"source": "text", "value": "폴리에스터 45%, 면 55%"}, "Detail": {"source": "none"}},
    "description": "- 투턱 디테일 적용\n- 시원한 하프 팬츠",
    "product_info": "제품 소재\t폴리에스터 45%, 면 55%\n색상\t상세 페이지 참고",
    "images": [{"index": 0, "source_url": "https://img.29cm.co.kr/item/a.jpg", "download_status": "downloaded",
                "local_path": "images/2545554/0.jpg", "sha256": "a" * 64, "bytes": 10},
               {"index": 1, "source_url": "https://img.29cm.co.kr/item/b.jpg", "download_status": "failed"}],
    "crawled_at": "2026-11-17T12:00:00.000Z",
}


class FakeGateway:
    def __init__(self, result=None, error=None):
        self.result, self.error, self.calls = result, error, []

    def complete(self, instructions, payload, schema):
        self.calls.append((instructions, payload, schema))
        if self.error:
            raise self.error
        return self.result


class FillTests(unittest.TestCase):
    def test_requests_only_missing_or_referred_axes(self):
        self.assertEqual(fill.features_to_fill(RECORD), ["Color", "Fit", "Detail"])
        schema = fill.output_schema(["Color", "Fit"])
        self.assertEqual(schema["required"], ["Color", "Fit"])
        self.assertFalse(schema["additionalProperties"])

    def test_quote_must_come_from_input_and_null_means_no_evidence(self):
        text = fill.source_text(RECORD)
        accepted, rejected = fill.validate_fill({
            "Color": {"value": "Charcoal", "evidence_quote": "Half Pants Charcoal", "confidence": 0.8},
            "Fit": {"value": "와이드", "evidence_quote": "와이드 핏 팬츠", "confidence": 0.9},
            "Detail": {"value": "투턱", "evidence_quote": "투턱  디테일\n적용", "confidence": 0.9},
        }, ["Color", "Fit", "Detail"], text)
        self.assertEqual(set(accepted), {"Color", "Detail"})
        self.assertEqual(rejected, {"Fit": "quote_not_in_input"})
        accepted, rejected = fill.validate_fill({
            "Color": {"value": None, "evidence_quote": None, "confidence": 0},
            "Fit": {"value": "상세 페이지 참고", "evidence_quote": "상세 페이지 참고", "confidence": 0.5},
        }, ["Color", "Fit", "Detail"], text)
        self.assertEqual(accepted, {})
        self.assertEqual(rejected, {"Color": "no_evidence", "Fit": "referred_phrase", "Detail": "missing"})

    def test_color_count_and_bad_confidence_are_rejected(self):
        text = "상품명: LACE SLEEVELESS (2COLOR)"
        _, rejected = fill.validate_fill({"Color": {"value": "2COLOR", "evidence_quote": "2COLOR", "confidence": 0.4},
                                          "Detail": {"value": "LACE", "evidence_quote": "LACE", "confidence": 2}},
                                         ["Color", "Detail"], text)
        self.assertEqual(rejected, {"Color": "not_a_color", "Detail": "invalid_confidence"})
        self.assertEqual(fill.validate_fill("x", ["Color"], text), ({}, {"Color": "invalid_output"}))

    def test_fill_one_sends_text_only_and_records_provenance(self):
        gateway = FakeGateway({"Color": {"value": "Charcoal", "evidence_quote": "Charcoal", "confidence": 0.7},
                               "Fit": {"value": None, "evidence_quote": None, "confidence": 0},
                               "Detail": {"value": "투턱", "evidence_quote": "투턱 디테일 적용", "confidence": 0.9}})
        out = fill.fill_one(gateway, "deepseek-test", RECORD)
        payload = gateway.calls[0][1]
        self.assertEqual(set(payload), {"product_text", "requested_features"})
        self.assertNotIn("img.29cm", json.dumps(payload, ensure_ascii=False))
        self.assertEqual(out["provenance"], "model_interpretation")
        self.assertEqual(out["model"], "deepseek-test")
        self.assertEqual(set(out["fills"]), {"Color", "Detail"})
        failed = fill.fill_one(FakeGateway(error=StyleMateError("provider_timeout", "x")), "m", RECORD)
        self.assertEqual((failed["error"], failed["fills"]), ("provider_timeout", {}))

    def test_export_record_validates_and_keeps_raw_and_model_values_apart(self):
        fills = {"fills": {"Detail": {"value": "투턱", "evidence_quote": "투턱 디테일 적용", "confidence": 0.9}}, "model": "m"}
        record = fill.catalog_record(RECORD, fills)
        validate_record(record, ParkRegistry(), "record")
        raw = record["raw_metadata"]
        self.assertEqual(record["garment_type"], "Pants")
        self.assertEqual(raw["fabric"], "폴리에스터 45%, 면 55%")
        self.assertNotIn("color", raw)  # referred raw value is not promoted
        self.assertNotIn("detail", raw)  # model value is not promoted to a supplier field
        self.assertEqual(raw["pi_model_interpretation"]["Detail"]["provenance"], "model_interpretation")
        self.assertEqual([i["location"] for i in record["images"]], ["2545554/0.jpg"])
        self.assertEqual(record["labels"], [])

    def test_garment_type_mapping(self):
        top = {**RECORD, "group": "top"}
        cases = {("여성의류", "상의", "블라우스"): "Blouse", ("남성의류", "상의", "피케/카라 티셔츠"): "Polo",
                 ("남성의류", "니트웨어", "크루넥"): "Knit/Sweater", ("여성의류", "상의", "긴소매 티셔츠"): "T-shirt",
                 ("남성의류", "상의", "반소매 셔츠"): "Shirt", ("여성의류", "상의", "후디"): "Hoodie"}
        for crumbs, expected in cases.items():
            self.assertEqual(fill.garment_type({**top, "breadcrumb": list(crumbs)}), expected, crumbs)
        self.assertEqual(fill.garment_type({**RECORD, "breadcrumb": ["여성의류", "스커트", "미니"]}), "Skirt")

    def test_export_report_counts_before_and_after(self):
        with TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "products").mkdir()
            (data / "pi_fills").mkdir()
            (data / "products" / "2545554.json").write_text(json.dumps(RECORD, ensure_ascii=False), encoding="utf-8")
            (data / "pi_fills" / "2545554.json").write_text(json.dumps({
                "product_id": "2545554", "called": True, "error": None, "model": "m", "rejected": {"Fit": "no_evidence"},
                "fills": {"Color": {"value": "Charcoal", "evidence_quote": "Charcoal", "confidence": 0.7}}}), encoding="utf-8")
            report = fill.export(data, data / "out.jsonl")
            lines = (data / "out.jsonl").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(report["fill_rate"]["all"]["Color"], {"before": 0.0, "after_text": 1.0, "after": 1.0, "model_added": {"text": 1}})
        self.assertEqual(report["fill_rate"]["all"]["Fabric"]["before"], 1.0)
        self.assertEqual(report["rejections"], {"no_evidence": 1})

    def test_image_fill_validation_by_evidence_type(self):
        text = fill.source_text(RECORD)
        labels = {"main0", "detail1-t2"}
        result = {
            "Color": {"value": "차콜", "evidence_type": "image_visual", "evidence": "어두운 회색 반바지", "image": "main0", "confidence": 0.8},
            "Fit": {"value": "와이드", "evidence_type": "image_text", "evidence": "FIT: WIDE", "image": "detail9", "confidence": 0.8},
            "Fabric": {"value": "울", "evidence_type": "image_visual", "evidence": "울처럼 보임", "image": "main0", "confidence": 0.5},
            "Detail": {"value": "투턱", "evidence_type": "text", "evidence": "투턱 디테일 적용", "image": "main0", "confidence": 0.9},
        }
        accepted, rejected = fill.validate_image_fill(result, ["Color", "Fit", "Fabric", "Detail"], text, labels)
        self.assertEqual(rejected, {"Fit": "unknown_image", "Fabric": "fabric_needs_written_evidence"})
        self.assertEqual(accepted["Color"]["image"], "main0")
        self.assertIsNone(accepted["Detail"]["image"])
        _, rejected = fill.validate_image_fill({"Detail": {**result["Detail"], "evidence": "없는 문장"}}, ["Detail"], text, labels)
        self.assertEqual(rejected, {"Detail": "quote_not_in_input"})

    def test_remaining_features_skip_text_pass_fills_and_tiles_cover_tall_images(self):
        self.assertEqual(fill.remaining_features(RECORD, {"fills": {"Color": {}}}), ["Fit", "Detail"])
        self.assertEqual(fill.tile_plan(900, 5000), [(0, 1800), (1800, 3600), (3600, 5000)])
        self.assertEqual(fill.tile_plan(500, 1000), [(0, 1000)])
        self.assertEqual(fill.tile_plan(0, 10), [])

    def test_export_merges_image_fills_without_overriding_text_fills(self):
        text_fill = {"model": "m", "fills": {"Detail": {"value": "투턱", "evidence_quote": "투턱 디테일 적용", "confidence": 0.9}}}
        image_fill = {"model": "m", "fills": {
            "Detail": {"value": "핀턱", "evidence_type": "image_visual", "evidence": "앞 주름", "image": "main0", "confidence": 0.6},
            "Fit": {"value": "와이드", "evidence_type": "image_visual", "evidence": "넓은 통", "image": "main0", "confidence": 0.7}}}
        record = fill.catalog_record(RECORD, text_fill, image_fill)
        validate_record(record, ParkRegistry(), "record")
        model = record["raw_metadata"]["pi_model_interpretation"]
        self.assertEqual((model["Detail"]["value"], model["Detail"]["evidence_type"]), ("투턱", "text"))
        self.assertEqual(model["Fit"]["evidence_type"], "image_visual")
        self.assertNotIn("fit", record["raw_metadata"])

    def test_missing_key_stops_without_other_provider(self):
        with TemporaryDirectory() as tmp, unittest.mock.patch.dict("os.environ", {"OPENCODE_API_KEY": ""}):
            self.assertEqual(fill.main(["--data", tmp]), 3)


if __name__ == "__main__":
    unittest.main()
