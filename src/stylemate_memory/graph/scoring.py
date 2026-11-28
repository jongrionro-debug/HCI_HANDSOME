"""Per-value Beta scores, contrast-only attribution and exclusions (ADR 0013 decision 8).

Scores live only in this request's graph state; nothing here writes memory.
The update sizes are pilot assumptions (decision 15), not tuned values.
"""

from __future__ import annotations

import math
import random
from typing import Any

PRIOR = (1.0, 1.0)
SELECT_GAIN = 1.0
MISS_PENALTY = 0.3
REASON_GAIN = 2.0
CONFIRM_GAIN = 3.0  # L3: a confirmed interpretation (2-feedback.md 3절, 가정)
MISS_STREAK_LIMIT = 3
DISLIKE_HIDE = 2
CHIP_MEAN = 0.6
CHIP_UPDATES = 2
IMAGE_BLIND_AXES = ("Fabric",)  # not verifiable from a photo


def delta_e2000(lab1: tuple[float, ...] | list[float], lab2: tuple[float, ...] | list[float]) -> float:
    """CIEDE2000 colour difference (Sharma, Wu & Dalal 2005), same formula as scripts/build_lumi_pi_v3.py."""
    l1, a1, b1 = lab1
    l2, a2, b2 = lab2
    c1, c2 = math.hypot(a1, b1), math.hypot(a2, b2)
    cbar7 = ((c1 + c2) / 2) ** 7
    g = 0.5 * (1 - math.sqrt(cbar7 / (cbar7 + 25 ** 7)))
    a1p, a2p = (1 + g) * a1, (1 + g) * a2
    c1p, c2p = math.hypot(a1p, b1), math.hypot(a2p, b2)
    h1p = math.degrees(math.atan2(b1, a1p)) % 360 if c1p else 0.0
    h2p = math.degrees(math.atan2(b2, a2p)) % 360 if c2p else 0.0
    dlp, dcp = l2 - l1, c2p - c1p
    if c1p * c2p == 0:
        dhp = 0.0
    elif abs(h2p - h1p) <= 180:
        dhp = h2p - h1p
    else:
        dhp = h2p - h1p - 360 if h2p > h1p else h2p - h1p + 360
    dhp_big = 2 * math.sqrt(c1p * c2p) * math.sin(math.radians(dhp / 2))
    lbar, cbarp = (l1 + l2) / 2, (c1p + c2p) / 2
    if c1p * c2p == 0:
        hbarp = h1p + h2p
    elif abs(h1p - h2p) <= 180:
        hbarp = (h1p + h2p) / 2
    else:
        hbarp = (h1p + h2p + 360) / 2 if h1p + h2p < 360 else (h1p + h2p - 360) / 2
    t = (1 - 0.17 * math.cos(math.radians(hbarp - 30)) + 0.24 * math.cos(math.radians(2 * hbarp))
         + 0.32 * math.cos(math.radians(3 * hbarp + 6)) - 0.20 * math.cos(math.radians(4 * hbarp - 63)))
    sl = 1 + 0.015 * (lbar - 50) ** 2 / math.sqrt(20 + (lbar - 50) ** 2)
    sc, sh = 1 + 0.045 * cbarp, 1 + 0.015 * cbarp * t
    cbarp7 = cbarp ** 7
    rt = (-2 * math.sqrt(cbarp7 / (cbarp7 + 25 ** 7))
          * math.sin(math.radians(60 * math.exp(-(((hbarp - 275) / 25) ** 2)))))
    return math.sqrt((dlp / sl) ** 2 + (dcp / sc) ** 2 + (dhp_big / sh) ** 2 + rt * (dcp / sc) * (dhp_big / sh))


def score_key(target_id: str, scope: str, axis: str, value: str) -> str:
    return "|".join((target_id, scope, axis, value))


def split_key(key: str) -> tuple[str, str, str, str]:
    target_id, scope, axis, value = key.split("|", 3)
    return target_id, scope, axis, value


def get(scores: dict[str, Any], key: str) -> dict[str, Any]:
    return scores.get(key) or {"a": PRIOR[0], "b": PRIOR[1], "n": 0}


def mean(entry: dict[str, Any]) -> float:
    return entry["a"] / (entry["a"] + entry["b"])


def sample(entry: dict[str, Any], rng: random.Random) -> float:
    return rng.betavariate(entry["a"], entry["b"])


def active_values(hypotheses: list[dict[str, Any]], excluded: list[str], scope: str) -> dict[str, dict[str, set[str]]]:
    """target -> axis -> values in the exploration space minus exclusions."""
    space: dict[str, dict[str, set[str]]] = {}
    for h in hypotheses:
        for value in h["values"]:
            if score_key(h["target_id"], scope, h["axis"], value) in excluded:
                continue
            space.setdefault(h["target_id"], {}).setdefault(h["axis"], set()).add(value)
    return space


def attribute_grid(state: dict[str, Any], cards: list[dict[str, Any]], selected: set[str], scope: str,
                   extra: dict[str, dict[str, set[str]]] | None = None) -> list[str]:
    """Update scores only where a selected/unselected value difference is confirmed.

    Values present on both sides are neutral. All-selected, none-selected or an
    unknown opposite side changes no value score (product ranking only).
    Returns the score keys that changed.
    """
    changed: list[str] = []
    space = active_values(state["hypotheses"], state["excluded"], scope)
    for target_id, axes in (extra or {}).items():  # ADR 0015: consented-memory values are contrasted too
        for axis, values in axes.items():
            kept = {v for v in values if score_key(target_id, scope, axis, v) not in state["excluded"]}
            space.setdefault(target_id, {}).setdefault(axis, set()).update(kept)
    for target_id, axes in space.items():
        shown = [c for c in cards if c["target_id"] == target_id]
        chosen = [c for c in shown if c["candidate_id"] in selected]
        rest = [c for c in shown if c["candidate_id"] not in selected]
        for axis, values in axes.items():
            if axis in IMAGE_BLIND_AXES:
                continue
            for value in values:
                key = score_key(target_id, scope, axis, value)
                exposed = any(value in (c["facts"].get(axis) or []) for c in shown)
                if exposed:
                    state["exposures"][key] = state["exposures"].get(key, 0) + 1
                if not chosen or not rest:
                    continue
                known_chosen = all(c["facts"].get(axis) for c in chosen)
                known_rest = all(c["facts"].get(axis) for c in rest)
                in_chosen = any(value in (c["facts"].get(axis) or []) for c in chosen)
                in_rest = any(value in (c["facts"].get(axis) or []) for c in rest)
                entry = get(state["scores"], key)
                if in_chosen and not in_rest and known_rest:
                    entry = {"a": entry["a"] + SELECT_GAIN, "b": entry["b"], "n": entry["n"] + 1}
                    state["miss_streak"][key] = 0
                elif in_rest and not in_chosen and known_chosen:
                    entry = {"a": entry["a"], "b": entry["b"] + MISS_PENALTY, "n": entry["n"] + 1}
                    streak = state["miss_streak"].get(key, 0) + 1
                    state["miss_streak"][key] = streak
                    if streak >= MISS_STREAK_LIMIT and key not in state["excluded"]:
                        state["excluded"].append(key)
                else:
                    continue
                state["scores"][key] = entry
                changed.append(key)
    return changed


def apply_reason_axis(state: dict[str, Any], cards: list[dict[str, Any]], selected: set[str], axis: str, scope: str) -> list[str]:
    """The user said which axis they liked: credit only that axis (Fabric allowed)."""
    changed = []
    for card in cards:
        if card["candidate_id"] not in selected:
            continue
        for value in card["facts"].get(axis) or []:
            key = score_key(card["target_id"], scope, axis, value)
            entry = get(state["scores"], key)
            state["scores"][key] = {"a": entry["a"] + REASON_GAIN, "b": entry["b"], "n": entry["n"] + 1}
            state["miss_streak"][key] = 0
            changed.append(key)
    return changed


def apply_dislikes(state: dict[str, Any], product_ids: list[str], turn: int) -> list[str]:
    """Count "별로" per product per distinct exposure; hide at DISLIKE_HIDE. No value change."""
    hidden = []
    for pid in product_ids:
        turns = state["dislikes"].setdefault(pid, [])
        if turn not in turns:
            turns.append(turn)
        if len(turns) >= DISLIKE_HIDE and pid not in state["hidden"]:
            state["hidden"].append(pid)
            hidden.append(pid)
    return hidden


def chips(state: dict[str, Any], scope: str, labels: dict[str, str]) -> list[dict[str, Any]]:
    """Understanding chips: pinned and confirmed (L3) values plus values whose score clearly rose."""
    result = []
    pinned = {p["key"] for p in state["pinned"]}
    confirmed = set(state.get("confirmed", []))
    for key, entry in sorted(state["scores"].items()):
        target_id, key_scope, axis, value = split_key(key)
        if key_scope != scope or key in state["excluded"]:
            continue
        if key in pinned or key in confirmed or (entry["n"] >= CHIP_UPDATES and mean(entry) >= CHIP_MEAN):
            result.append({"key": key, "target_id": target_id, "feature": axis, "label_ko": labels.get(axis, axis),
                           "value": value, "pinned": key in pinned, "confirmed": key in confirmed,
                           "mean": round(mean(entry), 3)})
    for pin in state["pinned"]:
        if not any(c["key"] == pin["key"] for c in result):
            target_id, _, axis, value = split_key(pin["key"])
            result.append({"key": pin["key"], "target_id": target_id, "feature": axis, "label_ko": labels.get(axis, axis),
                           "value": value, "pinned": True, "confirmed": False, "mean": None})
    return result
