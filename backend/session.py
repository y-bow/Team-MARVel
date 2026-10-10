"""
session.py — server-side conversation persistence (SQLite).

Replaces the in-process _CONVERSATIONS dict with a durable store keyed by
conversation_id. A lightweight session cookie links requests to a server-
side session so conversations survive process restarts and "clear my data"
(DELETE /api/session) works.

Tables:
  sessions     — session metadata (created_at, last_seen).
  conversations — conversation history per conversation_id, bound to a session.

Design choices:
  - One connection per operation (no cross-thread sharing concerns).
  - WAL mode for better concurrent read performance.
  - Session cookie is httpOnly + SameSite=Lax; never carries data.
  - Profile data is NOT stored server-side (stays client-owned per audit).
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.genai import types


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _history_to_json(history: list[types.Content]) -> str:
    return json.dumps(
        [item.model_dump(exclude_none=True) for item in history],
        ensure_ascii=False,
    )


def _history_from_json(raw: str) -> list[types.Content]:
    return [types.Content.model_validate(item) for item in json.loads(raw)]


# ---------------------------------------------------------------------------
# Cookie helpers
# ---------------------------------------------------------------------------

SESSION_COOKIE = "edusaarthi_session"
SESSION_TTL_DAYS = 30


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_session_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class SQLiteConversationStore:
    """
    Dict-like conversation store backed by SQLite.

    The public API mirrors the dict patterns used by AgentLoop:
      - ``store.get(conversation_id)`` → history list or None
      - ``store[conversation_id] = history`` — upsert
      - ``conversation_id in store`` — existence check
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._init_schema()

    # ---- schema ----

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    last_seen  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id TEXT PRIMARY KEY,
                    session_id      TEXT,
                    history_json    TEXT NOT NULL,
                    updated_at      TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                );

                CREATE INDEX IF NOT EXISTS idx_conv_session
                    ON conversations(session_id);
            """)

    # ---- dict-like conversation access (used by AgentLoop) ----

    def get(self, conversation_id: str) -> Optional[list[types.Content]]:
        row = self._connect().execute(
            "SELECT history_json FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if row is None:
            return None
        return _history_from_json(row[0])

    def __setitem__(self, conversation_id: str, history: list[types.Content]) -> None:
        payload = _history_to_json(history)
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO conversations (conversation_id, history_json, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(conversation_id) DO UPDATE SET
                       history_json = excluded.history_json,
                       updated_at   = excluded.updated_at""",
                (conversation_id, payload, now),
            )

    def __contains__(self, conversation_id: str) -> bool:
        row = self._connect().execute(
            "SELECT 1 FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        return row is not None

    # ---- session management ----

    def ensure_session(self, session_id: Optional[str]) -> str:
        """
        Return a valid session_id — reuse the supplied one if it exists,
        otherwise create a new session row and return its id.
        """
        if session_id:
            row = self._connect().execute(
                "SELECT session_id FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            if row:
                self._touch_session(session_id)
                return session_id

        new_id = _make_session_id()
        now = _utcnow_iso()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO sessions (session_id, created_at, last_seen) VALUES (?, ?, ?)",
                (new_id, now, now),
            )
        return new_id

    def _touch_session(self, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE sessions SET last_seen = ? WHERE session_id = ?",
                (_utcnow_iso(), session_id),
            )

    def bind_conversation(self, conversation_id: str, session_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                """UPDATE conversations SET session_id = ?
                   WHERE conversation_id = ? AND (session_id IS NULL OR session_id = '')""",
                (session_id, conversation_id),
            )

    def delete_session(self, session_id: str) -> int:
        """Delete all conversations for a session and the session itself."""
        with self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM conversations WHERE session_id = ?", (session_id,)
            )
            deleted_convs = cur.rowcount
            conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        return deleted_convs

    def count(self) -> int:
        row = self._connect().execute("SELECT COUNT(*) FROM conversations").fetchone()
        return row[0] if row else 0

    def sweep_stale(self, ttl_days: int = SESSION_TTL_DAYS) -> int:
        """Delete sessions (and their conversations) not seen in ttl_days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=ttl_days)).isoformat()
        stale_ids = [
            r[0]
            for r in self._connect().execute(
                "SELECT session_id FROM sessions WHERE last_seen < ?", (cutoff,)
            ).fetchall()
        ]
        if not stale_ids:
            return 0
        deleted = 0
        with self._connect() as conn:
            for sid in stale_ids:
                cur = conn.execute(
                    "DELETE FROM conversations WHERE session_id = ?", (sid,)
                )
                deleted += cur.rowcount
                conn.execute("DELETE FROM sessions WHERE session_id = ?", (sid,))
        return deleted