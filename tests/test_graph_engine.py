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
        shortlisted = {i["product_id"] for i in s["graph"]["shortlist"]}  # F8: the final comes from the shortlist
        final = next(c for c in s["cards"] if c["product_id"] in shortlisted)
        self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"], "candidate_id": final["candidate_id"]})
        self.send({"op": "end_request"})
        self.assertEqual(self.service.state()["request"]["status"], "closed")

        # Request deletion erases the graph checkpoints too.
        request_id = s["request"]["id"]
        self.assertIsNotNone(self.service._graph.intent(request_id))
        self.service._graph.forget(request_id)
        self.assertIsNone(self.service._graph.intent(request_id))

    def test_shortlist_collects_every_pick_and_final_comes_from_its_comparison(self):
        """F8/F9: picks of every turn stay in the shortlist; the final product is decided on the shortlist grid."""
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": None})
        picked = []
        for _ in range(3):
            cards = self.service._graph.intent(self.service.state()["request"]["id"])["last_grid"]["cards"]
            # An earlier pick may come back in a non-kept slot two turns later; pick a product not picked yet.
            fresh = next(c for c in cards if c["slot"] != "kept" and c["product_id"] not in picked)
            picked.append(fresh["product_id"])
            self.send(self.grid(selections=[{"target_id": "pants", "candidate_id": fresh["candidate_id"], "part_ref": None}]))
        s = self.service.state()
        shortlist = s["graph"]["shortlist"]
        self.assertEqual([i["product_id"] for i in shortlist], picked)
        self.assertEqual([i["turn"] for i in shortlist], [1, 2, 3])
        self.assertTrue(all(i["title"] and i["image_url"] for i in shortlist))
        self.assertEqual(s["graph"]["progress"]["shortlist_count"], 3)
        self.assertEqual(len(s["memories"]), 0)  # collecting picks stores no memory

        # A card that was never picked cannot become the final product.
        intent = self.service._graph.intent(s["request"]["id"])
        stranger = next(c for c in intent["last_grid"]["cards"] if c["product_id"] not in picked)
        snapshot = self.service.inspect_request(s["request"]["id"])["snapshot"]
        active = next(r for r in snapshot["rounds"] if r["status"] == "active")
        self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"],
                   "candidate_id": stranger["candidate_id"]}, ok=False)

        self.send({"op": "adjust_intent", "action": "shortlist_remove", "key": picked[0], "feature": None})
        self.assertEqual([i["product_id"] for i in self.service.state()["graph"]["shortlist"]], picked[1:])
        before = dict(self.service._graph.intent(s["request"]["id"])["scores"])
        self.send({"op": "adjust_intent", "action": "shortlist_compare", "key": None, "feature": None})
        s = self.service.state()
        self.assertTrue(s["graph"]["compare"])
        self.assertEqual(sorted(c["product_id"] for c in s["cards"]), sorted(picked[1:]))
        self.assertEqual(self.service._graph.intent(s["request"]["id"])["scores"], before)  # comparing is not a probe
        snapshot = self.service.inspect_request(s["request"]["id"])["snapshot"]
        active = next(r for r in snapshot["rounds"] if r["status"] == "active")
        self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"], "candidate_id": s["cards"][0]["candidate_id"]})
        self.assertEqual(self.service.state()["request"]["final_selection"]["product_id"], s["cards"][0]["product_id"])
        self.send({"op": "explore"})  # "계속 보기" returns to a normal probe grid
        self.assertFalse(self.service.state()["graph"]["compare"])

    def test_picks_stay_first_and_liked_axis_is_credited_per_image(self):
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": None})
        s = self.service.state()
        request_id = s["request"]["id"]
        cards = self.service._graph.intent(request_id)["last_grid"]["cards"]
        picked = cards[2]
        pick = {"target_id": "pants", "candidate_id": picked["candidate_id"], "part_ref": None}
        # A liked axis must exist on that selected card.
        self.send(self.grid(selections=[pick], liked={picked["candidate_id"]: ["Brand"]}), ok=False)
        self.send(self.grid(selections=[], liked={picked["candidate_id"]: ["Fit"]}), ok=False)
        self.send(self.grid(selections=[pick], liked={picked["candidate_id"]: ["Fit"]}))
        intent = self.service._graph.intent(request_id)
        key = scoring.score_key("pants", it.scope_of(intent), "Fit", picked["facts"]["Fit"][0])
        self.assertGreaterEqual(intent["scores"][key]["a"], 1.0 + scoring.REASON_GAIN)
        self.assertIsNone(intent["reason_prompt"])
        grid = intent["last_grid"]["cards"]
        self.assertEqual(len(grid), 8)
        self.assertEqual((grid[0]["slot"], grid[0]["product_id"]), ("kept", picked["product_id"]))
        self.assertEqual(sum(c["product_id"] == picked["product_id"] for c in grid), 1)
        feedback = len(self.service.inspect_request(request_id)["snapshot"]["feedback"])

        # Keeping only the earlier pick records no new evidence; "다 별로" may keep it too.
        kept = {"target_id": "pants", "candidate_id": grid[0]["candidate_id"], "part_ref": None}
        self.send(self.grid(selections=[kept], all_bad=True))
        self.assertEqual(len(self.service.inspect_request(request_id)["snapshot"]["feedback"]), feedback + 1)
        grid = self.service._graph.intent(request_id)["last_grid"]["cards"]
        self.assertEqual(grid[0]["product_id"], picked["product_id"])
        fresh = next(c for c in grid if c["slot"] != "kept")
        self.send(self.grid(selections=[{"target_id": "pants", "candidate_id": fresh["candidate_id"], "part_ref": None}],
                            all_bad=True), ok=False)
        # Deselecting the kept card drops it from the next grid.
        self.send(self.grid(selections=[{"target_id": "pants", "candidate_id": fresh["candidate_id"], "part_ref": None}]))
        grid = self.service._graph.intent(request_id)["last_grid"]["cards"]
        self.assertEqual([c["product_id"] for c in grid if c["slot"] == "kept"], [fresh["product_id"]])

    def test_legacy_ops_rejected_and_no_text_start(self):
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "pants", "garment_type": "Pants"}], "text": None})
        s = self.service.state()
        self.assertEqual(s["graph"]["outcome"], "grid")
        self.assertEqual(self.gateway.calls, [])  # no text, no FEA: no model call
        result, _ = self.send({"op": "respond_comparison", "comparison_ref": {"kind": "comparison", "id": "x"},
                               "decision": "accept"}, ok=False)
        self.assertEqual(result["outcome"], "rejected")


# ---- ADR 0015: tops, gender, consented-memory warm start, end summary, free situations -------------
TOPS = [("men", "Navy", "Regular", "T-shirt"), ("men", "Navy", "Oversized", "Shirt"), ("men", "Black", "Regular", "Shirt"),
        ("men", "Black", "Oversized", "T-shirt"), ("men", "White", "Regular", "T-shirt"), ("men", "White", "Oversized", "Shirt"),
        ("men", "Beige", "Regular", "Shirt"), ("men", "Beige", "Oversized", "T-shirt"), ("men", "Navy", "Slim", "Shirt"),
        ("men", "Grey", "Regular", "T-shirt"), ("men", "Grey", "Oversized", "Shirt"), ("men", "Navy", "Relaxed", "T-shirt"),
        ("women", "Navy", "Regular", "Blouse"), ("women", "Pink", "Oversized", "T-shirt"), ("women", "White", "Slim", "Blouse"),
        ("women", "Black", "Regular", "Shirt"), ("women", "Beige", "Relaxed", "T-shirt"), ("women", "Pink", "Regular", "Blouse"),
        ("women", "Grey", "Oversized", "Shirt"), ("women", "Navy", "Slim", "T-shirt")]


def top(index, gender, color, fit, kind):
    pid = f"t{index:02}"
    return {"format_version": c.CATALOG_FORMAT_VERSION, "product_id": pid,
            "source": {"source_id": "synthetic-top", "url": f"https://example.invalid/{pid}", "collected_at": "2026-11-19T09:00:00+09:00"},
            "title": f"합성 상의 {pid}", "description": None, "garment_type": "Top",
            "raw_metadata": {"gender": gender, "type": [kind], "color": [color], "fit": [fit]}, "labels": [],
            "images": [{"image_id": f"image-{pid}", "kind": "local", "location": f"{pid}.png",
                        "source_revision": "synthetic-v1", "sha256": None, "regions": []}]}


class MemoryGateway(FakeModelGateway):
    """Scripted parse (two fixed sentences), situation link and profile rewrite."""

    model = "scripted-memory"

    def __init__(self):
        super().__init__()
        self.calls = []

    @staticmethod
    def wish(key, content, text_id, quote, applies, pi):
        return {"key": key, "content": content, "target_id": "top", "source_ids": [text_id], "quote": quote,
                "origin": "explicit", "polarity": "prefer", "strength": "soft", "applies": applies,
                "pi": pi, "fea": [], "price": None}

    def complete(self, instructions, payload, schema):
        properties = schema.get("properties", {})
        if "match" in properties:
            self.calls.append(("link", payload["current_situation"], tuple(payload["past_situations"])))
            return {"match": next((p for p in payload["past_situations"] if "회식" in p and "회식" in payload["current_situation"]), None)}
        if "lines" in properties:
            self.calls.append(("profile", len(payload["memories"])))
            return {"lines": [{"memory_id": m["memory_id"], "text": m["text"].replace("좋아해요", "좋아요")} for m in payload["memories"]]}
        if "situations" not in properties:
            return super().complete(instructions, payload, schema)
        self.calls.append(("parse",))
        text = next((s for s in payload["sources"] if s["kind"] == "user_text"), None)
        wishes = []
        if text and "네이비" in text["content"]:
            wishes.append(self.wish("w1", "평소 네이비 레귤러 핏을 좋아해요.", text["source_id"], "네이비",
                                    {"mode": "baseline", "situation_ids": []},
                                    [{"feature": "Color", "values": ["Navy"], "match": "any"},
                                     {"feature": "Fit", "values": ["Regular"], "match": "any"}]))
        if text and "오버사이즈" in text["content"]:
            wishes.append(self.wish("w2", "회식 때는 오버사이즈 핏을 좋아해요.", text["source_id"], "오버사이즈",
                                    {"mode": "request", "situation_ids": []},
                                    [{"feature": "Fit", "values": ["Oversized"], "match": "any"}]))
        return {"situations": [], "wishes": wishes, "questions": []}


@unittest.skipUnless(graph_available(), "optional graph dependency (langgraph) is not installed")
class TopMemoryTests(unittest.TestCase):
    """ADR 0015 end to end: request 1 saves consented memory, request 2 starts from it."""

    def setUp(self):
        from stylemate_memory.app import ConsumerService
        from stylemate_memory.registry import load_registry
        self.temp = tempfile.TemporaryDirectory(prefix="lumi-top-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        images = root / "images"
        images.mkdir()
        records = [top(i, *row) for i, row in enumerate(TOPS)]
        for record in records:
            (images / record["images"][0]["location"]).write_bytes(PNG)
        (root / "catalog.json").write_text(json.dumps(records), encoding="utf-8")
        self.gateway = MemoryGateway()
        self.service = ConsumerService(root / "memory.sqlite3", root / "catalog.sqlite3", self.gateway,
                                       user_id="synthetic-user", image_root=images, engine="graph",
                                       registry=load_registry(c.LUMI_PI_V2_TOP_REGISTRY_VERSION))
        self.addCleanup(self.service.close)
        self.service.import_catalog(root / "catalog.json")
        self.service.build_catalog_maps()
        self.serial = 0
        self.gender = {r["product_id"]: r["raw_metadata"]["gender"] for r in records}

    send = GraphEngineTests.send
    grid = GraphEngineTests.grid

    def start(self, text=None, situation=None, gender="men"):
        self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                   "targets": [{"target_id": "top", "garment_type": "Top"}], "text": text,
                   "gender": gender, "situation": situation})
        s = self.service.state()
        self.assertEqual(s["operation"], "idle", s["error"])
        return s

    def intent(self):
        return self.service._graph.intent(self.service.state()["request"]["id"])

    def summary(self, step, choices=()):
        self.send({"op": "graph_summary", "step": step, "choices": list(choices)})
        return self.service.state()["graph"]["summary"]

    def first_request(self, text, situation, choices):
        self.start(text, situation)
        summary = self.summary("prepare")
        self.assertEqual(summary["status"], "draft")
        by_text = {p["text"]: p["id"] for p in summary["proposals"]}
        saved = self.summary("save", [{"id": by_text[t], "choice": ch} for t, ch in choices])
        self.assertEqual(self.service.state()["request"]["status"], "closed")
        return saved

    def long_term(self):
        rid = self.service.state()["request"]["id"]
        return self.service._run(self.service._graph_bridge.long_term_now, rid)

    def test_gender_filter_warm_start_novelty_and_profile_consent(self):
        s = self.start("평소 네이비 상의 좋아해요", {"kind": "chip", "value": "출근"})
        self.assertEqual(len(s["cards"]), 8)
        self.assertTrue(all(self.gender[c["product_id"]] == "men" for c in s["cards"]))
        self.assertEqual(s["graph"]["situations"], [{"key": "occasion", "value": "출근", "raw": "출근"}])
        self.assertEqual(s["graph"]["memory"]["chips"], [])  # nothing consented yet: cold start, no novelty slot
        self.assertNotIn("novel", s["graph"]["slots"].values())

        summary = self.summary("prepare")
        self.assertEqual([(p["text"], p["suggested"]) for p in summary["proposals"]], [("평소 네이비 레귤러 핏을 좋아해요.", "baseline")])
        self.assertEqual(self.long_term(), [])  # proposing is not saving
        saved = self.summary("save", [{"id": "p1", "choice": "baseline"}])
        self.assertEqual(saved["saved"], ["평소 네이비 레귤러 핏을 좋아해요."])
        self.service.wait_idle()
        memories = self.long_term()
        self.assertEqual([(m["content"], m["conditions"]) for m in memories], [("평소 네이비 레귤러 핏을 좋아해요.", {})])
        profile = self.service.state()["graph"]["summary"]["profile"]
        self.assertEqual(profile["status"], "ready")
        self.assertEqual(profile["changes"][0]["text"], "평소 네이비 레귤러 핏을 좋아요.")
        self.summary("profile", [{"id": profile["changes"][0]["memory_id"], "choice": "accept"}])
        memories = self.long_term()
        self.assertEqual([m["content"] for m in memories], ["평소 네이비 레귤러 핏을 좋아요."])
        self.assertEqual(sorted((b["feature"], tuple(b["values"])) for b in memories[0]["bindings"]),
                         [("Color", ("Navy",)), ("Fit", ("Regular",))])
        rid = self.service.state()["request"]["id"]
        old = self.service.inspect_request(rid)["snapshot"]
        # The original memory is kept as superseded (evidence preserved), not erased.
        rows = self.service._store.connection.execute(
            "SELECT json_extract(payload_json,'$.scope'),json_extract(payload_json,'$.content') FROM v1_memories "
            "WHERE status='superseded'").fetchall()
        self.assertIn(("long_term", "평소 네이비 레귤러 핏을 좋아해요."), [tuple(r) for r in rows])
        self.assertTrue(old["request"]["status"] == "closed")

        # Request 2, another situation: the usual taste starts the grid as soft priors.
        s = self.start(None, {"kind": "chip", "value": "데이트"})
        memory = s["graph"]["memory"]
        self.assertEqual([(c["text"], c["kind"], c["enabled"]) for c in memory["chips"]], [("평소 네이비 레귤러 핏을 좋아요.", "baseline", True)])
        intent = self.intent()
        self.assertEqual(sorted((p["axis"], p["value"]) for p in intent["priors"]), [("Color", "Navy"), ("Fit", "Regular")])
        self.assertEqual(intent["hard"], [])  # memory never becomes a hard filter
        cards = intent["last_grid"]["cards"]
        novel = [c for c in cards if c["slot"] == "novel"]
        self.assertEqual(len(novel), 2)
        self.assertTrue(all("Navy" not in (c["facts"].get("Color") or []) and "Regular" not in (c["facts"].get("Fit") or [])
                            for c in novel))
        self.assertEqual(self.gateway.calls.count(("parse",)), 1)  # no text in request 2: no parse call

        # x on the memory chip removes its priors; the next grid has no novelty slot.
        self.send({"op": "adjust_intent", "action": "memory_off", "key": memory["chips"][0]["memory_id"], "feature": None})
        s = self.service.state()
        self.assertFalse(s["graph"]["memory"]["chips"][0]["enabled"])
        self.assertNotIn("novel", s["graph"]["slots"].values())
        self.send({"op": "adjust_intent", "action": "memory_off", "key": "unknown", "feature": None}, ok=False)

    def test_free_situation_link_situation_priority_and_novelty_prompt(self):
        self.first_request("평소 네이비 좋아하고 회식엔 오버사이즈", {"kind": "free", "text": "팀 회식"},
                           [("평소 네이비 레귤러 핏을 좋아해요.", "baseline"), ("회식 때는 오버사이즈 핏을 좋아해요.", "situation")])
        memories = self.long_term()
        self.assertEqual(sorted(m["conditions"].get("occasion", "") for m in memories), ["", "팀 회식"])

        # A new free situation: the model links it to the saved raw situation; situation wins on Fit.
        s = self.start(None, {"kind": "free", "text": "회사 회식 자리"})
        self.assertIn(("link", "회사 회식 자리", ("팀 회식",)), self.gateway.calls)
        memory = s["graph"]["memory"]
        self.assertEqual(memory["links"], [{"raw": "회사 회식 자리", "past": "팀 회식", "enabled": True}])
        self.assertEqual([c["kind"] for c in memory["chips"]], ["situation", "baseline"])
        priors = sorted((p["kind"], p["axis"], p["value"]) for p in self.intent()["priors"])
        self.assertEqual(priors, [("baseline", "Color", "Navy"), ("situation", "Fit", "Oversized")])

        # Turning the link off drops the situation memory; the usual taste applies in full again.
        self.send({"op": "adjust_intent", "action": "link_off", "key": None, "feature": None})
        priors = sorted((p["kind"], p["axis"], p["value"]) for p in self.intent()["priors"])
        self.assertEqual(priors, [("baseline", "Color", "Navy"), ("baseline", "Fit", "Regular")])

        # "평소랑 다르게" asks once; yes dims memory and keeps one novelty slot.
        self.send(self.grid(text="이번엔 평소랑 다르게 보고 싶어요"))
        self.assertTrue(self.service.state()["graph"]["memory"]["novelty_prompt"])
        self.send({"op": "adjust_intent", "action": "novelty_yes", "key": None, "feature": None})
        s = self.service.state()
        self.assertEqual(s["graph"]["memory"]["mode"], "dim")
        self.assertFalse(s["graph"]["memory"]["novelty_prompt"])
        self.assertEqual(list(s["graph"]["slots"].values()).count("novel"), 1)

    def test_converged_images_and_final_product_become_situation_memory(self):
        self.first_request("평소 네이비 상의 좋아해요", None, [("평소 네이비 레귤러 핏을 좋아해요.", "baseline")])
        self.start(None, {"kind": "chip", "value": "데이트"})
        for _ in range(3):
            cards = self.intent()["last_grid"]["cards"]
            navy = [c["candidate_id"] for c in cards if "Navy" in (c["facts"].get("Color") or [])]
            self.send(self.grid(selections=[{"target_id": "top", "candidate_id": n, "part_ref": None} for n in navy]))
        s = self.service.state()
        self.assertIn(("Color", "Navy"), [(ch["feature"], ch["value"]) for ch in s["graph"]["chips"]])
        snapshot = self.service.inspect_request(s["request"]["id"])["snapshot"]
        active = next(r for r in snapshot["rounds"] if r["status"] == "active")
        final = next(c for c in self.intent()["last_grid"]["cards"] if "Navy" in (c["facts"].get("Color") or []))
        self.send({"op": "select_final", "candidate_set_ref": active["candidate_set_ref"], "candidate_id": final["candidate_id"]})
        summary = self.summary("prepare")
        texts = [p["text"] for p in summary["proposals"]]
        self.assertIn("네이비 쪽이 좋아요.", texts)
        self.assertEqual(summary["situation_label"], "데이트")
        self.assertTrue(all(p["suggested"] == "situation" for p in summary["proposals"]))
        choices = [{"id": p["id"], "choice": "situation" if p["text"] == "네이비 쪽이 좋아요." else "skip"} for p in summary["proposals"]]
        saved = self.summary("save", choices)
        self.assertEqual(saved["saved"], ["네이비 쪽이 좋아요."])
        self.service.wait_idle()
        situational = [m for m in self.long_term() if m["conditions"]]
        self.assertEqual([(m["content"], m["conditions"]) for m in situational], [("네이비 쪽이 좋아요.", {"occasion": "데이트"})])

    def test_skip_saves_nothing_and_women_filter(self):
        s = self.start("평소 네이비 상의 좋아해요", None, gender="women")
        self.assertTrue(all(self.gender[c["product_id"]] == "women" for c in s["cards"]))
        self.assertEqual(len(s["cards"]), 8)
        self.summary("prepare")
        summary = self.summary("save", [{"id": "p1", "choice": "skip"}])
        self.assertEqual(summary["saved"], [])
        self.assertEqual(self.service.state()["request"]["status"], "closed")
        self.assertEqual(self.long_term(), [])
        # "이 상황만" needs a situation; none was given.
        self.start("평소 네이비 상의 좋아해요", None)
        self.summary("prepare")
        result, _ = self.send({"op": "graph_summary", "step": "save", "choices": [{"id": "p1", "choice": "situation"}]}, ok=False)
        self.assertEqual(result["outcome"], "rejected")


def v3_product(index, garment, kind, fit, weight):
    pid = f"v{index:02}"
    return {"format_version": c.CATALOG_FORMAT_VERSION, "product_id": pid,
            "source": {"source_id": "synthetic-v3", "url": f"https://example.invalid/{pid}", "collected_at": "2026-11-25T09:00:00+09:00"},
            "title": f"합성 v3 {pid}", "description": None, "garment_type": garment,
            "raw_metadata": {"gender": "men", "type": [kind], "color": ["Navy" if index % 2 else "Black"], "fit": [fit],
                             "weight": [weight], "pi_v3": {"price_krw": 50000 + index, "axes": {"Fit": {"score": 2.0}}}},
            "labels": [], "images": [{"image_id": f"image-{pid}", "kind": "local", "location": f"{pid}.png",
                                      "source_revision": "synthetic-v1", "sha256": None, "regions": []}]}


@unittest.skipUnless(graph_available(), "optional graph dependency (langgraph) is not installed")
class PIV3RuntimeTests(unittest.TestCase):
    """lumi-pi-v3 (ADR 0016): one runtime dictionary serves top and bottom requests; Weight is a mapped axis."""

    def setUp(self):
        from stylemate_memory.app import ConsumerService
        from stylemate_memory.registry import load_registry
        self.temp = tempfile.TemporaryDirectory(prefix="lumi-v3-")
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        images = root / "images"
        images.mkdir()
        fits = ["Slim", "Regular", "Relaxed", "Oversized"]
        records = ([v3_product(i, "Top", "T-shirt" if i % 2 else "Shirt", fits[i % 4], "Light") for i in range(10)]
                   + [v3_product(i, "Bottom", "Trousers" if i % 2 else "Jeans", fits[i % 4], "Heavy") for i in range(10, 20)])
        for record in records:
            (images / record["images"][0]["location"]).write_bytes(PNG)
        (root / "catalog.json").write_text(json.dumps(records), encoding="utf-8")
        self.service = ConsumerService(root / "memory.sqlite3", root / "catalog.sqlite3", FakeModelGateway(),
                                       user_id="synthetic-user", image_root=images, engine="graph",
                                       registry=load_registry(c.LUMI_PI_V3_REGISTRY_VERSION))
        self.addCleanup(self.service.close)
        self.service.import_catalog(root / "catalog.json")
        self.service.build_catalog_maps()
        self.serial = 0
        self.garment = {r["product_id"]: r["garment_type"] for r in records}

    send = GraphEngineTests.send

    def test_top_and_bottom_requests_use_their_own_products(self):
        garments = [g["value"] for g in self.service.state()["garment_types"]]
        self.assertEqual(garments, ["Top", "Bottom"])
        for garment in ("Bottom", "Top"):
            self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                       "targets": [{"target_id": "t", "garment_type": garment}], "text": None, "gender": "men",
                       "situation": None})
            s = self.service.state()
            self.assertEqual(s["operation"], "idle", s["error"])
            self.assertEqual(len(s["cards"]), 8)
            self.assertTrue(all(self.garment[card["product_id"]] == garment for card in s["cards"]))
            facts = self.service._graph.intent(s["request"]["id"])["last_grid"]["cards"][0]["facts"]
            self.assertEqual(facts.get("Weight"), ["Heavy" if garment == "Bottom" else "Light"])
            self.send({"op": "end_request"})

    def test_question_loop_asks_once_and_a_text_answer_pins_the_value(self):
        import os
        from unittest import mock
        with mock.patch.dict(os.environ, {"STYLEMATE_QUESTION_LOOP": "on"}):
            self.send({"op": "start_request", "mode": "shopping", "timezone": "Asia/Seoul",
                       "targets": [{"target_id": "t", "garment_type": "Top"}], "text": None, "gender": "men",
                       "situation": None})
            s = self.service.state()
            ask = s["graph"]["ask"]
            self.assertTrue(s["graph"]["question_loop"])
            self.assertEqual(ask["mode"], "text_options")
            self.assertNotIn("value", ask["options"][0])
            set_id = s["graph"]["set_id"]
            self.send({"op": "answer_question", "question_id": "q-unknown", "choice": "skip", "option_ids": [],
                       "switch_to": None}, ok=False)
            option = ask["options"][0]
            self.send({"op": "answer_question", "question_id": ask["question_id"], "choice": "options",
                       "option_ids": [option["id"]], "switch_to": None})
            s = self.service.state()
            intent = self.service._graph.intent(s["request"]["id"])
            self.assertIsNone(s["graph"]["ask"])
            self.assertNotEqual(s["graph"]["set_id"], set_id)  # a pinned value redraws the grid
            pinned = [p["key"].split("|") for p in intent["pinned"]]
            self.assertEqual([(k[2], k[3]) for k in pinned], [(ask["axis"], intent["question_log"][0]["candidate"]["values"][0])])
            axis, value = pinned[0][2], pinned[0][3]
            self.assertTrue(all(value in card["facts"].get(axis, []) for card in intent["last_grid"]["cards"]))
            self.assertEqual([e["event"] for e in intent["question_log"]], ["ask", "answer"])


if __name__ == "__main__":
    unittest.main()
