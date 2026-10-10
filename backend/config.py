"""
config.py — EduSaarthi AI backend configuration.

Reads all settings from environment variables (via python-dotenv).
Missing OPENROUTER_API_KEY raises ConfigurationError at import time so
the server fails fast with a clear message — never serves fabricated answers.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv

# Load .env file if present (development convenience).
# In production, env vars are injected by the platform.
load_dotenv()


class ConfigurationError(RuntimeError):
    """Raised when a required configuration value is missing or invalid."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _require(name: str) -> str:
    """Return the value of env var *name* or raise ConfigurationError."""
    value = os.getenv(name, "").strip()
    if not value:
        raise ConfigurationError(
            f"Required environment variable '{name}' is not set. "
            "Copy .env.example to .env and fill in the value."
        )
    return value


def _optional(name: str, default: str) -> str:
    return os.getenv(name, default).strip() or default


def _optional_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(
            f"Environment variable '{name}' must be an integer, got: {raw!r}"
        ) from exc
    return value


# ---------------------------------------------------------------------------
# Config dataclass — single source of truth for the whole backend
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Config:
    # OpenRouter credentials (OpenAI-compatible API)
    openrouter_api_key: str
    openrouter_model: str

    # Flask server
    host: str
    port: int
    debug: bool

    # Agent behaviour limits
    max_iterations: int       # maximum tool-call rounds per request
    max_search_results: int   # maximum records returned by search_schemes
    max_message_length: int   # maximum user message length (chars)
    max_answer_length: int    # maximum answer length returned to client

    # Deadline staleness threshold (days). Deadlines not checked within this
    # window are flagged as "stale" rather than "current".
    deadline_stale_days: int

    # Path to the JSON knowledge base (read-only at runtime)
    data_path: str

    # OpenRouter API base URL (OpenAI-compatible Chat Completions endpoint)
    openrouter_base_url: str = field(default="https://openrouter.ai/api/v1")

    # Application version surfaced on /health
    version: str = field(default="1.0.0")

    # RAG Settings
    vector_store_path: str = field(default="data/chroma_db")
    embedding_model: str = field(default="all-MiniLM-L6-v2")


def load_config(require_api_key: bool = True) -> Config:
    """
    Load and validate configuration from environment variables.

    Raises ConfigurationError for missing required variables.
    Never logs the API key.
    """
    if require_api_key:
        api_key = _require("OPENROUTER_API_KEY")
        model = _require("OPENROUTER_MODEL")
    else:
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip() or "dummy-key-for-ingestion"
        model = os.getenv("OPENROUTER_MODEL", "").strip() or "dummy-model"
    return Config(
        openrouter_api_key=api_key,
        openrouter_model=model,
        openrouter_base_url=_optional(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ),
        host=_optional("HOST", "0.0.0.0"),
        port=_optional_int("PORT", 5000),
        debug=os.getenv("FLASK_DEBUG", "false").strip().lower() == "true",
        max_iterations=_optional_int("MAX_ITERATIONS", 8),
        max_search_results=_optional_int("MAX_SEARCH_RESULTS", 10),
        max_message_length=_optional_int("MAX_MESSAGE_LENGTH", 4000),
        max_answer_length=_optional_int("MAX_ANSWER_LENGTH", 8000),
        deadline_stale_days=_optional_int("DEADLINE_STALE_DAYS", 30),
        data_path=_optional("DATA_PATH", "data/schemes.json"),
        version=_optional("APP_VERSION", "1.0.0"),
        vector_store_path=_optional("VECTOR_STORE_PATH", "data/chroma_db"),
        embedding_model=_optional("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
    )
