"""
helpers.py — test helper functions for building mock LLM responses.

Separated from conftest.py to avoid pytest's conftest discovery
conflicting with any installed 'tests' package in site-packages.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from google.genai import types


def make_text_response(text: str) -> MagicMock:
    """Build a mock GenerateContentResponse with a plain text final answer."""
    part = types.Part(text=text)
    content = types.Content(role="model", parts=[part])
    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = types.FinishReason.STOP

    response = MagicMock()
    response.candidates = [candidate]
    return response


def make_function_call_response(name: str, args: dict) -> MagicMock:
    """Build a mock response that requests a single tool call."""
    fc = types.FunctionCall(name=name, args=args)
    part = types.Part(function_call=fc)
    content = types.Content(role="model", parts=[part])
    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = types.FinishReason.STOP

    response = MagicMock()
    response.candidates = [candidate]
    return response


def make_parallel_calls_response(calls: list[tuple[str, dict]]) -> MagicMock:
    """Build a mock response with multiple parallel tool calls."""
    parts = [
        types.Part(function_call=types.FunctionCall(name=name, args=args))
        for name, args in calls
    ]
    content = types.Content(role="model", parts=parts)
    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = types.FinishReason.STOP

    response = MagicMock()
    response.candidates = [candidate]
    return response


def make_malformed_finish_response(reason: Any) -> MagicMock:
    """Build a response with a non-STOP, non-function-call finish reason."""
    content = types.Content(role="model", parts=[])
    candidate = MagicMock()
    candidate.content = content
    candidate.finish_reason = reason

    response = MagicMock()
    response.candidates = [candidate]
    return response
