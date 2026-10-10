"""
test_chat.py — tests for POST /api/chat request validation and basic responses.
"""

import pytest
from tests.helpers import make_text_response, make_function_call_response


# ---------------------------------------------------------------------------
# Request validation
# ---------------------------------------------------------------------------

def test_chat_missing_message_field(client):
    response = client.post("/api/chat", json={"conversation_id": None})
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "MISSING_FIELD"


def test_chat_empty_body(client):
    response = client.post(
        "/api/chat",
        data="",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_chat_non_json_content_type(client):
    response = client.post(
        "/api/chat",
        data="message=hello",
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "INVALID_CONTENT_TYPE"


def test_chat_malformed_json(client):
    response = client.post(
        "/api/chat",
        data="{bad json}",
        content_type="application/json",
    )
    assert response.status_code == 400


def test_chat_message_not_string(client):
    response = client.post("/api/chat", json={"message": 12345})
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "INVALID_FIELD"


def test_chat_empty_string_message(client):
    response = client.post("/api/chat", json={"message": "   "})
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "INVALID_FIELD"


def test_chat_message_too_long(client):
    long_message = "x" * 5000
    response = client.post("/api/chat", json={"message": long_message})
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "MESSAGE_TOO_LONG"


def test_chat_conversation_id_not_string(client):
    response = client.post(
        "/api/chat", json={"message": "hello", "conversation_id": 99}
    )
    assert response.status_code == 400
    data = response.get_json()
    assert data["code"] == "INVALID_FIELD"


# ---------------------------------------------------------------------------
# Successful responses
# ---------------------------------------------------------------------------

def test_chat_successful_simple_answer(client, mock_provider):
    """Simple question → text answer → no tool calls."""
    mock_provider.generate.return_value = make_text_response(
        "Here are some scholarships available to you."
    )
    response = client.post("/api/chat", json={"message": "What scholarships exist?"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "completed"
    assert "scholarships" in data["answer"]


def test_chat_response_has_required_fields(client, mock_provider):
    mock_provider.generate.return_value = make_text_response("Hello!")
    data = client.post("/api/chat", json={"message": "Hi"}).get_json()
    for field in ("conversation_id", "status", "answer", "sources", "events", "action_plan"):
        assert field in data, f"Missing field: {field}"


def test_chat_returns_conversation_id(client, mock_provider):
    mock_provider.generate.return_value = make_text_response("Hello!")
    data = client.post("/api/chat", json={"message": "Hi"}).get_json()
    assert isinstance(data["conversation_id"], str)
    assert len(data["conversation_id"]) > 0


def test_chat_null_conversation_id_creates_new(client, mock_provider):
    mock_provider.generate.return_value = make_text_response("Hello!")
    data = client.post(
        "/api/chat", json={"message": "Hi", "conversation_id": None}
    ).get_json()
    assert isinstance(data["conversation_id"], str)


def test_chat_existing_conversation_id_reused(client, mock_provider):
    """If a known conversation_id is sent, it should be preserved."""
    mock_provider.generate.return_value = make_text_response("Turn 1")
    data1 = client.post("/api/chat", json={"message": "Hi"}).get_json()
    conv_id = data1["conversation_id"]

    mock_provider.generate.return_value = make_text_response("Turn 2")
    data2 = client.post(
        "/api/chat", json={"message": "Continue", "conversation_id": conv_id}
    ).get_json()
    assert data2["conversation_id"] == conv_id


def test_chat_with_search_tool_call(client, mock_provider):
    """Model calls search_schemes, then gives a final answer."""
    mock_provider.generate.side_effect = [
        make_function_call_response(
            "search_schemes", {"query": "SC scholarship class 10"}
        ),
        make_text_response("I found 1 matching scheme for you."),
    ]
    response = client.post(
        "/api/chat",
        json={"message": "Find me SC scholarships for class 10"},
    )
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "completed"
    # At least one tool event should be recorded
    assert any(e["tool"] == "search_schemes" for e in data["events"])


def test_chat_sources_populated_from_tool(client, mock_provider):
    """Sources from search results should appear in the response."""
    mock_provider.generate.side_effect = [
        make_function_call_response(
            "search_schemes", {"query": "scholarship"}
        ),
        make_text_response("Here are some scholarships."),
    ]
    data = client.post("/api/chat", json={"message": "scholarships"}).get_json()
    # sources list should contain entries with id, title, url
    for src in data["sources"]:
        assert "id" in src
        assert "title" in src
        assert "url" in src


def test_chat_needs_clarification_status(client, mock_provider):
    """If model response ends with '?', status should be needs_clarification."""
    mock_provider.generate.return_value = make_text_response(
        "Could you please tell me your state and education level?"
    )
    data = client.post("/api/chat", json={"message": "Help me"}).get_json()
    assert data["status"] == "needs_clarification"


def test_chat_no_stack_trace_on_agent_error(client, mock_provider):
    """Internal errors must not expose stack traces to the client."""
    from backend.agent import ProviderError

    mock_provider.generate.side_effect = Exception("some internal detail")
    response = client.post("/api/chat", json={"message": "Hi"})
    assert response.status_code == 500
    data = response.get_json()
    assert "some internal detail" not in data.get("error", "")
    assert "Traceback" not in str(data)


def test_chat_provider_quota_error_returns_429(client, mock_provider):
    """Quota errors from the provider should return 429."""
    from backend.agent import ProviderError

    mock_provider.generate.side_effect = ProviderError(
        "API quota exceeded.", http_status=429
    )
    response = client.post("/api/chat", json={"message": "Hi"})
    assert response.status_code == 429
    data = response.get_json()
    assert data["code"] == "PROVIDER_ERROR"


def test_chat_provider_timeout_returns_503(client, mock_provider):
    """Server/timeout errors should return 503."""
    from backend.agent import ProviderError

    mock_provider.generate.side_effect = ProviderError(
        "Model unavailable.", http_status=503
    )
    response = client.post("/api/chat", json={"message": "Hi"})
    assert response.status_code == 503
