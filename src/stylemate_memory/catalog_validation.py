"""Closed, offline validation for supplier catalog data (not user memories)."""

from __future__ import annotations

from datetime import datetime
import json
import math
from pathlib import PurePosixPath
import re
from typing import Any
from urllib.parse import unquote, urlsplit

from .contracts import CATALOG_FORMAT_VERSION, CatalogRecord, ProductAssertion, RegistryPort
from .errors import StyleMateError


MAX_RECORD_BYTES = 256 * 1024
IMAGE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp", ".gif": "image/gif"}


def fail(location: str, reason: str, code: str = "invalid_input") -> None:
    # Locations contain field names and indices, never supplier values or paths.
    raise StyleMateError(code, f"{location}: {reason}")


def fields(value: Any, names: set[str], location: str) -> None:
    if not isinstance(value, dict) or set(value) != names:
        fail(location, "required/unknown fields do not match the contract")


def text(value: Any, location: str, limit: int = 128) -> None:
    if (not isinstance(value, str) or not value.strip() or len(value) > limit
            or any(ord(c) < 32 and c not in "\n\r\t" for c in value)):
        fail(location, f"nonblank text of at most {limit} characters required")


def identifier(value: Any, location: str) -> None:
    text(value, location)
    if value != value.strip() or any(ord(c) < 32 for c in value):
        fail(location, "opaque ID/revision must not contain control or edge whitespace")


def version(value: Any, location: str) -> None:
    if type(value) is not int or not 1 <= value <= 2**63 - 1:
        fail(location, "positive integer version required (bool is not a version)")


def timestamp(value: Any, location: str) -> None:
    text(value, location)
    try:
        parsed = datetime.fromisoformat(value)
        if parsed.tzinfo is None or parsed.utcoffset() is None or "T" not in value:
            raise ValueError
    except ValueError:
        fail(location, "ISO 8601 timestamp with timezone required")


def url(value: Any, location: str, *, image: bool = False) -> None:
    text(value, location, 2048)
    try:
        parsed = urlsplit(value)
        if (parsed.scheme not in (("https",) if image else ("http", "https"))
                or not parsed.hostname or parsed.username is not None or parsed.password is not None
                or parsed.fragment or "\\" in value or any(c.isspace() for c in value)
                or (image and parsed.port not in (None, 443))):
            raise ValueError
        parsed.port  # Validate malformed ports for source URLs too.
    except ValueError:
        fail(location, "supplier HTTP(S) URL required; image URLs require HTTPS without credentials")


def local_location(value: Any, location: str) -> None:
    text(value, location, 2048)
    path = PurePosixPath(value)
    if (path.is_absolute() or "\\" in value or ":" in value or unquote(value) != value
            or any(part in ("", ".", "..") for part in value.split("/"))
            or any(ord(c) < 32 for c in value) or path.suffix.lower() not in IMAGE_TYPES):
        fail(location, "relative PNG/JPEG/WebP/GIF path inside the configured image root required")


def canonical(value: Any, location: str = "records") -> str:
    def check(node: Any, depth: int = 0) -> None:
        if depth > 32:
            fail(location, "JSON nesting exceeds 32 levels")
        if node is None or type(node) in (bool, int, str):
            return
        if type(node) is float and math.isfinite(node):
            return
        if isinstance(node, list):
            for item in node:
                check(item, depth + 1)
            return
        if isinstance(node, dict) and all(isinstance(key, str) for key in node):
            for item in node.values():
                check(item, depth + 1)
            return
        fail(location, "finite UTF-8 JSON values with string object keys required")

    check(value)
    try:
        result = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        result.encode("utf-8")
        return result
    except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
        fail(location, "invalid JSON value")


def _source_value(record: CatalogRecord, source_field: str, location: str) -> Any:
    parts = source_field.split(".")
    if parts[0] not in ("title", "description", "raw_metadata"):
        fail(location, "source_field must refer to title, description, or raw_metadata")
    node: Any = record
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            fail(location, "source_field does not exist in this product's raw record")
        node = node[part]
    return node


def validate_assertions(assertions: Any, record: CatalogRecord, registry: RegistryPort,
                        location: str) -> None:
    if not isinstance(assertions, list) or len(assertions) > 256:
        fail(location, "at most 256 product assertions required")
    seen = set()
    for index, assertion in enumerate(assertions):
        at = f"{location}[{index}]"
        fields(assertion, {"observation", "status", "provenance"}, at)
        observation = assertion["observation"]
        try:
            registry.validate_observation(observation, record["garment_type"])
        except StyleMateError as exc:
            fail(f"{at}.observation", exc.message, exc.code)
        key = canonical({k: v for k, v in observation.items() if k not in ("values", "present")})
        if key in seen:
            fail(at, "duplicate observation path; represent conflicting evidence in one assertion")
        seen.add(key)
        status = assertion["status"]
        if status not in ("confirmed", "inferred", "unknown", "conflict"):
            fail(f"{at}.status", "invalid product assertion status")
        value = observation["values" if observation["domain"] == "PI" else "present"]
        provenance = assertion["provenance"]
        if not isinstance(provenance, list) or len(provenance) > 64:
            fail(f"{at}.provenance", "at most 64 provenance entries required")
        kinds = []
        direct_pi = False
        for p_index, source in enumerate(provenance):
            where = f"{at}.provenance[{p_index}]"
            fields(source, {"kind", "source_field", "quote", "verifier", "evidence_ref", "verified_at"}, where)
            kind = source["kind"]
            if kind not in ("raw_metadata", "provided_label", "verified_label", "model_interpretation", "unknown"):
                fail(f"{where}.kind", "invalid provenance kind")
            kinds.append(kind)
            for field in ("source_field", "quote", "verifier", "evidence_ref"):
                if source[field] is not None:
                    text(source[field], f"{where}.{field}", 4000 if field == "quote" else 128)
            if source["verified_at"] is not None:
                timestamp(source["verified_at"], f"{where}.verified_at")
            if source["source_field"] is not None:
                raw = _source_value(record, source["source_field"], f"{where}.source_field")
                quote = source["quote"]
                original = raw if isinstance(raw, str) else canonical(raw)
                if quote is None or quote not in original:
                    fail(f"{where}.quote", "quote must occur in the supplied raw field")
                # A canonical PI scalar/list may be checked directly against
                # supplier metadata. Mere word occurrence in prose, photos,
                # and FEA/performance claims are not direct verification.
                if (kind == "raw_metadata" and source["source_field"].startswith("raw_metadata.")
                        and observation["domain"] == "PI" and value is not None
                        and (raw if isinstance(raw, list) else [raw]) == value
                        and all(item in quote for item in value)):
                    direct_pi = True
            elif source["quote"] is not None:
                fail(f"{where}.quote", "a quote needs a raw source_field")
            if kind == "unknown":
                if any(source[k] is not None for k in source if k != "kind"):
                    fail(where, "unknown provenance cannot claim evidence or verification")
            elif kind == "raw_metadata" and source["source_field"] is None:
                fail(where, "raw provenance needs source_field and exact quote")
            elif kind == "provided_label" and (source["verifier"] is None or
                                               not (source["source_field"] or source["evidence_ref"])):
                fail(where, "provided label needs its supplier and source/evidence reference")
            elif kind == "verified_label" and any(source[k] is None for k in ("verifier", "verified_at", "evidence_ref")):
                fail(where, "verified label needs verifier, verified_at, and supplier evidence_ref")
            elif kind == "model_interpretation" and not (source["source_field"] or source["evidence_ref"]):
                fail(where, "model interpretation needs raw or supplied image evidence")
            if kind not in ("verified_label", "unknown") and source["verified_at"] is not None:
                fail(where, "unverified provenance cannot supply verified_at")
        if status == "unknown":
            if value is not None or any(kind != "unknown" for kind in kinds):
                fail(at, "unknown must preserve a null value and no claimed verification")
        elif not kinds or all(kind == "unknown" for kind in kinds):
            fail(at, "non-unknown assertion needs provenance")
        elif status == "confirmed":
            if value is None or not ("verified_label" in kinds or direct_pi) or "model_interpretation" in kinds:
                fail(at, "confirmed requires a verified label or exact canonical PI metadata; model claims stay inferred")
        elif status == "inferred" and value is None:
            fail(at, "inferred assertion needs a candidate value")


def validate_record(record: Any, registry: RegistryPort, location: str) -> CatalogRecord:
    fields(record, {"format_version", "product_id", "source", "title", "description", "garment_type",
                    "raw_metadata", "images", "labels"}, location)
    if record["format_version"] != CATALOG_FORMAT_VERSION:
        fail(f"{location}.format_version", "unsupported catalog format", "unsupported_contract")
    encoded = canonical(record, location)
    try:
        size = len(encoded.encode("utf-8"))
    except UnicodeError:
        fail(location, "invalid UTF-8 text")
    if size > MAX_RECORD_BYTES:
        fail(location, "record exceeds 256 KiB")
    for field in ("product_id", "garment_type"):
        identifier(record[field], f"{location}.{field}")
    text(record["title"], f"{location}.title", 4000)
    if record["description"] is not None:
        text(record["description"], f"{location}.description", 4000)
    source = record["source"]
    fields(source, {"source_id", "url", "collected_at"}, f"{location}.source")
    identifier(source["source_id"], f"{location}.source.source_id")
    url(source["url"], f"{location}.source.url")
    timestamp(source["collected_at"], f"{location}.source.collected_at")
    if not isinstance(record["raw_metadata"], dict):
        fail(f"{location}.raw_metadata", "JSON object required")
    if not isinstance(record["images"], list) or len(record["images"]) > 32:
        fail(f"{location}.images", "at most 32 image references required")
    image_ids = set()
    for index, image in enumerate(record["images"]):
        at = f"{location}.images[{index}]"
        fields(image, {"image_id", "kind", "location", "source_revision", "sha256", "regions"}, at)
        identifier(image["image_id"], f"{at}.image_id")
        if image["image_id"] in image_ids:
            fail(f"{at}.image_id", "duplicate image ID", "catalog_conflict")
        image_ids.add(image["image_id"])
        identifier(image["source_revision"], f"{at}.source_revision")
        if image["kind"] == "local":
            local_location(image["location"], f"{at}.location")
        elif image["kind"] == "remote":
            url(image["location"], f"{at}.location", image=True)
        else:
            fail(f"{at}.kind", "local or remote required")
        if image["sha256"] is not None and (not isinstance(image["sha256"], str) or
                                            re.fullmatch(r"[0-9a-fA-F]{64}", image["sha256"]) is None):
            fail(f"{at}.sha256", "null or 64 hexadecimal characters required")
        if not isinstance(image["regions"], list) or len(image["regions"]) > 32:
            fail(f"{at}.regions", "at most 32 named image regions required")
        region_ids = set()
        for r_index, region in enumerate(image["regions"]):
            where = f"{at}.regions[{r_index}]"
            fields(region, {"region_id", "garment_type", "box"}, where)
            identifier(region["region_id"], f"{where}.region_id")
            identifier(region["garment_type"], f"{where}.garment_type")
            if region["region_id"] in region_ids:
                fail(where, "duplicate named region")
            region_ids.add(region["region_id"])
            box = region["box"]
            if (not isinstance(box, list) or len(box) != 4 or
                    any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in box)
                    or not (box[0] < box[2] and box[1] < box[3])):
                fail(f"{where}.box", "normalized [left, top, right, bottom] with positive area required")
    validate_assertions(record["labels"], record, registry, f"{location}.labels")
    return json.loads(encoded)
