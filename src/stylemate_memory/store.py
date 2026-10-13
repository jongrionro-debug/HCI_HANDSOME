"""Small, caller-scoped SQLite store for StyleMate shopping memory.

The store deliberately knows nothing about authentication, natural-language
meaning, or an LLM provider.  A trusted local caller supplies the evidence and
consent references after it has obtained them from the user.  This module only
enforces ownership, lifecycle, optimistic concurrency, retention, and atomic
batch writes.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import sqlite3
import uuid
from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .errors import StyleMateError


_REQUEST_INACTIVITY = timedelta(days=30)
_REQUEST_MAX_AGE = timedelta(days=90)
_LONG_TERM_RETENTION = timedelta(days=365)
_CLOSED_RETENTION = timedelta(days=30)

_MEMORY_KEYS = {
    "id",
    "user_id",
    "request_id",
    "scope",
    "feature",
    "values",
    "polarity",
    "strength",
    "match",
    "selector",
    "conditions",
    "content",
    "origin",
    "confirmed",
    "status",
    "version",
    "family_id",
    "created_at",
    "valid_from",
    "valid_until",
    "retention_until",
    "evidence_ref",
    "consent_ref",
}

_MEMORY_PAYLOAD_KEYS = _MEMORY_KEYS | {"key", "value", "claim"}
_DELETION_RECEIPT_TTL = timedelta(hours=24)


def _fail(code: str, message: str) -> StyleMateError:
    return StyleMateError(code, message)


def _nonblank(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _fail("invalid_input", f"{field} must be a non-blank string")
    return value.strip()


def _new_id() -> str:
    return str(uuid.uuid4())


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError, OverflowError) as exc:
        raise _fail("invalid_input", "payload must be JSON serializable") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise _fail("invalid_clock", "clock must return a timezone-aware datetime")
    return value.isoformat(timespec="microseconds")


def _parse_datetime(value: Any, field: str, *, allow_none: bool = True) -> datetime | None:
    if value is None and allow_none:
        return None
    if not isinstance(value, str) or not value.strip():
        raise _fail("invalid_input", f"{field} must be an ISO datetime")
    text = value.strip().replace("Z", "+00:00")
    try:
        result = datetime.fromisoformat(text)
    except ValueError as exc:
        raise _fail("invalid_input", f"{field} must be an ISO datetime") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise _fail("invalid_input", f"{field} must include a timezone")
    return result


def _as_json(value: Any) -> str:
    return _canonical(value)


class MemoryStore(AbstractContextManager["MemoryStore"]):
    """SQLite-backed memory store.

    ``clock`` is injected for deterministic expiry and DST-boundary tests.  A
    failure hook is intentionally local: it can raise at a named write point
    so callers can verify the transaction rolls back.  No credentials or raw
    conversation text are ever written by this class.
    """

    def __init__(
        self,
        path: str | Path,
        clock: Callable[[], datetime] | None = None,
        failure_hook: Callable[..., Any] | None = None,
    ) -> None:
        self.path = str(path)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._failure_hook = failure_hook
        self._connection: sqlite3.Connection | None = sqlite3.connect(
            self.path, timeout=10, isolation_level=None, check_same_thread=False
        )
        self._connection.row_factory = sqlite3.Row
        self._configure()
        self._migrate()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise _fail("closed", "memory store is closed")
        return self._connection

    def _configure(self) -> None:
        conn = self.connection
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = DELETE")
        conn.execute("PRAGMA secure_delete = ON")
        conn.execute("PRAGMA synchronous = FULL")

    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS requests (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                input_id TEXT NOT NULL,
                input_digest TEXT NOT NULL,
                timezone TEXT NOT NULL,
                revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('open', 'closed', 'expired')),
                retention_until TEXT NOT NULL,
                max_until TEXT NOT NULL,
                UNIQUE (user_id, input_id)
            );

            CREATE INDEX IF NOT EXISTS requests_user_idx ON requests(user_id);

            CREATE TABLE IF NOT EXISTS profiles (
                user_id TEXT PRIMARY KEY,
                revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0)
            );

            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                request_id TEXT REFERENCES requests(id) ON DELETE CASCADE,
                scope TEXT NOT NULL CHECK (scope IN ('short_term', 'long_term')),
                feature TEXT NOT NULL,
                values_json TEXT NOT NULL,
                polarity TEXT NOT NULL CHECK (polarity IN ('prefer', 'avoid', 'require')),
                strength TEXT NOT NULL CHECK (strength IN ('soft', 'hard')),
                match_mode TEXT NOT NULL CHECK (match_mode IN ('any', 'all', 'range')),
                selector_json TEXT NOT NULL,
                conditions_json TEXT NOT NULL,
                content TEXT NOT NULL,
                origin TEXT NOT NULL CHECK (origin IN ('explicit', 'inferred')),
                confirmed INTEGER NOT NULL CHECK (confirmed IN (0, 1)),
                status TEXT NOT NULL CHECK (status IN ('candidate', 'active', 'withdrawn', 'superseded')),
                version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1),
                family_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                valid_from TEXT,
                valid_until TEXT,
                retention_until TEXT NOT NULL,
                evidence_ref TEXT NOT NULL,
                consent_ref TEXT,
                FOREIGN KEY (user_id) REFERENCES profiles(user_id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS memories_user_idx ON memories(user_id);
            CREATE INDEX IF NOT EXISTS memories_family_idx ON memories(user_id, family_id);
            CREATE INDEX IF NOT EXISTS memories_retention_idx ON memories(retention_until);

            CREATE TABLE IF NOT EXISTS batch_receipts (
                user_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                request_body_digest TEXT NOT NULL,
                memory_ids_json TEXT NOT NULL,
                request_revision INTEGER NOT NULL,
                profile_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, batch_id),
                FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS events (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                request_id TEXT REFERENCES requests(id) ON DELETE CASCADE,
                memory_id TEXT,
                op TEXT NOT NULL,
                evidence_digest TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES profiles(user_id) ON DELETE CASCADE
            );

            -- These tables intentionally contain no source content or memory
            -- identifiers.  They only prevent an input/batch nonce from being
            -- immediately reused after its source rows were physically erased.
            CREATE TABLE IF NOT EXISTS deletion_receipts (
                user_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                request_id TEXT NOT NULL,
                opaque TEXT NOT NULL,
                command_fingerprint TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                request_revision INTEGER NOT NULL,
                profile_revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                PRIMARY KEY (user_id, batch_id),
                FOREIGN KEY (request_id) REFERENCES requests(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS request_tombstones (
                user_id TEXT NOT NULL,
                input_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (user_id, input_id)
            );

            CREATE TABLE IF NOT EXISTS batch_tombstones (
                user_id TEXT NOT NULL,
                batch_id TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                PRIMARY KEY (user_id, batch_id)
            );
            """
        )
        # Keep a saved prototype database readable if it was created by the
        # first implementation before the opaque deletion-command fingerprint
        # was added.  Existing rows cannot be replayed safely, so seed them
        # with an impossible marker and let the normal conflict path reject a
        # retry until their short TTL expires.
        deletion_columns = {
            row["name"] for row in self.connection.execute("PRAGMA table_info(deletion_receipts)")
        }
        if "command_fingerprint" not in deletion_columns:
            self.connection.execute(
                "ALTER TABLE deletion_receipts ADD COLUMN command_fingerprint TEXT NOT NULL DEFAULT '__legacy_deleted__'"
            )

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise _fail("invalid_clock", "clock must return a timezone-aware datetime")
        return value

    def _call_failure_hook(self, stage: str, context: Mapping[str, Any] | None = None) -> None:
        if self._failure_hook is None:
            return
        hook = self._failure_hook
        try:
            parameters = inspect.signature(hook).parameters
        except (TypeError, ValueError):
            parameters = {"stage": None}
        if len(parameters) == 0:
            hook()
        elif len(parameters) == 1:
            hook(stage)
        else:
            hook(stage, dict(context or {}))

    def _ensure_profile(self, user_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO profiles(user_id, revision) VALUES (?, 0)", (user_id,)
        )

    def _purge_expired_nonces(self, user_id: str, now: datetime) -> None:
        now_s = _iso(now)
        self.connection.execute(
            "DELETE FROM request_tombstones WHERE user_id=? AND expires_at<=?",
            (user_id, now_s),
        )
        self.connection.execute(
            "DELETE FROM batch_tombstones WHERE user_id=? AND expires_at<=?",
            (user_id, now_s),
        )
        self.connection.execute(
            "DELETE FROM deletion_receipts WHERE user_id=? AND expires_at<=?",
            (user_id, now_s),
        )

    def _assert_input_not_tombstoned(self, user_id: str, input_id: str, now: datetime) -> None:
        row = self.connection.execute(
            "SELECT expires_at FROM request_tombstones WHERE user_id=? AND input_id=?",
            (user_id, input_id),
        ).fetchone()
        if row is not None and _parse_datetime(row["expires_at"], "expires_at", allow_none=False) > now:
            raise _fail("idempotency_conflict", "input_id is reserved during deletion recovery")

    def _assert_batch_not_tombstoned(self, user_id: str, batch_id: str, now: datetime) -> None:
        row = self.connection.execute(
            "SELECT expires_at FROM batch_tombstones WHERE user_id=? AND batch_id=?",
            (user_id, batch_id),
        ).fetchone()
        if row is not None and _parse_datetime(row["expires_at"], "expires_at", allow_none=False) > now:
            raise _fail("idempotency_conflict", "batch_id is reserved during deletion recovery")

    def _profile_revision(self, user_id: str) -> int:
        row = self.connection.execute(
            "SELECT revision FROM profiles WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return 0
        return int(row[0])

    def _bump_profile(self, user_id: str) -> int:
        self.connection.execute(
            "UPDATE profiles SET revision = revision + 1 WHERE user_id = ?", (user_id,)
        )
        return self._profile_revision(user_id)

    def _request_row(self, user_id: str, request_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM requests WHERE id = ? AND user_id = ?", (request_id, user_id)
        ).fetchone()
        if row is None:
            raise _fail("not_found", "request not found")
        return row

    def _request_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "revision": int(row["revision"]),
            "timezone": row["timezone"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "retention_until": row["retention_until"],
        }

    def _expired_request(self, row: sqlite3.Row, now: datetime) -> bool:
        return now >= (_parse_datetime(row["retention_until"], "retention_until", allow_none=False))

    def _assert_request_open(self, row: sqlite3.Row, now: datetime) -> None:
        if self._expired_request(row, now):
            self.connection.execute(
                "UPDATE requests SET status = 'expired' WHERE id = ?", (row["id"],)
            )
            raise _fail("retention_expired", "request retention has expired")
        if row["status"] != "open":
            raise _fail("request_closed", "request is not open")

    def _check_revision(self, actual: int, expected: int | None, name: str) -> None:
        if expected is not None and type(expected) is not int:
            raise _fail("invalid_input", f"{name} revision must be an integer")
        if expected is not None and expected != actual:
            raise _fail("revision_conflict", f"{name} revision does not match")

    def start_request(
        self, user_id: str, *, input_id: str, text: str, timezone: str
    ) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        input_id = _nonblank(input_id, "input_id")
        if not isinstance(text, str) or not text.strip():
            raise _fail("invalid_input", "text must be a non-blank string")
        timezone = _nonblank(timezone, "timezone")
        try:
            # ZoneInfo is deliberately optional; this checks the common IANA form
            # when available without making timezone data an application dependency.
            from zoneinfo import ZoneInfo

            ZoneInfo(timezone)
        except Exception as exc:
            raise _fail("invalid_input", "timezone must be a valid IANA timezone") from exc
        now = self._now()
        now_s = _iso(now)
        digest = hashlib.sha256(
            _canonical({"text": text, "timezone": timezone}).encode("utf-8")
        ).hexdigest()
        retention = now + _REQUEST_INACTIVITY
        max_until = now + _REQUEST_MAX_AGE
        conn = self.connection
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._ensure_profile(user_id)
            self._purge_expired_nonces(user_id, now)
            self._assert_input_not_tombstoned(user_id, input_id, now)
            existing = conn.execute(
                "SELECT * FROM requests WHERE user_id = ? AND input_id = ?",
                (user_id, input_id),
            ).fetchone()
            if existing is not None:
                if existing["status"] == "expired" or self._expired_request(existing, now):
                    conn.execute(
                        "UPDATE requests SET status='expired' WHERE id=? AND user_id=?",
                        (existing["id"], user_id),
                    )
                    conn.commit()
                    raise _fail("retention_expired", "input_id belongs to an expired request")
                if existing["input_digest"] != digest:
                    raise _fail("idempotency_conflict", "input_id was already used with different text or timezone")
                conn.commit()
                return self._request_dict(existing)
            request_id = _new_id()
            conn.execute(
                """
                INSERT INTO requests
                (id,user_id,input_id,input_digest,timezone,revision,created_at,updated_at,status,retention_until,max_until)
                VALUES (?,?,?,?,?,1,?,?,?, ?, ?)
                """,
                (
                    request_id,
                    user_id,
                    input_id,
                    digest,
                    timezone,
                    now_s,
                    now_s,
                    "open",
                    _iso(retention),
                    _iso(max_until),
                ),
            )
            conn.commit()
            return self._request_dict(self._request_row(user_id, request_id))
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def get_request(self, user_id: str, request_id: str) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        return self._request_dict(self._request_row(user_id, request_id))

    def resume_request(
        self, user_id: str, request_id: str, expected_revision: int | None = None
    ) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        conn = self.connection
        now = self._now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._request_row(user_id, request_id)
            self._check_revision(int(row["revision"]), expected_revision, "request")
            self._assert_request_retained(row, now)
            if row["status"] == "open":
                conn.commit()
                return self._request_dict(row)
            retention = min(
                now + _REQUEST_INACTIVITY,
                _parse_datetime(row["max_until"], "max_until", allow_none=False),
            )
            conn.execute(
                """
                UPDATE requests SET status='open', revision=revision+1,
                    updated_at=?, retention_until=? WHERE id=? AND user_id=?
                """,
                (_iso(now), _iso(retention), request_id, user_id),
            )
            conn.commit()
            return self._request_dict(self._request_row(user_id, request_id))
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def _assert_request_retained(self, row: sqlite3.Row, now: datetime) -> None:
        if self._expired_request(row, now):
            self.connection.execute(
                "UPDATE requests SET status='expired' WHERE id=?", (row["id"],)
            )
            raise _fail("retention_expired", "request retention has expired")

    def close_request(
        self, user_id: str, request_id: str, expected_revision: int | None = None
    ) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        conn = self.connection
        now = self._now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._request_row(user_id, request_id)
            self._check_revision(int(row["revision"]), expected_revision, "request")
            self._assert_request_retained(row, now)
            if row["status"] == "closed":
                conn.commit()
                return self._request_dict(row)
            if row["status"] != "open":
                raise _fail("request_closed", "request is not open")
            retention = min(
                now + _CLOSED_RETENTION,
                _parse_datetime(row["max_until"], "max_until", allow_none=False),
            )
            conn.execute(
                """
                UPDATE requests SET status='closed', revision=revision+1,
                    updated_at=?, retention_until=? WHERE id=? AND user_id=?
                """,
                (_iso(now), _iso(now), request_id, user_id),
            )
            # Closed requests are kept briefly for recovery, but have no active UI context.
            conn.execute(
                "UPDATE requests SET retention_until=? WHERE id=? AND user_id=?",
                (_iso(retention), request_id, user_id),
            )
            conn.commit()
            return self._request_dict(self._request_row(user_id, request_id))
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    def _memory_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": row["id"],
            "user_id": row["user_id"],
            "request_id": row["request_id"],
            "scope": row["scope"],
            "feature": row["feature"],
            "values": json.loads(row["values_json"]),
            "polarity": row["polarity"],
            "strength": row["strength"],
            "match": row["match_mode"],
            "selector": json.loads(row["selector_json"]),
            "conditions": json.loads(row["conditions_json"]),
            "content": row["content"],
            "origin": row["origin"],
            "confirmed": bool(row["confirmed"]),
            "status": row["status"],
            "version": int(row["version"]),
            "family_id": row["family_id"],
            "created_at": row["created_at"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "retention_until": row["retention_until"],
            "evidence_ref": row["evidence_ref"],
            "consent_ref": row["consent_ref"],
        }

    def _memory_row(self, user_id: str, memory_id: str) -> sqlite3.Row:
        row = self.connection.execute(
            "SELECT * FROM memories WHERE id=? AND user_id=?", (memory_id, user_id)
        ).fetchone()
        if row is None:
            raise _fail("not_found", "memory not found")
        return row

    def _closed_retention(self, retention_value: Any, now: datetime) -> str:
        original = _parse_datetime(retention_value, "retention_until", allow_none=False)
        return _iso(min(original, now + _CLOSED_RETENTION))

    def _validate_memory_payload(
        self,
        payload: Mapping[str, Any],
        *,
        user_id: str,
        request_id: str,
        now: datetime,
        default_scope: str = "short_term",
        family_id: str | None = None,
        force_explicit: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise _fail("invalid_input", "memory payload must be an object")
        if "memory" in payload and isinstance(payload["memory"], Mapping):
            nested = dict(payload["memory"])
            nested.update({k: v for k, v in payload.items() if k not in {"memory", "op"}})
            payload = nested
        if "claim" in payload and isinstance(payload["claim"], Mapping):
            merged = dict(payload["claim"])
            merged.update({k: v for k, v in payload.items() if k != "claim"})
            payload = merged
        unknown = set(payload) - _MEMORY_PAYLOAD_KEYS
        if unknown:
            raise _fail("invalid_input", "unknown memory field")
        if "key" in payload and "feature" not in payload:
            payload = {**payload, "feature": payload["key"]}
        if "value" in payload and "values" not in payload:
            payload = {**payload, "values": [payload["value"]]}
        scope = payload.get("scope", default_scope)
        if scope not in ("short_term", "long_term"):
            raise _fail("invalid_input", "scope must be short_term or long_term")
        feature = _nonblank(payload.get("feature"), "feature")
        values = payload.get("values")
        if not isinstance(values, list) or not values:
            raise _fail("invalid_input", "values must be a non-empty list")
        if any(isinstance(v, bool) or not isinstance(v, (str, int)) for v in values):
            raise _fail("invalid_input", "values must contain only strings or integers")
        if any(isinstance(v, str) and not v.strip() for v in values):
            raise _fail("invalid_input", "values cannot contain blank strings")
        if len({(type(v).__name__, v) for v in values}) != len(values):
            raise _fail("invalid_input", "values must be unique")
        polarity = payload.get("polarity", "prefer")
        strength = payload.get("strength", "soft")
        match_mode = payload.get("match", "any")
        if polarity not in ("prefer", "avoid", "require"):
            raise _fail("invalid_input", "invalid polarity")
        if strength not in ("soft", "hard"):
            raise _fail("invalid_input", "invalid strength")
        if match_mode not in ("any", "all", "range"):
            raise _fail("invalid_input", "invalid match")
        selector = payload.get("selector", {})
        conditions = payload.get("conditions", {})
        if not isinstance(selector, Mapping) or set(selector) - {"garment_type", "slot_id"}:
            raise _fail("invalid_input", "selector only supports garment_type and slot_id")
        if not isinstance(conditions, Mapping) or any(
            not isinstance(k, str) or not k.strip() or not isinstance(v, str) or not v.strip()
            for k, v in conditions.items()
        ):
            raise _fail("invalid_input", "conditions must be a string-to-string object")
        selector = {str(k): _nonblank(v, f"selector.{k}") for k, v in selector.items() if v is not None}
        if scope == "long_term" and "slot_id" in selector:
            raise _fail("invalid_input", "long-term memory cannot carry request slot_id")
        content = _nonblank(payload.get("content"), "content")
        origin = payload.get("origin", "explicit")
        if force_explicit:
            origin = "explicit"
        if origin not in ("explicit", "inferred"):
            raise _fail("invalid_input", "invalid origin")
        confirmed_value = payload.get("confirmed", False)
        if type(confirmed_value) is not bool:
            raise _fail("invalid_input", "confirmed must be a boolean")
        confirmed = confirmed_value
        status = payload.get("status")
        if status is None:
            status = "active" if confirmed else "candidate"
        if status not in ("candidate", "active"):
            raise _fail("invalid_input", "new memories must be candidate or active")
        if origin == "inferred" and confirmed:
            raise _fail("confirmation_required", "inferred memory cannot be confirmed on create")
        if origin == "inferred":
            status = "candidate"
            confirmed = False
        if confirmed and status != "active":
            raise _fail("invalid_input", "confirmed memory must be active")
        if scope == "short_term":
            actual_request_id: str | None = request_id
        else:
            actual_request_id = None
        supplied_request_id = payload.get("request_id")
        if supplied_request_id is not None and supplied_request_id != actual_request_id:
            raise _fail("invalid_input", "request_id does not match memory scope")
        evidence_ref = _nonblank(payload.get("evidence_ref"), "evidence_ref")
        consent_ref = payload.get("consent_ref")
        if consent_ref is not None:
            consent_ref = _nonblank(consent_ref, "consent_ref")
        if scope == "long_term" and not consent_ref:
            raise _fail("consent_required", "long-term memory requires consent_ref")
        valid_from = _parse_datetime(payload.get("valid_from"), "valid_from")
        valid_until = _parse_datetime(payload.get("valid_until"), "valid_until")
        if valid_from is not None and valid_until is not None and valid_until < valid_from:
            raise _fail("invalid_input", "valid_until must be after valid_from")
        retention = _parse_datetime(payload.get("retention_until"), "retention_until")
        if retention is None:
            retention = now + (_LONG_TERM_RETENTION if scope == "long_term" else _REQUEST_INACTIVITY)
        else:
            # A caller may shorten a retention period, but cannot extend the
            # product's bounded lifetime from a memory action.
            retention = min(
                retention,
                now + (_LONG_TERM_RETENTION if scope == "long_term" else _REQUEST_INACTIVITY),
            )
        if retention <= now:
            raise _fail("retention_expired", "memory retention has expired")
        family = _nonblank(family_id or payload.get("family_id") or _new_id(), "family_id")
        return {
            "id": payload.get("id") or _new_id(),
            "user_id": user_id,
            "request_id": actual_request_id,
            "scope": scope,
            "feature": feature,
            "values": values,
            "polarity": polarity,
            "strength": strength,
            "match": match_mode,
            "selector": dict(selector),
            "conditions": dict(conditions),
            "content": content,
            "origin": origin,
            "confirmed": confirmed,
            "status": status,
            "version": 1,
            "family_id": family,
            "created_at": _iso(now),
            # Keep user supplied validity strings intact after parsing them.
            # This makes short-term date boundaries auditable without changing
            # a caller's offset or precision.
            "valid_from": payload.get("valid_from") if valid_from else None,
            "valid_until": payload.get("valid_until") if valid_until else None,
            "retention_until": _iso(retention),
            "evidence_ref": evidence_ref,
            "consent_ref": consent_ref,
        }

    def _memory_semantic_key(self, memory: Mapping[str, Any]) -> str:
        return _canonical(
            {
                "scope": memory["scope"],
                "request_id": memory["request_id"],
                "feature": memory["feature"],
                "values": memory["values"],
                "polarity": memory["polarity"],
                "strength": memory["strength"],
                "match": memory["match"],
                "selector": memory["selector"],
                "conditions": memory["conditions"],
                "content": memory["content"],
            }
        )

    def _find_duplicate(self, memory: Mapping[str, Any]) -> sqlite3.Row | None:
        rows = self.connection.execute(
            """
            SELECT * FROM memories
            WHERE user_id=? AND scope=? AND status IN ('candidate','active')
              AND ((scope='short_term' AND request_id=?) OR scope='long_term')
            """,
            (memory["user_id"], memory["scope"], memory["request_id"]),
        ).fetchall()
        key = self._memory_semantic_key(memory)
        for row in rows:
            if self._memory_semantic_key(self._memory_dict(row)) == key:
                return row
        return None

    def _insert_memory(self, memory: Mapping[str, Any]) -> None:
        self.connection.execute(
            """
            INSERT INTO memories
            (id,user_id,request_id,scope,feature,values_json,polarity,strength,match_mode,
             selector_json,conditions_json,content,origin,confirmed,status,version,family_id,
             created_at,valid_from,valid_until,retention_until,evidence_ref,consent_ref)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                memory["id"], memory["user_id"], memory["request_id"], memory["scope"],
                memory["feature"], _as_json(memory["values"]), memory["polarity"],
                memory["strength"], memory["match"], _as_json(memory["selector"]),
                _as_json(memory["conditions"]), memory["content"], memory["origin"],
                int(memory["confirmed"]), memory["status"], memory["version"],
                memory["family_id"], memory["created_at"], memory["valid_from"],
                memory["valid_until"], memory["retention_until"], memory["evidence_ref"],
                memory["consent_ref"],
            ),
        )

    def _write_event(
        self, user_id: str, request_id: str, memory_id: str | None, op: str, evidence_ref: str, now: datetime
    ) -> None:
        self.connection.execute(
            """
            INSERT INTO events(id,user_id,request_id,memory_id,op,evidence_digest,created_at)
            VALUES (?,?,?,?,?,?,?)
            """,
            (_new_id(), user_id, request_id, memory_id, op, _digest(evidence_ref), _iso(now)),
        )

    def _fetch_batch_receipt(self, user_id: str, batch_id: str, digest: str) -> dict[str, Any] | None:
        deletion = self.connection.execute(
            "SELECT * FROM deletion_receipts WHERE user_id=? AND batch_id=?",
            (user_id, batch_id),
        ).fetchone()
        if deletion is not None:
            if deletion["command_fingerprint"] != digest:
                raise _fail("idempotency_conflict", "deleted batch was replayed with different actions")
            return {
                "memory_ids": [],
                "request_revision": int(deletion["request_revision"]),
                "profile_revision": int(deletion["profile_revision"]),
                "batch_id": batch_id,
                "request_id": deletion["request_id"],
            }
        row = self.connection.execute(
            "SELECT * FROM batch_receipts WHERE user_id=? AND batch_id=?", (user_id, batch_id)
        ).fetchone()
        if row is None:
            return None
        if row["request_body_digest"] != digest:
            raise _fail("idempotency_conflict", "batch_id was already used with different actions")
        return {
            "memory_ids": json.loads(row["memory_ids_json"]),
            "request_revision": int(row["request_revision"]),
            "profile_revision": int(row["profile_revision"]),
            "batch_id": batch_id,
            "request_id": row["request_id"],
        }

    def apply_batch(
        self,
        user_id: str,
        request_id: str,
        *,
        batch_id: str,
        actions: list[Mapping[str, Any]],
        expected_request_revision: int | None = None,
        expected_profile_revision: int | None = None,
    ) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        batch_id = _nonblank(batch_id, "batch_id")
        if not isinstance(actions, list) or not actions:
            raise _fail("invalid_input", "actions must be a non-empty list")
        if any(not isinstance(action, Mapping) for action in actions):
            raise _fail("invalid_input", "each action must be an object")
        for action in actions:
            self._validate_action_shape(action)
        operations = [action.get("op") for action in actions]
        if "delete" in operations and any(operation != "delete" for operation in operations):
            raise _fail("invalid_input", "delete must be the only kind of action in a batch")
        body = {"request_id": request_id, "actions": actions}
        body_digest = _digest(body)
        conn = self.connection
        now = self._now()
        needs_vacuum = False
        changed = False
        profile_changed = False
        memory_ids: list[str] = []
        has_delete = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._purge_expired_nonces(user_id, now)
            receipt = self._fetch_batch_receipt(user_id, batch_id, body_digest)
            if receipt is not None:
                conn.commit()
                return receipt
            self._assert_batch_not_tombstoned(user_id, batch_id, now)
            request = self._request_row(user_id, request_id)
            self._assert_request_open(request, now)
            self._check_revision(int(request["revision"]), expected_request_revision, "request")
            profile_revision = self._profile_revision(user_id)
            self._check_revision(profile_revision, expected_profile_revision, "profile")
            self._call_failure_hook("begin", {"batch_id": batch_id, "request_id": request_id})
            for action in actions:
                result = self._apply_action(
                    user_id,
                    request_id,
                    action,
                    now,
                )
                memory_ids.extend(result["memory_ids"])
                has_delete = has_delete or action.get("op") == "delete"
                changed = changed or result["changed"]
                profile_changed = profile_changed or result["profile_changed"]
                needs_vacuum = needs_vacuum or result["needs_vacuum"]
                self._call_failure_hook("after_action", {"op": action.get("op"), "batch_id": batch_id})
            if changed:
                new_request_revision = int(request["revision"]) + 1
                retention = min(
                    now + _REQUEST_INACTIVITY,
                    _parse_datetime(request["max_until"], "max_until", allow_none=False),
                )
                conn.execute(
                    """
                    UPDATE requests SET revision=?, updated_at=?, retention_until=?
                    WHERE id=? AND user_id=?
                    """,
                    (new_request_revision, _iso(now), _iso(retention), request_id, user_id),
                )
            else:
                new_request_revision = int(request["revision"])
            if profile_changed:
                profile_revision = self._bump_profile(user_id)
            else:
                profile_revision = self._profile_revision(user_id)
            self._call_failure_hook("before_receipt", {"batch_id": batch_id})
            result = {
                "memory_ids": list(dict.fromkeys(memory_ids)),
                "request_revision": new_request_revision,
                "profile_revision": profile_revision,
                "batch_id": batch_id,
                "request_id": request_id,
            }
            if has_delete:
                # A deletion replay is recognized by an opaque 24-hour nonce.
                # It intentionally carries neither the target ID nor the
                # action digest once the target has been physically removed.
                conn.execute(
                    """
                    INSERT INTO deletion_receipts
                    (user_id,batch_id,request_id,opaque,command_fingerprint,expires_at,request_revision,profile_revision,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        user_id,
                        batch_id,
                        request_id,
                        _new_id(),
                        body_digest,
                        _iso(now + _DELETION_RECEIPT_TTL),
                        new_request_revision,
                        profile_revision,
                        _iso(now),
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO batch_receipts
                    (user_id,batch_id,request_id,request_body_digest,memory_ids_json,request_revision,profile_revision,created_at)
                    VALUES (?,?,?,?,?,?,?,?)
                    """,
                    (
                        user_id,
                        batch_id,
                        request_id,
                        body_digest,
                        _as_json(result["memory_ids"]),
                        new_request_revision,
                        profile_revision,
                        _iso(now),
                    ),
                )
            self._call_failure_hook("commit", {"batch_id": batch_id})
            conn.commit()
        except StyleMateError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
            raise _fail("storage_failed", "memory batch was rolled back") from exc
        if needs_vacuum:
            self._vacuum()
        return result

    def _validate_action_shape(self, action: Mapping[str, Any]) -> None:
        op = action.get("op")
        if op == "create":
            allowed = {"op", "memory"} | _MEMORY_PAYLOAD_KEYS
        elif op in {"confirm", "promote"}:
            allowed = {"op", "memory_id", "expected_version", "evidence_ref", "consent_ref"}
        elif op in {"withdraw", "delete"}:
            allowed = {"op", "memory_id", "expected_version", "evidence_ref"}
        elif op == "replace":
            allowed = (
                {"op", "memory_id", "expected_version", "evidence_ref", "consent_ref", "memory", "new_memory"}
                | _MEMORY_PAYLOAD_KEYS
            )
        else:
            raise _fail("invalid_input", "unsupported memory action")
        unknown = set(action) - allowed
        if unknown:
            raise _fail("invalid_input", "unknown action field")

    def _apply_action(
        self, user_id: str, request_id: str, action: Mapping[str, Any], now: datetime
    ) -> dict[str, Any]:
        op = action.get("op")
        if op not in ("create", "confirm", "promote", "replace", "withdraw", "delete"):
            raise _fail("invalid_input", "unsupported memory action")
        if op == "create":
            create_payload = dict(action)
            create_payload.pop("op", None)
            memory = self._validate_memory_payload(
                create_payload, user_id=user_id, request_id=request_id, now=now
            )
            if memory["scope"] == "long_term" and not (
                memory["origin"] == "explicit" and memory["confirmed"] and memory["status"] == "active"
            ):
                raise _fail("consent_required", "direct long-term create requires explicit confirmation")
            duplicate = self._find_duplicate(memory)
            if duplicate is not None:
                return {"memory_ids": [duplicate["id"]], "changed": False, "profile_changed": False, "needs_vacuum": False}
            self._insert_memory(memory)
            self._write_event(user_id, request_id, memory["id"], op, memory["evidence_ref"], now)
            return {
                "memory_ids": [memory["id"]],
                "changed": True,
                "profile_changed": memory["scope"] == "long_term",
                "needs_vacuum": False,
            }
        memory_id = _nonblank(action.get("memory_id"), "memory_id")
        expected_version = action.get("expected_version")
        if type(expected_version) is not int or expected_version < 1:
            raise _fail("invalid_input", "expected_version is required")
        evidence_ref = _nonblank(action.get("evidence_ref"), "evidence_ref")
        row = self._memory_row(user_id, memory_id)
        if int(row["version"]) != expected_version:
            raise _fail("version_conflict", "memory version does not match")
        if row["scope"] == "short_term" and row["request_id"] != request_id:
            raise _fail("request_mismatch", "short-term memory belongs to another request")
        if op == "confirm":
            if row["status"] != "candidate":
                return {"memory_ids": [memory_id], "changed": False, "profile_changed": False, "needs_vacuum": False}
            consent_ref = action.get("consent_ref")
            if row["scope"] == "long_term":
                consent_ref = _nonblank(consent_ref, "consent_ref")
            self.connection.execute(
                """
                UPDATE memories SET origin='explicit',confirmed=1,status='active',version=version+1,
                    evidence_ref=?,consent_ref=COALESCE(?,consent_ref) WHERE id=? AND user_id=?
                """,
                (evidence_ref, consent_ref, memory_id, user_id),
            )
            self._write_event(user_id, request_id, memory_id, op, evidence_ref, now)
            return {"memory_ids": [memory_id], "changed": True, "profile_changed": row["scope"] == "long_term", "needs_vacuum": False}
        if op == "promote":
            consent_ref = _nonblank(action.get("consent_ref"), "consent_ref")
            if row["scope"] == "long_term" and row["status"] == "active":
                return {"memory_ids": [memory_id], "changed": False, "profile_changed": False, "needs_vacuum": False}
            if row["scope"] != "short_term" or row["status"] != "active" or not row["confirmed"]:
                raise _fail("invalid_transition", "only an active confirmed short-term memory can be promoted")
            target = self._memory_dict(row)
            target.update(
                {
                    "id": _new_id(),
                    "scope": "long_term",
                    "request_id": None,
                    "origin": "explicit",
                    "confirmed": True,
                    "status": "active",
                    "version": 1,
                    "created_at": _iso(now),
                    "retention_until": _iso(now + _LONG_TERM_RETENTION),
                    "evidence_ref": evidence_ref,
                    "consent_ref": consent_ref,
                }
            )
            if target["selector"].get("slot_id") is not None:
                raise _fail("invalid_input", "long-term memory cannot carry request slot_id")
            duplicate = self._find_duplicate(target)
            if duplicate is not None:
                # A prior retry may already have made the same long-term
                # representative.  Preserve the short-term source and return
                # the existing representative instead of making a copy.
                return {"memory_ids": [duplicate["id"]], "changed": False, "profile_changed": False, "needs_vacuum": False}
            self._insert_memory(target)
            self._write_event(user_id, request_id, target["id"], op, evidence_ref, now)
            return {"memory_ids": [target["id"]], "changed": True, "profile_changed": True, "needs_vacuum": False}
        if op == "replace":
            if row["status"] not in ("candidate", "active"):
                raise _fail("invalid_transition", "only active or candidate memories can be replaced")
            replacement = action.get("memory")
            if not isinstance(replacement, Mapping):
                replacement = action.get("new_memory")
            if isinstance(replacement, Mapping):
                payload = dict(replacement)
                for key in ("evidence_ref", "consent_ref"):
                    if key in action and key not in payload:
                        payload[key] = action[key]
            else:
                payload = {
                    key: value
                    for key, value in action.items()
                    if key not in {"op", "memory_id", "expected_version"}
                }
            payload["scope"] = payload.get("scope", row["scope"])
            if payload["scope"] != row["scope"]:
                raise _fail("invalid_transition", "replace cannot change memory scope")
            payload["family_id"] = row["family_id"]
            payload["origin"] = "explicit"
            payload["confirmed"] = True
            payload["status"] = "active"
            payload["evidence_ref"] = evidence_ref
            if payload["scope"] == "long_term":
                payload["consent_ref"] = _nonblank(payload.get("consent_ref"), "consent_ref")
            new_memory = self._validate_memory_payload(
                payload,
                user_id=user_id,
                request_id=request_id,
                now=now,
                default_scope=row["scope"],
                family_id=row["family_id"],
                force_explicit=True,
            )
            duplicate = self._find_duplicate(new_memory)
            if duplicate is not None:
                # Replacing an item with its own meaning is a no-op.  Treating
                # the old row as a duplicate and then superseding it would
                # create an endless chain on retries.
                if duplicate["id"] == memory_id:
                    return {"memory_ids": [duplicate["id"]], "changed": False, "profile_changed": False, "needs_vacuum": False}
                # The requested meaning already has an active representative.
                # Close the source atomically so two active meanings do not
                # survive a semantic replacement.
                self.connection.execute(
                    """
                    UPDATE memories SET status='superseded',version=version+1,retention_until=?
                    WHERE id=? AND user_id=?
                    """,
                    (self._closed_retention(row["retention_until"], now), memory_id, user_id),
                )
                self._write_event(user_id, request_id, memory_id, op, evidence_ref, now)
                return {"memory_ids": [duplicate["id"]], "changed": True, "profile_changed": row["scope"] == "long_term", "needs_vacuum": False}
            self._insert_memory(new_memory)
            new_id = new_memory["id"]
            self.connection.execute(
                """
                UPDATE memories SET status='superseded',version=version+1,retention_until=?
                WHERE id=? AND user_id=?
                """,
                (self._closed_retention(row["retention_until"], now), memory_id, user_id),
            )
            self._write_event(user_id, request_id, memory_id, op, evidence_ref, now)
            return {"memory_ids": [new_id], "changed": True, "profile_changed": row["scope"] == "long_term", "needs_vacuum": False}
        if op == "withdraw":
            family_rows = self.connection.execute(
                """
                SELECT * FROM memories WHERE user_id=? AND family_id=?
                  AND status IN ('candidate','active')
                """,
                (user_id, row["family_id"]),
            ).fetchall()
            if not family_rows:
                raise _fail("invalid_transition", "memory family is already closed")
            for family_row in family_rows:
                self.connection.execute(
                    """
                    UPDATE memories SET status='withdrawn',confirmed=0,version=version+1,retention_until=?
                    WHERE id=? AND user_id=?
                    """,
                    (self._closed_retention(family_row["retention_until"], now), family_row["id"], user_id),
                )
            self._write_event(user_id, request_id, memory_id, op, evidence_ref, now)
            ids = [r["id"] for r in family_rows]
            return {"memory_ids": ids, "changed": True, "profile_changed": any(r["scope"] == "long_term" for r in family_rows), "needs_vacuum": False}
        # delete: remove the entire family and any receipts/events that expose its IDs.
        family_rows = self.connection.execute(
            "SELECT id,scope FROM memories WHERE user_id=? AND family_id=?", (user_id, row["family_id"])
        ).fetchall()
        ids = [r["id"] for r in family_rows]
        self._write_event(user_id, request_id, memory_id, op, evidence_ref, now)
        for receipt in self.connection.execute(
            "SELECT user_id,batch_id,memory_ids_json FROM batch_receipts WHERE user_id=?", (user_id,)
        ).fetchall():
            receipt_ids = set(json.loads(receipt["memory_ids_json"]))
            if receipt_ids.intersection(ids):
                self.connection.execute(
                    """
                    INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                    VALUES (?,?,?)
                    """,
                    (receipt["user_id"], receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                )
                self.connection.execute(
                    "DELETE FROM batch_receipts WHERE user_id=? AND batch_id=?",
                    (receipt["user_id"], receipt["batch_id"]),
                )
        placeholders = ",".join("?" for _ in ids)
        if ids:
            self.connection.execute(
                f"DELETE FROM events WHERE user_id=? AND memory_id IN ({placeholders})",
                [user_id, *ids],
            )
        self.connection.execute(
            "DELETE FROM memories WHERE user_id=? AND family_id=?", (user_id, row["family_id"])
        )
        return {"memory_ids": ids, "changed": True, "profile_changed": any(r["scope"] == "long_term" for r in family_rows), "needs_vacuum": True}

    def snapshot(self, user_id: str, request_id: str) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        now = self._now()
        row = self._request_row(user_id, request_id)
        self._assert_request_retained(row, now)
        if row["status"] != "open":
            raise _fail("request_closed", "request is not open")
        rows = self.connection.execute(
            """
            SELECT * FROM memories
            WHERE user_id=? AND (scope='long_term' OR (scope='short_term' AND request_id=?))
            ORDER BY created_at,id
            """,
            (user_id, request_id),
        ).fetchall()
        return {
            "request": self._request_dict(row),
            "profile_revision": self._profile_revision(user_id),
            "memories": [self._memory_dict(memory) for memory in rows],
            "now": _iso(now),
        }

    def _vacuum(self) -> None:
        # VACUUM requires a clean transaction.  SQLite's secure_delete pragma
        # remains enabled after the operation.
        self.connection.execute("VACUUM")

    def prune_expired(self, user_id: str | None = None) -> dict[str, int]:
        if user_id is not None:
            user_id = _nonblank(user_id, "user_id")
        now = self._now()
        conn = self.connection
        needs_vacuum = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            request_query = "SELECT id,user_id,input_id,retention_until FROM requests"
            request_args: tuple[Any, ...] = ()
            if user_id:
                request_query += " WHERE user_id=?"
                request_args = (user_id,)
            request_rows = [
                row
                for row in conn.execute(request_query, request_args).fetchall()
                if _parse_datetime(row["retention_until"], "retention_until", allow_none=False) <= now
            ]
            request_ids = [r["id"] for r in request_rows]
            # Collect these before the request cascade so the result reports
            # all removed short-term rows as well as independently expired
            # long-term rows.
            memory_query = "SELECT id,retention_until FROM memories"
            memory_args: list[Any] = []
            if user_id:
                memory_query += " WHERE user_id=?"
                memory_args.append(user_id)
            expired_memory_rows = [
                row
                for row in conn.execute(memory_query, memory_args).fetchall()
                if _parse_datetime(row["retention_until"], "retention_until", allow_none=False) <= now
            ]
            memory_ids = [r["id"] for r in expired_memory_rows]
            if request_ids:
                request_placeholders = ",".join("?" for _ in request_ids)
                request_memory_query = f"SELECT id FROM memories WHERE request_id IN ({request_placeholders})"
                request_memory_rows = conn.execute(request_memory_query, request_ids).fetchall()
                memory_ids.extend(r["id"] for r in request_memory_rows)
                memory_ids = list(dict.fromkeys(memory_ids))
                for request_row in request_rows:
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO request_tombstones(user_id,input_id,expires_at)
                        VALUES (?,?,?)
                        """,
                        (request_row["user_id"], request_row["input_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                    )
                    for receipt in conn.execute(
                        "SELECT batch_id FROM batch_receipts WHERE user_id=? AND request_id=?",
                        (request_row["user_id"], request_row["id"]),
                    ).fetchall():
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                            VALUES (?,?,?)
                            """,
                            (request_row["user_id"], receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                        )
                    for receipt in conn.execute(
                        "SELECT batch_id FROM deletion_receipts WHERE user_id=? AND request_id=?",
                        (request_row["user_id"], request_row["id"]),
                    ).fetchall():
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                            VALUES (?,?,?)
                            """,
                            (request_row["user_id"], receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                        )
            if request_ids:
                placeholders = ",".join("?" for _ in request_ids)
                conn.execute(f"DELETE FROM requests WHERE id IN ({placeholders})", request_ids)
                needs_vacuum = True
            if memory_ids:
                placeholders = ",".join("?" for _ in memory_ids)
                receipt_rows = conn.execute(
                    "SELECT user_id,batch_id,memory_ids_json FROM batch_receipts"
                ).fetchall()
                for receipt in receipt_rows:
                    if set(json.loads(receipt["memory_ids_json"])).intersection(memory_ids):
                        conn.execute(
                            """
                            INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                            VALUES (?,?,?)
                            """,
                            (receipt["user_id"], receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                        )
                        conn.execute(
                            "DELETE FROM batch_receipts WHERE user_id=? AND batch_id=?",
                            (receipt["user_id"], receipt["batch_id"]),
                        )
                conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", memory_ids)
                conn.execute(f"DELETE FROM events WHERE memory_id IN ({placeholders})", memory_ids)
                needs_vacuum = True
            if user_id:
                conn.execute("DELETE FROM batch_receipts WHERE user_id=? AND request_id NOT IN (SELECT id FROM requests)", (user_id,))
            else:
                conn.execute("DELETE FROM batch_receipts WHERE request_id NOT IN (SELECT id FROM requests)")
            for table, key_columns in (
                ("request_tombstones", ("user_id", "input_id")),
                ("batch_tombstones", ("user_id", "batch_id")),
                ("deletion_receipts", ("user_id", "batch_id")),
            ):
                nonce_rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                for nonce in nonce_rows:
                    if _parse_datetime(nonce["expires_at"], "expires_at", allow_none=False) <= now:
                        where = " AND ".join(f"{column}=?" for column in key_columns)
                        conn.execute(
                            f"DELETE FROM {table} WHERE {where}",
                            tuple(nonce[column] for column in key_columns),
                        )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        if needs_vacuum:
            self._vacuum()
        return {"requests": len(request_ids), "memories": len(memory_ids)}

    def delete_request(self, user_id: str, request_id: str) -> dict[str, Any]:
        user_id = _nonblank(user_id, "user_id")
        request_id = _nonblank(request_id, "request_id")
        conn = self.connection
        now = self._now()
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self._request_row(user_id, request_id)
            memory_rows = conn.execute(
                "SELECT id FROM memories WHERE user_id=? AND request_id=?", (user_id, request_id)
            ).fetchall()
            ids = [r["id"] for r in memory_rows]
            receipt_rows = conn.execute(
                "SELECT batch_id FROM batch_receipts WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchall()
            deletion_receipt_rows = conn.execute(
                "SELECT batch_id FROM deletion_receipts WHERE user_id=? AND request_id=?",
                (user_id, request_id),
            ).fetchall()
            conn.execute(
                """
                INSERT OR REPLACE INTO request_tombstones(user_id,input_id,expires_at)
                VALUES (?,?,?)
                """,
                (user_id, row["input_id"], _iso(now + _DELETION_RECEIPT_TTL)),
            )
            for receipt in receipt_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                    VALUES (?,?,?)
                    """,
                    (user_id, receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                )
            for receipt in deletion_receipt_rows:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO batch_tombstones(user_id,batch_id,expires_at)
                    VALUES (?,?,?)
                    """,
                    (user_id, receipt["batch_id"], _iso(now + _DELETION_RECEIPT_TTL)),
                )
            conn.execute("DELETE FROM requests WHERE id=? AND user_id=?", (request_id, user_id))
            conn.execute("DELETE FROM batch_receipts WHERE user_id=? AND request_id=?", (user_id, request_id))
            conn.execute("DELETE FROM events WHERE user_id=? AND request_id=?", (user_id, request_id))
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        if ids:
            self._vacuum()
        return {"request_id": request_id, "memory_ids": ids, "deleted": True}

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


__all__ = ["MemoryStore"]
