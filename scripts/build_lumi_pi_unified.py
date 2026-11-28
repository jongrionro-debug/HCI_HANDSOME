#!/usr/bin/env python3
"""Unify every Drive catalog package into one LUMI PI map (lumi-pi-v5.1) and one image folder, without model calls.

Schema ``lumi-pi-v5.1`` = PI v5 (ADR 0019: v4 top/bottom/outer + skirt group) plus the value extensions of the
29CM women knit v4.3 / women outer v4.2 packages (Texture Smooth, Fuzzy, ...; Fabric Down, Silk, Alpaca, ...;
Detail Hook fastening, Reversible). Only 29CM products are kept.

Sources (``--drive``, default ``data/raw/drive``; the extracted Drive zips, names unchanged):
  1. women outer  lumi_29cm_women_outer_pi_v4/...v4.2...   (PI v4.2, kept as is)
  2. women knit   lumi_29cm_women_knit_pi_v4/...v4.3...    (PI v4.3, kept as is)
  3. men outer    men_outer_crawling_1000                  (PI v4 rule+model, P-number images mapped to 29CM ids)
  4. PI v3        lumi-pi-v3-catalog + lumi-first-images   (29CM only; skirts move to the v5 skirt group)
  5. raw only     29cm-men-top 2, json_knit+images_knit, skirt_pi+skirt_images
     -> v2/v3 rules for tops, v5 rules for skirts, palette colour; still-empty axes come from
        fill_pi_unified.py (DeepSeek image+text) via data/raw/fills_unified/<id>.json, merged here as inferred.
Earlier sources win on a duplicate product id; a v3 skirt is rebuilt as a skirt seeded with its v3 values.

Every applicable axis is present: ``values`` + ``status`` (confirmed | derived | inferred | unknown) + ``method`` +
``evidence``; ordinal axes add ``score``/``scale``; Color keeps ``colors`` (rgb, lab, share).
Axes a group does not use (top/outer Silhouette, skirt Fit) are left out.

    python3 scripts/build_lumi_pi_unified.py --data data             # writes data/catalog/lumi-pi-unified*.json[l]
    python3 scripts/build_lumi_pi_unified.py --data data --pending   # only count raw products still needing a model call
    python3 scripts/build_lumi_pi_unified.py --data data --export-runtime   # runtime dictionary + import file from the
        # existing lumi-pi-unified.jsonl (no rebuild): output/feature-map/lumi-pi-v5.1.json, data/catalog/lumi-pi-v5.1-import-NN.jsonl
"""
from __future__ import annotations

import argparse
import copy
import glob
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_lumi_pi_v2 as v2  # noqa: E402
import build_lumi_pi_v3 as v3  # noqa: E402
import build_lumi_pi_v5 as v5  # noqa: E402

VERSION = "lumi-pi-v5.1"
OUT_NAME = "lumi-pi-unified"
GROUPS = v5.GROUPS
FILL_MIN_CONFIDENCE = 0.7  # same bar as the women outer v4.2 / knit v4.3 strict fills

# ---- schema: v5 + v4.3 value extensions ------------------------------------------------
EXTRA_VALUES = {
    "Texture": ["Smooth", "Fuzzy", "Glossy", "Matte", "Crinkled", "Grained", "Mesh", "Herringbone", "Cable knit", "Open knit"],
    "Fabric": ["Down", "Silk", "Alpaca", "Mohair", "Angora"],
    "Detail": ["Hook fastening", "Reversible"],
}
SCHEMA: dict[str, dict[str, Any]] = copy.deepcopy(v5.SCHEMA)
for _axis, _values in EXTRA_VALUES.items():
    SCHEMA[_axis]["values"] = list(dict.fromkeys(SCHEMA[_axis]["values"] + _values))
SCHEMA["Type"]["values_by_group"]["outer"] = list(dict.fromkeys(
    SCHEMA["Type"]["values_by_group"]["outer"] + ["Nylon jacket", "Raincoat", "Robe", "Jacket"]))
SCHEMA["Type"]["values"] = list(dict.fromkeys(t for g in GROUPS for t in SCHEMA["Type"]["values_by_group"][g]))
AXES = tuple(a for a in SCHEMA if a != "Price")
UNUSED = {"top": {"Silhouette"}, "outer": {"Silhouette"}, "skirt": {"Fit"}, "bottom": set()}
LENGTH_SCALE = v5.LENGTH_SCALE
ORDINAL = {"Fit": v3.FIT_SCALE, "Weight": v3.WEIGHT_SCALE}


def applicable(group: str) -> list[str]:
    return [a for a in AXES if a not in UNUSED[group]]


def allowed(axis: str, group: str) -> list[str]:
    entry = SCHEMA[axis]
    if axis == "Length":
        return list(LENGTH_SCALE[group]) + (["Cropped"] if group == "top" else [])
    if "values_by_group" in entry and group in entry["values_by_group"]:
        return list(entry["values_by_group"][group])
    return list(entry.get("values", []))


# ---- slot helpers ------------------------------------------------------------------------
KEEP = ("score", "scale", "colors", "confidence", "needs_review", "seller_values", "absence_supported", "flag",
        "merged_from", "model", "evidence_type", "evidence_image")


def unknown() -> dict[str, Any]:
    return {"values": [], "status": "unknown", "method": None, "evidence": []}


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def norm_slot(raw: dict[str, Any]) -> dict[str, Any] | None:
    """v3 (values) / v4.x (values or label) slot -> unified slot. None for not_applicable."""
    if raw.get("status") == "not_applicable":
        return None
    values = as_list(raw.get("values")) or as_list(raw.get("label"))
    if not values and raw.get("colors"):  # v4.x Color keeps only the palette
        values = list(dict.fromkeys(c["label"] for c in raw["colors"] if c.get("label")))
    out = {"values": list(dict.fromkeys(v for v in values if isinstance(v, str))), "status": raw.get("status") or "inferred",
           "method": raw.get("method"), "evidence": [str(e) for e in as_list(raw.get("evidence"))][:5]}
    if not out["values"] and out["status"] != "unknown" and not raw.get("absence_supported"):
        out["status"] = "unknown"
    for key in KEEP:
        if raw.get(key) is not None:
            out[key] = raw[key]
    if raw.get("seller_labels") and "seller_values" not in out:
        out["seller_values"] = raw["seller_labels"]
    return out


def add_scores(pi: dict[str, Any], group: str) -> None:
    for axis, scale in ORDINAL.items():
        slot = pi.get(axis)
        if slot and slot["values"] and slot.get("score") is None:
            scores = [scale[v] for v in slot["values"] if v in scale]
            if scores:
                slot["score"] = v3.round_step(sum(scores) / len(scores)) if axis == "Fit" else scores[0]
    slot = pi.get("Length")
    if slot and slot["values"]:
        scores = [LENGTH_SCALE[group][v] for v in slot["values"] if v in LENGTH_SCALE[group]]
        if scores and slot.get("score") is None:
            slot["score"] = sum(scores) / len(scores)
        slot["scale"] = group
    if pi.get("Fit") and pi["Fit"]["values"]:
        pi["Fit"]["scale"] = group
    tone, color = pi.get("Tone"), pi.get("Color")
    if tone and tone.get("score") is None and color and color.get("colors"):
        tone["score"] = color["colors"][0]["lab"][0]


def finish(record: dict[str, Any], problems: list[str]) -> dict[str, Any]:
    """Keep schema values only, fill unknown axes, add scores. Out-of-schema values are dropped and reported."""
    group, pi = record["group"], record["pi"]
    for axis in list(pi):
        if axis not in applicable(group):
            del pi[axis]
            continue
        slot = pi[axis]
        ok = allowed(axis, group)
        bad = [v for v in slot["values"] if v not in ok]
        if bad:
            problems.append(f"{record['id']} {axis} {bad}")
            slot["values"] = [v for v in slot["values"] if v in ok]
            slot.setdefault("dropped_values", bad)
            if not slot["values"]:
                pi[axis] = dict(unknown(), dropped_values=bad)
        if axis == "Style":
            pi[axis]["values"] = pi[axis]["values"][:v3.STYLE_MAX]
    for axis in applicable(group):
        pi.setdefault(axis, unknown())
    add_scores(pi, group)
    record["pi"] = {a: pi[a] for a in applicable(group)}
    return record


def base_record(pid: str, group: str, gender: str | None, title: str, brand: str | None, price: dict[str, Any],
                image: Path, origin: str, origin_version: str) -> dict[str, Any]:
    return {"id": f"29cm-{pid}", "source": "29cm", "source_product_id": pid, "group": group, "gender": gender,
            "title": title, "brand": brand, "url": f"https://www.29cm.co.kr/products/{pid}",
            "price": v3.price_of(price), "pi_schema": VERSION, "origin": {"package": origin, "pi_version": origin_version},
            "image_source": str(image), "pi": {}}


# ---- labeled packages ------------------------------------------------------------------------

def load_parts(base: Path, prefix: str) -> list[dict[str, Any]]:
    out = []
    for path in sorted(base.glob(f"{prefix}-part*.json")):
        out += json.loads(path.read_text(encoding="utf-8"))["products"]
    return out


def v4x_records(base: Path, prefix: str, origin: str, version: str) -> list[dict[str, Any]]:
    out = []
    for p in load_parts(base, prefix):
        src, prod = p["source"], p["product"]
        price = p["pi"].get("Price") or {"amount": prod.get("price_krw"), "currency": "KRW"}
        rec = base_record(p["product_id"], src["group"], src.get("garment_gender") or src.get("listing_gender"),
                          prod["title"], prod.get("brand"), price, base / p["image"]["path"], origin, version)
        for axis, raw in p["pi"].items():
            if axis in AXES and isinstance(raw, dict):
                slot = norm_slot(raw)
                if slot is not None:
                    rec["pi"][axis] = slot
        out.append(rec)
    return out


def men_outer_records(base: Path) -> list[dict[str, Any]]:
    out = []
    for p in json.loads((base / "products.json").read_text(encoding="utf-8"))["products"]:
        pid = p["source_id"].removeprefix("29cm-")
        price = {"amount": p["price"].get("amount"), "currency": p["price"].get("currency", "KRW")}
        rec = base_record(pid, "outer", "men", p["name"], p.get("brand"), price, base / p["image"],
                          "men_outer_crawling_1000", "lumi-pi-v4")
        for axis, raw in p["pi"].items():
            if axis not in AXES:
                continue
            values = as_list(raw.get("value"))
            rule, model = raw.get("rule") or {}, raw.get("model") or {}
            if axis == "Color":
                colors = [dict(c, hex="#%02x%02x%02x" % tuple(c["rgb"])) for c in raw.get("palette") or []]
                slot = {"values": values, "colors": colors, "status": "derived", "method": "image_palette",
                        "evidence": [p["image"]], "seller_values": as_list(raw.get("seller"))}
            elif axis == "Tone":
                slot = {"values": values, "score": raw.get("L"), "status": "derived", "method": "lab_lightness", "evidence": []}
            elif raw.get("source") == "rule" and rule.get("values"):
                slot = {"values": values, "status": rule.get("status") or "derived", "method": rule.get("method"),
                        "evidence": [str(e) for e in as_list(rule.get("evidence"))]}
                if rule.get("score") is not None:
                    slot["score"] = float(rule["score"])
            elif values:
                slot = {"values": values, "status": "inferred", "method": "image_model",
                        "evidence": [str(e) for e in as_list(model.get("evidence"))]}
            else:
                slot = unknown()
            if raw.get("flag"):
                slot["flag"] = raw["flag"]
            rec["pi"][axis] = slot
        out.append(rec)
    return out


def v3_records(drive: Path) -> list[dict[str, Any]]:
    out = []
    images = drive / "lumi-first-images"
    for line in (drive / "lumi-pi-v3-catalog/catalog/lumi-pi-v3.jsonl").read_text(encoding="utf-8").split("\n"):
        if not line.strip():
            continue
        r = json.loads(line)
        if r["source"] != "29cm":
            continue
        rec = base_record(r["source_product_id"], r["group"], r.get("gender"), r["title"], r.get("brand"), r["price"],
                          images / r["image"], "lumi-pi-v3-catalog", "lumi-pi-v3")
        slots = {a: norm_slot(s) for a, s in r["pi"].items() if a in AXES}
        rec["pi"] = {a: s for a, s in slots.items() if s is not None}
        if r.get("merged"):
            rec["origin"]["v3_merged"] = r["merged"]
        out.append(rec)
    return out


# ---- raw-only products (rules) ----------------------------------------------------------------
TOP_TYPE = {"슬리브리스": "Sleeveless", "반소매 티셔츠": "T-shirt", "긴소매 티셔츠": "Long-sleeve T-shirt",
            "반소매 셔츠": "Shirt", "긴소매 셔츠": "Shirt", "피케/카라 티셔츠": "Polo", "후디": "Hoodie",
            "스웨트셔츠": "Sweatshirt"}
TOP_LENGTH = {"슬리브리스": "Sleeveless", "반소매 티셔츠": "Short sleeve", "반소매 셔츠": "Short sleeve",
              "긴소매 티셔츠": "Long sleeve", "긴소매 셔츠": "Long sleeve"}
KNIT_TYPE = {"크루넥": "Sweater", "터틀넥": "Sweater", "브이넥": "Sweater", "폴로셔츠": "Polo", "후드": "Hoodie"}
HOOD = v2._rx("hood", "hoodie", "hooded", "후드", "후디")
HALF_ZIP = v2._rx("half zip", "half-zip", "하프 집업", "하프집업", "반집업")
CARDIGAN = v2._rx("cardigan", "카디건", "가디건")
VEST = v2._rx("vest", "베스트", "조끼")
POLO = v2._rx("polo", "폴로", "카라")


def raw_type(kind: str, sub: str, title: str) -> tuple[str | None, str | None]:
    """(Type, merged_from). Ambiguous small categories are left for the model unless the title decides."""
    if kind == "top_m":
        if sub in TOP_TYPE:
            return TOP_TYPE[sub], None
        if sub == "집업" and HOOD.search(title):
            return "Hoodie", "Zip hoodie"
        return None, None
    if sub in KNIT_TYPE:
        return KNIT_TYPE[sub], None
    if sub == "집업":
        if HOOD.search(title):
            return "Hoodie", "Zip hoodie"
        return ("Sweater", None) if HALF_ZIP.search(title) else ("Cardigan", None)
    for rx, value in ((CARDIGAN, "Cardigan"), (VEST, "Sleeveless"), (HOOD, "Hoodie"), (POLO, "Polo")):
        if rx.search(title):
            return value, None
    return "Sweater", None


def first_image(base: Path, product: dict[str, Any], pid: str) -> Path | None:
    for image in product.get("images") or []:
        if image.get("local_path") and (base / image["local_path"]).exists():
            return base / image["local_path"]
    found = sorted(glob.glob(str(base / "images" / pid / "*"))) + sorted(glob.glob(str(base / "images" / f"{pid}.*")))
    return Path(found[0]) if found else None


def seller_text(p: dict[str, Any]) -> str:
    return f"{p['title']}. {v2.clean(p.get('description'))}. {p.get('product_info') or ''}"


def raw_products(drive: Path) -> list[tuple[str, Path, dict[str, Any]]]:
    """(kind, image base dir, product json) for the raw-only packages; the first one wins on duplicate ids."""
    seen: set[str] = set()
    out = []
    sets = [("top_m", drive / "29cm-men-top 2/29cm-men-top", drive / "29cm-men-top 2/29cm-men-top/products"),
            ("knit_m", drive / "images_knit", drive / "json_knit"),
            ("skirt", drive / "skirt_images", drive / "skirt_pi/products")]
    for kind, image_base, product_dir in sets:
        for path in sorted(product_dir.glob("*.json")):
            p = json.loads(path.read_text(encoding="utf-8"))
            if p["product_id"] in seen:
                continue
            seen.add(p["product_id"])
            if kind == "knit_m":  # json_knit says images/<id>.jpg; the files are in images_knit.zip/images_knit/
                p = dict(p, images=[dict(i, local_path=i["local_path"].replace("images/", "images_knit/", 1))
                                    for i in p.get("images") or [] if i.get("local_path")])
            out.append((kind, image_base, p))
    return out


def colour_slots(image: Path, group: str, seller_colour: str) -> dict[str, Any]:
    palette = v3.extract_palette(image, "bottom" if group == "skirt" else group, True, 3)
    if not palette:
        return {}
    seller = v2.match(v2.COLOR_RULES, seller_colour or "")[0]
    color = {"values": list(dict.fromkeys(c["label"] for c in palette)), "colors": palette, "status": "derived",
             "method": "image_palette", "evidence": [image.name], "seller_values": seller}
    lightness = palette[0]["lab"][0]
    tone = {"values": [v3.tone_label(lightness)], "score": lightness, "status": "derived", "method": "lab_lightness",
            "evidence": [palette[0]["hex"]]}
    return {"Color": color, "Tone": tone}


def top_rules(kind: str, p: dict[str, Any], image: Path) -> dict[str, Any]:
    sub, title, seller = p["discovered_from"]["small"], p["title"], seller_text(p)
    pi: dict[str, Any] = {}
    type_value, merged_from = raw_type(kind, sub, title)
    if type_value:
        pi["Type"] = v2.slot([type_value], "confirmed" if kind == "top_m" and not merged_from else "derived",
                             "subcategory" if kind == "top_m" else "knit_category_mapping", [sub, title])
        if merged_from:
            pi["Type"]["merged_from"] = merged_from
    if sub in TOP_LENGTH:
        pi["Length"] = v2.slot([TOP_LENGTH[sub]], "confirmed", "subcategory", [sub])
    v2.fill_common(pi, type_value, seller)
    pi.pop("Silhouette", None)
    if kind == "knit_m" and "Texture" not in pi:
        pi["Texture"] = v2.slot(["Knit"], "derived", "knitwear_category", [p["subcategory"]])
    if merged_from and "Zip" not in (pi.get("Detail") or {}).get("values", []):
        pi.setdefault("Detail", v2.slot([], "derived", "type_merge", [merged_from]))["values"].append("Zip")
    record = {"id": p["product_id"], "source": "29cm", "source_product_id": p["product_id"], "group": "top",
              "gender": p.get("gender"), "title": title, "brand": p.get("brand"), "image": image.name,
              "url_handle": p["url"], "price": {"amount": p["price"].get("amount"), "currency": "KRW"}, "pi": pi}
    converted = v3.convert(record, seller, None)["pi"]  # Weight, Style split, Fit/Length scores
    for axis in ("Color", "Tone"):
        converted.pop(axis, None)
    converted.update(colour_slots(image, "top", ((p.get("pi") or {}).get("Color") or {}).get("value") or ""))
    return converted


def size_text(p: dict[str, Any]) -> str:
    rows = " ".join(r.get("value") or "" for r in p.get("product_info_rows") or [] if r.get("name") == "치수")
    return f"{p.get('description') or ''}\n{rows}"


def skirt_rules(p: dict[str, Any], image: Path, seed: dict[str, Any] | None) -> dict[str, Any]:
    sub, title, seller = p["discovered_from"]["small"], p["title"], seller_text(p)
    pi = v5.skirt_pi(sub, title, seller, size_text(p))
    common: dict[str, Any] = {}
    v2.fill_common(common, "Skirt", seller)
    for axis in ("Pattern", "Texture", "Fabric", "Detail", "Style"):
        if axis not in pi and axis in common:
            pi[axis] = common[axis]
    style = v3.style_of(pi, seller)
    if style:
        pi["Style"] = style
    for axis, slot in (seed or {}).items():  # v3 values of the same product, where rules left a gap
        if axis not in pi and axis not in ("Length", "Silhouette", "Fit", "Color", "Tone") and slot["values"]:
            pi[axis] = dict(slot, method=f"{slot.get('method')}+v3_seed")
    pi.update(colour_slots(image, "skirt", ((p.get("pi") or {}).get("Color") or {}).get("value") or ""))
    if seed and "Color" not in pi:
        for axis in ("Color", "Tone"):
            if seed.get(axis):
                pi[axis] = seed[axis]
    return pi


def apply_fills(record: dict[str, Any], fills_dir: Path) -> int:
    path = fills_dir / f"{record['id']}.json"
    if not path.exists():
        return 0
    data, applied = json.loads(path.read_text(encoding="utf-8")), 0
    for axis, fill in data.get("fills", {}).items():
        current = record["pi"].get(axis)
        if (current and current["values"]) or fill["confidence"] < FILL_MIN_CONFIDENCE:
            continue
        record["pi"][axis] = {"values": fill["values"], "status": "inferred", "method": "image_model",
                              "evidence": [fill["evidence"]], "confidence": fill["confidence"], "model": data.get("model")}
        applied += 1
    return applied


# ---- build ------------------------------------------------------------------------------------

def collect(drive: Path, fills_dir: Path | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    problems: list[str] = []
    excluded: dict[str, list[str]] = {"no_image": [], "duplicate": []}
    by_id: dict[str, dict[str, Any]] = {}
    labeled = (v4x_records(drive / "lumi_29cm_women_outer_pi_v4/LUMI_29CM_women_outer_1000_PI_v4.2_Texture_20261126",
                           "women-outer-pi-v4.2", "lumi_29cm_women_outer_pi_v4", "lumi-pi-v4.2")
               + v4x_records(drive / "lumi_29cm_women_knit_pi_v4/LUMI_29CM_women_knit_1000_PI_v4.3_20261126",
                             "women-knit-pi-v4.3", "lumi_29cm_women_knit_pi_v4", "lumi-pi-v4.3")
               + men_outer_records(drive / "men_outer_crawling_1000/men_outer_crawling_1000"))
    v3_skirts: dict[str, dict[str, Any]] = {}
    for rec in labeled + v3_records(drive):
        if rec["id"] in by_id:
            excluded["duplicate"].append(f"{rec['id']} ({rec['origin']['package']})")
            continue
        if rec["origin"]["pi_version"] == "lumi-pi-v3" and (rec["pi"].get("Type") or {}).get("values") == ["Skirt"]:
            v3_skirts[rec["id"]] = rec
        by_id[rec["id"]] = rec
    raw_ids: set[str] = set()
    for kind, base, p in raw_products(drive):
        pid = f"29cm-{p['product_id']}"
        if pid in by_id and pid not in v3_skirts:
            excluded["duplicate"].append(f"{pid} (raw {kind})")
            continue
        image = first_image(base, p, p["product_id"])
        if image is None:
            excluded["no_image"].append(f"{pid} ({kind})")
            continue
        group = "skirt" if kind == "skirt" else "top"
        seed = v3_skirts.pop(pid, None)
        origin = {"top_m": "29cm-men-top 2", "knit_m": "json_knit+images_knit", "skirt": "skirt_pi+skirt_images"}[kind]
        rec = base_record(p["product_id"], group, p.get("gender"), p["title"], p.get("brand"),
                          {"amount": p["price"].get("amount"), "currency": p["price"].get("currency") or "KRW"},
                          image, origin, "raw-29cm-category-v1")
        if seed:
            rec["origin"]["v3_seed"] = True
        rec["pi"] = skirt_rules(p, image, seed["pi"] if seed else None) if group == "skirt" else top_rules(kind, p, image)
        rec["seller_text"] = seller_text(p)
        by_id[pid] = rec
        raw_ids.add(pid)
    for pid, rec in v3_skirts.items():  # v3 skirt with no raw record: keep its v3 values as a skirt
        rec["group"] = "skirt"
        rec["pi"] = {a: s for a, s in rec["pi"].items() if a not in ("Length", "Silhouette", "Fit")}
        rec["seller_text"] = rec["title"]
        raw_ids.add(pid)
    fills, records = 0, []
    for rec in by_id.values():
        if fills_dir is not None and rec["id"] in raw_ids:
            fills += apply_fills(rec, fills_dir)
        records.append(finish(rec, problems))
    meta = {"excluded": excluded, "schema_problems": problems, "model_fills_applied": fills, "raw_ids": sorted(raw_ids)}
    return records, meta


def pending(records: list[dict[str, Any]], raw_ids: set[str]) -> list[dict[str, Any]]:
    """Raw-only products with an empty applicable axis the model may fill (Color/Tone come from the palette)."""
    out = []
    for r in records:
        if r["id"] not in raw_ids:
            continue
        axes = [a for a in applicable(r["group"]) if not r["pi"][a]["values"] and a not in ("Color", "Tone")]
        if axes:
            out.append({"record": r, "axes": axes})
    return out


def write_outputs(records: list[dict[str, Any]], meta: dict[str, Any], data: Path, copy_images: bool) -> dict[str, Any]:
    image_dir = data / "images" / OUT_NAME
    image_dir.mkdir(parents=True, exist_ok=True)
    for r in records:
        src = Path(r.pop("image_source"))
        r.pop("seller_text", None)
        name = f"{r['id']}{src.suffix.lower()}"
        r["image"] = name
        if copy_images and not (image_dir / name).exists():
            shutil.copy2(src, image_dir / name)
    out_dir = data / "catalog"
    out_dir.mkdir(parents=True, exist_ok=True)
    records.sort(key=lambda r: (GROUPS.index(r["group"]), r["gender"] or "", r["id"]))
    (out_dir / f"{OUT_NAME}.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
                                               encoding="utf-8")
    schema = {"version": VERSION, "groups": list(GROUPS), "schema": SCHEMA,
              "meta": dict(v5.META, unused_by_group={g: sorted(u) for g, u in UNUSED.items()},
                           extra_values_from_v4_3=EXTRA_VALUES, fill_min_confidence=FILL_MIN_CONFIDENCE)}
    (out_dir / f"{OUT_NAME}-schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=1), encoding="utf-8")
    fill = {}
    for group in GROUPS:
        rows = [r for r in records if r["group"] == group]
        fill[group] = {a: {"filled": sum(bool(r["pi"][a]["values"]) for r in rows),
                           "by_status": dict(Counter(r["pi"][a]["status"] for r in rows))} for a in applicable(group)}
    report = {"version": VERSION, "products": len(records),
              "by_group_gender": dict(Counter(f"{r['group']}/{r['gender']}" for r in records)),
              "by_origin": dict(Counter(r["origin"]["package"] for r in records)),
              "model_fills_applied": meta["model_fills_applied"], "fill": fill,
              "excluded": {k: {"count": len(v), "ids": v} for k, v in meta["excluded"].items()},
              "dropped_out_of_schema": meta["schema_problems"], "image_dir": str(image_dir)}
    (out_dir / f"{OUT_NAME}-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return report


# ---- runtime export (graph engine) ----------------------------------------------------------
RUNTIME_GARMENTS = {"top": ("Top", "상의"), "bottom": ("Bottom", "하의"), "outer": ("Outer", "아우터"),
                    "skirt": ("Skirt", "스커트")}
RUNTIME_LABEL_KO = v2.LABEL_KO | {"Weight": "두께"}
RUNTIME_ORDER = ("Type", "Brand") + AXES[1:]
IMPORT_PART_BYTES = 12 * 1024 * 1024  # under the 16 MiB catalog-import limit
SHAPE_KEYS = ("kind", "fill", "condition", "scale", "step", "relative_step", "groups", "max_values", "label_thresholds")


def export_runtime(records: list[dict[str, Any]], data: Path, registry_path: Path) -> dict[str, Any]:
    """Runtime dictionary (lumi-pi-v5.1, four garment types) and a lumi-catalog-v1 import file.

    Same split as the v3 export: confirmed/derived labels go to raw_metadata.<axis>, inferred labels go to labels as
    model_interpretation. Ordinal scores, colour Lab and price_krw stay under raw_metadata.pi_v3 (the key name the
    graph engine reads since ADR 0016). Values a group never uses are listed per garment type
    (values_by_garment_type), and Length keeps one score table per group in value_shape.scale (keys = group names,
    the same names as the product's Length.scale).
    """
    park = json.loads((v2.ROOT / "output/feature-map/park-2025-feature-map.json").read_text(encoding="utf-8"))
    counts = {axis: Counter(v for r in records if axis in r["pi"] for v in r["pi"][axis]["values"]) for axis in AXES}
    counts["Brand"] = Counter(r["brand"] for r in records if r.get("brand"))
    by_group = {axis: {g: Counter(v for r in records if r["group"] == g and axis in r["pi"] for v in r["pi"][axis]["values"])
                       for g in GROUPS} for axis in AXES}
    pi: dict[str, Any] = {}
    for axis in RUNTIME_ORDER:
        if axis == "Brand":
            values = sorted(counts["Brand"])
        else:
            schema_values = list(dict.fromkeys(SCHEMA[axis].get("values", []) + [v for g in GROUPS for v in allowed(axis, g)]))
            values = [v for v in schema_values if counts[axis][v]]
        pi[axis] = {"label_ko": RUNTIME_LABEL_KO[axis], "values": values, "reported_count": len(values),
                    "enumeration_complete": True, "distribution": {v: counts[axis][v] for v in values}}
        if axis == "Brand":
            continue
        pi[axis]["value_shape"] = {k: SCHEMA[axis][k] for k in SHAPE_KEYS if k in SCHEMA[axis]}
        if axis == "Length":
            pi[axis]["value_shape"]["scale"] = {g: dict(LENGTH_SCALE[g]) for g in GROUPS}
        per_group = {RUNTIME_GARMENTS[g][0]: [v for v in values if by_group[axis][g][v]] for g in GROUPS if axis in applicable(g)}
        if axis == "Type" or any(set(vs) != set(values) for vs in per_group.values()) or len(per_group) < len(GROUPS):
            pi[axis]["values_by_garment_type"] = per_group
    registry = {
        "name": "LUMI PI v5.1 unified 29CM catalog (tops, bottoms, outer, skirts) + Park FEA taxonomy",
        "version": VERSION, "status": "Generated", "runtime_implemented": True,
        "scope": "29CM 상의·하의·아우터·스커트 통합 카탈로그(lumi-pi-unified)의 실행 사전이다. 값 라벨은 영어다(ADR 0014·0016·0018·0019).",
        "lumi_use": "PI 축은 ADR 0016의 12축(+Brand), 품목군별 값은 values_by_garment_type, FEA 30개 태그는 Park 사전을 쓴다. "
                    "실행 비교는 라벨 일치이며 점수·Lab·price_krw는 상품 raw_metadata.pi_v3에 둔다.",
        "generated_by": "scripts/build_lumi_pi_unified.py --export-runtime",
        "axis_order": list(RUNTIME_ORDER),
        "product_information": pi,
        "consumer_needs_taxonomy": park["consumer_needs_taxonomy"],
        "garment_types": [{"value": garment, "label_ko": label} for garment, label in RUNTIME_GARMENTS.values()],
        "execution": {"supported_garment_types": [garment for garment, _ in RUNTIME_GARMENTS.values()],
                      "accept_inferred_product_pi": True, "price_currency": "KRW", "price_boundary_inclusion": None},
        "counts": {"products": len(records), "product_information_categories": len(pi),
                   "consumer_needs_attributes": park["counts"]["consumer_needs_attributes"],
                   "values": {a: len(pi[a]["values"]) for a in RUNTIME_ORDER},
                   "by_garment_type": {RUNTIME_GARMENTS[g][0]: sum(r["group"] == g for r in records) for g in GROUPS}},
        "source_boundaries": [
            "confirmed는 구조화 필드·판매자 문구 키워드, derived는 고정 규칙·이미지 색 추출, inferred는 DeepSeek 텍스트·이미지 해석이다.",
            "inferred 값은 상품 Map에서 status=inferred·model_interpretation으로 남는다. accept_inferred_product_pi=true는 실행 선택이며 검증 라벨이 아니다.",
            "Silhouette은 하의·스커트, Fit은 스커트를 뺀 품목군에서만 쓴다. Fabric은 사진으로 갱신하지 않는다(ADR 0013 결정 8).",
            "모델 값은 사람이 검수하지 않았다.",
        ],
    }
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    image_dir = data / "images" / OUT_NAME
    lines = []
    for r in records:
        shapes = {axis: {k: entry[k] for k in ("score", "scale", "colors") if k in entry}
                  for axis, entry in r["pi"].items() if any(k in entry for k in ("score", "colors"))}
        raw_md: dict[str, Any] = {"group": r["group"], "gender": r["gender"], "brand_text": r.get("brand"),
                                  "price_text": r["price"]["amount"], "currency": r["price"]["currency"],
                                  "pi_schema": r.get("pi_schema"), "pi_inferred": {},
                                  "pi_v3": {"price_krw": r["price"].get("price_krw"), "axes": shapes}}
        if r.get("brand"):
            raw_md["brand"] = r["brand"]
        labels = []
        for axis in AXES:
            entry = r["pi"].get(axis)
            if not entry or not entry["values"]:
                continue
            entry = entry | {"values": list(dict.fromkeys(entry["values"]))}  # two palette clusters can share a name
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
        image = image_dir / r["image"]
        digest = hashlib.sha256(image.read_bytes()).hexdigest()
        collected = datetime.fromtimestamp(image.stat().st_mtime, timezone.utc).isoformat(timespec="seconds")
        lines.append(json.dumps({
            "format_version": "lumi-catalog-v1", "product_id": r["id"],
            "source": {"source_id": r["source"], "url": r["url"], "collected_at": collected},
            "title": r["title"], "description": None, "garment_type": RUNTIME_GARMENTS[r["group"]][0],
            "raw_metadata": raw_md,
            "images": [{"image_id": f"{r['id']}-0", "kind": "local", "location": f"{OUT_NAME}/{r['image']}",
                        "source_revision": f"sha256:{digest}", "sha256": digest, "regions": []}],
            "labels": labels}, ensure_ascii=False))
    # catalog-import reads at most 16 MiB per file and upserts by product ID, so parts can be imported one by one.
    for old in (data / "catalog").glob(f"{VERSION}-import*.jsonl"):
        old.unlink()
    parts: list[list[str]] = [[]]
    size = 0
    for line in lines:
        if parts[-1] and size + len(line.encode("utf-8")) + 1 > IMPORT_PART_BYTES:
            parts.append([])
            size = 0
        parts[-1].append(line)
        size += len(line.encode("utf-8")) + 1
    files = []
    for number, part in enumerate(parts, 1):
        path = data / "catalog" / f"{VERSION}-import-{number:02}.jsonl"
        path.write_text("\n".join(part) + "\n", encoding="utf-8")
        files.append(path.name)
    return {"products": len(records), "by_garment": dict(Counter(RUNTIME_GARMENTS[r["group"]][0] for r in records)),
            "import_files": files}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--drive", type=Path, default=None, help="extracted Drive packages (default <data>/raw/drive)")
    parser.add_argument("--pending", action="store_true", help="print how many raw products still need a model call")
    parser.add_argument("--no-copy", action="store_true", help="do not copy images (paths are still written)")
    parser.add_argument("--export-runtime", action="store_true",
                        help="read the existing lumi-pi-unified.jsonl and write output/feature-map/lumi-pi-v5.1.json "
                             "and data/catalog/lumi-pi-v5.1-import-NN.jsonl parts (no rebuild, no model calls)")
    args = parser.parse_args()
    if args.export_runtime:
        source = args.data / "catalog" / f"{OUT_NAME}.jsonl"
        records = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
        result = export_runtime(records, args.data, v2.ROOT / "output" / "feature-map" / f"{VERSION}.json")
        print(json.dumps(result, ensure_ascii=False))
        return 0
    drive = args.drive or args.data / "raw" / "drive"
    records, meta = collect(drive, args.data / "raw" / "fills_unified")
    if args.pending:
        todo = pending(records, set(meta["raw_ids"]))
        print(json.dumps({"raw": len(meta["raw_ids"]), "pending": len(todo),
                          "axes": dict(Counter(a for t in todo for a in t["axes"]))}, ensure_ascii=False))
        return 0
    report = write_outputs(records, meta, args.data, not args.no_copy)
    print(json.dumps({k: report[k] for k in ("products", "by_group_gender", "by_origin", "model_fills_applied")},
                     ensure_ascii=False))
    print("excluded", {k: v["count"] for k, v in report["excluded"].items()},
          "dropped values", len(report["dropped_out_of_schema"]))
    for group, axes in report["fill"].items():
        print(group, {a: v["filled"] for a, v in axes.items()})
    return 0


if __name__ == "__main__":
    sys.exit(main())
