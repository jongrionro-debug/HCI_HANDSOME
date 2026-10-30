"""Transactional v1 erasure; SQLite remains the only authoritative store.

Unstructured summaries/caches are invalidated, never edited by a model. Mixed
quotes can retain only verbatim, disjoint excerpts already used by surviving
memories. Without that evidence the affected quote is erased conservatively.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from .errors import StyleMateError
from .store import _CLOSED_RETENTION, _DELETION_RECEIPT_TTL, _canonical, _digest, _fail, _iso, _new_id
from .store_v1 import _META_KEYS, _TABLES, _ref, _us


def _refs(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        if set(value) == {"type", "id", "version"}:
            return [value]
        return [ref for item in value.values() for ref in _refs(item)]
    if isinstance(value, list):
        return [ref for item in value for ref in _refs(item)]
    return []


def _remaining_quote(quote: str, erased: list[str], survivors: list[str]) -> str | None:
    """Choose a verbatim safe span; never manufacture a joined quotation."""
    if not quote or not erased or not all(text and text in quote for text in erased):
        return None
    intervals = []
    for text in erased:
        start = quote.find(text)
        while start >= 0:
            intervals.append((start, start + len(text)))
            start = quote.find(text, start + 1)
    cursor, spans = 0, []
    for start, end in sorted(intervals):
        if cursor < start:
            spans.append(quote[cursor:start])
        cursor = max(cursor, end)
    spans.append(quote[cursor:])
    candidates = []
    for span in spans:
        supported = [text for text in survivors if text and text in span]
        if supported:
            first = min(span.index(text) for text in supported)
            last = max(span.rindex(text) + len(text) for text in supported)
            candidates.append((len(supported), span[first:last]))
    return max(candidates, key=lambda item: (item[0], len(item[1])))[1] if candidates else None


class CleanupStorage:
    def __init__(self, storage: Any) -> None:
        self.v1 = storage
        self.store = storage.store

    @property
    def conn(self):
        return self.store.connection

    def mark_pending(self, user_id: str) -> None:
        # Only an owner flag persists: no deleted IDs, content or payload hash.
        self.conn.execute("INSERT OR IGNORE INTO v1_cleanup_pending VALUES (?)", (user_id,))

    def finish(self, user_id: str | None = None) -> None:
        query = "SELECT user_id FROM v1_cleanup_pending"
        rows = self.conn.execute(query + (" WHERE user_id=?" if user_id is not None else ""),
                                 (user_id,) if user_id is not None else ()).fetchall()
        if not rows:
            return
        try:
            self.store._call_failure_hook("cleanup_before_vacuum")
            self.store._vacuum()
            # If this write fails the flag remains and another call retries.
            self.conn.executemany("DELETE FROM v1_cleanup_pending WHERE user_id=?",
                                  [(row["user_id"],) for row in rows])
        except Exception as exc:
            raise _fail("cleanup_pending", "SQLite cleanup is pending; retry the operation or prune_expired") from exc

    def prune(self, user_id: str | None = None) -> dict[str, int]:
        self.finish(user_id)
        now = self.store._now()
        counts = {"requests": 0, "memories": 0}
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            owners = [user_id] if user_id is not None else [r[0] for r in self.conn.execute("SELECT user_id FROM profiles")]
            for owner in owners:
                requests = self.conn.execute(
                    "SELECT * FROM requests WHERE user_id=? AND contract_version IS NOT NULL", (owner,)).fetchall()
                for row in requests:
                    if _us(row["retention_until"]) <= _us(now):
                        counts["memories"] += len(self.erase_request(row, now))
                        counts["requests"] += 1
                seeds = {r[0] for r in self.conn.execute(
                    "SELECT id FROM v1_objects WHERE user_id=? AND retention_us<=?", (owner, _us(now)))}
                seeds.update(r[0] for r in self.conn.execute(
                    """SELECT m.id FROM v1_memories m JOIN v1_objects o ON o.id=m.id
                       WHERE o.user_id=? AND m.valid_until_us<=?""", (owner, _us(now))))
                long_expired = {r[0] for r in self.conn.execute(
                    """SELECT m.id FROM v1_memories m JOIN v1_objects o ON o.id=m.id
                       WHERE o.user_id=? AND m.scope='long_term' AND (o.retention_us<=? OR m.valid_until_us<=?)""",
                    (owner, _us(now), _us(now)))}
                for group, family in ((long_expired, True), (seeds - long_expired, False)):
                    if group:
                        result = self.erase(owner, group, now, family=family)
                        counts["memories"] += len(result["removed_memories"])
                        if result["profile_changed"]:
                            self.store._bump_profile(owner)
                self.store._purge_expired_nonces(owner, now)
            self.conn.commit()
        except StyleMateError:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise _fail('storage_failed', 'Expiry cleanup was rolled back; retry prune_expired') from exc
        self.finish(user_id)
        return counts

    def delete_request(self, user_id: str, request_id: str) -> dict[str, Any]:
        now = self.store._now()
        ids = []
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.store._purge_expired_nonces(user_id, now)
            row = self.conn.execute("SELECT * FROM requests WHERE user_id=? AND id=?", (user_id, request_id)).fetchone()
            if row is not None:
                ids = self.erase_request(row, now)
            else:
                receipts = self.conn.execute("SELECT * FROM v1_request_deletions WHERE user_id=?", (user_id,)).fetchall()
                if not any(r["command_fingerprint"] == self._request_fingerprint(request_id, r["opaque"]) for r in receipts):
                    raise _fail("not_found", "request not found")
            self.conn.commit()
        except StyleMateError:
            self.conn.rollback()
            raise
        except Exception as exc:
            self.conn.rollback()
            raise _fail('storage_failed', 'Request deletion was rolled back; retry the operation') from exc
        self.finish(user_id)
        return {"request_id": request_id, "memory_ids": ids, "deleted": True}

    @staticmethod
    def _request_fingerprint(request_id: str, opaque: str) -> str:
        return _digest({"op": "delete_request", "opaque": opaque, "request_id": request_id})

    def _objects(self, user_id: str) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        kinds, objects = {}, {}
        for kind, table in _TABLES.items():
            for row in self.conn.execute(
                f"SELECT o.*,t.payload_json FROM v1_objects o JOIN {table} t ON t.id=o.id WHERE o.user_id=?",
                (user_id,),
            ):
                kinds[row["id"]] = kind
                objects[row["id"]] = self.v1._object(row)
        return kinds, objects

    def tombstone_batches(self, user_id: str, now: Any, *, affected: set[str],
                          request_ids: set[str] = frozenset()) -> None:
        for row in self.conn.execute("SELECT * FROM v1_batch_receipts WHERE user_id=?", (user_id,)).fetchall():
            receipt = json.loads(row["receipt_json"])
            if row["request_id"] not in request_ids and not any(r["id"] in affected for r in _refs(receipt)):
                continue
            self.conn.execute("INSERT OR REPLACE INTO batch_tombstones VALUES (?,?,?)",
                              (user_id, row["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)))
            self.conn.execute("DELETE FROM v1_batch_receipts WHERE user_id=? AND batch_id=?",
                              (user_id, row["batch_id"]))

    def erase(self, user_id: str, seeds: set[str], now: Any, *, family: bool = False,
              withdraw: bool = False, request_ids: set[str] = frozenset()) -> dict[str, Any]:
        """Plan and erase in the caller's transaction; no external source is read.

        A promoted independent long-term snapshot survives request erasure.
        Memory erasure/withdrawal follows families and derived_from copies.
        supports/supersedes only lose their link, never the other memory.
        """
        kinds, original = self._objects(user_id)
        objects = copy.deepcopy(original)
        stored_edges: dict[str, set[str]] = {}
        for edge in self.conn.execute(
            "SELECT r.owner_id,r.target_id FROM v1_object_refs r JOIN v1_objects o ON o.id=r.owner_id WHERE o.user_id=?",
            (user_id,),
        ):
            stored_edges.setdefault(edge['owner_id'], set()).add(edge['target_id'])
        blocked = set(seeds) & objects.keys()
        if not blocked and not request_ids:
            return {"removed_memories": [], "withdrawn_memories": [], "profile_changed": False, "changed_refs": []}
        while True:
            before = set(blocked)
            if family:
                families = {objects[i]["family_id"] for i in blocked if kinds[i] == "memory"}
                blocked.update(i for i, o in objects.items() if kinds[i] == "memory" and o["family_id"] in families)
            for i, o in objects.items():
                if (kinds[i] == "link" and (o["relation"] == 'derived_from' or family and o["relation"] == 'promoted_from')
                        and o["target_ref"]["id"] in blocked):
                    blocked.add(o["source_ref"]["id"])
                if kinds[i] == "memory" and any(r['type'] == 'memory' and r["id"] in blocked for r in o["source_refs"]):
                    blocked.add(i)
            if blocked == before:
                break
        memory_seeds = {i for i in blocked if kinds[i] == "memory"}
        protected: set[str] = set()
        if withdraw:
            # Closed records retain their original bounded history. Independent
            # Evidence snapshots and usable copies are removed below.
            protected = set(memory_seeds)
            protected.update(i for i, o in objects.items() if o.get("memory_id") in memory_seeds)
            for i in list(protected):
                event = objects[i].get("event_ref")
                if event and event["id"] in objects:
                    protected.add(event["id"])
                    protected.add(objects[event["id"]]["display_ref"]["id"])
        doomed = blocked - protected
        changed: set[str] = set(protected)
        def redact_evidence():
            erased_memories = {i for i in doomed | blocked if kinds[i] == 'memory'}
            tainted = {r['id'] for i in erased_memories for r in original[i]['source_refs'] if r['type'] == 'evidence'}
            for evidence_id in tainted - doomed:
                evidence = objects.get(evidence_id)
                if evidence is None:
                    continue
                erased = [original[i]['content'] for i in erased_memories
                          if any(r['id'] == evidence_id for r in original[i]['source_refs'])]
                quote = original[evidence_id].get('quote')
                remainder = None
                if evidence.get('kind') == 'user_text' and quote:
                    excerpts = [o['content'] for i, o in original.items() if kinds[i] == 'memory'
                        and i not in doomed | blocked and any(r['id'] == evidence_id for r in o['source_refs'])]
                    remainder = _remaining_quote(quote, erased, excerpts)
                if remainder:
                    evidence.update(quote=remainder, context=None)
                    changed.add(evidence_id)
                else:
                    doomed.add(evidence_id)

        def keep_refs(refs):
            return [r for r in refs if r["id"] not in doomed and r["id"] not in blocked - protected]

        def update(i, **fields):
            if any(objects[i].get(k) != v for k, v in fields.items()):
                objects[i].update(fields)
                changed.add(i)

        while True:
            before = (len(doomed), len(changed))
            redact_evidence()
            affected = doomed | changed | blocked
            for i, o in objects.items():
                if i in doomed:
                    continue
                kind = kinds[i]
                dependencies = {r["id"] for r in _refs(o)} | stored_edges.get(i, set())
                if i in protected:
                    if "source_refs" in o:
                        update(i, source_refs=[])
                    if kind == "display":
                        snapshot = o["snapshot"] | {"subject_refs": keep_refs(o["snapshot"]["subject_refs"])}
                        basis = o["basis"] | {"object_versions": keep_refs(o["basis"]["object_versions"])}
                        update(i, snapshot=snapshot, basis=basis)
                    continue
                if kind == "memory":
                    if not dependencies & affected:
                        continue
                    # A source memory is a content dependency, unlike a supports link.
                    proofs = [o.get(key) for key in ('confirmation_ref', 'consent_ref')]
                    if any(r and r['id'] in doomed for r in proofs) or any(
                        r["type"] == "memory" and r["id"] in doomed | blocked for r in o["source_refs"]):
                        doomed.add(i)
                    else:
                        sources = keep_refs(o["source_refs"])
                        redacted = [objects[r['id']] for r in sources if r['type'] == 'evidence' and r['id'] in changed]
                        if not sources or sources != o['source_refs'] or any(
                            e.get('kind') == 'user_text' and o['content'] not in e['quote'] for e in redacted):
                            doomed.add(i)
                elif kind in ("binding", "confirmation", "consent"):
                    proof_ref = o.get('event_ref') or o.get('confirmation_ref')
                    if o["memory_id"] in doomed or proof_ref and proof_ref['id'] in doomed:
                        doomed.add(i)
                    else:
                        sources = keep_refs(o["source_refs"])
                        if not sources or sources != o['source_refs']:
                            doomed.add(i)
                        elif kind in ('confirmation', 'consent'):
                            snapshot = o['snapshot']
                            subjects = keep_refs(snapshot['subject_refs'])
                            removed_specs = [self.v1._spec(objects[r['id']]) for r in snapshot['subject_refs']
                                             if r['type'] == 'binding' and r['id'] in doomed]
                            remaining_specs = [self.v1._spec(objects[r['id']]) for r in subjects if r['type'] == 'binding']
                            bindings = [spec for spec in snapshot['bindings'] if spec not in removed_specs or spec in remaining_specs]
                            update(i, snapshot=snapshot | {'subject_refs': subjects, 'bindings': bindings})
                elif kind == "link":
                    if dependencies & (doomed | blocked):
                        doomed.add(i)
                elif kind == "derived":
                    # There is no durable summary/index product contract yet.
                    # Drop the whole opaque materialization rather than retain text.
                    doomed.add(i)
                elif kind == "display":
                    if dependencies & affected:
                        # A consumed proof for surviving content may keep its
                        # meaning, but never a deleted source in its basis.
                        proof_owners = [p for j, p in objects.items() if j not in doomed
                            and kinds[j] in ("confirmation", "consent") and p["event_ref"]["id"] in objects
                            and objects[p["event_ref"]["id"]].get("display_ref", {}).get("id") == i]
                        if proof_owners:
                            update(i, snapshot=o["snapshot"] | {"subject_refs": keep_refs(o["snapshot"]["subject_refs"])},
                                   basis=o["basis"] | {"object_versions": keep_refs(o["basis"]["object_versions"])})
                        else:
                            doomed.add(i)
                elif kind == "event":
                    if o["display_ref"]["id"] in doomed:
                        doomed.add(i)
                elif kind == "evidence":
                    if dependencies & doomed:
                        doomed.add(i)
                elif kind == "feedback":
                    if any(o.get(k) and o[k]["id"] in doomed for k in ("round_ref", "candidate_set_ref", "question_ref")):
                        # Keep independently surviving evidence; obsolete UI refs
                        # cannot be used for a new confirmation or extraction.
                        update(i, **{k: None for k in ("round_ref", "candidate_set_ref", "question_ref")
                                     if o.get(k) and o[k]["id"] in doomed})
                    evidence = keep_refs(o["evidence_refs"])
                    if not evidence:
                        doomed.add(i)
                    elif evidence != o["evidence_refs"] or dependencies & changed:
                        reaction = o["reaction"]
                        if reaction == "selected" and not any(objects[r["id"]].get("kind") == "image_selection" for r in evidence):
                            reaction = "text_only"
                        update(i, evidence_refs=evidence, reaction=reaction)
                        changed.add(i)
                elif kind == "interpretation":
                    if o["feedback_ref"]["id"] in doomed:
                        doomed.add(i)
                    elif dependencies & affected:
                        # A redacted intake is terminal: old model responses must
                        # never be treated as a fresh extraction of its remainder.
                        update(i, candidate_refs=keep_refs(o["candidate_refs"]), question_refs=keep_refs(o["question_refs"]),
                               status="complete", extraction_key=None, error=None)
                        changed.add(i)
                elif kind in ("question", "candidate_set"):
                    if dependencies & affected:
                        doomed.add(i)
                elif kind == "round":
                    if o["candidate_set_ref"]["id"] in doomed:
                        doomed.add(i)
                    else:
                        update(i, question_refs=keep_refs(o["question_refs"]))
            if before == (len(doomed), len(changed)):
                break

        versions = {i: objects[i]["version"] + 1 for i in changed - doomed}

        def rewrite(value):
            if isinstance(value, dict):
                if set(value) == {"type", "id", "version"}:
                    return value | {"version": versions[value["id"]]} if value["id"] in versions else value
                return {k: rewrite(v) for k, v in value.items()}
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            return value

        # Update surviving ref owners as well, so a new index cannot resurrect
        # either the old quote version or its pre-erasure fingerprint.
        while True:
            before = len(versions)
            for i, o in objects.items():
                if i not in doomed and (rewrite(o) != original[i] or i in changed):
                    versions[i] = o["version"] + 1
                    changed.add(i)
            if before == len(versions):
                break
        affected = doomed | changed | blocked
        # This synchronous, idempotent invalidation boundary can fail before
        # SQLite commits. No successful deletion receipt is written on failure.
        try:
            self.store._call_failure_hook("cleanup_derived", {"user_id": user_id,
                "request_ids": sorted(request_ids),
                "object_refs": [_ref(kinds[i], original[i]) for i in sorted(affected)]})
        except Exception as exc:
            raise _fail("cleanup_pending", "Derived cleanup failed; the transaction was rolled back, retry the operation") from exc
        for i in sorted(changed - doomed):
            o = rewrite(objects[i])
            o["version"] = versions[i]
            if i in protected:
                retention = min(o["retention_until"], _iso(now + _CLOSED_RETENTION), key=_us)
                self.conn.execute("UPDATE v1_objects SET retention_until=?,retention_us=? WHERE id=?",
                                  (retention, _us(retention), i))
            self.conn.execute("UPDATE v1_objects SET version=? WHERE id=?", (o["version"], i))
            self.conn.execute(f"UPDATE {_TABLES[kinds[i]]} SET payload_json=? WHERE id=?",
                              (_canonical({k: v for k, v in o.items() if k not in _META_KEYS}), i))
        # Rebuild relationship rows from surviving versions without cascades
        # through supports or FK-order-dependent partial deletion.
        edges = self.conn.execute("SELECT r.* FROM v1_object_refs r JOIN v1_objects o ON o.id=r.owner_id WHERE o.user_id=?",
                                  (user_id,)).fetchall()
        for edge in edges:
            owner = objects[edge["owner_id"]]
            removed_source = (edge['role'] == 'source' and 'source_refs' in owner
                              and edge['target_id'] not in {r['id'] for r in owner['source_refs']})
            if edge["owner_id"] in doomed or edge["target_id"] in doomed or removed_source:
                self.conn.execute("DELETE FROM v1_object_refs WHERE owner_id=? AND role=? AND position=?",
                                  (edge["owner_id"], edge["role"], edge["position"]))
            elif edge["target_id"] in versions:
                self.conn.execute("UPDATE v1_object_refs SET target_version=? WHERE owner_id=? AND role=? AND position=?",
                                  (versions[edge["target_id"]], edge["owner_id"], edge["role"], edge["position"]))
        for i in sorted(doomed):
            self.conn.execute("DELETE FROM v1_objects WHERE id=?", (i,))
        for i in changed:
            if kinds[i] == "feedback":
                self.conn.execute("DELETE FROM v1_extraction_results WHERE feedback_id=?", (i,))
        self.tombstone_batches(user_id, now, affected=affected, request_ids=request_ids)
        affected_requests = {original[i]["request_id"] for i in affected if original[i]["request_id"] is not None}
        for request_id in affected_requests:
            self.conn.execute("UPDATE requests SET revision=revision+1 WHERE id=?", (request_id,))
        # Final product selection can contain a removed round/set reference too.
        for row in self.conn.execute("SELECT id,final_selection_json FROM requests WHERE user_id=? AND final_selection_json IS NOT NULL", (user_id,)):
            if any(r["id"] in affected for r in _refs(json.loads(row["final_selection_json"]))):
                self.conn.execute("UPDATE requests SET final_selection_json=NULL,revision=revision+1 WHERE id=?", (row["id"],))
        self.mark_pending(user_id)
        self.store._call_failure_hook("cleanup_after_objects")
        return {"removed_memories": sorted(i for i in doomed if kinds[i] == "memory"),
                "withdrawn_memories": sorted(memory_seeds) if withdraw else [],
                "profile_changed": any(original[i]["request_id"] is None for i in affected),
                "changed_refs": [_ref(kinds[i], objects[i] | {"version": versions[i]}) for i in sorted(changed - doomed)]}

    def erase_request(self, row: Any, now: Any) -> list[str]:
        user_id, request_id = row["user_id"], row["id"]
        seeds = {r["id"] for r in self.conn.execute("SELECT id FROM v1_objects WHERE user_id=? AND request_id=?", (user_id, request_id))}
        result = self.erase(user_id, seeds, now, request_ids={request_id})
        self.conn.execute("INSERT OR REPLACE INTO request_tombstones VALUES (?,?,?)",
                          (user_id, row["input_id"], _iso(now + _DELETION_RECEIPT_TTL)))
        for receipt in self.conn.execute("SELECT batch_id FROM deletion_receipts WHERE user_id=? AND request_id=?", (user_id, request_id)).fetchall():
            self.conn.execute("INSERT OR REPLACE INTO batch_tombstones VALUES (?,?,?)",
                              (user_id, receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)))
        opaque = _new_id()
        self.conn.execute("INSERT INTO v1_request_deletions VALUES (?,?,?,?)",
                          (user_id, opaque, self._request_fingerprint(request_id, opaque), _iso(now + _DELETION_RECEIPT_TTL)))
        self.conn.execute("DELETE FROM requests WHERE id=? AND user_id=?", (request_id, user_id))
        if result["profile_changed"]:
            self.store._bump_profile(user_id)
        return result["removed_memories"]
