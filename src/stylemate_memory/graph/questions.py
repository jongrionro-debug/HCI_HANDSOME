"""Question loop seam for the three question-design parts (research/question-design, Issues: modes / answers / policy).

One turn of the loop, all in code except where a part later adds a model call:

    candidates()  -> what could we ask?             (③ policy: which gaps, in what order, when to stop)
    allowed()     -> which modes can ask it now?    (① modes: feasibility per mode, from the catalog)
    choose()      -> which mode, decided by whom?   (③ policy: rule table, later LLM within allowed)
    build()       -> the question shown to the user (① modes: prompt, options, images)
    interpret()   -> what the answer changes        (② answers: scores, pins, nothing)

Contract shapes are plain dicts so they survive LangGraph checkpoints:

    Candidate  {"id", "target_id", "axis", "kind", "values"}
    Decision   {"candidate_id", "mode", "decided_by": "rule"|"llm"|"user", "reason", "allowed"}
    Question   {"question_id", "mode", "target_id", "axis", "prompt", "multi", "options": [Option],
                "allow": ["unsure", "skip", ...], "switch_to": [mode]}
    Option     {"id", "label", "value", "product_id"?, "image_id"?, "image_version"?}
    Answer     {"question_id", "choice": "options"|"neither"|"unsure"|"skip"|"switch", "option_ids", "switch_to"}

v0 implements only ``text_options`` end to end. The other modes are registered with ``build=None`` so
``allowed()`` drops them and the loop falls back to text. Each part replaces its functions here (or in a
module it adds) without changing the shapes; a shape change needs all three parts to agree.
The loop is off unless STYLEMATE_QUESTION_LOOP=on, so the current grid flow is unchanged until it is switched on.
"""

from __future__ import annotations

import os
from collections import Counter
from typing import Any, Callable

from . import scoring
from .labels import value_label

MODE_NAMES = ("text_options", "select_images", "contrast_pair", "explain_images", "propose_compare")
ANSWER_CHOICES = ("options", "neither", "unsure", "skip", "switch")
SKIP_AXES = ("Brand",)  # metadata only (ADR 0016)
MAX_OPTIONS = 4
MAX_CANDIDATES = 3
ASK_GAP = 2  # turns between two loop questions (③ decides the real rule)
LOG_LIMIT = 100

# ③ policy v0: default mode per axis (research/question-design/3-mapping.md "PI 축별 기본 방식").
DEFAULT_MODE = {"Type": "text_options", "Color": "text_options", "Tone": "select_images", "Pattern": "select_images",
                "Fit": "select_images", "Silhouette": "select_images", "Length": "select_images",
                "Weight": "text_options", "Texture": "explain_images", "Fabric": "text_options",
                "Detail": "select_images", "Style": "select_images"}


def loop_enabled() -> bool:
    return os.environ.get("STYLEMATE_QUESTION_LOOP", "off").strip().lower() == "on"


# ---- ③ policy: candidates and mode choice ----------------------------------------------------------

def candidates(intent: dict[str, Any], pools: dict[str, list[dict[str, Any]]], fixed: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Axes still open for a target whose eligible pool really differs on them. Registry order is kept by the caller."""
    asked = {(a["target_id"], a["axis"]) for a in intent.get("asked", [])}
    result = []
    for target in intent["targets"]:
        tid = target["target_id"]
        pool = pools.get(tid, [])
        axes: list[str] = []
        for product in pool:
            axes += [a for a in product["facts"] if a not in axes]
        for axis in axes:
            if axis in SKIP_AXES or (tid, axis) in asked or axis in fixed.get(tid, []):
                continue
            counts = Counter(v for p in pool for v in p["facts"].get(axis) or [])
            if len(counts) < 2:
                continue
            result.append({"id": f"{tid}:{axis}", "target_id": tid, "axis": axis, "kind": "gap",
                           "values": [v for v, _ in counts.most_common()]})
    return result[:MAX_CANDIDATES]


def should_ask(intent: dict[str, Any]) -> bool:
    if intent.get("ask") or intent.get("route_question") or intent.get("reason_prompt") or intent.get("compare_mode"):
        return False
    if intent.get("novelty_prompt") == "ask" or intent.get("taste_prompt"):
        return False
    last = max((a["turn"] for a in intent.get("asked", [])), default=None)
    return last is None or intent["turn"] - last >= ASK_GAP


def choose(candidate: dict[str, Any], allowed: list[str], intent: dict[str, Any]) -> dict[str, Any]:
    preferred = DEFAULT_MODE.get(candidate["axis"], "text_options")
    mode = preferred if preferred in allowed else allowed[0]
    reason = "default" if mode == preferred else f"fallback:{preferred}"
    return {"candidate_id": candidate["id"], "mode": mode, "decided_by": "rule", "reason": reason, "allowed": list(allowed)}


# ---- ① modes: feasibility and question building ------------------------------------------------------

def _text_options(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    values = candidate["values"][:MAX_OPTIONS]
    if len(values) < 2:
        return None
    label = labels.get(candidate["axis"], candidate["axis"])
    return {"prompt": f"{label}은(는) 어떤 쪽이 좋으세요?", "multi": False,
            "options": [{"id": f"o{i}", "label": value_label(candidate["axis"], v), "value": v} for i, v in enumerate(values)],
            "allow": ["unsure", "skip"]}


Builder = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, str]], "dict[str, Any] | None"]
MODES: dict[str, dict[str, Any]] = {
    "text_options": {"build": _text_options},
    "select_images": {"build": None},    # ① Issue: N images whose values differ on the axis
    "contrast_pair": {"build": None},    # ① Issue: two products differing only on the axis
    "explain_images": {"build": None},   # ① Issue: one representative image per value
    "propose_compare": {"build": None},  # ①/③ Issue: hand over to the shortlist comparison
}


def allowed(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    built: dict[str, dict[str, Any]] = {}
    for name in MODE_NAMES:
        build = MODES[name]["build"]
        question = build(candidate, pool, labels) if build else None
        if question:
            built[name] = question
    return list(built), built


# ---- loop ----------------------------------------------------------------------------------------------

def plan(intent: dict[str, Any], pools: dict[str, list[dict[str, Any]]], fixed: dict[str, list[str]],
         labels: dict[str, str]) -> dict[str, Any] | None:
    """Pick at most one question for this turn and log every decision (3-mapping.md: 결정 로그)."""
    if not should_ask(intent):
        return None
    for candidate in candidates(intent, pools, fixed):
        modes, built = allowed(candidate, pools.get(candidate["target_id"], []), labels)
        if not modes:
            continue
        decision = choose(candidate, modes, intent)
        if decision["mode"] not in modes:  # a policy outside the allowed list is discarded (3-mapping.md)
            decision = {**decision, "mode": modes[0], "reason": "rejected_choice", "decided_by": "rule"}
        question = {"question_id": f"q{intent['turn']}-{candidate['id']}", "mode": decision["mode"],
                    "target_id": candidate["target_id"], "axis": candidate["axis"],
                    "switch_to": [m for m in modes if m != decision["mode"]], **built[decision["mode"]]}
        log(intent, {"turn": intent["turn"], "event": "ask", "candidate": candidate, "decision": decision,
                     "question_id": question["question_id"]})
        intent.setdefault("asked", []).append({"target_id": candidate["target_id"], "axis": candidate["axis"],
                                               "turn": intent["turn"]})
        return question
    return None


def log(intent: dict[str, Any], entry: dict[str, Any]) -> None:
    intent["question_log"] = (intent.get("question_log", []) + [entry])[-LOG_LIMIT:]


# ---- ② answers ------------------------------------------------------------------------------------------

def valid_answer(question: dict[str, Any] | None, answer: dict[str, Any]) -> bool:
    if not question or answer.get("question_id") != question["question_id"] or answer.get("choice") not in ANSWER_CHOICES:
        return False
    ids = answer.get("option_ids") or []
    known = {o["id"] for o in question["options"]}
    if answer["choice"] == "options":
        return bool(ids) and set(ids) <= known and (question["multi"] or len(ids) == 1)
    if answer["choice"] == "switch":
        return answer.get("switch_to") in question["switch_to"] and not ids
    return not ids and (answer["choice"] in question["allow"] or answer["choice"] == "skip")


def interpret(intent: dict[str, Any], question: dict[str, Any], answer: dict[str, Any], scope: str) -> list[str]:
    """Apply one answer. Returns the changed score/pin keys (empty: nothing changes, e.g. unsure/skip).

    v0 (2-feedback.md, text_options row): a chosen option pins that value for this request. neither/unsure/skip
    change nothing. Other modes return [] until the ② Issue defines their rows.
    """
    changed: list[str] = []
    if answer["choice"] == "options" and question["mode"] == "text_options":
        for option in question["options"]:
            if option["id"] in answer["option_ids"]:
                key = scoring.score_key(question["target_id"], scope, question["axis"], option["value"])
                if not any(p["key"] == key for p in intent["pinned"]):
                    intent["pinned"].append({"key": key})
                intent["excluded"] = [k for k in intent["excluded"] if k != key]
                changed.append(key)
    log(intent, {"turn": intent["turn"], "event": "answer", "question_id": question["question_id"],
                 "mode": question["mode"], "choice": answer["choice"], "option_ids": list(answer.get("option_ids") or []),
                 "changed": changed})
    return changed


def public(question: dict[str, Any] | None) -> dict[str, Any] | None:
    if not question:
        return None
    return {k: question[k] for k in ("question_id", "mode", "target_id", "axis", "prompt", "multi", "allow", "switch_to")} | {
        "options": [{k: o[k] for k in ("id", "label", "product_id", "image_id", "image_version") if k in o}
                    for o in question["options"]]}
