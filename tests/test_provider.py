"""
test_provider.py — unit tests for the OpenRouterProvider wire translation.

No network calls: the HTTP layer is monkeypatched. These tests pin the
translation between the agent loop's google-genai types and the
OpenAI-compatible Chat Completions payload/response.
"""

from __future__ import annotations

import json
import urllib.error

import pytest
from google.genai import types

from backend.agent import OpenRouterProvider, ProviderError, _TOOL_DECLARATIONS
from backend.config import Config


def _config() -> Config:
    return Config(
        openrouter_api_key="test-key",
        openrouter_model="test/model",
        host="127.0.0.1",
        port=5001,
        debug=False,
        max_iterations=8,
        max_search_results=10,
        max_message_length=4000,
        max_answer_length=8000,
        deadline_stale_days=30,
        data_path="data/schemes.json",
        version="test",
    )


def _tools() -> list[types.Tool]:
    return [types.Tool(function_declarations=_TOOL_DECLARATIONS)]


def _history() -> list[types.Content]:
    return [
        types.Content(role="user", parts=[types.Part(text="find scholarships")]),
        types.Content(
            role="model",
            parts=[
                types.Part(
                    function_call=types.FunctionCall(
                        name="search_schemes", args={"query": "SC"}
                    )
                )
            ],
        ),
        types.Content(
            role="user",
            parts=[
                types.Part.from_function_response(
                    name="search_schemes", response={"output": {"result_count": 1}}
                )
            ],
        ),
        types.Content(role="model", parts=[types.Part(text="Here are results")]),
    ]


class FakeHTTPResponse:
    def __init__(self, payload: dict):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "FakeHTTPResponse":
        return self

    def __exit__(self, *args) -> bool:
        return False


class TestSchemaTranslation:
    def test_tools_translate_to_openai_shape(self):
        tools = OpenRouterProvider._tools_to_openai(_tools())
        names = [t["function"]["name"] for t in tools]
        assert names == [
            "search_schemes",
            "check_eligibility",
            "get_requirements",
            "verify_deadline",
            "create_action_plan",
            "ask_clarification",
        ]
        for entry in tools:
            assert entry["type"] == "function"
            assert entry["function"]["description"]

    def test_json_schema_types_are_lowercase(self):
        tools = OpenRouterProvider._tools_to_openai(_tools())
        by_name = {t["function"]["name"]: t["function"] for t in tools}
        params = by_name["search_schemes"]["parameters"]
        assert params["type"] == "object"
        assert params["properties"]["query"]["type"] == "string"
        assert params["required"] == ["query"]

    def test_nested_array_and_object_schemas(self):
        tools = OpenRouterProvider._tools_to_openai(_tools())
        by_name = {t["function"]["name"]: t["function"] for t in tools}
        params = by_name["create_action_plan"]["parameters"]
        assert params["properties"]["scheme_ids"]["type"] == "array"
        assert params["properties"]["scheme_ids"]["items"]["type"] == "string"
        eligibility = params["properties"]["eligibility_results"]["items"]
        assert eligibility["type"] == "object"


class TestContentsToMessages:
    def test_history_translates_to_ordered_messages(self):
        messages = OpenRouterProvider._contents_to_messages(_history())
        roles = [m["role"] for m in messages]
        assert roles == ["user", "assistant", "tool", "assistant"]
        assert messages[0]["content"] == "find scholarships"
        assert messages[3]["content"] == "Here are results"

    def test_tool_call_arguments_are_json_strings(self):
        messages = OpenRouterProvider._contents_to_messages(_history())
        calls = messages[1]["tool_calls"]
        assert len(calls) == 1
        assert calls[0]["function"]["name"] == "search_schemes"
        assert json.loads(calls[0]["function"]["arguments"]) == {"query": "SC"}

    def test_tool_result_ids_match_pending_calls(self):
        messages = OpenRouterProvider._contents_to_messages(_history())
        call_id = messages[1]["tool_calls"][0]["id"]
        assert messages[2]["tool_call_id"] == call_id
        assert json.loads(messages[2]["content"]) == {"output": {"result_count": 1}}

    def test_model_text_and_calls_combine(self):
        history = [
            types.Content(
                role="model",
                parts=[
                    types.Part(text="Let me search"),
                    types.Part(
                        function_call=types.FunctionCall(name="search_schemes", args={})
                    ),
                ],
            ),
        ]
        messages = OpenRouterProvider._contents_to_messages(history)
        assert messages[0]["content"] == "Let me search"
        assert messages[0]["tool_calls"][0]["function"]["name"] == "search_schemes"


class TestGenerate:
    def test_text_response_maps_to_candidate(self, monkeypatch):
        provider = OpenRouterProvider(api_key="k", base_url="https://openrouter.ai/api/v1")
        captured = {}

        def fake_post(payload):
            captured.update(payload)
            return {
                "choices": [{
                    "finish_reason": "stop",
                    "message": {"content": "Hello", "tool_calls": []},
                }]
            }

        monkeypatch.setattr(provider, "_post", fake_post)
        response = provider.generate(
            contents=_history(),
            model="test/model",
            tools=_tools(),
            system_instruction="SYS",
        )

        candidate = response.candidates[0]
        assert candidate.finish_reason == types.FinishReason.STOP
        assert candidate.content.parts[0].text == "Hello"
        assert captured["model"] == "test/model"
        assert captured["messages"][0] == {"role": "system", "content": "SYS"}
        assert captured["tools"]

    def test_tool_calls_response_maps_to_function_calls(self, monkeypatch):
        provider = OpenRouterProvider(api_key="k")

        def fake_post(payload):
            return {
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "content": None,
                        "tool_calls": [{
                            "id": "call_x",
                            "type": "function",
                            "function": {
                                "name": "search_schemes",
                                "arguments": "{\"query\": \"merit\"}",
                            },
                        }],
                    },
                }]
            }

        monkeypatch.setattr(provider, "_post", fake_post)
        response = provider.generate(
            contents=_history(), model="m", tools=_tools(),
            system_instruction="SYS",
        )

        part = response.candidates[0].content.parts[0]
        assert part.function_call.name == "search_schemes"
        assert part.function_call.args == {"query": "merit"}
        assert response.candidates[0].finish_reason == types.FinishReason.STOP

    def test_unparseable_arguments_become_empty_dict(self, monkeypatch):
        provider = OpenRouterProvider(api_key="k")

        def fake_post(payload):
            return {
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "tool_calls": [{
                            "function": {"name": "x", "arguments": "not-json"},
                        }]
                    },
                }]
            }

        monkeypatch.setattr(provider, "_post", fake_post)
        response = provider.generate(
            contents=_history(), model="m", tools=[], system_instruction="SYS"
        )
        assert response.candidates[0].content.parts[0].function_call.args == {}

    @pytest.mark.parametrize("wire,expected", [
        ("length", types.FinishReason.MAX_TOKENS),
        ("content_filter", types.FinishReason.PROHIBITED_CONTENT),
        ("stop", types.FinishReason.STOP),
    ])
    def test_finish_reason_mapping(self, monkeypatch, wire, expected):
        provider = OpenRouterProvider(api_key="k")

        def fake_post(payload):
            return {
                "choices": [{
                    "finish_reason": wire,
                    "message": {"content": "hi"},
                }]
            }

        monkeypatch.setattr(provider, "_post", fake_post)
        response = provider.generate(
            contents=_history(), model="m", tools=[], system_instruction="SYS"
        )
        assert response.candidates[0].finish_reason == expected

    def test_empty_choices_raise_provider_error(self, monkeypatch):
        provider = OpenRouterProvider(api_key="k")
        monkeypatch.setattr(provider, "_post", lambda payload: {"choices": []})
        with pytest.raises(ProviderError) as exc:
            provider.generate(
                contents=_history(), model="m", tools=[], system_instruction="SYS"
            )
        assert exc.value.http_status == 503


class TestPostErrorMapping:
    def _provider(self) -> OpenRouterProvider:
        return OpenRouterProvider(api_key="secret-key")

    def _patch_urlopen(self, monkeypatch, exc):
        def fake_urlopen(request, timeout=None):
            raise exc

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    @pytest.mark.parametrize("code,status", [
        (429, 429),
        (401, 502),
        (500, 503),
        (503, 503),
        (400, 400),
    ])
    def test_http_errors_map_to_provider_error(self, monkeypatch, code, status):
        err = urllib.error.HTTPError("https://x", code, "msg", {}, None)
        self._patch_urlopen(monkeypatch, err)
        with pytest.raises(ProviderError) as exc:
            self._provider()._post({"model": "m", "messages": []})
        assert exc.value.http_status == status

    def test_network_failure_maps_to_503(self, monkeypatch):
        self._patch_urlopen(
            monkeypatch, urllib.error.URLError("connection refused")
        )
        with pytest.raises(ProviderError) as exc:
            self._provider()._post({"model": "m", "messages": []})
        assert exc.value.http_status == 503

    def test_timeout_maps_to_503(self, monkeypatch):
        self._patch_urlopen(monkeypatch, TimeoutError("timed out"))
        with pytest.raises(ProviderError) as exc:
            self._provider()._post({"model": "m", "messages": []})
        assert exc.value.http_status == 503

    def test_request_payload_shape(self, monkeypatch):
        captured = {}

        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["auth"] = request.get_header("Authorization")
            captured["timeout"] = timeout
            return FakeHTTPResponse({"choices": [{"message": {"content": "ok"}}]})

        monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
        self._provider()._post({"model": "m", "messages": [{"role": "user", "content": "hi"}]})

        assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert captured["auth"] == "Bearer secret-key"
        assert captured["body"]["model"] == "m"
        assert captured["timeout"] == 120

    def test_api_key_never_leaks_into_error_messages(self, monkeypatch):
        err = urllib.error.HTTPError("https://x", 400, "bad", {}, None)
        self._patch_urlopen(monkeypatch, err)
        with pytest.raises(ProviderError) as exc:
            self._provider()._post({"model": "m", "messages": []})
        assert "secret-key" not in str(exc.value)
