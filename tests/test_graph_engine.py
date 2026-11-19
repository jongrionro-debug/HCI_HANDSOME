"""ADR 0013 graph engine end to end with real SQLite, a synthetic catalog and a scripted model.

Skipped when the optional ``graph`` dependency (langgraph) is not installed.
"""

import base64
import json
from pathlib import Path
import tempfile
import unittest

from stylemate_memory import contracts as c
from stylemate_memory.graph import intent as it, scoring
from stylemate_memory.graph.engine import graph_available
from stylemate_memory.model_io import FakeModelGateway

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aPioAAAAASUVORK5CYII=")
FITS = ["Wide"] * 4 + ["Straight"] * 4 + ["Skinny"] * 3 + ["Slim"] * 2


def product(index, fit):
    pid = f"g{index:02}"
    return {"format_version": c.CATALOG_FORMAT_VERSION, "product_id": pid,
            "source": {"source_id": "synthetic-graph", "url": f"https://example.invalid/{pid}", "collected_at": "2026-11-01T09:00:00+09:00"},
            "title": f"합성 바지 {pid}", "description": "판매 상품이 아닌 그래프 검증 fixture", "garment_type": "Pants",
            "raw_metadata": {"supplier_type": "Slacks", "supplier_color": "Black" if index % 2 else "Navy", "supplier_fit": fit},
            "labels": [], "images": [{"image_id": f"image-{pid}", "kind": "local", "location": f"{pid}.png",
                                      "source_revision": "synthetic-v1", "sha256": None, "regions": []}]}


class ScriptedGateway(FakeModelGateway):
    """parse_turn v2 answers built from the user's own words; one Fit hypothesis."""

    model = "scripted-graph"

    def __init__(self):
        super().__init__()
        self.calls = []

    def complete(self, instructions, payload, schema):
        properties = schema.get("properties", {})
        self.calls.append("parse" if "situations" in properties else "hypotheses" if "hypotheses" in properties else "other")
        if "hypotheses" in properties:
            key = payload["fea_needs"][0]["key"]
            return {"hypotheses": [{"id": "h1", "target_id": "pants", "fea_keys": [key], "axis": "Fit",
                                    "values": ["Wide", "Straight"], "reason": "편한 착용감은 여유 있는 핏일 수 있다."}]}
        if "situations" not in properties:
            return super().complete(instructions, payload, schema)
        text = next((s for s in payload["sources"] if s["kind"] == "user_text"), None)
        if text is None or "편한" not in text["content"]:
            return {"situations": [], "wishes": [], "questions": []}
        return {"situations": [{"id": "s1", "key": "occasion", "value": "출근", "raw": "출근", "quote": "출근",
                                "source_ids": [text["source_id"]]}],
                "wishes": [{"key": "w1", "content": "출근 때 편한 바지를 원한다.", "target_id": "pants",
                            "source_ids": [text["source_id"]], "quote": "편한 바지", "origin": "explicit",
                            "polarity": "prefer", "strength": "soft", "applies": {"mode": "request", "situation_ids": []},
                            "pi": [], "fea": [{"category": "Functional", "subcategory": "Donning", "tag": "Ease"}], "price": None}],
                "questions": []}


@unittest.skipUnless(graph_available(), "optional graph dependency (langgraph) is not installed")
class GraphEngineTests(unittest.TestCase):
    def setUp(self):
        from stylemate_memory.app import ConsumerService
        self.temp = tempfile.TemporaryDirectory(prefix="lumi-graph-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        images = root / "images"
        images.mkdir()
        records = [product(i, fit) for i, fit in enumerate(FITS)]
        for record in records:
            (images / record["images"][0]["location"]).write_bytes(PNG)
        (root / "catalog.json").write_text(json.dumps(records), encoding="utf-8")
        self.gateway = ScriptedGateway()
        self.root = root
        self.service = ConsumerService(root / "memory.sqlite3", root / "catalog.sqlite3", self.gateway,
                                       user_id="synthetic-user", image_root=images, engine="graph")
        self.addCleanup(self.service.close)
        self.service.import_catalog(root / "catalog.json")
        self.service.build_catalog_maps()
        self.serial = 0

    def send(self, action, ok=True):
        s = self.service.state()
        self.serial += 1
        start = action["op"] == "start_request"
        command = {"contract_version": c.CONTRACT_VERSION, "command_id": f"g-{self.serial}",
                   "request_id": None if start else s["request"]["id"], "expected": None if start else s["expected"],
                   "action": action}
        result = self.service.command(command)
        if ok:
            self.assertNotEqual(result["outcome"], "rejected", result)
        self.service.wait_idle()
        return result, command

    def grid(self, **kw):
        s = self.service.state()
        snapshot = self.service.inspect_request(s["request"]["id"])["snapshot"]
        active = next(r for r in snapshot["rounds"] if r["status"] == "active")
        return {"op": "grid_feedback", "round_id": active["id"], "candidate_set_id": s["graph"]["set_id"],
                "selections": [], "dislikes": [], "similar": None, "all_bad": False, "text": None, "question_id": None} | kw

    def test_turn_loop_grid_feedback_adjust_final_and_checkpoint(self):
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": "출근할 때 입을 편한 바지"})
        s = self.service.state()
        graph = s["graph"]
        self.assertEqual(s["operation"], "idle", s["error"])
        self.assertEqual(graph["outcome"], "grid")
        self.assertEqual(len(s["cards"]), 8)
        self.assertEqual(graph["hypotheses"][0]["values"], ["Wide", "Straight"])
        self.assertEqual(graph["situations"], [{"key": "occasion", "value": "출근", "raw": "출근"}])
        self.assertIsNone(s["comparison"])
        memories = len(s["memories"])
        self.assertEqual(memories, 2)  # situation + FEA wish, both pending confirmation

        cards = {c["candidate_id"]: c for c in self.service._graph.intent(s["request"]["id"])["last_grid"]["cards"]}
        wide = [cid for cid, c in cards.items() if c["facts"].get("Fit") == ["Wide"]]
        other = next(cid for cid, c in cards.items() if c["facts"].get("Fit") not in (["Wide"], None))
        self.send(self.grid(selections=[{"target_id": "pants", "candidate_id": w, "part_ref": None} for w in wide], dislikes=[other]))
        s = self.service.state()
        self.assertEqual(s["operation"], "idle", s["error"])
        self.assertEqual(s["graph"]["turn"], 2)
        self.assertEqual(len(s["memories"]), memories)  # an image pick or "별로" never becomes memory by itself
        intent = self.service._graph.intent(s["request"]["id"])
        wide_key = scoring.score_key("pants", it.scope_of(intent), "Fit", "Wide")
        self.assertGreater(intent["scores"][wide_key]["a"], 1.0)
        self.assertEqual(s["graph"]["chips"], [])  # a chip needs repeated evidence
        self.assertEqual(len(intent["dislikes"]), 1)

        # Replaying the same command is idempotent: no extra turn.
        _, last = self.send(self.grid(all_bad=True))
        turn = self.service.state()["graph"]["turn"]
        self.service.command(last)
        self.service.wait_idle()
        self.assertEqual(self.service.state()["graph"]["turn"], turn)

        self.send({"op": "adjust_intent", "action": "pin", "key": wide_key, "feature": None})
        s = self.service.state()
        self.assertTrue(next(ch for ch in s["graph"]["chips"] if ch["key"] == wide_key)["pinned"])
        self.assertTrue(all(c["facts"].get("Fit") == ["Wide"]
                            for c in self.service._graph.intent(s["request"]["id"])["last_grid"]["cards"]))

        self.send({"op": "adjust_intent", "action": "bogus", "key": None, "feature": None}, ok=False)
        snapshot = self.service.inspect_request(s["request"]["id"])["snapshot"]
        active = next(r for r in snapshot["rounds"] if r["status"] == "active")
        self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"], "candidate_id": s["cards"][0]["candidate_id"]})
        self.send({"op": "end_request"})
        self.assertEqual(self.service.state()["request"]["status"], "closed")

        # Request deletion erases the graph checkpoints too.
        request_id = s["request"]["id"]
        self.assertIsNotNone(self.service._graph.intent(request_id))
        self.service._graph.forget(request_id)
        self.assertIsNone(self.service._graph.intent(request_id))

    def test_legacy_ops_rejected_and_no_text_start(self):
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": None})
        s = self.service.state()
        self.assertEqual(s["graph"]["outcome"], "grid")
        self.assertEqual(self.gateway.calls, [])  # no text, no FEA: no model call
        result, _ = self.send({"op": "respond_comparison", "comparison_ref": {"kind": "comparison", "id": "x"},
                               "decision": "accept"}, ok=False)
        self.assertEqual(result["outcome"], "rejected")


if __name__ == "__main__":
    unittest.main()
