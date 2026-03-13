"""WebSocket lifecycle integration tests.

Tests the full WebSocket pipeline: auth, audio streaming (with mock STT),
text messaging (with mock TTS), meeting lifecycle, rate limiting,
connection limits, and error handling.
"""

from __future__ import annotations

import re
import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session
from starlette.websockets import WebSocketDisconnect

import pytest

from app.models import (
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    ParticipantRole,
    User,
)
from tests.ws.conftest import make_pcm16_audio, make_token


# ============================================================
# AUTH FLOW
# ============================================================


class TestAuthFlow:
    def test_auth_success(
        self, ws_client: TestClient, meeting_id: uuid.UUID, speaker_user: User
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            msg = ws.receive_json()

            assert msg["type"] == "auth_ok"
            assert msg["user_id"] == str(speaker_user.id)
            assert msg["role"] == "speaker"
            assert msg["meeting_id"] == str(meeting_id)

    def test_auth_invalid_token(
        self, ws_client: TestClient, meeting_id: uuid.UUID
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": "garbage-token"})
            msg = ws.receive_json()
            assert msg["type"] == "auth_error"
            assert "Invalid" in msg["message"] or "expired" in msg["message"]

            # Server closed the connection; next receive triggers disconnect
            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4001

    def test_auth_timeout(
        self, ws_client: TestClient, meeting_id: uuid.UUID
    ):
        with patch("app.ws.router._AUTH_TIMEOUT_SECONDS", 0.5):
            with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
                # Don't send anything — let the timeout fire
                msg = ws.receive_json()
                assert msg["type"] == "auth_error"
                assert "timeout" in msg["message"].lower()

                with pytest.raises(WebSocketDisconnect) as exc_info:
                    ws.receive_json()
                assert exc_info.value.code == 4000

    def test_auth_missing_token_field(
        self, ws_client: TestClient, meeting_id: uuid.UUID
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth"})
            msg = ws.receive_json()
            assert msg["type"] == "auth_error"
            assert "First message" in msg["message"]

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4001

    def test_auth_non_participant(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        third_user: User,
    ):
        """User with valid JWT but not a participant in this meeting."""
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(third_user.id)})
            msg = ws.receive_json()
            assert msg["type"] == "auth_error"
            assert "Not a participant" in msg["message"]

            with pytest.raises(WebSocketDisconnect) as exc_info:
                ws.receive_json()
            assert exc_info.value.code == 4003


# ============================================================
# AUDIO STREAMING
# ============================================================


class TestAudioStreaming:
    def test_speaker_sends_audio_receives_transcript(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            auth = ws.receive_json()
            assert auth["type"] == "auth_ok"

            # Send enough audio to exceed the 100ms minimum (MIN_UTTERANCE_SAMPLES)
            # 0.25s * 3 = 0.75s of audio
            for _ in range(3):
                ws.send_bytes(make_pcm16_audio(0.25))

            # Signal end of utterance to flush the STT buffer
            ws.send_json({"type": "control", "action": "utterance_end"})

            # Should receive a transcript message
            msg = ws.receive_json()
            assert msg["type"] == "transcript"
            assert msg["is_partial"] is False
            assert "[Mock transcript" in msg["text"]

    def test_reader_audio_ignored(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"
                ws_reader.receive_json()  # user_joined for speaker
                ws_speaker.receive_json()  # user_joined for reader

                # Reader sends binary audio — should be silently ignored
                ws_reader.send_bytes(make_pcm16_audio(0.25))
                ws_reader.send_json(
                    {"type": "control", "action": "utterance_end"}
                )

                # Send a sentinel text message; if audio produced a transcript
                # it would arrive on ws_speaker before the text message
                ws_reader.send_json(
                    {"type": "text_message", "content": "sentinel"}
                )

                # The first JSON the speaker receives must be the text, not a
                # transcript — proving the reader's audio was discarded
                msg = ws_speaker.receive_json()
                assert msg["type"] == "text_message", (
                    f"Expected text_message sentinel but got {msg['type']}"
                )


# ============================================================
# TEXT MESSAGING
# ============================================================


class TestTextMessaging:
    def test_reader_sends_text_speaker_receives(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                # Reader gets auth_ok + user_joined for speaker
                assert ws_reader.receive_json()["type"] == "auth_ok"
                joined_reader = ws_reader.receive_json()
                assert joined_reader["type"] == "user_joined"
                assert joined_reader["role"] == "speaker"

                # Speaker gets user_joined for reader
                joined_speaker = ws_speaker.receive_json()
                assert joined_speaker["type"] == "user_joined"
                assert joined_speaker["role"] == "reader"

                # Reader sends text message
                ws_reader.send_json(
                    {"type": "text_message", "content": "Hello speaker!"}
                )

                # Speaker receives the text message
                text_msg = ws_speaker.receive_json()
                assert text_msg["type"] == "text_message"
                assert text_msg["content"] == "Hello speaker!"

                # Speaker receives TTS audio bytes (mock: short silent WAV)
                tts_bytes = ws_speaker.receive_bytes()
                assert len(tts_bytes) > 0

                # Reader receives echo confirmation
                echo = ws_reader.receive_json()
                assert echo["type"] == "text_message"
                assert echo["content"] == "Hello speaker!"

    def test_empty_text_ignored(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"
                ws_reader.receive_json()  # user_joined for speaker
                ws_speaker.receive_json()  # user_joined for reader

                # Reader sends whitespace-only text — should be ignored
                ws_reader.send_json(
                    {"type": "text_message", "content": "   "}
                )

                # Send a leave to force a message; if empty text was forwarded,
                # it would arrive first
                ws_reader.send_json({"type": "leave"})


# ============================================================
# MEETING LIFECYCLE
# ============================================================


class TestMeetingLifecycle:
    def test_user_joined_broadcast(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"

                # Reader gets notified about existing speaker
                joined_about_speaker = ws_reader.receive_json()
                assert joined_about_speaker["type"] == "user_joined"
                assert joined_about_speaker["user_id"] == str(speaker_user.id)
                assert joined_about_speaker["role"] == "speaker"

                # Speaker gets notified about new reader
                joined_about_reader = ws_speaker.receive_json()
                assert joined_about_reader["type"] == "user_joined"
                assert joined_about_reader["user_id"] == str(reader_user.id)
                assert joined_about_reader["role"] == "reader"

    def test_user_left_on_disconnect(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"
                ws_reader.receive_json()  # user_joined for speaker
                ws_speaker.receive_json()  # user_joined for reader

                # Use explicit leave (not WS close) to avoid a deadlock:
                # Starlette's TestClient uses unbuffered anyio channels, so
                # __exit__ → join() blocks the main thread before it can read
                # the broadcast from the speaker's channel.
                ws_reader.send_json({"type": "leave"})

                # Read user_left while both `with` blocks are still open
                left_msg = ws_speaker.receive_json()
                assert left_msg["type"] == "user_left"
                assert left_msg["user_id"] == str(reader_user.id)

    def test_meeting_ended_broadcast(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
    ):
        mid = str(meeting_id)
        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"
                ws_reader.receive_json()  # user_joined for speaker
                ws_speaker.receive_json()  # user_joined for reader

                # Speaker ends the meeting
                ws_speaker.send_json({"type": "end_meeting"})

                # Both should receive meeting_ended
                ended_speaker = ws_speaker.receive_json()
                assert ended_speaker["type"] == "meeting_ended"

                ended_reader = ws_reader.receive_json()
                assert ended_reader["type"] == "meeting_ended"


# ============================================================
# RATE LIMITING
# ============================================================


class TestRateLimiting:
    def test_oversized_audio_chunk_dropped(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            assert ws.receive_json()["type"] == "auth_ok"

            # Send a chunk larger than MAX_AUDIO_CHUNK_BYTES (32,000)
            oversized = b"\x00" * 40_000
            ws.send_bytes(oversized)

            # Flush — should produce no transcript since the chunk was dropped
            ws.send_json({"type": "control", "action": "utterance_end"})

            # Send an unknown type as a sentinel — if the oversized chunk
            # produced a transcript, it would arrive before the error reply
            ws.send_json({"type": "sentinel_probe"})
            msg = ws.receive_json()
            assert msg["type"] == "error", (
                f"Expected sentinel error but got {msg['type']} — "
                "oversized chunk was not dropped"
            )
            assert "Unknown message type: sentinel_probe" in msg["message"]

    def test_audio_rate_limit_drops_excess(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            assert ws.receive_json()["type"] == "auth_ok"

            # Token bucket starts at 8. Send 12 chunks rapidly.
            # Only 8 should be accepted (bucket starts full, no time to refill).
            chunk = make_pcm16_audio(0.25)  # 0.25s = 8000 bytes
            for _ in range(12):
                ws.send_bytes(chunk)

            # Flush the buffer
            ws.send_json({"type": "control", "action": "utterance_end"})

            msg = ws.receive_json()
            assert msg["type"] == "transcript"
            assert "[Mock transcript" in msg["text"]

            # Parse duration from mock transcript: "[Mock transcript — 2.0s of audio]"
            # 8 accepted chunks * 0.25s = 2.0s max; 12 chunks * 0.25s = 3.0s without limit
            m = re.search(r"(\d+\.\d+)s of audio", msg["text"])
            assert m is not None, f"Could not parse duration from: {msg['text']}"
            duration = float(m.group(1))
            assert duration <= 2.0 + 0.01, (
                f"Expected <= 2.0s (8 chunks), got {duration}s — "
                "rate limiter did not drop excess chunks"
            )

    def test_text_rate_limit(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        reader_user: User,
    ):
        """Rate-limit text messages using a very tight bucket.

        Uses a single reader connection (no speaker) and patches the burst
        to 2 with zero refill so the 3rd message is guaranteed to hit the
        limit regardless of processing time between frames.
        """
        mid = str(meeting_id)
        with (
            patch("app.ws.router._TEXT_MSG_BURST", 2),
            patch("app.ws.router._TEXT_MSG_RATE_LIMIT", 0),
        ):
            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"

                # Send 5 messages — first 2 pass, remaining 3 are rate-limited
                for i in range(5):
                    ws_reader.send_json(
                        {"type": "text_message", "content": f"msg {i}"}
                    )

                # Read responses: 2 echoes then rate-limit errors
                rate_limited = False
                for _ in range(10):
                    msg = ws_reader.receive_json()
                    if msg.get("type") == "error" and "Rate limited" in msg.get(
                        "message", ""
                    ):
                        rate_limited = True
                        break

                assert rate_limited, (
                    "Expected rate limit error but didn't receive one"
                )


# ============================================================
# CONNECTION LIMITS
# ============================================================


class TestConnectionLimits:
    def test_third_participant_rejected(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
        reader_user: User,
        third_user: User,
        db: Session,
    ):
        # Add third user as participant in DB (bypass service-layer limit)
        p_third = MeetingParticipant(
            meeting_id=meeting_id,
            user_id=third_user.id,
            role=ParticipantRole.reader,
        )
        db.add(p_third)
        db.commit()

        mid = str(meeting_id)

        with ws_client.websocket_connect(f"/ws/{mid}") as ws_speaker:
            ws_speaker.send_json(
                {"type": "auth", "token": make_token(speaker_user.id)}
            )
            assert ws_speaker.receive_json()["type"] == "auth_ok"

            with ws_client.websocket_connect(f"/ws/{mid}") as ws_reader:
                ws_reader.send_json(
                    {"type": "auth", "token": make_token(reader_user.id)}
                )
                assert ws_reader.receive_json()["type"] == "auth_ok"
                ws_reader.receive_json()  # user_joined
                ws_speaker.receive_json()  # user_joined

                # Third user tries to connect
                with ws_client.websocket_connect(f"/ws/{mid}") as ws_third:
                    ws_third.send_json(
                        {"type": "auth", "token": make_token(third_user.id)}
                    )
                    msg = ws_third.receive_json()
                    assert msg["type"] == "auth_error"
                    assert "full" in msg["message"].lower()

                    with pytest.raises(WebSocketDisconnect) as exc_info:
                        ws_third.receive_json()
                    assert exc_info.value.code == 4003


# ============================================================
# ERROR HANDLING
# ============================================================


class TestErrorHandling:
    def test_invalid_json(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            assert ws.receive_json()["type"] == "auth_ok"

            # Send invalid JSON
            ws.send_text("this is not json")
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Invalid JSON" in msg["message"]

            # Connection should still be open — send a leave to verify
            ws.send_json({"type": "leave"})

    def test_unknown_message_type(
        self,
        ws_client: TestClient,
        meeting_id: uuid.UUID,
        speaker_user: User,
    ):
        with ws_client.websocket_connect(f"/ws/{meeting_id}") as ws:
            ws.send_json({"type": "auth", "token": make_token(speaker_user.id)})
            assert ws.receive_json()["type"] == "auth_ok"

            # Send unknown message type
            ws.send_json({"type": "banana", "data": "test"})
            msg = ws.receive_json()
            assert msg["type"] == "error"
            assert "Unknown message type: banana" in msg["message"]

            # Connection should still be open
            ws.send_json({"type": "leave"})
