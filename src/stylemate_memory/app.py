"""Connect an owned store snapshot to a read-only inference adapter."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
from pathlib import Path
import sqlite3
import time
from typing import Any
from uuid import uuid4

from . import contracts as c
from .context import build_context, build_context_v1
from .errors import StyleMateError, V1_ERROR_CODES
from .inference import ModelAdapter, infer, validate_target_map_basis


class ShoppingApp:
    """The caller supplies a trusted local user ID; this is not authentication."""

    def __init__(self, store: Any, adapter: ModelAdapter) -> None:
        self.store = store
        self.adapter = adapter

    def infer_request(
        self,
        user_id: str,
        request_id: str,
        targets: list[dict[str, Any]],
        *,
        facts: dict[str, Any] | None = None,
        char_budget: int = 6000,
    ) -> dict[str, Any]:
        snapshot = self.store.snapshot(user_id, request_id)
        context = build_context(
            snapshot,
            targets,
            facts=facts,
            char_budget=char_budget,
        )
        if context.get("blocked"):
            raise StyleMateError("context_blocked", "필수 조건을 유지할 수 없어 추론을 보류했습니다.")
        profile = infer(context, self.adapter)
        try:
            current = build_context(
                self.store.snapshot(user_id, request_id),
                targets,
                facts=facts,
                char_budget=char_budget,
            )
        except StyleMateError:
            raise StyleMateError("stale_context", "요청이나 기억이 변경되어 결과를 다시 만들어야 합니다.") from None
        if current.get("blocked") or current.get("context_id") != context.get("context_id"):
            raise StyleMateError("stale_context", "요청이나 기억이 변경되어 결과를 다시 만들어야 합니다.")
        used_ids = {
            source_id
            for item in profile.get("suggestions", []) + profile.get("constraints", [])
            for source_id in item.get("source_ids", [])
        }
        profile["request_id"] = request_id
        profile["versions"] = {
            "request": snapshot["request"]["revision"],
            "profile": snapshot["profile_revision"],
            "memories": {
                memory["id"]: memory["version"]
                for memory in snapshot["memories"]
                if memory["id"] in used_ids
            },
        }
        return profile


def _ref(kind: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "id": obj["id"], "version": obj["version"]}


def _shape(value: Any, keys: Any) -> None:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise StyleMateError("invalid_input")


def _text(value: Any, limit: int = 128) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\0" in value:
        raise StyleMateError("invalid_input")


def _error(error: Exception) -> dict[str, str]:
    code = error.code if isinstance(error, StyleMateError) else "provider_error"
    if code not in V1_ERROR_CODES:
        code = "provider_error"
    messages = {
        "stale_context": "요청이나 근거가 바뀌었습니다. 최신 상태에서 다시 진행해 주세요.",
        "version_conflict": "표시한 내용이 변경되었습니다. 최신 상태를 확인해 주세요.",
        "context_blocked": "필수 조건과 근거를 유지할 수 없어 탐색을 보류했습니다.",
        "request_closed": "종료한 요청입니다. 새 요청을 시작해 주세요.",
        "request_expired": "보관 기간이 지난 요청입니다.",
        "confirmation_required": "내용이 맞는지 먼저 확인해 주세요.",
        "consent_required": "이후 활용 여부를 별도로 선택해 주세요.",
    }
    return {"code": code, "message": messages.get(code, "처리를 마치지 못했습니다. 입력과 현재 상태를 확인해 주세요.")}


class ConsumerService:
    """A2's trusted, single-tester v1 boundary, with no environment/secret reads.

    SQLite and catalog access share one executor (and therefore one thread and
    write ordering). Model work runs outside it, so edits/erasure/end can proceed
    while a response is in flight. Only a freshly checked result can be applied.
    Legacy ShoppingApp/CLI behavior above is intentionally independent.
    """

    def __init__(self, db_path: str | Path, catalog_path: str | Path, gateway: Any = None, *,
                 user_id: str = "local-tester", image_root: str | Path | None = None,
                 registry: Any = None, semantic: Any = None, clock: Any = None) -> None:
        _text(user_id)
        self.user_id = user_id
        self.gateway = gateway
        self.registry = registry
        self.semantic = semantic
        self._db = ThreadPoolExecutor(max_workers=1, thread_name_prefix="lumi-store")
        self._models = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lumi-model")
        self._jobs: dict[str, str] = {}
        self._closed = False
        try:
            self._run(self._open, db_path, catalog_path, image_root, clock)
        except BaseException:
            self._models.shutdown(wait=True)
            self._db.shutdown(wait=True)
            raise

    def _open(self, db_path: Any, catalog_path: Any, image_root: Any, clock: Any) -> None:
        from .catalog import Catalog
        from .consumer_state import ConsumerJournal
        from .model_io import FakeModelGateway
        from .registry import load_registry
        from .store import MemoryStore

        self.registry = self.registry or load_registry(c.V1_REGISTRY_VERSION)
        self.gateway = self.gateway or FakeModelGateway()
        self._store = MemoryStore(db_path, clock=clock)
        try:
            self._catalog = Catalog(catalog_path, image_root=image_root, registry=self.registry)
            self._journal = ConsumerJournal(self._store, self.user_id)
        except BaseException:
            if hasattr(self, "_catalog"):
                self._catalog.close()
            self._store.close()
            raise

    def _run(self, function: Any, *args: Any, **kwargs: Any) -> Any:
        return self._db.submit(function, *args, **kwargs).result()

    def __enter__(self) -> ConsumerService:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        if self._closed:
            return
        self._run(self._jobs.clear)
        self._closed = True
        self._models.shutdown(wait=True)
        self._run(lambda: (self._catalog.close(), self._store.close()))
        self._db.shutdown(wait=True)

    def wait_idle(self, timeout: float = 10) -> None:
        """Offline harness helper; HTTP clients poll state instead."""
        deadline = time.monotonic() + timeout
        while self._run(lambda: bool(self._jobs)):
            if time.monotonic() >= deadline:
                raise TimeoutError("consumer operation is still running")
            time.sleep(0.005)

    def _snapshot(self, request_id: str) -> dict[str, Any]:
        return self._store.snapshot(self.user_id, request_id, contract_version=c.CONTRACT_VERSION, include_closed=True)

    @staticmethod
    def _expected(snapshot: dict[str, Any]) -> dict[str, Any]:
        pairs = (("memory", "memories"), ("binding", "bindings"), ("evidence", "evidence"),
                 ("feedback", "feedback"), ("interpretation", "interpretations"),
                 ("round", "rounds"), ("candidate_set", "candidate_sets"), ("question", "questions"))
        refs = [_ref(kind, obj) for kind, key in pairs for obj in snapshot[key]]
        # Mutation callers can send a narrower Expected; state exposes current
        # visible controls, not every historical comparison as a control token.
        if len(refs) > 256:
            controls = {"memory", "binding", "round"}
            active = next((r for r in reversed(snapshot["rounds"]) if r["status"] == "active"), None)
            live = {active["candidate_set_ref"]["id"]} if active else set()
            live.update(q["id"] for q in snapshot["questions"] if q["status"] == "open")
            refs = [r for r in refs if r["type"] in controls or r["id"] in live]
        if len(refs) > 256:
            raise StyleMateError("context_blocked")
        return {"request_revision": snapshot["request"]["revision"],
                "profile_revision": snapshot["profile_revision"], "object_versions": refs}

    def _basis(self, snapshot: dict[str, Any], refs: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        expected = self._expected(snapshot)
        if refs is not None:
            expected["object_versions"] = refs
        return expected | {"request_id": snapshot["request"]["id"], "contract_version": c.CONTRACT_VERSION,
                           "registry_version": self.registry.version, "index_version": None, "catalog": None,
                           "valid_until": snapshot["request"]["retention_until"]}

    def _ui_expected(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        # E1 deliberately refuses to guess an active set or retry target from
        # historical refs. Expose exactly the current controls in the UI token;
        # internal context/display bases retain their complete dependencies.
        visible = dict(snapshot)
        active = next((r for r in snapshot["rounds"] if r["status"] == "active"), None)
        visible["rounds"] = [active] if active else []
        visible["candidate_sets"] = [s for s in snapshot["candidate_sets"]
                                     if active and _ref("candidate_set", s) == active["candidate_set_ref"]]
        row = self._store.connection.execute(
            "SELECT o.id FROM v1_objects o JOIN v1_feedback f ON f.id=o.id WHERE o.user_id=? AND o.request_id=? ORDER BY o.rowid DESC LIMIT 1",
            (self.user_id, snapshot["request"]["id"])).fetchone()
        visible["feedback"] = [f for f in snapshot["feedback"] if row and f["id"] == row[0]]
        visible["interpretations"] = [i for i in snapshot["interpretations"]
                                       if visible["feedback"] and i["feedback_ref"]["id"] == visible["feedback"][0]["id"]]
        return self._expected(visible)

    def _check_expected(self, snapshot: dict[str, Any], expected: Any) -> None:
        self._store._v1._expected(expected, None, None)
        basis = self._basis(snapshot, expected["object_versions"]) | {
            "request_revision": expected["request_revision"], "profile_revision": expected["profile_revision"]}
        self._store._v1._check_basis(self._store._request_row(self.user_id, snapshot["request"]["id"]),
                                     basis, self._store._now())

    def _apply(self, request_id: str, batch_id: str, actions: list[dict[str, Any]], expected: Any = None) -> dict[str, Any]:
        return self._store.apply_batch(self.user_id, request_id, batch_id=batch_id, actions=actions,
            contract_version=c.CONTRACT_VERSION, expected=expected if expected is not None else self._expected(self._snapshot(request_id)),
            catalog_freshness=self._catalog)

    @staticmethod
    def _step(command_id: str, step: str) -> str:
        return "consumer-" + hashlib.sha256((command_id + ":" + step).encode()).hexdigest()

    def _request_views(self) -> list[dict[str, Any]]:
        rows = self._store.connection.execute(
            "SELECT id FROM requests WHERE user_id=? AND contract_version=? ORDER BY rowid DESC",
            (self.user_id, c.CONTRACT_VERSION)).fetchall()
        views = []
        for row in rows:
            try:
                record = self._snapshot(row["id"])["request"]
            except StyleMateError as error:
                if error.code == "request_expired":
                    continue
                raise
            views.append({k: record[k] for k in c.RequestState.__required_keys__})
        return views

    def state(self, request_id: str | None = None) -> c.ConsumerState:
        return self._run(self._state, request_id)

    def _state(self, request_id: str | None = None) -> dict[str, Any]:
        if request_id is not None:
            _text(request_id)
        requests = self._request_views()
        request_id = request_id or self._journal.active()
        if request_id is not None and not any(r["id"] == request_id for r in requests):
            # An explicitly supplied foreign/deleted ID is not a user switch.
            if request_id == self._journal.active():
                request_id = None
            else:
                self._snapshot(request_id)
        if request_id is None:
            request_id = requests[0]["id"] if requests else None
        result: dict[str, Any] = {
            "contract_version": c.CONTRACT_VERSION, "state_version": self._journal.next_version(),
            "request": None, "requests": requests, "expected": None, "phase": "onboarding", "operation": "idle",
            "memories": [], "cards": [], "reviews": [], "questions": [], "error": None,
            "comparison": None,
        }
        if request_id is None:
            return result
        snapshot = self._snapshot(request_id)
        result["request"] = {k: snapshot["request"][k] for k in c.RequestState.__required_keys__}
        result["expected"] = self._ui_expected(snapshot)
        result["memories"] = [{"ref": _ref("memory", m), "reusable": m["scope"] == "short_term" and m["selector"]["slot_id"] is None,
                               **{k: m[k] for k in ("content", "scope", "confirmed", "status")}}
                              for m in snapshot["memories"]]
        result["questions"] = [{"ref": _ref("question", q), **{k: q[k] for k in ("text", "target_id", "options", "status")}}
                               for q in snapshot["questions"] if q["status"] == "open"]
        operation, code = self._journal.operation(request_id)
        error = _error(StyleMateError(code)) if code else None
        pending = self._latest_pending(snapshot)
        if request_id in self._jobs:
            operation, error = "running", None
        elif pending and snapshot["request"]["status"] == "open":
            operation, error = "interpretation_pending", pending["error"]
        elif operation == "running":
            operation, error = "stale", _error(StyleMateError("stale_context"))
        active = next((r for r in reversed(snapshot["rounds"]) if r["status"] == "active"), None)
        if active and operation not in ("running", "stale", "no_results", "error", "blocked"):
            candidate_set = next((s for s in snapshot["candidate_sets"] if s["id"] == active["candidate_set_ref"]["id"]), None)
            try:
                if candidate_set is None:
                    raise StyleMateError("stale_context")
                self._store._v1.feedback.current_set(self._store._request_row(self.user_id, request_id), active["id"],
                    candidate_set["id"], result["expected"], self._store._now(), self._catalog)
                for card in candidate_set["cards"]:
                    record = self._catalog.get_record(card["product_id"])
                    image_url = None
                    if card["image_id"] is not None:
                        from urllib.parse import quote
                        source = next((i for i in record["images"] if i["image_id"] == card["image_id"]), None)
                        # Remote supplier references are not fetched/proxied.
                        if source is not None and source["kind"] == "local":
                            image_url = f"/api/images/{quote(card['image_id'], safe='')}?version={card['image_version']}"
                    result["cards"].append(deepcopy(card) | {"title": record["title"], "image_url": image_url})
                from .hypotheses import load_comparison, public_comparison
                comparison = load_comparison(self, candidate_set["id"])
                if comparison and not comparison["answered"]:
                    result["comparison"] = public_comparison(comparison)
                    target_ids = {card["target_id"] for card in candidate_set["cards"]
                                  if card["candidate_id"] in {o["candidate_id"] for o in comparison["options"]}}
                    result["questions"] = [q for q in result["questions"] if q["target_id"] not in target_ids]
            except StyleMateError:
                operation, error = "stale", _error(StyleMateError("stale_context"))
                result["cards"] = []
        result["reviews"] = self._reviews(snapshot)
        closed = snapshot["request"]["status"] != "open"
        result["phase"] = ("wrap_up" if closed or snapshot["request"]["final_selection"] else "review" if result["reviews"]
                           else "onboarding" if snapshot["request"]["mode"] == "onboarding"
                           else "exploring" if active else "request")
        result["operation"], result["error"] = ("idle", None) if closed else (operation, error)
        return result

    def _reviews(self, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        request_id = snapshot["request"]["id"]
        rows = self._store.connection.execute("""
            SELECT o.*,d.payload_json FROM v1_objects o JOIN v1_displays d ON d.id=o.id
            WHERE o.user_id=? AND o.request_id=? AND NOT EXISTS (
                SELECT 1 FROM consumer_dismissals x WHERE x.display_id=o.id)
            AND NOT EXISTS (SELECT 1 FROM v1_user_events e JOIN v1_event_uses u ON u.event_id=e.id
                WHERE json_extract(e.payload_json,'$.display_ref.id')=o.id) ORDER BY o.rowid DESC
        """, (self.user_id, request_id)).fetchall()
        reviews = []
        for row in rows:
            display = self._store._v1._object(row)
            if display["purpose"] == "future_reuse" and snapshot["request"]["status"] != "closed":
                continue
            try:
                self._store._v1._check_basis(self._store._request_row(self.user_id, request_id), display["basis"],
                    self._store._now(), catalog_freshness=self._catalog, check_catalog=True,
                    removing=display["purpose"] in ("withdraw", "delete"))
            except StyleMateError:
                continue
            reviews.append({"ref": _ref("display", display), "purpose": display["purpose"], "snapshot": display["snapshot"]})
        row = self._store.connection.execute("SELECT * FROM consumer_request_reviews WHERE user_id=? AND request_id=?",
                                             (self.user_id, request_id)).fetchone()
        if row and row["request_revision"] == snapshot["request"]["revision"] and row["profile_revision"] == snapshot["profile_revision"]:
            reviews.append({"ref": {"type": "display", "id": row["id"], "version": 1}, "purpose": "delete_request",
                            "snapshot": {"meaning": None, "bindings": [], "subject_refs": []}})
        return reviews

    def command(self, command: c.ConsumerCommand) -> c.ConsumerResult:
        return self._run(self._command, deepcopy(command))

    def _command(self, command: Any) -> dict[str, Any]:
        request_id = None
        try:
            self._validate_command(command)
            request_id = command["request_id"]
            if command["expected"] is not None:
                self._store._v1._expected(command["expected"], None, None)
            prior = self._journal.lookup(command)
            if prior and prior.get("outcome"):
                # A receipt never restores a previously cached screen after erasure.
                return {"outcome": prior["outcome"], "state": self._state(None if prior.get("deleted") else prior["request_id"]), "error": None}
            action, command_id = command["action"], command["command_id"]
            op = action["op"]
            if op == "start_request":
                request = self._store.start_request(self.user_id, input_id=self._step(command_id, "start"),
                    text=action["text"], timezone=action["timezone"], mode=action["mode"], targets=action["targets"],
                    contract_version=c.CONTRACT_VERSION, registry_version=self.registry.version)
                request_id = request["id"]
                self._jobs.clear()  # a late response cannot bleed into a new request
                self._journal.activate(request_id)
                self._journal.reserve(command, request_id)
                if action["text"] is not None:
                    feedback = {"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
                                "reaction": "text_only", "selections": [], "text": action["text"], "question_id": None}
                    receipt = self._apply(request_id, self._step(command_id, "intake"), [feedback])
                    self._extract(request_id, self._feedback_ref(receipt), command_id)
                elif action["mode"] == "shopping":
                    self._explore(request_id, command_id)
                self._journal.finish(command_id, "accepted" if request_id in self._jobs else "applied")
            else:
                snapshot = self._snapshot(request_id)
                # Store mutations perform their own replay-before-revision check.
                if not prior:
                    self._check_expected(snapshot, command["expected"])
                self._journal.reserve(command, request_id)
                if op == "resume_request":
                    if self._journal.active() != request_id:
                        self._jobs.clear()
                    self._journal.activate(request_id)
                elif op == "submit_feedback":
                    if self._latest_pending(snapshot):
                        raise StyleMateError("context_blocked")
                    receipt = self._apply(request_id, self._step(command_id, "intake"), [action], command["expected"])
                    self._extract(request_id, self._feedback_ref(receipt), command_id)
                elif op == "retry_extraction":
                    self._extract(request_id, action["feedback_ref"], command_id)
                elif op == "respond_comparison":
                    from .hypotheses import respond_comparison
                    respond_comparison(self, snapshot, action, command, command_id)
                elif op == "explore":
                    self._explore(request_id, command_id)
                elif op == "prepare_review":
                    display_id = self._prepare_review(snapshot, action, command_id)
                    self._journal.finish(command_id, "applied", display_id)
                elif op == "respond_review":
                    self._respond_review(snapshot, action, command, command_id)
                elif op in ("select_final", "end_request"):
                    if op == "select_final":
                        context = self._context(snapshot)
                        if any(item["binding"]["domain"] == "FEA" and item["binding"]["strength"] == "hard"
                               for item in context["constraints"]):
                            raise StyleMateError("context_blocked", "필수 기능 요구의 상품 근거를 먼저 확인하거나 조건을 조정해 주세요.")
                    self._apply(request_id, self._step(command_id, "apply"), [action], command["expected"])
                    self._jobs.pop(request_id, None)
                    self._journal.clear_operation(request_id)
                if op not in ("prepare_review", "respond_review"):
                    self._journal.finish(command_id, "accepted" if request_id in self._jobs else "applied")
            return {"outcome": "accepted" if request_id in self._jobs else "applied",
                    "state": self._state(request_id if self._exists(request_id) else None), "error": None}
        except (StyleMateError, ValueError, TypeError, KeyError, StopIteration, RecursionError, sqlite3.Error) as exc:
            if not isinstance(exc, StyleMateError):
                exc = StyleMateError("storage_failed" if isinstance(exc, sqlite3.Error) else "invalid_input")
            error = _error(exc)
            try:
                state = self._state(request_id if request_id and self._exists(request_id) else None)
            except StyleMateError:
                state = self._state()
            return {"outcome": "rejected", "state": state, "error": error}

    def _exists(self, request_id: str | None) -> bool:
        return self._store.connection.execute("SELECT 1 FROM requests WHERE id=? AND user_id=?",
                                             (request_id, self.user_id)).fetchone() is not None

    def _latest_pending(self, snapshot: dict[str, Any]) -> dict[str, Any] | None:
        row = self._store.connection.execute(
            "SELECT i.payload_json FROM v1_objects o JOIN v1_interpretations i ON i.id=o.id "
            "WHERE o.user_id=? AND o.request_id=? ORDER BY o.rowid DESC LIMIT 1",
            (self.user_id, snapshot["request"]["id"])).fetchone()
        if row:
            import json
            value = json.loads(row[0])
            if value["status"] == "pending":
                return value
        return None

    @staticmethod
    def _validate_command(command: Any) -> None:
        _shape(command, c.ConsumerCommand.__required_keys__)
        if command["contract_version"] != c.CONTRACT_VERSION:
            raise StyleMateError("unsupported_contract")
        _text(command["command_id"])
        action = command["action"]
        if not isinstance(action, dict):
            raise StyleMateError("invalid_input")
        shapes = {"start_request": c.StartRequestUI, "resume_request": c.SimpleUI, "explore": c.SimpleUI,
                  "end_request": c.SimpleUI, "submit_feedback": c.FeedbackAction, "retry_extraction": c.RetryExtractionUI,
                  "prepare_review": c.ReviewUI, "respond_review": c.RespondReviewUI, "select_final": c.SelectFinalAction}
        shapes["respond_comparison"] = c.RespondComparisonUI
        if not isinstance(action.get("op"), str) or action["op"] not in shapes:
            raise StyleMateError("invalid_input")
        optional = {"text"} if action["op"] == "respond_comparison" and "text" in action else set()
        _shape(action, shapes[action["op"]].__required_keys__ | optional)
        if action["op"] == "start_request":
            if command["request_id"] is not None or command["expected"] is not None:
                raise StyleMateError("invalid_input")
        else:
            _text(command["request_id"])
            _shape(command["expected"], c.Expected.__required_keys__)
        if action["op"] == "respond_review" and action["decision"] not in ("accept", "decline", "skip"):
            raise StyleMateError("invalid_input")
        if action["op"] == "respond_comparison" and action["decision"] not in ("choose", "neither", "unsure"):
            raise StyleMateError("invalid_input")

    @staticmethod
    def _feedback_ref(receipt: dict[str, Any]) -> dict[str, Any]:
        return next(r for r in receipt["changed_refs"] if r["type"] == "feedback")

    def _submit_model(self, request_id: str, function: Any, callback: Any) -> None:
        token = uuid4().hex
        self._jobs[request_id] = token
        self._journal.set_operation(request_id, "running")
        future = self._models.submit(function)

        def complete(result: Any) -> None:
            def apply_result() -> None:
                if self._jobs.get(request_id) != token:
                    return
                try:
                    callback(result)
                except Exception as exc:
                    safe = _error(exc)
                    self._journal.set_operation(request_id,
                        "stale" if safe["code"] in ("stale_context", "request_closed", "not_found", "request_expired")
                        else "blocked" if safe["code"] == "context_blocked" else "error", safe["code"])
                finally:
                    if self._jobs.get(request_id) == token:
                        self._jobs.pop(request_id, None)
            self._db.submit(apply_result)
        future.add_done_callback(complete)

    def _fresh(self, original: dict[str, Any], *, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self._snapshot(original["request"]["id"])
        if current["request"]["status"] != "open" or self._journal.active() != original["request"]["id"]:
            raise StyleMateError("stale_context")
        basis = self._basis(original)
        self._store._v1._check_basis(self._store._request_row(self.user_id, original["request"]["id"]), basis,
                                     self._store._now(), catalog_freshness=self._catalog, check_catalog=True)
        if catalog is not None:
            self._store._v1.feedback.check_catalog(catalog, self._catalog)
        return current

    def _extract(self, request_id: str, feedback_ref: dict[str, Any], command_id: str, *, edit_subject: Any = None) -> None:
        from .consumer_state import canonical
        c.validate_ref(feedback_ref)
        interpretation = self._store.interpretation_status(self.user_id, request_id, feedback_ref)
        if interpretation["status"] == "complete":
            return
        snapshot = self._snapshot(request_id)
        if snapshot["request"]["status"] != "open":
            raise StyleMateError("request_closed")
        feedback = next(f for f in snapshot["feedback"] if f["id"] == feedback_ref["id"])
        refs = {r["id"]: r for r in feedback["evidence_refs"]}
        sources, aliases = [], {}
        for evidence in snapshot["evidence"]:
            if evidence["id"] not in refs or evidence["kind"] not in ("user_text", "image_selection"):
                continue
            alias = f"e{len(sources) + 1:03}"
            aliases[alias] = evidence["id"]
            selection = evidence["selection"]
            content = evidence["quote"]
            if selection:
                product = self._catalog.get_product_map(selection["product_id"])
                selected_context = {"target_id": selection["target_id"], "product_assertions": product["assertions"],
                                    "part_ref": selection["part_ref"], "reason": None}
                if interpretation.get("extraction_key", "") and interpretation["extraction_key"].startswith("comparison-"):
                    from .hypotheses import load_comparison
                    comparison = load_comparison(self, selection["candidate_set_ref"]["id"])
                    if comparison:
                        selected_context["unconfirmed_comparison"] = {"prompt": comparison["prompt"],
                            "shown_meaning": next(o["meaning"] for o in comparison["options"] if o["candidate_id"] == selection["candidate_id"])}
                content = canonical(selected_context)
            sources.append({"source_id": alias, "kind": evidence["kind"], "content": content, "selector": evidence["selector"]})
        inputs = {"sources": sources, "targets": snapshot["request"]["targets"], "registry": self.registry.describe()}
        extraction_key = hashlib.sha256(canonical({"evidence": feedback["evidence_refs"], "registry": self.registry.version,
            "adapter": type(self.gateway).__name__, "model": getattr(self.gateway, "model", "injected"), "service": "a2-v1"}).encode()).hexdigest()
        if (interpretation.get("extraction_key") or "").startswith("comparison-"):
            extraction_key = "comparison-text:" + extraction_key
        catalog = self._catalog.current_versions([], [])
        if feedback["candidate_set_ref"]:
            candidate_set = next(s for s in snapshot["candidate_sets"] if s["id"] == feedback["candidate_set_ref"]["id"])
            catalog = candidate_set["basis"]["catalog"]

        def calculate() -> Any:
            # Empty/skipped responses contain no positive preference signal.
            if not sources or feedback["reaction"] == "question_skipped":
                return {"candidates": [], "questions": []}
            return self.gateway.extract(deepcopy(inputs))

        def apply_result(future: Any) -> None:
            self._fresh(snapshot, catalog=catalog)
            try:
                result = future.result()
                from .model_io import validate_extraction_v1
                result = validate_extraction_v1(result, inputs, self.registry)
                for candidate in result["candidates"]:
                    candidate["source_ids"] = [aliases[s] for s in candidate["source_ids"]]
            except Exception as exc:
                error = _error(exc)
                if error["code"] not in V1_ERROR_CODES:
                    error = _error(StyleMateError("provider_error"))
                self._apply(request_id, self._step(command_id, "extraction-failed"), [{"op": "record_extraction",
                    "feedback_ref": feedback_ref, "extraction_key": extraction_key, "result": None, "error": error}])
                self._journal.set_operation(request_id, "interpretation_pending", error["code"])
                return
            receipt = self._apply(request_id, self._step(command_id, "extraction-complete"), [{"op": "record_extraction",
                "feedback_ref": feedback_ref, "extraction_key": extraction_key, "result": result, "error": None}])
            self._journal.set_operation(request_id, "idle")
            if edit_subject is not None:
                self._edit_review(request_id, edit_subject, receipt, command_id)
            elif snapshot["request"]["mode"] == "shopping":
                self._explore(request_id, command_id)

        self._submit_model(request_id, calculate, apply_result)

    def _context(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        return build_context_v1(snapshot, snapshot["request"]["targets"], registry=self.registry, semantic=self.semantic)

    def _explore(self, request_id: str, command_id: str) -> None:
        snapshot = self._snapshot(request_id)
        if snapshot["request"]["status"] != "open":
            raise StyleMateError("request_closed")
        if self._latest_pending(snapshot):
            self._journal.set_operation(request_id, "interpretation_pending")
            return
        context = self._context(snapshot)
        if context["blocked"] or not snapshot["request"]["targets"]:
            self._journal.set_operation(request_id, "blocked", "context_blocked")
            return
        catalog = self._catalog.current_versions([], [])

        def calculate() -> Any:
            from .hypotheses import infer_with_hypotheses
            return infer_with_hypotheses(context, self.gateway, registry=self.registry)

        def apply_result(future: Any) -> None:
            from .comparison import build_candidate_cards
            from .product_search import search_products
            current = self._fresh(snapshot, catalog=catalog)
            target_map, hypotheses = future.result()  # provider errors never fall back to a rule
            validate_target_map_basis(target_map, self._context(current), registry=self.registry, now=self._store._now())
            results = [search_products(target_map, t["target_id"], self._catalog, pi_only=True) for t in snapshot["request"]["targets"]]
            from .hypotheses import load_comparison
            previous = [load_comparison(self, row[0]) for row in self._store.connection.execute(
                "SELECT c.set_id FROM consumer_comparisons c JOIN v1_objects o ON o.id=c.set_id WHERE o.user_id=? AND o.request_id=?",
                (self.user_id, request_id))]
            answered = {item["hypothesis_id"] for item in previous if item["answered"]}
            from .hypotheses import comparison_options
            hypothesis = None
            plan = build_candidate_cards(results, target_map, self._catalog, pi_only=True)
            for candidate in hypotheses:
                if candidate["id"] in answered:
                    continue
                trial = build_candidate_cards(results, target_map, self._catalog, pi_only=True, hypothesis=candidate)
                if comparison_options(self, candidate, trial):
                    plan, hypothesis = trial, candidate
                    break
            if any(item["binding"]["domain"] == "FEA" and item["binding"]["strength"] == "hard" for item in target_map["constraints"]):
                plan["questions"] = [{"text": "필수 기능 요구는 상품 PI만으로 확인할 수 없어요. 비교는 계속할 수 있지만 최종 선택 전에 추가 근거나 조건 조정이 필요해요.",
                    "target_id": None, "subject_refs": [], "options": []}] + plan["questions"][:2]
            # Search and publication share the catalog-owning executor. Rebuild
            # memory/index basis too immediately before the store validates it.
            validate_target_map_basis(target_map, self._context(self._snapshot(request_id)),
                                      registry=self.registry, now=self._store._now())
            if not plan["cards"]:
                if any(result["status"] == "blocked" for result in results):
                    self._journal.set_operation(request_id, "blocked", "context_blocked")
                else:
                    self._journal.set_operation(request_id, "no_results")
                return
            round_obj = self._store.publish_candidates(self.user_id, request_id, batch_id=self._step(command_id, "candidates"),
                                                       plan=plan, catalog_freshness=self._catalog)
            if hypothesis:
                from .hypotheses import prepare_comparison
                prepare_comparison(self, hypothesis, plan, round_obj)
            self._journal.set_operation(request_id, "idle")

        self._submit_model(request_id, calculate, apply_result)

    @staticmethod
    def _meaning(memory: dict[str, Any], scope: str | None = None) -> dict[str, Any]:
        return {k: deepcopy(memory[k]) for k in c.MemoryContent.__required_keys__} | {"scope": scope or memory["scope"]}

    @staticmethod
    def _spec(binding: dict[str, Any]) -> dict[str, Any]:
        fields = c.PIBindingSpec.__required_keys__ if binding["domain"] == "PI" else c.FEABindingSpec.__required_keys__
        return {k: deepcopy(binding[k]) for k in fields}

    def _prepare_review(self, snapshot: dict[str, Any], action: dict[str, Any], command_id: str) -> str | None:
        request_id, purpose = snapshot["request"]["id"], action["purpose"]
        if purpose not in ("confirm_content", "confirm_bindings", "future_reuse", "replace", "withdraw", "delete", "delete_request"):
            raise StyleMateError("invalid_input")
        if not isinstance(action["subject_refs"], list):
            raise StyleMateError("invalid_input")
        for ref in action["subject_refs"]:
            c.validate_ref(ref)
        if purpose == "delete_request":
            if action["subject_refs"] or action["proposed_text"] is not None:
                raise StyleMateError("invalid_input")
            display_id = uuid4().hex
            self._store.connection.execute("DELETE FROM consumer_request_reviews WHERE user_id=? AND request_id=?", (self.user_id, request_id))
            self._store.connection.execute("INSERT INTO consumer_request_reviews VALUES (?,?,?,?,?)",
                (display_id, request_id, self.user_id, snapshot["request"]["revision"], snapshot["profile_revision"]))
            return None
        memory_refs = [r for r in action["subject_refs"] if r["type"] == "memory"]
        if len(memory_refs) != 1:
            raise StyleMateError("invalid_input")
        memory = next((m for m in snapshot["memories"] if _ref("memory", m) == memory_refs[0]), None)
        if memory is None:
            raise StyleMateError("stale_context")
        if purpose == "future_reuse" and snapshot["request"]["status"] != "closed":
            raise StyleMateError("consent_required", "이후 활용 동의는 대화를 마친 뒤 진행해 주세요.")
        subjects = [memory_refs[0]]
        bindings = [b for b in snapshot["bindings"] if b["memory_id"] == memory["id"] and b["status"] in ("candidate", "active")]
        if purpose in ("confirm_bindings", "future_reuse"):
            subjects += [_ref("binding", b) for b in bindings]
        if purpose == "confirm_bindings" and not memory["confirmed"]:
            raise StyleMateError("confirmation_required")
        if purpose == "future_reuse" and (not memory["confirmed"] or memory["selector"]["slot_id"] is not None):
            raise StyleMateError("confirmation_required" if not memory["confirmed"] else "consent_required")
        meaning = self._meaning(memory, "long_term" if purpose == "future_reuse" else None)
        specs = [self._spec(b) for b in bindings] if purpose in ("confirm_bindings", "future_reuse") else []
        proposed = action["proposed_text"]
        if purpose == "replace":
            _text(proposed, 4000)
            if not memory["confirmed"]:
                raise StyleMateError("confirmation_required")
            if self._latest_pending(snapshot):
                raise StyleMateError("context_blocked")
            # The edited sentence is separate user evidence. Existing bindings,
            # facts/conditions are not silently transplanted into new wording.
            receipt = self._apply(request_id, self._step(command_id, "edit-intake"), [{"op": "submit_feedback", "round_id": None,
                "candidate_set_id": None, "reaction": "text_only", "selections": [], "text": proposed, "question_id": None}])
            self._extract(request_id, self._feedback_ref(receipt), self._step(command_id, "edit"), edit_subject=memory_refs[0])
            # Extraction must finish before any reviewed replacement is issued.
            return None
        if proposed is not None:
            raise StyleMateError("invalid_input")
        basis = self._basis(snapshot)
        active = next((r for r in snapshot["rounds"] if r["status"] == "active"), None)
        if not active and snapshot["request"]["status"] == "closed" and purpose in ("confirm_content", "confirm_bindings", "future_reuse"):
            queue, seen, set_ids = list(memory["source_refs"]), set(), set()
            while queue:
                ref = queue.pop()
                if (ref["type"], ref["id"]) in seen:
                    continue
                seen.add((ref["type"], ref["id"]))
                source = self._store._v1._resolve(self.user_id, request_id, ref, self._store._now())
                queue.extend(source.get("source_refs", []))
                if ref["type"] == "evidence" and source.get("selection"):
                    set_ids.add(source["selection"]["candidate_set_ref"]["id"])
            if len(set_ids) > 1:
                raise StyleMateError("context_blocked")
            if set_ids:
                historical = next((s for s in snapshot["candidate_sets"] if s["id"] in set_ids), None)
                if historical is None:
                    raise StyleMateError("stale_context")
                basis["catalog"] = historical["basis"]["catalog"]
                self._store._v1.feedback.check_catalog(basis["catalog"], self._catalog)
        if active and purpose not in ("withdraw", "delete"):
            candidate_set = next(s for s in snapshot["candidate_sets"] if s["id"] == active["candidate_set_ref"]["id"])
            basis["catalog"] = candidate_set["basis"]["catalog"]
            self._store._v1.feedback.check_catalog(basis["catalog"], self._catalog)
        display = self._store.issue_display(self.user_id, request_id, purpose=purpose,
            snapshot={"meaning": meaning, "bindings": specs, "subject_refs": subjects}, basis=basis)
        return display["id"]

    def _edit_review(self, request_id: str, subject: dict[str, Any], receipt: dict[str, Any], command_id: str) -> None:
        snapshot = self._snapshot(request_id)
        old = next((m for m in snapshot["memories"] if _ref("memory", m) == subject), None)
        candidates = [m for m in snapshot["memories"] if _ref("memory", m) in receipt["changed_refs"]]
        if old is None or not old["confirmed"]:
            raise StyleMateError("confirmation_required")
        if len(candidates) != 1:
            # Ambiguous edits remain ordinary candidates/questions for explicit
            # review; never guess which sentence replaces the selected memory.
            raise StyleMateError("context_blocked")
        candidate = candidates[0]
        if old["scope"] == "long_term":
            # A local edit does not inherit prior future-use consent. Review the
            # new short-term candidate, leaving the long-term original intact.
            self._prepare_review(snapshot, {"purpose": "confirm_content", "subject_refs": [_ref("memory", candidate)],
                                            "proposed_text": None}, command_id)
            return
        bindings = [b for b in snapshot["bindings"] if b["memory_id"] == candidate["id"]]
        subjects = [subject, _ref("memory", candidate)] + candidate["source_refs"]
        display = self._store.issue_display(self.user_id, request_id, purpose="replace",
            snapshot={"meaning": self._meaning(candidate), "bindings": [self._spec(b) for b in bindings], "subject_refs": subjects},
            basis=self._basis(snapshot))
        self._journal.finish(command_id, "applied", display["id"])

    def _respond_review(self, snapshot: dict[str, Any], action: dict[str, Any], command: dict[str, Any], command_id: str) -> None:
        request_id = snapshot["request"]["id"]
        c.validate_ref(action["display_ref"])
        review = next((r for r in self._reviews(snapshot) if r["ref"] == action["display_ref"]), None)
        if review is None:
            raise StyleMateError("stale_context")
        if action["decision"] != "accept":
            if review["purpose"] == "delete_request":
                self._store.connection.execute("DELETE FROM consumer_request_reviews WHERE id=?", (review["ref"]["id"],))
            else:
                self._store.connection.execute("INSERT OR IGNORE INTO consumer_dismissals VALUES (?)", (review["ref"]["id"],))
            self._journal.finish(command_id, "applied")
            return
        purpose = review["purpose"]
        if purpose == "future_reuse" and snapshot["request"]["status"] != "closed":
            raise StyleMateError("consent_required")
        if purpose == "delete_request":
            # Request erasure has its own trusted-store method, rather than a
            # fabricated MemoryMeaning or a made-up memory/evidence subject.
            self._store.delete_request(self.user_id, request_id)
            self._jobs.pop(request_id, None)
            self._journal.clear_operation(request_id)
            self._journal.deleted(command)
            return
        event = self._store.record_user_event(self.user_id, request_id, command_id=command_id,
            display_ref=action["display_ref"], purpose=purpose, expected=command["expected"])
        memory_ref = next(r for r in review["snapshot"]["subject_refs"] if r["type"] == "memory")
        base = {"memory_id": memory_ref["id"], "expected_version": memory_ref["version"]}
        if purpose in ("confirm_content", "confirm_bindings"):
            mutation = base | {"op": "confirm" if purpose == "confirm_content" else "confirm_bindings",
                "confirmation_event_ref": event, "binding_confirmations": [r for r in review["snapshot"]["subject_refs"]
                    if r["type"] == "binding"] if purpose == "confirm_bindings" else []}
        elif purpose == "future_reuse":
            mutation = base | {"op": "promote", "consent_event_ref": event}
        elif purpose in ("withdraw", "delete"):
            mutation = base | {"op": purpose, "user_event_ref": event}
        elif purpose == "replace":
            mutation = base | {"op": "replace", "memory": {k: review["snapshot"]["meaning"][k] for k in c.MemoryContent.__required_keys__},
                "bindings": review["snapshot"]["bindings"], "source_refs": [r for r in review["snapshot"]["subject_refs"] if r["type"] == "evidence"],
                "confirmation_event_ref": event, "consent_event_ref": None}
        else:
            raise StyleMateError("invalid_input")
        self._apply(request_id, self._step(command_id, "apply"), [mutation], command["expected"])
        self._jobs.pop(request_id, None)
        self._journal.clear_operation(request_id)
        if purpose == "delete":
            self._journal.deleted(command)
        else:
            self._journal.finish(command_id, "applied")

    def import_catalog(self, path: str | Path) -> dict[str, Any]:
        """Trusted local operation; there is deliberately no HTTP file-path route."""
        from .catalog_io import import_file
        return self._run(import_file, self._catalog, path)

    def build_catalog_maps(self) -> list[dict[str, Any]]:
        from .catalog_mapping import build_product_map
        def build() -> list[dict[str, Any]]:
            output = []
            for record in self._catalog.export_records():
                product_id = record["product_id"]
                previous = self._catalog._product(product_id)["map_version"]
                product_map = build_product_map(record, raw_version=self._catalog.raw_version(product_id), registry=self.registry, pi_only=True)
                output.append(self._catalog.save_product_map(product_map, expected_raw_version=product_map["raw_version"],
                                                            expected_map_version=previous))
            return output
        return self._run(build)

    def image(self, image_id: str, version: int) -> tuple[bytes, str]:
        return self._run(self._catalog.read_image, image_id, version=version)

    def inspect_request(self, request_id: str) -> dict[str, Any]:
        """Explicit local developer observation only; never exposed by HTTP."""
        def inspect() -> dict[str, Any]:
            snapshot = self._snapshot(request_id)
            return {"snapshot": snapshot, "context": self._context(snapshot) if snapshot["request"]["status"] == "open" else None}
        return self._run(inspect)
