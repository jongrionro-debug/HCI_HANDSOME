#!/usr/bin/env python3
"""Download the first product image of top/bottom garments from Shopify catalog JSON (ADR 0014).

Input is a crawled ``<source>_catalog.json`` (Shopify ``products.json`` items). Only the
first image of each top/bottom garment is fetched, resized by the Shopify CDN ``width``
parameter. Existing files are skipped, so the command can be re-run. A manifest lists
every kept product with its garment group, image file and the colour of the variant that
the first image belongs to.

    python3 scripts/fetch_shopify_first_images.py --catalog data/raw/waxlondon/catalog.json \
        --source waxlondon --out data
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

USER_AGENT = "LUMI-research-catalog/0.1"
WIDTH = 1200
RETRIES = 4

# Shopify product_type -> group. Anything not listed is not a top/bottom garment and is skipped.
TYPE_GROUPS = {
    "colebuxton": {
        "T-Shirts": "top", "Long Sleeve T-Shirts": "top", "Hoodie": "top", "Zip Hoodie": "top",
        "Sweatshirt": "top", "Knit Top": "top", "Knit Hoodie": "top", "Shirt": "top",
        "Sweatpants": "bottom", "Denim Jeans": "bottom", "Trousers": "bottom", "Cargo Pants": "bottom",
        "Track Pants": "bottom", "Track pants": "bottom", "Knit Pants": "bottom", "Shorts": "bottom",
        "Denim Shorts": "bottom",
    },
    "waxlondon": {
        "T-Shirts": "top", "Knitwear": "top", "Overshirts": "top", "Overshirt": "top",
        "Short Sleeve Shirts": "top", "Long Sleeve Shirts": "top", "Sweats": "top", "Polos": "top",
        "Vests": "top", "Trousers": "bottom", "Shorts": "bottom",
        # Suiting mixes blazers and trousers: keep trousers only (see title rule below).
        "Suiting": "bottom",
    },
}


def group_of(source: str, product: dict) -> str | None:
    group = TYPE_GROUPS[source].get(product.get("product_type") or "")
    if group and product.get("product_type") == "Suiting" and "trouser" not in product["title"].lower():
        return None
    return group


def first_image_colour(product: dict) -> str | None:
    """Colour option of the variant that owns the first image, else of the first variant."""
    names = [o["name"].lower() for o in product.get("options", [])]
    if "color" not in names and "colour" not in names:
        return None
    index = names.index("color") if "color" in names else names.index("colour")
    image = product["images"][0]
    variants = product.get("variants") or []
    owner = next((v for v in variants if v["id"] in (image.get("variant_ids") or [])), variants[0] if variants else None)
    return owner.get(f"option{index + 1}") if owner else None


def resized(src: str) -> str:
    parts = urllib.parse.urlsplit(src)
    query = dict(urllib.parse.parse_qsl(parts.query))
    query["width"] = str(WIDTH)
    return urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query)))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--catalog", required=True, type=Path)
    parser.add_argument("--source", required=True, choices=sorted(TYPE_GROUPS))
    parser.add_argument("--out", required=True, type=Path, help="data root; images go to <out>/images/<source>/")
    parser.add_argument("--delay", type=float, default=0.3)
    args = parser.parse_args()

    products = json.loads(args.catalog.read_text(encoding="utf-8"))
    image_dir = args.out / "images" / args.source
    image_dir.mkdir(parents=True, exist_ok=True)
    manifest, failures, fetched = [], [], 0
    for product in products:
        group = group_of(args.source, product)
        if not group or not product.get("images"):
            continue
        target = image_dir / f"{product['id']}.jpg"
        if not target.exists():
            request = urllib.request.Request(resized(product["images"][0]["src"]), headers={"User-Agent": USER_AGENT})
            error = None
            for attempt in range(RETRIES):
                try:
                    with urllib.request.urlopen(request, timeout=30) as response:
                        body = response.read()  # IncompleteRead raises here; nothing partial is written
                    target.write_bytes(body)
                    fetched += 1
                    error = None
                    break
                except Exception as failure:  # retry, then report at the end
                    error = failure
                    time.sleep(args.delay * (attempt + 2))
            time.sleep(args.delay)
            if error is not None:
                failures.append({"product_id": product["id"], "error": f"{type(error).__name__}: {error}"})
                continue
        manifest.append({"source": args.source, "product_id": str(product["id"]), "title": product["title"],
                         "product_type": product["product_type"], "group": group,
                         "colour_option": first_image_colour(product),
                         "image": str(target.relative_to(args.out)), "image_src": product["images"][0]["src"]})
    (args.out / "raw" / args.source).mkdir(parents=True, exist_ok=True)
    (args.out / "raw" / args.source / "first_images.json").write_text(
        json.dumps({"kept": manifest, "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"source": args.source, "kept": len(manifest), "fetched_now": fetched, "failures": len(failures),
                      "top": sum(m["group"] == "top" for m in manifest),
                      "bottom": sum(m["group"] == "bottom" for m in manifest)}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
