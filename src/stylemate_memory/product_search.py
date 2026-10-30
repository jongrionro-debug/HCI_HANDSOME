"""Offline product retrieval, separate from user-memory retrieval.

Only constraints execute; flattened target values are display fields. Confirmed
product observations can satisfy conditions, while inferred/unknown/conflicting
observations cannot. Scores are an initial, equal-weight soft baseline, not a
learned relevance measure. The module logger records product counts and latency
only. No model, image I/O, user-memory writes or automatic relaxation occurs.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import logging
from time import perf_counter

from .catalog_validation import (
    MAX_RECORD_BYTES, canonical, fields, identifier, text, timestamp,
    validate_assertions, version,
)
from .contracts import (
    CONTRACT_VERSION, Basis, CatalogPort, CatalogVersions, Constraint,
    FeaturePath, ProductMap, SearchHit, SearchResult, TargetMap, validate_ref,
)
from .errors import StyleMateError
from .registry import load_registry


logger = logging.getLogger(__name__)


def _fail(message: str, code: str = "invalid_input") -> None:
    raise StyleMateError(code, message)


def _refs(refs: list, limit: int = 256) -> None:
    if not isinstance(refs, list) or len(refs) > limit:
        _fail("Invalid version references.")
    seen = set()
    for ref in refs:
        checked = validate_ref(ref)
        key = (checked["type"], checked["id"])
        if key in seen:
            _fail("Duplicate version reference.")
        seen.add(key)


def _validate_catalog_versions(value: CatalogVersions) -> None:
    fields(value, {"catalog_version", "products", "images"}, "catalog basis")
    if type(value["catalog_version"]) is not int or value["catalog_version"] < 0:
        _fail("Invalid catalog revision.")
    for name, id_field, keys in (
        ("products", "product_id", {"product_id", "raw_version", "map_version"}),
        ("images", "image_id", {"image_id", "version"}),
    ):
        if not isinstance(value[name], list) or len(value[name]) > 256:
            _fail("Catalog freshness supports at most 256 dependencies of each kind.", "context_blocked")
        seen = set()
        for entry in value[name]:
            fields(entry, keys, "catalog dependency")
            identifier(entry[id_field], id_field)
            for key in keys - {id_field}:
                version(entry[key], key)
            if entry[id_field] in seen:
                _fail("Duplicate catalog dependency.")
            seen.add(entry[id_field])


def _current(catalog: CatalogPort, products: list[str], images: list[str]) -> CatalogVersions:
    if len(products) > 256 or len(images) > 256:
        _fail("Catalog freshness supports at most 256 dependencies of each kind.", "context_blocked")
    return catalog.current_versions(sorted(products), sorted(images))


def _check_catalog(catalog: CatalogPort, expected: CatalogVersions) -> None:
    _validate_catalog_versions(expected)
    current = _current(catalog, [p["product_id"] for p in expected["products"]],
                       [i["image_id"] for i in expected["images"]])
    ordered = deepcopy(expected)
    ordered["products"].sort(key=lambda p: p["product_id"])
    ordered["images"].sort(key=lambda i: i["image_id"])
    if current != ordered:
        _fail("Product search dependencies changed; search again.", "stale_context")


def _path(value: dict) -> FeaturePath:
    keys = ("domain", "feature") if value["domain"] == "PI" else ("domain", "category", "subcategory", "tag")
    return {key: value[key] for key in keys}


def _validate_target_map(target_map: TargetMap):
    fields(target_map, set(TargetMap.__required_keys__), "target_map")
    if len(canonical(target_map).encode("utf-8")) > MAX_RECORD_BYTES:
        _fail("Target map exceeds 256 KiB.")
    if target_map["contract_version"] != CONTRACT_VERSION:
        _fail("Unsupported target contract.", "unsupported_contract")
    registry = load_registry(target_map["registry_version"])
    identifier(target_map["context_id"], "context_id")
    basis = target_map["basis"]
    fields(basis, set(Basis.__required_keys__), "basis")
    if (basis["contract_version"] != CONTRACT_VERSION
            or basis["registry_version"] != registry.version):
        _fail("Target and basis contracts differ.", "stale_context")
    identifier(basis["request_id"], "basis.request_id")
    version(basis["request_revision"], "request_revision")
    # A profile without long-term entries has revision zero.
    if type(basis["profile_revision"]) is not int or basis["profile_revision"] < 0:
        _fail("Invalid profile revision.")
    _refs(basis["object_versions"])
    basis_refs = {canonical(ref) for ref in basis["object_versions"]}
    if basis["index_version"] is not None:
        identifier(basis["index_version"], "index_version")
    if basis["valid_until"] is not None:
        timestamp(basis["valid_until"], "valid_until")
        if datetime.fromisoformat(basis["valid_until"]) <= datetime.now(timezone.utc):
            _fail("Product search basis expired.", "stale_context")
    if basis["catalog"] is not None:
        _validate_catalog_versions(basis["catalog"])
    if not isinstance(target_map["questions"], list):
        _fail("Invalid target questions.")
    for question in target_map["questions"]:
        text(question, "question", 4000)
    if not isinstance(target_map["targets"], list) or not target_map["targets"]:
        _fail("A target is required.")
    targets = {}
    for target in target_map["targets"]:
        fields(target, {"target_id", "garment_type", "product_information", "consumer_needs"}, "target")
        tid = target["target_id"]
        identifier(tid, "target_id")
        if tid in targets:
            _fail("Duplicate target ID.")
        empty = registry.empty_target(tid, target["garment_type"])
        fields(target["product_information"], set(empty["product_information"]), "product_information")
        fields(target["consumer_needs"], set(empty["consumer_needs"]), "consumer_needs")
        for feature, value in target["product_information"].items():
            registry.validate_target_value({"domain": "PI", "feature": feature}, value, target["garment_type"])
        for category, subcategories in empty["consumer_needs"].items():
            fields(target["consumer_needs"][category], set(subcategories), "FEA category")
            for subcategory, tags in subcategories.items():
                supplied = target["consumer_needs"][category][subcategory]
                fields(supplied, set(tags), "FEA subcategory")
                for tag, value in supplied.items():
                    registry.validate_target_value({"domain": "FEA", "category": category,
                                                    "subcategory": subcategory, "tag": tag},
                                                   value, target["garment_type"])
        targets[tid] = target
    if not isinstance(target_map["constraints"], list):
        _fail("Invalid target constraints.")
    ids = set()
    for constraint in target_map["constraints"]:
        fields(constraint, set(Constraint.__required_keys__), "constraint")
        identifier(constraint["id"], "constraint.id")
        identifier(constraint["target_id"], "constraint.target_id")
        if constraint["id"] in ids or constraint["target_id"] not in targets:
            _fail("Duplicate constraint or unknown target.")
        ids.add(constraint["id"])
        if constraint["origin"] not in ("explicit", "inferred") or type(constraint["confirmed"]) is not bool:
            _fail("Invalid constraint authority fields.")
        if constraint["binding_ref"] is not None:
            if validate_ref(constraint["binding_ref"])["type"] != "binding":
                _fail("binding_ref must refer to a binding.")
        _refs(constraint["source_refs"], 64)
        if not constraint["source_refs"]:
            _fail("A constraint needs source references.")
        dependencies = constraint["source_refs"] + ([constraint["binding_ref"]] if constraint["binding_ref"] is not None else [])
        if any(canonical(ref) not in basis_refs for ref in dependencies):
            _fail("Constraint dependencies are missing from the target basis.", "stale_context")
        fields(constraint["selector"], {"garment_type", "slot_id"}, "selector")
        target = targets[constraint["target_id"]]
        if (constraint["selector"]["garment_type"] not in (None, target["garment_type"])
                or constraint["selector"]["slot_id"] not in (None, target["target_id"])):
            _fail("Constraint selector does not match its target.")
        conditions = constraint["conditions"]
        if not isinstance(conditions, dict) or not set(conditions) <= {"occasion", "activity", "goal"}:
            _fail("Invalid constraint conditions.")
        for value in conditions.values():
            text(value, "condition", 4000)
        binding = constraint["binding"]
        if not isinstance(binding, dict) or binding.get("strength") not in ("hard", "soft"):
            _fail("Invalid constraint binding.")
        if binding.get("domain") not in ("PI", "FEA"):
            _fail("Invalid constraint domain.")
        binding_keys = ({"feature", "values", "match"} if binding["domain"] == "PI"
                        else {"category", "subcategory", "tag"})
        fields(binding, {"domain", "polarity", "strength"} | binding_keys, "constraint.binding")
        if binding["polarity"] not in ("prefer", "require", "avoid", "indifferent"):
            _fail("Invalid constraint polarity.")
        # Unsupported operations remain visible as blocked hard/unknown soft
        # conditions. Never execute a range as an any/all list.
        try:
            registry.validate_binding(binding, target["garment_type"])
        except StyleMateError as exc:
            if exc.code != "unsupported_mapping":
                raise
    return registry, targets


def _constraints(target_map: TargetMap, target_id: str) -> list[Constraint]:
    return [c for c in target_map["constraints"] if c["target_id"] == target_id]


def _blocked(constraints: list[Constraint], target: dict, registry) -> bool:
    if target["garment_type"] not in registry.describe()["execution"]["supported_garment_types"]:
        return True
    for constraint in constraints:
        if constraint["binding"]["strength"] != "hard":
            continue
        if not constraint["confirmed"]:
            return True
        try:
            registry.validate_binding(constraint["binding"], target["garment_type"])
        except StyleMateError as exc:
            if exc.code != "unsupported_mapping":
                raise
            return True
    return False


def _evaluate(product_map: ProductMap, constraints: list[Constraint], registry, garment: str) -> SearchHit | None:
    observations = {canonical(_path(a["observation"])): a for a in product_map["assertions"]}
    matched, unknown = [], []
    score = 0.0
    for constraint in constraints:
        binding = constraint["binding"]
        if binding["polarity"] == "indifferent":
            continue
        try:
            registry.validate_binding(binding, garment)
        except StyleMateError as exc:
            if exc.code != "unsupported_mapping":
                raise
            observation = None
        else:
            observation = observations.get(canonical(_path(binding)))
        satisfied = None
        if observation is not None and observation["status"] == "confirmed":
            value = observation["observation"]
            if binding["domain"] == "PI" and value["values"] is not None:
                matches = [v in value["values"] for v in binding["values"]]
                satisfied = any(matches) if binding["match"] == "any" else all(matches)
            elif binding["domain"] == "FEA":
                satisfied = value["present"]
            if satisfied is not None and binding["polarity"] == "avoid":
                satisfied = not satisfied
        if binding["strength"] == "hard" and satisfied is not True:
            return None
        if satisfied is None:
            unknown.append(constraint["id"])
        elif satisfied:
            matched.append(constraint["id"])
        if binding["strength"] == "soft" and satisfied is not None:
            score += 1.0 if satisfied else -1.0
    return {"product_id": product_map["product_id"], "product_map_version": product_map["map_version"],
            "score": score, "matched_constraint_ids": sorted(matched), "unknown_constraint_ids": sorted(unknown)}


def search_products(target_map: TargetMap, target_id: str, catalog: CatalogPort) -> SearchResult:
    """Filter one target's confirmed hard requirements, then rank soft matches.

    Unsupported/unconfirmed hard conditions or unbuilt/stale maps block retrieval;
    product facts that are unknown simply fail the hard filter. Expiry and catalog
    changes are checked here; A/B must also recheck memory/request state at apply.
    The CatalogPort freshness ceiling is 256 product/image dependencies each.
    """
    started = perf_counter()
    registry, targets = _validate_target_map(target_map)
    identifier(target_id, "target_id")
    if target_id not in targets:
        _fail("Unknown product-search target.")
    basis = deepcopy(target_map["basis"])
    if basis["catalog"] is not None:
        _check_catalog(catalog, basis["catalog"])
    initial = _current(catalog, [], [])
    target = targets[target_id]
    constraints = _constraints(target_map, target_id)
    hits = []
    products, images = {}, set()
    status = "blocked" if _blocked(constraints, target, registry) else "no_results"
    scanned = 0
    if status != "blocked":
        records = {}
        for record in catalog.export_records():
            pid = record["product_id"]
            if pid in records and records[pid] != record:
                _fail("Conflicting duplicate product records.", "catalog_conflict")
            records[pid] = record
        for pid, record in sorted(records.items()):
            if record["garment_type"] != target["garment_type"]:
                continue
            scanned += 1
            try:
                product_map = catalog.get_product_map(pid)
            except StyleMateError as exc:
                if exc.code not in ("context_blocked", "stale_context"):
                    raise
                status = "blocked"
                continue
            if product_map["registry_version"] != registry.version or product_map["subject"] != "product":
                _fail("Product and target map registries differ.", "unsupported_contract")
            validate_assertions(product_map["assertions"], record, registry, "product_map.assertions")
            products[pid] = {"product_id": pid, "raw_version": product_map["raw_version"],
                             "map_version": product_map["map_version"]}
            images.update(image["image_id"] for image in record["images"])
            hit = _evaluate(product_map, constraints, registry, target["garment_type"])
            if hit is not None:
                hits.append(hit)
    previous = basis["catalog"]
    if previous is not None:
        for p in previous["products"]:
            if p["product_id"] in products and products[p["product_id"]] != p:
                _fail("Product dependencies changed during retrieval.", "stale_context")
            products[p["product_id"]] = p
        images.update(i["image_id"] for i in previous["images"])
    current = _current(catalog, list(products), list(images))
    if (current["catalog_version"] != initial["catalog_version"]
            or current["products"] != [products[pid] for pid in sorted(products)]):
        _fail("Catalog changed during product search.", "stale_context")
    basis["catalog"] = current
    if status == "blocked":
        hits = []
    else:
        hits.sort(key=lambda hit: (-hit["score"], hit["product_id"]))
        status = "results" if hits else "no_results"
    logger.info("product_search status=%s scanned=%d eligible=%d elapsed_ms=%.3f",
                status, scanned, len(hits), (perf_counter() - started) * 1000)
    return {"target_id": target_id, "hits": hits, "status": status, "basis": basis}
