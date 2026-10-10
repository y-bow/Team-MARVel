"""
test_health.py — tests for GET /health endpoint.
"""

import pytest


def test_health_returns_200(client):
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_json(client):
    response = client.get("/health")
    data = response.get_json()
    assert data is not None


def test_health_has_required_fields(client):
    data = client.get("/health").get_json()
    assert "status" in data
    assert "version" in data
    assert "model" in data
    assert "data_loaded" in data
    assert "scheme_count" in data


def test_health_status_is_ok(client):
    data = client.get("/health").get_json()
    assert data["status"] == "ok"


def test_health_data_loaded(client):
    data = client.get("/health").get_json()
    assert data["data_loaded"] is True


def test_health_scheme_count_matches_synthetic(client):
    """Synthetic data has 3 schemes."""
    data = client.get("/health").get_json()
    assert data["scheme_count"] == 3


def test_health_no_secrets_exposed(client):
    """Health endpoint must not expose API keys or internal paths."""
    data = client.get("/health").get_json()
    response_str = str(data)
    assert "test-api-key" not in response_str
    assert ".json" not in response_str


def test_health_includes_data_quality_summary(client):
    """Health must surface deterministic dataset freshness counts."""
    data = client.get("/health").get_json()
    quality = data["data_quality"]
    assert quality["records"] == data["scheme_count"]
    assert quality["verified"] + quality["unverified"] == quality["records"]
    assert quality["past_deadlines"] == 1
    assert quality["unknown_deadlines"] == 1
    assert quality["never_checked"] == 1
    assert quality["stale_records"] == 2
    assert quality["oldest_last_checked"] == "2000-01-01"
