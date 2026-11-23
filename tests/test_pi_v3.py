"""PI v3 value shapes (ADR 0016): colour maths, ordinal scores, Weight/Style rules, merges. No Pillow, no data/."""

import unittest

from scripts import build_lumi_pi_v3 as v3


def slot(values, status="confirmed", method="keyword"):
    return {"values": values, "status": status, "method": method, "evidence": []}


def record(group, pi, price=None):
    return {"id": "x-1", "source": "waxlondon", "source_product_id": "1", "group": group, "gender": "men",
            "title": "t", "brand": "b", "image": "images/x.jpg", "url_handle": "h",
            "price": price or {"amount": "100.00", "currency": "GBP"}, "pi": pi}


class ColourMathTest(unittest.TestCase):
    def test_srgb_to_lab_reference_points(self):
        for got, want in zip(v3.srgb_to_lab((255, 255, 255)), (100.0, 0.0, 0.0)):
            self.assertAlmostEqual(got, want, places=2)
        for got, want in zip(v3.srgb_to_lab((255, 0, 0)), (53.24, 80.09, 67.20)):
            self.assertAlmostEqual(got, want, places=1)

    def test_ciede2000_matches_sharma_pairs(self):
        pairs = [((50, 2.6772, -79.7751), (50, 0, -82.7485), 2.0425),
                 ((50, 0, 0), (50, -1, 2), 2.3669),
                 ((50, 2.5, 0), (73, 25, -18), 27.1492),
                 ((2.0776, 0.0795, -1.135), (0.9033, -0.0636, -0.5514), 0.9082)]
        for lab1, lab2, want in pairs:
            self.assertAlmostEqual(v3.delta_e2000(lab1, lab2), want, places=3)

    def test_colour_names_and_tone(self):
        self.assertEqual(v3.color_name((50, 0, 0)), "Grey")
        self.assertEqual(v3.color_name((9, 0, 0)), "Black")
        self.assertEqual(v3.color_name((11, 2, -8)), "Navy")
        self.assertEqual([v3.tone_label(x) for x in (20, 55, 85)], ["Dark", "Medium", "Light"])

    def test_palette_drops_background_and_keeps_two_colours_for_stripes(self):
        white, navy, ecru = (245, 245, 243), (30, 36, 60), (232, 222, 200)
        border = [white] * 40
        solid = v3.palette_from_pixels([white] * 50 + [navy] * 50, border, drop_skin=False, max_colors=3)
        self.assertEqual([c["label"] for c in solid], ["Navy"])
        stripes = v3.palette_from_pixels([white] * 20 + [navy] * 40 + [ecru] * 40, border, False, 3)
        self.assertEqual(sorted(c["label"] for c in stripes), ["Ecru", "Navy"])
        self.assertTrue(all(c["share"] >= v3.PALETTE_MIN_SHARE for c in stripes))


class OrdinalTest(unittest.TestCase):
    def test_fit_score_and_relative_shift(self):
        self.assertEqual(v3.fit_score(["Relaxed"]), 3.0)
        self.assertEqual(v3.fit_score(["Regular", "Relaxed"]), 2.5)
        self.assertIsNone(v3.fit_score([]))
        self.assertEqual(v3.shift_fit(3.0, +1), 3.5)
        self.assertEqual(v3.shift_fit(2.0, -1, "much"), 1.0)
        self.assertEqual(v3.shift_fit(4.0, +1, "much"), 4.0)

    def test_length_is_scored_per_group(self):
        self.assertEqual(v3.length_values("top", ["Long sleeve", "Full"]), (["Long sleeve"], 2.0))
        self.assertEqual(v3.length_values("top", ["Cropped"]), (["Cropped"], None))
        self.assertEqual(v3.length_values("bottom", ["Cropped", "Short sleeve"]), (["Cropped"], 2.0))


class RuleTest(unittest.TestCase):
    def test_weight_prefers_seller_words_then_rules(self):
        self.assertEqual(v3.weight_of({}, "Cut from a 400gsm loopback")["values"], ["Heavy"])
        self.assertEqual(v3.weight_of({}, "A lightweight cotton shirt")["status"], "confirmed")
        fleece = v3.weight_of({"Type": slot(["Sweatshirt"]), "Texture": slot(["Fleece"])}, "")
        self.assertEqual((fleece["values"], fleece["status"]), (["Heavy"], "derived"))
        self.assertEqual(v3.weight_of({"Type": slot(["T-shirt"])}, "")["values"], ["Light"])
        self.assertIsNone(v3.weight_of({}, ""))

    def test_style_splits_classic_and_caps_at_two(self):
        plain = {"Style": slot(["Classic"], "derived"), "Pattern": slot(["Solid"])}
        self.assertEqual(v3.style_of(plain, "")["values"], ["Minimal"])
        graphic = {"Style": slot(["Classic"], "derived"), "Pattern": slot(["Graphic"])}
        self.assertEqual(v3.style_of(graphic, "")["values"], ["Casual"])
        many = {"Style": slot(["Tailored", "Vintage", "Classic"], "derived"), "Pattern": slot(["Solid"])}
        self.assertEqual(v3.style_of(many, "")["values"], ["Formal", "Vintage"])
        outdoor = v3.style_of({}, "Water-repellent shell for hiking")
        self.assertEqual((outdoor["values"], outdoor["status"]), (["Outdoor"], "derived"))


class ConvertTest(unittest.TestCase):
    def test_merges_scores_and_price(self):
        top = v3.convert(record("top", {"Type": slot(["Zip hoodie"]), "Fit": slot(["Relaxed"]),
                                        "Silhouette": slot(["Boxy"]), "Color": slot(["Navy"])}), "", None)
        self.assertEqual(top["pi"]["Type"]["values"], ["Hoodie"])
        self.assertIn("Zip", top["pi"]["Detail"]["values"])
        self.assertNotIn("Silhouette", top["pi"])
        self.assertEqual((top["pi"]["Fit"]["score"], top["pi"]["Fit"]["scale"]), (3.0, "top"))
        self.assertEqual(top["pi"]["Tone"]["values"], ["Dark"])
        self.assertEqual(top["price"]["price_krw"], round(100 * v3.FX["GBP"]["KRW"]))
        bottom = v3.convert(record("bottom", {"Type": slot(["Trousers"]), "Silhouette": slot(["Wide"]),
                                              "Detail": slot(["Collar"]), "Fabric": slot(["Silk", "Cotton"])},
                                   {"amount": 39000, "currency": "KRW"}), "", None)
        self.assertEqual(bottom["pi"]["Silhouette"]["values"], ["Wide"])
        self.assertNotIn("Detail", bottom["pi"])
        self.assertEqual(bottom["pi"]["Fabric"]["values"], ["Viscose", "Cotton"])
        self.assertEqual(bottom["price"]["price_krw"], 39000)
        self.assertEqual(sorted(bottom["merged"]), ["Detail:Collar", "Fabric:Silk"])
        v3.validate([top, bottom])

    def test_validate_rejects_three_styles(self):
        bad = record("top", {"Style": slot(["Minimal", "Vintage", "Street"])})
        with self.assertRaises(SystemExit):
            v3.validate([bad])


if __name__ == "__main__":
    unittest.main()
