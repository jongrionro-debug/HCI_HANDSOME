"""Small service journal; domain objects and authorization stay in MemoryStore.

Only salted command fingerprints, pointers and safe operation codes are kept.
No command body, copied memory, conversation, provider output or API key is saved.
Domain erasure invalidates the journal, including fingerprints of redacted input.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import timedelta
from typing import Any

from .errors import StyleMateError


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


class ConsumerJournal:
    def __init__(self, store: Any, user_id: str) -> None:
        self.store, self.user_id = store, user_id
        self.db = store.connection
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS consumer_sequence (
                singleton INTEGER PRIMARY KEY CHECK(singleton=1), value INTEGER NOT NULL
            );
            INSERT OR IGNORE INTO consumer_sequence VALUES (1,0);
            CREATE TABLE IF NOT EXISTS consumer_active (
                user_id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS consumer_commands (
                user_id TEXT NOT NULL, command_id TEXT NOT NULL,
                request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                nonce TEXT NOT NULL, fingerprint TEXT NOT NULL, outcome TEXT,
                display_id TEXT REFERENCES v1_objects(id) ON DELETE CASCADE,
                PRIMARY KEY(user_id,command_id)
            );
            CREATE TABLE IF NOT EXISTS consumer_dismissals (
                display_id TEXT PRIMARY KEY REFERENCES v1_objects(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS consumer_request_reviews (
                id TEXT PRIMARY KEY, request_id TEXT NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL, request_revision INTEGER NOT NULL, profile_revision INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consumer_delete_nonces (
                user_id TEXT NOT NULL, command_id TEXT NOT NULL, nonce TEXT NOT NULL,
                fingerprint TEXT NOT NULL, expires_at TEXT NOT NULL,
                PRIMARY KEY(user_id,command_id)
            );
            CREATE TABLE IF NOT EXISTS consumer_operations (
                request_id TEXT PRIMARY KEY REFERENCES requests(id) ON DELETE CASCADE,
                user_id TEXT NOT NULL, operation TEXT NOT NULL, error_code TEXT
            );
            CREATE TRIGGER IF NOT EXISTS consumer_erasure AFTER DELETE ON v1_objects BEGIN
                DELETE FROM consumer_commands WHERE user_id=OLD.user_id;
                DELETE FROM consumer_request_reviews WHERE user_id=OLD.user_id;
            END;
        """)

    def next_version(self) -> int:
        self.db.execute("UPDATE consumer_sequence SET value=value+1 WHERE singleton=1")
        return self.db.execute("SELECT value FROM consumer_sequence WHERE singleton=1").fetchone()[0]

    def active(self) -> str | None:
        row = self.db.execute("SELECT request_id FROM consumer_active WHERE user_id=?", (self.user_id,)).fetchone()
        return row[0] if row else None

    def activate(self, request_id: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO consumer_active VALUES (?,?)", (self.user_id, request_id))

    @staticmethod
    def _digest(command: dict[str, Any], nonce: str) -> str:
        # Expected is a concurrency token, not the identity of a user action.
        body = {k: command[k] for k in ("contract_version", "request_id", "action")}
        return hashlib.sha256((nonce + canonical(body)).encode()).hexdigest()

    def lookup(self, command: dict[str, Any]) -> dict[str, Any] | None:
        self.db.execute("DELETE FROM consumer_delete_nonces WHERE expires_at<=?", (self.store._now().isoformat(),))
        for table in ("consumer_delete_nonces", "consumer_commands"):
            row = self.db.execute(f"SELECT * FROM {table} WHERE user_id=? AND command_id=?",
                                  (self.user_id, command["command_id"])).fetchone()
            if row is not None:
                if row["fingerprint"] != self._digest(command, row["nonce"]):
                    raise StyleMateError("idempotency_conflict")
                return dict(row) | ({"outcome": "applied", "deleted": True} if table == "consumer_delete_nonces" else {})
        return None

    def reserve(self, command: dict[str, Any], request_id: str) -> None:
        nonce = secrets.token_hex(24)
        self.db.execute("INSERT OR IGNORE INTO consumer_commands VALUES (?,?,?,?,?,NULL,NULL)",
                        (self.user_id, command["command_id"], request_id, nonce, self._digest(command, nonce)))

    def finish(self, command_id: str, outcome: str, display_id: str | None = None) -> None:
        self.db.execute("UPDATE consumer_commands SET outcome=?,display_id=? WHERE user_id=? AND command_id=?",
                        (outcome, display_id, self.user_id, command_id))

    def deleted(self, command: dict[str, Any]) -> None:
        # The same 24-hour, content-free replay boundary used by the store.
        self.db.execute("DELETE FROM consumer_commands WHERE user_id=?", (self.user_id,))
        nonce = secrets.token_hex(24)
        self.db.execute("INSERT INTO consumer_delete_nonces VALUES (?,?,?,?,?)",
                        (self.user_id, command["command_id"], nonce, self._digest(command, nonce),
                         (self.store._now() + timedelta(hours=24)).isoformat()))

    def operation(self, request_id: str) -> tuple[str, str | None]:
        row = self.db.execute("SELECT operation,error_code FROM consumer_operations WHERE user_id=? AND request_id=?",
                              (self.user_id, request_id)).fetchone()
        return (row[0], row[1]) if row else ("idle", None)

    def set_operation(self, request_id: str, operation: str, error_code: str | None = None) -> None:
        self.db.execute("INSERT OR REPLACE INTO consumer_operations SELECT id,?,?,? FROM requests WHERE id=? AND user_id=?",
                        (self.user_id, operation, error_code, request_id, self.user_id))

    def clear_operation(self, request_id: str) -> None:
        self.db.execute("DELETE FROM consumer_operations WHERE user_id=? AND request_id=?", (self.user_id, request_id))
