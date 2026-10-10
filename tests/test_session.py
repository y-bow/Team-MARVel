"""
test_session.py — SQLite conversation store and session cookie tests.

Covers the persistence layer behind Phase 3 (no-login session-based
conversation continuity).
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from google.genai import types

from backend.agent import InMemoryStore
from backend.session import SQLiteConversationStore, SESSION_COOKIE


# ---------------------------------------------------------------------------
# In-memory store smoke test
# ---------------------------------------------------------------------------

class TestInMemoryStore:
    def test_get_set_contains(self):
        store = InMemoryStore()
        assert "abc" not in store
        assert store.get("abc") is None

        history = [types.Content(role="user", parts=[types.Part(text="hi")])]
        store["abc"] = history
        assert "abc" in store
        assert store.get("abc")[0].parts[0].text == "hi"


# ---------------------------------------------------------------------------
# SQLite store unit tests
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "test_sessions.db")


@pytest.fixture
def store(tmp_db):
    return SQLiteConversationStore(tmp_db)


class TestSQLiteStore:
    def test_roundtrip_history(self, store):
        history = [
            types.Content(role="user", parts=[types.Part(text="find scholarships")]),
            types.Content(role="model", parts=[
                types.Part(function_call=types.FunctionCall(name="search_schemes", args={"query": "SC"}))
            ]),
            types.Content(role="user", parts=[
                types.Part.from_function_response(name="search_schemes", response={"output": {"result_count": 1}})
            ]),
        ]
        store["conv-1"] = history
        loaded = store.get("conv-1")
        assert len(loaded) == 3
        assert loaded[0].parts[0].text == "find scholarships"
        assert loaded[1].parts[0].function_call.name == "search_schemes"
        assert loaded[2].parts[0].function_response.response == {"output": {"result_count": 1}}

    def test_get_missing_returns_none(self, store):
        assert store.get("nonexistent") is None

    def test_contains_false_for_missing(self, store):
        assert "nonexistent" not in store

    def test_overwrite_history(self, store):
        store["c"] = [types.Content(role="user", parts=[types.Part(text="v1")])]
        store["c"] = [types.Content(role="user", parts=[types.Part(text="v2")])]
        assert store.get("c")[0].parts[0].text == "v2"

    def test_ensure_session_creates_new(self, store):
        sid = store.ensure_session(None)
        assert len(sid) == 32  # hex uuid
        assert store.ensure_session(sid) == sid  # reuse

    def test_ensure_session_rejects_unknown(self, store):
        sid = store.ensure_session("totally-fake")
        assert len(sid) == 32
        assert sid != "totally-fake"

    def test_bind_conversation(self, store):
        store["c1"] = [types.Content(role="user", parts=[types.Part(text="hi")])]
        sid = store.ensure_session(None)
        store.bind_conversation("c1", sid)
        # Conversation still accessible after bind
        assert store.get("c1") is not None

    def test_delete_session_clears_conversations(self, store):
        sid = store.ensure_session(None)
        store["c1"] = [types.Content(role="user", parts=[types.Part(text="hi")])]
        store.bind_conversation("c1", sid)
        deleted = store.delete_session(sid)
        assert deleted == 1
        assert store.get("c1") is None

    def test_count(self, store):
        assert store.count() == 0
        store["a"] = [types.Content(role="user", parts=[types.Part(text="a")])]
        store["b"] = [types.Content(role="user", parts=[types.Part(text="b")])]
        assert store.count() == 2


# ---------------------------------------------------------------------------
# App-level session integration (via test client)
# ---------------------------------------------------------------------------

@pytest.fixture
def session_app(tmp_path, repository, mock_provider):
    """Flask app wired with SQLite session store and mock provider."""
    from backend.config import Config
    from backend.app import create_app

    db_path = str(tmp_path / "sessions.db")
    cfg = Config(
        openrouter_api_key="test",
        openrouter_model="test/model",
        sessions_db=db_path,
        host="127.0.0.1",
        port=5001,
        debug=False,
        max_iterations=8,
        max_search_results=10,
        max_message_length=4000,
        max_answer_length=8000,
        deadline_stale_days=30,
        data_path=repository._data_path,
        version="test",
    )
    return create_app(config=cfg, repository=repository, provider=mock_provider)


@pytest.fixture
def session_client(session_app):
    session_app.config["TESTING"] = True
    return session_app.test_client()


class TestSessionCookie:
    def test_first_request_sets_session_cookie(self, session_client, mock_provider):
        from tests.helpers import make_text_response
        mock_provider.generate.return_value = make_text_response("Hello!")
        resp = session_client.post("/api/chat", json={"message": "Hi"})
        assert resp.status_code == 200
        assert SESSION_COOKIE in resp.headers.get("Set-Cookie", "")

    def test_multi_turn_persists_history(self, session_client, mock_provider):
        from tests.helpers import make_text_response
        mock_provider.generate.return_value = make_text_response("Hello!")
        r1 = session_client.post("/api/chat", json={"message": "Hi"})
        cid = r1.get_json()["conversation_id"]
        cookie = r1.headers.get("Set-Cookie", "").split(";")[0]

        mock_provider.generate.return_value = make_text_response("More info!")
        r2 = session_client.post(
            "/api/chat",
            json={"message": "Continue", "conversation_id": cid},
            headers={"Cookie": cookie},
        )
        assert r2.get_json()["conversation_id"] == cid

    def test_delete_session_clears_state(self, session_client, mock_provider):
        from tests.helpers import make_text_response
        mock_provider.generate.return_value = make_text_response("Hi!")
        r1 = session_client.post("/api/chat", json={"message": "Hi"})
        cookie = r1.headers.get("Set-Cookie", "").split(";")[0]

        r2 = session_client.delete("/api/session", headers={"Cookie": cookie})
        assert r2.status_code == 200
        data = r2.get_json()
        assert data["status"] == "ok"
        assert data["conversations_deleted"] >= 1
        # Cookie should be cleared
        assert "Set-Cookie" in r2.headers

    def test_delete_without_cookie_succeeds(self, session_client):
        r = session_client.delete("/api/session")
        assert r.status_code == 200
        assert r.get_json()["conversations_deleted"] == 0