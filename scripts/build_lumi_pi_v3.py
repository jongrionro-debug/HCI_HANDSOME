#!/usr/bin/env python3
"""Build the LUMI PI v3 catalog (ADR 0016) on top of the PI v2 fills (ADR 0014).

v3 separates the stored value from the chat label:
  - ordinal axes (Fit, Tone, Length, Weight) keep a numeric ``score``; labels are for display
  - Color keeps RGB/Lab per representative colour (first image, garment area); labels are the nearest of 17 names
  - Price keeps the raw amount and adds ``price_krw`` at a fixed reference rate
  - categorical axes keep labels; values rarer than 1% of their group are merged into a similar value

No model is called. Colour extraction needs Pillow, which is imported only when images are read.

    python3 scripts/build_lumi_pi_v3.py --data data
    python3 scripts/build_lumi_pi_v3.py --data data --review-sample 30      # human review sheet
    python3 scripts/build_lumi_pi_v3.py --data data --score-review data/catalog/lumi-pi-v3-review.csv
    python3 scripts/build_lumi_pi_v3.py --data data --export-runtime   # runtime dictionary + import file
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_lumi_pi_v2 as v2  # noqa: E402

VERSION = "lumi-pi-v3"
FX = {"GBP": {"KRW": 1757.97, "date": "2026-11-20", "source": "ECB reference rate via api.frankfurter.app"}}
RARE_SHARE = 0.01  # values below 1% of their group's filled products are merged (Issue #20)
FIT_STEP = 0.5
RELATIVE_STEP = {"slight": 0.5, "much": 1.0}  # "조금 더" / "훨씬"
STYLE_MAX = 2
PALETTE_MAX, PALETTE_MIN_SHARE = 3, 0.10
TONE_DARK_BELOW, TONE_LIGHT_FROM = 40.0, 70.0  # L* thresholds for the Tone label

FIT_SCALE = {"Slim": 1.0, "Regular": 2.0, "Relaxed": 3.0, "Oversized": 4.0}
LENGTH_SCALE = {"top": {"Sleeveless": 0.0, "Short sleeve": 1.0, "Long sleeve": 2.0},
                "bottom": {"Shorts": 1.0, "Cropped": 2.0, "Full": 3.0}}
WEIGHT_SCALE = {"Light": 1.0, "Mid": 2.0, "Heavy": 3.0}

# Nearest-name anchors in Lab: median main colour of single-colour Shopify products per seller colour word
# (Cole Buxton + Wax London, 2026-11-23 build). Photos render garments darker and greyer than ideal swatches,
# so measured anchors name photographed colours better. 29CM is not used here and serves as the held-out check.
# Grey also gets a neutral mid grey (L* 50): the measured Grey anchor is light marl only, and without a mid anchor
# mid greys fell to Blue. "Multi" is gone: patterned products keep 2-3 colours instead.
GREY_MID = (50.0, 0.0, 0.0)
COLOR_ANCHORS: dict[str, tuple[float, float, float]] = {
    "Black": (9.7, 0.1, 0.0), "White": (93.2, 0.0, 0.1), "Ecru": (81.7, 0.3, 1.9), "Grey": (82.6, 0.3, -0.4),
    "Charcoal": (21.1, 1.1, 0.9), "Navy": (11.2, 1.8, -7.6), "Blue": (31.3, 1.1, -12.6),
    "Light blue": (67.2, -1.1, -7.2), "Brown": (15.9, 6.5, 6.2), "Beige": (66.2, 3.8, 11.8),
    "Khaki": (37.4, -0.5, 16.0), "Green": (20.9, -6.8, 0.4), "Red": (29.4, 40.8, 17.7), "Pink": (71.2, 12.7, 6.2),
    "Purple": (16.2, 12.3, -1.3), "Yellow": (81.2, -2.8, 24.1), "Orange": (40.6, 32.3, 26.6),
}

TYPE_MERGE = {"Knit vest": "Sleeveless", "Cargo pants": "Trousers", "Zip hoodie": "Hoodie"}
TYPE_MERGE_DETAIL = {"Cargo pants": "Pockets", "Zip hoodie": "Zip"}
VALUE_MERGE = {"Fabric": {"Silk": "Viscose"}}
# Group-scoped merges for values under RARE_SHARE in that group (2026-11-23 build). None drops a value that does
# not apply to the group (a collar or hood on bottoms, an elastic waist on tops).
GROUP_MERGE: dict[str, dict[str, dict[str, str | None]]] = {
    "top": {"Detail": {"Elastic waist": None}},
    "bottom": {"Pattern": {"Logo": "Graphic", "Other": "Graphic"},
               "Texture": {"Waffle": "Knit", "Boucle": "Knit", "Seersucker": "Twill"},
               "Fabric": {"Cashmere": "Wool"}, "Detail": {"Collar": None, "Hood": None}},
}
STYLE_MAP = {"Tailored": "Formal"}  # Classic is split into Minimal / Casual below

SCHEMA: dict[str, dict[str, Any]] = {
    "Type": {"kind": "categorical", "fill": "chat", "condition": "filter",
             "values": [t for t in v2.SCHEMA["Type"] if t not in TYPE_MERGE]},
    "Price": {"kind": "continuous", "fill": "chat", "condition": "filter", "stored": "amount+currency, price_krw",
              "compare": "budget range on price_krw"},
    "Color": {"kind": "continuous", "fill": "chat", "condition": "score", "stored": "rgb, lab, share (max 3)",
              "compare": "CIEDE2000 on Lab", "values": list(COLOR_ANCHORS)},
    "Tone": {"kind": "ordinal", "fill": "image", "condition": "score", "stored": "L* of the main colour",
             "values": ["Dark", "Medium", "Light"], "label_thresholds": {"Dark": f"L*<{TONE_DARK_BELOW}",
                                                                          "Light": f"L*>={TONE_LIGHT_FROM}"}},
    "Pattern": {"kind": "categorical", "fill": "image", "condition": "score", "values": v2.SCHEMA["Pattern"]},
    "Fit": {"kind": "ordinal", "fill": "image", "condition": "score", "scale": FIT_SCALE, "step": FIT_STEP,
            "relative_step": RELATIVE_STEP, "scored_by_group": True, "values": list(FIT_SCALE)},
    "Silhouette": {"kind": "categorical", "fill": "image", "condition": "score", "groups": ["bottom"],
                   "values": ["Straight", "Tapered", "Wide", "Flare"]},
    "Length": {"kind": "ordinal", "fill": "image", "condition": "score", "scale": LENGTH_SCALE,
               "values": v2.SCHEMA["Length"]},
    "Weight": {"kind": "ordinal", "fill": "chat", "condition": "score", "scale": WEIGHT_SCALE, "values": list(WEIGHT_SCALE)},
    "Texture": {"kind": "categorical", "fill": "image", "condition": "score", "values": v2.SCHEMA["Texture"]},
    "Fabric": {"kind": "categorical", "fill": "chat", "condition": "score", "image_update": False,
               "values": [f for f in v2.SCHEMA["Fabric"] if f not in VALUE_MERGE["Fabric"]]},
    "Detail": {"kind": "categorical", "fill": "image", "condition": "score", "values": v2.SCHEMA["Detail"]},
    "Style": {"kind": "categorical", "fill": "image", "condition": "score", "max_values": STYLE_MAX,
              "values": ["Minimal", "Casual", "Formal", "Vintage", "Sporty", "Workwear", "Preppy", "Street", "Outdoor"]},
}
AXES = tuple(a for a in SCHEMA if a != "Price")
META = {"hard_filters": ["Type", "Price (budget)", "explicit exclusion"],
        "preference_states": {"value": "사용자가 고른 값", "any": "상관없음(묻지 않는다)", "unknown": "아직 모름(이미지 단계에서 묻는다)"},
        "metadata_only": ["Brand", "url"]}

# ---- colour maths (no Pillow) ------------------------------------------------------


def srgb_to_lab(rgb: tuple[int, int, int] | list[int]) -> tuple[float, float, float]:
    """sRGB 0-255 -> CIELAB (D65)."""
    def lin(c: float) -> float:
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(float(c)) for c in rgb)
    x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047
    y = 0.2126729 * r + 0.7151522 * g + 0.0721750 * b
    z = (0.0193339 * r + 0.1191920 * g + 0.9503041 * b) / 1.08883

    def f(t: float) -> float:
        return t ** (1 / 3) if t > 216 / 24389 else (24389 / 27 * t + 16) / 116
    fx, fy, fz = f(x), f(y), f(z)
    return 116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)


def delta_e76(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    return math.dist(a, b)


def delta_e2000(lab1: tuple[float, ...], lab2: tuple[float, ...]) -> float:
    """CIEDE2000 colour difference (Sharma, Wu & Dalal 2005)."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar7 = ((c1 + c2) / 2) ** 7
    g = 0.5 * (1 - math.sqrt(cbar7 / (cbar7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dlp, dcp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lbar, cbarp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    else:
        hbarp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbarp - 30)) + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6)) - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / math.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbarp, 1 + 0.015 * cbarp * t
    cbarp7 = cbarp ** 7
    rt = (-2 * math.sqrt(cbarp7 / (cbarp7 + 25 ** 7))
          * math.sin(math.radians(60 * math.exp(-(((hbarp - 275) / 25) ** 2)))))
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp_big / sh) ** 2 + rt * (dcp / sc) * (dhp_big / sh))


ANCHOR_LAB: dict[str, list[tuple[float, float, float]]] = {name: [lab] for name, lab in COLOR_ANCHORS.items()}
ANCHOR_LAB["Grey"].append(GREY_MID)


def anchor_distance(lab: tuple[float, ...] | list[float], name: str) -> float:
    return min(delta_e2000(tuple(lab), anchor) for anchor in ANCHOR_LAB[name])


def color_name(lab: tuple[float, float, float]) -> str:
    return min(ANCHOR_LAB, key=lambda name: anchor_distance(lab, name))


def tone_label(lightness: float) -> str:
    return "Dark" if lightness < TONE_DARK_BELOW else "Light" if lightness >= TONE_LIGHT_FROM else "Medium"


# ---- palette extraction --------------------------------------------------------------


def _kmeans(points: list[tuple[float, float, float]], k: int, rounds: int = 8) -> list[list[int]]:
    """Deterministic k-means in Lab (farthest-point init). Returns member indices per cluster."""
    centers = [points[0]]
    while len(centers) < min(k, len(points)):
        far = max(range(len(points)), key=lambda i: min(delta_e76(points[i], c) for c in centers))
        if min(delta_e76(points[far], c) for c in centers) < 1e-6:
            break
        centers.append(points[far])
    members: list[list[int]] = []
    for _ in range(rounds):
        members = [[] for _ in centers]
        for i, p in enumerate(points):
            members[min(range(len(centers)), key=lambda c: delta_e76(p, centers[c]))].append(i)
        centers = [tuple(sum(points[i][d] for i in m) / len(m) for d in range(3)) if m else centers[j]
                   for j, m in enumerate(members)]
    return [m for m in members if m]


def _is_skin(r: int, g: int, b: int) -> bool:
    return r > 95 and g > 40 and b > 20 and max(r, g, b) - min(r, g, b) > 15 and abs(r - g) > 15 and r > g and r > b


def palette_from_pixels(pixels: list[tuple[int, int, int]], border: list[tuple[int, int, int]],
                        drop_skin: bool, max_colors: int) -> list[dict[str, Any]]:
    """Garment palette: drop pixels close to the dominant border colours (background) and, for model shots,
    skin; cluster the rest in Lab; merge near clusters; keep colours covering >= 10%."""
    cache: dict[tuple[int, int, int], tuple[float, float, float]] = {}

    def lab(p: tuple[int, int, int]) -> tuple[float, float, float]:
        key = (p[0] >> 2, p[1] >> 2, p[2] >> 2)
        if key not in cache:
            cache[key] = srgb_to_lab((key[0] * 4 + 2, key[1] * 4 + 2, key[2] * 4 + 2))
        return cache[key]

    border_labs = [lab(p) for p in border]
    background = [tuple(sum(border_labs[i][d] for i in m) / len(m) for d in range(3))
                  for m in _kmeans(border_labs, 4) if len(m) >= 0.15 * len(border_labs)]
    kept = [p for p in pixels if all(delta_e76(lab(p), bg) >= 12 for bg in background)]
    if drop_skin:
        no_skin = [p for p in kept if not _is_skin(*p)]
        kept = no_skin if len(no_skin) >= 0.3 * len(kept) else kept
    if len(kept) < 0.05 * len(pixels):
        kept = pixels
    labs = [lab(p) for p in kept]
    clusters = []
    for m in _kmeans(labs, 5):
        center = tuple(sum(labs[i][d] for i in m) / len(m) for d in range(3))
        rgb = [round(sum(kept[i][d] for i in m) / len(m)) for d in range(3)]
        clusters.append({"lab": center, "rgb": rgb, "n": len(m)})
    clusters.sort(key=lambda c: -c["n"])
    merged: list[dict[str, Any]] = []
    for c in clusters:
        near = next((m for m in merged if delta_e76(m["lab"], c["lab"]) < 12), None)
        if near is None:
            merged.append(dict(c))
            continue
        total = near["n"] + c["n"]
        near["lab"] = tuple((near["lab"][d] * near["n"] + c["lab"][d] * c["n"]) / total for d in range(3))
        near["rgb"] = [round((near["rgb"][d] * near["n"] + c["rgb"][d] * c["n"]) / total) for d in range(3)]
        near["n"] = total
    merged.sort(key=lambda c: -c["n"])
    out = []
    for c in merged[:max_colors]:
        share = c["n"] / len(kept)
        if out and share < PALETTE_MIN_SHARE:
            break
        lab_c = tuple(round(v, 1) for v in c["lab"])
        out.append({"rgb": c["rgb"], "hex": "#%02x%02x%02x" % tuple(c["rgb"]), "lab": list(lab_c),
                    "share": round(share, 3), "label": color_name(lab_c)})
    return out


def extract_palette(path: Path, group: str, model_shot: bool, max_colors: int) -> list[dict[str, Any]]:
    from PIL import Image  # optional dependency, only needed when images are read

    with Image.open(path) as image:
        small = image.convert("RGB").resize((60, 75))
    w, h = small.size
    px = small.load()
    border = [px[x, y] for x in range(w) for y in (0, 1, h - 2, h - 1)] + \
             [px[x, y] for y in range(h) for x in (0, 1, w - 2, w - 1)]
    if model_shot:  # 29CM: person + scene; take the band where the garment usually sits
        y0, y1 = (0.18, 0.62) if group == "top" else (0.50, 0.92)
        box = (int(0.22 * w), int(y0 * h), int(0.78 * w), int(y1 * h))
    else:  # Shopify: single garment on a flat background
        box = (int(0.08 * w), int(0.08 * h), int(0.92 * w), int(0.92 * h))
    pixels = [px[x, y] for x in range(box[0], box[2]) for y in range(box[1], box[3])]
    return palette_from_pixels(pixels, border, drop_skin=model_shot, max_colors=max_colors)


# ---- ordinal scores ----------------------------------------------------------------


def round_step(value: float, step: float = FIT_STEP) -> float:
    return math.floor(value / step + 0.5) * step


def fit_score(labels: list[str]) -> float | None:
    scores = [FIT_SCALE[v] for v in labels if v in FIT_SCALE]
    return round_step(sum(scores) / len(scores)) if scores else None


def shift_fit(score: float, direction: int, amount: str = "slight") -> float:
    """Relative feedback target: "조금 더 여유" = +0.5, "훨씬" = +1.0, clipped to the scale."""
    return min(max(score + direction * RELATIVE_STEP[amount], min(FIT_SCALE.values())), max(FIT_SCALE.values()))


def length_values(group: str, labels: list[str]) -> tuple[list[str], float | None]:
    keep = [v for v in labels if v in LENGTH_SCALE[group] or (group == "top" and v == "Cropped")]
    scores = [LENGTH_SCALE[group][v] for v in keep if v in LENGTH_SCALE[group]]
    return keep, (sum(scores) / len(scores) if scores else None)


# ---- Weight ------------------------------------------------------------------------
WEIGHT_RULES = [
    ("Light", v2._rx("lightweight", "light-weight", "light weight", "thin fabric", "thin cotton", "sheer", "breathable", "summer weight",
                     "얇은", "얇아", "얇게", "시원한", "시어한")),
    ("Heavy", v2._rx("heavyweight", "heavy-weight", "heavy weight", "heavy cotton", "heavy jersey", "thick", "chunky",
                     "padded", "quilted", "insulated", "도톰", "두툼", "두꺼운", "보온")),
    ("Mid", v2._rx("midweight", "mid-weight", "mid weight", "medium weight", "medium-weight", "적당한 두께")),
]
GSM = re.compile(r"(\d{3})\s?(?:gsm|g/m2|g/m²)", re.I)
LIGHT_TYPES = {"T-shirt", "Polo", "Blouse", "Sleeveless", "Shorts", "Leggings", "Shirt"}


def weight_of(pi: dict[str, Any], seller: str) -> dict[str, Any] | None:
    found = GSM.search(seller)
    if found:
        grams = int(found.group(1))
        value = "Light" if grams < 200 else "Heavy" if grams >= 320 else "Mid"
        return v2.slot([value], "confirmed", "gsm", [found.group(0)])
    values, quotes = v2.match(WEIGHT_RULES, seller)
    if len(values) == 1:
        return v2.slot(values, "confirmed", "keyword", quotes)

    def has(axis: str, *wanted: str) -> bool:
        return any(v in (pi.get(axis) or {}).get("values", []) for v in wanted)
    type_value = (pi.get("Type") or {}).get("values", [None])[0]
    if has("Texture", "Fleece", "Boucle", "Corduroy"):
        return v2.slot(["Heavy"], "derived", "texture_rule", pi["Texture"]["values"])
    if type_value in ("Sweater", "Cardigan") and has("Fabric", "Wool", "Cashmere"):
        return v2.slot(["Heavy"], "derived", "type_fabric_rule", [type_value] + pi["Fabric"]["values"])
    if has("Fabric", "Linen") or has("Texture", "Seersucker"):
        return v2.slot(["Light"], "derived", "fabric_rule", (pi.get("Fabric") or pi["Texture"])["values"])
    if type_value:
        return v2.slot(["Light" if type_value in LIGHT_TYPES else "Mid"], "derived", "type_rule", [type_value])
    return None


# ---- Style ---------------------------------------------------------------------------
STYLE_RULES = [
    ("Outdoor", v2._rx("outdoor", "outdoors", "gorpcore", "hiking", "trail", "mountain", "polartec", "windproof",
                       "waterproof", "water-repellent", "water repellent", "아웃도어", "고프코어", "등산", "방수", "발수")),
    ("Formal", v2._rx("tailored", "tailoring", "smart", "suiting", "formal", "dress shirt", "테일러드", "포멀", "수트", "정장")),
    ("Minimal", v2._rx("minimal", "minimalist", "clean lines", "simple", "plain", "미니멀", "심플", "무지")),
    ("Casual", v2._rx("casual", "laid-back", "laid back", "캐주얼")),
]
DECORATED = {"Graphic", "Logo", "Floral", "Jacquard", "Stripe", "Check", "Other"}
DECORATION_DETAIL = {"Embroidery", "Patch", "Distressed", "Washed"}


def style_of(pi: dict[str, Any], seller: str) -> dict[str, Any] | None:
    old = pi.get("Style")
    old_values = old["values"] if old else []
    pattern = set((pi.get("Pattern") or {}).get("values", []))
    detail = set((pi.get("Detail") or {}).get("values", []))
    plain = not (pattern & DECORATED) and not (detail & DECORATION_DETAIL)
    specific = [STYLE_MAP.get(v, v) for v in old_values if v != "Classic"]
    hits, quotes = v2.match(STYLE_RULES, seller)
    generic = []
    if "Classic" in old_values:
        generic.append("Minimal" if plain else "Casual")
    for value in hits:
        if value in ("Minimal", "Casual") and generic:
            continue
        if value == "Minimal" and not plain:
            continue
        (generic if value in ("Minimal", "Casual") else specific).append(value)
    values = list(dict.fromkeys(specific + generic))[:STYLE_MAX]
    if not values:
        return None
    if old and not hits:
        return v2.slot(values, old["status"], old["method"] + "+v3_split", old["evidence"])
    return v2.slot(values, "derived", "keyword+v3_split", quotes + (old["evidence"] if old else []))


# ---- record conversion -------------------------------------------------------------


def seller_texts(data: Path) -> dict[str, str]:
    texts = {}
    for source in ("colebuxton", "waxlondon"):
        for p in json.loads((data / "raw" / source / "catalog.json").read_text(encoding="utf-8")):
            texts[f"{source}-{p['id']}"] = f"{p['title']}. {v2.clean(p.get('body_html'))}"
    for line in (data / "raw" / "29cm" / "lumi-catalog-v1.jsonl").read_text(encoding="utf-8").split("\n"):
        if line.strip():
            r = json.loads(line)
            texts[r["product_id"]] = (f"{r['title']}. {v2.clean(r.get('description'))}. "
                                      f"{r['raw_metadata'].get('product_info') or ''}")
    return texts


def price_of(price: dict[str, Any]) -> dict[str, Any]:
    try:
        amount = float(price["amount"]) if price.get("amount") not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    currency = price.get("currency")
    if amount is None:
        krw = None
    elif currency == "KRW":
        krw = round(amount)
    else:
        krw = round(amount * FX[currency]["KRW"])
    out: dict[str, Any] = {"amount": amount, "currency": currency, "price_krw": krw}
    if currency in FX:
        out["fx"] = {"rate": FX[currency]["KRW"], "date": FX[currency]["date"], "source": FX[currency]["source"]}
    return out


def convert(record: dict[str, Any], seller: str, palette: list[dict[str, Any]] | None) -> dict[str, Any]:
    group, old = record["group"], record["pi"]
    pi: dict[str, Any] = {}
    merged: list[str] = []
    for axis in ("Type", "Pattern", "Texture", "Fabric", "Detail"):
        if axis in old:
            pi[axis] = dict(old[axis], values=list(old[axis]["values"]))
    if "Type" in pi:
        original = pi["Type"]["values"][0]
        if original in TYPE_MERGE:
            pi["Type"]["values"] = [TYPE_MERGE[original]]
            pi["Type"]["merged_from"] = original
            merged.append(f"Type:{original}")
            if original in TYPE_MERGE_DETAIL:
                detail = pi.setdefault("Detail", v2.slot([], "derived", "type_merge", [original]))
                if TYPE_MERGE_DETAIL[original] not in detail["values"]:
                    detail["values"].append(TYPE_MERGE_DETAIL[original])
    for axis in ("Pattern", "Texture", "Fabric", "Detail"):
        table = {**VALUE_MERGE.get(axis, {}), **GROUP_MERGE[group].get(axis, {})}
        if axis in pi and any(v in table for v in pi[axis]["values"]):
            pi[axis]["merged_from"] = [v for v in pi[axis]["values"] if v in table]
            merged += [f"{axis}:{v}" for v in pi[axis]["merged_from"]]
            values = [table.get(v, v) for v in pi[axis]["values"]]
            pi[axis]["values"] = list(dict.fromkeys(v for v in values if v is not None))
            if not pi[axis]["values"]:
                del pi[axis]

    seller_colors = [c for c in (old.get("Color") or {}).get("values", []) if c != "Multi"]
    if palette:
        colors = palette if (old.get("Pattern") or {}).get("values") != ["Solid"] else palette[:1]
        pi["Color"] = {"values": list(dict.fromkeys(c["label"] for c in colors)), "colors": colors,
                       "status": "derived", "method": "image_palette", "evidence": [record["image"]],
                       "seller_values": (old.get("Color") or {}).get("values", [])}
        lightness = colors[0]["lab"][0]
        pi["Tone"] = {"values": [tone_label(lightness)], "score": lightness, "status": "derived",
                      "method": "lab_lightness", "evidence": [colors[0]["hex"]]}
    elif seller_colors:
        lab = COLOR_ANCHORS[seller_colors[0]]
        pi["Color"] = dict(old["Color"], values=seller_colors, colors=[], seller_values=old["Color"]["values"])
        pi["Tone"] = {"values": [tone_label(lab[0])], "score": round(lab[0], 1), "status": "derived",
                      "method": "anchor_lightness", "evidence": seller_colors[:1]}

    if "Fit" in old:
        score = fit_score(old["Fit"]["values"])
        if score is not None:
            pi["Fit"] = dict(old["Fit"], score=score, scale=group, image_adjustment=None)
    if group == "bottom" and "Silhouette" in old:
        keep = [v for v in old["Silhouette"]["values"] if v in SCHEMA["Silhouette"]["values"]]
        if keep:
            pi["Silhouette"] = dict(old["Silhouette"], values=keep)
    if "Length" in old:
        keep, score = length_values(group, old["Length"]["values"])
        if keep:
            pi["Length"] = dict(old["Length"], values=keep, score=score, scale=group)
    weight = weight_of(pi, seller)
    if weight:
        weight["score"] = WEIGHT_SCALE[weight["values"][0]]
        pi["Weight"] = weight
    style = style_of(dict(old, Pattern=pi.get("Pattern"), Detail=pi.get("Detail")), seller)
    if style:
        pi["Style"] = style
    out = {k: record[k] for k in ("id", "source", "source_product_id", "group", "gender", "title", "brand",
                                  "image", "url_handle")}
    out["price"] = price_of(record["price"])
    out["pi"] = pi
    out["merged"] = merged
    return out


def validate(records: list[dict[str, Any]]) -> None:
    for record in records:
        for axis, entry in record["pi"].items():
            allowed = SCHEMA[axis].get("values")
            bad = [v for v in entry["values"] if allowed is not None and v not in allowed]
            if bad:
                raise SystemExit(f"{record['id']} {axis}: values outside schema {bad}")
            if axis == "Style" and len(entry["values"]) > STYLE_MAX:
                raise SystemExit(f"{record['id']} Style: more than {STYLE_MAX} values")
            if axis == "Silhouette" and record["group"] != "bottom":
                raise SystemExit(f"{record['id']} Silhouette on a top")


def rare_values(records: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    """Per group and categorical axis: values below RARE_SHARE of the products filled on that axis."""
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for group in ("top", "bottom"):
        rows = [r for r in records if r["group"] == group]
        for axis, spec in SCHEMA.items():
            if spec["kind"] != "categorical" or axis == "Price":
                continue
            filled = [r for r in rows if axis in r["pi"]]
            counts = Counter(v for r in filled for v in r["pi"][axis]["values"])
            low = {v: {"count": n, "share": round(n / len(filled), 4)} for v, n in counts.items()
                   if filled and n / len(filled) < RARE_SHARE}
            if low:
                out.setdefault(group, {})[axis] = low
    return out


def proxy_checks(records: list[dict[str, Any]], v2_records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Automatic agreement against seller colour words and v2 Tone. A proxy, not a human judgement."""
    out: dict[str, Any] = {}
    for source in sorted({r["source"] for r in records}):
        rows = [r for r in records if r["source"] == source and (r["pi"].get("Color") or {}).get("colors")]
        seller = [r for r in rows if [c for c in r["pi"]["Color"]["seller_values"] if c != "Multi"]
                  and len(r["pi"]["Color"]["seller_values"]) == 1]
        main_hit = sum(r["pi"]["Color"]["colors"][0]["label"] in r["pi"]["Color"]["seller_values"] for r in seller)
        near = sum(min(anchor_distance(r["pi"]["Color"]["colors"][0]["lab"], s)
                       for s in r["pi"]["Color"]["seller_values"]) < 20 for r in seller)
        tone_rows = [r for r in rows if "Tone" in v2_records[r["id"]]["pi"]]
        tone_hit = sum(r["pi"]["Tone"]["values"][0] in v2_records[r["id"]]["pi"]["Tone"]["values"] for r in tone_rows)
        out[source] = {"with_palette": len(rows), "single_seller_colour": len(seller),
                       "main_label_equals_seller": round(main_hit / len(seller), 3) if seller else None,
                       "main_within_de2000_20_of_seller": round(near / len(seller), 3) if seller else None,
                       "tone_equals_v2": round(tone_hit / len(tone_rows), 3) if tone_rows else None}
    return out


def report_of(records: list[dict[str, Any]], v2_records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    fill: dict[str, Any] = {}
    for group in ("top", "bottom"):
        rows = [r for r in records if r["group"] == group]
        for axis in AXES:
            filled = [r for r in rows if axis in r["pi"]]
            entry: dict[str, Any] = {
                "filled": len(filled), "of": len(rows),
                "by_status": dict(Counter(r["pi"][axis]["status"] for r in filled)),
                "by_method": dict(Counter(r["pi"][axis]["method"] for r in filled).most_common()),
                "values": dict(Counter(v for r in filled for v in r["pi"][axis]["values"]).most_common())}
            scores = [r["pi"][axis]["score"] for r in filled if r["pi"][axis].get("score") is not None]
            if scores:
                entry["scores"] = (dict(sorted(Counter(round(s / 10) * 10 for s in scores).items())) if axis == "Tone"
                                   else dict(sorted(Counter(scores).items())))
            if axis == "Color":
                entry["palette_size"] = dict(Counter(len(r["pi"][axis].get("colors", [])) for r in filled))
            fill.setdefault(group, {})[axis] = entry
    prices = [r["price"]["price_krw"] for r in records if r["price"]["price_krw"] is not None]
    return {
        "version": VERSION, "products": len(records), "by_source": dict(Counter(r["source"] for r in records)),
        "by_group": dict(Counter(r["group"] for r in records)),
        "price_krw": {"filled": len(prices), "min": min(prices, default=None), "max": max(prices, default=None),
                      "median": sorted(prices)[len(prices) // 2] if prices else None, "fx": FX},
        "merged": {group: dict(Counter(m for r in records if r["group"] == group for m in r["merged"]))
                   for group in ("top", "bottom")},
        "below_rare_share": rare_values(records), "rare_share": RARE_SHARE,
        "proxy_checks": proxy_checks(records, v2_records), "fill": fill, "schema": SCHEMA, "meta": META,
    }


# ---- human review sheet ------------------------------------------------------------
REVIEW_FIELDS = ["id", "source", "group", "image", "title", "seller_colors", "extracted_colors", "fit_labels",
                 "fit_score", "human_main_color", "human_palette_ok", "human_fit_score", "note"]


def write_review(records: list[dict[str, Any]], data: Path, size: int) -> Path:
    rng = random.Random(20)
    picked = []
    sources = sorted({r["source"] for r in records})
    for i, source in enumerate(sources):
        pool = [r for r in records if r["source"] == source and "Fit" in r["pi"] and r["pi"].get("Color", {}).get("colors")]
        picked += rng.sample(pool, min(len(pool), size // len(sources) + (1 if i < size % len(sources) else 0)))
    path = data / "catalog" / f"{VERSION}-review.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS)
        writer.writeheader()
        for r in picked:
            colors = r["pi"]["Color"]["colors"]
            writer.writerow({"id": r["id"], "source": r["source"], "group": r["group"], "image": r["image"],
                             "title": r["title"], "seller_colors": "|".join(r["pi"]["Color"]["seller_values"]),
                             "extracted_colors": "|".join(f"{c['label']} {c['hex']} {c['share']}" for c in colors),
                             "fit_labels": "|".join(r["pi"]["Fit"]["values"]), "fit_score": r["pi"]["Fit"]["score"]})
    rows = "".join(
        f"<tr><td><img src='../{r['image']}' width=160></td><td>{r['id']}<br>{r['title']}</td><td>"
        + "".join(f"<div><span style='display:inline-block;width:40px;height:20px;background:{c['hex']};"
                  f"border:1px solid #888'></span> {c['label']} {c['hex']} {c['share']}</div>"
                  for c in r["pi"]["Color"]["colors"])
        + f"</td><td>seller: {', '.join(r['pi']['Color']['seller_values'])}</td>"
          f"<td>{', '.join(r['pi']['Fit']['values'])} = {r['pi']['Fit']['score']}</td></tr>"
        for r in picked)
    (data / "catalog" / f"{VERSION}-review.html").write_text(
        "<!doctype html><meta charset=utf-8><title>PI v3 review</title><table border=1 cellpadding=4>"
        "<tr><th>image</th><th>product</th><th>extracted</th><th>seller</th><th>fit</th></tr>" + rows + "</table>",
        encoding="utf-8")
    return path


def score_review(path: Path) -> dict[str, Any]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    color = [r for r in rows if r["human_main_color"].strip()]
    palette = [r for r in rows if r["human_palette_ok"].strip()]
    fit = [r for r in rows if r["human_fit_score"].strip()]

    def main(r: dict[str, str]) -> str:
        return r["extracted_colors"].split("|")[0].rsplit(" ", 2)[0]
    fit_diff = [abs(float(r["human_fit_score"]) - float(r["fit_score"])) for r in fit]
    return {
        "reviewed": len(rows),
        "main_color_label": {"n": len(color), "agree": sum(main(r) == r["human_main_color"].strip() for r in color)},
        "palette_ok": {"n": len(palette), "agree": sum(r["human_palette_ok"].strip().lower() in ("y", "yes", "1")
                                                       for r in palette)},
        "fit_exact": {"n": len(fit), "agree": sum(d == 0 for d in fit_diff)},
        "fit_within_0_5": {"n": len(fit), "agree": sum(d <= 0.5 for d in fit_diff)},
    }


RUNTIME_GARMENTS = {"top": ("Top", "상의"), "bottom": ("Bottom", "하의")}
RUNTIME_LABEL_KO = v2.LABEL_KO | {"Weight": "두께"}


def export_runtime(records: list[dict[str, Any]], data: Path, registry_path: Path) -> dict[str, Any]:
    """Tops + bottoms runtime dictionary (lumi-pi-v3) and a lumi-catalog-v1 import file.

    Same split as the v2 tops export: confirmed/derived labels go to ``raw_metadata.<axis>``, inferred labels go to
    ``labels`` as model_interpretation. The v3 value shapes that the runtime does not compare yet (ordinal
    ``score``, colour Lab, ``price_krw``) are kept under ``raw_metadata.pi_v3`` for the answer-reflection work.
    """
    park = json.loads((v2.ROOT / "output/feature-map/park-2025-feature-map.json").read_text(encoding="utf-8"))
    counts = {axis: Counter(v for r in records if axis in r["pi"] for v in r["pi"][axis]["values"]) for axis in AXES}
    counts["Brand"] = Counter(r["brand"] for r in records if r.get("brand"))
    order = ("Type", "Brand") + AXES[1:]
    pi = {}
    for axis in order:
        values = sorted(counts[axis]) if axis == "Brand" else [v for v in SCHEMA[axis]["values"] if counts[axis][v]]
        pi[axis] = {"label_ko": RUNTIME_LABEL_KO[axis], "values": values, "reported_count": len(values),
                    "enumeration_complete": True, "distribution": {v: counts[axis][v] for v in values}}
        if axis in SCHEMA:
            pi[axis]["value_shape"] = {k: SCHEMA[axis][k] for k in ("kind", "fill", "condition", "scale", "groups")
                                       if k in SCHEMA[axis]}
    pi["Type"]["values_by_garment_type"] = {
        garment: [v for v in pi["Type"]["values"] if any(r["group"] == group and v in r["pi"]["Type"]["values"]
                                                         for r in records)]
        for group, (garment, _) in RUNTIME_GARMENTS.items()}
    registry = {
        "name": "LUMI PI v3 tops and bottoms (ADR 0016) + Park FEA taxonomy",
        "version": VERSION, "status": "Generated", "runtime_implemented": True,
        "scope": "29CM·Cole Buxton·Wax London 상·하의를 담은 PI v3 실행 사전이다. 값 라벨은 영어다(ADR 0014·0016).",
        "lumi_use": "PI 축은 ADR 0016의 12축(+Brand), FEA 30개 태그는 Park 사전을 그대로 쓴다. 실행 비교는 라벨 일치이며, "
                    "점수·Lab·price_krw는 상품 raw_metadata.pi_v3에만 둔다.",
        "generated_by": "scripts/build_lumi_pi_v3.py --export-runtime",
        "axis_order": list(order),
        "product_information": pi,
        "consumer_needs_taxonomy": park["consumer_needs_taxonomy"],
        "garment_types": [{"value": garment, "label_ko": label} for garment, label in RUNTIME_GARMENTS.values()],
        "execution": {"supported_garment_types": [garment for garment, _ in RUNTIME_GARMENTS.values()],
                      "accept_inferred_product_pi": True, "price_currency": None, "price_boundary_inclusion": None},
        "counts": {"products": len(records), "product_information_categories": len(pi),
                   "consumer_needs_attributes": park["counts"]["consumer_needs_attributes"],
                   "values": {a: len(pi[a]["values"]) for a in order}},
        "source_boundaries": [
            "confirmed는 구조화 필드·판매자 문구 키워드, derived는 고정 규칙·이미지 색 추출, inferred는 DeepSeek 텍스트·이미지 해석이다.",
            "inferred 값은 상품 Map에서 status=inferred·model_interpretation으로 남는다. accept_inferred_product_pi=true는 실행 선택이며 검증 라벨이 아니다.",
            "Silhouette은 하의 전용이다. Fabric은 사진으로 갱신하지 않는다(ADR 0013 결정 8).",
        ],
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = []
    for r in records:
        shapes = {axis: {k: entry[k] for k in ("score", "scale", "colors") if k in entry}
                  for axis, entry in r["pi"].items() if any(k in entry for k in ("score", "colors"))}
        raw_md: dict[str, Any] = {"group": r["group"], "gender": r["gender"], "brand_text": r.get("brand"),
                                  "price_text": r["price"]["amount"], "currency": r["price"]["currency"],
                                  "pi_inferred": {},
                                  "pi_v3": {"price_krw": r["price"].get("price_krw"), "axes": shapes}}
        if r.get("brand"):
            raw_md["brand"] = r["brand"]
        labels = []
        for axis in AXES:
            entry = r["pi"].get(axis)
            if not entry or not entry["values"]:
                continue
            if entry["status"] in ("confirmed", "derived"):
                raw_md[axis.lower()] = entry["values"]
            else:
                evidence = " | ".join(str(e) for e in entry.get("evidence", []) if e)[:4000] or ", ".join(entry["values"])
                raw_md["pi_inferred"][axis] = {"values": entry["values"], "method": entry["method"], "evidence": evidence}
                labels.append({"observation": {"domain": "PI", "feature": axis, "values": entry["values"]},
                               "status": "inferred",
                               "provenance": [{"kind": "model_interpretation",
                                               "source_field": f"raw_metadata.pi_inferred.{axis}.evidence",
                                               "quote": evidence, "verifier": None, "evidence_ref": None,
                                               "verified_at": None}]})
        image = data / r["image"]
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        url = r["url_handle"] if r["source"] == "29cm" else v2.SHOP_URL[r["source"]] + r["url_handle"]
        collected = datetime.fromtimestamp(image.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        lines.append(json.dumps({
            "format_version": "lumi-catalog-v1", "product_id": r["id"],
            "source": {"source_id": r["source"], "url": url, "collected_at": collected},
            "title": r["title"], "description": None, "garment_type": RUNTIME_GARMENTS[r["group"]][0],
            "raw_metadata": raw_md,
            "images": [{"image_id": f"{r['id']}-0", "kind": "local", "location": r["image"].removeprefix("images/"),
                        "source_revision": f"sha256:{digest}", "sha256": digest, "regions": []}],
            "labels": labels}, ensure_ascii=False))
    (data / "catalog" / f"{VERSION}-import.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"products": len(records), "by_garment": dict(Counter(RUNTIME_GARMENTS[r["group"]][0] for r in records))}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--no-images", action="store_true", help="skip palette extraction (Color falls back to seller words)")
    parser.add_argument("--review-sample", type=int, default=0, help="write a stratified human review sheet of N products")
    parser.add_argument("--score-review", type=Path, help="score a filled review CSV and exit")
    parser.add_argument("--export-runtime", action="store_true",
                        help="also write output/feature-map/lumi-pi-v3.json and data/catalog/lumi-pi-v3-import.jsonl")
    args = parser.parse_args()
    if args.score_review:
        print(json.dumps(score_review(args.score_review), ensure_ascii=False, indent=1))
        return 0
    old = v2.shopify_records(args.data, "colebuxton") + v2.shopify_records(args.data, "waxlondon") + v2.records_29cm(args.data)
    v2.apply_text_fills(old, args.data)
    v2.apply_image_fills(old, args.data)
    v2.validate(old)
    texts = seller_texts(args.data)
    records = []
    for r in old:
        palette = None if args.no_images else extract_palette(args.data / r["image"], r["group"], r["source"] == "29cm",
                                                               PALETTE_MAX)
        records.append(convert(r, texts.get(r["id"], r["title"]), palette))
    validate(records)
    out_dir = args.data / "catalog"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{VERSION}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                              encoding="utf-8")
    report = report_of(records, {r["id"]: r for r in old})
    (out_dir / f"{VERSION}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("products", "by_source", "by_group", "price_krw", "merged",
                                             "below_rare_share", "proxy_checks")}, ensure_ascii=False))
    for group in ("top", "bottom"):
        for axis in AXES:
            entry = report["fill"][group][axis]
            print(f"{group:6s} {axis:10s} {entry['filled']:4d}/{entry['of']} {entry['values']}")
    if args.review_sample:
        print("review sheet:", write_review(records, args.data, args.review_sample))
    if args.export_runtime:
        print(json.dumps(export_runtime(records, args.data, v2.ROOT / "output/feature-map" / f"{VERSION}.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
