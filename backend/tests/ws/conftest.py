"""WebSocket test fixtures.

Provides mock ML engines, DB entities (User, Meeting, MeetingParticipant),
JWT token helpers, and singleton cleanup for WebSocket integration tests.
"""

from __future__ import annotations

import struct
import uuid
from collections.abc import Generator
from datetime import timedelta
from math import sin, pi

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

from app.core.security import create_access_token, get_password_hash
from app.main import app
from app.models import (
    Meeting,
    MeetingParticipant,
    MeetingStatus,
    ParticipantRole,
    User,
)
from app.ws.connection_manager import manager
from app.ws.handlers import _handlers


# ── Helpers (not fixtures) ──────────────────────────────────


def make_token(user_id: uuid.UUID) -> str:
    """Generate a valid JWT for the given user."""
    return create_access_token(
        subject=str(user_id), expires_delta=timedelta(hours=1)
    )


def make_pcm16_audio(duration: float = 0.25, freq: float = 440.0) -> bytes:
    """Generate PCM16 16kHz mono audio bytes (sine wave)."""
    sr = 16000
    n_samples = int(sr * duration)
    samples = []
    for i in range(n_samples):
        t = i / sr
        value = 0.5 * sin(2 * pi * freq * t)
        # Clamp to int16 range and pack as little-endian signed 16-bit
        sample = max(-32768, min(32767, int(value * 32767)))
        samples.append(struct.pack("<h", sample))
    return b"".join(samples)


# ── Session-scoped fixtures ─────────────────────────────────


@pytest.fixture(scope="session", autouse=True)
def _enable_mock_mode():
    """Enable STT/TTS/Translation/Sign-to-Text mock mode so tests need no models."""
    import app.ml.sign_to_text as sign_to_text_mod
    import app.ml.stt as stt_mod
    import app.ml.tts as tts_mod
    import app.ml.translation as translation_mod

    stt_mod.MOCK_MODE = True
    tts_mod.MOCK_MODE = True
    translation_mod.MOCK_MODE = True
    sign_to_text_mod.MOCK_MODE = True

    stt_mod.stt_engine.load_model()
    tts_mod.tts_engine.load_model()
    translation_mod.translation_engine.load_model()
    sign_to_text_mod.sign_to_text_engine.load_model(
        repo_dir="", checkpoint="", mt5_dir=""
    )

    yield

    stt_mod.MOCK_MODE = False
    tts_mod.MOCK_MODE = False
    translation_mod.MOCK_MODE = False
    sign_to_text_mod.MOCK_MODE = False


# ── Function-scoped fixtures ────────────────────────────────


@pytest.fixture(autouse=True)
def _clean_ws_state():
    """Clear WebSocket singleton state after each test."""
    yield
    manager._local.clear()
    # Cancel any active per-meeting subscribe tasks so they don't leak
    # across tests (introduced in Task 5: Redis subscribe wiring).
    for task in list(getattr(manager, "_subscribe_tasks", {}).values()):
        if not task.done():
            task.cancel()
    if hasattr(manager, "_subscribe_tasks"):
        manager._subscribe_tasks.clear()
    if hasattr(manager._backend, "_meetings"):
        manager._backend._meetings.clear()
    _handlers.clear()


# ── Session-scoped fixtures (cont.) ────────────────────────


@pytest.fixture(scope="session")
def ws_client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def speaker_user(db: Session) -> User:
    user = User(
        email=f"speaker-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("testpass123"),
        is_active=True,
        full_name="Speaker Test",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="session")
def reader_user(db: Session) -> User:
    user = User(
        email=f"reader-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("testpass123"),
        is_active=True,
        full_name="Reader Test",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture(scope="session")
def third_user(db: Session) -> User:
    user = User(
        email=f"third-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("testpass123"),
        is_active=True,
        full_name="Third User",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@pytest.fixture()
def meeting_id(
    db: Session, speaker_user: User, reader_user: User
) -> Generator[uuid.UUID, None, None]:
    """Create a fresh meeting with speaker + reader participants."""
    meeting = Meeting(
        host_id=speaker_user.id,
        status=MeetingStatus.active,
    )
    db.add(meeting)
    db.commit()
    db.refresh(meeting)

    p_speaker = MeetingParticipant(
        meeting_id=meeting.id,
        user_id=speaker_user.id,
        role=ParticipantRole.speaker,
    )
    p_reader = MeetingParticipant(
        meeting_id=meeting.id,
        user_id=reader_user.id,
        role=ParticipantRole.reader,
    )
    db.add(p_speaker)
    db.add(p_reader)
    db.commit()

    yield meeting.id

    # Clean up meeting and participants so each test starts fresh
    db.execute(
        delete(MeetingParticipant).where(
            MeetingParticipant.meeting_id == meeting.id
        )
    )
    db.execute(delete(Meeting).where(Meeting.id == meeting.id))
    db.commit()
