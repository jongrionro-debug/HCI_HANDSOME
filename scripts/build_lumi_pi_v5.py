#!/usr/bin/env python3
"""LUMI PI v5 (ADR 0019): PI v4 (ADR 0018) plus the ``skirt`` group for 29CM women's skirts.

v5 keeps every v4 rule for ``top``, ``bottom`` and ``outer`` and adds:
  - group ``skirt``: Type Skirt · Skort, a skirt-length Length scale (Mini · Knee · Midi · Long), skirt
    Silhouette values (Pencil · H-line · A-line · Flare · Mermaid) and Weight item rules
  - Fit is not used for skirts (it overlaps Silhouette); Silhouette is used by bottom and skirt
  - Texture: Velvet, Lace, Satin, Tulle  ·  Detail: Wrap, Tiered, Ruffle  ·  Pattern: Dot
  - Style: Feminine, for the skirt group only
  - the 29CM 데님 small category does not set Texture: it also lists wool and pencil skirts (trial crawl 2026-11-26)
  - Length reads the title before the small category, and the seller text only after it

Skirt products are filled by ``skirt_pi`` with rules only (no model call). Each slot keeps v2's
``values`` / ``status`` (confirmed | derived) / ``method`` / ``evidence``; ordinal axes add ``score``.
Color, Tone, Pattern, Style and Price use the v2/v3 functions unchanged (29CM model cuts use the v3 bottom band).

    python3 scripts/build_lumi_pi_v5.py --schema        # print the v5 schema as JSON
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_lumi_pi_v2 as v2  # noqa: E402
import build_lumi_pi_v3 as v3  # noqa: E402
import build_lumi_pi_v4 as v4  # noqa: E402

VERSION = "lumi-pi-v5"
GROUPS = (*v4.GROUPS, "skirt")

# ---- Type ----------------------------------------------------------------------------
# 29CM 여성의류 > 스커트 small categories (2026-11-26): 미니 · 미디 · 롱 · 데님. They split by length or fabric,
# not by garment, so every small category gives Type Skirt; length goes to Length. Skort needs a keyword.
SKIRT_SUBCATEGORIES = ("미니", "미디", "롱", "데님")
SKIRT_TYPES = ["Skirt", "Skort"]
SKORT_RULE = re.compile(r"\bskort\b|\bskirt[\s-]?pants\b|\bculottes?\b|스커트\s?팬츠|치마\s?바지|큐롯", re.I)
# Skirt leaves bottom: in v5 it is the skirt group's Type, so a bottom grid no longer mixes pants and skirts.
TYPE_VALUES = {**v4.TYPE_VALUES, "bottom": [t for t in v4.TYPE_VALUES["bottom"] if t != "Skirt"], "skirt": SKIRT_TYPES}
TYPE_MERGE = {**v4.TYPE_MERGE, "skirt": {}}

# ---- Length (skirt: hem length) ----------------------------------------------------------
LENGTH_SCALE = {**v4.LENGTH_SCALE, "skirt": {"Mini": 1.0, "Knee": 2.0, "Midi": 3.0, "Long": 4.0}}
SKIRT_LENGTH_BY_SUBCATEGORY = {"미니": "Mini", "미디": "Midi", "롱": "Long"}  # 데님 carries no length
SKIRT_LENGTH_RULES = [
    ("Mini", re.compile(r"\bmini\b|미니(?!멀)", re.I)),  # 미니멀 is a style
    ("Knee", v2._rx("knee", "knee-length", "knee length", "무릎")),
    ("Midi", v2._rx("midi", "미디")),
    # 롱슬리브 is a sleeve, not a hem
    ("Long", re.compile(r"\b(?:long|maxi)\b(?![\s-]*sleeve)|롱(?!\s*슬리브)|맥시", re.I)),
]
# Middle-size 총장 (cm) -> label. Upper bounds; at or above the last bound is Long.
# These bounds are an assumption to tune from the collected distribution (ADR 0019).
SKIRT_LENGTH_CM = [(45.0, "Mini"), (62.0, "Knee"), (82.0, "Midi")]

# ---- Silhouette (skirt values) ------------------------------------------------------------
SKIRT_SILHOUETTES = ["Pencil", "H-line", "A-line", "Flare", "Mermaid"]
SKIRT_SILHOUETTE_RULES = [
    ("Pencil", v2._rx("pencil", "펜슬")),
    ("H-line", re.compile(r"\bh[\s-]?line\b|h\s?라인|에이치\s?라인", re.I)),
    ("A-line", re.compile(r"\ba[\s-]?line\b|a\s?라인|에이\s?라인", re.I)),
    ("Flare", v2._rx("flare", "flared", "circle", "플레어", "서큘러")),
    ("Mermaid", v2._rx("mermaid", "trumpet", "머메이드", "트럼펫")),
]

# ---- added values ------------------------------------------------------------------------
TEXTURE_ADDED = ["Velvet", "Lace", "Satin", "Tulle"]
DETAIL_ADDED = ["Wrap", "Tiered", "Ruffle"]
PATTERN_ADDED = ["Dot"]
STYLE_ADDED = {"skirt": ["Feminine"]}
SKIRT_TEXTURE_RULES = [
    ("Velvet", v2._rx("velvet", "velour", "벨벳", "벨로아")),
    ("Lace", re.compile(r"\blace\b(?![\s-]*up)|레이스(?!\s*업)", re.I)),  # lace-up is a closure
    ("Satin", v2._rx("satin", "새틴", "사틴")),
    ("Tulle", re.compile(r"\btulle\b|튤(?!립)|망사", re.I)),  # 튤립 is a tulip cut
]
SKIRT_DETAIL_RULES = [
    # "랩" alone also hits 스트랩, so the Korean word needs 스커트·치마 or a space after it
    ("Wrap", re.compile(r"\bwrap(?:ped)?\b|(?<![가-힣])랩\s?(?:스커트|치마)|(?<![가-힣])랩(?=\s)", re.I)),
    ("Tiered", v2._rx("tiered", "tier", "티어드", "캉캉")),
    ("Ruffle", v2._rx("ruffle", "ruffled", "frill", "frilled", "러플", "프릴")),
]
SKIRT_PATTERN_RULES = [("Dot", v2._rx("dot", "dots", "polka", "도트", "땡땡이"))]

# ---- Weight (skirt) ------------------------------------------------------------------------
SKIRT_HEAVY_TEXTURE = {"Velvet", "Corduroy", "Tweed", "Melton", "Suede", "Boucle"}
SKIRT_HEAVY_FABRIC_ANY = {"Leather", "Fur"}
SKIRT_HEAVY_FABRIC_TITLE = {"Wool", "Cashmere"}
SKIRT_LIGHT_TEXTURE = {"Tulle", "Lace", "Seersucker"}
SKIRT_LIGHT_FABRIC = {"Linen"}
CHIFFON = v2._rx("chiffon", "voile", "organza", "시폰", "쉬폰", "보일", "오간자")

# ---- schema ---------------------------------------------------------------------------------
SCHEMA: dict[str, dict[str, Any]] = copy.deepcopy(v4.SCHEMA)
SCHEMA["Type"].update(values=list(dict.fromkeys(t for g in GROUPS for t in TYPE_VALUES[g])),
                      values_by_group=TYPE_VALUES, merge_by_group=TYPE_MERGE)
SCHEMA["Length"].update(scale=LENGTH_SCALE,
                        values_by_group={**SCHEMA["Length"]["values_by_group"], "skirt": list(LENGTH_SCALE["skirt"])})
SCHEMA["Length"]["values"] = list(dict.fromkeys(SCHEMA["Length"]["values"] + list(LENGTH_SCALE["skirt"])))
SCHEMA["Silhouette"].update(groups=["bottom", "skirt"],
                            values_by_group={"bottom": list(v3.SCHEMA["Silhouette"]["values"]), "skirt": SKIRT_SILHOUETTES})
SCHEMA["Silhouette"]["values"] = list(dict.fromkeys(SCHEMA["Silhouette"]["values"] + SKIRT_SILHOUETTES))
SCHEMA["Texture"]["values"] = SCHEMA["Texture"]["values"] + TEXTURE_ADDED
SCHEMA["Detail"]["values"] = SCHEMA["Detail"]["values"] + DETAIL_ADDED
SCHEMA["Pattern"]["values"] = SCHEMA["Pattern"]["values"] + PATTERN_ADDED
_style = list(SCHEMA["Style"]["values"])
SCHEMA["Style"]["values"] = _style + STYLE_ADDED["skirt"]
SCHEMA["Style"]["values_by_group"] = {g: _style + STYLE_ADDED.get(g, []) for g in GROUPS}
AXES = tuple(a for a in SCHEMA if a != "Price")
META = dict(copy.deepcopy(v4.META), groups=list(GROUPS),
            unused_by_group={**v4.META["unused_by_group"], "skirt": ["Fit"]},
            skirt_length_cm=SKIRT_LENGTH_CM, skirt_subcategories=list(SKIRT_SUBCATEGORIES))


# ---- skirt rules ------------------------------------------------------------------------------

def skirt_type(subcategory: str, text: str) -> dict[str, Any] | None:
    found = SKORT_RULE.search(text or "")
    if found:
        return v2.slot(["Skort"], "confirmed", "keyword", [found.group(0)])
    if subcategory.strip() in SKIRT_SUBCATEGORIES:
        return v2.slot(["Skirt"], "confirmed", "subcategory", [subcategory])
    return None


def length_from_cm(cm: float) -> str:
    for bound, label in SKIRT_LENGTH_CM:
        if cm < bound:
            return label
    return "Long"


def skirt_length(subcategory: str, title: str, seller_text: str = "", size_text: str = "") -> dict[str, Any] | None:
    """Title keyword > subcategory > seller keyword > middle-size 총장. The first step that decides wins.

    Unlike v4 outer, the title comes before the subcategory: in the trial crawl a 미디 listing was titled
    "Long Skirt" and the 데님 small category carries no length. Seller text comes after the subcategory
    because it names lengths in passing ("미니 립 포켓" on a 미디 pencil skirt).
    """
    scale = LENGTH_SCALE["skirt"]
    sub = subcategory.strip()

    def out(value: str, status: str, method: str, evidence: list[str]) -> dict[str, Any]:
        return dict(v2.slot([value], status, method, evidence), score=scale[value], scale="skirt")
    value, quotes = v4._one(SKIRT_LENGTH_RULES, title or "")
    if value:
        return out(value, "confirmed", "title_keyword", quotes)
    if sub in SKIRT_LENGTH_BY_SUBCATEGORY:
        return out(SKIRT_LENGTH_BY_SUBCATEGORY[sub], "confirmed", "subcategory", [subcategory])
    value, quotes = v4._one(SKIRT_LENGTH_RULES, seller_text or "")
    if value:
        return out(value, "confirmed", "keyword", quotes)
    cm = v4.total_length_cm(size_text)
    if cm is not None:
        return out(length_from_cm(cm), "confirmed", "total_length_cm", [f"총장 {cm:g}cm"])
    return None


def skirt_silhouette(text: str) -> dict[str, Any] | None:
    """One silhouette keyword, else nothing (left for the model pass)."""
    value, quotes = v4._one(SKIRT_SILHOUETTE_RULES, text or "")
    return v2.slot([value], "confirmed", "keyword", quotes) if value else None


def _keyword_slot(axis: str, rules: list[tuple[str, re.Pattern[str]]], text: str) -> dict[str, Any] | None:
    values, quotes = v2.match(rules, text or "")
    merge = v3.VALUE_MERGE.get(axis, {})
    values = list(dict.fromkeys(merge.get(v, v) for v in values if merge.get(v, v) in SCHEMA[axis]["values"]))
    return v2.slot(values, "confirmed", "keyword", quotes) if values else None


def skirt_keywords(text: str) -> dict[str, dict[str, Any]]:
    """Fabric, Texture, Detail and Pattern from seller keywords (confirmed). No subcategory rule (see 데님)."""
    out: dict[str, dict[str, Any]] = {}
    for axis, rules in (("Fabric", v2.FABRIC_RULES + v4.OUTER_FABRIC_RULES),
                        ("Texture", v2.TEXTURE_RULES + v4.OUTER_TEXTURE_RULES + SKIRT_TEXTURE_RULES),
                        ("Detail", v2.DETAIL_RULES + SKIRT_DETAIL_RULES),
                        ("Pattern", SKIRT_PATTERN_RULES)):
        found = _keyword_slot(axis, rules, text)
        if found:
            out[axis] = found
    return out


def skirt_weight(pi: dict[str, Any], text: str, title: str = "") -> dict[str, Any] | None:
    """GSM > thickness keyword > material rule > Mid (v3 order, skirt rules).

    Wool and cashmere count as heavy only when the title names them: seller blends list a few percent of wool
    on light polyester skirts (trial crawl: "polyester 65 / rayon 22 / wool 4").
    """
    def out(value: str, status: str, method: str, evidence: list[str]) -> dict[str, Any]:
        return dict(v2.slot([value], status, method, evidence), score=v3.WEIGHT_SCALE[value])
    found = v3.GSM.search(text or "")
    if found:
        grams = int(found.group(1))
        return out("Light" if grams < 200 else "Heavy" if grams >= 320 else "Mid", "confirmed", "gsm", [found.group(0)])
    value, quotes = v4._one(v3.WEIGHT_RULES, text or "")
    if value:
        return out(value, "confirmed", "keyword", quotes)
    texture = set((pi.get("Texture") or {}).get("values", []))
    fabric = set((pi.get("Fabric") or {}).get("values", []))
    title_fabric = set(v2.match(v2.FABRIC_RULES, title or "")[0])
    heavy = texture & SKIRT_HEAVY_TEXTURE | fabric & SKIRT_HEAVY_FABRIC_ANY | title_fabric & SKIRT_HEAVY_FABRIC_TITLE
    if heavy:
        return out("Heavy", "derived", "material_rule", sorted(heavy))
    chiffon = CHIFFON.search(text or "")
    if texture & SKIRT_LIGHT_TEXTURE or fabric & SKIRT_LIGHT_FABRIC or chiffon:
        evidence = sorted(texture & SKIRT_LIGHT_TEXTURE | fabric & SKIRT_LIGHT_FABRIC) + ([chiffon.group(0)] if chiffon else [])
        return out("Light", "derived", "material_rule", evidence)
    return out("Mid", "derived", "type_rule", ["Skirt"])


def skirt_pi(subcategory: str, title: str, seller_text: str = "", size_text: str = "") -> dict[str, Any]:
    """Rule-based Type, Length, Silhouette, Fabric, Texture, Detail, Pattern and Weight for one skirt."""
    text = f"{title}. {seller_text}"
    pi: dict[str, Any] = {}
    type_slot = skirt_type(subcategory, text)
    if type_slot:
        pi["Type"] = type_slot
    length = skirt_length(subcategory, title, seller_text, size_text)
    if length:
        pi["Length"] = length
    silhouette = skirt_silhouette(text)
    if silhouette:
        pi["Silhouette"] = silhouette
    pi.update(skirt_keywords(text))
    weight = skirt_weight(pi, text, title)
    if weight:
        pi["Weight"] = weight
    return pi


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--schema", action="store_true", help="print the v5 schema as JSON")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps({"version": VERSION, "groups": list(GROUPS), "schema": SCHEMA, "meta": META},
                         ensure_ascii=False, indent=1))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
