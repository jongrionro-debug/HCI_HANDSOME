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
import sqlite3
import threading
from pathlib import Path
from typing import Any, TypedDict

from ..errors import StyleMateError
from . import grid as grid_plan
from . import intent as it
from . import scoring
from .hypotheses import HYPOTHESIS_INSTRUCTIONS, build_hypothesis_payload, hypothesis_schema, validate_hypotheses
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

    # ---- nodes ------------------------------------------------------------
    def _parse_turn(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        event = state["event"] or {"type": "explore", "command_id": None}
        intent["event"] = {k: event.get(k) for k in ("type", "command_id", "action")}
        intent["pending_error"] = None
        intent["route_question"] = None
        if event.get("command_id") and event["command_id"] in intent["processed"]:
            return {"intent": intent}
        scope = it.scope_of(intent)
        last = intent["last_grid"]
        if event["type"] == "feedback" and event.get("grid") and last and event["grid"]["set_id"] == last["set_id"]:
            signal = event["grid"]
            cards = last["cards"]
            selected = set(signal["selected"])
            by_id = {c["candidate_id"]: c for c in cards}
            intent["all_bad"] = bool(signal["all_bad"])
            changed = [] if signal["all_bad"] else scoring.attribute_grid(intent, cards, selected, scope)
            scoring.apply_dislikes(intent, [by_id[c]["product_id"] for c in signal["dislikes"] if c in by_id], intent["turn"])
            similar = by_id.get(signal["similar"]) if signal.get("similar") else None
            intent["anchor"] = {k: similar[k] for k in ("product_id", "target_id", "facts")} if similar else None
            intent["reason_prompt"] = None
            if selected and not changed and not signal["all_bad"]:
                axes = self._differing_axes(cards, selected)
                if axes:
                    intent["reason_prompt"] = {"set_id": last["set_id"], "selected": sorted(selected), "axes": axes}
        elif event["type"] == "adjust":
            self._adjust(intent, event, scope)
        if event.get("feedback_ref"):
            self._interpret(intent, event)
            if intent["questions"] and event.get("answers_question"):
                intent["questions"].pop(0)
        if event.get("command_id"):
            intent["processed"] = (intent["processed"] + [event["command_id"]])[-200:]
        return {"intent": intent}

    @staticmethod
    def _differing_axes(cards: list[dict[str, Any]], selected: set[str]) -> list[str]:
        chosen = [c for c in cards if c["candidate_id"] in selected]
        rest = [c for c in cards if c["candidate_id"] not in selected]
        axes = []
        for axis in ("Type", "Color", "Fit", "Fabric", "Detail"):
            a = {v for c in chosen for v in c["facts"].get(axis) or []}
            b = {v for c in rest for v in c["facts"].get(axis) or []}
            if a and a != b:
                axes.append(axis)
        return axes

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
        it.merge_parse(intent, parsed, turn_tag)
        intent["warnings"] = (intent["warnings"] + warnings)[-50:]

    def _update_intent(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        it.derive(intent)
        return {"intent": intent}

    def _propose_hypotheses(self, state: GraphState) -> dict[str, Any]:
        intent = deepcopy(state["intent"])
        signature = it.fea_signature(intent)
        if signature == intent["fea_signature"] or intent["pending_error"]:
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
                                           [{"target_id": t, "axis": a, "values": v} for (t, a), v in excluded.items()])
        try:
            raw = self.bridge.complete(HYPOTHESIS_INSTRUCTIONS, payload, hypothesis_schema())
            hypotheses, warnings = validate_hypotheses(raw, payload, self.bridge.registry)
        except Exception:
            intent["warnings"] = (intent["warnings"] + ["hypotheses_unavailable"])[-50:]
            intent["fea_signature"] = ""  # retry on the next turn
            return {"intent": intent}
        intent["hypotheses"] = hypotheses
        intent["warnings"] = (intent["warnings"] + warnings)[-50:]
        return {"intent": intent}

    @staticmethod
    def _route(state: GraphState) -> str:
        intent = state["intent"]
        if intent["pending_error"]:
            return "hold"
        if intent["event"]["type"] == "adjust" and intent["event"].get("action") == "reason":
            return "hold"  # a liked-axis answer updates scores; the grid stays
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
        plan = grid_plan.plan_grid(self.bridge.products(), intent["targets"], intent, scope, turn,
                                   seed=f"{intent['request_id']}:{turn}", anchor=intent["anchor"])
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
            converge_ids = sorted(c["product_id"] for c in published["cards"] if c["slot"] == "converge")
            intent["top_history"] = (intent["top_history"] + [converge_ids])[-5:]
            intent["converged"] = grid_plan.converged(intent["top_history"], plan["shortage"])
            intent["shortage"] = plan["shortage"]
        return {"intent": intent}

    def _wait_user(self, state: GraphState) -> dict[str, Any]:
        from langgraph.types import interrupt
        event = interrupt({"request_id": state["intent"]["request_id"]})
        return {"event": event}
