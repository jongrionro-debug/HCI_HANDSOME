"""A2 service integration: real SQLite/catalog, synthetic products, fake HTTP."""

import base64
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from stylemate_memory import contracts as c
from stylemate_memory.app import ConsumerService
from stylemate_memory.cli import main as cli_main
from stylemate_memory.inspector import main as inspector_main
from stylemate_memory.errors import StyleMateError
from stylemate_memory.llm import OpenAIResponsesGateway
from stylemate_memory.model_io import FakeModelGateway
from stylemate_memory.settings import ConsumerSettings


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPioAAAAASUVORK5CYII=")


def product(pid, color):
    return {"format_version": c.CATALOG_FORMAT_VERSION, "product_id": pid,
        "source": {"source_id": "synthetic-a2", "url": f"https://example.invalid/{pid}", "collected_at": "2026-10-30T09:00:00+09:00"},
        "title": f"합성 바지 {pid}", "description": "판매 상품이 아닌 통합 검증 fixture", "garment_type": "Pants",
        "raw_metadata": {"supplier_type": "Slacks", "supplier_color": color, "supplier_fit": "Wide"}, "labels": [],
        "images": [{"image_id": f"image-{pid}", "kind": "local", "location": f"{pid}.png", "source_revision": "synthetic-v1",
                    "sha256": None, "regions": []}]}


class FakeTransport:
    def __init__(self):
        self.calls = []
        self.fail_extract = False
        self.fail_propose = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.pause = None

    def __call__(self, url, headers, payload, timeout):
        self.calls.append(deepcopy(payload))
        self_kind = "extract" if "candidates" in payload["text"]["format"]["schema"]["properties"] else "propose"
        if self.pause == self_kind:
            self.entered.set()
            if not self.release.wait(5):
                raise AssertionError("test did not release fake model")
        if (self_kind == "extract" and self.fail_extract) or (self_kind == "propose" and self.fail_propose):
            raise StyleMateError("provider_timeout", "private provider detail must never reach a user")
        inputs = json.loads(payload["input"])
        if "payload" in inputs:
            inputs = inputs["payload"]
        if self_kind == "propose":
            value = {"suggestions": [], "questions": []}
        else:
            sources = inputs["sources"]
            text = next((s for s in sources if s["kind"] == "user_text"), None)
            candidates = []
            if text:
                color = "Beige" if "베이지" in text["content"] else "Navy"
                candidates = [{"candidate_key": "one", "content": text["content"], "kind": "preference", "fact": None,
                    "selector": {"garment_type": "Pants", "slot_id": None}, "conditions": {}, "condition_quotes": {},
                    "polarity": "prefer", "strength": "soft", "origin_hint": "explicit", "scope_hint": "unknown",
                    "source_ids": [text["source_id"]], "quote": text["content"],
                    "bindings": [{"domain": "PI", "feature": "Color", "values": [color], "match": "any", "polarity": "prefer", "strength": "soft"}]}]
            value = {"candidates": candidates, "questions": []}
        return {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}]}


class ServiceFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="lumi-a2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "images"
        self.images.mkdir()
        self.records = [product("navy", "Navy"), product("beige", "Beige")]
        for record in self.records:
            (self.images / record["images"][0]["location"]).write_bytes(PNG)
        self.data = self.root / "synthetic.json"
        self.data.write_text(json.dumps(self.records), encoding="utf-8")
        self.now = datetime(2026, 10, 30, tzinfo=timezone.utc)
        self.transport = FakeTransport()
        self.gateway = OpenAIResponsesGateway(model="dummy-a2-model", api_key="dummy-a2-key", transport=self.transport)
        self.serial = 0
        self.service = self.open_service()
        self.addCleanup(lambda: self.service.close())
        self.service.import_catalog(self.data)
        self.service.build_catalog_maps()

    def open_service(self):
        return ConsumerService(self.root / "memory.sqlite3", self.root / "catalog.sqlite3", self.gateway,
                               user_id="synthetic-user", image_root=self.images, clock=lambda: self.now)

    def state(self):
        return self.service.state()

    def send(self, action, *, command=None, ok=True):
        s = self.state()
        self.serial += 1
        start = (command["action"] if command else action)["op"] == "start_request"
        command = command or {"contract_version": c.CONTRACT_VERSION, "command_id": f"a2-{self.serial}",
            "request_id": None if start else s["request"]["id"], "expected": None if start else s["expected"], "action": action}
        result = self.service.command(command)
        if ok:
            self.assertNotEqual(result["outcome"], "rejected", result)
        return result, command

    def start(self, text="네이비를 좋아해요", mode="shopping"):
        result, command = self.send({"op": "start_request", "mode": mode, "timezone": "Asia/Seoul",
            "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": text})
        self.service.wait_idle()
        return self.state(), command

    def review(self, purpose, memory=None, *, accept=True, text=None):
        memory = memory or self.state()["memories"][0]
        self.send({"op": "prepare_review", "purpose": purpose, "subject_refs": [memory["ref"]], "proposed_text": text})
        if text is not None:
            self.service.wait_idle()
        s = self.state()
        self.assertTrue(s["reviews"], s)
        result, command = self.send({"op": "respond_review", "display_ref": s["reviews"][0]["ref"],
                                    "decision": "accept" if accept else "decline"})
        return result, command

    def snapshot(self):
        return self.service.inspect_request(self.state()["request"]["id"])["snapshot"]


class ConsumerServiceTests(ServiceFixture):
    def test_text_recommend_feedback_separate_confirmations_search_end_and_reuse(self):
        # New consumer Maps are PI-only. Keep this regression on explicitly
        # supplied legacy full Maps so >4,000-character structured image input
        # remains covered independently of the new catalog generation policy.
        def legacy_maps():
            from stylemate_memory.catalog_mapping import build_product_map
            for record in self.service._catalog.export_records():
                pid = record["product_id"]
                mapped = build_product_map(record, raw_version=self.service._catalog.raw_version(pid), registry=self.service.registry)
                self.service._catalog.save_product_map(mapped, expected_raw_version=mapped["raw_version"],
                    expected_map_version=self.service._catalog.get_product_map(pid)["map_version"])
        self.service._run(legacy_maps)
        s, start_command = self.start()
        self.assertEqual(s["operation"], "blocked", s)
        self.assertFalse(s["cards"], s)  # C2 requires confirmed evidence first
        self.assertFalse(s["memories"][0]["confirmed"])
        first_count = len(self.snapshot()["evidence"])
        self.send({}, command=start_command)
        self.assertEqual(len(self.snapshot()["evidence"]), first_count)
        self.review("confirm_content")
        self.assertTrue(self.state()["memories"][0]["confirmed"])
        self.assertFalse(self.snapshot()["bindings"][0]["confirmed"])
        self.review("confirm_bindings")
        self.assertTrue(self.snapshot()["bindings"][0]["confirmed"])
        self.send({"op": "explore"})
        self.service.wait_idle()
        s = self.state()
        self.assertEqual(s["operation"], "idle", s)
        for kind in ("round", "candidate_set", "feedback"):
            self.assertEqual(len([r for r in s["expected"]["object_versions"] if r["type"] == kind]), 1, s["expected"])
        card = s["cards"][0]
        refs = s["expected"]["object_versions"]
        round_ref = next(r for r in refs if r["type"] == "round")
        set_ref = next(r for r in reversed(refs) if r["type"] == "candidate_set")
        # Resolve the current issued set, since Expected may include history.
        active = next(r for r in self.snapshot()["rounds"] if r["status"] == "active")
        set_ref = active["candidate_set_ref"]
        self.transport.pause = "propose"
        self.send({"op": "submit_feedback", "round_id": round_ref["id"], "candidate_set_id": set_ref["id"],
            "reaction": "selected", "selections": [{"target_id": card["target_id"], "candidate_id": card["candidate_id"],
                "part_ref": {"image_id": card["image_id"], "image_version": card["image_version"], "region_id": None, "box": [0.1, 0.2, 0.8, 0.9]}}],
            "text": "베이지로 바꾸고 싶어요", "question_id": None})
        try:
            self.assertTrue(self.transport.entered.wait(2), self.state())
            self.assertEqual(self.state()["operation"], "running")
            self.assertEqual(self.state()["cards"], [])
        finally:
            self.transport.release.set()
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "idle", self.state())
        self.assertTrue(any(m["content"] == "베이지로 바꾸고 싶어요" for m in self.state()["memories"]))
        image_source = next(s for call in reversed(self.transport.calls)
                            for s in json.loads(call["input"])["sources"] if s["kind"] == "image_selection")
        self.assertGreater(len(image_source["content"]), 4000)
        assertions = json.loads(image_source["content"])["product_assertions"]
        self.assertEqual(len(assertions), 37)
        self.assertTrue(any(a["status"] == "unknown" for a in assertions))
        self.assertEqual(len(self.snapshot()["feedback"]), 2)
        self.assertEqual(len([e for e in self.snapshot()["evidence"] if e["kind"] == "image_selection"]), 1)
        self.assertEqual(len(self.snapshot()["consents"]), 0)
        self.send({"op": "select_final", "candidate_set_ref": next(r for r in self.snapshot()["rounds"] if r["status"] == "active")["candidate_set_ref"],
                   "candidate_id": self.state()["cards"][0]["candidate_id"]})
        self.assertEqual(self.state()["request"]["status"], "open")
        self.send({"op": "end_request"})
        self.assertEqual(self.state()["request"]["status"], "closed")
        self.assertEqual(len(self.snapshot()["consents"]), 0)
        memory = next(m for m in self.state()["memories"] if m["confirmed"])
        self.review("future_reuse", memory, accept=False)
        self.assertFalse(any(m["scope"] == "long_term" for m in self.state()["memories"]))
        self.review("future_reuse", memory)
        self.assertTrue(any(m["scope"] == "long_term" for m in self.state()["memories"]))
        for call in self.transport.calls:
            self.assertFalse(call["store"])
            self.assertNotIn("synthetic-user", call["input"])

    def test_pending_retry_does_not_duplicate_input_and_provider_failure_has_no_fallback(self):
        self.transport.fail_extract = True
        s, _ = self.start()
        self.assertEqual(s["operation"], "interpretation_pending", s)
        self.assertEqual(s["error"]["code"], "provider_timeout")
        self.assertNotIn("private provider", json.dumps(s))
        before = self.snapshot()
        feedback = before["feedback"][0]
        self.transport.fail_extract = False
        self.send({"op": "retry_extraction", "feedback_ref": {"type": "feedback", "id": feedback["id"], "version": feedback["version"]}})
        self.service.wait_idle()
        self.assertEqual(len(self.snapshot()["evidence"]), len(before["evidence"]))
        self.assertEqual(len(self.snapshot()["feedback"]), 1)
        self.assertEqual(self.state()["operation"], "blocked", self.state())
        self.review("confirm_content")
        self.transport.fail_propose = True
        self.send({"op": "explore"})
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "error")
        self.assertEqual(self.state()["error"]["code"], "provider_timeout")
        self.service.close()
        self.service = self.open_service()
        self.assertEqual(self.state()["operation"], "error")
        self.assertEqual(self.state()["error"]["code"], "provider_timeout")

    def test_restart_resume_new_request_isolation_and_delete_replay(self):
        s, _ = self.start(mode="onboarding")
        self.review("confirm_content")
        self.send({"op": "end_request"})
        self.review("future_reuse")
        old_id = self.state()["request"]["id"]
        self.service.close()
        self.service = self.open_service()
        self.assertEqual(self.state()["request"]["id"], old_id)
        s, _ = self.start("베이지가 좋아요")
        self.assertEqual(len([m for m in s["memories"] if m["scope"] == "short_term"]), 1)
        self.assertEqual(len([m for m in s["memories"] if m["scope"] == "long_term"]), 1)
        command = {"contract_version": c.CONTRACT_VERSION, "command_id": "resume-old", "request_id": old_id,
                   "expected": self.service.state(old_id)["expected"], "action": {"op": "resume_request"}}
        self.send({}, command=command)
        self.assertEqual(self.state()["request"]["id"], old_id)
        memory = next(m for m in self.state()["memories"] if m["scope"] == "long_term")
        _, delete_command = self.review("delete", memory)
        self.assertFalse(any(m["scope"] == "long_term" for m in self.state()["memories"]))
        self.send({}, command=delete_command)
        self.service.close()
        self.service = self.open_service()
        self.send({}, command=delete_command)
        self.assertFalse(self.state()["memories"])

    def test_late_extraction_after_end_and_new_request_cannot_create_candidates(self):
        self.transport.pause = "extract"
        self.send({"op": "start_request", "mode": "shopping", "timezone": "UTC",
            "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": "네이비"})
        self.assertTrue(self.transport.entered.wait(2))
        old_id = self.state()["request"]["id"]
        self.send({"op": "end_request"})
        self.transport.pause = None
        self.start("베이지")
        self.transport.release.set()
        self.service._models.submit(lambda: None).result(timeout=3)
        self.assertFalse(self.service.inspect_request(old_id)["snapshot"]["memories"])
        self.assertTrue(all(m["content"] == "베이지" for m in self.state()["memories"]))

    def test_late_proposal_after_deletion_is_discarded(self):
        self.start()
        self.review("confirm_content")
        self.transport.pause = "propose"
        self.send({"op": "explore"})
        self.assertTrue(self.transport.entered.wait(2))
        self.review("delete")
        self.transport.release.set()
        self.service._models.submit(lambda: None).result(timeout=3)
        self.assertFalse(self.state()["memories"])
        self.assertFalse(self.state()["cards"])

    def test_memory_edit_and_withdraw_are_explicit(self):
        self.start(mode="onboarding")
        self.review("confirm_content")
        self.review("replace", text="베이지를 좋아해요")
        self.assertTrue(any(m["confirmed"] and m["content"] == "베이지를 좋아해요" for m in self.state()["memories"]))
        self.assertFalse(any(m["confirmed"] and m["content"] == "네이비를 좋아해요" for m in self.state()["memories"]))
        memory = next(m for m in self.state()["memories"] if m["confirmed"])
        self.review("withdraw", memory)
        self.assertFalse(any(m["confirmed"] for m in self.state()["memories"]))

    def test_catalog_change_during_proposal_rejects_old_maps_and_images(self):
        self.start(mode="onboarding")
        self.review("confirm_content")
        self.transport.pause = "propose"
        self.send({"op": "explore"})
        self.assertTrue(self.transport.entered.wait(2))
        changed = deepcopy(self.records)
        changed[0]["images"][0]["source_revision"] = "synthetic-v2"
        self.data.write_text(json.dumps(changed), encoding="utf-8")
        self.service.import_catalog(self.data)
        self.transport.release.set()
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "stale", self.state())
        self.assertFalse(self.state()["cards"])

    def test_expiry_during_proposal_blocks_application(self):
        self.start(mode="onboarding")
        self.review("confirm_content")
        self.transport.pause = "propose"
        self.send({"op": "explore"})
        self.assertTrue(self.transport.entered.wait(2))
        self.now += timedelta(days=100)
        self.transport.release.set()
        self.service.wait_idle()
        self.assertIsNone(self.state()["request"])
        self.assertEqual(self.service._run(lambda: self.service._store.connection.execute("SELECT COUNT(*) FROM v1_candidate_sets").fetchone()[0]), 0)

    def test_pending_survives_restart_and_new_intake_waits_for_same_evidence_retry(self):
        self.transport.fail_extract = True
        self.start(mode="onboarding")
        self.service.close()
        self.service = self.open_service()
        self.assertEqual(self.state()["operation"], "interpretation_pending")
        before = self.snapshot()
        result, _ = self.send({"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
            "reaction": "text_only", "selections": [], "text": "새 입력", "question_id": None}, ok=False)
        self.assertEqual(result["outcome"], "rejected")
        self.assertEqual(len(self.snapshot()["evidence"]), len(before["evidence"]))
        self.transport.fail_extract = False
        feedback = before["feedback"][0]
        self.send({"op": "retry_extraction", "feedback_ref": {"type": "feedback", "id": feedback["id"], "version": feedback["version"]}})
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "idle")
        self.assertEqual(len(self.snapshot()["memories"]), 1)

    def test_request_erasure_needs_no_fabricated_memory_and_nonce_replay_survives_restart(self):
        self.start(None, mode="onboarding")
        self.send({"op": "prepare_review", "purpose": "delete_request", "subject_refs": [], "proposed_text": None})
        display = self.state()["reviews"][0]
        self.assertIsNone(display["snapshot"]["meaning"])
        _, command = self.send({"op": "respond_review", "display_ref": display["ref"], "decision": "accept"})
        self.assertIsNone(self.state()["request"])
        self.service.close()
        self.service = self.open_service()
        self.send({}, command=command)
        self.assertIsNone(self.state()["request"])

    def test_changed_product_maps_block_until_rebuilt_instead_of_reporting_no_results(self):
        self.start()
        self.review("confirm_content")
        self.records[0]["description"] = "합성 원자료 갱신 후 Map 재생성 필요"
        self.data.write_text(json.dumps(self.records), encoding="utf-8")
        self.service.import_catalog(self.data)
        self.send({"op": "explore"})
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "blocked", self.state())
        self.assertEqual(self.state()["error"]["code"], "context_blocked")
        self.assertEqual(self.state()["cards"], [])
        self.service.build_catalog_maps()
        self.send({"op": "explore"})
        self.service.wait_idle()
        self.assertEqual(self.state()["operation"], "idle", self.state())
        self.assertTrue(self.state()["cards"])

    def test_no_results_and_expiry_are_distinct_from_intake_failure(self):
        self.service.close()
        self.service = ConsumerService(self.root / "empty-memory.sqlite3", self.root / "empty-catalog.sqlite3", self.gateway,
                                       user_id="synthetic-user", clock=lambda: self.now)
        self.start()
        self.review("confirm_content")
        self.send({"op": "explore"})
        self.service.wait_idle()
        s = self.state()
        self.assertEqual(s["operation"], "no_results", s)
        _, command = self.send({"op": "submit_feedback", "round_id": None, "candidate_set_id": None,
            "reaction": "selected", "selections": [], "text": None, "question_id": None}, ok=False)
        self.assertEqual(len(self.snapshot()["feedback"]), 1)
        self.now += timedelta(days=100)
        self.assertIsNone(self.state()["request"])

    def test_configuration_cli_inspection_and_import_do_not_read_keys(self):
        class NoSecrets(dict):
            def get(self, key, default=None):
                if key == "OPENAI_API_KEY":
                    raise AssertionError("secret read during offline configuration")
                return super().get(key, default)
        settings = ConsumerSettings(self.root / "other-memory.sqlite3", self.root / "other-catalog.sqlite3")
        self.assertIsInstance(settings.gateway(settings=NoSecrets()), FakeModelGateway)
        with patch("urllib.request.urlopen", side_effect=AssertionError("offline only")), patch.dict("os.environ", {"STYLEMATE_PROVIDER": "openai"}):
            args = ["--db", str(self.root / "cli-memory.sqlite3"), "--catalog-db", str(self.root / "cli-catalog.sqlite3")]
            with patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(cli_main(["catalog-import", *args, "--file", str(self.data)]), 0)
                self.assertEqual(cli_main(["catalog-map", *args]), 0)
                self.assertEqual(inspector_main(["--consumer-state", *args]), 0)
        configured = ConsumerSettings(settings.db, settings.catalog_db, provider="openai", model="dummy")
        self.assertIsInstance(configured.gateway(settings={"OPENAI_API_KEY": "dummy"}, transport=self.transport), OpenAIResponsesGateway)


if __name__ == "__main__":
    unittest.main()
