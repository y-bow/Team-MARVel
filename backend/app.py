"""
app.py — EduSaarthi AI Flask application.

Endpoints:
  GET  /             — serves the static frontend (frontend/index.html)
  GET  /<path>       — serves frontend assets (css/, js/, assets/)
  GET  /health       — liveness check, no secrets exposed
  POST /api/chat     — single-turn or multi-turn AI conversation

Design rules:
  - NEVER expose stack traces, API keys, or internal paths to clients.
  - All errors are JSON with "error" and "code" fields.
  - Request and response validation happens before touching the agent.
  - ProviderError maps to its http_status code.
  - ConfigurationError at startup → server refuses to start (fail fast).
  - Tool event statuses are normalised to completed/failed for the client.
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path

# Ensure the repository root is importable so both `python backend/app.py`
# (direct execution) and `python -m backend.app` work.
_repo_root = str(Path(__file__).resolve().parent.parent)
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from flask import Flask, jsonify, request, send_from_directory

from backend.config import load_config, ConfigurationError
from backend.repository import JSONRepository
from backend.agent import AgentLoop, GeminiProvider, ProviderError, build_tool_registry

# Absolute path to the frontend directory (served as static files).
FRONTEND_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend"
)

# Tool event statuses as seen by the client. Successful tools are "completed",
# errors are "failed" so the UI never renders a failure as success.
_EVENT_STATUS_MAP = {
    "ok": "completed",
    "error": "failed",
    "queued": "queued",
    "running": "running",
    "completed": "completed",
    "failed": "failed",
}


def _normalise_events(events):
    """Return a copy of *events* with statuses mapped to the client vocabulary."""
    normalised = []
    for event in events or []:
        item = dict(event)
        status = str(item.get("status", "")).lower()
        item["status"] = _EVENT_STATUS_MAP.get(status, "completed")
        normalised.append(item)
    return normalised

# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(config=None, repository=None, provider=None) -> Flask:
    """
    Create and configure the Flask application.

    Accepts optional overrides for config, repository, and provider so that
    tests can inject mocks without touching environment variables.
    """
    # Serve the static frontend from the repository's frontend/ directory.
    # static_url_path="" makes assets resolve at "/css/...", "/js/..." etc.,
    # and the explicit "/" route below serves index.html.
    app = Flask(
        __name__,
        static_folder=FRONTEND_DIR,
        static_url_path="",
    )

    # ------------------------------------------------------------------
    # Load config (fail fast on missing credentials)
    # ------------------------------------------------------------------
    try:
        cfg = config or load_config()
    except ConfigurationError as exc:
        # Let the error propagate — server should not start without valid config
        raise

    # ------------------------------------------------------------------
    # Initialise repository
    # ------------------------------------------------------------------
    try:
        repo = repository or JSONRepository(cfg.data_path)
    except FileNotFoundError as exc:
        raise RuntimeError(str(exc)) from exc

    # ------------------------------------------------------------------
    # Initialise provider and agent loop
    # ------------------------------------------------------------------
    prov = provider or GeminiProvider(api_key=cfg.gemini_api_key)
    registry = build_tool_registry(repo, cfg)
    agent = AgentLoop(provider=prov, tool_registry=registry, config=cfg)

    # Store on app for access in request context
    app.config["EDUSAARTHI_CONFIG"] = cfg
    app.config["EDUSAARTHI_REPO"] = repo
    app.config["EDUSAARTHI_AGENT"] = agent

    # ------------------------------------------------------------------
    # Error handlers
    # ------------------------------------------------------------------

    @app.errorhandler(400)
    def bad_request(exc):
        return jsonify({"error": str(exc), "code": "BAD_REQUEST"}), 400

    @app.errorhandler(404)
    def not_found(exc):
        return jsonify({"error": "Endpoint not found.", "code": "NOT_FOUND"}), 404

    @app.errorhandler(405)
    def method_not_allowed(exc):
        return jsonify({"error": "Method not allowed.", "code": "METHOD_NOT_ALLOWED"}), 405

    @app.errorhandler(500)
    def internal_error(exc):
        # Log internally but never expose details to client
        app.logger.error("Unhandled exception: %s", traceback.format_exc())
        return jsonify({
            "error": "An internal server error occurred. Please try again.",
            "code": "INTERNAL_ERROR",
        }), 500

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/")
    def index():
        """Serve the single-page frontend."""
        return send_from_directory(FRONTEND_DIR, "index.html")

    @app.get("/health")
    def health():
        """
        Liveness and readiness check.
        Returns basic status — no secrets, keys, or internal paths.
        """
        cfg_ = app.config["EDUSAARTHI_CONFIG"]
        repo_ = app.config["EDUSAARTHI_REPO"]
        return jsonify({
            "status": "ok",
            "version": cfg_.version,
            "model": cfg_.gemini_model,
            "data_loaded": True,
            "scheme_count": repo_.count(),
        }), 200

    @app.post("/api/chat")
    def chat():
        """
        Single chat turn.

        Request body (JSON):
          {
            "message": "...",          (required, 1–MAX_MESSAGE_LENGTH chars)
            "conversation_id": "..."   (optional; null to start a new conversation)
          }

        Response body (JSON): see API contract in backend/README.md.
        """
        cfg_ = app.config["EDUSAARTHI_CONFIG"]
        agent_ = app.config["EDUSAARTHI_AGENT"]

        # -- Parse JSON body --
        if not request.is_json:
            return jsonify({
                "error": "Request must have Content-Type: application/json.",
                "code": "INVALID_CONTENT_TYPE",
            }), 400

        try:
            body = request.get_json(force=False, silent=False)
        except Exception:
            return jsonify({
                "error": "Request body is not valid JSON.",
                "code": "INVALID_JSON",
            }), 400

        if body is None:
            return jsonify({
                "error": "Request body must be a JSON object.",
                "code": "INVALID_JSON",
            }), 400

        # -- Validate message --
        message = body.get("message")
        if message is None:
            return jsonify({
                "error": "Field 'message' is required.",
                "code": "MISSING_FIELD",
            }), 400
        if not isinstance(message, str):
            return jsonify({
                "error": "Field 'message' must be a string.",
                "code": "INVALID_FIELD",
            }), 400
        message = message.strip()
        if not message:
            return jsonify({
                "error": "Field 'message' must not be empty.",
                "code": "INVALID_FIELD",
            }), 400
        max_len = cfg_.max_message_length
        if len(message) > max_len:
            return jsonify({
                "error": f"Field 'message' exceeds maximum length of {max_len} characters.",
                "code": "MESSAGE_TOO_LONG",
            }), 400

        # -- Validate conversation_id --
        conversation_id = body.get("conversation_id")
        if conversation_id is not None and not isinstance(conversation_id, str):
            return jsonify({
                "error": "Field 'conversation_id' must be a string or null.",
                "code": "INVALID_FIELD",
            }), 400
        if isinstance(conversation_id, str):
            conversation_id = conversation_id.strip() or None

        # -- Run agent --
        try:
            result = agent_.run(message=message, conversation_id=conversation_id)
        except ProviderError as exc:
            return jsonify({
                "error": str(exc),
                "code": "PROVIDER_ERROR",
            }), exc.http_status
        except Exception:
            app.logger.error("Agent error: %s", traceback.format_exc())
            return jsonify({
                "error": "An unexpected error occurred. Please try again.",
                "code": "AGENT_ERROR",
            }), 500

        payload = {
            "conversation_id": result.conversation_id,
            "status": result.status,
            "answer": result.answer,
            "sources": result.sources,
            "events": _normalise_events(result.events),
            "action_plan": result.action_plan,
        }

        # Clarification bridge: the structured object is always present when the
        # agent is asking a follow-up question (agent already sets it; this is a
        # defensive fallback so the frontend never sees a bare status).
        if result.clarification:
            payload["clarification"] = result.clarification
        elif result.status == "needs_clarification":
            payload["clarification"] = {"question": result.answer, "options": []}

        # Optional fields are included only when the tool results support them.
        if result.matches:
            payload["matches"] = result.matches
        if result.eligibility:
            payload["eligibility"] = result.eligibility
        if result.documents:
            payload["documents"] = result.documents
        if result.steps:
            payload["steps"] = result.steps

        return jsonify(payload), 200

    return app


# ---------------------------------------------------------------------------
# Entry point (development only — use Gunicorn in production)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    try:
        application = create_app()
    except (ConfigurationError, RuntimeError) as exc:
        print(f"\n[ERROR] Cannot start EduSaarthi AI backend: {exc}\n")
        raise SystemExit(1)

    cfg = application.config["EDUSAARTHI_CONFIG"]
    application.run(host=cfg.host, port=cfg.port, debug=cfg.debug)
