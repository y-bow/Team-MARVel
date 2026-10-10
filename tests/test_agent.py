"""
test_agent.py — unit tests for the AgentLoop logic.

Tests: iteration limit, unregistered tools, malformed args,
sequential and parallel tool calls, quota/timeout errors,
MALFORMED_FUNCTION_CALL finish reason, and invalid model output.
"""

import pytest
from unittest.mock import MagicMock

from backend.agent import AgentLoop, ProviderError, build_tool_registry
from backend.tools import STATUS_POTENTIAL_MATCH
from tests.helpers import (
    make_text_response,
    make_function_call_response,
    make_parallel_calls_response,
    make_malformed_finish_response,
)
from google.genai import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_agent(mock_provider, repository, test_config):
    registry = build_tool_registry(repository, test_config)
    return AgentLoop(
        provider=mock_provider,
        tool_registry=registry,
        config=test_config,
    )


# ---------------------------------------------------------------------------
# Iteration limit
# ---------------------------------------------------------------------------

class TestIterationLimit:
    def test_iteration_limit_hit(self, mock_provider, repository, test_config):
        """Agent should stop and return a meaningful message when limit is hit."""
        # Always return a function call so the loop never naturally terminates
        mock_provider.generate.return_value = make_function_call_response(
            "search_schemes", {"query": "scholarship"}
        )
        # Use a config with very low max_iterations
        from backend.config import Config
        low_iter_config = Config(
            openrouter_api_key="test",
            openrouter_model="test/model-not-real",
            host="127.0.0.1",
            port=5001,
            debug=False,
            max_iterations=2,  # hit after 2 rounds
            max_search_results=10,
            max_message_length=4000,
            max_answer_length=8000,
            deadline_stale_days=30,
            data_path=test_config.data_path,
            version="test",
        )
        agent = make_agent(mock_provider, repository, low_iter_config)
        result = agent.run("Find scholarships")
        assert "maximum" in result.answer.lower() or "limit" in result.answer.lower()
        # Events should record the iteration limit
        assert any("limit" in e["summary"].lower() or "iteration" in e["summary"].lower()
                   for e in result.events)


# ---------------------------------------------------------------------------
# Unregistered tool
# ---------------------------------------------------------------------------

class TestUnregisteredTool:
    def test_unregistered_tool_safe_response(self, mock_provider, repository, test_config):
        """Model calls an unregistered tool → error returned to model, loop continues."""
        mock_provider.generate.side_effect = [
            make_function_call_response("hack_system", {"payload": "evil"}),
            make_text_response("I cannot perform that action."),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Do something bad")
        # Should still complete without exception
        assert result.status in ("completed", "needs_clarification")
        # Event should show error for the unregistered tool
        unregistered_events = [e for e in result.events if e["tool"] == "hack_system"]
        assert len(unregistered_events) == 1
        assert unregistered_events[0]["status"] == "error"


# ---------------------------------------------------------------------------
# Malformed tool arguments
# ---------------------------------------------------------------------------

class TestMalformedArguments:
    def test_malformed_args_handled_gracefully(self, mock_provider, repository, test_config):
        """If model sends wrong arg types, the agent should handle it gracefully."""
        mock_provider.generate.side_effect = [
            # Pass query as a number instead of a string
            make_function_call_response("search_schemes", {"query": 9999}),
            make_text_response("I had trouble with that request."),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Find scholarships")
        # Should complete (not raise)
        assert result.answer is not None

    def test_missing_required_arg_handled(self, mock_provider, repository, test_config):
        """Missing required arg to a tool should not crash the server."""
        mock_provider.generate.side_effect = [
            make_function_call_response("check_eligibility", {}),  # missing scheme_id and student_info
            make_text_response("Let me help you differently."),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Check eligibility")
        assert result.answer is not None


# ---------------------------------------------------------------------------
# Sequential tool calls
# ---------------------------------------------------------------------------

class TestSequentialToolCalls:
    def test_two_sequential_calls(self, mock_provider, repository, test_config):
        """Search → check_eligibility → final answer."""
        mock_provider.generate.side_effect = [
            make_function_call_response(
                "search_schemes", {"query": "SC scholarship"}
            ),
            make_function_call_response(
                "check_eligibility",
                {
                    "scheme_id": "test-sc-scholarship",
                    "student_info": {
                        "education_level": "10th",
                        "caste_category": "SC",
                        "percentage": 60.0,
                        "annual_family_income": 200000,
                    },
                },
            ),
            make_text_response(
                "Based on your details, you are a potential match for the SC scholarship."
            ),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Am I eligible for SC scholarship in class 10?")
        assert result.status == "completed"
        tool_names = [e["tool"] for e in result.events]
        assert "search_schemes" in tool_names
        assert "check_eligibility" in tool_names

    def test_events_record_each_call(self, mock_provider, repository, test_config):
        mock_provider.generate.side_effect = [
            make_function_call_response("get_requirements", {"scheme_id": "test-sc-scholarship"}),
            make_function_call_response("verify_deadline", {"scheme_id": "test-sc-scholarship"}),
            make_text_response("Here are the requirements and deadline info."),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("What are the requirements and deadline?")
        tool_names = [e["tool"] for e in result.events]
        assert "get_requirements" in tool_names
        assert "verify_deadline" in tool_names


# ---------------------------------------------------------------------------
# Parallel tool calls
# ---------------------------------------------------------------------------

class TestParallelToolCalls:
    def test_parallel_calls_both_executed(self, mock_provider, repository, test_config):
        """Both tool calls in the same response should execute."""
        mock_provider.generate.side_effect = [
            make_parallel_calls_response([
                ("get_requirements", {"scheme_id": "test-sc-scholarship"}),
                ("verify_deadline", {"scheme_id": "test-sc-scholarship"}),
            ]),
            make_text_response("Here are both the requirements and deadline."),
        ]
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Give me requirements and deadline together")
        tool_names = [e["tool"] for e in result.events]
        assert "get_requirements" in tool_names
        assert "verify_deadline" in tool_names


# ---------------------------------------------------------------------------
# Provider errors
# ---------------------------------------------------------------------------

class TestProviderErrors:
    def test_quota_error_propagates(self, mock_provider, repository, test_config):
        mock_provider.generate.side_effect = ProviderError(
            "Quota exceeded", http_status=429
        )
        agent = make_agent(mock_provider, repository, test_config)
        with pytest.raises(ProviderError) as exc_info:
            agent.run("Find scholarships")
        assert exc_info.value.http_status == 429

    def test_server_error_propagates(self, mock_provider, repository, test_config):
        mock_provider.generate.side_effect = ProviderError(
            "Model unavailable", http_status=503
        )
        agent = make_agent(mock_provider, repository, test_config)
        with pytest.raises(ProviderError) as exc_info:
            agent.run("Find scholarships")
        assert exc_info.value.http_status == 503


# ---------------------------------------------------------------------------
# MALFORMED_FUNCTION_CALL finish reason
# ---------------------------------------------------------------------------

class TestMalformedFunctionCallFinish:
    def test_malformed_function_call_finish(self, mock_provider, repository, test_config):
        mock_provider.generate.return_value = make_malformed_finish_response(
            types.FinishReason.MALFORMED_FUNCTION_CALL
        )
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Find scholarships")
        # Should produce a safe user-facing message, not crash
        assert result.answer is not None
        assert "issue" in result.answer.lower() or "rephrase" in result.answer.lower()


# ---------------------------------------------------------------------------
# No candidates in response (invalid model output)
# ---------------------------------------------------------------------------

class TestInvalidModelOutput:
    def test_empty_candidates_list(self, mock_provider, repository, test_config):
        response = MagicMock()
        response.candidates = []
        mock_provider.generate.return_value = response
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Find scholarships")
        assert result.answer is not None
        assert "couldn't generate" in result.answer.lower() or "try again" in result.answer.lower()


# ---------------------------------------------------------------------------
# Conversation state preserved
# ---------------------------------------------------------------------------

class TestConversationState:
    def test_conversation_id_consistent(self, mock_provider, repository, test_config):
        mock_provider.generate.return_value = make_text_response("Hello!")
        agent = make_agent(mock_provider, repository, test_config)
        r1 = agent.run("Hi")
        cid = r1.conversation_id
        r2 = agent.run("Continue", conversation_id=cid)
        assert r2.conversation_id == cid

    def test_unknown_conversation_id_creates_new(self, mock_provider, repository, test_config):
        mock_provider.generate.return_value = make_text_response("Hello!")
        agent = make_agent(mock_provider, repository, test_config)
        result = agent.run("Hi", conversation_id="totally-unknown-id-xyz")
        assert result.conversation_id is not None
