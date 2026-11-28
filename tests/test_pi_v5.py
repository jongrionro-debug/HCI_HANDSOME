"""PI v5 skirt group (ADR 0019): schema additions, skirt Type/Length/Silhouette/material/Weight rules."""

import json
import unittest

from scripts import build_lumi_pi_v4 as v4
from scripts import build_lumi_pi_v5 as v5

SIZE_TABLE = "치수항목\tS\tM\tL\n총장\t70\t72\t74\n허리단면\t33\t35\t37"


class SchemaTest(unittest.TestCase):
    def test_skirt_group_and_type(self):
        self.assertEqual(v5.GROUPS, ("top", "bottom", "outer", "skirt"))
        by_group = v5.SCHEMA["Type"]["values_by_group"]
        self.assertEqual(by_group["skirt"], ["Skirt", "Skort"])
        self.assertNotIn("Skirt", by_group["bottom"])
        self.assertEqual(v5.SCHEMA["Type"]["values"].count("Skirt"), 1)

    def test_length_silhouette_and_unused_fit(self):
        self.assertEqual(v5.LENGTH_SCALE["skirt"], {"Mini": 1.0, "Knee": 2.0, "Midi": 3.0, "Long": 4.0})
        self.assertEqual(v5.SCHEMA["Length"]["values_by_group"]["skirt"], ["Mini", "Knee", "Midi", "Long"])
        self.assertEqual(v5.SCHEMA["Silhouette"]["groups"], ["bottom", "skirt"])
        self.assertEqual(v5.SCHEMA["Silhouette"]["values_by_group"]["skirt"],
                         ["Pencil", "H-line", "A-line", "Flare", "Mermaid"])
        self.assertEqual(v5.META["unused_by_group"]["skirt"], ["Fit"])
        self.assertEqual(v5.META["unused_by_group"]["outer"], ["Silhouette"])

    def test_added_values(self):
        for axis, value in (("Texture", "Velvet"), ("Texture", "Tulle"), ("Detail", "Wrap"),
                            ("Detail", "Ruffle"), ("Pattern", "Dot"), ("Style", "Feminine")):
            self.assertIn(value, v5.SCHEMA[axis]["values"])
        self.assertIn("Feminine", v5.SCHEMA["Style"]["values_by_group"]["skirt"])
        self.assertNotIn("Feminine", v5.SCHEMA["Style"]["values_by_group"]["top"])

    def test_v4_is_unchanged(self):
        self.assertNotIn("skirt", v4.LENGTH_SCALE)
        self.assertIn("Skirt", v4.SCHEMA["Type"]["values_by_group"]["bottom"])
        self.assertNotIn("Velvet", v4.SCHEMA["Texture"]["values"])
        self.assertEqual(v4.SCHEMA["Silhouette"]["groups"], ["bottom"])

    def test_schema_is_json(self):
        json.dumps({"schema": v5.SCHEMA, "meta": v5.META}, ensure_ascii=False)


class SkirtTypeTest(unittest.TestCase):
    def test_subcategory_and_skort_keyword(self):
        self.assertEqual(v5.skirt_type("미디", "wool midi skirt")["values"], ["Skirt"])
        skort = v5.skirt_type("미니", "winter fake mini skirt pants")
        self.assertEqual((skort["values"], skort["method"]), (["Skort"], "keyword"))
        self.assertEqual(v5.skirt_type("미니", "치마바지 숏")["values"], ["Skort"])
        self.assertIsNone(v5.skirt_type("기타", "스커트"))


class SkirtLengthTest(unittest.TestCase):
    def test_title_wins_over_subcategory(self):
        got = v5.skirt_length("미디", "Jacquard Long Skirt")
        self.assertEqual((got["values"], got["score"], got["method"]), (["Long"], 4.0, "title_keyword"))

    def test_subcategory_wins_over_seller_text(self):
        got = v5.skirt_length("미디", "lip pencil skirt", "앞 패널 미니 립 포켓")
        self.assertEqual((got["values"], got["method"]), (["Midi"], "subcategory"))

    def test_denim_uses_seller_text_then_size(self):
        self.assertEqual(v5.skirt_length("데님", "H Line Denim Skirt", "무릎 기장")["values"], ["Knee"])
        by_cm = v5.skirt_length("데님", "H Line Denim Skirt", "", SIZE_TABLE)
        self.assertEqual((by_cm["values"], by_cm["evidence"]), (["Midi"], ["총장 72cm"]))
        self.assertIsNone(v5.skirt_length("데님", "H Line Denim Skirt"))

    def test_false_lengths(self):
        self.assertIsNone(v5.skirt_length("데님", "미니멀 데님 스커트"))
        self.assertIsNone(v5.skirt_length("데님", "롱슬리브 세트 스커트"))
        self.assertIsNone(v5.skirt_length("데님", "mini & maxi skirt"))
        self.assertEqual([v5.length_from_cm(x) for x in (40, 55, 70, 95)], ["Mini", "Knee", "Midi", "Long"])


class SkirtShapeAndMaterialTest(unittest.TestCase):
    def test_silhouette(self):
        self.assertEqual(v5.skirt_silhouette("울 텍스처 H라인 롱 스커트")["values"], ["H-line"])
        self.assertEqual(v5.skirt_silhouette("suede semi A-line skirt")["values"], ["A-line"])
        self.assertEqual(v5.skirt_silhouette("lip pencil skirt")["values"], ["Pencil"])
        self.assertIsNone(v5.skirt_silhouette("A라인 머메이드 스커트"))
        self.assertIsNone(v5.skirt_silhouette("basic skirt"))

    def test_keywords(self):
        got = v5.skirt_keywords("Corduroy Velvet Mini Skirt. 랩 스커트 러플 도트")
        self.assertEqual(got["Texture"]["values"], ["Corduroy", "Velvet"])
        self.assertIn("Wrap", got["Detail"]["values"])
        self.assertIn("Ruffle", got["Detail"]["values"])
        self.assertEqual(got["Pattern"]["values"], ["Dot"])

    def test_false_materials_and_details(self):
        self.assertNotIn("Detail", v5.skirt_keywords("스트랩 장식"))
        self.assertNotIn("Texture", v5.skirt_keywords("튤립 스커트 레이스업"))
        self.assertNotIn("Texture", v5.skirt_pi("데님", "백 슬릿 펜슬 셋업 스커트"))  # the 데님 small category alone


class SkirtWeightTest(unittest.TestCase):
    def test_material_rules(self):
        velvet = v5.skirt_weight({"Texture": {"values": ["Velvet"]}}, "", "Velvet Ease Skirt")
        self.assertEqual((velvet["values"], velvet["status"], velvet["score"]), (["Heavy"], "derived", 3.0))
        self.assertEqual(v5.skirt_weight({}, "시폰 플리츠", "")["values"], ["Light"])

    def test_wool_counts_only_in_the_title(self):
        blend = {"Fabric": {"values": ["Wool", "Polyester"]}}
        self.assertEqual(v5.skirt_weight(blend, "polyester 80 / wool 20", "lip pencil skirt")["values"], ["Mid"])
        self.assertEqual(v5.skirt_weight(blend, "", "Basic Wool Mini Skirt")["values"], ["Heavy"])

    def test_gsm_first(self):
        self.assertEqual(v5.skirt_weight({"Texture": {"values": ["Velvet"]}}, "180gsm", "")["method"], "gsm")


class SkirtPiTest(unittest.TestCase):
    def test_fills_axes_together(self):
        pi = v5.skirt_pi("미디", "Blair Velvet Midi Skirt (Brown)", "겉감: 폴리에스터 95% 폴리우레탄 5%")
        self.assertEqual(pi["Type"]["values"], ["Skirt"])
        self.assertEqual(pi["Length"]["values"], ["Midi"])
        self.assertEqual(pi["Texture"]["values"], ["Velvet"])
        self.assertEqual(pi["Weight"]["values"], ["Heavy"])
        self.assertNotIn("Fit", pi)


if __name__ == "__main__":
    unittest.main()
