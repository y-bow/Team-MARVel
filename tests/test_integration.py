"""
test_integration.py — optional integration tests against the live Gemini API.

These tests are SKIPPED unless EDUSAARTHI_LIVE_TESTS=1 is set.
They make real API calls and should NOT be run in CI without a budget guard.

Run manually:
    EDUSAARTHI_LIVE_TESTS=1 GEMINI_API_KEY=your_key pytest tests/test_integration.py -v
"""

import os
import pytest

SKIP_REASON = (
    "Live integration tests disabled. "
    "Set EDUSAARTHI_LIVE_TESTS=1 (with GEMINI_API_KEY) to run."
)
pytestmark = pytest.mark.skipif(
    os.getenv("EDUSAARTHI_LIVE_TESTS") != "1", reason=SKIP_REASON
)


@pytest.fixture(scope="module")
def live_client():
    """Flask test client with real Gemini provider and real data."""
    from backend.config import load_config
    from backend.repository import JSONRepository
    from backend.agent import GeminiProvider, AgentLoop, build_tool_registry
    from backend.app import create_app

    cfg = load_config()
    repo = JSONRepository(cfg.data_path)
    provider = GeminiProvider(api_key=cfg.gemini_api_key)
    registry = build_tool_registry(repo, cfg)
    agent = AgentLoop(provider=provider, tool_registry=registry, config=cfg)
    app = create_app(config=cfg, repository=repo, provider=provider)
    app.config["EDUSAARTHI_AGENT"] = agent
    app.testing = True
    return app.test_client()


def test_integration_health(live_client):
    resp = live_client.get("/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["scheme_count"] > 0


def test_integration_simple_chat(live_client):
    resp = live_client.post(
        "/api/chat",
        json={"message": "What scholarships are available for SC students in class 10?"},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] in ("completed", "needs_clarification")
    assert len(data["answer"]) > 10


def test_integration_eligibility_check(live_client):
    resp = live_client.post(
        "/api/chat",
        json={
            "message": (
                "I am a class 10 SC student with 62% marks and family income of "
                "₹1.8 lakh. Am I eligible for any scholarship?"
            )
        },
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] in ("completed", "needs_clarification")
    assert len(data["events"]) > 0


def test_integration_multi_turn(live_client):
    """Two turns in the same conversation."""
    resp1 = live_client.post(
        "/api/chat", json={"message": "Tell me about scholarships for women in tech."}
    )
    assert resp1.status_code == 200
    cid = resp1.get_json()["conversation_id"]

    resp2 = live_client.post(
        "/api/chat",
        json={
            "message": "What documents do I need to apply?",
            "conversation_id": cid,
        },
    )
    assert resp2.status_code == 200
    assert resp2.get_json()["conversation_id"] == cid