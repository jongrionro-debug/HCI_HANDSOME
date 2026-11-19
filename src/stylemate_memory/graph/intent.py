"""IntentState: the request-local working state of the graph engine (ADR 0013 decision 3).

It is JSON-serializable and lives in the LangGraph checkpointer. The memory
SQLite store stays the source of truth for memories, consent and deletion.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .situations import matchable


def new_intent(request_id: str, targets: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "request_id": request_id, "targets": targets, "turn": 0, "situations": [], "wishes": [], "held": [],
        "hard": [], "soft": [], "fea_needs": [], "fea_signature": "", "hypotheses": [], "scores": {},
        "exposures": {}, "miss_streak": {}, "excluded": [], "pinned": [], "hidden": [], "dislikes": {},
        "questions": [], "warnings": [], "processed": [], "last_grid": None, "top_history": [],
        "all_bad": False, "anchor": None, "reason_prompt": None, "outcome": "idle", "converged": False,
        "event": None, "pending_error": None, "unresolved_hard_fea": False, "route_question": None,
        "pool_sizes": {}, "shortage": False,
    }


def scope_of(intent: dict[str, Any]) -> str:
    """Score scope = normalized request situations; a corrected situation starts a new scope."""
    parts = sorted(f"{s['key']}={s['value']}" for s in intent["situations"] if matchable(s))
    return ",".join(parts) or "request"


def merge_parse(intent: dict[str, Any], parsed: dict[str, Any], turn_tag: str) -> None:
    """Add this turn's valid items. A new single situation of a known key replaces it."""
    new = parsed["situations"]
    counts: dict[str, int] = {}
    for s in new:
        counts[s["key"]] = counts.get(s["key"], 0) + 1
    replaced = {k for k, n in counts.items() if n == 1}
    intent["situations"] = [s for s in intent["situations"] if s["key"] not in replaced] + [dict(s) for s in new]
    for wish in parsed["wishes"]:
        intent["wishes"].append(dict(wish) | {"key": f"{turn_tag}-{wish['key']}"})
    intent["held"] += [dict(w) | {"key": f"{turn_tag}-{w['key']}"} for w in parsed["held"]]
    for q in parsed["questions"]:
        intent["questions"].append({"text": q["text"], "reason": q["reason"], "origin": "model"})
    intent["warnings"] = (intent["warnings"] + parsed["warnings"])[-50:]
    derive(intent)


def derive(intent: dict[str, Any]) -> None:
    """Rebuild hard/soft constraints and FEA needs from the accumulated wishes."""
    hard, soft, needs = [], [], []
    for wish in intent["wishes"]:
        target_id = wish["target_id"]
        for binding in wish["pi"]:
            entry = {"kind": "pi", "target_id": target_id, "feature": binding["feature"], "values": list(binding["values"]),
                     "match": binding["match"], "polarity": wish["polarity"], "source": wish["key"]}
            if wish["polarity"] == "indifferent":
                continue
            # Explicit hard wording, and an explicitly named Type, are hard (decision 5).
            if wish["origin"] == "explicit" and (wish["strength"] == "hard" or (binding["feature"] == "Type" and wish["polarity"] == "prefer")):
                hard.append(entry)
            else:
                soft.append(entry)
        if wish["price"] is not None:
            hard.append({"kind": "price", "target_id": target_id, "price": dict(wish["price"]), "source": wish["key"]})
        if wish["fea"] and wish["polarity"] == "prefer":
            needs.append({"key": wish["key"], "target_id": target_id, "fea": [dict(f) for f in wish["fea"]],
                          "quote": wish["quote"], "content": wish["content"], "strength": wish["strength"]})
    intent["hard"], intent["soft"], intent["fea_needs"] = hard, soft, needs
    intent["unresolved_hard_fea"] = any(n["strength"] == "hard" for n in needs)


def fea_signature(intent: dict[str, Any]) -> str:
    body = sorted(json.dumps({"t": n["target_id"], "f": n["fea"]}, sort_keys=True, ensure_ascii=False) for n in intent["fea_needs"])
    return hashlib.sha256("\n".join(body).encode()).hexdigest()


def fixed_axes(intent: dict[str, Any]) -> dict[str, list[str]]:
    """Axes the user specified directly: no hypothesis may fill them."""
    result: dict[str, list[str]] = {}
    for target in intent["targets"]:
        tid = target["target_id"]
        axes = set()
        for wish in intent["wishes"]:
            if wish["target_id"] in (None, tid) and wish["polarity"] in ("prefer", "indifferent"):
                axes |= {b["feature"] for b in wish["pi"]}
        result[tid] = sorted(axes)
    return result


def hard_conflict(intent: dict[str, Any]) -> str | None:
    """Return a Korean question when hard conditions cannot hold together."""
    by: dict[tuple[Any, str], list[dict[str, Any]]] = {}
    for h in intent["hard"]:
        if h["kind"] == "pi":
            by.setdefault((h["target_id"], h["feature"]), []).append(h)
    for (target_id, feature), items in by.items():
        wanted = [set(h["values"]) for h in items if h["polarity"] == "prefer"]
        avoided = set().union(*[set(h["values"]) for h in items if h["polarity"] == "avoid"]) if items else set()
        if any(w and w <= avoided for w in wanted):
            return f"{feature} 조건이 서로 맞지 않아요. 원하는 쪽을 알려주세요."
        if len(wanted) > 1 and not set.intersection(*wanted):
            return f"{feature}에 꼭 필요한 값이 서로 달라요. 어느 쪽으로 찾을까요?"
    return None


def route(intent: dict[str, Any]) -> str:
    """Code rule (decision 6): hard conflict or no target -> question, else grid."""
    if not intent["targets"]:
        return "ask_clarify"
    if hard_conflict(intent):
        return "ask_clarify"
    return "retrieve"
