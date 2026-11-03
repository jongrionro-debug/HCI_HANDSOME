"""Storage-only implementation of the opt-in A0 contract.

The public boundary remains MemoryStore. Round/feedback storage lives in
store_feedback and erasure propagation in store_cleanup.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, get_args
from zoneinfo import ZoneInfo

from . import contracts as c
from .errors import StyleMateError
from .registry import load_registry
# MemoryStore loads this helper after store.py has finished importing.
from .store import (
    _CLOSED_RETENTION, _LONG_TERM_RETENTION, _REQUEST_INACTIVITY, _REQUEST_MAX_AGE,
    _canonical, _digest, _fail, _iso,
    _new_id, _parse_datetime, _DELETION_RECEIPT_TTL,
)


SCHEMA_VERSION = 1
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_TABLES = {
    "memory": "v1_memories", "evidence": "v1_evidence", "binding": "v1_bindings",
    "confirmation": "v1_confirmations", "consent": "v1_consents", "link": "v1_links",
    "display": "v1_displays", "event": "v1_user_events", "feedback": "v1_feedback",
    "interpretation": "v1_interpretations", "question": "v1_questions",
    "round": "v1_rounds", "candidate_set": "v1_candidate_sets", "derived": "v1_derived",
}
_META_KEYS = set(c.StoredObject.__required_keys__)


def _shape(value: Any, keys: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise _fail("invalid_input", f"{name} has missing or unknown fields")
    return value


def _text(value: Any, name: str, limit: int = 128) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise _fail("invalid_input", f"{name} must be a non-blank string within {limit} characters")
    try:
        value.encode("utf-8")
    except UnicodeError:
        raise _fail("invalid_input", f"{name} must be valid UTF-8") from None
    return value  # preserve quotes, IDs and canonical strings exactly


def _list(value: Any, name: str, limit: int, *, nonempty: bool = False) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit or (nonempty and not value):
        raise _fail("invalid_input", f"{name} has an invalid length")
    return value


def _us(value: str | datetime) -> int:
    dt = value if isinstance(value, datetime) else _parse_datetime(value, "timestamp", allow_none=False)
    delta = dt.astimezone(timezone.utc) - _EPOCH
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def _ref(kind: str, obj: dict[str, Any]) -> dict[str, Any]:
    return {"type": kind, "id": obj["id"], "version": obj["version"]}


def _batch_size(value: dict[str, Any]) -> None:
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise _fail("invalid_input", "batch must be valid UTF-8 JSON") from None
    if size > 256 * 1024:
        raise _fail("invalid_input", "batch exceeds 256 KiB")


class V1Storage:
    def __init__(self, store: Any) -> None:
        self.store = store
        from .store_feedback import FeedbackStorage

        self.feedback = FeedbackStorage(self)

    @property
    def conn(self) -> sqlite3.Connection:
        return self.store.connection

    def migrate_schema(self) -> None:
        """Add storage tables atomically, without converting legacy rows."""
        conn = self.conn
        if conn.execute("PRAGMA user_version").fetchone()[0] > SCHEMA_VERSION:
            raise _fail("unsupported_contract", "unsupported storage schema version")
        try:
            conn.execute("BEGIN IMMEDIATE")
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(requests)")}
            for name, spec in {
                "contract_version": "TEXT", "registry_version": "TEXT",
                "mode": "TEXT NOT NULL DEFAULT 'shopping'",
                "targets_json": "TEXT NOT NULL DEFAULT '[]'", "final_selection_json": "TEXT",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE requests ADD COLUMN {name} {spec}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS requests_owner_idx ON requests(id,user_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_objects (
                id TEXT PRIMARY KEY, object_type TEXT NOT NULL,
                user_id TEXT NOT NULL REFERENCES profiles(user_id), request_id TEXT,
                contract_version TEXT NOT NULL CHECK(contract_version='lumi-memory-v1'),
                version INTEGER NOT NULL CHECK(typeof(version)='integer' AND version>=1),
                created_at TEXT NOT NULL, retention_until TEXT NOT NULL, retention_us INTEGER NOT NULL,
                FOREIGN KEY(request_id,user_id) REFERENCES requests(id,user_id) ON DELETE CASCADE
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS v1_scope_idx ON v1_objects(user_id,request_id,object_type,retention_us)")
            extras = {
                "memory": """scope TEXT NOT NULL CHECK(scope IN ('short_term','long_term')),
                    status TEXT NOT NULL CHECK(status IN ('candidate','active','superseded','withdrawn')),
                    valid_from_us INTEGER, valid_until_us INTEGER,""",
                "binding": """memory_id TEXT NOT NULL REFERENCES v1_memories(id) ON DELETE CASCADE,
                    registry_version TEXT NOT NULL,""",
                "confirmation": "memory_id TEXT NOT NULL REFERENCES v1_memories(id) ON DELETE CASCADE,",
                "consent": "memory_id TEXT NOT NULL REFERENCES v1_memories(id) ON DELETE CASCADE,",
            }
            for kind, table in _TABLES.items():
                conn.execute(f"""CREATE TABLE IF NOT EXISTS {table} (
                    id TEXT PRIMARY KEY REFERENCES v1_objects(id) ON DELETE CASCADE,
                    {extras.get(kind, '')} payload_json TEXT NOT NULL
                )""")
            conn.execute("CREATE INDEX IF NOT EXISTS v1_binding_memory_idx ON v1_bindings(memory_id)")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_object_refs (
                owner_id TEXT NOT NULL REFERENCES v1_objects(id) ON DELETE CASCADE,
                role TEXT NOT NULL, position INTEGER NOT NULL,
                target_id TEXT NOT NULL REFERENCES v1_objects(id), target_type TEXT NOT NULL,
                target_version INTEGER NOT NULL CHECK(typeof(target_version)='integer' AND target_version>=1),
                PRIMARY KEY(owner_id,role,position)
            )""")
            conn.execute("CREATE INDEX IF NOT EXISTS v1_reverse_refs_idx ON v1_object_refs(target_id,target_type)")
            conn.execute("CREATE TABLE IF NOT EXISTS v1_cleanup_pending (user_id TEXT PRIMARY KEY)")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_request_deletions (
                user_id TEXT NOT NULL, opaque TEXT PRIMARY KEY,
                command_fingerprint TEXT NOT NULL, expires_at TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_event_uses (
                event_id TEXT PRIMARY KEY REFERENCES v1_objects(id) ON DELETE CASCADE
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_extraction_results (
                feedback_id TEXT PRIMARY KEY REFERENCES v1_objects(id) ON DELETE CASCADE,
                extraction_key TEXT NOT NULL, fingerprint TEXT NOT NULL
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_batch_receipts (
                user_id TEXT NOT NULL, batch_id TEXT NOT NULL,
                request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                fingerprint TEXT NOT NULL, receipt_json TEXT NOT NULL, created_at TEXT NOT NULL,
                PRIMARY KEY(user_id,batch_id)
            )""")
            conn.execute("""CREATE TABLE IF NOT EXISTS v1_legacy_migrations (
                user_id TEXT NOT NULL, source_request_id TEXT NOT NULL,
                target_request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                source_digest TEXT NOT NULL, PRIMARY KEY(user_id,source_request_id)
            )""")
            self.store._call_failure_hook("v1_schema_before_commit")
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    @staticmethod
    def check_contract(row: sqlite3.Row, contract_version: str | None) -> None:
        if contract_version not in (None, c.CONTRACT_VERSION) or row["contract_version"] != contract_version:
            raise _fail("unsupported_contract", "request and operation contracts do not match")
        if contract_version == c.CONTRACT_VERSION and row["registry_version"] != c.V1_REGISTRY_VERSION:
            raise _fail("unsupported_contract", "unsupported request registry version")

    @staticmethod
    def request_dict(row: sqlite3.Row) -> dict[str, Any]:
        return {
            key: row[key] for key in (
                "id", "user_id", "contract_version", "registry_version", "revision", "timezone",
                "created_at", "updated_at", "status", "retention_until", "max_until", "mode",
            )
        } | {
            "targets": json.loads(row["targets_json"]),
            "final_selection": json.loads(row["final_selection_json"]) if row["final_selection_json"] else None,
        }

    def _request(self, user_id: str, request_id: str, *, include_closed: bool = False) -> sqlite3.Row:
        row = self.store._request_row(user_id, request_id)
        self.check_contract(row, c.CONTRACT_VERSION)
        if row["status"] == "expired" or _us(row["retention_until"]) <= _us(self.store._now()):
            raise _fail("request_expired", "request retention has expired")
        if not include_closed and row["status"] != "open":
            raise _fail("request_closed", "request is not open")
        return row

    def _metadata(self, user_id: str, request_id: str | None, now: datetime, retention: str) -> dict[str, Any]:
        return {
            "id": _new_id(), "user_id": user_id, "request_id": request_id,
            "contract_version": c.CONTRACT_VERSION, "version": 1,
            "created_at": _iso(now), "retention_until": retention,
        }

    def _put(
        self, kind: str, obj: dict[str, Any], refs: dict[str, list[dict[str, Any]]] | None = None,
    ) -> None:
        """Internal transactional insert; callers validate authority and references."""
        self.conn.execute(
            """INSERT INTO v1_objects
                (id,object_type,user_id,request_id,contract_version,version,created_at,retention_until,retention_us)
                VALUES (?,?,?,?,?,?,?,?,?)""",
            (obj["id"], kind, obj["user_id"], obj["request_id"], obj["contract_version"],
             obj["version"], obj["created_at"], obj["retention_until"], _us(obj["retention_until"])),
        )
        columns: dict[str, Any] = {"id": obj["id"]}
        if kind == "memory":
            columns.update({
                "scope": obj["scope"], "status": obj["status"],
                "valid_from_us": _us(obj["valid_from"]) if obj["valid_from"] else None,
                "valid_until_us": _us(obj["valid_until"]) if obj["valid_until"] else None,
            })
        if kind in ("binding", "confirmation", "consent"):
            columns["memory_id"] = obj["memory_id"]
        if kind == "binding":
            columns["registry_version"] = obj["registry_version"]
        columns["payload_json"] = _canonical({k: v for k, v in obj.items() if k not in _META_KEYS})
        self.conn.execute(
            f"INSERT INTO {_TABLES[kind]} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(columns.values()),
        )
        for role, items in (refs or {}).items():
            for index, ref in enumerate(items):
                self.conn.execute(
                    "INSERT INTO v1_object_refs VALUES (?,?,?,?,?,?)",
                    (obj["id"], role, index, ref["id"], ref["type"], ref["version"]),
                )

    @staticmethod
    def _object(row: sqlite3.Row) -> dict[str, Any]:
        return {key: row[key] for key in _META_KEYS} | json.loads(row["payload_json"])

    def _resolve(self, user_id: str, request_id: str, ref: Any, now: datetime) -> dict[str, Any]:
        c.validate_ref(ref)
        _text(ref["id"], "reference id")
        table = _TABLES[ref["type"]]
        row = self.conn.execute(
            f"""SELECT o.*,t.payload_json FROM v1_objects o JOIN {table} t ON t.id=o.id
                WHERE o.id=? AND o.object_type=? AND o.user_id=?
                    AND (o.request_id=? OR o.request_id IS NULL)""",
            (ref["id"], ref["type"], user_id, request_id),
        ).fetchone()
        if row is None:
            raise _fail("not_found", "referenced object not found")
        if row["version"] != ref["version"]:
            raise _fail("version_conflict", "referenced object version does not match")
        if row["retention_us"] <= _us(now):
            raise _fail("stale_context", "referenced object has expired")
        return self._object(row)

    def _update(self, kind: str, obj: dict[str, Any], *, bump: bool = True) -> dict[str, Any]:
        if kind == "candidate_set":
            raise _fail("invalid_input", "published candidate sets are immutable")
        obj = dict(obj)
        if bump:
            obj["version"] += 1
        self.conn.execute("UPDATE v1_objects SET version=? WHERE id=?", (obj["version"], obj["id"]))
        self.conn.execute(
            f"UPDATE {_TABLES[kind]} SET payload_json=? WHERE id=?",
            (_canonical({k: v for k, v in obj.items() if k not in _META_KEYS}), obj["id"]),
        )
        if kind == "memory":
            self.conn.execute("UPDATE v1_memories SET status=? WHERE id=?", (obj["status"], obj["id"]))
        return obj

    @staticmethod
    def _meaning(memory: dict[str, Any], scope: str | None = None) -> dict[str, Any]:
        return {key: memory[key] for key in c.MemoryContent.__required_keys__} | {
            "scope": scope or memory["scope"],
        }

    @staticmethod
    def _spec(binding: dict[str, Any]) -> dict[str, Any]:
        keys = c.PIBindingSpec.__required_keys__ if binding["domain"] == "PI" else c.FEABindingSpec.__required_keys__
        return {key: binding[key] for key in keys}

    def _bindings(self, memory_id: str) -> list[dict[str, Any]]:
        return [self._object(row) for row in self.conn.execute(
            """SELECT o.*,b.payload_json FROM v1_objects o JOIN v1_bindings b ON b.id=o.id
                WHERE b.memory_id=? ORDER BY o.created_at,o.id""", (memory_id,),
        )]

    @staticmethod
    def _live(ref: dict[str, Any], obj: dict[str, Any], now: datetime, *, removing: bool = False) -> None:
        if removing:
            return  # ownership, version and retention are still checked by _resolve
        if ref["type"] in ("memory", "binding") and obj["status"] not in ("candidate", "active"):
            raise _fail("stale_context", "reviewed object is no longer usable")
        if ref["type"] == "memory" and (
            "legacy" in obj
            or (obj["valid_from"] and _us(obj["valid_from"]) > _us(now))
            or (obj["valid_until"] and _us(obj["valid_until"]) <= _us(now))
        ):
            raise _fail("stale_context", "memory is not currently usable")
        if ref["type"] == "consent" and obj["status"] != "active":
            raise _fail("stale_context", "consent has been withdrawn")

    def _memory(self, request: sqlite3.Row, action: dict[str, Any], now: datetime) -> dict[str, Any]:
        _text(action["memory_id"], "memory_id")
        ref = {"type": "memory", "id": action["memory_id"], "version": action["expected_version"]}
        obj = self._resolve(request["user_id"], request["id"], ref, now)
        self._live(ref, obj, now, removing=action['op'] in ('withdraw', 'delete'))
        if (request["status"] != "open" and obj["scope"] == "short_term"
            and action["op"] not in ("confirm", "confirm_bindings", "promote", "withdraw", "delete")):
            raise _fail("request_closed", "closed requests only allow review/reuse/removal of existing content")
        return obj

    def _check_basis(self, request: sqlite3.Row, basis: Any, now: datetime, *, catalog_freshness: Any = None,
                     check_catalog: bool = False, removing: bool = False) -> None:
        _shape(basis, c.Basis.__required_keys__, "basis")
        expected = {key: basis[key] for key in c.Expected.__required_keys__}
        self._expected(expected, None, None)
        if (basis["request_id"] != request["id"] or basis["contract_version"] != c.CONTRACT_VERSION
            or basis["registry_version"] != request["registry_version"]):
            raise _fail("stale_context", "review basis does not match the request contract")
        if (basis["request_revision"] != request["revision"]
            or basis["profile_revision"] != self.store._profile_revision(request["user_id"])):
            raise _fail("stale_context", "review basis has changed")
        if basis["index_version"] is not None:
            _text(basis["index_version"], "index_version")
        expiry = _parse_datetime(basis["valid_until"], "basis.valid_until")
        if expiry is not None and expiry <= now:
            raise _fail("stale_context", "review basis has expired")
        for ref in basis["object_versions"]:
            obj = self._resolve(request["user_id"], request["id"], ref, now)
            self._live(ref, obj, now, removing=removing)
        if basis["catalog"] is not None:
            from .store_feedback import _catalog_versions

            _catalog_versions(basis["catalog"])
            if check_catalog:
                self.feedback.check_catalog(basis["catalog"], catalog_freshness)

    def issue_display(self, user_id: str, request_id: str, *, purpose: str,
                      snapshot: Any, basis: Any) -> dict[str, Any]:
        """Trusted-service boundary: persist a review, never import a client proof."""
        _text(user_id, "user_id")
        _text(request_id, "request_id")
        if purpose not in get_args(c.ReviewPurpose):
            raise _fail("invalid_input", "unsupported review purpose")
        _shape(snapshot, c.ReviewSnapshot.__required_keys__, "review snapshot")
        _batch_size({"snapshot": snapshot, "basis": basis})
        now = self.store._now()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            request = self._request(user_id, request_id, include_closed=True)
            self._check_basis(request, basis, now, removing=purpose in ('withdraw', 'delete'))
            meaning = _shape(snapshot["meaning"], c.MemoryMeaning.__required_keys__, "review meaning")
            self._memory_content({k: meaning[k] for k in c.MemoryContent.__required_keys__}, request)
            if meaning["scope"] not in ("short_term", "long_term"):
                raise _fail("invalid_input", "invalid review scope")
            if meaning["scope"] == "long_term" and meaning["selector"]["slot_id"] is not None:
                raise _fail("invalid_input", "long-term review cannot contain a request slot")
            self._binding_specs(request, meaning, snapshot["bindings"], confirmed=True)
            refs = _list(snapshot["subject_refs"], "review subjects", 64, nonempty=True)
            expected_refs = {_canonical(ref) for ref in basis["object_versions"]}
            if len({_canonical(ref) for ref in refs}) != len(refs):
                raise _fail("invalid_input", "duplicate review subject")
            subjects = []
            retention = [request["retention_until"]]
            for ref in refs:
                obj = self._resolve(user_id, request_id, ref, now)
                self._live(ref, obj, now, removing=purpose in ('withdraw', 'delete'))
                if _canonical(ref) not in expected_refs:
                    raise _fail("invalid_input", "review subjects must be in its basis")
                subjects.append((ref, obj))
                retention.append(obj["retention_until"])
                if ref["type"] == "memory" and obj["valid_until"]:
                    retention.append(obj["valid_until"])
            self.feedback.review_dependencies(request, snapshot, basis, now, purpose=purpose)
            memories = [obj for ref, obj in subjects if ref["type"] == "memory"]
            if purpose not in ("replace", "future_reuse"):
                for obj in memories:
                    scope = "long_term" if purpose == "future_reuse" else obj["scope"]
                    if self._meaning(obj, scope) != meaning:
                        raise _fail("invalid_user_event", "review meaning differs from its subject")
            if purpose == "future_reuse" and meaning["scope"] != "long_term":
                raise _fail("consent_required", "future reuse requires a separate long-term snapshot")
            if request["status"] != "open" and meaning["scope"] == "short_term" and purpose not in ("confirm_content", "confirm_bindings", "withdraw", "delete"):
                raise _fail("request_closed", "closed content may only be reviewed or removed")
            for ref, obj in subjects:
                if ref["type"] == "binding":
                    if self._spec(obj) not in snapshot["bindings"] or obj["memory_id"] not in {m["id"] for m in memories}:
                        raise _fail("invalid_user_event", "binding review must show its exact value and memory")
            if basis["valid_until"] is not None:
                retention.append(basis["valid_until"])
            display = self._metadata(user_id, request_id, now, min(retention, key=_us)) | {
                "purpose": purpose, "snapshot": snapshot, "basis": basis,
            }
            self._put("display", display, {"subject": refs, "basis": basis["object_versions"]})
            self.store._call_failure_hook("review_before_commit")
            self.conn.commit()
            return display
        except StyleMateError:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise _fail("storage_failed", "review display was rolled back") from exc

    def record_user_event(self, user_id: str, request_id: str, *, command_id: str,
                          display_ref: Any, purpose: str, expected: Any) -> dict[str, Any]:
        """Call only for an explicit accept; decline/skip never call this method."""
        for key, value in (("user_id", user_id), ("request_id", request_id), ("command_id", command_id)):
            _text(value, key)
        c.validate_ref(display_ref)
        if display_ref["type"] != "display" or purpose not in get_args(c.ReviewPurpose):
            raise _fail("invalid_user_event", "event requires a server-issued display and purpose")
        self._expected(expected, None, None)
        now = self.store._now()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            request = self._request(user_id, request_id, include_closed=True)
            prior = self.conn.execute(
                """SELECT o.*,e.payload_json FROM v1_objects o JOIN v1_user_events e ON e.id=o.id
                    WHERE o.user_id=? AND json_extract(e.payload_json,'$.command_id')=?""", (user_id, command_id),
            ).fetchone()
            if prior is not None:
                event = self._object(prior)
                if event["request_id"] != request_id or event["display_ref"] != display_ref or event["purpose"] != purpose:
                    raise _fail("idempotency_conflict", "command_id was used for another user event")
                self.conn.commit()
                return _ref("event", event)
            display = self._resolve(user_id, request_id, display_ref, now)
            if display["request_id"] != request_id or display["purpose"] != purpose:
                raise _fail("invalid_user_event", "display ownership or purpose does not match")
            self._check_basis(request, display["basis"], now, removing=purpose in ('withdraw', 'delete'))
            if (expected["request_revision"] != request["revision"]
                or expected["profile_revision"] != self.store._profile_revision(user_id)):
                raise _fail("version_conflict", "user event expected revisions do not match")
            for ref in expected["object_versions"]:
                self._resolve(user_id, request_id, ref, now)
            event = self._metadata(user_id, request_id, now, display["retention_until"]) | {
                "purpose": purpose, "display_ref": display_ref, "command_id": command_id,
            }
            self._put("event", event, {"display": [display_ref]})
            self.store._call_failure_hook("user_event_before_commit")
            self.conn.commit()
            return _ref("event", event)
        except StyleMateError:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise _fail("storage_failed", "user event was rolled back") from exc

    def _review_events(self, request: sqlite3.Row, actions: list[Any], now: datetime,
                       catalog_freshness: Any) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        """Validate every event against the batch START state, before mutations."""
        result = {}
        for action in actions:
            if not isinstance(action, dict):
                raise _fail("invalid_input", "each action must be an object")
            for key in ("confirmation_event_ref", "consent_event_ref", "user_event_ref"):
                ref = action.get(key)
                if ref is None:
                    continue
                c.validate_ref(ref)
                if ref["type"] != "event":
                    raise _fail("invalid_user_event", "review proof must be a trusted event")
                event = self._resolve(request["user_id"], request["id"], ref, now)
                if event["request_id"] != request["id"]:
                    raise _fail("invalid_user_event", "event belongs to another request")
                if self.conn.execute("SELECT 1 FROM v1_event_uses WHERE event_id=?", (event["id"],)).fetchone():
                    raise _fail("invalid_user_event", "event was already applied")
                display = self._resolve(request["user_id"], request["id"], event["display_ref"], now)
                if display["purpose"] != event["purpose"]:
                    raise _fail("invalid_user_event", "event and display purposes differ")
                removing = event['purpose'] in ('withdraw', 'delete')
                self._check_basis(request, display["basis"], now, catalog_freshness=catalog_freshness,
                                  check_catalog=not removing, removing=removing)
                result[event["id"]] = (event, display)
        return result

    def _proof(self, events: dict[str, Any], ref: Any, purpose: str, meaning: dict[str, Any],
               *, subject_id: str | None = None, specs: list[Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
        code = "consent_required" if purpose == "future_reuse" else "confirmation_required"
        if ref is None:
            raise _fail(code, "a separate trusted review event is required")
        c.validate_ref(ref)
        proof = events.get(ref["id"])
        if proof is None or proof[0]["purpose"] != purpose or proof[1]["snapshot"]["meaning"] != meaning:
            raise _fail("invalid_user_event", "event purpose or reviewed meaning does not match")
        snapshot = proof[1]["snapshot"]
        if subject_id is not None and not any(r["type"] == "memory" and r["id"] == subject_id for r in snapshot["subject_refs"]):
            raise _fail("invalid_user_event", "event does not review this memory")
        if specs is not None and sorted(map(_canonical, snapshot["bindings"])) != sorted(map(_canonical, specs)):
            raise _fail("invalid_user_event", "reviewed bindings differ from the operation")
        return proof

    def _consume(self, proof: tuple[dict[str, Any], dict[str, Any]]) -> None:
        event_id = proof[0]["id"]
        if self.conn.execute("SELECT 1 FROM v1_event_uses WHERE event_id=?", (event_id,)).fetchone():
            raise _fail("invalid_user_event", "event cannot authorize multiple operations")
        self.conn.execute("INSERT INTO v1_event_uses VALUES (?)", (event_id,))

    def _expected(
        self, expected: Any, expected_request_revision: int | None, expected_profile_revision: int | None,
    ) -> dict[str, Any]:
        _shape(expected, c.Expected.__required_keys__, "expected")
        for key, minimum, compatibility in (
            ("request_revision", 1, expected_request_revision),
            ("profile_revision", 0, expected_profile_revision),
        ):
            if type(expected[key]) is not int or expected[key] < minimum:
                raise _fail("invalid_input", "expected revisions must be integers")
            if compatibility is not None and (type(compatibility) is not int or compatibility != expected[key]):
                raise _fail("invalid_input", "legacy and v1 expected revisions disagree")
        seen = set()
        for ref in _list(expected["object_versions"], "object_versions", 256):
            c.validate_ref(ref)
            _text(ref["id"], "reference id")
            key = (ref["type"], ref["id"])
            if key in seen:
                raise _fail("invalid_input", "duplicate object_versions entry")
            seen.add(key)
        return expected

    def start_request(
        self, user_id: str, *, input_id: str, text: str | None, timezone: str,
        contract_version: str, registry_version: str | None, mode: str, targets: Any,
    ) -> dict[str, Any]:
        if contract_version != c.CONTRACT_VERSION or registry_version != c.V1_REGISTRY_VERSION:
            raise _fail("unsupported_contract", "v1 requires explicit storage and registry contracts")
        _text(user_id, "user_id")
        _text(input_id, "input_id")
        if text is not None:
            _text(text, "text", 4000)
        _text(timezone, "timezone")
        try:
            ZoneInfo(timezone)
        except (ValueError, KeyError):
            raise _fail("invalid_input", "timezone must be a valid IANA timezone") from None
        if mode not in ("shopping", "onboarding"):
            raise _fail("invalid_input", "unsupported request mode")
        targets = [] if targets is None else targets
        if not isinstance(targets, list):
            raise _fail("invalid_input", "targets must be an array")
        seen = set()
        for target in targets:
            _shape(target, c.TargetSpec.__required_keys__, "target")
            _text(target["target_id"], "target_id")
            _text(target["garment_type"], "garment_type")
            if target["target_id"] in seen:
                raise _fail("invalid_input", "duplicate target_id")
            seen.add(target["target_id"])
        payload = {"text": text, "timezone": timezone, "mode": mode, "targets": targets,
                   "contract_version": contract_version, "registry_version": registry_version}
        c.batch_fingerprint(contract_version, "start_request", [payload])
        fingerprint = _digest(payload)
        now = self.store._now()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.store._ensure_profile(user_id)
            self.store._purge_expired_nonces(user_id, now)
            self.store._assert_input_not_tombstoned(user_id, input_id, now)
            existing = self.conn.execute(
                "SELECT * FROM requests WHERE user_id=? AND input_id=?", (user_id, input_id)
            ).fetchone()
            if existing is not None:
                self.check_contract(existing, contract_version)
                if _us(existing["retention_until"]) <= _us(now) or existing["status"] == "expired":
                    raise _fail("request_expired", "input_id belongs to an expired request")
                if existing["input_digest"] != fingerprint:
                    raise _fail("idempotency_conflict", "input_id was already used with a different body")
                result = self.request_dict(existing)
            else:
                request_id = _new_id()
                self.conn.execute(
                    """INSERT INTO requests
                    (id,user_id,input_id,input_digest,timezone,revision,created_at,updated_at,status,
                     retention_until,max_until,contract_version,registry_version,mode,targets_json)
                    VALUES (?,?,?,?,?,1,?,?,'open',?,?,?,?,?,?)""",
                    (request_id, user_id, input_id, fingerprint, timezone, _iso(now), _iso(now),
                     _iso(now + _REQUEST_INACTIVITY), _iso(now + _REQUEST_MAX_AGE),
                     contract_version, registry_version, mode, _canonical(targets)),
                )
                result = self.request_dict(self.store._request_row(user_id, request_id))
            # Only the digest is stored here. Text intake uses submit_feedback,
            # so creating a request and submitting its first input cannot duplicate evidence.
            self.conn.commit()
            return result
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def _memory_content(self, memory: Any, request: sqlite3.Row) -> dict[str, Any]:
        _shape(memory, c.MemoryContent.__required_keys__, "memory")
        _text(memory["content"], "content", 4000)
        if memory["kind"] not in ("preference", "requirement", "situation"):
            raise _fail("invalid_input", "unsupported memory kind")
        if memory["polarity"] not in ("prefer", "avoid", "require", "indifferent"):
            raise _fail("invalid_input", "unsupported memory polarity")
        if memory["strength"] not in ("soft", "hard"):
            raise _fail("invalid_input", "unsupported memory strength")
        if memory["polarity"] == "indifferent" and memory["strength"] != "soft":
            raise _fail("invalid_input", "indifferent must be soft")
        selector = _shape(memory["selector"], c.Selector.__required_keys__, "selector")
        for key, value in selector.items():
            if value is not None:
                _text(value, key)
        if selector["slot_id"] is not None:
            target = next((t for t in json.loads(request["targets_json"])
                           if t["target_id"] == selector["slot_id"]), None)
            if target is None or selector["garment_type"] != target["garment_type"]:
                raise _fail("invalid_input", "selector does not match a request target")
        conditions = memory["conditions"]
        if not isinstance(conditions, dict) or set(conditions) - {"occasion", "activity", "goal"}:
            raise _fail("invalid_input", "conditions must use occasion, activity or goal")
        for value in conditions.values():
            _text(value, "condition", 4000)
        fact = memory["fact"]
        if fact is not None:
            _shape(fact, c.Fact.__required_keys__, "fact")
            if memory["kind"] != "situation" or fact["key"] not in ("occasion", "activity", "goal"):
                raise _fail("invalid_input", "fact requires a situation and a supported key")
            _text(fact["value"], "fact value", 4000)
        start = _parse_datetime(memory["valid_from"], "valid_from")
        end = _parse_datetime(memory["valid_until"], "valid_until")
        if start is not None and end is not None and end <= start:
            raise _fail("invalid_input", "memory validity must be a nonempty half-open interval")
        return memory

    def _sources(self, request: sqlite3.Row, refs: Any, now: datetime) -> list[dict[str, Any]]:
        user_id, request_id = request["user_id"], request["id"]
        refs = _list(refs, "source_refs", 64, nonempty=True)
        sources = []
        seen = set()
        for ref in refs:
            source = self._resolve(user_id, request_id, ref, now)
            if ref["type"] not in ("evidence", "memory"):
                raise _fail("invalid_input", "memory sources must be evidence or memory")
            if (ref["type"], ref["id"]) in seen:
                raise _fail("invalid_input", "duplicate source reference")
            seen.add((ref["type"], ref["id"]))
            if ref["type"] == "memory":
                if (source["status"] not in ("candidate", "active") or "legacy" in source
                    or (source["valid_from"] and _us(source["valid_from"]) > _us(now))
                    or (source["valid_until"] and _us(source["valid_until"]) <= _us(now))):
                    raise _fail("stale_context", "source memory is not usable")
            sources.append(source)
        return sources

    def _binding_specs(self, request: sqlite3.Row, memory: dict[str, Any], bindings: Any,
                       *, confirmed: bool = False) -> list[dict[str, Any]]:
        bindings = _list(bindings, "bindings", 16)
        registry = load_registry(request["registry_version"]) if bindings else None
        binding_keys = set()
        for spec in bindings:
            registry.validate_binding(spec, memory["selector"]["garment_type"])
            if spec["domain"] == "PI":
                if spec["values"] is not None:
                    _list(spec["values"], "PI values", 32, nonempty=True)
                    for value in spec["values"]:
                        _text(value, "PI value")
            if spec["polarity"] != memory["polarity"]:
                raise _fail("invalid_input", "binding polarity disagrees with its memory")
            if not confirmed and (spec["strength"] != "soft" or spec["polarity"] == "indifferent"):
                raise _fail("confirmation_required", "unconfirmed bindings can only be soft interpretations")
            if spec["strength"] == "hard" and memory["strength"] != "hard":
                raise _fail("invalid_input", "binding strength exceeds its memory")
            key = _canonical(spec)
            if key in binding_keys:
                raise _fail("invalid_input", "duplicate binding")
            binding_keys.add(key)
        return bindings

    def _new_bindings(self, request: sqlite3.Row, memory: dict[str, Any], specs: list[Any],
                      refs: list[Any], now: datetime, *, origin: str = "inferred") -> list[dict[str, Any]]:
        bindings = []
        for spec in specs:
            binding = self._metadata(memory["user_id"], memory["request_id"], now, memory["retention_until"]) | spec | {
                "subject": "user_target", "memory_id": memory["id"],
                "registry_version": request["registry_version"], "origin": origin,
                "confirmed": False, "status": "candidate", "source_refs": refs,
                "confirmation_ref": None,
            }
            self._put("binding", binding, {"source": refs, "memory": [_ref("memory", memory)]})
            bindings.append(binding)
        return bindings

    def _confirmation(self, memory: dict[str, Any], bindings: list[dict[str, Any]],
                      proof: tuple[dict[str, Any], dict[str, Any]], now: datetime,
                      *, bump_memory: bool = True, bump_bindings: bool = True) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        event, display = proof
        confirmation = self._metadata(memory["user_id"], memory["request_id"], now, memory["retention_until"]) | {
            "memory_id": memory["id"], "snapshot": display["snapshot"],
            "source_refs": memory["source_refs"], "event_ref": _ref("event", event), "confirmed_at": event["created_at"],
        }
        self._put("confirmation", confirmation, {"memory": [_ref("memory", memory)],
            "source": memory["source_refs"], "event": [confirmation["event_ref"]]})
        changed = [_ref("confirmation", confirmation)]
        if event["purpose"] in ("confirm_content", "replace"):
            memory = self._update("memory", memory | {
                "confirmed": True, "status": "active", "confirmation_ref": _ref("confirmation", confirmation),
            }, bump=bump_memory)
            changed.append(_ref("memory", memory))
        for binding in bindings:
            binding = self._update("binding", binding | {
                "confirmed": True, "status": "active", "confirmation_ref": _ref("confirmation", confirmation),
            }, bump=bump_bindings)
            changed.append(_ref("binding", binding))
        return memory, changed

    def _create(self, request: sqlite3.Row, action: dict[str, Any], now: datetime,
                events: dict[str, Any], *, confirmation_purpose: str = "confirm_content") -> list[dict[str, Any]]:
        _shape(action, c.CreateAction.__required_keys__, action["op"])
        memory = self._memory_content(action["memory"], request)
        refs = action["source_refs"]
        sources = self._sources(request, refs, now)
        scope = "long_term" if action["op"] == "create_long_term" else "short_term"
        meaning = memory | {"scope": scope}
        confirmation = None
        if action["confirmation_event_ref"] is not None or scope == "long_term":
            confirmation = self._proof(events, action["confirmation_event_ref"], confirmation_purpose, meaning,
                                       specs=action["bindings"])
        specs = self._binding_specs(request, memory, action["bindings"], confirmed=confirmation is not None)
        if confirmation is not None:
            subjects = confirmation[1]["snapshot"]["subject_refs"]
            if any(ref not in subjects for ref in refs):
                raise _fail("invalid_user_event", "creation sources were not reviewed")
        if scope == "long_term":
            if memory["selector"]["slot_id"] is not None:
                raise _fail("invalid_input", "long-term memory cannot contain a request slot")
            consent = self._proof(events, action["consent_event_ref"], "future_reuse", meaning, specs=specs)
            if request["status"] != "open" and not any(
                ref["type"] == "memory" and source["confirmed"] and source["status"] == "active"
                and self._meaning(source, "long_term") == meaning for ref, source in zip(refs, sources)
            ):
                raise _fail("request_closed", "closed requests only reuse already confirmed content")
            self._consume(confirmation)
            self._consume(consent)
            return self._long_term(request, memory, specs, confirmation, consent, now)
        if request["status"] != "open":
            raise _fail("request_closed", "short-term creation requires an open request")
        if action["consent_event_ref"] is not None:
            raise _fail("invalid_user_event", "short-term creation cannot consume future-reuse consent")
        retention = min([request["retention_until"], _iso(now + _REQUEST_INACTIVITY)]
                        + [source["retention_until"] for source in sources], key=_us)
        obj = self._metadata(request["user_id"], request["id"], now, retention) | memory | {
            "scope": "short_term", "origin": "inferred", "confirmed": False,
            "status": "candidate", "source_refs": refs, "confirmation_ref": None,
            "consent_ref": None, "family_id": _new_id(),
        }
        self._put("memory", obj, {"source": refs})
        bindings = self._new_bindings(request, obj, specs, refs, now)
        changed = [_ref("memory", obj)] + [_ref("binding", b) for b in bindings]
        if confirmation is not None:
            self._consume(confirmation)
            event, display = confirmation
            # Creation reviews show exact binding specs before their IDs exist.
            # Attach the IDs assigned in this transaction to the confirmation
            # snapshot, keeping the issued display and reviewed specs immutable.
            creation_display = display | {"snapshot": display["snapshot"] | {
                "subject_refs": display["snapshot"]["subject_refs"] + [_ref("binding", b) for b in bindings]}}
            _, confirmed_refs = self._confirmation(obj, bindings, (event, creation_display), now, bump_memory=False, bump_bindings=False)
            changed.extend(confirmed_refs)
        return changed

    def _independent_proof(self, request: sqlite3.Row, memory: dict[str, Any], specs: list[Any],
                           subjects: list[Any], proof: tuple[dict[str, Any], dict[str, Any]],
                           now: datetime) -> tuple[dict[str, Any], dict[str, Any]]:
        """Copy only the reviewed meaning; no FK to a source request or its logs."""
        original_event, _ = proof
        snapshot = {"meaning": self._meaning(memory), "bindings": specs, "subject_refs": subjects}
        # The original request identifier is historical metadata, never a required FK.
        # Independent reviews are not accepted as fresh UI events by _review_events.
        basis = {
            "request_id": request["id"], "contract_version": c.CONTRACT_VERSION,
            "registry_version": request["registry_version"], "index_version": None, "catalog": None,
            "request_revision": request["revision"], "profile_revision": self.store._profile_revision(memory["user_id"]),
            "object_versions": subjects, "valid_until": memory["valid_until"],
        }
        display = self._metadata(memory["user_id"], None, now, memory["retention_until"]) | {
            "purpose": original_event["purpose"], "snapshot": snapshot, "basis": basis,
        }
        self._put("display", display, {"subject": subjects})
        event = self._metadata(memory["user_id"], None, now, memory["retention_until"]) | {
            "purpose": original_event["purpose"], "display_ref": _ref("display", display), "command_id": _new_id(),
        }
        # Preserve the time of the actual user action instead of manufacturing a later acceptance.
        event["created_at"] = original_event["created_at"]
        self._put("event", event, {"display": [event["display_ref"]]})
        self._consume((event, display))
        return event, display

    def _long_term(self, request: sqlite3.Row, content: dict[str, Any], specs: list[Any],
                   confirmation: tuple[dict[str, Any], dict[str, Any]], consent: tuple[dict[str, Any], dict[str, Any]],
                   now: datetime, *, source: dict[str, Any] | None = None,
                   source_bindings: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        retention = _iso(now + _LONG_TERM_RETENTION)
        if content["valid_until"] is not None:
            retention = min(retention, content["valid_until"], key=_us)
        obj = self._metadata(request["user_id"], None, now, retention) | content | {
            "scope": "long_term", "origin": source["origin"] if source else "explicit",
            "confirmed": False, "status": "candidate", "source_refs": [],
            "confirmation_ref": None, "consent_ref": None,
            "family_id": source["family_id"] if source else _new_id(),
        }
        self._put("memory", obj)
        content_specs = [spec for spec in confirmation[1]["snapshot"]["bindings"] if spec in specs]
        independent_confirmation = self._independent_proof(request, obj, content_specs, [_ref("memory", obj)], confirmation, now)
        independent_consent = self._independent_proof(request, obj, specs, [_ref("memory", obj)], consent, now)
        evidence = self._metadata(request["user_id"], None, now, retention) | {
            "kind": "consent_snapshot", "quote": None, "context": None, "selector": content["selector"],
            "selection": None, "display_ref": _ref("display", independent_consent[1]), "snapshot": self._meaning(obj),
        }
        self._put("evidence", evidence, {"display": [evidence["display_ref"]]})
        obj["source_refs"] = [_ref("evidence", evidence)]
        self.conn.execute("INSERT INTO v1_object_refs VALUES (?, 'source', 0, ?, 'evidence', 1)", (obj["id"], evidence["id"]))
        obj = self._update("memory", obj, bump=False)
        bindings = self._new_bindings(request, obj, specs, obj["source_refs"], now)
        # Direct long-term creation explicitly reviews all supplied bindings. Promotion
        # preserves each existing binding's inferred/confirmed state separately.
        confirmed_bindings = bindings if source_bindings is None else []
        obj, changed = self._confirmation(obj, confirmed_bindings, independent_confirmation, now,
                                          bump_memory=False, bump_bindings=False)
        for binding, original in zip(bindings, source_bindings or []):
            binding = self._update("binding", binding | {"origin": original["origin"]}, bump=False)
            if original["confirmed"]:
                original_confirmation = self._resolve(request["user_id"], request["id"], original["confirmation_ref"], now)
                event = self._resolve(request["user_id"], request["id"], original_confirmation["event_ref"], now)
                display = self._resolve(request["user_id"], request["id"], event["display_ref"], now)
                binding_proof = self._independent_proof(request, obj, [self._spec(binding)],
                    [_ref("memory", obj), _ref("binding", binding)], (event | {"purpose": "confirm_bindings"}, display), now)
                _, binding_refs = self._confirmation(obj, [binding], binding_proof, now, bump_bindings=False)
                changed.extend(binding_refs)
        consent_obj = self._metadata(request["user_id"], None, now, retention) | {
            "memory_id": obj["id"], "purpose": "future_reuse", "snapshot": independent_consent[1]["snapshot"],
            "source_refs": obj["source_refs"], "event_ref": _ref("event", independent_consent[0]),
            "consented_at": independent_consent[0]["created_at"], "status": "active",
        }
        self._put("consent", consent_obj, {"memory": [_ref("memory", obj)], "source": obj["source_refs"],
            "event": [consent_obj["event_ref"]]})
        obj = self._update("memory", obj | {"consent_ref": _ref("consent", consent_obj)}, bump=False)
        changed.extend([_ref("evidence", evidence), _ref("consent", consent_obj)] + [_ref("binding", b) for b in bindings])
        if source is not None:
            changed.append(self._link(request, obj, source, "promoted_from", now))
        self.store._call_failure_hook("long_term_after_snapshots")
        return changed

    def _link(self, request: sqlite3.Row, source: dict[str, Any], target: dict[str, Any],
              relation: str, now: datetime) -> dict[str, Any]:
        """Store the directed statement: source relation target."""
        link = self._metadata(request["user_id"], request["id"], now,
            min(request["retention_until"], source["retention_until"], target["retention_until"], key=_us)) | {
            "relation": relation, "source_ref": _ref("memory", source), "target_ref": _ref("memory", target),
        }
        self._put("link", link, {"source": [link["source_ref"]], "target": [link["target_ref"]]})
        return _ref("link", link)

    def _confirm(self, request: sqlite3.Row, action: dict[str, Any], now: datetime,
                 events: dict[str, Any]) -> list[dict[str, Any]]:
        _shape(action, c.ConfirmAction.__required_keys__, action["op"])
        memory = self._memory(request, action, now)
        self._sources(request, memory["source_refs"], now)
        purpose = "confirm_bindings" if action["op"] == "confirm_bindings" else "confirm_content"
        if purpose == "confirm_bindings" and not memory["confirmed"]:
            raise _fail("confirmation_required", "confirm the memory content separately first")
        refs = _list(action["binding_confirmations"], "binding confirmations", 16,
                     nonempty=purpose == "confirm_bindings")
        if len({_canonical(ref) for ref in refs}) != len(refs):
            raise _fail("invalid_input", "duplicate binding confirmation")
        bindings = []
        proof = self._proof(events, action["confirmation_event_ref"], purpose, self._meaning(memory), subject_id=memory["id"])
        for ref in refs:
            binding = self._resolve(request["user_id"], request["id"], ref, now)
            if ref["type"] != "binding" or binding["memory_id"] != memory["id"]:
                raise _fail("invalid_user_event", "binding belongs to another memory")
            self._live(ref, binding, now)
            self._sources(request, binding["source_refs"], now)
            if ref not in proof[1]["snapshot"]["subject_refs"] or self._spec(binding) not in proof[1]["snapshot"]["bindings"]:
                raise _fail("invalid_user_event", "binding ID/version and exact value were not shown")
            bindings.append(binding)
        self._consume(proof)
        if memory["scope"] == "long_term":
            proof = self._independent_proof(request, memory, [self._spec(b) for b in bindings],
                [_ref("memory", memory)] + refs, proof, now)
        _, changed = self._confirmation(memory, bindings, proof, now)
        return changed

    def _propose_bindings(self, request: sqlite3.Row, action: dict[str, Any], now: datetime) -> list[dict[str, Any]]:
        _shape(action, c.ProposeBindingsAction.__required_keys__, "propose_bindings")
        memory = self._memory(request, action, now)
        specs = self._binding_specs(request, memory, action["bindings"])
        sources = self._sources(request, action["source_refs"], now)
        if memory["scope"] == "long_term" and any(source["request_id"] is not None for source in sources):
            raise _fail("consent_required", "long-term interpretations must use independent long-term sources")
        existing = {_canonical(self._spec(b)) for b in self._bindings(memory["id"]) if b["status"] in ("candidate", "active")}
        specs = [spec for spec in specs if _canonical(spec) not in existing]
        if not specs:
            return []
        bindings = self._new_bindings(request, memory, specs, action["source_refs"], now)
        # Proposals cannot prolong the lifetime of their sources.
        for binding in bindings:
            retention = min([binding["retention_until"]] + [source["retention_until"] for source in sources], key=_us)
            self.conn.execute("UPDATE v1_objects SET retention_until=?,retention_us=? WHERE id=?",
                              (retention, _us(retention), binding["id"]))
        return [_ref("binding", binding) for binding in bindings]

    def _promote(self, request: sqlite3.Row, action: dict[str, Any], now: datetime,
                 events: dict[str, Any]) -> list[dict[str, Any]]:
        _shape(action, c.PromoteAction.__required_keys__, "promote")
        memory = self._memory(request, action, now)
        if memory["scope"] != "short_term" or memory["status"] != "active" or not memory["confirmed"]:
            raise _fail("confirmation_required", "promotion requires an active confirmed short-term memory")
        if memory["selector"]["slot_id"] is not None:
            raise _fail("invalid_input", "promotion cannot remove a request slot")
        self._sources(request, memory["source_refs"], now)
        bindings = [b for b in self._bindings(memory["id"]) if b["status"] in ("candidate", "active")]
        for binding in bindings:
            self._live(_ref("binding", binding), binding, now)
            self._sources(request, binding["source_refs"], now)
        specs = [self._spec(b) for b in bindings]
        consent = self._proof(events, action["consent_event_ref"], "future_reuse", self._meaning(memory, "long_term"),
                              subject_id=memory["id"], specs=specs)
        confirmation_obj = self._resolve(request["user_id"], request["id"], memory["confirmation_ref"], now)
        event = self._resolve(request["user_id"], request["id"], confirmation_obj["event_ref"], now)
        display = self._resolve(request["user_id"], request["id"], event["display_ref"], now)
        # Content confirmation may predate a binding edit; only its immutable meaning is reused.
        if confirmation_obj["snapshot"]["meaning"] != self._meaning(memory):
            raise _fail("invalid_user_event", "content confirmation no longer matches")
        self._consume(consent)
        return self._long_term(request, {k: memory[k] for k in c.MemoryContent.__required_keys__}, specs,
                               (event, display), consent, now, source=memory, source_bindings=bindings)

    def _replace(self, request: sqlite3.Row, action: dict[str, Any], now: datetime,
                 events: dict[str, Any]) -> list[dict[str, Any]]:
        _shape(action, c.ReplaceAction.__required_keys__, "replace")
        old = self._memory(request, action, now)
        if not old["confirmed"] or old["status"] != "active":
            raise _fail("confirmation_required", "replacement requires an active confirmed memory")
        content = self._memory_content(action["memory"], request)
        meaning = content | {"scope": old["scope"]}
        specs = self._binding_specs(request, content, action["bindings"], confirmed=True)
        self._sources(request, action["source_refs"], now)
        proof = self._proof(events, action["confirmation_event_ref"], "replace", meaning,
                            subject_id=old["id"], specs=specs)
        if any(ref not in proof[1]["snapshot"]["subject_refs"] for ref in action["source_refs"]):
            raise _fail("invalid_user_event", "replacement sources were not reviewed")
        if old["scope"] == "long_term":
            if content["selector"]["slot_id"] is not None:
                raise _fail("invalid_input", "long-term replacement cannot introduce a request slot")
            consent = self._proof(events, action["consent_event_ref"], "future_reuse", meaning, specs=specs)
            self._consume(proof)
            self._consume(consent)
            changed = self._long_term(request, content, specs, proof, consent, now)
        else:
            if action["consent_event_ref"] is not None:
                raise _fail("invalid_user_event", "short-term replacement cannot consume future-reuse consent")
            # A replacement is confirmed by its own review purpose, rather than
            # disguising the old active memory as a new unconfirmed candidate.
            create = {k: action[k] for k in c.CreateAction.__required_keys__ if k != "op"} | {"op": "create"}
            changed = self._create(request, create, now, events, confirmation_purpose="replace")
        new_ref = next(ref for ref in changed if ref["type"] == "memory")
        new = self._resolve(request["user_id"], request["id"], new_ref, now)
        # A new ordinary long-term preference supersedes its older promoted
        # copies as well; a request-local replacement leaves the long-term original intact.
        family = [old]
        if old["scope"] == "long_term":
            family = [self._object(row) for row in self.conn.execute(
                """SELECT o.*,m.payload_json FROM v1_objects o JOIN v1_memories m ON m.id=o.id
                    WHERE o.user_id=? AND json_extract(m.payload_json,'$.family_id')=?
                        AND m.status IN ('candidate','active')""", (old["user_id"], old["family_id"]),
            )]
        for member in family:
            updated = self._update("memory", member | {"status": "superseded"})
            changed.append(_ref("memory", updated))
            if member["id"] == old["id"]:
                old = updated
        changed.append(self._link(request, new, old, "supersedes", now))
        return changed

    def _withdraw(self, request: sqlite3.Row, action: dict[str, Any], now: datetime,
                  events: dict[str, Any]) -> list[dict[str, Any]]:
        from .store_cleanup import CleanupStorage

        _shape(action, c.RemoveAction.__required_keys__, "withdraw")
        memory = self._memory(request, action, now)
        proof = self._proof(events, action["user_event_ref"], "withdraw", self._meaning(memory), subject_id=memory["id"])
        self._consume(proof)
        result = CleanupStorage(self).erase(request["user_id"], {memory["id"]}, now, family=True, withdraw=True)
        affected_ids = set(result["withdrawn_memories"])
        rows = self.conn.execute(
            """SELECT o.*,m.payload_json FROM v1_objects o JOIN v1_memories m ON m.id=o.id
                WHERE o.user_id=?""", (request["user_id"],),
        ).fetchall()
        changed = result["changed_refs"]
        for row in rows:
            obj = self._object(row)
            if obj["id"] not in affected_ids or obj["status"] == "withdrawn":
                continue
            obj = self._update("memory", obj | {"status": "withdrawn"})
            changed.append(_ref("memory", obj))
            for binding in self._bindings(obj["id"]):
                changed.append(_ref("binding", self._update("binding", binding | {"status": "withdrawn"})))
            if obj["consent_ref"] is not None:
                # An expired sibling must not prevent withdrawal of a live family.
                consent_row = self.conn.execute(
                    """SELECT o.*,c.payload_json FROM v1_objects o JOIN v1_consents c ON c.id=o.id
                        WHERE o.user_id=? AND c.id=?""", (obj["user_id"], obj["consent_ref"]["id"]),
                ).fetchone()
                if consent_row is not None:
                    consent = self._object(consent_row)
                    if consent["status"] != "withdrawn":
                        changed.append(_ref("consent", self._update("consent", consent | {"status": "withdrawn"})))
        return changed

    def _delete(self, request, actions, now, events):
        from .store_cleanup import CleanupStorage

        seeds = set()
        for action in actions:
            _shape(action, c.RemoveAction.__required_keys__, 'delete')
            memory = self._memory(request, action, now)
            proof = self._proof(events, action['user_event_ref'], 'delete', self._meaning(memory), subject_id=memory['id'])
            self._consume(proof)
            seeds.add(memory['id'])
        result = CleanupStorage(self).erase(request['user_id'], seeds, now, family=True)
        if result['profile_changed']:
            self.store._bump_profile(request['user_id'])

    def apply_batch(
        self, user_id: str, request_id: str, *, batch_id: str, actions: Any,
        contract_version: str, expected: Any, expected_request_revision: int | None,
        expected_profile_revision: int | None, catalog_freshness: Any,
    ) -> dict[str, Any]:
        if contract_version != c.CONTRACT_VERSION:
            raise _fail("unsupported_contract", "unsupported storage contract")
        for name, value in (("user_id", user_id), ("request_id", request_id), ("batch_id", batch_id)):
            _text(value, name)
        _list(actions, "actions", 32, nonempty=True)
        deleting = any(isinstance(a, dict) and a.get('op') == 'delete' for a in actions)
        if deleting and any(not isinstance(a, dict) or a.get('op') != 'delete' for a in actions):
            raise _fail('invalid_input', 'delete cannot be mixed with other actions')
        expected = self._expected(expected, expected_request_revision, expected_profile_revision)
        fingerprint = c.batch_fingerprint(contract_version, request_id, actions)
        _batch_size({"contract_version": contract_version, "request_id": request_id,
                     "batch_id": batch_id, "expected": expected, "actions": actions})
        now = self.store._now()
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            self.store._purge_expired_nonces(user_id, now)
            deleted = self.conn.execute('SELECT * FROM deletion_receipts WHERE user_id=? AND batch_id=?', (user_id, batch_id)).fetchone()
            if deleted is not None:
                digest = 'v1:' + hashlib.sha256((deleted['opaque'] + fingerprint).encode()).hexdigest()
                if deleted['command_fingerprint'] != digest:
                    raise _fail('idempotency_conflict', 'deleted batch was replayed with different actions')
                self.conn.commit()
                from .store_cleanup import CleanupStorage
                CleanupStorage(self).finish(user_id)
                return {'outcome': 'applied', 'batch_id': batch_id, 'request_id': request_id,
                        'request_revision': deleted['request_revision'], 'profile_revision': deleted['profile_revision'],
                        'changed_refs': [], 'evidence_refs': [], 'interpretation_ref': None}
            for table in ("batch_receipts",):
                if self.conn.execute(f"SELECT 1 FROM {table} WHERE user_id=? AND batch_id=?",
                                     (user_id, batch_id)).fetchone() is not None:
                    raise _fail("idempotency_conflict", "batch_id belongs to another contract")
            prior = self.conn.execute(
                "SELECT * FROM v1_batch_receipts WHERE user_id=? AND batch_id=?", (user_id, batch_id)
            ).fetchone()
            if prior is not None:
                if prior["fingerprint"] != fingerprint:
                    raise _fail("idempotency_conflict", "batch_id was already used with different actions")
                self.conn.commit()
                from .store_cleanup import CleanupStorage
                CleanupStorage(self).finish(user_id)
                return json.loads(prior["receipt_json"])
            self.store._assert_batch_not_tombstoned(user_id, batch_id, now)
            request = self._request(user_id, request_id, include_closed=True)
            if any(isinstance(a, dict) and a.get("op") == "submit_feedback" for a in actions) and len(actions) != 1:
                raise _fail("invalid_input", "feedback intake must be a separate single-action batch")
            if (expected["request_revision"] != request["revision"]
                or expected["profile_revision"] != self.store._profile_revision(user_id)):
                raise _fail("version_conflict", "expected revisions do not match")
            for ref in expected["object_versions"]:
                self._resolve(user_id, request_id, ref, now)
            initial_refs = {(ref["type"], ref["id"]) for ref in expected["object_versions"]}
            for action in actions:
                if not isinstance(action, dict):
                    raise _fail("invalid_input", "each action must be an object")
                if "memory_id" in action:
                    _text(action["memory_id"], "memory_id")
                    c.validate_ref({"type": "memory", "id": action["memory_id"], "version": action.get("expected_version")})
                    if ("memory", action["memory_id"]) not in initial_refs:
                        raise _fail("invalid_input", "memory mutation requires its batch-start object version")
                confirmations = _list(action["binding_confirmations"], "binding confirmations", 16) if "binding_confirmations" in action else []
                for ref in confirmations:
                    c.validate_ref(ref)
                    if (ref["type"], ref["id"]) not in initial_refs:
                        raise _fail("invalid_input", "binding confirmation requires its batch-start version")
            events = self._review_events(request, actions, now, catalog_freshness)
            self.store._call_failure_hook("begin", {"batch_id": batch_id, "request_id": request_id})
            changed: list[dict[str, Any]] = []
            evidence_refs: list[dict[str, Any]] = []
            interpretation_ref = None
            request_changed = deleting
            if deleting:
                self._delete(request, actions, now, events)
            for action in actions:
                if not isinstance(action, dict):
                    raise _fail("invalid_input", "each action must be an object")
                if action.get("op") in ("create", "create_long_term"):
                    changed.extend(self._create(request, action, now, events))
                elif action.get("op") in ("confirm", "confirm_bindings"):
                    changed.extend(self._confirm(request, action, now, events))
                elif action.get("op") == "propose_bindings":
                    changed.extend(self._propose_bindings(request, action, now))
                elif action.get("op") == "promote":
                    changed.extend(self._promote(request, action, now, events))
                elif action.get("op") == "replace":
                    changed.extend(self._replace(request, action, now, events))
                elif action.get("op") == "withdraw":
                    changed.extend(self._withdraw(request, action, now, events))
                elif action.get('op') == 'delete':
                    pass  # all deletion proofs were consumed before family erasure
                elif action.get("op") == "record_extraction":
                    changed.extend(self.feedback.extract(request, action, now, catalog_freshness))
                elif action.get("op") == "record_comparison":
                    _shape(action, c.RecordComparisonAction.__required_keys__, "record_comparison")
                    if len(actions) != 1 or request["status"] != "open":
                        raise _fail("invalid_input", "comparison response requires its own open-request batch")
                    response = action["feedback"]
                    _shape(response, c.FeedbackAction.__required_keys__, "comparison feedback")
                    if (response["reaction"] not in ("selected", "none", "unsure")
                            or response["question_id"] is not None or response["round_id"] is None
                            or (action["memory"] is not None) != (response["reaction"] == "selected" and response["text"] is None)):
                        raise _fail("invalid_input", "comparison response must explicitly choose, reject or defer")
                    response_refs, intake = self.feedback.submit(request, action["feedback"], expected, now, catalog_freshness)
                    changed.extend(response_refs)
                    evidence_refs = [ref for ref in response_refs if ref["type"] == "evidence"]
                    interpretation_ref = next(ref for ref in response_refs if ref["type"] == "interpretation")
                    if action["memory"] is not None:
                        if action["feedback"]["reaction"] != "selected" or len(action["feedback"]["selections"]) != 1:
                            raise _fail("invalid_input", "a confirmed interpretation needs one explicit comparison choice")
                        changed.extend(self._create(request, {k: action[k] for k in ("memory", "source_refs", "bindings", "confirmation_event_ref")}
                            | {"op": "create", "consent_event_ref": None}, now, events))
                    elif action["confirmation_event_ref"] is not None or action["bindings"] or action["source_refs"]:
                        raise _fail("invalid_input", "an unsure/rejected comparison cannot confirm an interpretation")
                    feedback_ref = next(ref for ref in response_refs if ref["type"] == "feedback")
                    if response["text"] is None:
                        changed.extend(self.feedback.extract(request, {"op": "record_extraction", "feedback_ref": feedback_ref,
                            "extraction_key": "comparison-response:" + batch_id, "result": {"candidates": [], "questions": []}, "error": None}, now, catalog_freshness))
                    else:
                        self._update("interpretation", intake | {"extraction_key": "comparison-response:" + batch_id}, bump=False)
                elif action.get("op") == "select_final":
                    if request["status"] != "open":
                        raise _fail("request_closed", "final selection requires an open request")
                    request_changed = self.feedback.select_final(request, action, expected, now, catalog_freshness) or request_changed
                    request = self.store._request_row(user_id, request_id)
                elif action.get("op") == "end_request":
                    _shape(action, c.EndRequestAction.__required_keys__, "end_request")
                    if request["status"] == "open":
                        retention = min(request["retention_until"], _iso(now + _CLOSED_RETENTION), key=_us)
                        self.conn.execute("UPDATE requests SET status='closed',retention_until=? WHERE id=?",
                                          (retention, request_id))
                        request = self.store._request_row(user_id, request_id)
                        request_changed = True
                        round_obj = self.feedback.active_round(request, now)
                        if round_obj:
                            round_obj = self._update("round", round_obj | {"status": "closed"})
                            changed.append(_ref("round", round_obj))
                elif action.get("op") == "submit_feedback":
                    if request["status"] != "open":
                        raise _fail("request_closed", "feedback requires an open request")
                    if interpretation_ref is not None:
                        raise _fail("invalid_input", "only one feedback intake is allowed per batch")
                    new_refs, interpretation = self.feedback.submit(request, action, expected, now, catalog_freshness)
                    changed.extend(new_refs)
                    evidence_refs.extend(ref for ref in new_refs if ref["type"] == "evidence")
                    interpretation_ref = _ref("interpretation", interpretation)
                else:
                    raise _fail("invalid_input", "unsupported storage action")
                self.store._call_failure_hook("after_action", {"op": action["op"], "batch_id": batch_id})
            # Receipts describe the final object versions, not intermediate action versions.
            final_refs = {}
            profile_changed = False
            for ref in changed:
                row = self.conn.execute("SELECT version,request_id FROM v1_objects WHERE id=?", (ref["id"],)).fetchone()
                if row is None:
                    continue
                final_refs[(ref["type"], ref["id"])] = ref | {"version": row["version"]}
                if ref["type"] in ("memory", "binding", "consent") and row["request_id"] is None:
                    profile_changed = True
            changed = list(final_refs.values())
            if profile_changed:
                self.store._bump_profile(user_id)
            revision = request["revision"] + int(bool(changed) or request_changed)
            if changed or request_changed:
                retention = request["retention_until"]
                if request["status"] == "open" and not deleting and not any(a['op'] == 'withdraw' for a in actions):
                    retention = _iso(min(now + _REQUEST_INACTIVITY,
                        _parse_datetime(request["max_until"], "max_until", allow_none=False)))
                self.conn.execute(
                    "UPDATE requests SET revision=?,updated_at=?,retention_until=? WHERE id=? AND user_id=?",
                    (revision, _iso(now), retention, request_id, user_id),
                )
            evidence_refs = [ref for ref in changed if ref["type"] == "evidence"]
            receipt = {
                "outcome": "applied" if changed or request_changed else "unchanged", "batch_id": batch_id, "request_id": request_id,
                "request_revision": revision, "profile_revision": self.store._profile_revision(user_id),
                "changed_refs": changed, "evidence_refs": evidence_refs, "interpretation_ref": interpretation_ref,
            }
            self.store._call_failure_hook("before_receipt", {"batch_id": batch_id})
            if deleting:
                opaque = _new_id()
                digest = 'v1:' + hashlib.sha256((opaque + fingerprint).encode()).hexdigest()
                self.conn.execute('''INSERT INTO deletion_receipts
                    (user_id,batch_id,request_id,opaque,command_fingerprint,expires_at,request_revision,profile_revision,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)''',
                    (user_id, batch_id, request_id, opaque, digest, _iso(now + _DELETION_RECEIPT_TTL),
                     revision, self.store._profile_revision(user_id), _iso(now)))
            else:
                self.conn.execute(
                    "INSERT INTO v1_batch_receipts VALUES (?,?,?,?,?,?)",
                    (user_id, batch_id, request_id, fingerprint, _canonical(receipt), _iso(now)),
                )
            self.store._call_failure_hook("commit", {"batch_id": batch_id})
            self.conn.commit()
            from .store_cleanup import CleanupStorage
            CleanupStorage(self).finish(user_id)
            return receipt
        except StyleMateError:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise _fail("storage_failed", "memory batch was rolled back") from exc

    def snapshot(
        self, user_id: str, request_id: str, *, contract_version: str, include_closed: bool,
    ) -> dict[str, Any]:
        if contract_version != c.CONTRACT_VERSION:
            raise _fail("unsupported_contract", "unsupported storage contract")
        _text(user_id, "user_id")
        _text(request_id, "request_id")
        if type(include_closed) is not bool:
            raise _fail("invalid_input", "include_closed must be bool")
        now = self.store._now()
        try:
            self.conn.execute("BEGIN")
            request = self._request(user_id, request_id, include_closed=include_closed)
            result = {
                "contract_version": contract_version, "registry_version": request["registry_version"],
                "request": self.request_dict(request), "now": _iso(now),
                "profile_revision": self.store._profile_revision(user_id),
            }
            # Scope, retention and exact half-open validity are enforced in SQL.
            # Content/binding confirmation, consent and semantic conditions remain
            # C2's responsibility; an unconfirmed candidate is still returned.
            memories = self.conn.execute(
                """SELECT o.*,m.payload_json FROM v1_objects o JOIN v1_memories m ON m.id=o.id
                WHERE o.user_id=? AND o.contract_version=? AND o.retention_us>?
                    AND ((m.scope='short_term' AND o.request_id=?)
                         OR (m.scope='long_term' AND o.request_id IS NULL))
                    AND m.status IN ('candidate','active')
                    AND (m.valid_from_us IS NULL OR m.valid_from_us<=?)
                    AND (m.valid_until_us IS NULL OR m.valid_until_us>?)
                ORDER BY o.created_at,o.id""",
                (user_id, contract_version, _us(now), request_id, _us(now), _us(now)),
            ).fetchall()
            result["memories"] = [self._object(row) for row in memories]
            memory_ids = {item["id"] for item in result["memories"]}
            for kind, key in (
                ("evidence", "evidence"), ("binding", "bindings"), ("confirmation", "confirmations"),
                ("consent", "consents"), ("link", "links"), ("feedback", "feedback"),
                ("interpretation", "interpretations"), ("round", "rounds"),
                ("candidate_set", "candidate_sets"), ("question", "questions"),
            ):
                rows = self.conn.execute(
                    f"""SELECT o.*,t.payload_json FROM v1_objects o JOIN {_TABLES[kind]} t ON t.id=o.id
                    WHERE o.user_id=? AND o.contract_version=? AND o.retention_us>?
                        AND (o.request_id=? OR o.request_id IS NULL) ORDER BY o.created_at,o.id""",
                    (user_id, contract_version, _us(now), request_id),
                ).fetchall()
                items = [self._object(row) for row in rows]
                if kind in ("binding", "confirmation", "consent"):
                    items = [item for item in items if item["memory_id"] in memory_ids]
                result[key] = items
            self.conn.commit()
            return result
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def interpretation_status(self, user_id: str, request_id: str, feedback_ref: Any) -> dict[str, Any]:
        _text(user_id, "user_id")
        _text(request_id, "request_id")
        try:
            self.conn.execute("BEGIN")
            request = self._request(user_id, request_id, include_closed=True)
            now = self.store._now()
            feedback = self._resolve(user_id, request_id, feedback_ref, now)
            if feedback_ref["type"] != "feedback":
                raise _fail("invalid_input", "feedback_ref must refer to feedback")
            result = self.feedback.object(request, "interpretation", feedback["interpretation_ref"]["id"], now)
            self.conn.commit()
            return result
        except Exception:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise

    def migrate_legacy(self, user_id: str, request_id: str, *, registry_version: str) -> dict[str, Any]:
        """Copy a legacy projection once; never reinterpret its values or consent.

        Original tables remain usable by legacy callers. Historical confirmation
        and consent stay in LegacyRecord.original: no v1 trusted event, quote,
        binding or broader reuse authorization can be reconstructed from them.
        """
        _text(user_id, "user_id")
        _text(request_id, "request_id")
        if registry_version != c.V1_REGISTRY_VERSION:
            raise _fail("unsupported_contract", "unsupported migration registry")
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            source_request = self.store._request_row(user_id, request_id)
            self.check_contract(source_request, None)
            source_rows = self.conn.execute(
                """SELECT * FROM memories WHERE user_id=?
                AND ((scope='short_term' AND request_id=?) OR scope='long_term')
                ORDER BY created_at,id""", (user_id, request_id),
            ).fetchall()
            originals = [self.store._memory_dict(row) for row in source_rows]
            digest = _digest({"request": dict(source_request), "memories": originals})
            prior = self.conn.execute(
                "SELECT * FROM v1_legacy_migrations WHERE user_id=? AND source_request_id=?",
                (user_id, request_id),
            ).fetchone()
            if prior is not None:
                if prior["source_digest"] != digest:
                    raise _fail("version_conflict", "legacy source changed after migration")
                result = self.request_dict(self.store._request_row(user_id, prior["target_request_id"]))
                self.conn.commit()
                return result
            self.store._call_failure_hook("migration_begin", {"request_id": request_id})
            target_id = _new_id()
            self.conn.execute(
                """INSERT INTO requests
                (id,user_id,input_id,input_digest,timezone,revision,created_at,updated_at,status,
                 retention_until,max_until,contract_version,registry_version,mode,targets_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'shopping','[]')""",
                (target_id, user_id, _new_id(), _digest({"legacy_request": request_id}),
                 source_request["timezone"], source_request["revision"], source_request["created_at"],
                 source_request["updated_at"], source_request["status"], source_request["retention_until"],
                 source_request["max_until"], c.CONTRACT_VERSION, registry_version),
            )
            for original in originals:
                if ((original["scope"] == "long_term" and original["request_id"] is not None)
                    or (original["scope"] == "short_term" and original["request_id"] != request_id)):
                    raise _fail("invalid_input", "legacy memory scope does not match its request")
                existing = self.conn.execute(
                    """SELECT o.*,m.payload_json FROM v1_objects o
                    JOIN v1_memories m ON m.id=o.id WHERE o.id=?""", (original["id"],),
                ).fetchone()
                if existing is not None:
                    item = self._object(existing)
                    # Shared long-term rows can appear in several request migrations.
                    if (original["scope"] != "long_term" or item["user_id"] != user_id
                        or item.get("legacy", {}).get("original") != original):
                        raise _fail("version_conflict", "legacy memory projection already differs")
                    continue
                feature = original["feature"]
                kind = "situation" if feature in ("occasion", "activity", "goal") else (
                    "requirement" if original["polarity"] == "require" else "preference"
                )
                obj = {key: original[key] for key in (
                    "id", "user_id", "scope", "content", "polarity", "strength", "origin", "confirmed",
                    "status", "version", "family_id", "created_at", "valid_from", "valid_until", "retention_until",
                )} | {
                    "contract_version": c.CONTRACT_VERSION,
                    "request_id": target_id if original["scope"] == "short_term" else None,
                    "kind": kind, "fact": None,
                    "selector": {key: original["selector"].get(key) for key in ("garment_type", "slot_id")},
                    "conditions": {key: value for key, value in original["conditions"].items()
                                   if key in ("occasion", "activity", "goal")},
                    "source_refs": [], "confirmation_ref": None, "consent_ref": None,
                    "legacy": {
                        "registry_version": c.LEGACY_REGISTRY_VERSION, "original": original,
                        "evidence_status": "reference_only" if original["evidence_ref"] else "missing",
                        "mapping_status": "requires_review",
                    },
                }
                # No original quote exists in a legacy DB. Preserve references
                # as historical data instead of manufacturing Evidence or events.
                self._put("memory", obj)
                self.store._call_failure_hook("migration_after_memory", {"memory_id": original["id"]})
            self.conn.execute(
                "INSERT INTO v1_legacy_migrations VALUES (?,?,?,?)", (user_id, request_id, target_id, digest)
            )
            self.store._call_failure_hook("migration_before_commit", {"request_id": request_id})
            self.conn.commit()
            return self.request_dict(self.store._request_row(user_id, target_id))
        except StyleMateError:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise
        except Exception as exc:
            if self.conn.in_transaction:
                self.conn.rollback()
            raise _fail("storage_failed", "legacy migration was rolled back") from exc
