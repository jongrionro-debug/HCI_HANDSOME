"""Local, single-tester Chat -> memory -> Feature Map inspector.

This is a developer tool, not the consumer UI or a public authenticated API.
SQLite remains the memory authority. Chat, model traces and review hints stay
in process memory; runtime DBs are kept outside the repository.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
from typing import Any
import uuid

from .app import ShoppingApp
from .codex_llm import CodexGateway, CodexFeatureAdapter, EXTRACTION_INSTRUCTIONS, extraction_schema, validate_extraction
from .context import build_context
from .errors import StyleMateError
from .registry import FEATURES, registry_metadata
from .store import MemoryStore


def _id() -> str:
    return str(uuid.uuid4())


def _at() -> str:
    return datetime.now(timezone.utc).isoformat()


class Inspector:
    """Serialize mutations; state polling reads a cached, immutable copy."""
    def __init__(self, store: MemoryStore, gateway: Any, *, user_id: str = "developer-test", garment_type: str = "Pants") -> None:
        if garment_type not in FEATURES["garment_type"]["values"]:
            raise StyleMateError("invalid_target", "지원하지 않는 아이템 종류입니다.")
        self.store, self.gateway, self.user_id = store, gateway, user_id
        self._lock = threading.RLock()
        self._worker: threading.Thread | None = None
        self._drafts: dict[str, dict[str, Any]] = {}
        request = self.store.start_request(user_id, input_id=_id(), text="개발자 관찰 요청", timezone="Asia/Seoul")
        self._state: dict[str, Any] = {
            "model": getattr(gateway, "model", "injected-test-model"), "provider": "codex-cli",
            "request_id": request["id"], "target": {"id": "item-1", "garment_type": garment_type},
            "busy": False, "phase": "ready", "actual_call": False, "completed_call": False, "last_call": None,
            "messages": [], "memories": [], "profile": None,
            "context": None, "trace": [], "last_error": None, "registry": registry_metadata(),
            "garment_types": deepcopy(FEATURES["garment_type"]["values"]),
        }
        self._refresh()

    def state(self) -> dict[str, Any]:
        with self._lock:
            return deepcopy(self._state)

    def _set(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)

    def _trace(self, phase: str, summary: str, data: Any = None) -> None:
        with self._lock:
            self._state["phase"] = phase
            self._state["trace"].append({"id": _id(), "at": _at(), "phase": phase, "summary": summary, "data": deepcopy(data)})
            self._state["trace"] = self._state["trace"][-60:]

    def _message(self, role: str, text: str, message_id: str | None = None) -> str:
        mid = message_id or _id()
        with self._lock:
            self._state["messages"].append({"id": mid, "role": role, "text": text, "at": _at()})
        return mid

    def _snapshot(self) -> dict[str, Any]:
        return self.store.snapshot(self.user_id, self._state["request_id"])

    @staticmethod
    def _extraction_memories(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        """Do not reintroduce inactive/unconfirmed/expired memories to the LLM."""
        now = datetime.fromisoformat(snapshot["now"])
        result = []
        for memory in snapshot["memories"]:
            if memory["status"] != "active" or memory["confirmed"] is not True:
                continue
            starts = memory.get("valid_from")
            ends = [memory.get("valid_until"), memory.get("retention_until")]
            if starts and datetime.fromisoformat(starts) > now:
                continue
            if any(end and datetime.fromisoformat(end) <= now for end in ends):
                continue
            result.append(memory)
        return result

    def _refresh(self) -> None:
        snapshot = self._snapshot()
        memories = snapshot["memories"]
        for memory in memories:
            memory["draft"] = deepcopy(self._drafts.get(memory["id"]))
        context = build_context(snapshot, [self._state["target"]])
        self._set(memories=memories, context=context)

    def _model_attempt(self, stage: str) -> None:
        if isinstance(self.gateway, CodexGateway):
            self._set(actual_call=True, completed_call=False, last_call={"stage": stage, "attempted": True, "completed": False})

    def _model_completed(self) -> None:
        if isinstance(self.gateway, CodexGateway):
            last = deepcopy(self._state["last_call"] or {})
            last["completed"] = True
            self._set(completed_call=True, last_call=last)

    def _proposal_trace(self, payload: Any, raw: Any, metadata: Any) -> None:
        self._model_completed()
        self._trace("feature-model-output", "LLM 목표값 제안 수신; 아직 검증 전", {"input": payload, "output": raw, "call": metadata})

    def _infer(self) -> None:
        self._set(profile=None)
        self._refresh()
        self._trace("feature-model", "유효 메모리 context로 목표값 생성", {"context": self._state["context"]})
        profile = ShoppingApp(self.store, CodexFeatureAdapter(self.gateway, self._proposal_trace, lambda: self._model_attempt("feature"))).infer_request(
            self.user_id, self._state["request_id"], [self._state["target"]])
        self._set(profile=profile)
        self._trace("validated-feature-map", "직접값·대상·근거·제약·최신성을 검증한 Feature Map", profile)

    def chat(self, text: str) -> None:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise StyleMateError("invalid_input", "1~4,000자의 테스트 문장을 입력해 주세요.")
        text = text.strip()
        mid = self._message("user", text)
        snapshot = self._snapshot()
        visible_memories = self._extraction_memories(snapshot)
        summaries = [{key: m[key] for key in ["id", "feature", "values", "polarity", "strength", "match", "scope", "status", "confirmed", "selector", "conditions", "content", "version"]} for m in visible_memories]
        payload = {"latest_message": text, "target": self._state["target"],
                   "history": [{"role": m["role"], "text": m["text"]} for m in self._state["messages"][-12:]],
                   "memories": summaries, "registry": registry_metadata()}
        self._trace("extract-model", "최신 입력과 현재 기억으로 메모리 후보 추출", payload)
        self._model_attempt("extract")
        raw = self.gateway.complete(EXTRACTION_INSTRUCTIONS, payload, extraction_schema())
        self._model_completed()
        self._trace("extraction-output", "LLM 추출 원본; 아직 저장/확인 전", {"output": raw, "call": getattr(self.gateway, "last_metadata", {})})
        extracted = validate_extraction(raw, text, visible_memories)
        actions, hints = [], {}
        for candidate in extracted["candidates"]:
            memory_id = _id()
            hints[memory_id] = {"scope_hint": candidate["scope_hint"], "quote": candidate["quote"],
                                "explanation": candidate["explanation"], "replaces": candidate["replaces"],
                                "condition_quotes": candidate["conditions"],
                                "source_message_id": mid,
                                "replace_versions": {m["id"]: m["version"] for m in snapshot["memories"] if m["id"] in candidate["replaces"]}}
            actions.append({"op": "create", "id": memory_id, "feature": candidate["feature"], "values": candidate["values"],
                            "polarity": candidate["polarity"], "strength": candidate["strength"], "match": candidate["match"],
                            "selector": {"garment_type": candidate["garment_type"]} if candidate["garment_type"] else {},
                            "conditions": {c["key"]: c["value"] for c in candidate["conditions"]},
                            "content": candidate["quote"], "scope": "short_term", "origin": "inferred", "confirmed": False,
                            "evidence_ref": "input:" + mid})
        if actions:
            receipt = self.store.apply_batch(self.user_id, self._state["request_id"], batch_id="extract:" + mid, actions=actions,
                                             expected_request_revision=snapshot["request"]["revision"], expected_profile_revision=snapshot["profile_revision"])
            # Exact duplicate creates can return an existing ID. Preserve its
            # original review hint instead of pretending a new item was made.
            known_ids = {m["id"] for m in snapshot["memories"]}
            for memory_id in receipt["memory_ids"]:
                if memory_id in hints and memory_id not in known_ids:
                    self._drafts[memory_id] = hints[memory_id]
            self._trace("candidate-stored", "추출을 검증하고 미확인 단기 후보만 SQLite에 저장", receipt)
        else:
            self._trace("no-candidate", "직접 저장할 후보 없음", {"questions": extracted["questions"], "unmapped": extracted["unmapped"]})
        reply_parts = [extracted["assistant_reply"]]
        if extracted["questions"]:
            reply_parts.append("\n".join(extracted["questions"]))
        if extracted["unmapped"]:
            reply_parts.append("사전에 없는 내용: " + ", ".join(extracted["unmapped"]))
        reply_parts.append(f"추출 후보 {len(actions)}개. 가운데에서 내용을 확인하면 이번 요청에 반영됩니다.")
        self._message("assistant", "\n\n".join(part for part in reply_parts if part.strip()))
        self._refresh()
        self._infer()

    def memory(self, op: str, memory_id: str, expected_version: int) -> None:
        if op not in {"confirm", "remember", "withdraw"} or type(expected_version) is not int:
            raise StyleMateError("invalid_input", "메모리 동작과 정수 버전을 확인해 주세요.")
        snapshot = self._snapshot()
        memories = {m["id"]: m for m in snapshot["memories"]}
        memory = memories.get(memory_id)
        if memory is None or memory["version"] != expected_version:
            raise StyleMateError("version_conflict", "메모리가 변경됐습니다. 새 상태에서 다시 선택해 주세요.")
        if memory["status"] not in {"candidate", "active"}:
            raise StyleMateError("invalid_transition", "활성 항목 또는 확인 중인 후보만 조작할 수 있습니다.")
        event_id, evidence = _id(), ""
        evidence = "developer-click:" + event_id
        actions, source_id, source_version = [], memory_id, expected_version
        if op == "withdraw":
            actions.append({"op": "withdraw", "memory_id": memory_id, "expected_version": expected_version, "evidence_ref": evidence})
        else:
            if op == "confirm" and memory["status"] != "candidate":
                raise StyleMateError("invalid_transition", "이미 확인된 항목입니다.")
            hint = self._drafts.get(memory_id, {})
            replaces = hint.get("replaces", []) if memory["status"] == "candidate" else []
            if replaces:
                old = memories.get(replaces[0])
                if old is None or old["scope"] != "short_term" or old["status"] != "active" or old["version"] != hint["replace_versions"].get(old["id"]):
                    raise StyleMateError("stale_proposal", "교체 근거가 변경됐습니다. 내용을 다시 추출해 주세요.")
                source_id, source_version = _id(), 1
                replacement = {key: deepcopy(memory[key]) for key in ["feature", "values", "polarity", "strength", "match", "selector", "conditions", "content", "scope"]}
                replacement.update(id=source_id, evidence_ref=evidence)
                actions.extend([
                    {"op": "withdraw", "memory_id": memory_id, "expected_version": expected_version, "evidence_ref": evidence},
                    {"op": "replace", "memory_id": old["id"], "expected_version": old["version"], "evidence_ref": evidence, "memory": replacement},
                ])
            elif memory["status"] == "candidate":
                actions.append({"op": "confirm", "memory_id": memory_id, "expected_version": expected_version, "evidence_ref": evidence})
                source_version += 1
            if op == "remember":
                if memory["scope"] != "short_term":
                    raise StyleMateError("invalid_transition", "이미 장기로 활용 중입니다.")
                actions.append({"op": "promote", "memory_id": source_id, "expected_version": source_version,
                                "evidence_ref": evidence, "consent_ref": "future-use-click:" + event_id})
        self._trace("user-memory-command", "테스터가 내용/범위를 명시 선택", {"op": op, "memory_id": memory_id, "actions": actions})
        receipt = self.store.apply_batch(self.user_id, self._state["request_id"], batch_id="review:" + event_id, actions=actions,
                                         expected_request_revision=snapshot["request"]["revision"], expected_profile_revision=snapshot["profile_revision"])
        self._trace("memory-applied", "기존 저장 계약의 원자적 batch 성공", receipt)
        self._refresh()
        self._infer()

    def new_request(self, garment_type: str) -> None:
        self._validate_garment(garment_type)
        request = self.store.start_request(self.user_id, input_id=_id(), text="개발자 새 요청", timezone="Asia/Seoul")
        self._set(request_id=request["id"], target={"id": "item-1", "garment_type": garment_type}, messages=[], profile=None, context=None, trace=[])
        self._drafts = {}
        self._trace("new-request", "새 요청: 이전 단기 항목은 이월하지 않고 유효 장기만 조회", {"request_id": request["id"]})
        self._refresh()
        self._infer()

    @staticmethod
    def _validate_garment(garment_type: str) -> None:
        if not isinstance(garment_type, str) or garment_type not in FEATURES["garment_type"]["values"]:
            raise StyleMateError("invalid_target", "지원하지 않는 아이템 종류입니다.")

    def target(self, garment_type: str) -> None:
        self._validate_garment(garment_type)
        self._set(target={"id": "item-1", "garment_type": garment_type})
        self._trace("target-changed", "대상별 기억 조회와 Feature Map 다시 생성", {"garment_type": garment_type})
        self._infer()

    def _perform(self, action: str, payload: dict[str, Any]) -> None:
        try:
            if action == "chat":
                self.chat(payload["text"])
            elif action == "memory":
                self.memory(payload["op"], payload["memory_id"], payload["expected_version"])
            elif action == "request":
                self.new_request(payload["garment_type"])
            elif action == "target":
                self.target(payload["garment_type"])
            else:
                self._infer()
            self._set(phase="ready")
        except StyleMateError as error:
            self._set(profile=None, last_error=error.as_dict(), phase="error")
            self._trace("error", "상태를 확인하세요. 모델 실패를 성공으로 표시하지 않습니다.", error.as_dict())
            try:
                self._refresh()
            except StyleMateError:
                pass
        except Exception:
            # Never expose exception text, CLI stderr, paths or process config.
            error = {"code": "inspector_error", "message": "처리 중 오류가 발생했습니다. 저장된 항목과 로그를 확인해 주세요."}
            self._set(profile=None, last_error=error, phase="error")
            self._trace("error", "처리 실패", error)
        finally:
            self._set(busy=False)

    def dispatch(self, action: str, payload: dict[str, Any], *, threaded: bool = True) -> None:
        fields = {"chat": {"text"}, "memory": {"op", "memory_id", "expected_version"}, "request": {"garment_type"}, "target": {"garment_type"}, "infer": set()}
        if action not in fields or not isinstance(payload, dict) or set(payload) != fields[action]:
            raise StyleMateError("invalid_input", "지원하지 않는 요청 형식입니다.")
        # Cheap validation happens before accepting a job or touching state.
        if action == "chat" and (not isinstance(payload["text"], str) or not payload["text"].strip() or len(payload["text"]) > 4000):
            raise StyleMateError("invalid_input", "1~4,000자의 테스트 문장을 입력해 주세요.")
        if action in {"target", "request"}:
            self._validate_garment(payload["garment_type"])
        if action == "memory" and (not isinstance(payload["op"], str) or payload["op"] not in {"confirm", "remember", "withdraw"} or not isinstance(payload["memory_id"], str) or type(payload["expected_version"]) is not int):
            raise StyleMateError("invalid_input", "메모리 동작·ID·정수 버전을 확인해 주세요.")
        with self._lock:
            if self._state["busy"]:
                raise StyleMateError("inspector_busy", "현재 호출이 끝난 뒤 다음 동작을 선택해 주세요.")
            self._state.update(busy=True, last_error=None, phase="starting")
        if threaded:
            self._worker = threading.Thread(target=self._perform, args=(action, deepcopy(payload)), daemon=True)
            self._worker.start()
        else:
            self._perform(action, deepcopy(payload))

    def close(self) -> None:
        if self._worker and self._worker.is_alive():
            self._worker.join()
        self.store.close()


def make_server(inspector: Inspector, port: int = 8765) -> ThreadingHTTPServer:
    """Serve only packaged UI/API on loopback; no directory/file browsing."""
    ui_path = Path(__file__).with_name("inspector.html")

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass

        def _host_allowed(self) -> bool:
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def _send(self, code: int, body: Any, *, html: bool = False) -> None:
            data = body.encode("utf-8") if html else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8" if html else "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if not self._host_allowed():
                self._send(403, {"error": {"code": "forbidden_host", "message": "로컬 주소로 접속해 주세요."}})
            elif self.path in {"/", "/index.html"}:
                self._send(200, ui_path.read_text(encoding="utf-8"), html=True)
            elif self.path == "/api/state":
                self._send(200, inspector.state())
            else:
                self._send(404, {"error": {"code": "not_found", "message": "지원하지 않는 경로입니다."}})

        def do_POST(self) -> None:
            origin = self.headers.get("Origin")
            if not self._host_allowed() or (origin is not None and origin != "http://" + self.headers.get("Host", "")):
                self._send(403, {"error": {"code": "forbidden_origin", "message": "로컬 화면에서 요청해 주세요."}})
                return
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
                self._send(415, {"error": {"code": "invalid_content_type", "message": "JSON 요청만 지원합니다."}})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 24000:
                    raise ValueError
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                routes = {"/api/chat": "chat", "/api/memory": "memory", "/api/request": "request", "/api/target": "target", "/api/infer": "infer"}
                if self.path not in routes:
                    self._send(404, {"error": {"code": "not_found", "message": "지원하지 않는 경로입니다."}})
                    return
                inspector.dispatch(routes[self.path], payload)
                self._send(202, {"accepted": True})
            except StyleMateError as error:
                self._send(409 if error.code == "inspector_busy" else 400, {"error": error.as_dict()})
            except (ValueError, UnicodeError):
                self._send(400, {"error": {"code": "invalid_input", "message": "요청 JSON과 길이를 확인해 주세요."}})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="StyleMate 개발자용 채팅/메모리/Feature Map 관찰 도구")
    parser.add_argument("--db", default=str(Path(tempfile.gettempdir()) / "stylemate-inspector" / "memory.sqlite3"))
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model", default="gpt-6-luna")
    parser.add_argument("--garment-type", default="Pants", choices=FEATURES["garment_type"]["values"])
    args = parser.parse_args(argv)
    Path(args.db).parent.mkdir(parents=True, exist_ok=True)
    inspector = Inspector(MemoryStore(args.db), CodexGateway(args.model), garment_type=args.garment_type)
    server = make_server(inspector, args.port)
    print(f"StyleMate developer inspector: http://127.0.0.1:{server.server_port}", flush=True)
    print(f"Model: {args.model} via Codex CLI (real calls); SQLite: {args.db}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        inspector.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
