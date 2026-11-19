"""8-image grid planner (ADR 0013 decisions 6 and 8): converge · explore · control.

Pure function over product views and request graph state. It never runs a
model, writes storage, or treats an unknown PI as a negative case.
"""

from __future__ import annotations

import random
from typing import Any

from . import scoring

GRID_SIZE = 8
MAX_FOCUS_AXES = 2


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
    for product in products:
        if product["target_id"] != target_id or not product["image_id"]:
            continue
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
    converge_n = min(6, 2 * max(1, turn))
    if intent.get("all_bad"):
        converge_n = max(0, converge_n - 4)
    if not space:
        converge_n = size
    samples = {}
    for axis, values in space.items():
        for value in values:
            key = scoring.score_key(target_id, scope, axis, value)
            samples[(axis, value)] = scoring.sample(scoring.get(intent["scores"], key), rng)

    def converge_score(product: dict[str, Any]) -> float:
        total = _soft(product, intent, target_id) + 0.5 * _similar(product, anchor)
        for (axis, value), drawn in samples.items():
            if _has(product, axis, value):
                total += drawn
        return total + rng.random() * 1e-6

    chosen: list[tuple[str, dict[str, Any]]] = []
    used: set[str] = set()

    def take(slot: str, product: dict[str, Any]) -> None:
        chosen.append((slot, product))
        used.add(product["product_id"])

    for product in sorted(pool, key=converge_score, reverse=True):
        if len(chosen) >= min(converge_n, size):
            break
        take("converge", product)
    # Focus at most MAX_FOCUS_AXES axes this turn: the most uncertain ones.
    def uncertainty(axis: str) -> float:
        return sum(1.0 / (1 + intent["exposures"].get(scoring.score_key(target_id, scope, axis, v), 0)) for v in space[axis])
    focus = sorted(space, key=lambda a: (-uncertainty(a), a))[:MAX_FOCUS_AXES]
    focus_values = [(a, v) for a in focus for v in sorted(space[a])]
    control_needed = bool(focus_values) and len(chosen) < size
    explore_budget = size - len(chosen) - (1 if control_needed else 0)
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
    # Any remaining room: best remaining eligible products (still distinct).
    for product in sorted(pool, key=converge_score, reverse=True):
        if len(chosen) >= size:
            break
        if product["product_id"] not in used:
            take("explore" if space else "converge", product)
    exposures = [{"axis": a, "value": v} for a, v in focus_values]
    return chosen, exposures


def plan_grid(products: list[dict[str, Any]], targets: list[dict[str, Any]], intent: dict[str, Any], scope: str,
              turn: int, seed: str, anchor: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return {status, cards, exposures, pool_sizes, shortage}.

    status: results | no_results (conditions) | hidden_empty (hiding emptied the pool).
    """
    rng = random.Random(seed)
    quotas = {t["target_id"]: GRID_SIZE // len(targets) for t in targets}
    for t in targets[:GRID_SIZE % len(targets)]:
        quotas[t["target_id"]] += 1
    cards, exposures, pool_sizes, status = [], {}, {}, "results"
    hidden_only = True
    for target in targets:
        tid = target["target_id"]
        pool, hidden = eligible(products, tid, intent, scope)
        pool_sizes[tid] = len(pool)
        if not pool:
            if not hidden:
                hidden_only = False
            continue
        hidden_only = False
        picked, focus = plan_target(pool, tid, intent, scope, quotas[tid], turn, rng,
                                    anchor if anchor and anchor["target_id"] == tid else None)
        exposures[tid] = focus
        for slot, product in picked:
            cards.append({"slot": slot, **product})
    if not cards:
        status = "hidden_empty" if hidden_only and any(eligible(products, t["target_id"], intent, scope)[1] for t in targets) else "no_results"
    shortage = any(size < quotas[tid] for tid, size in pool_sizes.items())
    return {"status": status, "cards": cards, "exposures": exposures, "pool_sizes": pool_sizes, "shortage": shortage}


def converged(history: list[list[str]], shortage: bool) -> bool:
    """Top products identical for 2 consecutive turns, and not merely a short pool."""
    if shortage or len(history) < 3:
        return False
    return set(history[-1]) == set(history[-2]) == set(history[-3]) and bool(history[-1])
