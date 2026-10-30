"""B3 transactional round/feedback storage, behind MemoryStore's fixed port.

This module never chooses products or runs a model. record_extraction is an
internal service operation: the service resolves per-call model aliases back to
the IDs of this feedback's Evidence before passing an ExtractionResult here.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from . import contracts as c
from .errors import V1_ERROR_CODES, StyleMateError
from .registry import load_registry
from .store import _REQUEST_INACTIVITY, _canonical, _digest, _fail, _iso, _new_id
from .store_v1 import _batch_size, _list, _ref, _shape, _text, _us


def _version(value: Any, *, minimum: int = 1) -> None:
    if type(value) is not int or value < minimum:
        raise _fail("invalid_input", "versions and positions must be integers in range")


def _catalog_versions(value: Any) -> dict[str, Any]:
    _shape(value, c.CatalogVersions.__required_keys__, "catalog versions")
    _version(value["catalog_version"], minimum=0)
    for key, fields, id_key in (("products", c.ProductVersion.__required_keys__, "product_id"),
                                ("images", c.ImageVersion.__required_keys__, "image_id")):
        seen = set()
        for item in _list(value[key], key, 256):
            _shape(item, fields, key)
            _text(item[id_key], id_key)
            if item[id_key] in seen:
                raise _fail("invalid_input", "duplicate catalog version reference")
            seen.add(item[id_key])
            for name in fields - {id_key}:
                _version(item[name])
    return value


class FeedbackStorage:
    def __init__(self, storage: Any) -> None:
        self.v1 = storage
        self.store = storage.store

    @property
    def conn(self):
        return self.v1.conn

    def object(self, request: Any, kind: str, object_id: Any, now: datetime) -> dict[str, Any]:
        """Resolve an internal current pointer; external writes still need Expected."""
        _text(object_id, kind + " id")
        row = self.conn.execute(
            "SELECT version FROM v1_objects WHERE id=? AND object_type=? AND user_id=? AND request_id=?",
            (object_id, kind, request["user_id"], request["id"]),
        ).fetchone()
        if row is None:
            raise _fail("not_found", "request object not found")
        return self.v1._resolve(request["user_id"], request["id"],
                                {"type": kind, "id": object_id, "version": row["version"]}, now)

    def active_round(self, request: Any, now: datetime) -> dict[str, Any] | None:
        row = self.conn.execute(
            """SELECT o.id FROM v1_objects o JOIN v1_rounds r ON r.id=o.id
               WHERE o.user_id=? AND o.request_id=? AND o.retention_us>?
                   AND json_extract(r.payload_json,'$.status')='active'""",
            (request["user_id"], request["id"], _us(now)),
        ).fetchone()
        return self.object(request, "round", row["id"], now) if row else None

    def check_catalog(self, versions: Any, freshness: Any) -> None:
        versions = _catalog_versions(versions)
        if freshness is None:
            raise _fail("stale_context", "catalog freshness is required")
        try:
            current = freshness.current_versions([p["product_id"] for p in versions["products"]],
                                                  [i["image_id"] for i in versions["images"]])
        except Exception:
            raise _fail("stale_context", "catalog versions could not be verified") from None
        _catalog_versions(current)
        # CatalogPort preserves the requested ID order; compare by identity too.
        def normalize(v):
            return {"catalog_version": v["catalog_version"],
                    "products": sorted(v["products"], key=lambda p: p["product_id"]),
                    "images": sorted(v["images"], key=lambda i: i["image_id"])}
        if normalize(current) != normalize(versions):
            raise _fail("stale_context", "published product maps or images have changed")

    def review_dependencies(self, request: Any, snapshot: Any, basis: Any, now: datetime, *, purpose: str) -> None:
        """An image-derived review must not omit its displayed comparison basis."""
        if purpose in ("withdraw", "delete"):
            return  # removing a memory does not attest any product attribute
        if request["status"] == "closed" and purpose == "future_reuse" and basis["catalog"] is None:
            subjects = [self.v1._resolve(request["user_id"], request["id"], ref, now)
                        for ref in snapshot["subject_refs"] if ref["type"] == "memory"]
            if subjects and all(m["confirmed"] and m["status"] == "active" for m in subjects):
                return  # a new, content-only review of already confirmed meaning
        queue = list(snapshot["subject_refs"])
        seen = set()
        while queue:
            source_ref = queue.pop()
            identity = _canonical(source_ref)
            if identity in seen:
                continue
            seen.add(identity)
            if len(seen) > 256:
                raise _fail("invalid_input", "review dependency limit exceeded")
            obj = self.v1._resolve(request["user_id"], request["id"], source_ref, now)
            self.v1._live(source_ref, obj, now)
            queue.extend(obj.get("source_refs", []))
            if source_ref["type"] != "evidence" or obj["selection"] is None:
                continue
            selection = obj["selection"]
            # An extracted question can advance a round without changing its
            # immutable cards. Review the current round with the original set.
            round_obj = self.object(request, "round", selection["round_ref"]["id"], now)
            if (_ref("round", round_obj) not in basis["object_versions"]
                or selection["candidate_set_ref"] not in basis["object_versions"]):
                raise _fail("stale_context", "image review is missing its comparison basis")
            closed_reuse = request["status"] == "closed" and purpose == "future_reuse" and round_obj["status"] == "closed"
            if (round_obj["status"] != "active" and not closed_reuse) or round_obj["candidate_set_ref"] != selection["candidate_set_ref"]:
                raise _fail("stale_context", "reviewed image comparison is no longer active")
            candidate_set = self.v1._resolve(request["user_id"], request["id"], selection["candidate_set_ref"], now)
            versions = _catalog_versions(basis["catalog"])
            original = candidate_set["basis"]["catalog"]
            products = {p["product_id"]: p for p in versions["products"]}
            original_products = {p["product_id"]: p for p in original["products"]}
            images = {i["image_id"]: i["version"] for i in versions["images"]}
            if versions["catalog_version"] != original["catalog_version"]:
                raise _fail("stale_context", "review catalog differs from the displayed comparison")
            for card in candidate_set["cards"]:
                if (products.get(card["product_id"]) != original_products[card["product_id"]]
                    or (card["image_id"] is not None and images.get(card["image_id"]) != card["image_version"])):
                    raise _fail("stale_context", "review must include versions of every displayed card")

    def _plan(self, request: Any, plan: Any, now: datetime, freshness: Any) -> None:
        _shape(plan, c.CandidatePlan.__required_keys__, "candidate plan")
        self.v1._check_basis(request, plan["basis"], now)
        versions = _catalog_versions(plan["basis"]["catalog"])
        products = {p["product_id"]: p["map_version"] for p in versions["products"]}
        images = {i["image_id"]: i["version"] for i in versions["images"]}
        targets = {t["target_id"] for t in json.loads(request["targets_json"])}
        candidates, positions, pairs = set(), set(), set()
        for card in _list(plan["cards"], "cards", 4, nonempty=True):
            _shape(card, c.CandidateCard.__required_keys__, "candidate card")
            for field in ("candidate_id", "target_id", "product_id"):
                _text(card[field], field)
            _version(card["product_map_version"])
            _version(card["position"], minimum=0)
            if card["target_id"] not in targets:
                raise _fail("invalid_input", "candidate target is not in this request")
            pair = (card["target_id"], card["product_id"])
            if card["candidate_id"] in candidates or card["position"] in positions or pair in pairs:
                raise _fail("invalid_input", "candidate IDs, positions and target/product pairs must be unique")
            candidates.add(card["candidate_id"])
            positions.add(card["position"])
            pairs.add(pair)
            if products.get(card["product_id"]) != card["product_map_version"]:
                raise _fail("stale_context", "candidate product is missing from its catalog basis")
            if card["image_id"] is None:
                if card["image_version"] is not None:
                    raise _fail("invalid_input", "missing image requires a null version")
            else:
                _text(card["image_id"], "image_id")
                _version(card["image_version"])
                if images.get(card["image_id"]) != card["image_version"]:
                    raise _fail("stale_context", "candidate image is missing from its catalog basis")
        registry = load_registry(request["registry_version"])
        paths = set()
        for path in _list(plan["compared_features"], "compared_features", 37):
            if not isinstance(path, dict):
                raise _fail("invalid_input", "comparison feature must be a registry path")
            pi = path.get("domain") == "PI"
            _shape(path, c.PIPath.__required_keys__ if pi else c.FEAPath.__required_keys__, "comparison feature")
            registry.validate_observation(path | ({"values": None} if pi else {"present": None}), None)
            if _canonical(path) in paths:
                raise _fail("invalid_input", "duplicate comparison feature")
            paths.add(_canonical(path))
        for draft in _list(plan["questions"], "questions", 3):
            self._question_draft(request, draft, now)
        self.check_catalog(versions, freshness)

    def _question_draft(self, request: Any, draft: Any, now: datetime) -> None:
        _shape(draft, c.QuestionDraft.__required_keys__, "question")
        _text(draft["text"], "question text", 4000)
        if draft["target_id"] is not None:
            _text(draft["target_id"], "question target")
            if draft["target_id"] not in {t["target_id"] for t in json.loads(request["targets_json"])}:
                raise _fail("invalid_input", "question target is not in this request")
        refs = _list(draft["subject_refs"], "question subjects", 64)
        if len({_canonical(ref) for ref in refs}) != len(refs):
            raise _fail("invalid_input", "duplicate question subject")
        for ref in refs:
            obj = self.v1._resolve(request["user_id"], request["id"], ref, now)
            self.v1._live(ref, obj, now)
            selector = obj.get("selector")
            if draft["target_id"] is not None and selector:
                target = next(t for t in json.loads(request["targets_json"]) if t["target_id"] == draft["target_id"])
                if (selector["slot_id"] not in (None, target["target_id"])
                    or selector["garment_type"] not in (None, target["garment_type"])):
                    raise _fail("invalid_input", "question subject belongs to another target")
        options = _list(draft["options"], "question options", 32)
        for option in options:
            _text(option, "question option", 4000)
        if len(set(options)) != len(options):
            raise _fail("invalid_input", "duplicate question option")

    def question(self, request: Any, draft: Any, now: datetime, retention: str) -> dict[str, Any]:
        self._question_draft(request, draft, now)
        deadlines = [retention] + [self.v1._resolve(request["user_id"], request["id"], ref, now)["retention_until"]
                                    for ref in draft["subject_refs"]]
        obj = self.v1._metadata(request["user_id"], request["id"], now, min(deadlines, key=_us)) | draft | {"status": "open"}
        self.v1._put("question", obj, {"subject": obj["subject_refs"]})
        return obj

    def _question_set(self, question: Any, set_ref: Any) -> None:
        # Keep the issuing set relationship after a round replaces its current
        # question_refs. A previous question cannot be answered as initial text.
        self.conn.execute("INSERT INTO v1_object_refs VALUES (?, 'candidate_set', 0, ?, 'candidate_set', ?)",
                          (question["id"], set_ref["id"], set_ref["version"]))

    def publish(self, user_id: str, request_id: str, *, batch_id: str,
                plan: Any, catalog_freshness: Any) -> dict[str, Any]:
        for key, value in (("user_id", user_id), ("request_id", request_id), ("batch_id", batch_id)):
            _text(value, key)
        _batch_size({"plan": plan})
        fingerprint = "publish_candidates:" + _digest({"contract_version": c.CONTRACT_VERSION,
                                                       "request_id": request_id, "plan": plan})
        now = self.store._now()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.store._purge_expired_nonces(user_id, now)
            for table in ("batch_receipts", "deletion_receipts"):
                if self.conn.execute(f"SELECT 1 FROM {table} WHERE user_id=? AND batch_id=?", (user_id, batch_id)).fetchone():
                    raise _fail("idempotency_conflict", "batch_id belongs to another operation")
            prior = self.conn.execute("SELECT * FROM v1_batch_receipts WHERE user_id=? AND batch_id=?", (user_id, batch_id)).fetchone()
            if prior:
                if prior["fingerprint"] != fingerprint:
                    raise _fail("idempotency_conflict", "batch_id was used for another publication")
                self.conn.commit()
                return json.loads(prior["receipt_json"])
            self.store._assert_batch_not_tombstoned(user_id, batch_id, now)
            request = self.v1._request(user_id, request_id)
            self._plan(request, plan, now, catalog_freshness)
            retention = min([request["retention_until"]] + ([plan["basis"]["valid_until"]] if plan["basis"]["valid_until"] else []), key=_us)
            candidate_set = self.v1._metadata(user_id, request_id, now, retention) | {
                "target_ids": sorted({card["target_id"] for card in plan["cards"]}), "cards": plan["cards"],
                "compared_features": plan["compared_features"], "basis": plan["basis"],
            }
            self.v1._put("candidate_set", candidate_set, {"basis": plan["basis"]["object_versions"]})
            self.store._call_failure_hook("candidates_after_set")
            questions = [self.question(request, draft, now, retention) for draft in plan["questions"]]
            for question in questions:
                self._question_set(question, _ref("candidate_set", candidate_set))
            round_obj = self.active_round(request, now)
            fields = {"candidate_set_ref": _ref("candidate_set", candidate_set),
                      "question_refs": [_ref("question", q) for q in questions], "status": "active"}
            if round_obj:
                round_obj = self.v1._update("round", round_obj | fields)
                self.conn.execute("DELETE FROM v1_object_refs WHERE owner_id=?", (round_obj["id"],))
                for role, refs in (("candidate_set", [round_obj["candidate_set_ref"]]), ("question", round_obj["question_refs"])):
                    for index, ref in enumerate(refs):
                        self.conn.execute("INSERT INTO v1_object_refs VALUES (?,?,?,?,?,?)",
                                          (round_obj["id"], role, index, ref["id"], ref["type"], ref["version"]))
            else:
                round_obj = self.v1._metadata(user_id, request_id, now, retention) | fields
                self.v1._put("round", round_obj, {"candidate_set": [round_obj["candidate_set_ref"]], "question": round_obj["question_refs"]})
            self.conn.execute("UPDATE requests SET revision=revision+1,updated_at=? WHERE id=?", (_iso(now), request_id))
            self.conn.execute("INSERT INTO v1_batch_receipts VALUES (?,?,?,?,?,?)",
                              (user_id, batch_id, request_id, fingerprint, _canonical(round_obj), _iso(now)))
            self.store._call_failure_hook("candidates_before_commit")
            self.conn.commit()
            return round_obj
        except StyleMateError:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise _fail("storage_failed", "candidate publication was rolled back") from exc

    def current_set(self, request: Any, round_id: Any, set_id: Any, expected: Any,
                    now: datetime, freshness: Any) -> tuple[dict[str, Any], dict[str, Any]]:
        round_obj = self.object(request, "round", round_id, now)
        candidate_set = self.object(request, "candidate_set", set_id, now)
        for kind, obj in (("round", round_obj), ("candidate_set", candidate_set)):
            if _ref(kind, obj) not in expected["object_versions"]:
                raise _fail("invalid_input", "feedback requires current round and candidate-set versions")
        if round_obj["status"] != "active" or round_obj["candidate_set_ref"] != _ref("candidate_set", candidate_set):
            raise _fail("stale_context", "candidate set has been replaced or closed")
        basis = candidate_set["basis"]
        if basis["valid_until"] is not None and _us(basis["valid_until"]) <= _us(now):
            raise _fail("stale_context", "candidate basis has expired")
        for ref in basis["object_versions"]:
            # Publication itself advances this round. Its input version is a
            # control token, checked above against the newly issued set, not a
            # semantic dependency that should invalidate its own publication.
            if ref["type"] == "round" and ref["id"] == round_obj["id"]:
                continue
            self.v1._live(ref, self.v1._resolve(request["user_id"], request["id"], ref, now), now)
        self.check_catalog(basis["catalog"], freshness)
        return round_obj, candidate_set

    def _part(self, part: Any, card: Any, garment: str, freshness: Any) -> None:
        if part is None:
            return
        _shape(part, c.PartRef.__required_keys__, "part_ref")
        _version(part["image_version"])
        if card["image_id"] is None or (part["image_id"], part["image_version"]) != (card["image_id"], card["image_version"]):
            raise _fail("invalid_input", "partial selection must refer to the displayed image version")
        if (part["region_id"] is None) == (part["box"] is None):
            raise _fail("invalid_input", "part_ref requires exactly one region or box")
        if part["box"] is not None:
            box = _list(part["box"], "box", 4)
            if (len(box) != 4 or any(type(v) not in (int, float) or not 0 <= v <= 1 or not math.isfinite(v) for v in box)
                or box[0] >= box[2] or box[1] >= box[3]):
                raise _fail("invalid_input", "box must have positive area within the original normalized image")
        else:
            _text(part["region_id"], "region_id")
            # CatalogPort.resolve_image supplies named regions. Freshness alone
            # cannot attest a region; never accept an unverifiable region ID.
            resolver = getattr(freshness, "resolve_image", None)
            if resolver is None:
                raise _fail("invalid_input", "named regions require CatalogPort.resolve_image")
            try:
                image = resolver(card["image_id"], version=card["image_version"])
            except Exception:
                raise _fail("stale_context", "selected image region could not be verified") from None
            if not any(r["region_id"] == part["region_id"] and r["garment_type"] == garment for r in image["regions"]):
                raise _fail("invalid_input", "region is absent or belongs to another target garment")

    def submit(self, request: Any, action: Any, expected: Any, now: datetime,
               freshness: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        _shape(action, c.FeedbackAction.__required_keys__, "submit_feedback")
        reaction = action["reaction"]
        if reaction not in ("selected", "none", "unsure", "text_only", "question_skipped"):
            raise _fail("invalid_input", "unsupported feedback reaction")
        selections = _list(action["selections"], "selections", 4)
        text = action["text"]
        if text is not None:
            _text(text, "text", 4000)
        if ((reaction == "selected" and not selections) or (reaction != "selected" and selections)
            or (reaction == "text_only" and text is None)
            or (reaction == "question_skipped" and (text is not None or action["question_id"] is None))):
            raise _fail("invalid_input", "reaction, selections, text and question must agree")
        if (action["round_id"] is None) != (action["candidate_set_id"] is None):
            raise _fail("invalid_input", "round and candidate set must both be present or null")
        round_obj = candidate_set = question = None
        if action["round_id"] is not None:
            round_obj, candidate_set = self.current_set(request, action["round_id"], action["candidate_set_id"], expected, now, freshness)
        elif reaction not in ("text_only", "question_skipped") or selections:
            raise _fail("invalid_input", "image reactions require an issued candidate set")
        if action["question_id"] is not None:
            question = self.object(request, "question", action["question_id"], now)
            question_ref = _ref("question", question)
            if question_ref not in expected["object_versions"]:
                raise _fail("invalid_input", "question response requires its current version")
            if question["status"] != "open":
                raise _fail("stale_context", "question has already been answered or skipped")
            if round_obj:
                if question_ref not in round_obj["question_refs"]:
                    raise _fail("invalid_input", "question does not belong to this comparison")
            elif self.conn.execute("SELECT 1 FROM v1_object_refs WHERE owner_id=? AND role='candidate_set'", (question["id"],)).fetchone():
                raise _fail("invalid_input", "comparison question requires its round and candidate set")
        targets = {t["target_id"]: t["garment_type"] for t in json.loads(request["targets_json"])}
        cards = {card["candidate_id"]: card for card in candidate_set["cards"]} if candidate_set else {}
        selected = []
        seen = set()
        for selection in selections:
            _shape(selection, c.Selection.__required_keys__, "selection")
            _text(selection["candidate_id"], "candidate_id")
            _text(selection["target_id"], "target_id")
            card = cards.get(selection["candidate_id"])
            if card is None or card["target_id"] != selection["target_id"]:
                raise _fail("invalid_input", "selection is not a displayed candidate/target pair")
            if question and question["target_id"] not in (None, selection["target_id"]):
                raise _fail("invalid_input", "selection does not answer this question's target")
            self._part(selection["part_ref"], card, targets[card["target_id"]], freshness)
            key = _canonical(selection)
            if key in seen:
                raise _fail("invalid_input", "duplicate selection")
            seen.add(key)
            selected.append((selection, card))
        retention = min([request["retention_until"], _iso(now + _REQUEST_INACTIVITY)]
                        + [o["retention_until"] for o in (round_obj, candidate_set, question) if o], key=_us)
        feedback = self.v1._metadata(request["user_id"], request["id"], now, retention)
        evidence = []
        def add(kind, *, quote=None, selection=None, selector=None, context=None):
            obj = self.v1._metadata(request["user_id"], request["id"], now, retention) | {
                "kind": kind, "quote": quote, "context": context, "selector": selector or {"garment_type": None, "slot_id": None},
                "selection": selection, "display_ref": None, "snapshot": None,
            }
            refs = {"round": [_ref("round", round_obj)], "candidate_set": [_ref("candidate_set", candidate_set)]} if round_obj else {}
            self.v1._put("evidence", obj, refs)
            evidence.append(_ref("evidence", obj))
        # A set of selections, never a ranking: keep only the selected fact.
        for selection, card in sorted(selected, key=lambda pair: _canonical(pair[0])):
            add("image_selection", selection=selection | {"round_ref": _ref("round", round_obj),
                "candidate_set_ref": _ref("candidate_set", candidate_set), "product_id": card["product_id"],
                "product_map_version": card["product_map_version"], "image_id": card["image_id"], "image_version": card["image_version"]},
                selector={"garment_type": targets[card["target_id"]], "slot_id": card["target_id"]})
        if reaction in ("none", "unsure", "question_skipped"):
            add("ui_response", context=reaction)
        self.store._call_failure_hook("feedback_after_selection")
        if text is not None:
            add("user_text", quote=text)
        self.store._call_failure_hook("feedback_after_evidence")
        changed = list(evidence)
        if question:
            question = self.v1._update("question", question | {"status": "skipped" if reaction == "question_skipped" else "answered"})
            changed.append(_ref("question", question))
            # Round question_refs identify the issued question versions. The
            # current status/version is queried from snapshot.questions.
        interpretation = self.v1._metadata(request["user_id"], request["id"], now, retention) | {
            "feedback_ref": _ref("feedback", feedback), "status": "pending", "extraction_key": None,
            "candidate_refs": [], "question_refs": [], "error": None,
        }
        feedback |= {"reaction": reaction, "round_ref": _ref("round", round_obj) if round_obj else None,
                     "candidate_set_ref": _ref("candidate_set", candidate_set) if candidate_set else None,
                     "question_ref": _ref("question", question) if question else None,
                     "evidence_refs": evidence, "interpretation_ref": _ref("interpretation", interpretation)}
        refs = {"evidence": evidence}
        for key, role in (("round_ref", "round"), ("candidate_set_ref", "candidate_set"), ("question_ref", "question")):
            if feedback[key]:
                refs[role] = [feedback[key]]
        self.v1._put("feedback", feedback, refs)
        self.v1._put("interpretation", interpretation, {"feedback": [interpretation["feedback_ref"]]})
        self.conn.execute("INSERT INTO v1_object_refs VALUES (?, 'interpretation', 0, ?, 'interpretation', 1)",
                          (feedback["id"], interpretation["id"]))
        return changed + [_ref("feedback", feedback), _ref("interpretation", interpretation)], interpretation

    def extract(self, request: Any, action: Any, now: datetime, freshness: Any) -> list[dict[str, Any]]:
        _shape(action, c.RecordExtractionAction.__required_keys__, "record_extraction")
        c.validate_ref(action["feedback_ref"])
        if action["feedback_ref"]["type"] != "feedback":
            raise _fail("invalid_input", "extraction requires a feedback reference")
        _text(action["extraction_key"], "extraction_key")
        if (action["result"] is None) == (action["error"] is None):
            raise _fail("invalid_input", "extraction needs exactly one result or error")
        feedback = self.v1._resolve(request["user_id"], request["id"], action["feedback_ref"], now)
        state = self.object(request, "interpretation", feedback["interpretation_ref"]["id"], now)
        prior = self.conn.execute("SELECT * FROM v1_extraction_results WHERE feedback_id=?", (feedback["id"],)).fetchone()
        if prior:
            if prior["extraction_key"] != action["extraction_key"]:
                raise _fail("stale_context", "completed feedback needs no new extraction")
            if action["result"] is not None and prior["fingerprint"] != _digest(action["result"]):
                raise _fail("idempotency_conflict", "extraction key was completed with a different result")
            return []
        if state['status'] == 'complete':
            # Erasure may retain a redacted intake, but never its former model
            # result/fingerprint. Such an intake cannot become new evidence.
            raise _fail('stale_context', 'redacted feedback cannot be reinterpreted')
        if request["status"] != "open":
            raise _fail("request_closed", "extraction requires an open request")
        latest = self.conn.execute(
            """SELECT o.id FROM v1_objects o JOIN v1_feedback f ON f.id=o.id
               WHERE o.user_id=? AND o.request_id=? ORDER BY o.rowid DESC LIMIT 1""", (request["user_id"], request["id"]),
        ).fetchone()
        if latest["id"] != feedback["id"]:
            raise _fail("stale_context", "a newer feedback supersedes this extraction")
        active = None
        if feedback["round_ref"]:
            active = self.active_round(request, now)
            if not active or active["candidate_set_ref"] != feedback["candidate_set_ref"]:
                raise _fail("stale_context", "feedback's candidate set is no longer active")
            candidate_set = self.v1._resolve(request["user_id"], request["id"], feedback["candidate_set_ref"], now)
            self.check_catalog(candidate_set["basis"]["catalog"], freshness)
        evidence = [self.v1._resolve(request["user_id"], request["id"], ref, now) for ref in feedback["evidence_refs"]]
        if action["error"] is not None:
            error = _shape(action["error"], c.PublicError.__required_keys__, "extraction error")
            if not isinstance(error["code"], str) or error["code"] not in V1_ERROR_CODES:
                raise _fail("invalid_input", "unsupported extraction error")
            _text(error["message"], "extraction error message", 4000)
            state = self.v1._update("interpretation", state | {"status": "pending", "extraction_key": action["extraction_key"],
                "error": {"code": error["code"], "message": "Interpretation is pending; retry is available."}})
            return [_ref("interpretation", state)]
        from .model_io import validate_extraction_v1

        registry = load_registry(request["registry_version"])
        sources = [{"source_id": e["id"], "kind": e["kind"],
                    "content": e["quote"] if e["kind"] == "user_text" else _canonical(e["selection"]), "selector": e["selector"]}
                   for e in evidence if e["kind"] in ("user_text", "image_selection")]
        result = validate_extraction_v1(action["result"], {"sources": sources, "targets": json.loads(request["targets_json"]),
                                                        "registry": registry.describe()}, registry)
        if feedback["reaction"] == "question_skipped" and result["candidates"]:
            raise _fail("invalid_extraction", "skipping a question is not an answer or a preference")
        refs_by_id = {ref["id"]: ref for ref in feedback["evidence_refs"]}
        changed, candidate_refs = [], []
        for candidate in result["candidates"]:
            memory = {key: candidate[key] for key in ("kind", "content", "fact", "selector", "conditions", "polarity", "strength")}
            memory |= {"valid_from": None, "valid_until": None}
            self.v1._memory_content(memory, request)
            # Validate even a quoted hard requirement as a *candidate*. These
            # bindings remain inferred/unconfirmed; no confirmation is granted.
            specs = self.v1._binding_specs(request, memory, candidate["bindings"], confirmed=True)
            refs = [refs_by_id[source_id] for source_id in candidate["source_ids"]]
            obj = self.v1._metadata(request["user_id"], request["id"], now, state["retention_until"]) | memory | {
                "scope": "short_term", "origin": "inferred", "confirmed": False, "status": "candidate",
                "source_refs": refs, "confirmation_ref": None, "consent_ref": None, "family_id": _new_id(),
            }
            self.v1._put("memory", obj, {"source": refs})
            bindings = self.v1._new_bindings(request, obj, specs, refs, now)
            candidate_refs.append(_ref("memory", obj))
            changed += [_ref("memory", obj)] + [_ref("binding", b) for b in bindings]
            self.store._call_failure_hook("extraction_after_candidate")
        questions = [self.question(request, {"text": text, "target_id": None, "subject_refs": feedback["evidence_refs"], "options": []},
                                   now, state["retention_until"]) for text in result["questions"]]
        if questions and active:
            for index, question in enumerate(questions, start=len(active["question_refs"])):
                self._question_set(question, active["candidate_set_ref"])
                self.conn.execute("INSERT INTO v1_object_refs VALUES (?, 'question', ?, ?, 'question', ?)",
                                  (active["id"], index, question["id"], question["version"]))
            active = self.v1._update("round", active | {"question_refs": active["question_refs"] + [_ref("question", q) for q in questions]})
            changed.append(_ref("round", active))
        state = self.v1._update("interpretation", state | {"status": "complete", "extraction_key": action["extraction_key"],
            "candidate_refs": candidate_refs, "question_refs": [_ref("question", q) for q in questions], "error": None})
        self.conn.execute("INSERT INTO v1_extraction_results VALUES (?,?,?)", (feedback["id"], action["extraction_key"], _digest(action["result"])))
        self.store._call_failure_hook("extraction_before_complete")
        return changed + [_ref("question", q) for q in questions] + [_ref("interpretation", state)]

    def select_final(self, request: Any, action: Any, expected: Any, now: datetime, freshness: Any) -> bool:
        _shape(action, c.SelectFinalAction.__required_keys__, "select_final")
        c.validate_ref(action["candidate_set_ref"])
        if action["candidate_set_ref"]["type"] != "candidate_set":
            raise _fail("invalid_input", "final selection requires a candidate set")
        _text(action["candidate_id"], "candidate_id")
        round_obj = self.active_round(request, now)
        if round_obj is None:
            raise _fail("stale_context", "no active comparison")
        _, candidate_set = self.current_set(request, round_obj["id"], action["candidate_set_ref"]["id"], expected, now, freshness)
        if _ref("candidate_set", candidate_set) != action["candidate_set_ref"]:
            raise _fail("version_conflict", "final candidate-set version changed")
        card = next((card for card in candidate_set["cards"] if card["candidate_id"] == action["candidate_id"]), None)
        if card is None:
            raise _fail("invalid_input", "final candidate was not displayed")
        final = {"candidate_set_ref": _ref("candidate_set", candidate_set)} | {k: card[k] for k in
                  ("candidate_id", "target_id", "product_id", "product_map_version")}
        encoded = _canonical(final)
        if request["final_selection_json"] == encoded:
            return False
        self.conn.execute("UPDATE requests SET final_selection_json=? WHERE id=?", (encoded, request["id"]))
        return True
