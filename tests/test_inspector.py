from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from stylemate_memory.codex_llm import CodexGateway, validate_extraction
from stylemate_memory.errors import StyleMateError
from stylemate_memory.inspector import Inspector, make_server
from stylemate_memory.store import MemoryStore


def candidate(text, feature="fit", values=None, garment="Pants", **extra):
    result = dict(feature=feature, values=values or ["Relaxed"], garment_type=garment, polarity="prefer",
                  strength="soft", match="any", scope_hint="unknown", quote=text,
                  explanation="가상 모델이 사용자 표현을 구조화", conditions=[], replaces=[])
    result.update(extra)
    return result


def extracted(*items):
    return dict(assistant_reply="조건을 확인해 주세요.", candidates=list(items), questions=[], unmapped=[])


class FakeGateway:
    model = "fixture-model"
    last_metadata = {"provider": "injected-fixture"}
    def __init__(self):
        self.extraction = extracted()
        self.proposal = {"suggestions": [], "questions": []}
        self.calls = []
    def complete(self, instructions, payload, schema):
        self.calls.append(deepcopy(payload))
        return deepcopy(self.extraction if "candidates" in schema["properties"] else self.proposal)


class InspectorTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.db = Path(self.folder.name) / "memory.sqlite3"
        self.gateway = FakeGateway()
        self.tool = Inspector(MemoryStore(self.db), self.gateway)
        self.addCleanup(self.tool.close)

    def run_action(self, action, **payload):
        self.tool.dispatch(action, payload, threaded=False)
        return self.tool.state()

    def send(self, text, **extra):
        self.gateway.extraction = extracted(candidate(text, **extra))
        return self.run_action("chat", text=text)

    def review(self, memory, op):
        return self.run_action("memory", op=op, memory_id=memory["id"], expected_version=memory["version"])

    def feature(self, state, key):
        return state["profile"]["targets"][0]["features"][key]

    def test_chat_stores_candidates_only_and_confirmation_fills_profile(self):
        state = self.send("평소 바지는 여유 있게", scope_hint="baseline")
        memory = state["memories"][0]
        self.assertEqual(memory["status"], "candidate")
        self.assertEqual(memory["scope"], "short_term")
        self.assertFalse(memory["confirmed"])
        self.assertIsNone(memory["consent_ref"])
        self.assertEqual(self.feature(state, "fit")["status"], "unspecified")
        confirmed = self.review(memory, "confirm")
        self.assertEqual(self.feature(confirmed, "fit")["values"], ["Relaxed"])
        self.assertEqual(self.feature(confirmed, "fit")["source_ids"], [memory["id"]])
        self.assertEqual(confirmed["memories"][0]["version"], 2)
        self.assertEqual(memory["evidence_ref"], "input:" + memory["draft"]["source_message_id"])
        self.assertTrue(any(t["phase"] == "validated-feature-map" for t in confirmed["trace"]))

    def test_explicit_remember_survives_new_request_and_temporary_exception_does_not(self):
        state = self.send("평소 바지는 여유 있게", scope_hint="baseline")
        state = self.review(state["memories"][0], "remember")
        long_memory = next(m for m in state["memories"] if m["scope"] == "long_term")
        self.assertTrue(long_memory["consent_ref"].startswith("future-use-click:"))
        state = self.run_action("request", garment_type="Pants")
        self.assertEqual(self.feature(state, "fit")["values"], ["Relaxed"])
        state = self.send("오늘만 바지는 꼭 슬림", values=["Slim"], scope_hint="current", polarity="require", strength="hard")
        pending = next(m for m in state["memories"] if m["status"] == "candidate")
        state = self.review(pending, "confirm")
        self.assertEqual(self.feature(state, "fit")["values"], ["Slim"])
        state = self.run_action("request", garment_type="Pants")
        self.assertEqual(self.feature(state, "fit")["values"], ["Relaxed"])
        self.assertEqual(state["messages"], [])
        self.assertFalse(any(m["id"] == pending["id"] for m in state["memories"]))
        self.assertEqual({m["id"] for m in state["memories"]}, {long_memory["id"]})

    def test_current_correction_uses_existing_atomic_replace(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "confirm")
        old = state["memories"][0]
        state = self.send("아니 보통 핏으로", values=["Regular"], replaces=[old["id"]])
        draft = next(m for m in state["memories"] if m["status"] == "candidate")
        state = self.review(draft, "confirm")
        self.assertIsNone(state["last_error"])
        self.assertEqual(self.feature(state, "fit")["values"], ["Regular"])
        active = next(m for m in state["memories"] if m["status"] == "active")
        self.assertEqual(active["family_id"], old["family_id"])
        self.assertNotEqual(active["id"], draft["id"])
        self.assertEqual(next(m for m in state["memories"] if m["id"] == old["id"])["status"], "superseded")

    def test_correction_and_remember_are_one_batch(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "confirm")
        old = state["memories"][0]
        state = self.send("보통 핏으로 바꿔", values=["Regular"], replaces=[old["id"]])
        state = self.review(next(m for m in state["memories"] if m["status"] == "candidate"), "remember")
        self.assertIsNone(state["last_error"])
        state = self.run_action("request", garment_type="Pants")
        self.assertEqual(self.feature(state, "fit")["values"], ["Regular"])

    def test_model_cannot_invent_evidence_or_edit_long_term_memory(self):
        for malformed in [candidate("not-in-input"), candidate("hello", feature="fabric", values=["Cotton"]), candidate("hello", replaces=["invented-id"])]:
            self.gateway.extraction = extracted(malformed)
            state = self.run_action("chat", text="hello")
            self.assertEqual(state["last_error"]["code"], "invalid_extraction")
            self.assertEqual(state["memories"], [])
            self.assertIsNone(state["profile"])
        state = self.send("기본 핏은 여유 있게")
        state = self.review(state["memories"][0], "remember")
        long_id = next(m["id"] for m in state["memories"] if m["scope"] == "long_term")
        self.gateway.extraction = extracted(candidate("오늘 슬림", values=["Slim"], replaces=[long_id]))
        state = self.run_action("chat", text="오늘 슬림")
        self.assertEqual(state["last_error"]["code"], "invalid_extraction")

    def test_stale_replacement_does_not_change_current_memory(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "confirm")
        old = state["memories"][0]
        state = self.send("보통 핏으로 바꿔", values=["Regular"], replaces=[old["id"]])
        draft = next(m for m in state["memories"] if m["status"] == "candidate")
        self.tool.store.apply_batch(self.tool.user_id, state["request_id"], batch_id="external-withdraw", actions=[
            dict(op="withdraw", memory_id=old["id"], expected_version=old["version"], evidence_ref="external-user")])
        before = self.tool.store.snapshot(self.tool.user_id, state["request_id"])
        state = self.review(draft, "confirm")
        self.assertEqual(state["last_error"]["code"], "stale_proposal")
        self.assertEqual(before["memories"], self.tool.store.snapshot(self.tool.user_id, state["request_id"])["memories"])

    def test_fabricated_condition_is_rejected_before_memory_write(self):
        for conditions in [[dict(key="occasion", value="면접", quote="바지는 검은색")], [dict(key="occasion", value="면접", quote="면접 때")]]:
            self.gateway.extraction = extracted(candidate("바지는 검은색", feature="color", values=["Black"], conditions=conditions))
            state = self.run_action("chat", text="바지는 검은색")
            self.assertEqual(state["last_error"]["code"], "invalid_extraction")
            self.assertEqual(state["memories"], [])
        message = "면접 때 바지는 검은색"
        state = self.send(message, feature="color", values=["Black"], conditions=[dict(key="occasion", value="면접", quote="면접 때")])
        self.assertIsNone(state["last_error"])
        self.assertEqual(state["memories"][0]["conditions"], {"occasion": "면접"})

    def test_failed_real_gateway_invocation_is_displayed_as_attempted(self):
        def timeout(*a, **k): raise subprocess.TimeoutExpired("private-info", 1)
        self.tool.gateway = CodexGateway(executable="fake", runner=timeout)
        state = self.run_action("infer")
        self.assertEqual(state["last_error"]["code"], "provider_timeout")
        self.assertTrue(state["actual_call"])
        self.assertFalse(state["completed_call"])
        self.assertEqual(state["last_call"], {"stage": "feature", "attempted": True, "completed": False})

    def test_bad_inference_keeps_saved_memory_and_removes_stale_profile(self):
        state = self.send("바지는 네이비", feature="color", values=["Navy"])
        memory = state["memories"][0]
        self.gateway.proposal = {"suggestions": [dict(target_id="item-1", feature="color", values=["Red"], match="any", source_ids=[memory["id"]], reason="wrong")], "questions": []}
        state = self.review(memory, "confirm")
        self.assertEqual(state["last_error"]["code"], "model_constraint_violation")
        self.assertIsNone(state["profile"])
        self.assertEqual(state["memories"][0]["status"], "active")
        self.assertEqual(state["memories"][0]["values"], ["Navy"])

    def test_target_isolation_and_fact_based_inference(self):
        state = self.send("셔츠는 흰색", feature="color", values=["White"], garment="Shirt")
        state = self.review(state["memories"][0], "confirm")
        self.assertEqual(self.feature(state, "color")["status"], "unspecified")
        state = self.run_action("target", garment_type="Shirt")
        self.assertEqual(self.feature(state, "color")["values"], ["White"])
        state = self.send("단정한 셔츠", feature="goal", values=["단정"], garment="Shirt")
        goal = next(m for m in state["memories"] if m["status"] == "candidate")
        self.gateway.proposal = {"suggestions": [dict(target_id="item-1", feature="mood", values=["Refined"], match="any", source_ids=[goal["id"]], reason="단정 목표")], "questions": []}
        state = self.review(goal, "confirm")
        self.assertEqual(self.feature(state, "mood")["status"], "inferred")
        self.assertEqual(self.feature(state, "mood")["source_ids"], [goal["id"]])

    def test_withdraw_recomputes_and_model_does_not_rewrite_store(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "remember")
        long_memory = next(m for m in state["memories"] if m["scope"] == "long_term")
        before = self.tool.store.snapshot(self.tool.user_id, state["request_id"])
        self.run_action("infer")
        after = self.tool.store.snapshot(self.tool.user_id, state["request_id"])
        self.assertEqual(before["memories"], after["memories"])
        state = self.review(long_memory, "withdraw")
        self.assertEqual(self.feature(state, "fit")["status"], "unspecified")

    def test_withdrawn_unconfirmed_and_expired_memories_are_not_sent_to_extraction(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "confirm")
        self.review(state["memories"][0], "withdraw")
        state = self.send("바지는 네이비", feature="color", values=["Navy"])
        self.tool.store.apply_batch(self.tool.user_id, state["request_id"], batch_id="expired-fixture", actions=[
            dict(op="create", feature="season", values=["Winter"], content="expired fixture", selector={"garment_type": "Pants"},
                 confirmed=True, evidence_ref="fixture", valid_until="2020-01-01T00:00:00+00:00")])
        self.gateway.extraction = extracted()
        self.run_action("chat", text="다른 조건은 없어")
        latest = next(payload for payload in reversed(self.gateway.calls) if "latest_message" in payload)
        self.assertEqual(latest["memories"], [])

    def test_busy_rejection_state_polling_and_validation(self):
        started, release = threading.Event(), threading.Event()
        original = self.gateway.complete
        def slow(*args):
            started.set()
            release.wait(2)
            return original(*args)
        self.gateway.complete = slow
        self.tool.dispatch("infer", {})
        self.assertTrue(started.wait(1))
        self.assertTrue(self.tool.state()["busy"])
        try:
            with self.assertRaises(StyleMateError) as caught:
                self.tool.dispatch("request", {"garment_type": "Pants"})
            self.assertEqual(caught.exception.code, "inspector_busy")
        finally:
            release.set()
            self.tool._worker.join(3)
        self.assertFalse(self.tool.state()["busy"])
        with self.assertRaises(StyleMateError):
            self.tool.dispatch("memory", {"op": "confirm", "memory_id": "id", "expected_version": True})

    def test_restart_retains_long_memory_but_not_old_chat_or_short_context(self):
        state = self.send("바지는 여유 있게")
        state = self.review(state["memories"][0], "remember")
        self.tool.close()
        restarted = Inspector(MemoryStore(self.db), FakeGateway())
        try:
            restarted.dispatch("infer", {}, threaded=False)
            state = restarted.state()
            self.assertEqual(self.feature(state, "fit")["values"], ["Relaxed"])
            self.assertEqual(state["messages"], [])
            self.assertTrue(all(m["scope"] == "long_term" for m in state["memories"]))
        finally:
            restarted.close()


class GatewayTests(unittest.TestCase):
    def event_result(self, items=None, returncode=0, stderr="private-info"):
        items = items or [{"type": "agent_message", "text": '{"ok":true}'}]
        events = [dict(type="item.completed", item=item) for item in items]
        events.append(dict(type="turn.completed", usage={"input_tokens": 5, "output_tokens": 3}))
        return subprocess.CompletedProcess([], returncode, "\n".join(json.dumps(e) for e in events), stderr)

    def test_ephemeral_read_only_cli_and_schema_are_used_without_shell(self):
        captured = {}
        def runner(command, **kwargs):
            captured.update(command=command, kwargs=kwargs)
            schema_path = Path(command[command.index("--output-schema") + 1])
            self.assertEqual(json.loads(schema_path.read_text()), {"type": "object"})
            return self.event_result()
        gateway = CodexGateway(executable="fake-codex", runner=runner)
        self.assertEqual(gateway.complete("instruction", {"text": "input"}, {"type": "object"}), {"ok": True})
        self.assertIn("--ignore-user-config", captured["command"])
        self.assertIn("--ephemeral", captured["command"])
        self.assertIn("read-only", captured["command"])
        self.assertNotIn("shell", captured["kwargs"])
        self.assertIn('"text": "input"', captured["kwargs"]["input"])
        self.assertEqual(gateway.last_metadata["usage"]["input_tokens"], 5)

    def test_non_model_tool_output_and_provider_failures_are_sanitized(self):
        for response, code in [(self.event_result([{"type": "command_execution", "command": "private-info"}]), "unexpected_model_tool"),
                               (self.event_result(returncode=1), "provider_unavailable"),
                               (subprocess.CompletedProcess([], 0, "{}", "private-info"), "provider_incomplete")]:
            gateway = CodexGateway(executable="fake", runner=lambda *args, **kwargs: response)
            with self.assertRaises(StyleMateError) as caught:
                gateway.complete("", {}, {})
            self.assertEqual(caught.exception.code, code)
            self.assertNotIn("private-info", caught.exception.message)

    def test_timeout_and_invalid_json_do_not_become_success(self):
        def timeout(*args, **kwargs): raise subprocess.TimeoutExpired("private-info", 1)
        for runner, code in [(timeout, "provider_timeout"), (lambda *args, **kwargs: self.event_result([{"type": "agent_message", "text": "not-json"}]), "invalid_output")]:
            with self.assertRaises(StyleMateError) as caught:
                CodexGateway(executable="fake", runner=runner).complete("", {}, {})
            self.assertEqual(caught.exception.code, code)

    def test_pre_turn_notice_is_counted_without_leaking_message(self):
        notice = json.dumps({"type": "item.completed", "item": {"type": "error", "message": "private-info"}})
        response = self.event_result()
        response.stdout = notice + '\n' + json.dumps({"type": "turn.started"}) + '\n' + response.stdout
        gateway = CodexGateway(executable="fake", runner=lambda *a, **k: response)
        self.assertEqual(gateway.complete("", {}, {}), {"ok": True})
        self.assertEqual(gateway.last_metadata["startup_notice_count"], 1)
        self.assertNotIn("private-info", json.dumps(gateway.last_metadata))
        response.stdout = json.dumps({"type": "turn.started"}) + '\n' + notice + '\n' + self.event_result().stdout
        with self.assertRaises(StyleMateError) as caught:
            gateway.complete("", {}, {})
        self.assertEqual(caught.exception.code, "provider_unavailable")

    def test_malformed_extraction_enums_are_rejected(self):
        for key in ["feature", "garment_type", "polarity", "strength", "match", "scope_hint"]:
            value = candidate("hello")
            value[key] = []
            with self.assertRaises(StyleMateError):
                validate_extraction(extracted(value), "hello", [])


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tool = Inspector(MemoryStore(":memory:"), FakeGateway())
        self.server = make_server(self.tool, 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)
    def cleanup(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
        self.tool.close()
    def request(self, method, path, body=None, headers=None):
        connection = HTTPConnection("127.0.0.1", self.server.server_port, timeout=2)
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response.status, data
    def test_ui_state_and_unavailable_file_paths(self):
        status, body = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"/api/chat", body)
        self.assertEqual(self.request("GET", "/api/state")[0], 200)
        self.assertEqual(self.request("GET", "/../AGENTS.md")[0], 404)
    def test_external_origin_host_and_non_json_are_rejected(self):
        self.assertEqual(self.request("POST", "/api/infer", "{}", {"Content-Type": "application/json", "Origin": "https://external.example"})[0], 403)
        self.assertEqual(self.request("GET", "/api/state", headers={"Host": "external.example"})[0], 403)
        self.assertEqual(self.request("POST", "/api/infer", "{}", {"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.request("POST", "/api/chat", '{"text": ""}', {"Content-Type": "application/json"})[0], 400)


if __name__ == "__main__":
    unittest.main()
