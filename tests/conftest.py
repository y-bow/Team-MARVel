"""
conftest.py — shared pytest fixtures for the EduSaarthi AI backend test suite.

All fixtures use synthetic data and mocked LLM responses.
No real API key or paid calls are made during offline tests.
"""

from __future__ import annotations

import json
import os
import tempfile
from unittest.mock import MagicMock

import pytest

from backend.config import Config
from backend.repository import JSONRepository

# Import test helpers (separate module to avoid site-packages conflict)
from tests.helpers import (  # noqa: F401 – re-exported for backward compat
    make_text_response,
    make_function_call_response,
    make_parallel_calls_response,
    make_malformed_finish_response,
)

# ---------------------------------------------------------------------------
# Synthetic schemes (minimal, deterministic)
# ---------------------------------------------------------------------------

SYNTHETIC_SCHEMES = [
    {
        "id": "test-sc-scholarship",
        "name": "Test SC Pre-Matric Scholarship",
        "description": "A test scholarship for SC students in Class 10.",
        "criteria": {
            "education_levels": ["10th"],
            "state": None,
            "caste_categories": ["SC"],
            "min_percentage": 55.0,
            "annual_family_income_max": 250000.0,
            "gender": "any",
            "disability_required": None,
            "notes": "Test notes only.",
        },
        "documents": ["Aadhaar card", "Caste certificate", "Marksheet"],
        "application_steps": ["Step 1: Register", "Step 2: Apply"],
        "deadline": "2099-12-31",  # far future — always current in tests
        "source_url": "https://example.gov.in/test-sc",
        "verified": True,
        "last_checked": "2099-01-01",
        "tags": ["scholarship", "SC", "test"],
    },
    {
        "id": "test-women-tech",
        "name": "Test Women in Tech Scholarship",
        "description": "A test scholarship for female UG students in Computer Science.",
        "criteria": {
            "education_levels": ["UG"],
            "state": None,
            "caste_categories": ["any"],
            "min_percentage": None,
            "annual_family_income_max": None,
            "gender": "Female",
            "disability_required": None,
            "notes": None,
        },
        "documents": ["Enrollment proof", "Transcripts"],
        "application_steps": ["Step 1: Fill form", "Step 2: Submit"],
        "deadline": "2000-01-01",  # definitely in the past
        "source_url": "https://example.com/women-tech",
        "verified": True,
        "last_checked": "2000-01-01",  # stale
        "tags": ["scholarship", "women", "tech", "UG"],
    },
    {
        "id": "test-no-source",
        "name": "Test Scheme Without Source URL",
        "description": "A scheme with no source URL and unverified deadline.",
        "criteria": {
            "education_levels": ["PG"],
            "state": "Maharashtra",
            "caste_categories": ["OBC"],
            "min_percentage": 60.0,
            "annual_family_income_max": 300000.0,
            "gender": "any",
            "disability_required": None,
            "notes": None,
        },
        "documents": [],
        "application_steps": [],
        "deadline": None,
        "source_url": None,
        "verified": False,
        "last_checked": None,
        "tags": ["scholarship", "OBC", "Maharashtra"],
    },
]


@pytest.fixture
def schemes_json_file():
    """Write synthetic schemes to a temp file and return its path."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, encoding="utf-8"
    ) as f:
        json.dump(SYNTHETIC_SCHEMES, f)
        path = f.name
    yield path
    os.unlink(path)


@pytest.fixture
def repository(schemes_json_file):
    """A JSONRepository backed by synthetic data."""
    return JSONRepository(schemes_json_file)


@pytest.fixture
def test_config(schemes_json_file):
    """A Config instance with test-safe values (no real API key needed)."""
    return Config(
        openrouter_api_key="test-api-key-not-real",
        openrouter_model="test/model-not-real",
        host="127.0.0.1",
        port=5001,
        debug=False,
        max_iterations=8,
        max_search_results=10,
        max_message_length=4000,
        max_answer_length=8000,
        deadline_stale_days=30,
        data_path=schemes_json_file,
        version="test-1.0",
    )


@pytest.fixture
def mock_provider():
    """Return a mock provider whose generate() can be configured per test."""
    provider = MagicMock()
    return provider


@pytest.fixture
def flask_app(test_config, repository, mock_provider):
    """Flask test client with mocked provider and synthetic repository."""
    from backend.agent import build_tool_registry, AgentLoop
    from backend.app import create_app

    registry = build_tool_registry(repository, test_config)
    agent = AgentLoop(provider=mock_provider, tool_registry=registry, config=test_config)
    app = create_app(config=test_config, repository=repository, provider=mock_provider)
    # Replace agent with our pre-built one (provider already injected)
    app.config["EDUSAARTHI_AGENT"] = agent
    app.testing = True
    return app


@pytest.fixture
def client(flask_app):
    """Flask test client."""
    return flask_app.test_client()
