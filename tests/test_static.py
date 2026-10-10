"""
test_static.py — tests for serving the static frontend from Flask.

Verifies the root URL serves frontend/index.html, assets are reachable,
missing assets 404, and the JSON API routes still work alongside the
static routes (no shadowing).
"""


def test_root_serves_frontend_index(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.content_type
    assert b"EduSaarthi" in response.data


def test_root_index_contains_app_shell(client):
    response = client.get("/")
    assert b'id="chatView"' in response.data
    assert b"composer" in response.data


def test_css_asset_served(client):
    response = client.get("/css/styles.css")
    assert response.status_code == 200
    assert len(response.data) > 0


def test_js_asset_served(client):
    response = client.get("/js/api.js")
    assert response.status_code == 200
    assert len(response.data) > 0


def test_assets_dir_listing_is_not_exposed(client):
    """Directory paths should not render a listing."""
    response = client.get("/assets/")
    assert response.status_code == 404


def test_missing_asset_returns_404(client):
    response = client.get("/does-not-exist.js")
    assert response.status_code == 404


def test_health_still_json_alongside_static(client):
    """The static catch-all must not shadow /health."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data is not None
    assert data["status"] == "ok"


def test_chat_route_still_works_alongside_static(client, mock_provider):
    """The static catch-all must not shadow POST /api/chat."""
    from tests.helpers import make_text_response

    mock_provider.generate.return_value = make_text_response("Hello from static test.")
    response = client.post("/api/chat", json={"message": "Hi"})
    assert response.status_code == 200
    data = response.get_json()
    assert data["status"] == "completed"