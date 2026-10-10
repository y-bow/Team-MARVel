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


# ---------------------------------------------------------------------------
# Clarification responses (structured field)
# ---------------------------------------------------------------------------

def test_chat_clarification_includes_structured_field(client, mock_provider):
    """needs_clarification status must carry a structured clarification object."""
    question = "Could you please tell me your state and education level?"
    mock_provider.generate.return_value = make_text_response(question)
    data = client.post("/api/chat", json={"message": "Help me"}).get_json()
    assert data["status"] == "needs_clarification"
    assert data.get("clarification") is not None
    assert data["clarification"]["question"] == question


def test_chat_clarification_has_options_list(client, mock_provider):
    mock_provider.generate.return_value = make_text_response("Which course?")
    data = client.post("/api/chat", json={"message": "Help me"}).get_json()
    assert data["clarification"]["question"] == "Which course?"
    assert isinstance(data["clarification"]["options"], list)


def test_chat_completed_status_has_no_clarification(client, mock_provider):
    mock_provider.generate.return_value = make_text_response("Here is the answer.")
    data = client.post("/api/chat", json={"message": "Hi"}).get_json()
    assert data["status"] == "completed"
    assert data.get("clarification") is None


# ---------------------------------------------------------------------------
# Tool event status normalisation (completed / failed)
# ---------------------------------------------------------------------------

def test_chat_success_tool_event_is_completed(client, mock_provider):
    mock_provider.generate.side_effect = [
        make_function_call_response("search_schemes", {"query": "scholarship"}),
        make_text_response("Found some scholarships."),
    ]
    data = client.post("/api/chat", json={"message": "scholarships"}).get_json()
    for event in data["events"]:
        assert event["status"] in ("completed", "failed")
    search_events = [e for e in data["events"] if e["tool"] == "search_schemes"]
    assert search_events
    assert all(e["status"] == "completed" for e in search_events)


def test_chat_unregistered_tool_event_is_failed(client, mock_provider):
    mock_provider.generate.side_effect = [
        make_function_call_response("hack_system", {"payload": "evil"}),
        make_text_response("I cannot perform that action."),
    ]
    data = client.post("/api/chat", json={"message": "Do something"}).get_json()
    bad_events = [e for e in data["events"] if e["tool"] == "hack_system"]
    assert len(bad_events) == 1
    assert bad_events[0]["status"] == "failed"


def test_chat_tool_error_result_is_failed(client, mock_provider):
    """A tool that returns an error dict (not a raise) is reported as failed."""
    mock_provider.generate.side_effect = [
        make_function_call_response(
            "search_schemes", {"query": "x", "education_level": "not-a-level"}
        ),
        make_text_response("Let me help you differently."),
    ]
    data = client.post("/api/chat", json={"message": "Find schemes"}).get_json()
    search_events = [e for e in data["events"] if e["tool"] == "search_schemes"]
    assert search_events
    assert all(e["status"] == "failed" for e in search_events)


# ---------------------------------------------------------------------------
# Optional rich fields (matches / eligibility / documents / steps)
# ---------------------------------------------------------------------------

def test_chat_matches_populated_from_search(client, mock_provider):
    mock_provider.generate.side_effect = [
        make_function_call_response("search_schemes", {"query": "SC scholarship"}),
        make_text_response("Here are matching schemes."),
    ]
    data = client.post("/api/chat", json={"message": "SC scholarships"}).get_json()
    assert data.get("matches")
    for match in data["matches"]:
        assert match["id"]
        assert match["title"]
        # Matches without a source URL must carry an empty string, never a
        # broken or fabricated link.
        assert isinstance(match["url"], str)
        assert match["url"] == "" or match["url"].startswith(
            ("http://", "https://")
        )


def test_chat_eligibility_populated_from_check(client, mock_provider):
    # education+caste satisfied, percentage below minimum (unsatisfied),
    # income omitted (unknown) — exercises the met/missing/unknown mapping.
    mock_provider.generate.side_effect = [
        make_function_call_response(
            "check_eligibility",
            {
                "scheme_id": "test-sc-scholarship",
                "student_info": {
                    "education_level": "10th",
                    "caste_category": "SC",
                    "percentage": 40.0,
                },
            },
        ),
        make_text_response("Here is your eligibility."),
    ]
    data = client.post("/api/chat", json={"message": "Am I eligible?"}).get_json()
    eligibility = data.get("eligibility")
    assert eligibility is not None
    assert isinstance(eligibility["met"], list)
    assert isinstance(eligibility["missing"], list)
    assert isinstance(eligibility["unknown"], list)

    def rows_with(rows, criterion):
        return [r for r in rows if criterion in r]

    assert any("education_level" in r for r in eligibility["met"])
    assert any("caste_category" in r for r in eligibility["met"])
    assert any("percentage" in r for r in eligibility["missing"])
    assert any("annual_family_income" in r for r in eligibility["unknown"])
    assert rows_with(eligibility["missing"], "education_level") == []
    assert rows_with(eligibility["unknown"], "percentage") == []


def test_chat_documents_and_steps_from_requirements(client, mock_provider):
    mock_provider.generate.side_effect = [
        make_function_call_response("get_requirements", {"scheme_id": "test-sc-scholarship"}),
        make_text_response("Here are the requirements."),
    ]
    data = client.post("/api/chat", json={"message": "What do I need?"}).get_json()
    assert data.get("documents")
    assert data.get("steps")
    assert all(isinstance(d, str) for d in data["documents"])
    assert all(isinstance(s, str) for s in data["steps"])


def test_chat_optional_fields_absent_without_supporting_tools(client, mock_provider):
    """Plain text answer must not emit matches/eligibility/documents/steps."""
    mock_provider.generate.return_value = make_text_response("Just an answer.")
    data = client.post("/api/chat", json={"message": "Hello"}).get_json()
    for field in ("clarification", "matches", "eligibility", "documents", "steps"):
        assert field not in data, f"Unexpected field present: {field}"


def test_chat_events_never_emit_ok_or_error(client, mock_provider):
    """API event statuses must use the client vocabulary only."""
    mock_provider.generate.side_effect = [
        make_function_call_response("search_schemes", {"query": "scholarship"}),
        make_text_response("Found some."),
    ]
    data = client.post("/api/chat", json={"message": "scholarships"}).get_json()
    for event in data["events"]:
        assert event["status"] in ("queued", "running", "completed", "failed")


# ---------------------------------------------------------------------------
# Explicit clarification tool and grounded-status rules
# ---------------------------------------------------------------------------

def test_chat_ask_clarification_tool_sets_structured_status(client, mock_provider):
    """An ask_clarification tool call is an authoritative clarification request."""
    mock_provider.generate.return_value = make_function_call_response(
        "ask_clarification",
        {"question": "Which state are you from?", "options": ["Maharashtra", "Karnataka"]},
    )
    data = client.post("/api/chat", json={"message": "Help me"}).get_json()
    assert data["status"] == "needs_clarification"
    assert data["clarification"]["question"] == "Which state are you from?"
    assert data["clarification"]["options"] == ["Maharashtra", "Karnataka"]
    mock_provider.generate.assert_called_once()


def test_chat_ask_clarification_event_is_completed(client, mock_provider):
    mock_provider.generate.return_value = make_function_call_response(
        "ask_clarification", {"question": "Which course?"}
    )
    data = client.post("/api/chat", json={"message": "Help me"}).get_json()
    assert any(
        e["tool"] == "ask_clarification" and e["status"] == "completed"
        for e in data["events"]
    )


def test_chat_grounded_answer_ending_with_question_is_completed(client, mock_provider):
    """Trailing offer-questions in grounded answers must not flip to clarification."""
    mock_provider.generate.side_effect = [
        make_function_call_response("search_schemes", {"query": "SC"}),
        make_text_response("Here are schemes. Would you like me to check eligibility?"),
    ]
    data = client.post("/api/chat", json={"message": "SC scholarships"}).get_json()
    assert data["status"] == "completed"
    assert data.get("clarification") is None


def test_chat_matches_deduplicated_across_searches(client, mock_provider):
    mock_provider.generate.side_effect = [
        make_function_call_response("search_schemes", {"query": "SC"}),
        make_function_call_response("search_schemes", {"query": "SC"}),
        make_text_response("Done."),
    ]
    data = client.post("/api/chat", json={"message": "SC"}).get_json()
    ids = [m["id"] for m in data["matches"]]
    assert len(ids) == len(set(ids))
