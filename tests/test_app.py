from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stylemate_memory.app import ShoppingApp
from stylemate_memory.cli import configured_adapter, main, synthetic_demo
from stylemate_memory.errors import StyleMateError
from stylemate_memory.inference import RuleAdapter
from stylemate_memory.llm import OpenAIResponsesAdapter
from stylemate_memory.store import MemoryStore


class EmptyAdapter:
    def propose(self, context):
        return {"suggestions": [], "questions": []}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.now = datetime(2026, 10, 14, 9, tzinfo=timezone.utc)
        self.store = MemoryStore(Path(self.folder.name) / "memory.sqlite3", clock=lambda: self.now)
        self.addCleanup(self.store.close)
        self.request = self.store.start_request("alice", input_id="request-1", text="쇼핑 바지", timezone="Asia/Seoul")
        self.targets = [{"id": "pants-1", "garment_type": "Pants"}]

    def create(self, feature="fit", values=None, **extra):
        action = {
            "op": "create", "feature": feature, "values": values or ["Relaxed"],
            "confirmed": True, "evidence_ref": f"input:{feature}",
            "content": "사용자 확인 조건", "selector": {"garment_type": "Pants"},
        }
        action.update(extra)
        receipt = self.store.apply_batch("alice", self.request["id"], batch_id=f"create-{feature}", actions=[action])
        return receipt["memory_ids"][0]

    def test_direct_conditions_survive_empty_model_without_memory_writes(self):
        memory_id = self.create()
        before = self.store.snapshot("alice", self.request["id"])
        result = ShoppingApp(self.store, EmptyAdapter()).infer_request("alice", self.request["id"], self.targets)
        after = self.store.snapshot("alice", self.request["id"])
        self.assertEqual(result["targets"][0]["features"]["fit"]["values"], ["Relaxed"])
        self.assertEqual(result["request_id"], self.request["id"])
        self.assertEqual(result["versions"]["request"], before["request"]["revision"])
        self.assertEqual(result["versions"]["memories"], {memory_id: 1})
        self.assertEqual(before, after)

    def test_responses_adapter_is_connected_to_real_store_with_fake_http(self):
        self.create()
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append(payload)
            context = json.loads(payload["input"])["context"]
            self.assertEqual(context["targets"][0]["garment_type"], "Pants")
            self.assertNotIn("user_id", context)
            self.assertFalse(payload["store"])
            self.assertTrue(payload["text"]["format"]["strict"])
            return {
                "status": "completed", "output": [{"type": "message", "content": [{
                    "type": "output_text", "text": json.dumps({"suggestions": [], "questions": []})
                }]}],
            }

        adapter = OpenAIResponsesAdapter(model="dummy-test-model", api_key="dummy-test-key", transport=transport)
        before = self.store.snapshot("alice", self.request["id"])
        profile = ShoppingApp(self.store, adapter).infer_request("alice", self.request["id"], self.targets)
        self.assertEqual(profile["targets"][0]["features"]["fit"]["values"], ["Relaxed"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(before, self.store.snapshot("alice", self.request["id"]))

    def test_late_response_after_profile_change_is_discarded(self):
        memory_id = self.create(scope="long_term", consent_ref="future-use-confirmation")
        store = self.store
        request_id = self.request["id"]

        class ConcurrentAdapter:
            def propose(self, context):
                store.apply_batch("alice", request_id, batch_id="withdraw-during-model", actions=[{
                    "op": "withdraw", "memory_id": memory_id, "expected_version": 1,
                    "evidence_ref": "user-withdraws-now",
                }])
                return {"suggestions": [], "questions": []}

        with self.assertRaises(StyleMateError) as caught:
            ShoppingApp(self.store, ConcurrentAdapter()).infer_request("alice", request_id, self.targets)
        self.assertEqual(caught.exception.code, "stale_context")

    def test_late_response_after_close_is_discarded(self):
        self.create()
        store, request_id = self.store, self.request["id"]

        class ConcurrentAdapter:
            def propose(self, context):
                store.close_request("alice", request_id)
                return {"suggestions": [], "questions": []}

        with self.assertRaises(StyleMateError) as caught:
            ShoppingApp(self.store, ConcurrentAdapter()).infer_request("alice", request_id, self.targets)
        self.assertEqual(caught.exception.code, "stale_context")

    def test_expiry_during_inference_is_discarded_without_version_change(self):
        self.create(valid_until=(self.now + timedelta(seconds=1)).isoformat())
        test = self

        class ClockAdapter:
            def propose(self, context):
                test.now += timedelta(seconds=1)
                return {"suggestions": [], "questions": []}

        with self.assertRaises(StyleMateError) as caught:
            ShoppingApp(self.store, ClockAdapter()).infer_request("alice", self.request["id"], self.targets)
        self.assertEqual(caught.exception.code, "stale_context")

    def test_rule_demo_today_and_next_request_without_network(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("demo must be offline")):
            result = synthetic_demo()
        self.assertEqual(result["today"]["targets"][0]["features"]["fit"]["values"], ["Slim"])
        self.assertEqual(result["next_request"]["targets"][0]["features"]["fit"]["values"], ["Relaxed"])
        self.assertTrue(result["memory_unchanged_by_inference"])
        self.assertFalse(result["live_llm_called"])
        self.assertEqual(result["feature_count"], 17)

    def test_explicit_configuration_requires_model_and_key(self):
        self.assertIsInstance(configured_adapter("rule", None, {}), RuleAdapter)
        with self.assertRaises(StyleMateError) as caught:
            configured_adapter("other-provider", None, {})
        self.assertEqual(caught.exception.code, "invalid_provider")
        with self.assertRaises(StyleMateError):
            configured_adapter("openai", None, {})
        adapter = configured_adapter("openai", "test-model", {"OPENAI_API_KEY": "dummy-test-key"})
        self.assertIsInstance(adapter, OpenAIResponsesAdapter)

    def test_cli_bad_json_is_safe_and_registry_is_accessible(self):
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(main(["features"]), 0)
            result = json.loads(output.getvalue())
        self.assertEqual(len(result["features"]), 17)
        broken = Path(self.folder.name) / "invalid.json"
        broken.write_text("not JSON", encoding="utf-8")
        with patch("sys.stdout", new_callable=io.StringIO) as output:
            code = main(["batch", "--db", str(Path(self.folder.name) / "memory.sqlite3"),
                         "--user", "alice", "--request", self.request["id"], "--batch-id", "bad-file",
                         "--actions-file", str(broken)])
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_input_file")


if __name__ == "__main__":
    unittest.main()
