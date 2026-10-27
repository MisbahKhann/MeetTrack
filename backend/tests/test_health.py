"""Tests for the /health endpoint.

Happy path: 200 with expected JSON body.
Failure path: unknown route returns 404.
"""

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_health_returns_ok() -> None:
    """GET /health must return 200 with the standard liveness payload."""
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "meettrack-backend"
    assert body["version"] == "0.1.0"


def test_unknown_route_returns_404() -> None:
    """Any route not registered must return 404 (not 200 or 500)."""
    response = client.get("/does-not-exist")
    assert response.status_code == 404
