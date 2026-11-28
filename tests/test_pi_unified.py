"""Unified PI map (scripts/build_lumi_pi_unified.py): slot normalization, schema checks and raw Type rules."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_lumi_pi_unified as u  # noqa: E402


class NormSlotTest(unittest.TestCase):
    def test_label_becomes_values(self) -> None:
        slot = u.norm_slot({"label": "Relaxed", "score": 3.0, "status": "inferred", "method": "image_model",
                            "evidence": ["loose"], "fill_record": "x.json"})
        self.assertEqual(slot["values"], ["Relaxed"])
        self.assertEqual(slot["score"], 3.0)
        self.assertNotIn("fill_record", slot)

    def test_palette_only_colour_gets_labels(self) -> None:
        slot = u.norm_slot({"colors": [{"label": "Black", "lab": [5, 0, 0]}, {"label": "Grey", "lab": [50, 0, 0]}],
                            "status": "inferred", "seller_labels": ["Charcoal"]})
        self.assertEqual(slot["values"], ["Black", "Grey"])
        self.assertEqual(slot["seller_values"], ["Charcoal"])

    def test_duplicate_values_collapse(self) -> None:
        slot = u.norm_slot({"values": ["Purple", "Purple"], "status": "derived", "method": "image_palette"})
        self.assertEqual(slot["values"], ["Purple"])

    def test_not_applicable_is_dropped_and_empty_is_unknown(self) -> None:
        self.assertIsNone(u.norm_slot({"status": "not_applicable", "values": []}))
        self.assertEqual(u.norm_slot({"status": "inferred", "values": []})["status"], "unknown")
        kept = u.norm_slot({"status": "inferred", "values": [], "absence_supported": True})
        self.assertEqual(kept["status"], "inferred")


class FinishTest(unittest.TestCase):
    def test_group_axes_unknown_fill_and_schema_drop(self) -> None:
        problems: list[str] = []
        record = {"id": "29cm-1", "group": "skirt", "pi": {
            "Fit": {"values": ["Slim"], "status": "inferred", "method": "m", "evidence": []},
            "Length": {"values": ["Full"], "status": "derived", "method": "m", "evidence": []},
            "Silhouette": {"values": ["A-line"], "status": "inferred", "method": "m", "evidence": []}}}
        out = u.finish(record, problems)
        self.assertNotIn("Fit", out["pi"])  # skirts do not use Fit
        self.assertEqual(out["pi"]["Length"]["status"], "unknown")  # trouser length is not a skirt length
        self.assertEqual(out["pi"]["Length"]["dropped_values"], ["Full"])
        self.assertEqual(out["pi"]["Type"]["status"], "unknown")
        self.assertEqual(len(problems), 1)
        self.assertEqual(set(out["pi"]), set(u.applicable("skirt")))

    def test_scores_follow_group_scales(self) -> None:
        record = {"id": "29cm-2", "group": "outer", "pi": {
            "Length": {"values": ["Half"], "status": "derived", "method": "m", "evidence": []},
            "Weight": {"values": ["Heavy"], "status": "derived", "method": "m", "evidence": []},
            "Fit": {"values": ["Regular", "Relaxed"], "status": "inferred", "method": "m", "evidence": []}}}
        pi = u.finish(record, [])["pi"]
        self.assertEqual((pi["Length"]["score"], pi["Length"]["scale"]), (4.0, "outer"))
        self.assertEqual(pi["Weight"]["score"], 3.0)
        self.assertEqual(pi["Fit"]["score"], 2.5)
        self.assertNotIn("Silhouette", pi)

    def test_schema_keeps_v4_3_extensions(self) -> None:
        self.assertIn("Cable knit", u.allowed("Texture", "top"))
        self.assertIn("Mohair", u.allowed("Fabric", "top"))
        self.assertNotIn("Skirt", u.allowed("Type", "bottom"))
        self.assertEqual(u.allowed("Length", "skirt"), ["Mini", "Knee", "Midi", "Long"])


class RawTypeTest(unittest.TestCase):
    def test_men_top_categories(self) -> None:
        self.assertEqual(u.raw_type("top_m", "피케/카라 티셔츠", "pique"), ("Polo", None))
        self.assertEqual(u.raw_type("top_m", "집업", "Hooded zip-up"), ("Hoodie", "Zip hoodie"))
        self.assertEqual(u.raw_type("top_m", "집업", "Track top"), (None, None))  # left for the model

    def test_knit_categories(self) -> None:
        self.assertEqual(u.raw_type("knit_m", "집업", "하프집업 니트"), ("Sweater", None))
        self.assertEqual(u.raw_type("knit_m", "집업", "Knit zip-up"), ("Cardigan", None))
        self.assertEqual(u.raw_type("knit_m", "기타 니트", "Wool knit vest"), ("Sleeveless", None))



class ExportRuntimeTest(unittest.TestCase):
    """--export-runtime: four garment types, per-group values and Length scales, pi_v3 shapes, inferred labels."""

    def record(self, pid: str, group: str, pi: dict, gender: str = "women") -> dict:
        full = {a: u.unknown() for a in u.applicable(group)} | pi
        return {"id": pid, "source": "29cm", "group": group, "gender": gender, "title": pid, "brand": "b",
                "url": f"https://www.29cm.co.kr/products/{pid}", "pi_schema": u.VERSION,
                "price": {"amount": 10.0, "currency": "KRW", "price_krw": 10}, "pi": full, "image": f"{pid}.jpg"}

    def test_registry_and_import_lines(self) -> None:
        slot = lambda values, status="confirmed", **kw: {"values": values, "status": status, "method": "m", "evidence": ["e"], **kw}
        records = [self.record("29cm-1", "skirt", {"Type": slot(["Skirt"]), "Length": slot(["Midi"], score=3.0, scale="skirt"),
                                                   "Silhouette": slot(["A-line"], "inferred")}),
                   self.record("29cm-2", "outer", {"Type": slot(["Coat"]), "Length": slot(["Long"], score=5.0, scale="outer"),
                                                   "Fit": slot(["Relaxed"], score=3.0, scale="outer")}, "unisex")]
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "images" / u.OUT_NAME).mkdir(parents=True)
            (data / "catalog").mkdir()
            for r in records:
                (data / "images" / u.OUT_NAME / r["image"]).write_bytes(b"x")
            result = u.export_runtime(records, data, data / "registry.json")
            registry = json.loads((data / "registry.json").read_text(encoding="utf-8"))
            lines = [json.loads(x) for x in (data / "catalog" / f"{u.VERSION}-import-01.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(result["by_garment"], {"Skirt": 1, "Outer": 1})
        self.assertEqual(result["import_files"], [f"{u.VERSION}-import-01.jsonl"])
        self.assertEqual(registry["execution"]["supported_garment_types"], ["Top", "Bottom", "Outer", "Skirt"])
        pi = registry["product_information"]
        self.assertEqual(pi["Type"]["values_by_garment_type"]["Skirt"], ["Skirt"])
        self.assertNotIn("Skirt", pi["Fit"]["values_by_garment_type"])  # skirts do not use Fit
        self.assertEqual(pi["Length"]["value_shape"]["scale"]["skirt"]["Long"], 4.0)
        self.assertEqual(pi["Length"]["value_shape"]["scale"]["outer"]["Long"], 5.0)
        skirt = next(x for x in lines if x["product_id"] == "29cm-1")
        self.assertEqual(skirt["garment_type"], "Skirt")
        self.assertEqual(skirt["raw_metadata"]["length"], ["Midi"])
        self.assertEqual(skirt["raw_metadata"]["pi_v3"], {"price_krw": 10, "axes": {"Length": {"score": 3.0, "scale": "skirt"}}})
        self.assertEqual([l["observation"]["feature"] for l in skirt["labels"]], ["Silhouette"])
        self.assertEqual(skirt["images"][0]["location"], f"{u.OUT_NAME}/29cm-1.jpg")


if __name__ == "__main__":
    unittest.main()
