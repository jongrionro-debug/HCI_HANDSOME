"""PI v4 outer group (ADR 0017): schema additions, group-scoped merges, outer Type/Length/Weight/material rules."""

import json
import unittest

from scripts import build_lumi_pi_v3 as v3
from scripts import build_lumi_pi_v4 as v4

SIZE_TABLE = "치수항목\tS\tM\tL\tXL\n총길이\t66\t68.5\t71\t73\n가슴둘레\t110\t116\t122\t128"


class SchemaTest(unittest.TestCase):
    def test_outer_group_and_type_values(self):
        self.assertEqual(v4.GROUPS, ("top", "bottom", "outer"))
        outer = v4.SCHEMA["Type"]["values_by_group"]["outer"]
        self.assertIn("Zip hoodie", outer)
        self.assertIn("Padded jacket", outer)
        self.assertEqual(len(outer), len(set(outer)))
        self.assertNotIn("Zip hoodie", v4.SCHEMA["Type"]["values_by_group"]["top"])

    def test_type_merges_are_scoped_by_group(self):
        self.assertEqual(v4.TYPE_MERGE["top"]["Zip hoodie"], "Hoodie")
        self.assertEqual(v4.TYPE_MERGE["outer"], {})
        self.assertNotIn("Zip hoodie", v4.TYPE_MERGE["bottom"])

    def test_added_values_and_unused_silhouette(self):
        self.assertEqual(v4.SCHEMA["Fabric"]["values"][-2:], ["Leather", "Fur"])
        for value in ("Suede", "Quilted", "Shearling", "Melton", "Ripstop", "Tweed"):
            self.assertIn(value, v4.SCHEMA["Texture"]["values"])
        self.assertEqual(v4.SCHEMA["Silhouette"]["groups"], ["bottom"])
        self.assertIn("Silhouette", v4.META["unused_by_group"]["outer"])
        self.assertEqual(v4.LENGTH_SCALE["outer"], {"Cropped": 1.0, "Short": 2.0, "Hip": 3.0, "Half": 4.0, "Long": 5.0})

    def test_v3_is_unchanged(self):
        self.assertNotIn("outer", v3.LENGTH_SCALE)
        self.assertNotIn("Leather", v3.SCHEMA["Fabric"]["values"])
        self.assertEqual(v4.LENGTH_SCALE["top"], v3.LENGTH_SCALE["top"])
        self.assertEqual(v4.LENGTH_SCALE["bottom"], v3.LENGTH_SCALE["bottom"])

    def test_schema_is_json(self):
        json.dumps({"schema": v4.SCHEMA, "meta": v4.META}, ensure_ascii=False)


class OuterTypeTest(unittest.TestCase):
    def test_subcategory_mapping(self):
        self.assertEqual(v4.outer_type("후드 집업")["values"], ["Zip hoodie"])
        self.assertEqual(v4.outer_type("숏패딩")["values"], ["Padded jacket"])
        self.assertEqual(v4.outer_type("하프코트")["values"], ["Coat"])
        self.assertEqual(v4.outer_type("블루종")["status"], "confirmed")
        self.assertIsNone(v4.outer_type("기타 아우터"))
        self.assertEqual(len(v4.OUTER_SUBCATEGORY_TYPE), 24)


class OuterLengthTest(unittest.TestCase):
    def test_subcategory_wins_over_keyword_and_size(self):
        got = v4.outer_length("롱코트", "크롭 코트", SIZE_TABLE, "Coat")
        self.assertEqual((got["values"], got["score"], got["method"]), (["Long"], 5.0, "subcategory"))

    def test_keyword_then_size_then_type(self):
        self.assertEqual(v4.outer_length("블루종", "크롭 블루종", SIZE_TABLE, "Blouson")["values"], ["Cropped"])
        by_cm = v4.outer_length("블루종", "블루종", SIZE_TABLE, "Blouson")
        self.assertEqual((by_cm["values"], by_cm["method"], by_cm["evidence"]), (["Hip"], "total_length_cm", ["총길이 68.5cm"]))
        by_type = v4.outer_length("트렌치/맥코트", "트렌치", "", "Trench coat")
        self.assertEqual((by_type["values"], by_type["status"]), (["Long"], "derived"))

    def test_closures_and_sleeves_are_not_lengths(self):
        self.assertIsNone(v4.outer_length("플리스", "하프집업 플리스", "", None))
        self.assertIsNone(v4.outer_length("기타 아우터", "롱슬리브 레이어드", "", None))
        self.assertIsNone(v4.outer_length("기타 아우터", "short sleeve over shirt", "", None))

    def test_two_keywords_fall_through(self):
        self.assertEqual(v4.outer_length("블레이저", "숏 앤 롱 블레이저", "", "Blazer")["method"], "type_rule")

    def test_total_length_parsing(self):
        self.assertEqual(v4.total_length_cm(SIZE_TABLE), 68.5)
        self.assertEqual(v4.total_length_cm("치수항목\t1\t2\t3\n총장\t60\t62\t64"), 62.0)
        self.assertIsNone(v4.total_length_cm("가슴둘레\t110"))
        self.assertEqual([v4.length_from_cm(x) for x in (50, 60, 75, 90, 110)], ["Cropped", "Short", "Hip", "Half", "Long"])


class OuterWeightTest(unittest.TestCase):
    def test_gsm_and_keywords(self):
        self.assertEqual(v4.outer_weight({}, "400gsm 헤비 코튼", "블루종")["method"], "gsm")
        heavy = v4.outer_weight({}, "구스다운 숏패딩", "숏패딩")
        self.assertEqual((heavy["values"], heavy["score"], heavy["status"]), (["Heavy"], 3.0, "confirmed"))

    def test_light_padding_is_mid_when_keywords_conflict(self):
        pi = {"Type": {"values": ["Padded jacket"]}}
        got = v4.outer_weight(pi, "경량 패딩 자켓", "경량패딩")
        self.assertEqual((got["values"], got["method"]), (["Mid"], "subcategory_rule"))

    def test_material_and_type_rules(self):
        self.assertEqual(v4.outer_weight({"Texture": {"values": ["Shearling"]}}, "", "무스탕")["values"], ["Heavy"])
        coat = {"Type": {"values": ["Coat"]}, "Fabric": {"values": ["Wool", "Nylon"]}}
        self.assertEqual(v4.outer_weight(coat, "", "하프코트")["method"], "type_fabric_rule")
        self.assertEqual(v4.outer_weight({"Type": {"values": ["Windbreaker"]}}, "", "바람막이")["values"], ["Light"])
        self.assertIsNone(v4.outer_weight({}, "", "기타 아우터"))


class OuterMaterialTest(unittest.TestCase):
    def test_keywords_and_subcategory(self):
        got = v4.outer_materials("비건 레더 스웨이드 트러커", "레더 재킷")
        self.assertEqual((got["Fabric"]["values"], got["Fabric"]["status"]), (["Leather"], "confirmed"))
        self.assertEqual(got["Texture"]["values"], ["Suede"])
        self.assertEqual(v4.outer_materials("무스탕 자켓", "무스탕")["Texture"]["values"], ["Shearling"])
        self.assertEqual(v4.outer_materials("자켓", "퍼 재킷")["Fabric"]["status"], "derived")

    def test_fur_needs_a_fur_word(self):
        self.assertNotIn("Fabric", v4.outer_materials("퍼플 블루종", "블루종"))
        self.assertEqual(v4.outer_materials("페이크퍼 카라 코트", "롱코트")["Fabric"]["values"], ["Fur"])

    def test_silk_is_merged_like_v3(self):
        self.assertEqual(v4.outer_materials("silk blend blazer", "블레이저")["Fabric"]["values"], ["Viscose"])


class OuterPiTest(unittest.TestCase):
    def test_fills_axes_together(self):
        pi = v4.outer_pi("하프코트", "울 멜톤 하프 코트", "겉감: 울 80% 나일론 20%")
        self.assertEqual(pi["Type"]["values"], ["Coat"])
        self.assertEqual(pi["Length"]["values"], ["Half"])
        self.assertIn("Melton", pi["Texture"]["values"])
        self.assertEqual(pi["Weight"]["values"], ["Heavy"])


if __name__ == "__main__":
    unittest.main()
