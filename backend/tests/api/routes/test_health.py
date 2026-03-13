"""Tests for health check endpoint with model readiness gating."""

from unittest.mock import patch


def test_health_check_returns_503_when_models_not_ready(client):
    """Health check should return 503 before models finish loading."""
    with patch("app.main.models_ready", return_value=False):
        response = client.get("/api/v1/utils/health-check/")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "loading"


def test_health_check_returns_200_when_models_ready(client):
    """Health check should return 200 after models finish loading."""
    with patch("app.main.models_ready", return_value=True):
        response = client.get("/api/v1/utils/health-check/")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
