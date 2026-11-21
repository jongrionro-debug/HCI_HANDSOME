"""ConsumerService glue for the graph engine (STYLEMATE_ENGINE=graph).

The bridge runs every store/catalog access on the service's single DB thread
and reuses the existing write contracts (submit_feedback, record_extraction,
publish_candidates, select_final, end_request). Only shopping requests use the
graph; onboarding keeps the legacy flow.
"""

from __future__ import annotations

import hashlib
import os
from typing import Any
from urllib.parse import quote

from .. import contracts as c
from ..errors import V1_ERROR_CODES, StyleMateError
from . import intent as it
from . import memory as mem
from . import scoring
from .labels import VALUE_LABELS_KO, value_label
from .summary_text import POLISH_INSTRUCTIONS, polish_payload, polish_schema, validate_polish

READY_SHORTLIST = 3  # F9: "이제 후보함에서 골라도 돼요" after 3 picks + 2 chips, or convergence
READY_CHIPS = 2


def profile_rewrite_enabled() -> bool:
    """F3: STYLEMATE_PROFILE_REWRITE=off skips the profile rewrite step (default on, ADR 0015 decision 6)."""
    return os.environ.get("STYLEMATE_PROFILE_REWRITE", "on").strip().lower() not in ("off", "0", "false", "no")


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

    def long_term_memories(self, request_id: str) -> list[dict[str, Any]]:
        return self._db(self.long_term_now, request_id)

    def long_term_now(self, request_id: str) -> list[dict[str, Any]]:
        """Consented, confirmed, active long-term memories with their PI bindings (ADR 0015 decision 4)."""
        snapshot = self.s._snapshot(request_id)
        consented = {c["memory_id"] for c in snapshot["consents"] if c["status"] == "active"}
        result = []
        for m in snapshot["memories"]:
            if (m["scope"] != "long_term" or m["status"] != "active" or not m["confirmed"]
                    or m["consent_ref"] is None or m["id"] not in consented or m["kind"] == "situation"):
                continue
            bindings = [{"feature": b["feature"], "values": list(b["values"] or []), "polarity": b["polarity"]}
                        for b in snapshot["bindings"] if b["memory_id"] == m["id"] and b["domain"] == "PI"
                        and b["status"] in ("candidate", "active") and b["polarity"] in ("prefer", "avoid")]
            result.append({"memory_id": m["id"], "content": m["content"], "conditions": dict(m["conditions"]),
                           "garment_type": m["selector"]["garment_type"], "polarity": m["polarity"],
                           "bindings": bindings, "created_at": m["created_at"]})
        return result

    def products(self) -> list[dict[str, Any]]:
        return self._db(self.products_now)

    def products_now(self) -> list[dict[str, Any]]:
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
                                  "facts": facts, "price": price if type(price) is int else None,
                                  "gender": record["raw_metadata"].get("gender")})
            self._cache = {key: views}
            return views
        return run()

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
    chips = [chip | {"value_label_ko": value_label(chip["feature"], chip["value"]), "evidence": _chip_evidence(intent, chip)}
             for chip in scoring.chips(intent, scope, labels)]
    shortlist = _shortlist_view(service, intent, last)
    clarify = intent.get("clarify") if prompt else None
    return {
        "outcome": intent["outcome"], "set_id": last["set_id"],
        "slots": {c["candidate_id"]: c["slot"] for c in last["cards"]},
        "chips": chips,
        "question": question,
        "reason_prompt": ({"axes": [{"feature": a, "label_ko": labels.get(a, a)} for a in prompt["axes"]],
                           "question": clarify["question"] if clarify else None,
                           "options": [dict(o) for o in clarify["options"]] if clarify else None} if prompt else None),
        "hypotheses": [{"target_id": h["target_id"], "feature": h["axis"], "label_ko": labels.get(h["axis"], h["axis"]),
                        "values": h["values"], "reason": h["reason"]} for h in intent["hypotheses"]],
        "situations": [{"key": s["key"], "value": s["value"], "raw": s["raw"]} for s in intent["situations"]],
        "converged": intent["converged"], "shortage": intent.get("shortage", False),
        "hidden_count": len(intent["hidden"]), "unresolved_hard_fea": intent["unresolved_hard_fea"],
        "turn": intent["turn"],
        # ADR 0015
        "gender": intent.get("gender"),
        "memory": {"chips": [dict(c) for c in intent.get("memory_chips", [])], "mode": intent.get("memory_mode", "normal"),
                   "links": [dict(l) for l in intent.get("links", [])],
                   "novelty_prompt": intent.get("novelty_prompt") == "ask",
                   "taste_prompt": dict(intent["taste_prompt"]) if intent.get("taste_prompt") else None},
        "summary": public_summary(service._graph.summary(request_id)),
        # jaehyun_work
        "value_labels": VALUE_LABELS_KO,
        "compare": bool(last.get("compare")),
        "shortlist": shortlist,
        "progress": {"turn": intent["turn"], "shortlist_count": len(shortlist), "converged": intent["converged"],
                     "ready": bool(intent["converged"] or (len(shortlist) >= READY_SHORTLIST and len(chips) >= READY_CHIPS))},
        "memory_notice": _memory_notice(intent),
        "musts": [{"quote": n["quote"], "content": n["content"]} for n in intent["fea_needs"] if n["strength"] == "hard"],
        "profile_rewrite": profile_rewrite_enabled(),
    }


def _chip_evidence(intent: dict[str, Any], chip: dict[str, Any]) -> dict[str, int] | None:
    """F11: "고르신 6장 중 5장이 여유 핏" from the request's pick history; None without history."""
    picks = [p for p in intent.get("pick_history", []) if p["target_id"] == chip["target_id"] and p["facts"].get(chip["feature"])]
    if not picks:
        return None
    return {"with": sum(chip["value"] in p["facts"][chip["feature"]] for p in picks), "of": len(picks)}


def _shortlist_view(service: Any, intent: dict[str, Any], last: dict[str, Any]) -> list[dict[str, Any]]:
    """F8: every pick of the request with its image, title and the candidate ID when it is on screen."""
    on_screen = {(c["product_id"], c["target_id"]): c["candidate_id"] for c in last["cards"]}
    result = []
    for item in intent.get("shortlist", []):
        try:
            record = service._catalog.get_record(item["product_id"])
        except Exception:
            continue
        image_url = None
        if item["image_id"] and any(i["image_id"] == item["image_id"] and i["kind"] == "local" for i in record["images"]):
            image_url = f"/api/images/{quote(item['image_id'], safe='')}?version={item['image_version']}"
        result.append({"product_id": item["product_id"], "target_id": item["target_id"], "title": record["title"],
                       "turn": item["turn"], "image_url": image_url,
                       "candidate_id": on_screen.get((item["product_id"], item["target_id"]))})
    return result


def _memory_notice(intent: dict[str, Any]) -> dict[str, Any] | None:
    """F10: on the first memory-applied grid, which consented memories shaped it and where they came from."""
    chips = [c for c in intent.get("memory_chips", []) if c["enabled"]]
    if not chips or intent["turn"] > 1:
        return None
    by_id = {m["memory_id"]: m for m in intent.get("lt_memories", [])}
    sources = []
    for chip in chips:
        conditions = (by_id.get(chip["memory_id"]) or {}).get("conditions") or {}
        label = " · ".join(conditions.values()) if chip["kind"] == "situation" and conditions else None
        if label not in sources:
            sources.append(label)
    return {"lines": [c["text"] for c in chips][:3], "situations": [s for s in sources if s],
            "baseline": None in sources, "mode": intent.get("memory_mode", "normal")}


def public_summary(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if summary is None:
        return None
    return {"status": summary["status"], "situation_label": summary.get("situation_label"),
            "proposals": [{"id": p["id"], "text": p["text"], "suggested": "baseline" if p["baseline"] else
                           ("situation" if summary.get("conditions") else "baseline"), "source": p["source"]}
                          for p in summary.get("proposals", [])],
            "saved": summary.get("saved", []), "profile": summary.get("profile"),
            "profile_view": summary.get("profile_view")}


def _valid_liked(liked: dict[str, Any], cards: dict[str, dict[str, Any]], selected: set[str]) -> bool:
    """Liked axes per selected card: each must be a known PI axis on that card."""
    from .hypotheses import NON_HYPOTHESIS_AXES
    for candidate_id, axes in liked.items():
        if candidate_id not in selected or not isinstance(axes, list) or len(axes) > 8:
            return False
        if len(set(map(str, axes))) != len(axes) or not all(isinstance(a, str) for a in axes):
            return False
        facts = cards[candidate_id]["facts"]
        if any(a not in facts or a in NON_HYPOTHESIS_AXES for a in axes):
            return False
    return True


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


# ---- ADR 0015 end summary ------------------------------------------------------------
def _evidence_for(service: Any, snapshot: dict[str, Any], proposal: dict[str, Any],
                  facts: dict[str, dict[str, list[str]]]) -> list[dict[str, Any]]:
    """Evidence refs that back one proposal. Image evidence comes from ONE candidate set
    (the latest where the user picked a product with these values), so the closed-session
    review can show its comparison basis."""
    from ..app import _ref
    by_id = {e["id"]: e for e in snapshot["evidence"]}
    if proposal["evidence_ids"]:
        return [_ref("evidence", by_id[i]) for i in proposal["evidence_ids"] if i in by_id][:64]
    picks = [e for e in snapshot["evidence"] if e["kind"] == "image_selection" and e["selection"]]

    def matches(e: dict[str, Any]) -> bool:
        product = e["selection"]["product_id"]
        if proposal["source"] == "final":
            return product == proposal.get("product_id")
        return all(set(values) & set(facts.get(product, {}).get(axis) or []) for axis, values in proposal["pi"])

    hits = [e for e in picks if matches(e)]
    if not hits:
        return []
    latest = hits[-1]["selection"]["candidate_set_ref"]["id"]
    return [_ref("evidence", e) for e in hits if e["selection"]["candidate_set_ref"]["id"] == latest][:64]


def _prepare(service: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
    request_id = snapshot["request"]["id"]
    if snapshot["request"]["status"] != "open":
        raise StyleMateError("request_closed")
    intent = service._graph.intent(request_id)
    if intent is None:
        raise StyleMateError("stale_context")
    service._graph_bridge._targets = snapshot["request"]["targets"]
    views = service._graph_bridge.products_now()
    facts = {v["product_id"]: v["facts"] for v in views}
    final = None
    chosen = snapshot["request"]["final_selection"]
    if chosen:
        view = next((v for v in views if v["product_id"] == chosen["product_id"] and v["target_id"] == chosen["target_id"]), None)
        if view:
            final = {"product_id": view["product_id"], "target_id": view["target_id"], "facts": view["facts"]}
    items = []
    for proposal in mem.proposals(intent, final, _labels(service)):
        refs = _evidence_for(service, snapshot, proposal, facts)
        if refs:
            items.append(proposal | {"source_refs": refs})
    for index, item in enumerate(items, 1):
        item["id"] = f"p{index}"
    conditions = mem.situation_conditions(intent)
    summary = {"status": "polishing" if items else "draft", "proposals": items, "conditions": conditions,
               "situation_label": mem.situation_label(intent), "saved": [], "profile": None, "profile_view": None}
    service._graph.put_summary(request_id, summary)
    if items:
        _polish(service, request_id, items, summary["situation_label"])
    return summary


def _polish(service: Any, request_id: str, items: list[dict[str, Any]], situation: str | None) -> None:
    """F2: the model rewrites each code-built sentence from its materials. Saving waits for this;
    a failure or a sentence that drops a value keeps the rule sentence (fake provider: always)."""
    labels = _labels(service)

    def calculate() -> dict[str, str]:
        payload = polish_payload(items, situation, labels)
        raw = service.gateway.complete(POLISH_INSTRUCTIONS, payload, polish_schema())
        return validate_polish(raw, items)

    def apply_result(future: Any) -> None:
        summary = service._graph.summary(request_id)
        if summary is None or summary["status"] != "polishing":
            return
        try:
            texts = future.result()
        except Exception:
            texts = {}
        for proposal in summary["proposals"]:
            if proposal["id"] in texts:
                proposal["text"] = texts[proposal["id"]]
        summary["status"] = "draft"
        service._graph.put_summary(request_id, summary)
        service._journal.set_operation(request_id, "idle")

    service._submit_model(request_id, calculate, apply_result)


def _accept(service: Any, request_id: str, command_id: str, purpose: str, memory_ref: dict[str, Any],
            step: str) -> dict[str, Any]:
    """Issue the server display for a memory and record the user's accept on it (existing contract)."""
    snapshot = service._snapshot(request_id)
    display_id = service._prepare_review(snapshot, {"purpose": purpose, "subject_refs": [memory_ref], "proposed_text": None},
                                         service._step(command_id, step + "-display"))
    display_ref = {"type": "display", "id": display_id, "version": 1}
    return service._store.record_user_event(service.user_id, request_id, command_id=service._step(command_id, step + "-event"),
                                            display_ref=display_ref, purpose=purpose, expected=service._expected(snapshot))


def _current(service: Any, request_id: str, memory_id: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from ..app import _ref
    snapshot = service._snapshot(request_id)
    memory = next(m for m in snapshot["memories"] if m["id"] == memory_id)
    bindings = [b for b in snapshot["bindings"] if b["memory_id"] == memory_id and b["status"] in ("candidate", "active")]
    return _ref("memory", memory), [_ref("binding", b) for b in bindings]


def _save(service: Any, snapshot: dict[str, Any], choices: list[dict[str, Any]], command_id: str) -> None:
    """Chosen sentences -> short-term memory -> end -> content confirmation -> future-reuse consent.

    One end-summary button is the user's confirmation AND consent for that exact
    sentence (ADR 0015 decision 6); every step still goes through the store's
    display/event proofs, so the storage contract is unchanged.
    """
    request_id = snapshot["request"]["id"]
    summary = service._graph.summary(request_id)
    if snapshot["request"]["status"] != "open" or not summary or summary["status"] != "draft":
        raise StyleMateError("stale_context")
    by_id = {p["id"]: p for p in summary["proposals"]}
    picked = []
    for choice in choices:
        if (not isinstance(choice, dict) or set(choice) != {"id", "choice"} or choice["id"] not in by_id
                or choice["choice"] not in ("baseline", "situation", "skip")
                or (choice["choice"] == "situation" and not summary["conditions"])):
            raise StyleMateError("invalid_input")
        if choice["choice"] != "skip":
            picked.append((by_id[choice["id"]], choice["choice"]))
    targets = {t["target_id"]: t for t in snapshot["request"]["targets"]}
    actions = []
    for proposal, scope in picked:
        garment = targets[proposal["target_id"]]["garment_type"] if proposal["target_id"] in targets else None
        content = {"kind": "preference", "content": proposal["text"], "fact": None,
                   "selector": {"garment_type": garment, "slot_id": None},
                   "conditions": dict(summary["conditions"]) if scope == "situation" else {},
                   "polarity": proposal["polarity"], "strength": "soft", "valid_from": None, "valid_until": None}
        specs = [{"domain": "PI", "feature": axis, "values": list(values), "match": "any",
                  "polarity": proposal["polarity"], "strength": "soft"} for axis, values in proposal["pi"]]
        actions.append({"op": "create", "memory": content, "source_refs": proposal["source_refs"], "bindings": specs,
                        "confirmation_event_ref": None, "consent_event_ref": None})
    created = []
    if actions:
        receipt = service._apply(request_id, service._step(command_id, "summary-create"), actions)
        created = [r["id"] for r in receipt["changed_refs"] if r["type"] == "memory"]
    service._apply(request_id, service._step(command_id, "summary-end"), [{"op": "end_request"}])
    service._jobs.pop(request_id, None)
    service._journal.clear_operation(request_id)
    saved = []
    for index, memory_id in enumerate(created):
        tag = f"summary-{index}"
        memory_ref, _ = _current(service, request_id, memory_id)
        event = _accept(service, request_id, command_id, "confirm_content", memory_ref, tag + "-confirm")
        service._apply(request_id, service._step(command_id, tag + "-confirm"), [{"op": "confirm", "memory_id": memory_id,
            "expected_version": memory_ref["version"], "confirmation_event_ref": event, "binding_confirmations": []}])
        memory_ref, binding_refs = _current(service, request_id, memory_id)
        if binding_refs:
            event = _accept(service, request_id, command_id, "confirm_bindings", memory_ref, tag + "-bindings")
            service._apply(request_id, service._step(command_id, tag + "-bindings"), [{"op": "confirm_bindings",
                "memory_id": memory_id, "expected_version": memory_ref["version"], "confirmation_event_ref": event,
                "binding_confirmations": binding_refs}])
            memory_ref, _ = _current(service, request_id, memory_id)
        event = _accept(service, request_id, command_id, "future_reuse", memory_ref, tag + "-consent")
        service._apply(request_id, service._step(command_id, tag + "-consent"), [{"op": "promote", "memory_id": memory_id,
            "expected_version": memory_ref["version"], "consent_event_ref": event}])
        saved.append(picked[index][0]["text"])
    memories = service._graph_bridge.long_term_now(request_id)
    rewrite = bool(saved) and profile_rewrite_enabled()
    summary |= {"status": "saved", "saved": saved, "profile_view": mem.profile_view(memories),
                "profile": {"status": "running" if rewrite else "skipped", "changes": []}}
    service._graph.put_summary(request_id, summary)
    if rewrite:
        _rewrite_profile(service, request_id, memories)


def _rewrite_profile(service: Any, request_id: str, memories: list[dict[str, Any]]) -> None:
    """LLM rewrites the consented memories into a short profile; only changed lines are re-asked."""
    def calculate() -> list[dict[str, Any]]:
        raw = service.gateway.complete(mem.PROFILE_INSTRUCTIONS, mem.profile_payload(memories), mem.profile_schema())
        return mem.validate_profile(raw, memories)

    def apply_result(future: Any) -> None:
        summary = service._graph.summary(request_id)
        if summary is None:
            return
        try:
            changes = future.result()
            summary["profile"] = {"status": "ready" if changes else "unchanged", "changes": changes}
        except Exception:
            summary["profile"] = {"status": "unavailable", "changes": []}
        service._graph.put_summary(request_id, summary)
        service._journal.set_operation(request_id, "idle")

    service._submit_model(request_id, calculate, apply_result)


def _profile(service: Any, snapshot: dict[str, Any], choices: list[dict[str, Any]], command_id: str) -> None:
    """Accepted profile lines replace their long-term memory; the original is kept as superseded."""
    from ..app import _ref
    request_id = snapshot["request"]["id"]
    summary = service._graph.summary(request_id)
    profile = (summary or {}).get("profile") or {}
    if profile.get("status") != "ready":
        raise StyleMateError("stale_context")
    changes = {c["memory_id"]: c for c in profile["changes"]}
    for choice in choices:
        if (not isinstance(choice, dict) or set(choice) != {"id", "choice"} or choice["id"] not in changes
                or choice["choice"] not in ("accept", "keep")):
            raise StyleMateError("invalid_input")
    for index, choice in enumerate(c for c in choices if c["choice"] == "accept"):
        change = changes[choice["id"]]
        snap = service._snapshot(request_id)
        memory = next((m for m in snap["memories"] if m["id"] == change["memory_id"] and m["status"] == "active"), None)
        if memory is None:
            raise StyleMateError("stale_context")
        content = {k: memory[k] for k in c.MemoryContent.__required_keys__} | {"content": change["text"]}
        specs = [{k: b[k] for k in c.PIBindingSpec.__required_keys__} if b["domain"] == "PI"
                 else {k: b[k] for k in c.FEABindingSpec.__required_keys__}
                 for b in snap["bindings"] if b["memory_id"] == memory["id"] and b["status"] in ("candidate", "active")]
        memory_ref = _ref("memory", memory)
        subjects = [memory_ref] + list(memory["source_refs"])
        meaning = content | {"scope": "long_term"}
        events = []
        for purpose, refs in (("replace", subjects), ("future_reuse", [memory_ref])):
            display = service._store.issue_display(service.user_id, request_id, purpose=purpose,
                snapshot={"meaning": meaning, "bindings": specs, "subject_refs": refs}, basis=service._basis(snap, refs=refs))
            events.append(service._store.record_user_event(service.user_id, request_id,
                command_id=service._step(command_id, f"profile-{index}-{purpose}"), display_ref=_ref("display", display),
                purpose=purpose, expected=service._expected(snap)))
        service._apply(request_id, service._step(command_id, f"profile-{index}"), [{"op": "replace", "memory_id": memory["id"],
            "expected_version": memory["version"], "memory": content, "bindings": specs, "source_refs": list(memory["source_refs"]),
            "confirmation_event_ref": events[0], "consent_event_ref": events[1]}])
    memories = service._graph_bridge.long_term_now(request_id)
    summary["profile"] = {"status": "done", "changes": []}
    summary["profile_view"] = mem.profile_view(memories)
    service._graph.put_summary(request_id, summary)


def summary_command(service: Any, snapshot: dict[str, Any], command: dict[str, Any], command_id: str) -> None:
    action = command["action"]
    if action["step"] not in ("prepare", "save", "profile") or not isinstance(action["choices"], list) or len(action["choices"]) > 40:
        raise StyleMateError("invalid_input")
    if action["step"] == "prepare":
        if action["choices"]:
            raise StyleMateError("invalid_input")
        _prepare(service, snapshot)
    elif action["step"] == "save":
        _save(service, snapshot, action["choices"], command_id)
    else:
        _profile(service, snapshot, action["choices"], command_id)


ADJUST_ACTIONS = ("pin", "unpin", "remove", "unhide", "reason", "memory_off", "memory_on", "differ", "memory_full",
                  "novelty_yes", "novelty_no", "taste_yes", "taste_no", "link_off", "link_on",
                  "reason_skip", "shortlist_remove", "shortlist_compare")


def handle_command(service: Any, snapshot: dict[str, Any], command: dict[str, Any], command_id: str) -> bool:
    """Run a graph-mode command for an open shopping request. Return False to fall back to legacy."""
    action = command["action"]
    op = action["op"]
    request_id = snapshot["request"]["id"]
    if snapshot["request"]["mode"] != "shopping":
        return False
    if op in ("submit_feedback", "grid_feedback", "explore", "adjust_intent", "retry_extraction", "graph_summary") and request_id in service._jobs:
        raise StyleMateError("context_blocked")
    if op == "submit_feedback":
        if service._latest_pending(snapshot):
            raise StyleMateError("context_blocked")
        receipt = service._apply(request_id, service._step(command_id, "intake"), [action], command["expected"])
        run_turn(service, request_id, command_id, {"type": "feedback", "feedback_ref": service._feedback_ref(receipt),
                                                   "grid": None, "answers_question": action["question_id"] is not None,
                                                   "novel_hint": bool(action["text"] and mem.NOVEL_HINT.search(action["text"]))})
        return True
    if op == "grid_feedback":
        intent = service._graph.intent(request_id)
        last = intent["last_grid"] if intent else None
        if not last or last["set_id"] != action["candidate_set_id"]:
            raise StyleMateError("stale_context")
        by_id = {c["candidate_id"]: c for c in last["cards"]}
        shown = set(by_id)
        selected = [s["candidate_id"] for s in action["selections"]]
        liked = action.get("liked", {})
        if (not isinstance(action["dislikes"], list) or not set(action["dislikes"]) <= shown or not set(selected) <= shown
                or (action["similar"] is not None and action["similar"] not in shown) or not isinstance(action["all_bad"], bool)
                or len(action["selections"]) > 8 or not isinstance(liked, dict) or not _valid_liked(liked, by_id, set(selected))):
            raise StyleMateError("invalid_input")
        # Earlier picks shown again (slot "kept") are carried, not re-recorded as new evidence.
        fresh = [s for s in action["selections"] if by_id[s["candidate_id"]].get("slot") != "kept"]
        if action["all_bad"] and fresh:
            raise StyleMateError("invalid_input")
        text = action["text"] if isinstance(action["text"], str) and action["text"].strip() else None
        feedback_ref = None
        if fresh or text or action["all_bad"]:
            if service._latest_pending(snapshot):
                raise StyleMateError("context_blocked")
            reaction = "selected" if fresh else "none" if action["all_bad"] else "text_only"
            receipt = service._apply(request_id, service._step(command_id, "intake"), [{
                "op": "submit_feedback", "round_id": action["round_id"], "candidate_set_id": action["candidate_set_id"],
                "reaction": reaction, "selections": fresh, "text": text, "question_id": action["question_id"]}],
                command["expected"])
            feedback_ref = service._feedback_ref(receipt)
        run_turn(service, request_id, command_id, {"type": "feedback", "feedback_ref": feedback_ref,
            "answers_question": bool(text), "novel_hint": bool(text and mem.NOVEL_HINT.search(text)), "grid": {"set_id": action["candidate_set_id"], "selected": selected,
            "dislikes": list(action["dislikes"]), "similar": action["similar"], "all_bad": action["all_bad"],
            "liked": {cid: list(axes) for cid, axes in liked.items() if axes}}})
        return True
    if op == "graph_summary":
        summary_command(service, snapshot, command, command_id)
        return True
    if op == "adjust_intent":
        if action["action"] not in ADJUST_ACTIONS:
            raise StyleMateError("invalid_input")
        if action["action"] in ("memory_off", "memory_on"):
            intent = service._graph.intent(request_id)
            if not intent or not any(c["memory_id"] == action["key"] for c in intent["memory_chips"]):
                raise StyleMateError("invalid_input")
        if action["action"] in ("shortlist_remove", "shortlist_compare"):
            intent = service._graph.intent(request_id)
            shortlist = (intent or {}).get("shortlist", [])
            if not shortlist or (action["action"] == "shortlist_remove"
                                 and not any(s["product_id"] == action["key"] for s in shortlist)):
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
        # F8: the final product comes from the shortlist (a displayed candidate of the current set).
        card = next((c for c in (intent or {}).get("last_grid", {}).get("cards", []) if c["candidate_id"] == action["candidate_id"]), None) if intent and intent.get("last_grid") else None
        if card is None or not any(s["product_id"] == card["product_id"] for s in intent.get("shortlist", [])):
            raise StyleMateError("invalid_input")
        service._apply(request_id, service._step(command_id, "apply"), [action], command["expected"])
        service._jobs.pop(request_id, None)
        service._journal.clear_operation(request_id)
        return True
    return False


def start_info(action: dict[str, Any]) -> dict[str, Any]:
    """Validate ADR 0015 start options: gender filter and situation chip / free text."""
    gender = action.get("gender")
    if gender is not None and gender not in mem.GENDERS:
        raise StyleMateError("invalid_input")
    text = action["text"] if isinstance(action.get("text"), str) else ""
    return {"gender": gender, "situation": mem.start_situation(action.get("situation")),
            "novel_hint": bool(mem.NOVEL_HINT.search(text))}


def start(service: Any, request_id: str, command_id: str, feedback_ref: dict[str, Any] | None,
          info: dict[str, Any] | None = None) -> None:
    event = {"type": "feedback", "feedback_ref": feedback_ref, "grid": None} if feedback_ref else {"type": "explore"}
    info = info or {"gender": None, "situation": None, "novel_hint": False}
    event |= {"start": {"gender": info["gender"], "situation": info["situation"]}, "novel_hint": info["novel_hint"]}
    run_turn(service, request_id, command_id, event)


__all__ = ["GraphBridge", "graph_view", "handle_command", "run_turn", "start", "start_info", "c"]
