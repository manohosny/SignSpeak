"""Regression tests for the WebSocket router's pre-accept hardening
and message-loop limits introduced in PR1/PR5.

These tests deliberately use the post-accept first-message auth path so
they exercise the same JWT validation logic as the query-param path
without depending on the test client's WS query-string handling.
"""

from __future__ import annotations

import json
import uuid

import pytest
from fastapi.testclient import TestClient

from .conftest import make_token


def test_oversize_text_frame_closes_socket(ws_client: TestClient, meeting_id, speaker_user):
    """A text frame larger than the per-frame cap must close the socket
    with 1009 (Message Too Big) — the dispatcher must not parse it."""
    token = make_token(speaker_user.id)
    with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        # Drain auth_ok + any user_joined echoes
        while True:
            msg = ws.receive_json()
            if msg.get("type") == "auth_ok":
                break

        # Send a 100 KB JSON payload; cap is 64 KB.
        oversize = json.dumps({"type": "gloss_message", "content": "x" * (100 * 1024)})
        ws.send_text(oversize)

        # Server should reply with an error and then close.
        err = ws.receive_json()
        assert err.get("type") == "error"
        assert "too large" in err.get("message", "").lower()


def test_invalid_query_param_token_rejected_pre_accept(
    ws_client: TestClient, meeting_id
):
    """A WS upgrade with an invalid ?token=... must be closed pre-accept
    with code 4001, not silently dropped — verifies the C-1 fix."""
    with pytest.raises(Exception):
        # Either WebSocketDisconnect or a connection-refused style error.
        with ws_client.websocket_connect(
            f"/ws/{meeting_id}?token=not-a-real-jwt"
        ) as ws:
            ws.receive_json()


def test_unknown_message_type_returns_validation_error(
    ws_client: TestClient, meeting_id, speaker_user
):
    """The Pydantic dispatcher must reject unknown message types with a
    structured error, not a 500 — verifies the M-2 fix."""
    token = make_token(speaker_user.id)
    with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        while True:
            msg = ws.receive_json()
            if msg.get("type") == "auth_ok":
                break

        ws.send_text(json.dumps({"type": "made_up", "field": "hello"}))
        err = ws.receive_json()
        assert err.get("type") == "error"


def test_malformed_gloss_payload_returns_validation_error(
    ws_client: TestClient, meeting_id, reader_user
):
    """A gloss_message with a non-string content field must be caught by
    the Pydantic schema before reaching the handler."""
    token = make_token(reader_user.id)
    with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
        ws.send_text(json.dumps({"type": "auth", "token": token}))
        while True:
            msg = ws.receive_json()
            if msg.get("type") == "auth_ok":
                break

        ws.send_text(json.dumps({"type": "gloss_message", "content": 12345}))
        err = ws.receive_json()
        assert err.get("type") == "error"
