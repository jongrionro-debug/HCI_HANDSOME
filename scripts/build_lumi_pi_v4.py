#!/usr/bin/env python3
"""LUMI PI v4 (ADR 0017): PI v3 (ADR 0016) plus the ``outer`` group for 29CM men's outerwear.

v4 keeps every v3 rule for ``top`` and ``bottom`` and adds:
  - group ``outer``: its own Type list (one per 29CM small category; coats and padded jackets share a Type and
    differ by Length), a body-length Length scale and Weight item rules
  - Fabric: Leather, Fur  ·  Texture: Suede, Quilted, Shearling, Melton, Ripstop, Tweed
  - Silhouette stays bottom-only; outer does not use it
  - the v3 Type merges are scoped by group: Zip hoodie -> Hoodie applies to top only, so outer keeps Zip hoodie

Outer products are filled by ``outer_pi`` with rules only (no model call). Each slot keeps v2's
``values`` / ``status`` (confirmed | derived) / ``method`` / ``evidence``; ordinal axes add ``score``.
Color, Tone, Fit, Pattern, Detail, Style and Price use the v2/v3 functions unchanged.

    python3 scripts/build_lumi_pi_v4.py --schema        # print the v4 schema as JSON
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

VERSION = "lumi-pi-v4"
GROUPS = ("top", "bottom", "outer")

# ---- Type --------------------------------------------------------------------------
# One Type per 29CM 남성의류 > 아우터 small category (2026-11-24). 코트·패딩 share a Type; Length separates them.
# 기타 아우터 has no Type from metadata and is left for the second (model) pass.
OUTER_SUBCATEGORY_TYPE: dict[str, str | None] = {
    "야상": "Field jacket", "블루종": "Blouson", "바시티": "Varsity jacket", "데님 재킷": "Denim jacket",
    "퍼 재킷": "Fur jacket", "트레이닝 재킷": "Track jacket", "점퍼": "Jumper", "바람막이": "Windbreaker",
    "아노락": "Anorak", "플리스": "Fleece jacket", "무스탕": "Shearling jacket", "트렌치/맥코트": "Trench coat",
    "나일론/코치 재킷": "Coach jacket", "후드 집업": "Zip hoodie", "베스트": "Vest", "레더 재킷": "Leather jacket",
    "블레이저": "Blazer", "숏코트": "Coat", "하프코트": "Coat", "롱코트": "Coat",
    "경량패딩": "Padded jacket", "숏패딩": "Padded jacket", "롱패딩": "Padded jacket", "기타 아우터": None,
}
OUTER_TYPES = list(dict.fromkeys(t for t in OUTER_SUBCATEGORY_TYPE.values() if t))
TOP_TYPES = [t for t in v2.SCHEMA["Type"] if t in v2.TOPS and t not in v3.TYPE_MERGE]
BOTTOM_TYPES = [t for t in v2.SCHEMA["Type"] if t not in v2.TOPS and t not in v3.TYPE_MERGE]
TYPE_VALUES = {"top": TOP_TYPES, "bottom": BOTTOM_TYPES, "outer": OUTER_TYPES}
# v3 merged these everywhere; v4 scopes them to the group they came from.
TYPE_MERGE = {"top": {"Knit vest": "Sleeveless", "Zip hoodie": "Hoodie"},
              "bottom": {"Cargo pants": "Trousers"},
              "outer": {}}

# ---- Length (outer: body length) -----------------------------------------------------
LENGTH_SCALE = {**v3.LENGTH_SCALE, "outer": {"Cropped": 1.0, "Short": 2.0, "Hip": 3.0, "Half": 4.0, "Long": 5.0}}
OUTER_LENGTH_BY_SUBCATEGORY = {"숏코트": "Short", "숏패딩": "Short", "하프코트": "Half", "롱코트": "Long", "롱패딩": "Long"}
OUTER_LENGTH_RULES = [
    ("Cropped", v2._rx("cropped", "crop", "크롭")),
    ("Short", re.compile(r"\bshort\b(?![\s-]*sleeve)|숏(?!\s*슬리브)", re.I)),
    # 하프집업·half zip is a closure, not a length
    ("Half", re.compile(r"\bhalf[\s-](?:coat|length)\b|\bmid-length\b|하프(?!\s*(?:집업|지퍼|zip))", re.I)),
    ("Long", re.compile(r"\blong(?:line|\s+(?:coat|padding|parka|length))\b|\bmaxi\b|롱(?!\s*슬리브)|맥시", re.I)),
]
# Middle-size 총길이 (cm) -> label. Upper bounds; at or above the last bound is Long.
# These bounds are an assumption to tune from the collected distribution (ADR 0017).
OUTER_LENGTH_CM = [(55.0, "Cropped"), (68.0, "Short"), (80.0, "Hip"), (95.0, "Half")]
OUTER_LENGTH_BY_TYPE = {
    "Blouson": "Short", "Varsity jacket": "Short", "Jumper": "Short", "Track jacket": "Short",
    "Coach jacket": "Short", "Windbreaker": "Short", "Anorak": "Short", "Fleece jacket": "Short",
    "Zip hoodie": "Short", "Vest": "Short", "Padded jacket": "Short",
    "Denim jacket": "Hip", "Leather jacket": "Hip", "Blazer": "Hip", "Field jacket": "Hip",
    "Shearling jacket": "Hip", "Fur jacket": "Hip", "Trench coat": "Long", "Coat": "Half",
}
TOTAL_LENGTH_ROW = re.compile(r"^(?:총\s*길이|총장|총\s*기장|기장|length)$", re.I)

# ---- Weight (outer) -----------------------------------------------------------------
OUTER_WEIGHT_RULES = [
    ("Light", re.compile(v3.WEIGHT_RULES[0][1].pattern + "|" + v2._rx(
        "packable", "mesh", "경량", "라이트웨이트", "메쉬", "메시").pattern, re.I)),
    ("Heavy", re.compile(v3.WEIGHT_RULES[1][1].pattern + "|" + v2._rx(
        "down jacket", "down filled", "down-filled", "duck down", "goose down", "덕다운", "구스다운", "웰론",
        "충전재", "패딩", "헤비", "기모").pattern, re.I)),
    v3.WEIGHT_RULES[2],
]
OUTER_WEIGHT_BY_TYPE = {
    "Shearling jacket": "Heavy", "Fur jacket": "Heavy", "Coat": "Heavy", "Padded jacket": "Heavy",
    "Blouson": "Mid", "Field jacket": "Mid", "Denim jacket": "Mid", "Blazer": "Mid", "Varsity jacket": "Mid",
    "Leather jacket": "Mid", "Fleece jacket": "Mid", "Zip hoodie": "Mid", "Jumper": "Mid", "Trench coat": "Mid",
    "Windbreaker": "Light", "Anorak": "Light", "Coach jacket": "Light", "Track jacket": "Light", "Vest": "Light",
}
OUTER_WEIGHT_BY_SUBCATEGORY = {"경량패딩": "Mid"}  # before the Type rule: 경량패딩 shares Padded jacket with 숏·롱패딩

# ---- Fabric · Texture additions ------------------------------------------------------
FABRIC_ADDED = ["Leather", "Fur"]
TEXTURE_ADDED = ["Suede", "Quilted", "Shearling", "Melton", "Ripstop", "Tweed"]
OUTER_FABRIC_RULES = [
    ("Leather", v2._rx("leather", "lambskin", "cowhide", "레더", "가죽", "램스킨", "카우하이드")),
    # "퍼" alone also hits 퍼플·슈퍼, so Korean fur words need a qualifier
    ("Fur", re.compile(r"\b(?:faux\s+)?fur\b|페이크\s?퍼|에코\s?퍼|폭스\s?퍼|래빗\s?퍼|밍크|"
                       r"퍼\s?(?:자켓|재킷|트리밍|후드|카라|칼라)", re.I)),
]
OUTER_TEXTURE_RULES = [
    ("Suede", v2._rx("suede", "스웨이드")),
    ("Quilted", v2._rx("quilted", "quilting", "퀼팅", "퀼티드", "누빔")),
    ("Shearling", v2._rx("shearling", "mouton", "무스탕", "시어링", "양털")),
    ("Melton", v2._rx("melton", "멜톤")),
    ("Ripstop", v2._rx("ripstop", "rip-stop", "립스탑", "립스톱")),
    ("Tweed", v2._rx("tweed", "트위드")),
]
OUTER_SUBCATEGORY_MATERIAL = {"레더 재킷": ("Fabric", "Leather"), "퍼 재킷": ("Fabric", "Fur"),
                              "무스탕": ("Texture", "Shearling"), "플리스": ("Texture", "Fleece"),
                              "데님 재킷": ("Texture", "Denim")}

# ---- schema ---------------------------------------------------------------------------
SCHEMA: dict[str, dict[str, Any]] = copy.deepcopy(v3.SCHEMA)
SCHEMA["Type"].update(values=[t for g in GROUPS for t in TYPE_VALUES[g]], values_by_group=TYPE_VALUES,
                      merge_by_group=TYPE_MERGE)
SCHEMA["Length"].update(scale=LENGTH_SCALE,
                        values_by_group={"top": list(LENGTH_SCALE["top"]) + ["Cropped"],
                                         "bottom": list(LENGTH_SCALE["bottom"]),
                                         "outer": list(LENGTH_SCALE["outer"])})
SCHEMA["Length"]["values"] = list(dict.fromkeys(SCHEMA["Length"]["values"] + list(LENGTH_SCALE["outer"])))
SCHEMA["Fabric"]["values"] = SCHEMA["Fabric"]["values"] + FABRIC_ADDED
SCHEMA["Texture"]["values"] = SCHEMA["Texture"]["values"] + TEXTURE_ADDED
SCHEMA["Silhouette"]["groups"] = ["bottom"]  # unchanged from v3; listed so outer's absence is explicit
AXES = tuple(a for a in SCHEMA if a != "Price")
META = dict(copy.deepcopy(v3.META), groups=list(GROUPS), unused_by_group={"top": ["Silhouette"], "outer": ["Silhouette"]},
            outer_length_cm=OUTER_LENGTH_CM)


# ---- outer rules ----------------------------------------------------------------------


def _one(rules: list[tuple[str, re.Pattern[str]]], text: str) -> tuple[str | None, list[str]]:
    """The single rule value found in text, or None when nothing or more than one value matches."""
    values, quotes = v2.match(rules, text)
    return (values[0], quotes) if len(values) == 1 else (None, quotes)


def outer_type(subcategory: str) -> dict[str, Any] | None:
    value = OUTER_SUBCATEGORY_TYPE.get(subcategory.strip())
    return v2.slot([value], "confirmed", "subcategory", [subcategory]) if value else None


def total_length_cm(size_text: str) -> float | None:
    """Middle-size 총길이 from a tab-separated 실측표 (header 치수항목·S·M·L…). M when listed, else the middle column."""
    rows = [[c.strip() for c in line.split("\t")] for line in (size_text or "").splitlines() if "\t" in line]
    header = next((r for r in rows if r and re.match(r"^(?:치수\s*항목|사이즈|size)$", r[0], re.I)), None)
    for row in rows:
        if not row or not TOTAL_LENGTH_ROW.match(row[0]):
            continue
        cells = row[1:]
        numbers = [float(c) for c in cells if re.fullmatch(r"\d+(?:\.\d+)?", c)]
        if not numbers:
            return None
        if header and "M" in [h.upper() for h in header[1:]] and len(header) - 1 == len(cells):
            cell = cells[[h.upper() for h in header[1:]].index("M")]
            if re.fullmatch(r"\d+(?:\.\d+)?", cell):
                return float(cell)
        return numbers[(len(numbers) - 1) // 2]
    return None


def length_from_cm(cm: float) -> str:
    for bound, label in OUTER_LENGTH_CM:
        if cm < bound:
            return label
    return "Long"


def outer_length(subcategory: str, text: str, size_text: str, type_value: str | None) -> dict[str, Any] | None:
    """Subcategory > name/seller keyword > middle-size 총길이 > Type rule. The first step that decides wins."""
    scale = LENGTH_SCALE["outer"]

    def out(value: str, status: str, method: str, evidence: list[str]) -> dict[str, Any]:
        return dict(v2.slot([value], status, method, evidence), score=scale[value], scale="outer")
    if subcategory.strip() in OUTER_LENGTH_BY_SUBCATEGORY:
        return out(OUTER_LENGTH_BY_SUBCATEGORY[subcategory.strip()], "confirmed", "subcategory", [subcategory])
    value, quotes = _one(OUTER_LENGTH_RULES, text)
    if value:
        return out(value, "confirmed", "keyword", quotes)
    cm = total_length_cm(size_text)
    if cm is not None:
        return out(length_from_cm(cm), "confirmed", "total_length_cm", [f"총길이 {cm:g}cm"])
    if type_value in OUTER_LENGTH_BY_TYPE:
        return out(OUTER_LENGTH_BY_TYPE[type_value], "derived", "type_rule", [type_value])
    return None


def outer_weight(pi: dict[str, Any], text: str, subcategory: str) -> dict[str, Any] | None:
    """GSM > thickness/fill keyword > material rule > subcategory/Type rule (v3 order, outer rules)."""
    def out(value: str, status: str, method: str, evidence: list[str]) -> dict[str, Any]:
        return dict(v2.slot([value], status, method, evidence), score=v3.WEIGHT_SCALE[value])
    found = v3.GSM.search(text or "")
    if found:
        grams = int(found.group(1))
        return out("Light" if grams < 200 else "Heavy" if grams >= 320 else "Mid", "confirmed", "gsm", [found.group(0)])
    value, quotes = _one(OUTER_WEIGHT_RULES, text or "")
    if value:
        return out(value, "confirmed", "keyword", quotes)

    def has(axis: str, *wanted: str) -> bool:
        return any(v in (pi.get(axis) or {}).get("values", []) for v in wanted)
    type_value = (pi.get("Type") or {}).get("values", [None])[0]
    if has("Texture", "Shearling", "Melton") or has("Fabric", "Fur"):
        return out("Heavy", "derived", "material_rule",
                   (pi.get("Texture") or {}).get("values", []) + (pi.get("Fabric") or {}).get("values", []))
    if type_value == "Coat" and has("Fabric", "Wool", "Cashmere"):
        return out("Heavy", "derived", "type_fabric_rule", [type_value] + pi["Fabric"]["values"])
    if has("Texture", "Ripstop"):
        return out("Light", "derived", "material_rule", pi["Texture"]["values"])
    if subcategory.strip() in OUTER_WEIGHT_BY_SUBCATEGORY:
        return out(OUTER_WEIGHT_BY_SUBCATEGORY[subcategory.strip()], "derived", "subcategory_rule", [subcategory])
    if type_value in OUTER_WEIGHT_BY_TYPE:
        return out(OUTER_WEIGHT_BY_TYPE[type_value], "derived", "type_rule", [type_value])
    return None


def outer_materials(text: str, subcategory: str) -> dict[str, dict[str, Any]]:
    """Fabric and Texture from seller keywords (confirmed), else the subcategory (derived)."""
    out: dict[str, dict[str, Any]] = {}
    for axis, rules in (("Fabric", v2.FABRIC_RULES + OUTER_FABRIC_RULES),
                        ("Texture", v2.TEXTURE_RULES + OUTER_TEXTURE_RULES)):
        values, quotes = v2.match(rules, text or "")
        merge = v3.VALUE_MERGE.get(axis, {})
        values = list(dict.fromkeys(merge.get(v, v) for v in values if merge.get(v, v) in SCHEMA[axis]["values"]))
        if values:
            out[axis] = v2.slot(values, "confirmed", "keyword", quotes)
    derived = OUTER_SUBCATEGORY_MATERIAL.get(subcategory.strip())
    if derived and derived[0] not in out:
        out[derived[0]] = v2.slot([derived[1]], "derived", "subcategory", [subcategory])
    return out


def outer_pi(subcategory: str, title: str, seller_text: str = "", size_text: str = "") -> dict[str, Any]:
    """Rule-based Type, Length, Weight, Fabric and Texture for one outer product (first-priority fill)."""
    text = f"{title}. {seller_text}"
    pi: dict[str, Any] = {}
    type_slot = outer_type(subcategory)
    if type_slot:
        pi["Type"] = type_slot
    pi.update(outer_materials(text, subcategory))
    length = outer_length(subcategory, text, size_text, (type_slot or {}).get("values", [None])[0])
    if length:
        pi["Length"] = length
    weight = outer_weight(pi, text, subcategory)
    if weight:
        pi["Weight"] = weight
    return pi


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--schema", action="store_true", help="print the v4 schema as JSON")
    args = parser.parse_args()
    if args.schema:
        print(json.dumps({"version": VERSION, "groups": list(GROUPS), "schema": SCHEMA, "meta": META,
                          "outer_subcategory_type": OUTER_SUBCATEGORY_TYPE}, ensure_ascii=False, indent=1))
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
