"""Build versioned comparison cards from real, hard-eligible product hits.

The default/detail/two_axis sizes (3/2/4) are adjustable pilot assumptions. A
two-axis comparison requires four actual combinations; otherwise the focus is
reduced. Axes describe confirmed differences, never a controlled experiment or
an inferred selection reason. B owns round/set IDs and immutable publication.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
from itertools import combinations, product
import math

from .catalog_validation import canonical, fields, identifier, version
from .contracts import (
    CandidatePlan, CatalogPort, SearchHit, SearchResult, TargetMap,
)
from .product_search import (
    _blocked, _check_catalog, _constraints, _current, _evaluate, _fail,
    _validate_target_map,
)


_VISUAL_FEATURES = ("Color", "Fit", "Detail", "Type")
_SIZES = {"default": 3, "two_axis": 4, "detail": 2}
_NO_RESULTS_OPTIONS = ["조건 유지", "조건 조정", "탐색 종료"]


def _value(entry: dict, feature: str) -> tuple[str, ...] | None:
    for assertion in entry["map"]["assertions"]:
        observation = assertion["observation"]
        if (observation["domain"] == "PI" and observation["feature"] == feature
                and assertion["status"] == "confirmed" and observation["values"]):
            return tuple(sorted(observation["values"]))
    return None


def _deduplicate(entries: list[dict]) -> list[dict]:
    """Collapse duplicate products/photos, without guessing visual similarity."""
    seen_products, seen_sources, seen_views = set(), set(), set()
    kept = []
    for entry in entries:
        record = entry["record"]
        pid = record["product_id"]
        observations = [{"observation": a["observation"], "status": a["status"]} for a in entry["map"]["assertions"]]
        observations.sort(key=canonical)
        signature = canonical(observations)
        # Variants may share a product page. Different confirmed Maps remain
        # distinct even when their supplier URL or image is the same.
        source = (record["source"]["url"], signature)
        image = entry["image"]
        view = None
        if image is not None:
            identity = image["sha256"] or canonical({key: image[key] for key in ("kind", "location", "source_revision")})
            view = (identity, signature)
        if pid in seen_products or source in seen_sources or (view is not None and view in seen_views):
            continue
        seen_products.add(pid)
        seen_sources.add(source)
        if view is not None:
            seen_views.add(view)
        kept.append(entry)
    return kept


def _axes(entries: list[dict], target: dict) -> list[str]:
    result = []
    for feature in _VISUAL_FEATURES:
        if target["product_information"][feature]["status"] not in ("unspecified", "inferred", "conflict"):
            continue
        values = {_value(entry, feature) for entry in entries if entry["image"] is not None}
        values.discard(None)
        if len(values) > 1:
            result.append(feature)
    return result


def _rectangle(entries: list[dict], axes: list[str]):
    for first, second in combinations(axes, 2):
        cells = {}
        for index, entry in enumerate(entries):
            a, b = _value(entry, first), _value(entry, second)
            if entry["image"] is not None and a is not None and b is not None:
                cells.setdefault((a, b), (index, entry))
        values_a = sorted({a for a, _ in cells})
        values_b = sorted({b for _, b in cells})
        best = None
        for pair_a, pair_b in product(combinations(values_a, 2), combinations(values_b, 2)):
            keys = list(product(pair_a, pair_b))
            if all(key in cells for key in keys):
                chosen = sorted((cells[key] for key in keys), key=lambda item: item[0])
                rank = tuple(index for index, _ in chosen)
                if best is None or (sum(rank), rank) < best[0]:
                    best = ((sum(rank), rank), [entry for _, entry in chosen])
        if best is not None:
            return best[1], [first, second]
    return None


def _select(entries: list[dict], target: dict, count: int, mode: str):
    axes = _axes(entries, target)
    reduced = False
    if mode == "two_axis":
        rectangle = _rectangle(entries, axes) if count == 4 else None
        if rectangle is not None:
            return rectangle[0], rectangle[1], False
        reduced = True
        count = min(count, _SIZES["default"])
    if count < 2 or not axes:
        return entries[:count], [], reduced
    focus = axes[:1 if mode == "detail" or reduced else 2]
    known = [entry for entry in entries if entry["image"] is not None
             and all(_value(entry, axis) is not None for axis in focus)]
    if len(known) < 2 and len(focus) == 2:
        focus = focus[:1]
        known = [entry for entry in entries if entry["image"] is not None and _value(entry, focus[0]) is not None]
    if len(known) < 2:
        return entries[:count], [], reduced
    selected = [known.pop(0)]
    while known and len(selected) < count:
        seen = {axis: {_value(entry, axis) for entry in selected} for axis in focus}
        best = max(range(len(known)), key=lambda i: (
            sum(_value(known[i], axis) not in seen[axis] for axis in focus), -i,
        ))
        selected.append(known.pop(best))
    focus = [axis for axis in focus if len({_value(entry, axis) for entry in selected}) > 1]
    selected.sort(key=lambda entry: (-entry["hit"]["score"], entry["hit"]["product_id"]))
    return selected, focus, reduced


def build_candidate_cards(results: list[SearchResult], target_map: TargetMap, catalog: CatalogPort,
                          *, mode: str = "default", size: int | None = None) -> CandidatePlan:
    """Return the A0 CandidatePlan; do not publish sets or mutate user state.

    ``mode`` selects the 3/4/2 pilot policy and ``size`` overrides its card budget
    within 1..4. Multiple targets share this budget, with at least one card per
    available target, and comparisons remain target-local. Missing images stay
    null and cannot establish a visual comparison axis. Every result must belong
    to the exact target basis and current catalog; stale results are rejected.
    Product evidence is reachable via card -> basis/catalog -> ProductMap assertions.
    """
    registry, targets = _validate_target_map(target_map)
    if mode not in _SIZES or (size is not None and (type(size) is not int or not 1 <= size <= 4)):
        _fail("Invalid comparison mode or size.")
    count = _SIZES[mode] if size is None else size
    if not isinstance(results, list) or len(results) != len(targets):
        _fail("Supply one product-search result per target.")
    basis = deepcopy(target_map["basis"])
    product_versions, image_versions, pools, statuses = {}, {}, {}, {}
    catalog_version = None
    records = {record["product_id"]: record for record in catalog.export_records()}
    for result in results:
        fields(result, set(SearchResult.__required_keys__), "search_result")
        tid = result["target_id"]
        if tid not in targets or tid in pools:
            _fail("Duplicate or unknown search-result target.")
        supplied_basis = result["basis"]
        fields(supplied_basis, set(basis), "search_result.basis")
        if any(supplied_basis[key] != basis[key] for key in basis if key != "catalog"):
            _fail("Product results belong to another target context.", "stale_context")
        versions = supplied_basis["catalog"]
        if versions is None:
            _fail("Product result is missing catalog freshness.", "stale_context")
        _check_catalog(catalog, versions)
        if catalog_version not in (None, versions["catalog_version"]):
            _fail("Product results use different catalog snapshots.", "stale_context")
        catalog_version = versions["catalog_version"]
        by_product = {p["product_id"]: p for p in versions["products"]}
        product_versions.update(by_product)
        image_versions.update({image["image_id"]: image for image in versions["images"]})
        status, hits = result["status"], result["hits"]
        if status not in ("results", "no_results", "blocked") or not isinstance(hits, list):
            _fail("Invalid product-search result.")
        if (status == "results") != bool(hits):
            _fail("Product-search status and hits disagree.")
        target = targets[tid]
        constraints = _constraints(target_map, tid)
        if status == "results" and _blocked(constraints, target, registry):
            _fail("Blocked target cannot have product hits.", "invalid_output")
        entries = []
        for hit in hits:
            fields(hit, set(SearchHit.__required_keys__), "search_hit")
            identifier(hit["product_id"], "product_id")
            version(hit["product_map_version"], "product_map_version")
            if type(hit["score"]) not in (int, float) or not math.isfinite(hit["score"]):
                _fail("Invalid product score.")
            pid = hit["product_id"]
            if pid not in records or pid not in by_product:
                _fail("Product hit has no catalog dependency.", "stale_context")
            record = records[pid]
            product_map = catalog.get_product_map(pid)
            expected = by_product[pid]
            if (record["garment_type"] != target["garment_type"]
                    or product_map["raw_version"] != expected["raw_version"]
                    or product_map["map_version"] != expected["map_version"]):
                _fail("Product hit is stale or belongs to another target.", "stale_context")
            checked = _evaluate(product_map, constraints, registry, target["garment_type"])
            if checked is None or checked != hit:
                _fail("Product hit violates its target filter/ranking.", "invalid_output")
            image = record["images"][0] if record["images"] else None
            if image is not None and image["image_id"] not in image_versions:
                _fail("Product hit is missing its image dependency.", "stale_context")
            entries.append({"record": record, "map": product_map, "image": image, "hit": hit})
        entries.sort(key=lambda entry: (-entry["hit"]["score"], entry["hit"]["product_id"]))
        pools[tid] = _deduplicate(entries)
        statuses[tid] = status
    if basis["catalog"] is not None:
        _check_catalog(catalog, basis["catalog"])
        product_versions.update({p["product_id"]: p for p in basis["catalog"]["products"]})
        image_versions.update({i["image_id"]: i for i in basis["catalog"]["images"]})
    current = _current(catalog, list(product_versions), list(image_versions))
    if (current["catalog_version"] != catalog_version
            or current["products"] != [product_versions[pid] for pid in sorted(product_versions)]
            or current["images"] != [image_versions[iid] for iid in sorted(image_versions)]):
        _fail("Catalog changed during comparison planning.", "stale_context")
    basis["catalog"] = current
    available = [tid for tid in targets if pools[tid]]
    if len(available) > 4:
        _fail("A candidate set cannot represent more than four targets.", "context_blocked")
    budget = max(count, len(available))
    allocations = {tid: 1 for tid in available}
    while sum(allocations.values()) < budget:
        advanced = False
        for tid in available:
            if sum(allocations.values()) < budget and allocations[tid] < len(pools[tid]):
                allocations[tid] += 1
                advanced = True
        if not advanced:
            break
    selected, compared, questions = [], [], []
    empty = [tid for tid in targets if not pools[tid]]
    if empty:
        blocked = any(statuses[tid] == "blocked" for tid in empty)
        questions.append({
            "text": (
                "필수 조건의 해석 또는 상품 Map 확인이 필요합니다. 조건을 유지하거나 직접 조정하거나 탐색을 종료할 수 있습니다."
                if blocked else "필수 조건을 충족하는 상품이 없습니다. 조건을 유지하거나 직접 조정하거나 탐색을 종료할 수 있습니다."),
            "target_id": empty[0] if len(empty) == 1 else None,
            "subject_refs": [], "options": list(_NO_RESULTS_OPTIONS),
        })
    for tid in available:
        entries, axes, reduced = _select(pools[tid], targets[tid], allocations[tid], mode)
        start = len(selected)
        selected.extend((tid, entry) for entry in entries)
        for feature in axes:
            path = {"domain": "PI", "feature": feature}
            if path not in compared:
                compared.append(path)
        if axes and len(questions) < 3:
            differences = []
            for index, entry in enumerate(entries, start + 1):
                values = ", ".join(f"{axis}={'/'.join(_value(entry, axis))}" for axis in axes)
                differences.append(f"후보 {index}: {values}")
            prefix = "두 축의 네 조합을 확보하지 못해 비교 축을 줄였습니다. " if reduced else ""
            questions.append({"text": prefix + "; ".join(differences) + ". 가까운 후보나 원하는 차이를 알려주세요.",
                              "target_id": tid, "subject_refs": [], "options": ["후보 선택", "텍스트로 보완", "모르겠음"]})
    for question in target_map["questions"]:
        if len(questions) < 3:
            questions.append({"text": question, "target_id": None, "subject_refs": [], "options": []})
    # Bind identity to the generation basis as well as the product/image. A retry
    # in the same context is stable; a changed request/map/image gets a new ID.
    seed = {"basis": basis, "constraints": target_map["constraints"], "targets": target_map["targets"],
            "mode": mode, "size": count, "compared_features": compared}
    cards = []
    for position, (tid, entry) in enumerate(selected, 1):
        image = entry["image"]
        image_id = image["image_id"] if image is not None else None
        card = {"target_id": tid, "product_id": entry["hit"]["product_id"],
                "product_map_version": entry["hit"]["product_map_version"],
                "image_id": image_id,
                "image_version": image_versions[image_id]["version"] if image_id is not None else None,
                "position": position}
        digest = hashlib.sha256(canonical({"generation": seed, "card": card}).encode("utf-8")).hexdigest()
        cards.append({"candidate_id": "candidate-" + digest[:32], **card})
    _check_catalog(catalog, current)
    return {"cards": cards, "compared_features": compared, "questions": questions, "basis": basis}
