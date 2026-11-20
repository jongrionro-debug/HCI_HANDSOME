#!/usr/bin/env python3
"""Fill the LUMI PI v2 schema (ADR 0014) for 29CM + Cole Buxton + Wax London without image models.

Order of evidence, cheapest first:
  1. structured fields (Shopify product_type / colour option / title colour, 29CM normalized values)
  2. fixed derivation rules (Tone from colour, typical sleeve length from garment type)
  3. keyword rules over seller text (title, description, 29CM product table)
  4. 29CM DeepSeek text that already exists (re-used, never re-called) -> inferred
Text-model and image-model fills (fill_pi_v2_text.py, fill_pi_v2_image.py) are merged here from their caches.

Every axis keeps ``values``, ``status`` (confirmed | derived | inferred), ``method`` and ``evidence``.
Only the best available tier is kept per axis. Products without a first image are skipped.

    python3 scripts/build_lumi_pi_v2.py --data data
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_29cm_registry import resolve as resolve_29cm  # noqa: E402

VERSION = "lumi-pi-v2"
AXES = ("Type", "Color", "Tone", "Pattern", "Fit", "Silhouette", "Length", "Texture", "Fabric", "Detail", "Style")

SCHEMA: dict[str, list[str]] = {
    "Type": ["T-shirt", "Long-sleeve T-shirt", "Polo", "Shirt", "Overshirt", "Blouse", "Sweater", "Cardigan",
             "Knit vest", "Sleeveless", "Sweatshirt", "Hoodie", "Zip hoodie",
             "Trousers", "Jeans", "Sweatpants", "Cargo pants", "Shorts", "Skirt", "Leggings"],
    "Color": ["Black", "White", "Ecru", "Grey", "Charcoal", "Navy", "Blue", "Light blue", "Brown", "Beige", "Khaki",
              "Green", "Red", "Pink", "Purple", "Yellow", "Orange", "Multi"],
    "Tone": ["Dark", "Medium", "Light"],
    "Pattern": ["Solid", "Stripe", "Check", "Graphic", "Logo", "Floral", "Jacquard", "Other"],
    "Fit": ["Slim", "Regular", "Relaxed", "Oversized"],
    "Silhouette": ["Straight", "Tapered", "Wide", "Flare", "Boxy"],
    "Length": ["Short sleeve", "Long sleeve", "Sleeveless", "Cropped", "Shorts", "Full"],
    "Texture": ["Jersey", "Knit", "Ribbed", "Fleece", "Denim", "Corduroy", "Twill", "Seersucker", "Waffle", "Boucle"],
    "Fabric": ["Cotton", "Wool", "Cashmere", "Linen", "Polyester", "Nylon", "Viscose", "Elastane", "Acrylic", "Silk"],
    "Detail": ["Pockets", "Zip", "Buttons", "Collar", "Hood", "Drawcord", "Elastic waist", "Pleats", "Embroidery",
               "Patch", "Washed", "Distressed", "Slit"],
    "Style": ["Vintage", "Sporty", "Workwear", "Tailored", "Classic", "Preppy", "Street"],
}
TOPS = set(SCHEMA["Type"][:13])

# ---- keyword rules: (value, regex). English word boundaries; Korean plain substrings. ----
def _rx(*words: str) -> re.Pattern[str]:
    parts = [re.escape(w) if re.match(r"[가-힣]", w) else r"\b" + re.escape(w) + r"\b" for w in words]
    return re.compile("|".join(parts), re.I)


COLOR_RULES = [
    ("Light blue", _rx("light blue", "pale blue", "sky blue", "baby blue", "powder blue", "스카이블루", "연청")),
    ("Black", _rx("black", "블랙", "검정")), ("White", _rx("white", "화이트")),
    ("Ecru", _rx("ecru", "off white", "off-white", "cream", "ivory", "natural", "아이보리", "크림")),
    ("Charcoal", _rx("charcoal", "차콜")), ("Grey", _rx("grey", "gray", "marl", "heather", "그레이", "멜란지")),
    ("Navy", _rx("navy", "네이비")), ("Blue", _rx("blue", "cobalt", "indigo", "denim blue", "블루", "청")),
    ("Brown", _rx("brown", "chocolate", "tobacco", "coffee", "mocha", "브라운")),
    ("Beige", _rx("beige", "tan", "sand", "stone", "taupe", "camel", "oatmeal", "oat", "베이지")),
    ("Khaki", _rx("khaki", "olive", "카키")),
    ("Green", _rx("green", "sage", "mint", "forest", "그린")),
    ("Red", _rx("red", "burgundy", "merlot", "wine", "maroon", "레드", "버건디")),
    ("Pink", _rx("pink", "rose", "핑크")), ("Purple", _rx("purple", "lilac", "plum", "lavender", "퍼플")),
    ("Yellow", _rx("yellow", "butter", "mustard", "lemon", "옐로우")),
    ("Orange", _rx("orange", "rust", "terracotta", "오렌지")), ("Multi", _rx("multi", "멀티")),
]
PATTERN_RULES = [
    ("Stripe", _rx("stripe", "striped", "stripes", "pinstripe", "스트라이프")),
    ("Check", _rx("check", "checked", "checks", "plaid", "gingham", "tartan", "체크")),
    ("Floral", _rx("floral", "flower", "flowers", "플라워")),
    ("Jacquard", _rx("jacquard", "geometric", "houndstooth", "herringbone", "자카드", "헤링본")),
    ("Graphic", _rx("graphic", "artwork", "printed", "print", "프린트", "그래픽")),
    ("Logo", _rx("logo print", "printed logo", "logo graphic", "large logo", "chest logo", "로고 프린트")),
]
FIT_RULES = [
    ("Oversized", _rx("oversized", "oversize", "over fit", "오버핏", "오버 핏", "오버사이즈")),
    ("Relaxed", _rx("relaxed", "loose", "baggy", "easy fit", "루즈", "릴랙스", "세미오버")),
    ("Regular", _rx("regular fit", "regular", "classic fit", "standard fit", "레귤러")),
    ("Slim", _rx("slim", "fitted", "skinny", "슬림")),
]
SILHOUETTE_RULES = [
    ("Straight", _rx("straight", "스트레이트")), ("Tapered", _rx("tapered", "taper", "테이퍼드")),
    ("Wide", _rx("wide", "wide-leg", "wide leg", "와이드")), ("Flare", _rx("flare", "flared", "bootcut", "boot cut", "부츠컷", "플레어")),
    ("Boxy", _rx("boxy", "박시")),
]
LENGTH_RULES = [
    ("Short sleeve", _rx("short sleeve", "short sleeves", "short-sleeve", "short-sleeved", "short sleeved", "반소매", "반팔")),
    ("Long sleeve", _rx("long sleeve", "long sleeves", "long-sleeve", "long-sleeved", "long sleeved", "긴소매", "긴팔")),
    ("Sleeveless", _rx("sleeveless", "tank", "슬리브리스", "민소매", "나시")),
    ("Cropped", _rx("cropped", "crop", "ankle length", "ankle-length", "크롭", "앵클", "9부")),
]
TEXTURE_RULES = [
    ("Corduroy", _rx("corduroy", "cord", "코듀로이", "골덴")), ("Seersucker", _rx("seersucker", "시어서커")),
    ("Waffle", _rx("waffle", "와플")), ("Boucle", _rx("boucle", "bouclé", "mohair", "부클", "모헤어")),
    ("Fleece", _rx("fleece", "loopback", "brushed back", "french terry", "terry", "기모", "플리스")),
    ("Denim", _rx("denim", "데님")), ("Twill", _rx("twill", "트윌")),
    ("Ribbed", re.compile(r"\bribbed\b(?!\s+(?:cuffs?|hems?|trims?|collars?|necks?|necklines?|waist(?:band)?|edges?|details?))|\brib knit\b|골지", re.I)), ("Jersey", _rx("jersey", "저지")),
    ("Knit", _rx("knit", "knitted", "knitwear", "니트")),
]
FABRIC_RULES = [
    ("Cashmere", _rx("cashmere", "캐시미어")), ("Wool", re.compile(r"\b(?:wool|merino|lambswool|alpaca)\b|(?<![가-힣])울(?=\s*\d|\s*%|\s*혼방)", re.I)),
    ("Linen", _rx("linen", "린넨")), ("Cotton", _rx("cotton", "코튼")), ("Silk", _rx("silk", "실크")),
    ("Polyester", _rx("polyester", "폴리에스터", "폴리에스테르")), ("Nylon", _rx("nylon", "polyamide", "나일론")),
    ("Viscose", _rx("viscose", "rayon", "modal", "lyocell", "tencel", "레이온", "모달", "리오셀", "텐셀")),
    ("Elastane", _rx("elastane", "spandex", "polyurethane", "폴리우레탄", "스판")), ("Acrylic", _rx("acrylic", "아크릴")),
]
DETAIL_RULES = [
    ("Pockets", _rx("pocket", "pockets", "포켓", "주머니")), ("Zip", _rx("zip", "zipper", "zip-up", "zipped", "지퍼", "집업")),
    ("Buttons", _rx("button", "buttons", "buttoned", "버튼", "단추")), ("Collar", re.compile(r"(?<!ribbed )(?<!rib )\bcollar(?:ed)?\b|카라|칼라", re.I)),
    ("Hood", _rx("hood", "hooded", "hoodie", "후드")), ("Drawcord", _rx("drawcord", "drawstring", "스트링")),
    ("Elastic waist", _rx("elasticated", "elastic waist", "elasticated waist", "밴딩")),
    ("Pleats", _rx("pleat", "pleats", "pleated", "핀턱", "플리츠")),
    ("Embroidery", _rx("embroidered", "embroidery", "자수")), ("Patch", _rx("patch", "patches", "appliqué", "applique", "패치")),
    ("Washed", _rx("washed", "garment dyed", "garment-dyed", "vintage wash", "faded", "pigment", "워싱", "피그먼트")),
    ("Distressed", _rx("distressed", "destroyed", "ripped", "디스트로이드", "데미지")), ("Slit", _rx("slit", "split hem", "트임", "슬릿")),
]
STYLE_RULES = [
    ("Vintage", _rx("vintage", "retro", "90s", "heritage", "throwback", "빈티지", "레트로")),
    ("Sporty", _rx("sportswear", "sporty", "varsity", "athletic", "athletics", "gym", "track", "스포티", "트레이닝")),
    ("Workwear", _rx("workwear", "utility", "military", "cargo", "carpenter", "워크웨어", "밀리터리")),
    ("Tailored", _rx("tailored", "tailoring", "smart", "suiting", "formal", "테일러드", "포멀")),
    ("Classic", _rx("essential", "essentials", "everyday", "staple", "basic", "베이직", "데일리")),
    ("Preppy", _rx("preppy", "rugby", "collegiate", "프레피")), ("Street", _rx("streetwear", "street", "스트릿")),
]
KEYWORD_RULES = {"Pattern": PATTERN_RULES, "Fit": FIT_RULES, "Silhouette": SILHOUETTE_RULES, "Length": LENGTH_RULES,
                 "Texture": TEXTURE_RULES, "Fabric": FABRIC_RULES, "Detail": DETAIL_RULES, "Style": STYLE_RULES}

DARK, LIGHT = {"Black", "Charcoal", "Navy"}, {"White", "Ecru", "Light blue", "Beige", "Pink", "Yellow"}
DARK_MOD, LIGHT_MOD = _rx("dark", "deep", "washed black", "다크"), _rx("pale", "light", "faded", "soft", "라이트", "연그레이", "연베이지", "연핑크", "연블루")


def clean(text: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def match(rules: list[tuple[str, re.Pattern[str]]], text: str) -> tuple[list[str], list[str]]:
    values, quotes = [], []
    for value, pattern in rules:
        found = pattern.search(text)
        if found and value not in values:
            values.append(value)
            quotes.append(found.group(0))
    return values, quotes


def slot(values: list[str], status: str, method: str, evidence: list[str]) -> dict[str, Any]:
    return {"values": values, "status": status, "method": method, "evidence": evidence[:5]}


# ---- Type -------------------------------------------------------------------------
SHOPIFY_TYPE = {
    "T-Shirts": "T-shirt", "Long Sleeve T-Shirts": "Long-sleeve T-shirt", "Hoodie": "Hoodie", "Knit Hoodie": "Hoodie",
    "Zip Hoodie": "Zip hoodie", "Sweatshirt": "Sweatshirt", "Knit Top": "Sweater", "Shirt": "Shirt",
    "Sweatpants": "Sweatpants", "Track Pants": "Sweatpants", "Track pants": "Sweatpants", "Knit Pants": "Sweatpants",
    "Denim Jeans": "Jeans", "Trousers": "Trousers", "Cargo Pants": "Cargo pants", "Shorts": "Shorts",
    "Denim Shorts": "Shorts", "Knitwear": "Sweater", "Overshirts": "Overshirt", "Overshirt": "Overshirt",
    "Short Sleeve Shirts": "Shirt", "Long Sleeve Shirts": "Shirt", "Sweats": "Sweatshirt", "Polos": "Polo",
    "Vests": "Sleeveless", "Suiting": "Trousers",
}
TITLE_TYPE = [("Cardigan", _rx("cardigan")), ("Polo", _rx("polo")), ("Knit vest", _rx("tank top", "knit vest", "sweater vest")),
              ("Zip hoodie", _rx("zip hood", "zip-up hood", "zip hoodie")), ("Hoodie", _rx("hoodie", "hooded")),
              ("Jeans", _rx("jeans", "jean")), ("Cargo pants", _rx("cargo")), ("Long-sleeve T-shirt", _rx("long sleeve t-shirt", "long sleeve tee", "ls t-shirt"))]
KR_TYPE = {
    "코튼 팬츠": "Trousers", "슬랙스": "Trousers", "와이드 팬츠": "Trousers", "스트레이트 팬츠": "Trousers", "슬림 팬츠": "Trousers",
    "부츠컷 팬츠": "Trousers", "데님 팬츠": "Jeans", "트레이닝 팬츠": "Sweatpants", "쇼트 팬츠": "Shorts", "레깅스": "Leggings",
    "미디 스커트": "Skirt", "롱 스커트": "Skirt", "미니 스커트": "Skirt", "데님 스커트": "Skirt",
    "크루넥 니트": "Sweater", "브이넥 니트": "Sweater", "터틀넥 니트": "Sweater", "집업 니트": "Sweater", "캐시미어 니트": "Sweater",
    "후드 니트": "Hoodie", "폴로 니트": "Polo", "카디건": "Cardigan", "반소매 티셔츠": "T-shirt", "긴소매 티셔츠": "Long-sleeve T-shirt",
    "플리스": "Sweatshirt", "아노락": "Overshirt", "반소매 셔츠": "Shirt", "긴소매 셔츠": "Shirt", "셔츠": "Shirt",
    "스웨트셔츠": "Sweatshirt", "스웨트 집업": "Zip hoodie", "후디": "Hoodie", "피케·카라 티셔츠": "Polo", "슬리브리스": "Sleeveless",
    "블라우스": "Blouse",
}
KR_GARMENT_TYPE = {"Pants": "Trousers", "Skirt": "Skirt", "T-shirt": "T-shirt", "Shirt": "Shirt", "Blouse": "Blouse",
                   "Knit/Sweater": "Sweater", "Sweatshirt": "Sweatshirt", "Hoodie": "Hoodie", "Polo": "Polo", "Sleeveless": "Sleeveless"}
KR_SIL = {"와이드 팬츠": "Wide", "스트레이트 팬츠": "Straight", "부츠컷 팬츠": "Flare"}
KR_LEN = {"반소매 티셔츠": "Short sleeve", "긴소매 티셔츠": "Long sleeve", "반소매 셔츠": "Short sleeve", "긴소매 셔츠": "Long sleeve",
          "쇼트 팬츠": "Shorts", "슬리브리스": "Sleeveless"}
KR_FIT = {"오버": "Oversized", "세미오버": "Relaxed", "루즈·릴랙스": "Relaxed", "레귤러": "Regular", "슬림": "Slim"}
KR_FIT_SIL = {"와이드": "Wide", "스트레이트": "Straight", "부츠컷·플레어": "Flare"}
KR_FIT_LEN = {"크롭": "Cropped"}
KR_FABRIC = {"캐시미어": "Cashmere", "울": "Wool", "면": "Cotton", "폴리에스터": "Polyester", "나일론": "Nylon", "폴리우레탄": "Elastane",
             "레이온": "Viscose", "리오셀": "Viscose", "모달": "Viscose", "아세테이트": "Viscose", "아크릴": "Acrylic", "린넨": "Linen", "실크": "Silk"}
KR_DETAIL = {"지퍼·집업": ("Detail", "Zip"), "하프집업": ("Detail", "Zip"), "밴딩": ("Detail", "Elastic waist"), "스트링": ("Detail", "Drawcord"),
             "턱·핀턱": ("Detail", "Pleats"), "플리츠·주름": ("Detail", "Pleats"), "포켓": ("Detail", "Pockets"), "버튼": ("Detail", "Buttons"),
             "슬릿·트임": ("Detail", "Slit"), "워싱": ("Detail", "Washed"), "카라": ("Detail", "Collar"), "후드": ("Detail", "Hood"),
             "로고·자수": ("Detail", "Embroidery"), "리브·골지": ("Texture", "Ribbed"), "기모": ("Texture", "Fleece"),
             "코듀로이": ("Texture", "Corduroy"), "스트라이프": ("Pattern", "Stripe"), "체크·패턴": ("Pattern", "Check")}
KR_COLOR = {"스카이블루": "Light blue", "네이비": "Navy", "차콜": "Charcoal", "블랙": "Black", "화이트": "White", "아이보리": "Ecru",
            "베이지": "Beige", "브라운": "Brown", "카키": "Khaki", "그린": "Green", "블루": "Blue", "그레이": "Grey", "레드": "Red",
            "핑크": "Pink", "퍼플": "Purple", "옐로우": "Yellow", "멀티": "Multi"}
TYPICAL_LENGTH = {"T-shirt": "Short sleeve", "Polo": "Short sleeve", "Long-sleeve T-shirt": "Long sleeve", "Sweater": "Long sleeve",
                  "Cardigan": "Long sleeve", "Sweatshirt": "Long sleeve", "Hoodie": "Long sleeve", "Zip hoodie": "Long sleeve",
                  "Overshirt": "Long sleeve", "Sleeveless": "Sleeveless", "Knit vest": "Sleeveless", "Shorts": "Shorts",
                  "Trousers": "Full", "Jeans": "Full", "Sweatpants": "Full", "Cargo pants": "Full", "Leggings": "Full"}


def tone_of(colors: list[str], colour_text: str) -> list[str]:
    tones = []
    for color in colors:
        if color == "Multi":
            continue
        tone = "Dark" if color in DARK else "Light" if color in LIGHT else "Medium"
        if DARK_MOD.search(colour_text) and tone != "Dark":
            tone = "Dark"
        elif LIGHT_MOD.search(colour_text) and tone == "Medium":
            tone = "Light"
        if tone not in tones:
            tones.append(tone)
    return tones


def fill_common(pi: dict[str, Any], type_value: str | None, seller: str, model_text: str = "") -> None:
    """Steps 2-4 shared by every source: derived Tone/Length/Pattern, keyword rules, re-used model text."""
    def pick(axis: str, rules: list[tuple[str, re.Pattern[str]]], text: str) -> tuple[list[str], list[str]]:
        values, quotes = match(rules, text)
        if axis == "Silhouette":  # leg shapes only describe bottoms; tops can only be Boxy
            keep = [i for i, v in enumerate(values) if (v == "Boxy") == (type_value in TOPS)]
            values, quotes = [values[i] for i in keep], [quotes[i] for i in keep]
        if axis == "Fit" and len(values) > 1:  # prefer an explicit "<x> fit" phrase
            explicit = [v for v, q in zip(values, quotes) if re.search(re.escape(q) + r"\s*fit", text, re.I)]
            values, quotes = (explicit, explicit) if explicit else (values, quotes)
        return values, quotes

    for axis, rules in KEYWORD_RULES.items():
        if axis in pi:
            continue
        values, quotes = pick(axis, rules, seller)
        if values:
            pi[axis] = slot(values, "derived" if axis == "Style" else "confirmed", "keyword", quotes)
        elif model_text:
            values, quotes = pick(axis, rules, model_text)
            if values:
                pi[axis] = slot(values, "inferred", "model_text_reuse", quotes)
    if "Length" not in pi and type_value in TYPICAL_LENGTH:
        pi["Length"] = slot([TYPICAL_LENGTH[type_value]], "derived", "type_rule", [type_value])
    if "Pattern" not in pi and "Color" in pi and len(pi["Color"]["values"]) == 1 and pi["Color"]["values"] != ["Multi"]:
        pi["Pattern"] = slot(["Solid"], "derived", "single_colour_no_pattern_word", pi["Color"]["evidence"])
    if "Texture" not in pi and type_value in ("Sweater", "Cardigan", "Knit vest"):
        pi["Texture"] = slot(["Knit"], "derived", "type_rule", [type_value])
    if "Texture" not in pi and type_value == "Jeans":
        pi["Texture"] = slot(["Denim"], "derived", "type_rule", [type_value])


def shopify_records(data: Path, source: str) -> list[dict[str, Any]]:
    products = {str(p["id"]): p for p in json.loads((data / "raw" / source / "catalog.json").read_text(encoding="utf-8"))}
    kept = json.loads((data / "raw" / source / "first_images.json").read_text(encoding="utf-8"))["kept"]
    out = []
    for item in kept:
        product = products[item["product_id"]]
        title, body = product["title"], clean(product.get("body_html"))
        pi: dict[str, Any] = {}
        type_value = SHOPIFY_TYPE.get(product["product_type"])
        title_type, _ = match(TITLE_TYPE, title)
        if title_type and not (type_value in ("Shorts",) and title_type[0] in ("Jeans", "Cargo pants")):
            type_value = title_type[0]
        if type_value:
            pi["Type"] = slot([type_value], "confirmed", "product_type+title", [product["product_type"], title])
        colour_text = item.get("colour_option") or (title.split(" - ", 1)[1] if " - " in title else title)
        colors, quotes = match(COLOR_RULES, colour_text)
        if "Light blue" in colors and "Blue" in colors:
            colors.remove("Blue")
        if colors:
            pi["Color"] = slot(colors, "confirmed", "colour_option" if item.get("colour_option") else "title", [colour_text])
            pi["Tone"] = slot(tone_of(colors, colour_text), "derived", "colour_rule", [colour_text])
        if product["product_type"] in ("Short Sleeve Shirts", "Long Sleeve Shirts"):
            pi["Length"] = slot(["Short sleeve" if product["product_type"].startswith("Short") else "Long sleeve"],
                                "confirmed", "product_type", [product["product_type"]])
        fill_common(pi, type_value, f"{title}. {body}")
        variant = (product.get("variants") or [{}])[0]
        out.append({"id": f"{source}-{item['product_id']}", "source": source, "source_product_id": item["product_id"],
                    "group": item["group"], "gender": "men", "title": title, "brand": product.get("vendor"),
                    "price": {"amount": variant.get("price"), "currency": "GBP"}, "image": item["image"],
                    "url_handle": product.get("handle"), "pi": pi})
    return out


def records_29cm(data: Path) -> list[dict[str, Any]]:
    out = []
    # split("\n"), not splitlines(): 29CM seller text can contain U+2028 / U+0085, which splitlines() breaks on
    for line in (data / "raw" / "29cm" / "lumi-catalog-v1.jsonl").read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        record = json.loads(line)
        image = data / "images" / "29cm" / f"{record['product_id']}.jpg"
        if not image.exists():
            continue
        md = record["raw_metadata"]
        resolved = resolve_29cm(record)
        pi: dict[str, Any] = {}

        def put(axis: str, value: str, origin: str, quote: str) -> None:
            status = "confirmed" if origin == "raw" else "inferred"
            method = "29cm_normalized" if origin == "raw" else "29cm_model_reuse"
            current = pi.get(axis)
            if current and current["status"] == "confirmed" and status == "inferred":
                return
            if not current or (current["status"] == "inferred" and status == "confirmed"):
                pi[axis] = slot([], status, method, [])
            if value not in pi[axis]["values"]:
                pi[axis]["values"].append(value)
                pi[axis]["evidence"] = (pi[axis]["evidence"] + [quote])[:5]

        kr_type = (resolved.get("Type") or {}).get("values", [None])[0]
        type_value = KR_TYPE.get(kr_type) or KR_GARMENT_TYPE.get(record["garment_type"])
        if type_value:
            put("Type", type_value, resolved.get("Type", {}).get("origin", "raw"), kr_type or record["garment_type"])
        if kr_type in KR_SIL:
            put("Silhouette", KR_SIL[kr_type], resolved["Type"]["origin"], kr_type)
        if kr_type in KR_LEN:
            put("Length", KR_LEN[kr_type], resolved["Type"]["origin"], kr_type)
        for axis, table in (("Color", KR_COLOR), ("Fabric", KR_FABRIC)):
            for value in (resolved.get(axis) or {}).get("values", []):
                if value in table:
                    put(axis, table[value], resolved[axis]["origin"], resolved[axis]["quote"])
        for value in (resolved.get("Fit") or {}).get("values", []):
            for table, axis in ((KR_FIT, "Fit"), (KR_FIT_SIL, "Silhouette"), (KR_FIT_LEN, "Length")):
                if value in table and not (axis == "Silhouette" and type_value in TOPS):
                    put(axis, table[value], resolved["Fit"]["origin"], resolved["Fit"]["quote"])
        for value in (resolved.get("Detail") or {}).get("values", []):
            if value in KR_DETAIL:
                axis, english = KR_DETAIL[value]
                if value == "밴딩" and type_value in TOPS:  # on tops 밴딩 means a ribbed hem band, not an elastic waist
                    continue
                put(axis, english, resolved["Detail"]["origin"], resolved["Detail"]["quote"])
        if "Color" in pi:
            pi["Tone"] = slot(tone_of(pi["Color"]["values"], " ".join(pi["Color"]["evidence"])), "derived", "colour_rule",
                              pi["Color"]["evidence"])
        seller = f"{record['title']}. {clean(record.get('description'))}. {md.get('product_info') or ''}"
        model_text = " ".join(f"{v.get('value') or ''} {v.get('evidence') or ''}"
                              for v in (md.get("pi_model_interpretation") or {}).values() if isinstance(v, dict))
        fill_common(pi, type_value, seller, model_text)
        out.append({"id": record["product_id"], "source": "29cm", "source_product_id": record["product_id"].removeprefix("29cm-"),
                    "group": "top" if type_value in TOPS else "bottom", "gender": md.get("gender"), "title": record["title"],
                    "brand": md.get("brand"), "price": {"amount": md.get("price_amount"), "currency": "KRW"},
                    "image": str(image.relative_to(data)), "url_handle": record["source"]["url"], "pi": pi})
    return out


TEXT_FILL_MIN_CONFIDENCE = 0.5  # pilot 2026-11-19: both clear errors were below 0.5


def apply_text_fills(records: list[dict[str, Any]], data: Path) -> int:
    """Step 5: axes still empty after the rules take text-model values from fill_pi_v2_text.py, as inferred."""
    fill_dir, applied = data / "raw" / "fills_text", 0
    if not fill_dir.is_dir():
        return 0
    for record in records:
        path = fill_dir / f"{record['id']}.json"
        if not path.exists():
            continue
        for axis, fill in json.loads(path.read_text(encoding="utf-8")).get("fills", {}).items():
            if (axis in record["pi"] or (axis == "Silhouette" and record["group"] == "top")
                    or fill["confidence"] < TEXT_FILL_MIN_CONFIDENCE):
                continue
            record["pi"][axis] = slot(fill["values"], "inferred", "text_model", [fill["evidence_quote"]])
            applied += 1
            if axis == "Color" and "Tone" not in record["pi"]:
                record["pi"]["Tone"] = slot(tone_of(fill["values"], fill["evidence_quote"]), "derived", "colour_rule",
                                            [fill["evidence_quote"]])
    return applied


def apply_image_fills(records: list[dict[str, Any]], data: Path) -> int:
    """Step 6: top axes still empty after text fills take image+text model values from fill_pi_v2_image.py, as inferred."""
    fill_dir, applied = data / "raw" / "fills_image", 0
    if not fill_dir.is_dir():
        return 0
    for record in records:
        path = fill_dir / f"{record['id']}.json"
        if record["group"] != "top" or not path.exists():
            continue
        for axis, fill in json.loads(path.read_text(encoding="utf-8")).get("fills", {}).items():
            if axis in record["pi"] or fill["confidence"] < TEXT_FILL_MIN_CONFIDENCE:
                continue
            record["pi"][axis] = slot(fill["values"], "inferred", "image_model", [fill["evidence"]])
            applied += 1
            tones = tone_of(fill["values"], "") if axis == "Color" else []
            if tones and "Tone" not in record["pi"]:
                record["pi"]["Tone"] = slot(tones, "derived", "colour_rule", [fill["evidence"]])
    return applied


def validate(records: list[dict[str, Any]]) -> None:
    for record in records:
        for axis, entry in record["pi"].items():
            bad = [v for v in entry["values"] if v not in SCHEMA[axis]]
            if bad:
                raise SystemExit(f"{record['id']} {axis}: values outside schema {bad}")


TOP_REGISTRY_VERSION = "lumi-pi-v2-top"
TOP_GARMENT = "Top"
LABEL_KO = {"Type": "종류", "Brand": "브랜드", "Color": "색상", "Tone": "색 톤", "Pattern": "패턴", "Fit": "핏(여유)",
            "Silhouette": "실루엣", "Length": "기장·소매", "Texture": "표면감", "Fabric": "소재", "Detail": "디테일",
            "Style": "스타일"}
SHOP_URL = {"colebuxton": "https://colebuxton.com/products/", "waxlondon": "https://waxlondon.com/products/"}


def export_top(records: list[dict[str, Any]], data: Path, registry_path: Path) -> dict[str, int]:
    """Tops only: runtime value dictionary (lumi-pi-v2-top) and a lumi-catalog-v1 import file.

    confirmed/derived axes go to ``raw_metadata.<axis>`` as canonical lists (the mapping reads them as
    exact metadata); inferred axes go to ``labels`` as model_interpretation quoting
    ``raw_metadata.pi_inferred.<axis>.evidence``. Images stay under ``data/images``; the import file
    refers to them relative to that root.
    """
    park = json.loads((ROOT / "output/feature-map/park-2025-feature-map.json").read_text(encoding="utf-8"))
    tops = [r for r in records if r["group"] == "top"]
    counts = {axis: Counter(v for r in tops if axis in r["pi"] for v in r["pi"][axis]["values"]) for axis in AXES}
    counts["Brand"] = Counter(r["brand"] for r in tops if r.get("brand"))
    order = ("Type", "Brand") + AXES[1:]
    pi = {}
    for axis in order:
        values = sorted(counts[axis]) if axis == "Brand" else [v for v in SCHEMA[axis] if counts[axis][v]]
        pi[axis] = {"label_ko": LABEL_KO[axis], "values": values, "reported_count": len(values),
                    "enumeration_complete": True, "distribution": {v: counts[axis][v] for v in values}}
    pi["Type"]["values_by_garment_type"] = {TOP_GARMENT: list(pi["Type"]["values"])}
    registry = {
        "name": "LUMI PI v2 tops (ADR 0014) + Park FEA taxonomy",
        "version": TOP_REGISTRY_VERSION, "status": "Generated", "runtime_implemented": True,
        "scope": "29CM·Cole Buxton·Wax London 상의만 담은 PI v2 실행 사전이다. 값 라벨은 영어다(ADR 0014).",
        "lumi_use": "PI 축은 ADR 0014의 11축(+Brand), FEA 30개 태그는 Park 사전을 그대로 쓴다. Price는 통화가 섞여 조건에서 뺀다.",
        "generated_by": "scripts/build_lumi_pi_v2.py --export-top",
        "axis_order": list(order),
        "product_information": pi,
        "consumer_needs_taxonomy": park["consumer_needs_taxonomy"],
        "garment_types": [{"value": TOP_GARMENT, "label_ko": "상의"}],
        "execution": {"supported_garment_types": [TOP_GARMENT], "accept_inferred_product_pi": True,
                      "price_currency": None, "price_boundary_inclusion": None},
        "counts": {"products": len(tops), "product_information_categories": len(pi),
                   "consumer_needs_attributes": park["counts"]["consumer_needs_attributes"],
                   "values": {a: len(pi[a]["values"]) for a in order}},
        "source_boundaries": [
            "confirmed는 구조화 필드·판매자 문구 키워드, derived는 고정 규칙, inferred는 DeepSeek 텍스트·이미지 해석이다.",
            "inferred 값은 상품 Map에서 status=inferred·model_interpretation으로 남는다. accept_inferred_product_pi=true는 실행 선택이며 검증 라벨이 아니다.",
            "Fabric은 사진으로 갱신하지 않는다(ADR 0013 결정 8).",
        ],
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = []
    for r in tops:
        raw_md: dict[str, Any] = {"group": r["group"], "gender": r["gender"], "brand_text": r.get("brand"),
                                  "price_text": r["price"]["amount"], "currency": r["price"]["currency"],
                                  "pi_inferred": {}}
        if r.get("brand"):
            raw_md["brand"] = r["brand"]
        labels = []
        for axis in AXES:
            entry = r["pi"].get(axis)
            if not entry:
                continue
            if entry["status"] in ("confirmed", "derived"):
                raw_md[axis.lower()] = entry["values"]
            else:
                evidence = " | ".join(e for e in entry["evidence"] if e)[:4000] or ", ".join(entry["values"])
                raw_md["pi_inferred"][axis] = {"values": entry["values"], "method": entry["method"], "evidence": evidence}
                labels.append({"observation": {"domain": "PI", "feature": axis, "values": entry["values"]},
                               "status": "inferred",
                               "provenance": [{"kind": "model_interpretation",
                                               "source_field": f"raw_metadata.pi_inferred.{axis}.evidence",
                                               "quote": evidence, "verifier": None, "evidence_ref": None,
                                               "verified_at": None}]})
        image = data / r["image"]
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        url = r["url_handle"] if r["source"] == "29cm" else SHOP_URL[r["source"]] + r["url_handle"]
        collected = datetime.fromtimestamp(image.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        lines.append(json.dumps({
            "format_version": "lumi-catalog-v1", "product_id": r["id"],
            "source": {"source_id": r["source"], "url": url, "collected_at": collected},
            "title": r["title"], "description": None, "garment_type": TOP_GARMENT, "raw_metadata": raw_md,
            "images": [{"image_id": f"{r['id']}-0", "kind": "local", "location": r["image"].removeprefix("images/"),
                        "source_revision": f"sha256:{digest}", "sha256": digest, "regions": []}],
            "labels": labels}, ensure_ascii=False))
    (data / "catalog" / f"{TOP_REGISTRY_VERSION}-import.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"tops": len(tops), "all_axes_filled": sum(all(a in r["pi"] for a in AXES if a != "Silhouette") for r in tops)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--export-top", action="store_true",
                        help="also write output/feature-map/lumi-pi-v2-top.json and data/catalog/lumi-pi-v2-top-import.jsonl")
    args = parser.parse_args()
    records = shopify_records(args.data, "colebuxton") + shopify_records(args.data, "waxlondon") + records_29cm(args.data)
    text_fills = apply_text_fills(records, args.data)
    image_fills = apply_image_fills(records, args.data)
    validate(records)
    out_dir = args.data / "catalog"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{VERSION}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    fill = {axis: {"filled": sum(axis in r["pi"] for r in records),
                   "by_status": dict(Counter(r["pi"][axis]["status"] for r in records if axis in r["pi"])),
                   "values": dict(Counter(v for r in records if axis in r["pi"] for v in r["pi"][axis]["values"]).most_common())}
            for axis in AXES}
    report = {"version": VERSION, "products": len(records), "by_source": dict(Counter(r["source"] for r in records)),
              "by_group": dict(Counter(r["group"] for r in records)), "all_axes_filled": sum(len(r["pi"]) == len(AXES) for r in records),
              "text_model_fills": text_fills, "image_model_fills": image_fills, "fill": fill, "schema": SCHEMA}
    (out_dir / f"{VERSION}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("products", "by_source", "by_group", "all_axes_filled", "text_model_fills", "image_model_fills")},
                     ensure_ascii=False))
    for axis in AXES:
        print(f"{axis:10s} {fill[axis]['filled']:4d}/{len(records)} {fill[axis]['by_status']}")
    if args.export_top:
        print(json.dumps(export_top(records, args.data, ROOT / "output/feature-map" / f"{TOP_REGISTRY_VERSION}.json")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
