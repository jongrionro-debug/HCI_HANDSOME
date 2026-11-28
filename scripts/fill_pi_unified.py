#!/usr/bin/env python3
"""Fill still-empty PI axes of the raw-only products of the unified map with DeepSeek over the first image + seller text.

Reads the rule-only records of build_lumi_pi_unified.py (men tops, men knit, skirts; Color/Tone already come from the
palette) and asks, once per product, only for the empty applicable axes with that group's allowed values
(schema lumi-pi-v5.1). Visual axes need a short visual evidence note; Fabric needs a verbatim quote of the text.
Results are cached in data/raw/fills_unified/<id>.json, so re-runs skip finished products. Run
build_lumi_pi_unified.py afterwards: values with confidence >= 0.7 are merged as inferred (method image_model).

The API key is read from OPENCODE_API_KEY and is never printed or written.

    python3 scripts/fill_pi_unified.py --data data --limit 20
    python3 scripts/fill_pi_unified.py --data data --workers 6
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
from stylemate_memory.errors import StyleMateError  # noqa: E402
from stylemate_memory.llm import OPENCODE_MAX_OUTPUT_TOKENS, OPENCODE_TIMEOUT  # noqa: E402
from stylemate_memory.settings import DEEPSEEK_DEFAULT_MODEL  # noqa: E402
import build_lumi_pi_unified as unified  # noqa: E402
from fill_pi_v2_image import INSTRUCTIONS, ImageChatGateway, image_uri  # noqa: E402
from fill_pi_v2_text import ENDPOINT, GUIDE, squash  # noqa: E402

FILL_VERSION = "lumi-pi-v5.1-image-fill-v1"
TEXT_ONLY = ("Fabric",)
MAX_TEXT = 6000
COMMON_GUIDE = {
    **GUIDE,
    "Texture": GUIDE["Texture"] + ". Use a specific weave/knit value when it is visible; otherwise a coarse visible "
               "surface value (Smooth, Fuzzy, Glossy, Matte). Do not judge the whole garment from a trim or lining",
    "Fabric": "fibre content stated in the text; evidence must be a verbatim quote of the text",
    "Weight": "fabric weight/thickness visible or stated: Light = thin, sheer or summer weight; Mid = ordinary; "
              "Heavy = thick, padded or winter weight",
    "Style": "overall style/mood of the garment, at most 2 values",
}
GUIDES = {
    "top": {**COMMON_GUIDE,
            "Type": "garment type of this top (a zip-up with a hood is Hoodie; a knit zip-up without a hood is Cardigan)",
            "Length": "sleeve length: Sleeveless, Short sleeve or Long sleeve; add Cropped only when the body hem ends "
                      "clearly above the waist"},
    "skirt": {**COMMON_GUIDE,
              "Type": "Skort only for skirt-shaped shorts/culottes, otherwise Skirt",
              "Length": "hem length: Mini = clearly above the knee; Knee = around the knee; Midi = between knee and "
                        "ankle (mid-calf); Long = reaches the ankle or floor",
              "Silhouette": "skirt shape: Pencil = narrow, hugs hips and legs to the hem; H-line = straight from hip to "
                            "hem; A-line = widens gradually from the waist; Flare = widens strongly, circle/swing skirt; "
                            "Mermaid = fitted, then flares below the knee",
              "Detail": "construction/design details visible or stated (pockets, zip, buttons, pleats, slit, wrap, "
                        "tiers, ruffles, washing, distressing)"},
}


def output_schema(axes: list[str], group: str) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": axes, "properties": {
        axis: {"type": "object", "additionalProperties": False, "required": ["values", "evidence", "confidence"],
               "properties": {"values": {"type": "array", "items": {"type": "string", "enum": unified.allowed(axis, group)}},
                              "evidence": {"type": ["string", "null"]}, "confidence": {"type": "number"}}}
        for axis in axes}}


def validate(result: Any, axes: list[str], text: str, group: str) -> tuple[dict[str, Any], dict[str, str]]:
    accepted, rejected = {}, {}
    if not isinstance(result, dict):
        return {}, {a: "not_an_object" for a in axes}
    for axis in axes:
        item = result.get(axis)
        if not isinstance(item, dict):
            rejected[axis] = "missing"
            continue
        values = list(dict.fromkeys(v for v in item.get("values") or [] if isinstance(v, str)))
        evidence, confidence = item.get("evidence"), item.get("confidence")
        if axis == "Style":
            values = values[:2]
        if not values:
            rejected[axis] = "no_value"
        elif any(v not in unified.allowed(axis, group) for v in values):
            rejected[axis] = "outside_schema"
        elif axis in ("Weight", "Type") and len(values) > 1:
            rejected[axis] = "more_than_one"
        elif not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 240:
            rejected[axis] = "missing_evidence"
        elif axis in TEXT_ONLY and squash(evidence) not in squash(text):
            rejected[axis] = "quote_not_in_input"
        elif isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1:
            rejected[axis] = "invalid_confidence"
        else:
            accepted[axis] = {"values": values, "evidence": evidence.strip(), "confidence": float(confidence)}
    return accepted, rejected


_local = threading.local()
_pause_until = [0.0]  # shared across workers: after a 429 every worker waits
_pause_lock = threading.Lock()
RATE_LIMIT_TRIES = 6
RATE_LIMIT_WAIT_S = 60.0


def wait_for_pause() -> None:
    while True:
        with _pause_lock:
            left = _pause_until[0] - time.monotonic()
        if left <= 0:
            return
        time.sleep(min(left, 5.0))


def call(job: dict[str, Any], args: argparse.Namespace, key: str, out_dir: Path) -> tuple[int, bool]:
    gateway = getattr(_local, "gateway", None)
    if gateway is None:
        gateway = _local.gateway = ImageChatGateway(endpoint=ENDPOINT, model=args.model, api_key=key,
                                                    timeout=OPENCODE_TIMEOUT, max_output_tokens=OPENCODE_MAX_OUTPUT_TOKENS)
    record, axes = job["record"], job["axes"]
    group, text = record["group"], job["text"][:MAX_TEXT]
    out: dict[str, Any] = {"fill_version": FILL_VERSION, "id": record["id"], "model": args.model,
                           "called_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "group": group,
                           "requested": axes, "fills": {}, "rejected": {}, "error": None}
    started = time.monotonic()
    for attempt in range(RATE_LIMIT_TRIES):
        wait_for_pause()
        out["error"] = None
        try:
            gateway.image_uri = image_uri(Path(job["image"]))
            known = {a: s["values"] for a, s in record["pi"].items() if s["values"]}
            result = gateway.complete(INSTRUCTIONS.replace("GARMENT", "skirt" if group == "skirt" else "top"), {
                "product_text": text, "known_features": known,
                "requested_features": {a: {"meaning": GUIDES[group][a], "allowed": unified.allowed(a, group)}
                                       for a in axes}},
                output_schema(axes, group))
            out["fills"], out["rejected"] = validate(result, axes, text, group)
        except StyleMateError as error:
            out["error"] = error.code
        except OSError:
            out["error"] = "image_read_failed"
        if out["error"] != "provider_rate_limited":
            break
        with _pause_lock:  # back off together, longer on each retry
            _pause_until[0] = max(_pause_until[0], time.monotonic() + RATE_LIMIT_WAIT_S * (attempt + 1))
    out["attempts"] = attempt + 1
    out["elapsed_s"] = round(time.monotonic() - started, 1)
    (out_dir / f"{record['id']}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    time.sleep(args.interval_s)
    return len(out["fills"]), bool(out["error"])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data", type=Path, default=Path("data"))
    parser.add_argument("--drive", type=Path, default=None)
    parser.add_argument("--limit", type=int, default=None, help="process at most N products that still need a call")
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--model", default=DEEPSEEK_DEFAULT_MODEL)
    parser.add_argument("--interval-s", type=float, default=0.3)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()
    key = os.environ.get("OPENCODE_API_KEY", "")
    if not key.strip():
        print("OPENCODE_API_KEY가 설정되지 않아 중단합니다(다른 provider로 대체하지 않음).", file=sys.stderr)
        return 3
    out_dir = args.data / "raw" / "fills_unified"
    out_dir.mkdir(parents=True, exist_ok=True)
    records, meta = unified.collect(args.drive or args.data / "raw" / "drive", None)
    raw = {r["id"]: r for r in records if r["id"] in set(meta["raw_ids"])}
    jobs = []
    for item in unified.pending(list(raw.values()), set(raw)):
        target = out_dir / f"{item['record']['id']}.json"
        if target.exists():
            previous = json.loads(target.read_text(encoding="utf-8"))
            if not (args.retry_errors and previous.get("error")):
                continue
        item["image"], item["text"] = item["record"]["image_source"], item["record"].get("seller_text") or item["record"]["title"]
        jobs.append(item)
    if args.limit is not None:
        jobs = jobs[:args.limit]
    print(f"jobs={len(jobs)} workers={args.workers}", flush=True)
    calls = errors = accepted = 0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for future in as_completed([pool.submit(call, job, args, key, out_dir) for job in jobs]):
            got, failed = future.result()
            calls, accepted, errors = calls + 1, accepted + got, errors + failed
            if calls % 50 == 0:
                print(f"calls={calls} errors={errors} accepted_axes={accepted}", flush=True)
    print(json.dumps({"calls": calls, "errors": errors, "accepted_axes": accepted}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
