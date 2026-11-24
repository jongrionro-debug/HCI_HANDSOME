"""LangGraph StateGraph for the intent loop (ADR 0013 decisions 1-3).

parse_turn -> update_intent -> propose_hypotheses -> route ->
(ask_clarify | retrieve -> plan_probe) -> compose_turn -> wait_user (interrupt) -> parse_turn ...

Only flow control lives here. Storage, model transport and catalog reads go
through a ``bridge`` supplied by ConsumerService, so the existing store keeps
confirmation, consent and deletion. Every store write uses a batch ID derived
from the user's command ID, so a node re-run after a crash is idempotent.
Nodes never raise for model/provider faults: they record a pending
interpretation and still reach the interrupt.
"""

from __future__ import annotations

from copy import deepcopy
import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, TypedDict

from ..errors import StyleMateError
from . import grid as grid_plan
from . import intent as it
from . import memory as mem
from . import questions
from . import scoring
from .clarify import CLARIFY_INSTRUCTIONS, clarify_payload, clarify_schema, validate_clarify
from .hypotheses import (HYPOTHESIS_INSTRUCTIONS, NON_HYPOTHESIS_AXES, build_hypothesis_payload, hypothesis_schema,
                         refresh_selection, validate_hypotheses)
from .parse import PARSE_INSTRUCTIONS, build_payload, parse_schema_v2, to_v1_extraction, validate_parse_v2


def graph_available() -> bool:
    try:
        import langgraph  # noqa: F401
        from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: F401
    except ImportError:
        return False
    return True


class GraphState(TypedDict):
    intent: dict[str, Any]
    event: dict[str, Any] | None


class GraphEngine:
    def __init__(self, bridge: Any, checkpoint_path: str | Path) -> None:
        if not graph_available():
            raise StyleMateError("unsupported_contract", "graph 엔진에는 선택 의존성 graph(langgraph)가 필요합니다.")
        from langgraph.checkpoint.sqlite import SqliteSaver
        from langgraph.graph import END, START, StateGraph

        self.bridge = bridge
        # Only turns serialize on this lock. Reads and deletes go through the
        # saver's own lock: they run on the DB thread, which a running turn
        # may be waiting on (bridge calls), so they must never wait for a turn.
        self._lock = threading.Lock()
        self._forgotten: set[str] = set()
        self._conn = sqlite3.connect(str(checkpoint_path), check_same_thread=False)
        self.saver = SqliteSaver(self._conn)
        # ADR 0015: end-summary proposals and profile drafts per request, erased with the request.
        self._summary_lock = threading.Lock()
        with self._summary_lock:
            self._conn.execute("CREATE TABLE IF NOT EXISTS lumi_summaries (request_id TEXT PRIMARY KEY, payload_json TEXT NOT NULL)")
            self._conn.commit()
        g = StateGraph(GraphState)
        for name in ("parse_turn", "update_intent", "propose_hypotheses", "ask_clarify", "retrieve",
                     "plan_probe", "compose_turn", "wait_user"):
            g.add_node(name, getattr(self, "_" + name))
        g.add_edge(START, "parse_turn")
        g.add_edge("parse_turn", "update_intent")
        g.add_edge("update_intent", "propose_hypotheses")
        g.add_conditional_edges("propose_hypotheses", self._route,
                                {"ask_clarify": "ask_clarify", "retrieve": "retrieve", "hold": "compose_turn"})
        g.add_edge("ask_clarify", "compose_turn")
        g.add_edge("retrieve", "plan_probe")
        g.add_edge("plan_probe", "compose_turn")
        g.add_edge("compose_turn", "wait_user")
        g.add_edge("wait_user", "parse_turn")
        self.app = g.compile(checkpointer=self.saver)
        self._end = END

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _config(request_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": request_id}, "recursion_limit": 40}

    # ---- public API -------------------------------------------------------
    def run_turn(self, request_id: str, targets: list[dict[str, Any]], event: dict[str, Any]) -> dict[str, Any]:
        from langgraph.types import Command
        config = self._config(request_id)
        with self._lock:
            snapshot = self.app.get_state(config)
            if not snapshot.values:
                self.app.invoke({"intent": it.new_intent(request_id, deepcopy(targets)), "event": event}, config)
            else:
                if snapshot.next and snapshot.next != ("wait_user",):
                    # A turn stopped mid-way (crash). Finish it first; store
                    # batches are idempotent, so re-running is safe.
                    self.app.invoke(None, config)
                self.app.invoke(Command(resume=event), config)
            intent = deepcopy(self.app.get_state(config).values["intent"])
            if request_id in self._forgotten:  # deleted while this turn ran
                self.saver.delete_thread(request_id)
            return intent

    def intent(self, request_id: str) -> dict[str, Any] | None:
        if request_id in self._forgotten:
            return None
        values = self.app.get_state(self._config(request_id)).values
        return deepcopy(values["intent"]) if values else None

    def forget(self, request_id: str) -> None:
        self._forgotten.add(request_id)
        self.saver.delete_thread(request_id)
        self.put_summary(request_id, None)

    def summary(self, request_id: str) -> dict[str, Any] | None:
        if request_id in self._forgotten:
            return None
        with self._summary_lock, self.saver.lock:
            row = self._conn.execute("SELECT payload_json FROM lumi_summaries WHERE request_id=?", (request_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def put_summary(self, request_id: str, payload: dict[str, Any] | None) -> None:
        with self._summary_lock, self.saver.lock:
            if payload is None:
                self._conn.execute("DELETE FROM lumi_summaries WHERE request_id=?", (request_id,))
            else:
                self._conn.execute("INSERT OR REPLACE INTO lumi_summaries VALUES (?,?)",
                                   (request_id, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
            self._conn.commit()

    # ---- nodes ------------------------------------------------------------
    def _parse_turn(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        event = state["event"] or {"type": "explore", "command_id": None}
        intent["event"] = {k: event.get(k) for k in ("type", "command_id", "action")}
        intent["pending_error"] = None
        intent["route_question"] = None
        if event.get("command_id") and event["command_id"] in intent["processed"]:
            return {"intent": intent}
        # The shortlist grid is (re)drawn on "후보함에서 고르기" and on a removal made while comparing.
        intent["compare_mode"] = event["type"] == "adjust" and (event.get("action") == "shortlist_compare" or (
            event.get("action") == "shortlist_remove" and bool((intent["last_grid"] or {}).get("compare"))))
        if event.get("start") and not intent.get("started"):
            self._start(intent, event["start"])
        scope = it.scope_of(intent)
        last = intent["last_grid"]
        if event["type"] == "feedback" and event.get("grid") and last and event["grid"]["set_id"] == last["set_id"]:
            signal = event["grid"]
            cards = last["cards"]
            selected = set(signal["selected"])
            by_id = {c["candidate_id"]: c for c in cards}
            liked = signal.get("liked") or {}
            intent["all_bad"] = bool(signal["all_bad"])
            compare = bool(last.get("compare"))  # the shortlist comparison grid is not a probe
            extra = {t["target_id"]: mem.prior_values(intent, t["target_id"]) for t in intent["targets"]}
            before = {k: dict(v) for k, v in intent["scores"].items()}
            changed = [] if signal["all_bad"] or compare else scoring.attribute_grid(intent, cards, selected, scope, extra)
            if not compare:
                self._note_picks(intent, cards, selected)
            for candidate_id, axes in sorted(liked.items()):
                for axis in axes:  # "이 상품의 이 점이 좋았어요": credit only that card's axis
                    scoring.apply_reason_axis(intent, cards, {candidate_id}, axis, scope)
            mem.note_contra(intent, before, scope, intent["turn"])
            mem.note_novel_pick(intent, cards, selected, intent["turn"])
            scoring.apply_dislikes(intent, [by_id[c]["product_id"] for c in signal["dislikes"] if c in by_id], intent["turn"])
            similar = by_id.get(signal["similar"]) if signal.get("similar") else None
            intent["anchor"] = {k: similar[k] for k in ("product_id", "target_id", "facts")} if similar else None
            intent["kept"] = [{"product_id": c["product_id"], "target_id": c["target_id"]}
                              for c in cards if c["candidate_id"] in selected][:grid_plan.MAX_KEPT]
            intent["reason_prompt"] = None
            intent["clarify"] = None
            if selected and not changed and not liked and not signal["all_bad"] and not compare:
                axes = self._differing_axes(cards, selected)
                if axes:
                    intent["reason_prompt"] = {"set_id": last["set_id"], "selected": sorted(selected), "axes": axes}
                    intent["clarify"] = self._clarify(cards, selected, axes)
        elif event["type"] == "adjust":
            self._adjust(intent, event, scope)
        elif event["type"] == "answer":
            self._answer(intent, event, scope)
        if event.get("novel_hint"):
            mem.ask_novelty(intent)
        if event.get("feedback_ref"):
            self._interpret(intent, event)
            if intent["questions"] and event.get("answers_question"):
                intent["questions"].pop(0)
        if event.get("command_id"):
            intent["processed"] = (intent["processed"] + [event["command_id"]])[-200:]
        return {"intent": intent}

    def _note_picks(self, intent: dict[str, Any], cards: list[dict[str, Any]], selected: set[str]) -> None:
        """F8 shortlist (every fresh pick of the request) and F11 pick history. No score change."""
        fresh = [c for c in cards if c["candidate_id"] in selected and c["slot"] != "kept"]
        if not fresh:
            return
        views = {(v["product_id"], v["target_id"]): v for v in self.bridge.products()}
        shortlist = intent.setdefault("shortlist", [])
        known = {(s["product_id"], s["target_id"]) for s in shortlist}
        history = intent.setdefault("pick_history", [])
        for card in fresh:
            key = (card["product_id"], card["target_id"])
            view = views.get(key)
            history.append({"turn": intent["turn"], "target_id": card["target_id"], "facts": card["facts"]})
            if key in known or view is None:
                continue
            known.add(key)
            shortlist.append({"product_id": card["product_id"], "target_id": card["target_id"], "turn": intent["turn"],
                              "image_id": view["image_id"], "image_version": view["image_version"]})
        intent["shortlist"] = shortlist[-grid_plan.MAX_SHORTLIST:]
        intent["pick_history"] = history[-grid_plan.MAX_PICK_HISTORY:]

    def _clarify(self, cards: list[dict[str, Any]], selected: set[str], axes: list[str]) -> dict[str, Any] | None:
        """F4: one model-written question with 2-3 options over the differing axes. None -> chip fallback."""
        labels = {k: v["label_ko"] for k, v in self.bridge.registry.describe()["product_information"].items()}
        payload = clarify_payload(cards, selected, axes, labels)
        try:
            raw = self.bridge.complete(CLARIFY_INSTRUCTIONS, payload, clarify_schema(tuple(axes)))
            return validate_clarify(raw, axes, labels)
        except Exception:
            return None

    @staticmethod
    def _differing_axes(cards: list[dict[str, Any]], selected: set[str]) -> list[str]:
        chosen = [c for c in cards if c["candidate_id"] in selected]
        rest = [c for c in cards if c["candidate_id"] not in selected]
        axes = []
        for axis in sorted({a for c in cards for a in c["facts"]} - set(NON_HYPOTHESIS_AXES)):
            a = {v for c in chosen for v in c["facts"].get(axis) or []}
            b = {v for c in rest for v in c["facts"].get(axis) or []}
            if a and a != b:
                axes.append(axis)
        return axes

    def _answer(self, intent: dict[str, Any], event: dict[str, Any], scope: str) -> None:
        """Question loop (graph/questions.py): apply an answer, or rebuild the question in the mode the user chose."""
        question, answer = intent.get("ask"), event["answer"]
        intent["answer_changed"] = False
        if not questions.valid_answer(question, answer):
            return
        if answer["choice"] == "switch":
            target = question["target_id"]
            pool = grid_plan.eligible(self.bridge.products(), target, intent, scope)[0]
            candidate = {"id": f"{target}:{question['axis']}", "target_id": target, "axis": question["axis"], "kind": "switch",
                         "values": [o["value"] for o in question["options"] if "value" in o]}
            modes, built = questions.allowed(candidate, pool, self._labels())
            if answer["switch_to"] in built:
                questions.log(intent, {"turn": intent["turn"], "event": "switch", "question_id": question["question_id"],
                                       "decision": {"candidate_id": candidate["id"], "mode": answer["switch_to"],
                                                    "decided_by": "user", "reason": "user_switch", "allowed": modes}})
                intent["ask"] = question | built[answer["switch_to"]] | {
                    "mode": answer["switch_to"], "switch_to": [m for m in modes if m != answer["switch_to"]]}
            return
        intent["answer_changed"] = bool(questions.interpret(intent, question, answer, scope))
        intent["ask"] = None

    def _labels(self) -> dict[str, str]:
        return {k: v["label_ko"] for k, v in self.bridge.registry.describe()["product_information"].items()}

    def _adjust(self, intent: dict[str, Any], event: dict[str, Any], scope: str) -> None:
        action, key = event["action"], event.get("key")
        if action == "pin" and key:
            if not any(p["key"] == key for p in intent["pinned"]):
                intent["pinned"].append({"key": key})
            intent["excluded"] = [k for k in intent["excluded"] if k != key]
        elif action == "unpin" and key:
            intent["pinned"] = [p for p in intent["pinned"] if p["key"] != key]
        elif action == "remove" and key:
            intent["pinned"] = [p for p in intent["pinned"] if p["key"] != key]
            if key not in intent["excluded"]:
                intent["excluded"].append(key)
        elif action == "unhide":
            intent["hidden"] = []
            intent["dislikes"] = {}
        elif action == "reason" and intent["reason_prompt"] and intent["last_grid"]:
            prompt = intent["reason_prompt"]
            if event.get("feature") in prompt["axes"] and prompt["set_id"] == intent["last_grid"]["set_id"]:
                scoring.apply_reason_axis(intent, intent["last_grid"]["cards"], set(prompt["selected"]), event["feature"], scope)
            intent["reason_prompt"] = None
            intent["clarify"] = None
        elif action == "reason_skip":
            intent["reason_prompt"] = None
            intent["clarify"] = None
        elif action == "shortlist_remove" and key:  # F8: leaves value scores untouched
            intent["shortlist"] = [s for s in intent.get("shortlist", []) if s["product_id"] != key]
            intent["kept"] = [k for k in intent["kept"] if k["product_id"] != key]
        elif action in ("memory_off", "memory_on") and key:
            off = [m for m in intent["memory_off"] if m != key]
            intent["memory_off"] = off + [key] if action == "memory_off" else off
        elif action in ("differ", "novelty_yes"):
            intent["memory_mode"] = "dim"
            intent["novelty_prompt"] = "done"
        elif action == "novelty_no":
            intent["novelty_prompt"] = "done"
        elif action == "memory_full":
            intent["memory_mode"] = "normal"
        elif action in ("taste_yes", "taste_no") and intent["taste_prompt"]:
            if action == "taste_yes" and intent["taste_prompt"]["memory_id"] not in intent["memory_off"]:
                intent["memory_off"].append(intent["taste_prompt"]["memory_id"])
            intent["taste_prompt"] = None
        elif action in ("link_off", "link_on"):
            for link in intent["links"]:
                link["enabled"] = action == "link_on"

    def _start(self, intent: dict[str, Any], start: dict[str, Any]) -> None:
        """ADR 0015: gender, situation chip, consented memories and free-situation linking."""
        intent["started"] = True
        intent["gender"] = start.get("gender")
        situation = start.get("situation")
        if situation:
            intent["situations"] = [situation]
        try:
            intent["lt_memories"] = self.bridge.long_term_memories(intent["request_id"])
        except StyleMateError as failure:
            intent["warnings"] = (intent["warnings"] + [f"memory_unavailable:{failure.code}"])[-50:]
            intent["lt_memories"] = []
        past = mem.past_free_situations(intent["lt_memories"])
        if situation and mem.is_free(situation) and past:
            if situation["raw"] in past:
                intent["links"] = [{"raw": situation["raw"], "past": situation["raw"], "enabled": True}]
                return
            try:
                raw = self.bridge.complete(mem.LINK_INSTRUCTIONS, {"current_situation": situation["raw"],
                                                                   "past_situations": past}, mem.link_schema())
                match = mem.validate_link(raw, past)
            except Exception:
                intent["warnings"] = (intent["warnings"] + ["situation_link_unavailable"])[-50:]
                match = None
            if match:
                intent["links"] = [{"raw": situation["raw"], "past": match, "enabled": True}]

    def _interpret(self, intent: dict[str, Any], event: dict[str, Any]) -> None:
        bridge = self.bridge
        request_id = intent["request_id"]

        def record(result: Any, error: StyleMateError | None) -> bool:
            try:
                bridge.record_extraction(request_id, event["command_id"], event["feedback_ref"], result, error)
                return True
            except StyleMateError as failure:  # closed/deleted/superseded: never apply late results
                intent["pending_error"] = intent["pending_error"] or failure.code
                intent["outcome"] = "stale"
                return False

        try:
            sources, aliases = bridge.sources(request_id, event["feedback_ref"])
        except StyleMateError as failure:
            intent["pending_error"], intent["outcome"] = failure.code, "stale"
            return
        try:
            if not sources:
                record({"candidates": [], "questions": []}, None)
                return
            payload, registry = build_payload(sources, intent["targets"], bridge.registry, intent["situations"])
            raw = bridge.complete(PARSE_INSTRUCTIONS, payload, parse_schema_v2())
            parsed = validate_parse_v2(raw, payload, registry, intent["situations"])
            result, warnings = to_v1_extraction(parsed, payload, registry, intent["situations"])
        except StyleMateError as error:
            intent["pending_error"] = error.code
            record(None, error)
            return
        except Exception:  # transport bugs must not escape the interrupt loop
            intent["pending_error"] = "provider_error"
            record(None, StyleMateError("provider_error"))
            return
        for candidate in result["candidates"]:
            candidate["source_ids"] = [aliases[s] for s in candidate["source_ids"]]
        result["questions"] = []  # the graph keeps one question queue (decision 6)
        if not record(result, None):
            return
        turn_tag = f"t{len(intent['processed']) + 1}"
        parsed["aliases"] = aliases
        it.merge_parse(intent, parsed, turn_tag)
        intent["warnings"] = (intent["warnings"] + warnings)[-50:]

    def _update_intent(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        it.derive(intent)
        mem.refresh_priors(intent, it.fixed_axes(intent))
        return {"intent": intent}

    def _propose_hypotheses(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        signature = it.fea_signature(intent)
        if intent["pending_error"]:
            return {"intent": intent}
        selection = None
        if signature == intent["fea_signature"]:
            # F1: also refresh when picks share a value on an axis no hypothesis explores.
            selection = refresh_selection(intent)
            if selection is None:
                return {"intent": intent}
        intent["fea_signature"] = signature
        if not intent["fea_needs"]:
            intent["hypotheses"] = []
            return {"intent": intent}
        scope = it.scope_of(intent)
        excluded: dict[tuple[str, str], list[str]] = {}
        for key in intent["excluded"]:
            target_id, key_scope, axis, value = scoring.split_key(key)
            if key_scope == scope:
                excluded.setdefault((target_id, axis), []).append(value)
        payload = build_hypothesis_payload(intent["fea_needs"], intent["situations"], intent["targets"], self.bridge.registry,
                                           it.fixed_axes(intent),
                                           [{"target_id": t, "axis": a, "values": v} for (t, a), v in excluded.items()],
                                           selection)
        intent["hyp_turn"] = intent["turn"]
        try:
            raw = self.bridge.complete(HYPOTHESIS_INSTRUCTIONS, payload, hypothesis_schema(tuple(payload["registry_values"])))
            hypotheses, warnings = validate_hypotheses(raw, payload, self.bridge.registry)
        except Exception:
            intent["warnings"] = (intent["warnings"] + ["hypotheses_unavailable"])[-50:]
            if selection is None:
                intent["fea_signature"] = ""  # retry on the next turn; a failed refresh keeps the old space
            return {"intent": intent}
        if selection is not None and not hypotheses:
            return {"intent": intent}  # an empty refresh never wipes the current exploration space
        intent["hypotheses"] = hypotheses
        intent["warnings"] = (intent["warnings"] + warnings)[-50:]
        return {"intent": intent}

    @staticmethod
    def _route(state: GraphState) -> str:
        intent = state["intent"]
        if intent["pending_error"]:
            return "hold"
        if intent.get("compare_mode"):
            return it.route(intent)
        if intent["event"]["type"] == "answer" and not intent.get("answer_changed"):
            return "hold"  # unsure / skip / switch / an invalid answer keeps the grid
        if intent["event"]["type"] == "adjust" and intent["event"].get("action") in (
                "reason", "reason_skip", "novelty_no", "taste_no", "shortlist_remove"):
            return "hold"  # a liked-axis answer, a "no" or a shortlist removal keeps the grid
        return it.route(intent)

    def _ask_clarify(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        intent["route_question"] = it.hard_conflict(intent) or "어떤 옷을 찾고 있는지 알려주세요."
        intent["outcome"] = "question"
        return {"intent": intent}

    def _retrieve(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        intent["pool_sizes"] = {t["target_id"]: len(grid_plan.eligible(self.bridge.products(), t["target_id"], intent,
                                                                       it.scope_of(intent))[0]) for t in intent["targets"]}
        return {"intent": intent}

    def _plan_probe(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        scope = it.scope_of(intent)
        turn = intent["turn"] + 1
        products = self.bridge.products()
        if intent.get("compare_mode"):
            intent["planned"] = grid_plan.shortlist_grid(products, intent)
            intent["outcome"] = "grid" if intent["planned"]["status"] == "results" else "no_results"
            return {"intent": intent}
        plan = grid_plan.plan_grid(products, intent["targets"], intent, scope, turn,
                                   seed=f"{intent['request_id']}:{turn}", anchor=intent["anchor"],
                                   kept=grid_plan.kept_products(products, intent))
        intent["planned"] = plan
        intent["anchor"] = None
        intent["all_bad"] = False
        intent["outcome"] = "grid" if plan["status"] == "results" else plan["status"]
        return {"intent": intent}

    def _compose_turn(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        plan = intent.pop("planned", None)
        if intent["pending_error"]:
            intent["outcome"] = "pending"
            return {"intent": intent}
        if plan and plan["status"] == "results":
            command_id = intent["event"].get("command_id") or f"auto-{intent['request_id']}-{intent['turn'] + 1}"
            try:
                published = self.bridge.publish(intent["request_id"], command_id, intent["turn"] + 1, plan)
            except StyleMateError as error:
                intent["outcome"] = "stale" if error.code in ("stale_context", "request_closed", "not_found") else "error"
                return {"intent": intent}
            intent["turn"] += 1
            intent["last_grid"] = published
            if plan.get("compare"):
                published["compare"] = True
                return {"intent": intent}
            converge_ids = sorted(c["product_id"] for c in published["cards"] if c["slot"] == "converge")
            intent["top_history"] = (intent["top_history"] + [converge_ids])[-5:]
            intent["converged"] = grid_plan.converged(intent["top_history"], plan["shortage"])
            intent["shortage"] = plan["shortage"]
            if questions.loop_enabled():
                self._plan_question(intent)
        return {"intent": intent}

    def _plan_question(self, intent: dict[str, Any]) -> None:
        if intent.get("ask"):  # a new grid replaces an unanswered question; ASK_GAP keeps it from coming straight back
            questions.log(intent, {"turn": intent["turn"], "event": "ignored", "question_id": intent["ask"]["question_id"]})
            intent["ask"] = None
        scope = it.scope_of(intent)
        products = self.bridge.products()
        pools = {t["target_id"]: grid_plan.eligible(products, t["target_id"], intent, scope)[0] for t in intent["targets"]}
        fixed = it.fixed_axes(intent)
        for pin in intent["pinned"]:
            target_id, _, axis, _ = scoring.split_key(pin["key"])
            fixed.setdefault(target_id, []).append(axis)
        intent["ask"] = questions.plan(intent, pools, fixed, self._labels())

    def _wait_user(self, state: GraphState) -> dict[str, Any]:
        from langgraph.types import interrupt
        event = interrupt({"request_id": state["intent"]["request_id"]})
        return {"event": event}
