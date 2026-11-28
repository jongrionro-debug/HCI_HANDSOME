"""Question loop v1 (research/question-design 1-modes, 2-feedback, 3-mapping; ADR 0020).

One turn of the loop, code everywhere except the optional model choice in choose():

    candidates()  -> what could we ask?             (3: reactive triggers + proactive axis ranking)
    allowed()     -> which modes can ask it now?    (1: feasibility per mode, from the eligible pool)
    choose()      -> which mode, decided by whom?   (3: rule order, an LLM may pick inside allowed)
    build()       -> the question shown to the user (1: prompt, options, images)
    interpret()   -> what the answer changes        (2: strength levels L4..L-3, progress signals)

Contract shapes are plain dicts so they survive LangGraph checkpoints (agreed in Issue #29):

    Candidate  {"id", "target_id", "axis", "kind": "gap"|"reactive"|"flow"|"switch", "values",
                "trigger"?, "term"?, "chips"?: [{"axis", "value"}], "base"?: product view subset}
    Decision   {"candidate_id", "mode", "decided_by": "rule"|"llm"|"user", "reason", "allowed",
                "signals", "shadow"?: rule decision, "agree"?}
    Question   {"question_id", "mode", "kind", "target_id", "axis", "prompt", "multi", "layout"?,
                "options": [Option], "allow": ["unsure", "neither", "skip"], "strengths": [str],
                "switch_to": [mode], "base"?: {"product_id", "image_id", "image_version"}}
    Option     {"id", "label", "value", "axis"?, "product_id"?, "image_id"?, "image_version"?,
                "direction"?, "step"?}
    Answer     {"question_id", "choice": "options"|"neither"|"unsure"|"skip"|"switch", "option_ids",
                "switch_to", "strengths"?: {option_id: "only"|"more"}}

A free-text reply while a question is open is not an Answer: it goes through parse_turn like any text and closes
the question (2-feedback.md 4절 "글" rows). The loop is on unless STYLEMATE_QUESTION_LOOP=off.
All numbers here are pilot assumptions (가정) named in the decision documents.
"""

from __future__ import annotations

import math
import os
import random
from collections import Counter
from typing import Any, Callable

from . import memory, scoring
from .labels import value_label

MODE_NAMES = ("reason_chips", "explain_images", "relative_adjust", "photo_chips", "select_images", "text_options",
              "propose_compare")
IMAGE_MODES = ("select_images", "photo_chips", "explain_images", "relative_adjust")
ANSWER_CHOICES = ("options", "neither", "unsure", "skip", "switch")
STRENGTHS = ("only", "more")
SKIP_AXES = ("Brand", "Price")  # metadata or numeric filter, never asked as a value (ADR 0016)
TEXT_ONLY_AXES = ("Fabric", "Weight")  # 3-mapping 7절 ①: not checkable from a photo (Weight 가정)
NAME_AXES = ("Color",)  # 3-mapping 7절 ③: the name already shows the look (ADR 0016: colour by talk first)
ORDINAL_AXES = ("Fit", "Length", "Tone", "Weight")
MULTI_AXES = ("Type", "Style", "Pattern", "Detail")  # photo_chips multi-select; ordinal axes stay single
MAX_OPTIONS = 4
MIN_SHARED = 2  # reason_chips needs at least two shared values (가정)
MAX_CHIPS = 4
PROACTIVE_LIMIT = 4  # proactive questions per request (가정)
ASK_GAP = 2  # turns of rest after a proactive question left unanswered (가정)
ENOUGH_TURNS = 4  # "충분" after this many grid turns (가정)
COMPARE_REST = 3  # turns before offering the comparison again after "더 둘러볼게요" (가정)
LOG_LIMIT = 100
# 3-mapping 6절 importance default per axis (가정: stands in for the offline per-garment LLM table, not generated yet).
IMPORTANCE = {"Type": 1.0, "Fit": 0.9, "Color": 0.9, "Style": 0.8, "Silhouette": 0.7, "Length": 0.6, "Tone": 0.6,
              "Pattern": 0.6, "Texture": 0.5, "Detail": 0.5, "Weight": 0.5, "Fabric": 0.4}
MENTION_BOOST = 1.5
# PI v3 ordinal value scores (ADR 0016). Tone is L* of the main colour; label centres are 가정.
VALUE_SCORE = {"Fit": {"Slim": 1.0, "Regular": 2.0, "Relaxed": 3.0, "Oversized": 4.0},
               "Weight": {"Light": 1.0, "Mid": 2.0, "Heavy": 3.0},
               "Tone": {"Dark": 25.0, "Medium": 55.0, "Light": 80.0},
               "Length": {"Sleeveless": 0.0, "Short sleeve": 1.0, "Long sleeve": 2.0, "Shorts": 1.0, "Cropped": 2.0,
                          "Full": 3.0}}
STEP = {"step_small": 0.5, "step_large": 1.0}
TONE_STEP = {"step_small": 5.0, "step_large": 15.0}  # L* is 0-100, not the 1-4 ordinal scale (Issue #38, 가정)
DIRECTION_WORDS = {"Fit": ("슬림하게", "여유롭게"), "Length": ("짧게", "길게"), "Tone": ("어둡게", "밝게"),
                   "Weight": ("얇게", "두껍게")}
SIGNALS = ("unsure_repeat", "term_unknown", "long_text", "user_asked_images", "user_asked_text", "user_mentioned_axis",
           "shared_values", "ambiguous_term", "near_match", "enough", "split")
CHOOSE_INSTRUCTIONS = (
    "LUMI 질문 방식 선택. candidates는 코드가 거른 질문 후보이고 순서가 규칙 순위다. 각 후보의 allowed 안에서만 "
    "mode를 고르거나 candidate_id를 null로 두어 이번엔 묻지 않는다(선제형만). 첫 후보가 아닌 것을 고르면 signals에 "
    "facts에서 참인 근거 신호를 하나 이상 넣는다. 질문 문구는 쓰지 않는다.")


def loop_enabled() -> bool:
    return os.environ.get("STYLEMATE_QUESTION_LOOP", "on").strip().lower() not in ("off", "0", "false", "no")


def josa(word: str, pair: tuple[str, str] = ("은", "는")) -> str:
    """Korean particle after the last syllable (받침 -> first form)."""
    last = word.strip()[-1:] if word.strip() else ""
    if "가" <= last <= "힣":
        return pair[0] if (ord(last) - 0xAC00) % 28 else pair[1]
    return pair[1]


def v3_score(product: dict[str, Any] | None, axis: str) -> float | None:
    entry = (((product or {}).get("v3") or {}).get("axes") or {}).get(axis) or {}
    score = entry.get("score")
    return float(score) if isinstance(score, (int, float)) and not isinstance(score, bool) else None


# ---- 3 policy: candidates ------------------------------------------------------------------------------

def _mentioned(intent: dict[str, Any], target_id: str) -> set[str]:
    axes = {s["feature"] for s in intent.get("soft", []) if s.get("target_id") in (None, target_id)}
    axes |= {h["axis"] for h in intent.get("hypotheses", []) if h["target_id"] == target_id}
    return axes


def axis_ranking(intent: dict[str, Any], target_id: str, pool: list[dict[str, Any]], fixed: list[str],
                 scope: str) -> list[dict[str, Any]]:
    """3-mapping 6절: importance x split x uncertainty over the axes still open for this target."""
    asked = {a["axis"] for a in intent.get("asked", []) if a["target_id"] == target_id and a.get("kind", "gap") == "gap"}
    skipped = {a for t, a in intent.get("skipped_axes", []) if t == target_id}
    mentioned = _mentioned(intent, target_id)
    axes: list[str] = []
    for product in pool:
        axes += [a for a in product["facts"] if a not in axes]
    ranked = []
    for axis in axes:
        if axis in SKIP_AXES or axis in fixed or axis in asked or axis in skipped:
            continue
        counts = Counter(v for p in pool for v in p["facts"].get(axis) or [])
        if len(counts) < 2:
            continue
        total = sum(counts.values())
        split = -sum(n / total * math.log(n / total) for n in counts.values()) / math.log(len(counts))
        means = [scoring.mean(memory.effective(intent, scoring.score_key(target_id, scope, axis, v))) for v in counts]
        uncertainty = 1.0 - max(means)
        importance = IMPORTANCE.get(axis, 0.5) * (MENTION_BOOST if axis in mentioned else 1.0)
        ranked.append({"id": f"{target_id}:{axis}", "target_id": target_id, "axis": axis, "kind": "gap",
                       "values": [v for v, _ in counts.most_common()], "mentioned": axis in mentioned,
                       "score": round(importance * split * uncertainty, 4)})
    ranked.sort(key=lambda c: (-c["score"], c["axis"]))
    return ranked


def _shared_chips(trigger: dict[str, Any], fixed: list[str]) -> list[dict[str, str]]:
    chosen, shown = trigger["chosen"], trigger["shown"]
    chips = []
    for axis in sorted({a for c in chosen for a in c}, key=lambda a: (-IMPORTANCE.get(a, 0.5), a)):
        if axis in SKIP_AXES or axis in fixed:
            continue
        common = set.intersection(*[set(c.get(axis) or []) for c in chosen])
        everywhere = set.intersection(*[set(c.get(axis) or []) for c in shown]) if shown else set()
        chips += [{"axis": axis, "value": v} for v in sorted(common - everywhere)]
    return chips


def reactive(intent: dict[str, Any], pools: dict[str, list[dict[str, Any]]], fixed: dict[str, list[str]],
             products: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """3-mapping 2절·9절: questions caused by what the user just did (bypass ASK_GAP, one per turn)."""
    result = []
    trigger = intent.get("trigger") or {}
    selection = trigger.get("selection")
    if selection and len(selection["chosen"]) >= 2:
        chips = _shared_chips(selection, fixed.get(selection["target_id"], []))
        if len(chips) >= MIN_SHARED:
            result.append({"id": f"{selection['target_id']}:reason", "target_id": selection["target_id"], "axis": None,
                           "kind": "reactive", "trigger": "shared_values", "values": [], "chips": chips[:MAX_CHIPS],
                           "products": selection["product_ids"]})
    asked_terms = {(a["target_id"], a.get("term"), a["axis"]) for a in intent.get("asked", []) if a.get("term")}
    if intent.get("hyp_turn") is not None and intent.get("hyp_turn") == intent["turn"] - 1:
        quotes = {n["key"]: n.get("quote") or n.get("content") for n in intent.get("fea_needs", [])}
        for h in intent.get("hypotheses", []):
            term = next((quotes[k] for k in h["fea_keys"] if quotes.get(k)), None)
            if (not term or len(h["values"]) < 2 or h["axis"] in TEXT_ONLY_AXES + SKIP_AXES
                    or h["axis"] in fixed.get(h["target_id"], []) or (h["target_id"], term, h["axis"]) in asked_terms):
                continue
            result.append({"id": f"{h['target_id']}:{h['axis']}:term", "target_id": h["target_id"], "axis": h["axis"],
                           "kind": "reactive", "trigger": "ambiguous_term", "values": list(h["values"]), "term": term})
    base = trigger.get("base")
    recent = any(a.get("trigger") == "near_match" and intent["turn"] - a["turn"] <= 2 for a in intent.get("asked", []))
    if base and base["reason"] == "same_top" and recent:
        base = None  # a code-noticed base never repeats the adjustment the user just answered (가정)
    if base:
        view = next((p for p in products if p["product_id"] == base["product_id"] and p["target_id"] == base["target_id"]), None)
        if view:
            result.append({"id": f"{base['target_id']}:relative", "target_id": base["target_id"], "axis": None,
                           "kind": "reactive", "trigger": "near_match", "values": [], "reason": base["reason"],
                           "base": {k: view.get(k) for k in ("product_id", "target_id", "image_id", "image_version", "facts", "v3")}})
    return result


def enough(intent: dict[str, Any], ranking: list[dict[str, Any]]) -> bool:
    """3-mapping 2절 충분 판정: at most one open core axis, ENOUGH_TURNS grid turns, or "보여 줘"."""
    if len(intent.get("shortlist", [])) < 2:
        return False
    offered = intent.get("compare_offered")
    if offered is not None and intent["turn"] - offered < COMPARE_REST:
        return False
    core = [c for c in ranking if c["score"] > 0]
    return len(core) <= 1 or intent["turn"] >= ENOUGH_TURNS or bool(intent.get("show_hint"))


def proactive_open(intent: dict[str, Any]) -> bool:
    if sum(1 for a in intent.get("asked", []) if a.get("kind", "gap") == "gap") >= PROACTIVE_LIMIT:
        return False
    ignored = intent.get("ignored_turn")
    return ignored is None or intent["turn"] - ignored >= ASK_GAP


def candidates(intent: dict[str, Any], pools: dict[str, list[dict[str, Any]]], fixed: dict[str, list[str]],
               products: list[dict[str, Any]] | None = None, scope: str = "request") -> list[dict[str, Any]]:
    """Ordered candidates: reactive (3-mapping 4절 order) > comparison offer > proactive ranking."""
    result = reactive(intent, pools, fixed, products or [])
    ranking: list[dict[str, Any]] = []
    for target in intent["targets"]:
        tid = target["target_id"]
        ranking += axis_ranking(intent, tid, pools.get(tid, []), fixed.get(tid, []), scope)
    ranking.sort(key=lambda c: (-c["score"], c["axis"]))
    requeue = intent.get("requeue")
    if requeue:
        hit = [c for c in ranking if c["target_id"] == requeue["target_id"] and c["axis"] == requeue["axis"]]
        if not hit:  # an unsure / "다 별로" answer re-asks an already asked axis once
            pool = pools.get(requeue["target_id"], [])
            counts = Counter(v for p in pool for v in p["facts"].get(requeue["axis"]) or [])
            if len(counts) >= 2:
                hit = [{"id": f"{requeue['target_id']}:{requeue['axis']}", "target_id": requeue["target_id"],
                        "axis": requeue["axis"], "kind": "gap", "values": [v for v, _ in counts.most_common()],
                        "mentioned": False, "score": 0.0}]
        ranking = [dict(c, prefer=requeue["prefer"]) for c in hit] + [c for c in ranking if c not in hit]
    if not result and enough(intent, ranking):
        result.append({"id": "compare", "target_id": intent["targets"][0]["target_id"], "axis": None, "kind": "flow",
                       "trigger": "enough", "values": []})
    if requeue and ranking and ranking[0].get("prefer"):
        # The user's own progress signal ("모르겠어요", "그게 뭐예요?", "다 별로") outranks a code-noticed
        # "same product on top" base; it ignores the proactive rest and cap (2-feedback 진행 신호).
        lead = [c for c in result if c.get("reason") != "same_top"]
        late = [c for c in result if c.get("reason") == "same_top"]
        return lead + ranking[:1] + late + (ranking[1:] if proactive_open(intent) else [])
    if proactive_open(intent):
        result += ranking
    return result


def should_ask(intent: dict[str, Any]) -> bool:
    if intent.get("route_question") or intent.get("compare_mode"):
        return False
    if intent.get("novelty_prompt") == "ask" or intent.get("taste_prompt"):
        return False
    return True


# ---- 1 modes: feasibility and question building -----------------------------------------------------------

def _label(labels: dict[str, str], axis: str) -> str:
    return labels.get(axis, axis)


def _image(product: dict[str, Any]) -> dict[str, Any]:
    return {"product_id": product["product_id"], "image_id": product["image_id"], "image_version": product["image_version"]}


def _representative(pool: list[dict[str, Any]], axis: str, value: str, kind: str | None) -> dict[str, Any] | None:
    """One product showing the value: single-valued on the axis first, the dominant Type next (3-mapping 7절)."""
    options = [p for p in pool if value in (p["facts"].get(axis) or []) and p.get("image_id")]
    options.sort(key=lambda p: (len(p["facts"].get(axis) or []) != 1,
                                kind is not None and kind not in (p["facts"].get("Type") or []), p["product_id"]))
    return options[0] if options else None


def _dominant_type(pool: list[dict[str, Any]]) -> str | None:
    counts = Counter(v for p in pool for v in p["facts"].get("Type") or [])
    return counts.most_common(1)[0][0] if counts else None


def _text_options(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    if candidate["kind"] not in ("gap", "switch") or not candidate.get("axis"):
        return None
    values = candidate["values"][:MAX_OPTIONS]
    if len(values) < 2:
        return None
    label = _label(labels, candidate["axis"])
    return {"prompt": f"{label}{josa(label)} 어떤 쪽이 좋으세요?", "multi": False,
            "options": [{"id": f"o{i}", "label": value_label(candidate["axis"], v), "value": v} for i, v in enumerate(values)],
            "allow": ["unsure", "skip"], "strengths": []}


def _photo_chips(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    axis = candidate.get("axis")
    if candidate["kind"] not in ("gap", "switch") or not axis or axis in TEXT_ONLY_AXES:
        return None
    kind = _dominant_type(pool) if axis != "Type" else None
    options = []
    for value in candidate["values"]:
        product = _representative(pool, axis, value, kind)
        if product:
            options.append({"id": f"o{len(options)}", "label": value_label(axis, value), "value": value, **_image(product)})
        if len(options) >= MAX_OPTIONS:
            break
    if len(options) < 2:
        return None
    label = _label(labels, axis)
    multi = axis in MULTI_AXES
    prompt = f"{label}{josa(label)} 어떤 쪽이 좋으세요? 사진을 보고 " + ("마음에 드는 걸 모두 골라 주세요." if multi else "하나 골라 주세요.")
    return {"prompt": prompt, "multi": multi, "options": options, "allow": ["unsure", "skip"], "strengths": []}


def _select_images(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    """3-mapping 7절 후반: 2-4 products that differ on the axis, all of one Type (2 = contrast pair)."""
    axis = candidate.get("axis")
    if candidate["kind"] not in ("gap", "switch") or not axis or axis in TEXT_ONLY_AXES:
        return None
    types = {v for p in pool for v in p["facts"].get("Type") or []}
    if axis != "Type" and len(types) > 1:
        return None  # before Type is settled the photos would mix garments (초반 -> photo_chips)
    singles = [p for p in pool if len(p["facts"].get(axis) or []) == 1 and p.get("image_id")]
    by_value: dict[str, list[dict[str, Any]]] = {}
    for p in singles:
        by_value.setdefault(p["facts"][axis][0], []).append(p)
    values = [v for v in candidate["values"] if v in by_value][:MAX_OPTIONS]
    if len(values) < 2:
        return None
    seed = sorted(by_value[values[0]], key=lambda p: p["product_id"])[0]

    def alike(p: dict[str, Any]) -> int:
        return sum(len(set(p["facts"].get(a) or []) & set(seed["facts"].get(a) or [])) for a in seed["facts"] if a != axis)
    picks = [seed] + [sorted(by_value[v], key=lambda p: (-alike(p), p["product_id"]))[0] for v in values[1:]]
    label = _label(labels, axis)
    pair = len(picks) == 2
    prompt = (f"두 옷은 {label}만 달라요. 어느 쪽이 더 가까워요?" if pair
              else f"{label}만 다른 옷 {len(picks)}벌이에요. 끌리는 걸 모두 눌러 주세요.")
    return {"prompt": prompt, "multi": True, "layout": "pair" if pair else "grid",
            "options": [{"id": f"o{i}", "label": value_label(axis, p["facts"][axis][0]), "value": p["facts"][axis][0],
                         **_image(p)} for i, p in enumerate(picks)],
            "allow": ["neither", "unsure", "skip"], "strengths": []}


def _explain_images(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    if candidate.get("trigger") != "ambiguous_term":
        return None
    axis = candidate["axis"]
    kind = _dominant_type(pool) if axis != "Type" else None
    options = []
    for value in candidate["values"][:MAX_OPTIONS]:
        product = _representative(pool, axis, value, kind)
        if not product:
            return None  # every interpretation needs its picture (3-mapping 2절)
        options.append({"id": f"o{len(options)}", "label": value_label(axis, value), "value": value, **_image(product)})
    term = candidate["term"]
    return {"prompt": f"'{term}'{josa(term)} 어느 쪽에 가까워요?", "multi": False, "options": options,
            "allow": ["unsure", "skip"], "strengths": [], "term": term}


def _reason_chips(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    if candidate.get("trigger") != "shared_values":
        return None
    options = [{"id": f"o{i}", "label": f"{_label(labels, c['axis'])} · {value_label(c['axis'], c['value'])}",
                "value": c["value"], "axis": c["axis"]} for i, c in enumerate(candidate["chips"])]
    return {"prompt": "고르신 옷들의 공통점이에요. 어떤 게 좋았어요?", "multi": True, "options": options,
            "allow": ["unsure", "skip"], "strengths": list(STRENGTHS), "products": list(candidate.get("products", []))}


def _relative_adjust(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    base = candidate.get("base")
    if candidate.get("trigger") != "near_match" or not base:
        return None
    options: list[dict[str, Any]] = []
    for axis in sorted(ORDINAL_AXES, key=lambda a: (-IMPORTANCE.get(a, 0.5), a)):
        score = v3_score(base, axis)
        if score is None or axis in candidate.get("fixed", []):
            continue
        low, high = (0.0, 100.0) if axis == "Tone" else (min(VALUE_SCORE[axis].values()), max(VALUE_SCORE[axis].values()))
        for direction, word in ((1, DIRECTION_WORDS[axis][1]), (-1, DIRECTION_WORDS[axis][0])):
            if (direction > 0 and score >= high) or (direction < 0 and score <= low):
                continue
            for step, prefix in (("step_small", "조금 더"), ("step_large", "훨씬")):
                options.append({"id": f"o{len(options)}", "label": f"{prefix} {word}", "axis": axis,
                                "value": f"{'+' if direction > 0 else '-'}{step}", "direction": direction, "step": step})
        if len({o["axis"] for o in options}) >= 2:
            break
    if not options:
        return None
    return {"prompt": "이 옷을 기준으로 조금씩 바꿔 볼까요?", "multi": False, "options": options[:8],
            "allow": ["skip"], "strengths": [], "base": {k: base[k] for k in ("product_id", "image_id", "image_version")}}


def _propose_compare(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> dict[str, Any] | None:
    if candidate["kind"] != "flow":
        return None
    return {"prompt": "후보를 모았어요. 후보함에서 비교해 볼까요?", "multi": False,
            "options": [{"id": "compare", "label": "비교해 볼게요", "value": "compare"},
                        {"id": "continue", "label": "더 둘러볼게요", "value": "continue"}],
            "allow": [], "strengths": []}


Builder = Callable[[dict[str, Any], list[dict[str, Any]], dict[str, str]], "dict[str, Any] | None"]
MODES: dict[str, dict[str, Any]] = {
    "reason_chips": {"build": _reason_chips},
    "explain_images": {"build": _explain_images},
    "relative_adjust": {"build": _relative_adjust},
    "photo_chips": {"build": _photo_chips},
    "select_images": {"build": _select_images},
    "text_options": {"build": _text_options},
    "propose_compare": {"build": _propose_compare},
}
SWITCH_MODES = ("text_options", "photo_chips", "select_images")  # the modes a user can switch a gap question to


def allowed(candidate: dict[str, Any], pool: list[dict[str, Any]], labels: dict[str, str]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    built: dict[str, dict[str, Any]] = {}
    for name in MODE_NAMES:
        build = MODES[name]["build"]
        question = build(candidate, pool, labels) if build else None
        if question:
            built[name] = question
    return list(built), built


# ---- 3 policy: mode choice --------------------------------------------------------------------------------

def rule_mode(candidate: dict[str, Any], modes: list[str], intent: dict[str, Any]) -> tuple[str, str]:
    """3-mapping 4절·7절 default mode. Returns (mode, reason)."""
    if candidate["kind"] in ("reactive", "flow"):
        return modes[0], f"trigger:{candidate.get('trigger')}"
    axis = candidate["axis"]
    prefer = candidate.get("prefer")  # the latest progress signal wins over an earlier switch
    if prefer == "image":
        pick = next((m for m in ("select_images", "photo_chips") if m in modes), None)
        if pick:
            return pick, "requeue:unsure"
    if prefer in modes:
        return prefer, f"requeue:{prefer}"
    preferred = intent.get("mode_pref", {}).get(f"{candidate['target_id']}:{axis}")
    if preferred in modes:
        return preferred, "user_mode"  # a switched mode holds for that axis for the rest of the request
    if axis in (intent.get("term_unknown") or []) and "photo_chips" in modes:
        return "photo_chips", "term_unknown"
    if axis in TEXT_ONLY_AXES or axis in NAME_AXES:
        return "text_options", "axis:text"
    if axis == "Type" and "photo_chips" in modes:
        return "photo_chips", "axis:type_early"  # asking Type means it is not settled yet (3-mapping 7절)
    for mode in ("select_images", "photo_chips"):
        if mode in modes:
            return mode, "axis:late" if mode == "select_images" else "axis:early"
    return "text_options", "fallback:text"


def facts(intent: dict[str, Any], options: list[dict[str, Any]]) -> dict[str, bool]:
    """Code-checked truth of every signal the model may cite (3-mapping 8절)."""
    kinds = {c.get("trigger") for c in options}
    return {"unsure_repeat": intent.get("unsure_count", 0) >= 2, "term_unknown": bool(intent.get("term_unknown")),
            "long_text": intent.get("last_text_len", 0) >= 40, "user_asked_images": intent.get("mode_hint") == "image",
            "user_asked_text": intent.get("mode_hint") == "text",
            "user_mentioned_axis": any(c.get("mentioned") for c in options),
            "shared_values": "shared_values" in kinds, "ambiguous_term": "ambiguous_term" in kinds,
            "near_match": "near_match" in kinds, "enough": "enough" in kinds,
            "split": any(c.get("kind") == "gap" for c in options)}


def choose_schema(options: list[dict[str, Any]]) -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["candidate_id", "mode", "signals", "reason"],
            "properties": {"candidate_id": {"type": ["string", "null"], "enum": [o["candidate"]["id"] for o in options] + [None]},
                           "mode": {"type": ["string", "null"], "enum": list(MODE_NAMES) + [None]},
                           "signals": {"type": "array", "items": {"type": "string", "enum": list(SIGNALS)}},
                           "reason": {"type": "string"}}}


def choose(options: list[dict[str, Any]], intent: dict[str, Any],
           chooser: Callable[[str, dict[str, Any], dict[str, Any]], Any] | None = None
           ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Pick (option, decision). options = [{"candidate", "modes", "built"}] in rule order.

    The rule decision is always computed (shadow). A model choice is kept only when it names an allowed mode of a
    listed candidate and every cited signal is true; a non-first candidate needs at least one signal (3-mapping 1·6절).
    """
    first = options[0]
    mode, reason = rule_mode(first["candidate"], first["modes"], intent)
    rule = {"candidate_id": first["candidate"]["id"], "mode": mode, "decided_by": "rule", "reason": reason,
            "allowed": list(first["modes"]), "signals": []}
    if chooser is None or (len(options) == 1 and len(first["modes"]) == 1):
        return first, rule
    truth = facts(intent, [o["candidate"] for o in options])
    payload = {"candidates": [{"id": o["candidate"]["id"], "kind": o["candidate"]["kind"], "axis": o["candidate"].get("axis"),
                               "trigger": o["candidate"].get("trigger"), "allowed": o["modes"]} for o in options],
               "facts": truth, "turn": intent["turn"]}
    try:
        raw = chooser(CHOOSE_INSTRUCTIONS, payload, choose_schema(options))
    except Exception:
        return first, rule | {"reason": f"{reason};llm_unavailable"}
    rejected = rule | {"reason": f"{reason};rejected_llm", "shadow": dict(rule), "agree": False}
    signals = raw.get("signals") if isinstance(raw, dict) else None
    if not isinstance(raw, dict) or not isinstance(signals, list) or not all(s in SIGNALS and truth.get(s) for s in signals):
        return first, rejected
    if raw.get("candidate_id") is None:
        if first["candidate"]["kind"] == "gap":  # the model may skip only proactive questions
            return None, rule | {"mode": None, "decided_by": "llm", "reason": "llm_no_question", "signals": signals,
                                 "shadow": dict(rule), "agree": False}
        return first, rejected
    picked = next((o for o in options if o["candidate"]["id"] == raw["candidate_id"]), None)
    if picked is None or raw.get("mode") not in picked["modes"] or (picked is not first and not signals):
        return first, rejected
    decision = {"candidate_id": picked["candidate"]["id"], "mode": raw["mode"], "decided_by": "llm",
                "reason": str(raw.get("reason") or "")[:200], "allowed": list(picked["modes"]), "signals": signals,
                "shadow": dict(rule), "agree": picked is first and raw["mode"] == rule["mode"]}
    return picked, decision


# ---- loop -------------------------------------------------------------------------------------------------

def plan(intent: dict[str, Any], pools: dict[str, list[dict[str, Any]]], fixed: dict[str, list[str]],
         labels: dict[str, str], products: list[dict[str, Any]] | None = None, scope: str = "request",
         chooser: Callable[..., Any] | None = None) -> dict[str, Any] | None:
    """Pick at most one question for this turn and log the decision (3-mapping 11절)."""
    if not should_ask(intent):
        return None
    options = []
    for candidate in candidates(intent, pools, fixed, products, scope):
        if candidate.get("trigger") == "near_match":
            candidate = candidate | {"fixed": fixed.get(candidate["target_id"], [])}
        modes, built = allowed(candidate, pools.get(candidate["target_id"], []), labels)
        if modes:
            options.append({"candidate": candidate, "modes": modes, "built": built})
    if intent.get("reason_prompt") and not any(o["candidate"].get("trigger") == "shared_values" for o in options):
        return None  # the F4 reason banner is this turn's "공통점 0개 -> 글로 확인" question
    if not options:
        return None
    picked, decision = choose(options[:8], intent, chooser)
    top = [{"id": o["candidate"]["id"], "kind": o["candidate"]["kind"], "score": o["candidate"].get("score")} for o in options[:5]]
    if picked is None:
        log(intent, {"turn": intent["turn"], "event": "no_question", "decision": decision, "ranking": top})
        return None
    candidate = picked["candidate"]
    mode = decision["mode"]
    built = dict(picked["built"][mode])
    question_id = f"q{intent['turn']}-{candidate['id']}"
    if mode == "select_images":  # 2-feedback 4절: shuffle the shown order and log positions (position bias)
        shuffled = list(built["options"])
        random.Random(f"{intent.get('request_id')}:{question_id}").shuffle(shuffled)
        built["options"] = shuffled
    question = {"question_id": question_id, "mode": mode, "kind": candidate["kind"],
                "target_id": candidate["target_id"], "axis": candidate.get("axis"), "layout": built.pop("layout", None),
                "switch_to": [m for m in picked["modes"] if m != mode and m in SWITCH_MODES] if candidate["kind"] == "gap" else [],
                **built}
    log(intent, {"turn": intent["turn"], "event": "ask", "candidate": {k: v for k, v in candidate.items() if k != "base"},
                 "decision": decision, "ranking": top, "question_id": question["question_id"],
                 "positions": [o["id"] for o in question["options"]]})
    asked = {"target_id": candidate["target_id"], "axis": candidate.get("axis"), "turn": intent["turn"], "kind": candidate["kind"]}
    if candidate.get("term"):
        asked["term"] = candidate["term"]
    if candidate.get("trigger"):
        asked["trigger"] = candidate["trigger"]
    intent.setdefault("asked", []).append(asked)
    if candidate["kind"] == "flow":
        intent["compare_offered"] = intent["turn"]
    if candidate.get("prefer"):
        intent["requeue"] = None
    return question


def log(intent: dict[str, Any], entry: dict[str, Any]) -> None:
    intent["question_log"] = (intent.get("question_log", []) + [entry])[-LOG_LIMIT:]


# ---- 2 answers ------------------------------------------------------------------------------------------

def valid_answer(question: dict[str, Any] | None, answer: dict[str, Any]) -> bool:
    if not question or answer.get("question_id") != question["question_id"] or answer.get("choice") not in ANSWER_CHOICES:
        return False
    ids = answer.get("option_ids") or []
    known = {o["id"] for o in question["options"]}
    strengths = answer.get("strengths") or {}
    if (not isinstance(ids, list) or not isinstance(strengths, dict) or not set(strengths) <= set(ids)
            or not set(strengths.values()) <= set(question.get("strengths") or [])):
        return False
    if answer["choice"] == "options":
        return bool(ids) and len(set(ids)) == len(ids) and set(ids) <= known and (question["multi"] or len(ids) == 1)
    if answer["choice"] == "switch":
        return answer.get("switch_to") in question["switch_to"] and not ids
    return not ids and (answer["choice"] in question["allow"] or answer["choice"] == "skip")


def _pin(intent: dict[str, Any], key: str) -> None:
    if not any(p["key"] == key for p in intent["pinned"]):
        intent["pinned"].append({"key": key})
    intent["excluded"] = [k for k in intent["excluded"] if k != key]


def _gain(intent: dict[str, Any], key: str, a: float = 0.0, b: float = 0.0) -> None:
    entry = scoring.get(intent["scores"], key)
    intent["scores"][key] = {"a": entry["a"] + a, "b": entry["b"] + b, "n": entry["n"] + 1}
    if a:
        intent["miss_streak"][key] = 0


def _confirm(intent: dict[str, Any], key: str) -> None:
    """L3: a strong score plus a solid understanding chip; the chip x releases it (2-feedback P6)."""
    _gain(intent, key, a=scoring.CONFIRM_GAIN)
    confirmed = intent.setdefault("confirmed", [])
    if key not in confirmed:
        confirmed.append(key)
    intent["excluded"] = [k for k in intent["excluded"] if k != key]


def relative_values(axis: str, base: float, direction: int, step: str) -> tuple[float, list[str]]:
    """Target score and the values beyond the base in that direction closest to it (ADR 0016 relative step)."""
    move = (TONE_STEP if axis == "Tone" else STEP)[step]
    scale = VALUE_SCORE[axis]
    low, high = (0.0, 100.0) if axis == "Tone" else (min(scale.values()), max(scale.values()))
    target = min(max(base + direction * move, low), high)
    beyond = {v: s for v, s in scale.items() if (s - base) * direction > 0}
    if not beyond:
        return target, []
    best = min(abs(s - target) for s in beyond.values())
    return target, sorted(v for v, s in beyond.items() if abs(s - target) == best)


def interpret(intent: dict[str, Any], question: dict[str, Any], answer: dict[str, Any], scope: str,
              base_view: dict[str, Any] | None = None) -> list[str]:
    """Apply one answer (2-feedback.md 3·4절). Returns the changed keys; [] = the value state is unchanged.

    Progress signals (requeue, skipped axes, unsure count, base trigger) are left on intent for the next plan.
    """
    changed: list[str] = []
    mode, tid, axis = question["mode"], question["target_id"], question.get("axis")
    ids = answer.get("option_ids") or []
    chosen = [o for o in question["options"] if o["id"] in ids]
    rest = [o for o in question["options"] if o["id"] not in ids]
    choice = answer["choice"]

    def key(a: str, v: str) -> str:
        return scoring.score_key(tid, scope, a, v)

    if choice == "unsure":
        intent["unsure_count"] = intent.get("unsure_count", 0) + 1
        if axis and question["kind"] == "gap" and mode not in IMAGE_MODES:
            intent["requeue"] = {"target_id": tid, "axis": axis, "prefer": "image"}
    elif choice == "skip" and axis and question["kind"] == "gap":
        skipped = intent.setdefault("skipped_axes", [])
        if [tid, axis] not in skipped:
            skipped.append([tid, axis])  # not "상관없음": it only stops asking (P3)
    elif choice == "neither" and mode == "select_images" and axis:
        intent["requeue"] = {"target_id": tid, "axis": axis, "prefer": "text_options"}
    elif choice == "options":
        if mode == "text_options" or (mode == "photo_chips" and not question["multi"]):
            for o in chosen:  # L4: the user named the value
                _pin(intent, key(axis, o["value"]))
                changed.append(key(axis, o["value"]))
        elif mode == "photo_chips" and rest:  # multi: L3 each, all chosen = L0, unchosen = L0
            for o in chosen:
                _confirm(intent, key(axis, o["value"]))
                changed.append(key(axis, o["value"]))
        elif mode == "explain_images":
            for o in chosen:
                _confirm(intent, key(axis, o["value"]))
                changed.append(key(axis, o["value"]))
            dropped = {o["value"] for o in rest}
            for h in intent.get("hypotheses", []):  # the other readings leave this word's list only (value L0)
                if h["target_id"] == tid and h["axis"] == axis:
                    h["values"] = [v for v in h["values"] if v not in dropped]
        elif mode == "select_images" and rest and axis not in scoring.IMAGE_BLIND_AXES:
            mine, others = {o["value"] for o in chosen}, {o["value"] for o in rest}
            for value in sorted(mine - others):
                _gain(intent, key(axis, value), a=scoring.SELECT_GAIN)  # L1, asked axis only (P2)
                changed.append(key(axis, value))
            for value in sorted(others - mine):
                _gain(intent, key(axis, value), b=scoring.MISS_PENALTY)  # L-1, not counted toward auto exclusion
                changed.append(key(axis, value))
            if len(chosen) == 1:
                intent.setdefault("trigger", {})["base"] = {"target_id": tid, "product_id": chosen[0]["product_id"],
                                                            "reason": "single_pick"}
        elif mode == "reason_chips":
            strengths = answer.get("strengths") or {}
            more = False
            for o in chosen:
                k = key(o["axis"], o["value"])
                if strengths.get(o["id"]) == "only":
                    _pin(intent, k)  # 꼭 있어야 해요 = L4
                else:
                    _gain(intent, k, a=scoring.REASON_GAIN)  # 있으면 좋아요 = L2
                    more = True
                changed.append(k)
            if more and question.get("products"):  # = 비슷하게 더 둘러보기 (3-mapping 9절)
                intent.setdefault("trigger", {})["base"] = {"target_id": tid, "product_id": question["products"][0],
                                                            "reason": "more"}
        elif mode == "relative_adjust":
            o = chosen[0]
            score = v3_score(base_view, o["axis"])
            if score is not None:  # a missing base score changes nothing (P7)
                target, values = relative_values(o["axis"], score, o["direction"], o["step"])
                for value in values:
                    _gain(intent, key(o["axis"], value), a=scoring.REASON_GAIN)
                    changed.append(key(o["axis"], value))
                targets = [t for t in intent.get("v3_targets", []) if not (t["target_id"] == tid and t["axis"] == o["axis"])]
                intent["v3_targets"] = targets + [{"target_id": tid, "axis": o["axis"], "score": target}]
                intent["anchor"] = {k: base_view[k] for k in ("product_id", "target_id", "facts")} | {"v3": base_view.get("v3")}
                changed.append(f"v3:{tid}:{o['axis']}")
        elif mode == "propose_compare" and chosen and chosen[0]["value"] == "compare":
            intent["compare_mode"] = True
            changed.append("compare")
    log(intent, {"turn": intent["turn"], "event": "answer", "question_id": question["question_id"], "mode": mode,
                 "choice": choice, "option_ids": list(ids), "strengths": dict(answer.get("strengths") or {}),
                 "changed": changed})
    return changed


def public(question: dict[str, Any] | None) -> dict[str, Any] | None:
    if not question:
        return None
    keys = ("question_id", "mode", "kind", "target_id", "axis", "prompt", "multi", "layout", "allow", "strengths",
            "switch_to", "term")
    return {k: question.get(k) for k in keys} | {
        "base": dict(question["base"]) if question.get("base") else None,
        "options": [{k: o[k] for k in ("id", "label", "axis", "product_id", "image_id", "image_version") if k in o}
                    for o in question["options"]]}
