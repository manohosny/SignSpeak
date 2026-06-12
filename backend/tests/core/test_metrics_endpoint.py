"""The /metrics endpoint and the ML quality counters it exposes."""

from fastapi.testclient import TestClient

from app.core.content_filter import filter_text
from app.core.metrics import SIGN_SEGMENTS_GATED
from app.main import app


def test_metrics_endpoint_serves_prometheus_text() -> None:
    with TestClient(app) as client:
        resp = client.get("/metrics")
    assert resp.status_code == 200
    # Unlabeled counters register immediately; this also proves the custom
    # registry entries share the scrape endpoint with the HTTP histograms.
    assert "signspeak_message_flags_total" in resp.text


def test_gate_and_redaction_counters_appear_after_increment() -> None:
    SIGN_SEGMENTS_GATED.labels(reason="too_short").inc()
    filter_text("a@b.com")  # increments signspeak_content_redactions_total{pii}
    with TestClient(app) as client:
        body = client.get("/metrics").text
    assert 'signspeak_sign_segments_gated_total{reason="too_short"}' in body
    assert 'signspeak_content_redactions_total{kind="pii"}' in body


def test_metrics_not_in_openapi_schema() -> None:
    paths = app.openapi().get("paths", {})
    assert "/metrics" not in paths
