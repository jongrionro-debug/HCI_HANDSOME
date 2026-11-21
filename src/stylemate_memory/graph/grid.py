"""8-image grid planner (ADR 0013 decisions 6 and 8): converge · explore · control.

Pure function over product views and request graph state. It never runs a
model, writes storage, or treats an unknown PI as a negative case.
"""

from __future__ import annotations

import random
from typing import Any

from . import memory, scoring

GRID_SIZE = 8
MAX_FOCUS_AXES = 2
MAX_KEPT = 4  # previously picked products shown first; the rest of the 8 stay new
MAX_SHORTLIST = 24  # F8: every pick of the request; the comparison grid shows the latest GRID_SIZE
MAX_PICK_HISTORY = 80  # F11: picked cards' facts for chip evidence
MUST_PRIOR = 2.0  # F5: extra Beta pseudo count for values hypothesized from a "꼭" FEA need (pilot assumption)


def _has(product: dict[str, Any], axis: str, value: str) -> bool:
    return value in (product["facts"].get(axis) or [])


def price_ok(product: dict[str, Any], price: dict[str, Any]) -> bool:
    amount = product.get("price")
    if amount is None:
        return False  # a hard numeric limit needs a known price
    op, low, high = price["op"], price["min_krw"], price["max_krw"]
    return {"lte": lambda: amount <= high, "lt": lambda: amount < high, "gte": lambda: amount >= low,
            "gt": lambda: amount > low, "range": lambda: low <= amount <= high}[op]()


def eligible(products: list[dict[str, Any]], target_id: str, intent: dict[str, Any], scope: str) -> tuple[list[dict[str, Any]], int]:
    """Hard filters: direct hard PI, pinned chips, numeric price. Returns (pool, hidden_count)."""
    hard = [h for h in intent["hard"] if h["target_id"] in (None, target_id)]
    pins = [scoring.split_key(p["key"]) for p in intent["pinned"]]
    pool, hidden = [], 0
    gender = intent.get("gender")
    for product in products:
        if product["target_id"] != target_id or not product["image_id"]:
            continue
        if gender and product.get("gender") != gender:
            continue  # ADR 0015: an unknown gender only shows under "전체"
        ok = True
        for h in hard:
            if h["kind"] == "price":
                ok = ok and price_ok(product, h["price"])
                continue
            values = set(product["facts"].get(h["feature"]) or [])
            if h["polarity"] == "avoid":
                ok = ok and not (values & set(h["values"]))
            elif h["match"] == "all":
                ok = ok and set(h["values"]) <= values
            else:
                ok = ok and bool(values & set(h["values"]))
        for t, _, axis, value in pins:
            if t == target_id:
                ok = ok and _has(product, axis, value)
        if not ok:
            continue
        if product["product_id"] in intent["hidden"]:
            hidden += 1
            continue
        pool.append(product)
    return pool, hidden


def _soft(product: dict[str, Any], intent: dict[str, Any], target_id: str) -> float:
    total = 0.0
    for s in intent["soft"]:
        if s["target_id"] not in (None, target_id):
            continue
        hit = bool(set(product["facts"].get(s["feature"]) or []) & set(s["values"]))
        total += (1.0 if s["polarity"] == "prefer" else -1.0) if hit else 0.0
    return total


def _similar(product: dict[str, Any], anchor: dict[str, Any] | None) -> float:
    if not anchor or anchor["product_id"] == product["product_id"]:
        return 0.0
    return sum(len(set(product["facts"].get(a) or []) & set(anchor["facts"].get(a) or [])) for a in anchor["facts"])


def plan_target(pool: list[dict[str, Any]], target_id: str, intent: dict[str, Any], scope: str, size: int,
                turn: int, rng: random.Random, anchor: dict[str, Any] | None) -> tuple[list[tuple[str, dict[str, Any]]], list[dict[str, str]]]:
    """Return [(slot, product)] and the focused (axis, value) exposures of this turn."""
    space = scoring.active_values(intent["hypotheses"], intent["excluded"], scope).get(target_id, {})
    # ADR 0015: consented-memory values join the exploration space as Beta priors.
    for axis, values in memory.prior_values(intent, target_id).items():
        kept = {v for v in values if scoring.score_key(target_id, scope, axis, v) not in intent["excluded"]}
        if kept:
            space = {**space, axis: set(space.get(axis, set())) | kept}
    novel_n = min(memory.novel_slots(intent, target_id), max(0, size - 1))
    main_size = size - novel_n
    converge_n = min(6, 2 * max(1, turn))
    if intent.get("all_bad"):
        converge_n = max(0, converge_n - 4)
    if not space:
        converge_n = main_size
    samples, plain = {}, {}
    musts = must_values(intent)
    for axis, values in sorted(space.items()):
        for value in sorted(values):
            key = scoring.score_key(target_id, scope, axis, value)
            entry = memory.effective(intent, key)
            if (target_id, axis, value) in musts:
                entry = entry | {"a": entry["a"] + MUST_PRIOR}
            samples[(axis, value)] = scoring.sample(entry, rng)
            plain[(axis, value)] = scoring.sample(scoring.get(intent["scores"], key), rng)

    def converge_score(product: dict[str, Any]) -> float:
        total = _soft(product, intent, target_id) + 0.5 * _similar(product, anchor)
        for (axis, value), drawn in samples.items():
            if _has(product, axis, value):
                total += drawn
        return total + rng.random() * 1e-6

    def novel_score(product: dict[str, Any]) -> float:
        # Memory-free ranking; products without a memory-preferred value come first.
        total = _soft(product, intent, target_id) - (10.0 if memory.preferred_by_memory(intent, product) else 0.0)
        for (axis, value), drawn in plain.items():
            if _has(product, axis, value):
                total += drawn
        return total + rng.random() * 1e-6

    chosen: list[tuple[str, dict[str, Any]]] = []
    used: set[str] = set()

    def take(slot: str, product: dict[str, Any]) -> None:
        chosen.append((slot, product))
        used.add(product["product_id"])

    for product in sorted(pool, key=converge_score, reverse=True):
        if len(chosen) >= min(converge_n, main_size):
            break
        take("converge", product)
    # Focus at most MAX_FOCUS_AXES axes this turn: the most uncertain ones.
    def uncertainty(axis: str) -> float:
        return sum(1.0 / (1 + intent["exposures"].get(scoring.score_key(target_id, scope, axis, v), 0)) for v in space[axis])
    focus = sorted(space, key=lambda a: (-uncertainty(a), a))[:MAX_FOCUS_AXES]
    focus_values = [(a, v) for a in focus for v in sorted(space[a])]
    control_needed = bool(focus_values) and len(chosen) < main_size
    explore_budget = main_size - len(chosen) - (1 if control_needed else 0)
    by_exposure = sorted(focus_values, key=lambda av: (intent["exposures"].get(scoring.score_key(target_id, scope, *av), 0), av))
    progress = True
    while explore_budget > 0 and progress:
        progress = False
        for axis, value in by_exposure:
            if explore_budget <= 0:
                break
            options = [p for p in pool if p["product_id"] not in used and _has(p, axis, value)]
            if options:
                take("explore", max(options, key=converge_score))
                explore_budget -= 1
                progress = True
    if control_needed:
        # Control = this turn's focused values confirmed absent (known axis value).
        controls = [p for p in pool if p["product_id"] not in used
                    and all(p["facts"].get(axis) for axis in focus)
                    and not any(_has(p, axis, value) for axis, value in focus_values)]
        if controls:
            take("control", max(controls, key=converge_score))
    # Novelty slots: picked without memory priors (ADR 0015 decision 5).
    for product in sorted((p for p in pool if p["product_id"] not in used), key=novel_score, reverse=True)[:novel_n]:
        take("novel", product)
    # Any remaining room: best remaining eligible products (still distinct).
    for product in sorted(pool, key=converge_score, reverse=True):
        if len(chosen) >= size:
            break
        if product["product_id"] not in used:
            take("explore" if space else "converge", product)
    exposures = [{"axis": a, "value": v} for a, v in focus_values]
    return chosen, exposures


def must_values(intent: dict[str, Any]) -> set[tuple[str, str, str]]:
    """F5: (target, axis, value) hypothesized from a hard FEA need. Soft boost only, never a filter."""
    hard = {n["key"] for n in intent["fea_needs"] if n["strength"] == "hard"}
    return {(h["target_id"], h["axis"], v) for h in intent["hypotheses"] if set(h["fea_keys"]) & hard for v in h["values"]}


def shortlist_grid(products: list[dict[str, Any]], intent: dict[str, Any]) -> dict[str, Any]:
    """F8: the latest shortlist picks side by side, published as a normal candidate set so the
    existing select_final contract (final = a displayed candidate) applies unchanged."""
    by_key = {(p["product_id"], p["target_id"]): p for p in products if p["image_id"]}
    found = [by_key.get((s["product_id"], s["target_id"])) for s in intent.get("shortlist", [])]
    cards = [{"slot": "shortlist", **p} for p in found if p][-GRID_SIZE:]
    return {"status": "results" if cards else "no_results", "cards": cards, "exposures": {},
            "pool_sizes": {}, "shortage": False, "compare": True}


def kept_products(products: list[dict[str, Any]], intent: dict[str, Any]) -> list[dict[str, Any]]:
    """Products the user kept selected, in pick order (still in the catalog view)."""
    by_key = {(p["product_id"], p["target_id"]): p for p in products if p["image_id"]}
    found = [by_key.get((k["product_id"], k["target_id"])) for k in intent.get("kept", [])]
    return [p for p in found if p][:MAX_KEPT]


def plan_grid(products: list[dict[str, Any]], targets: list[dict[str, Any]], intent: dict[str, Any], scope: str,
              turn: int, seed: str, anchor: dict[str, Any] | None = None,
              kept: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return {status, cards, exposures, pool_sizes, shortage}.

    Kept products (earlier picks) come first with slot "kept" and fill part of
    the 8; the remaining slots are planned as new candidates.
    status: results | no_results (conditions) | hidden_empty (hiding emptied the pool).
    """
    rng = random.Random(seed)
    kept_cards = [{"slot": "kept", **p} for p in (kept or [])[:MAX_KEPT]]
    kept_ids = {p["product_id"] for p in kept_cards}
    room = GRID_SIZE - len(kept_cards)
    quotas = {t["target_id"]: room // len(targets) for t in targets}
    for t in targets[:room % len(targets)]:
        quotas[t["target_id"]] += 1
    cards, exposures, pool_sizes, status = [], {}, {}, "results"
    hidden_only = True
    for target in targets:
        tid = target["target_id"]
        pool, hidden = eligible(products, tid, intent, scope)
        pool = [p for p in pool if p["product_id"] not in kept_ids]
        pool_sizes[tid] = len(pool)
        if not pool:
            if not hidden:
                hidden_only = False
            continue
        hidden_only = False
        if quotas[tid] <= 0:
            continue
        picked, focus = plan_target(pool, tid, intent, scope, quotas[tid], turn, rng,
                                    anchor if anchor and anchor["target_id"] == tid else None)
        exposures[tid] = focus
        for slot, product in picked:
            cards.append({"slot": slot, **product})
    if not cards and not kept_cards:
        status = "hidden_empty" if hidden_only and any(eligible(products, t["target_id"], intent, scope)[1] for t in targets) else "no_results"
    shortage = any(size < quotas[tid] for tid, size in pool_sizes.items())
    return {"status": status, "cards": kept_cards + cards, "exposures": exposures,
            "pool_sizes": pool_sizes, "shortage": shortage}


def converged(history: list[list[str]], shortage: bool) -> bool:
    """Top products identical for 2 consecutive turns, and not merely a short pool."""
    if shortage or len(history) < 3:
        return False
    return set(history[-1]) == set(history[-2]) == set(history[-3]) and bool(history[-1])
