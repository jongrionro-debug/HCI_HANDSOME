"""ConsumerService glue for the graph engine (STYLEMATE_ENGINE=graph).

The bridge runs every store/catalog access on the service's single DB thread
and reuses the existing write contracts (submit_feedback, record_extraction,
publish_candidates, select_final, end_request). Only shopping requests use the
graph; onboarding keeps the legacy flow.
"""

from __future__ import annotations

import hashlib
from typing import Any

from .. import contracts as c
from ..errors import V1_ERROR_CODES, StyleMateError
from . import intent as it
from . import scoring


class GraphBridge:
    def __init__(self, service: Any) -> None:
        self.s = service
        self.registry = service.registry
        self._cache: dict[str, Any] = {}
        self._targets: list[dict[str, Any]] = []

    # model thread -------------------------------------------------------
    def complete(self, instructions: str, payload: dict[str, Any], schema: dict[str, Any]) -> Any:
        return self.s.gateway.complete(instructions, payload, schema)

    # DB thread helpers ---------------------------------------------------
    def _db(self, function: Any, *args: Any) -> Any:
        return self.s._run(function, *args)

    def _check_live(self, request_id: str) -> dict[str, Any]:
        # Resume ordering: a closed/deleted/inactive request never gets late results.
        if not self.s._exists(request_id):
            raise StyleMateError("not_found")
        snapshot = self.s._snapshot(request_id)
        if snapshot["request"]["status"] != "open" or self.s._journal.active() != request_id:
            raise StyleMateError("stale_context")
        return snapshot

    def sources(self, request_id: str, feedback_ref: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, str]]:
        def run() -> tuple[list[dict[str, Any]], dict[str, str]]:
            from ..consumer_state import canonical
            snapshot = self._check_live(request_id)
            feedback = next(f for f in snapshot["feedback"] if f["id"] == feedback_ref["id"])
            if feedback["reaction"] == "question_skipped":
                return [], {}
            refs = {r["id"] for r in feedback["evidence_refs"]}
            sources, aliases = [], {}
            for evidence in snapshot["evidence"]:
                if evidence["id"] not in refs or evidence["kind"] not in ("user_text", "image_selection"):
                    continue
                alias = f"e{len(sources) + 1:03}"
                aliases[alias] = evidence["id"]
                content = evidence["quote"]
                if evidence["selection"]:
                    selection = evidence["selection"]
                    product = self.s._catalog.get_product_map(selection["product_id"])
                    content = canonical({"target_id": selection["target_id"], "product_assertions": product["assertions"],
                                         "part_ref": selection["part_ref"], "reason": None})
                sources.append({"source_id": alias, "kind": evidence["kind"], "content": content, "selector": evidence["selector"]})
            return sources, aliases
        return self._db(run)

    def record_extraction(self, request_id: str, command_id: str, feedback_ref: dict[str, Any],
                          result: Any, error: StyleMateError | None) -> None:
        def run() -> None:
            from ..app import _error
            self._check_live(request_id)
            key = hashlib.sha256(f"graph-parse-v2:{feedback_ref['id']}:{type(self.s.gateway).__name__}:"
                                 f"{getattr(self.s.gateway, 'model', 'injected')}".encode()).hexdigest()
            if error is None:
                self.s._apply(request_id, self.s._step(command_id, "graph-extraction"), [{"op": "record_extraction",
                    "feedback_ref": feedback_ref, "extraction_key": key, "result": result, "error": None}])
                return
            public = _error(error)
            if public["code"] not in V1_ERROR_CODES:
                public = _error(StyleMateError("provider_error"))
            self.s._apply(request_id, self.s._step(command_id, "graph-extraction-failed"), [{"op": "record_extraction",
                "feedback_ref": feedback_ref, "extraction_key": key, "result": None, "error": public}])
        self._db(run)

    def products(self) -> list[dict[str, Any]]:
        """Product views per request target (garment match), cached per catalog version."""
        def run() -> list[dict[str, Any]]:
            from ..registry import product_fact_statuses
            catalog = self.s._catalog
            version = catalog.current_versions([], [])["catalog_version"]
            key = f"{version}:{sorted((t['target_id'], t['garment_type']) for t in self._targets)}"
            if key in self._cache:
                return self._cache[key]
            records = catalog.export_records()
            ids = [r["product_id"] for r in records]
            images = [i["image_id"] for r in records for i in r["images"][:1] if i["kind"] == "local"]
            # current_versions accepts at most 256 IDs per call; real catalogs are larger (ADR 0014).
            maps, image_versions = {}, {}
            for start in range(0, max(len(ids), len(images)), 256):
                versions = catalog.current_versions(ids[start:start + 256], images[start:start + 256])
                maps.update({p["product_id"]: p["map_version"] for p in versions["products"]})
                image_versions.update({i["image_id"]: i["version"] for i in versions["images"]})
            views = []
            for record in records:
                try:
                    product_map = catalog.get_product_map(record["product_id"])
                except Exception:
                    continue
                statuses = product_fact_statuses(product_map["registry_version"])
                facts: dict[str, list[str]] = {}
                for assertion in product_map["assertions"]:
                    obs = assertion["observation"]
                    if obs["domain"] == "PI" and obs["values"] and assertion["status"] in statuses:
                        facts[obs["feature"]] = sorted(obs["values"])
                image = next((i for i in record["images"][:1] if i["kind"] == "local"), None)
                price = record["raw_metadata"].get("price_amount")
                for target in self._targets:
                    if target["garment_type"] != record["garment_type"]:
                        continue
                    views.append({"product_id": record["product_id"], "target_id": target["target_id"],
                                  "product_map_version": maps.get(record["product_id"], product_map["map_version"]),
                                  "image_id": image["image_id"] if image else None,
                                  "image_version": image_versions.get(image["image_id"]) if image else None,
                                  "facts": facts, "price": price if type(price) is int else None})
            self._cache = {key: views}
            return views
        return self._db(run)

    def publish(self, request_id: str, command_id: str, turn: int, plan: dict[str, Any]) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            from ..consumer_state import canonical
            snapshot = self._check_live(request_id)
            cards, meta = [], []
            for position, card in enumerate(plan["cards"], 1):
                digest = hashlib.sha256(canonical({"request": request_id, "turn": turn, "target": card["target_id"],
                                                   "product": card["product_id"]}).encode()).hexdigest()
                candidate_id = "candidate-" + digest[:32]
                cards.append({"candidate_id": candidate_id, "target_id": card["target_id"], "product_id": card["product_id"],
                              "product_map_version": card["product_map_version"], "image_id": card["image_id"],
                              "image_version": card["image_version"], "position": position})
                meta.append({"candidate_id": candidate_id, "target_id": card["target_id"], "product_id": card["product_id"],
                             "slot": card["slot"], "facts": card["facts"]})
            catalog = self.s._catalog.current_versions(sorted({c["product_id"] for c in cards}),
                                                       sorted({c["image_id"] for c in cards if c["image_id"]}))
            axes = sorted({e["axis"] for focus in plan["exposures"].values() for e in focus})
            basis = self.s._basis(snapshot, refs=[]) | {"catalog": catalog}
            round_obj = self.s._store.publish_candidates(
                self.s.user_id, request_id, batch_id=self.s._step(command_id, f"graph-grid-{turn}"),
                plan={"cards": cards, "compared_features": [{"domain": "PI", "feature": a} for a in axes],
                      "questions": [], "basis": basis}, catalog_freshness=self.s._catalog)
            return {"set_id": round_obj["candidate_set_ref"]["id"], "round_id": round_obj["id"], "cards": meta}
        return self._db(run)


def _labels(service: Any) -> dict[str, str]:
    return {k: v["label_ko"] for k, v in service.registry.describe()["product_information"].items()}


def graph_view(service: Any, request_id: str) -> dict[str, Any] | None:
    intent = service._graph.intent(request_id)
    if intent is None:
        return None
    scope = it.scope_of(intent)
    labels = _labels(service)
    question = intent.get("route_question") or (intent["questions"][0]["text"] if intent["questions"] else None)
    last = intent["last_grid"] or {"set_id": None, "cards": []}
    prompt = intent["reason_prompt"]
    return {
        "outcome": intent["outcome"], "set_id": last["set_id"],
        "slots": {c["candidate_id"]: c["slot"] for c in last["cards"]},
        "chips": scoring.chips(intent, scope, labels),
        "question": question,
        "reason_prompt": ({"axes": [{"feature": a, "label_ko": labels.get(a, a)} for a in prompt["axes"]]} if prompt else None),
        "hypotheses": [{"target_id": h["target_id"], "feature": h["axis"], "label_ko": labels.get(h["axis"], h["axis"]),
                        "values": h["values"], "reason": h["reason"]} for h in intent["hypotheses"]],
        "situations": [{"key": s["key"], "value": s["value"], "raw": s["raw"]} for s in intent["situations"]],
        "converged": intent["converged"], "shortage": intent.get("shortage", False),
        "hidden_count": len(intent["hidden"]), "unresolved_hard_fea": intent["unresolved_hard_fea"],
        "turn": intent["turn"],
    }


def run_turn(service: Any, request_id: str, command_id: str, event: dict[str, Any]) -> None:
    """Start one graph turn on the model executor; the UI polls state."""
    snapshot = service._snapshot(request_id)
    targets = snapshot["request"]["targets"]
    service._graph_bridge._targets = targets
    event = event | {"command_id": command_id}

    def calculate() -> dict[str, Any]:
        return service._graph.run_turn(request_id, targets, event)

    def apply_result(future: Any) -> None:
        intent = future.result()
        outcome = intent["outcome"]
        if intent["pending_error"]:
            service._journal.set_operation(request_id, "interpretation_pending", intent["pending_error"])
        elif outcome in ("no_results", "hidden_empty"):
            service._journal.set_operation(request_id, "no_results")
        elif outcome == "stale":
            service._journal.set_operation(request_id, "stale", "stale_context")
        elif outcome == "error":
            service._journal.set_operation(request_id, "error", "storage_failed")
        else:
            service._journal.set_operation(request_id, "idle")

    service._submit_model(request_id, calculate, apply_result)


def handle_command(service: Any, snapshot: dict[str, Any], command: dict[str, Any], command_id: str) -> bool:
    """Run a graph-mode command for an open shopping request. Return False to fall back to legacy."""
    action = command["action"]
    op = action["op"]
    request_id = snapshot["request"]["id"]
    if snapshot["request"]["mode"] != "shopping":
        return False
    if op in ("submit_feedback", "grid_feedback", "explore", "adjust_intent", "retry_extraction") and request_id in service._jobs:
        raise StyleMateError("context_blocked")
    if op == "submit_feedback":
        if service._latest_pending(snapshot):
            raise StyleMateError("context_blocked")
        receipt = service._apply(request_id, service._step(command_id, "intake"), [action], command["expected"])
        run_turn(service, request_id, command_id, {"type": "feedback", "feedback_ref": service._feedback_ref(receipt),
                                                   "grid": None, "answers_question": action["question_id"] is not None})
        return True
    if op == "grid_feedback":
        intent = service._graph.intent(request_id)
        last = intent["last_grid"] if intent else None
        if not last or last["set_id"] != action["candidate_set_id"]:
            raise StyleMateError("stale_context")
        shown = {c["candidate_id"] for c in last["cards"]}
        selected = [s["candidate_id"] for s in action["selections"]]
        if (not isinstance(action["dislikes"], list) or not set(action["dislikes"]) <= shown or not set(selected) <= shown
                or (action["similar"] is not None and action["similar"] not in shown) or not isinstance(action["all_bad"], bool)
                or len(action["selections"]) > 8 or (action["all_bad"] and selected)):
            raise StyleMateError("invalid_input")
        text = action["text"] if isinstance(action["text"], str) and action["text"].strip() else None
        feedback_ref = None
        if selected or text or action["all_bad"]:
            if service._latest_pending(snapshot):
                raise StyleMateError("context_blocked")
            reaction = "selected" if selected else "none" if action["all_bad"] else "text_only"
            receipt = service._apply(request_id, service._step(command_id, "intake"), [{
                "op": "submit_feedback", "round_id": action["round_id"], "candidate_set_id": action["candidate_set_id"],
                "reaction": reaction, "selections": action["selections"], "text": text, "question_id": action["question_id"]}],
                command["expected"])
            feedback_ref = service._feedback_ref(receipt)
        run_turn(service, request_id, command_id, {"type": "feedback", "feedback_ref": feedback_ref,
            "answers_question": bool(text), "grid": {"set_id": action["candidate_set_id"], "selected": selected,
            "dislikes": list(action["dislikes"]), "similar": action["similar"], "all_bad": action["all_bad"]}})
        return True
    if op == "adjust_intent":
        if action["action"] not in ("pin", "unpin", "remove", "unhide", "reason"):
            raise StyleMateError("invalid_input")
        run_turn(service, request_id, command_id, {"type": "adjust", "action": action["action"], "key": action["key"],
                                                   "feature": action["feature"]})
        return True
    if op == "explore":
        run_turn(service, request_id, command_id, {"type": "explore"})
        return True
    if op == "retry_extraction":
        run_turn(service, request_id, command_id, {"type": "feedback", "feedback_ref": action["feedback_ref"], "grid": None})
        return True
    if op == "respond_comparison":
        raise StyleMateError("invalid_input")
    if op == "select_final":
        intent = service._graph.intent(request_id)
        if intent and intent["unresolved_hard_fea"]:
            raise StyleMateError("context_blocked", "필수 기능 요구의 상품 근거를 먼저 확인하거나 조건을 조정해 주세요.")
        service._apply(request_id, service._step(command_id, "apply"), [action], command["expected"])
        service._jobs.pop(request_id, None)
        service._journal.clear_operation(request_id)
        return True
    return False


def start(service: Any, request_id: str, command_id: str, feedback_ref: dict[str, Any] | None) -> None:
    event = {"type": "feedback", "feedback_ref": feedback_ref, "grid": None} if feedback_ref else {"type": "explore"}
    run_turn(service, request_id, command_id, event)


__all__ = ["GraphBridge", "graph_view", "handle_command", "run_turn", "start", "c"]
