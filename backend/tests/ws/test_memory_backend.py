"""Tests for MemorySessionBackend."""

import uuid

import pytest

from app.ws.backends.memory import MemorySessionBackend


@pytest.fixture
def backend():
    return MemorySessionBackend()


@pytest.fixture
def meeting_id():
    return uuid.uuid4()


@pytest.fixture
def user_a():
    return uuid.uuid4()


@pytest.fixture
def user_b():
    return uuid.uuid4()


async def test_register_and_get_participants(backend, meeting_id, user_a):
    await backend.register_participant(
        meeting_id, user_a, "Alice", "speaker", "server-1"
    )
    participants = await backend.get_participants(meeting_id)
    assert len(participants) == 1
    assert participants[0]["display_name"] == "Alice"
    assert participants[0]["role"] == "speaker"


async def test_unregister_removes_participant(backend, meeting_id, user_a):
    await backend.register_participant(
        meeting_id, user_a, "Alice", "speaker", "server-1"
    )
    await backend.unregister_participant(meeting_id, user_a)
    participants = await backend.get_participants(meeting_id)
    assert len(participants) == 0


async def test_is_meeting_full(backend, meeting_id, user_a, user_b):
    assert not await backend.is_meeting_full(meeting_id)
    await backend.register_participant(
        meeting_id, user_a, "Alice", "speaker", "server-1"
    )
    assert not await backend.is_meeting_full(meeting_id)
    await backend.register_participant(
        meeting_id, user_b, "Bob", "reader", "server-1"
    )
    assert await backend.is_meeting_full(meeting_id)


async def test_empty_meeting_cleaned_up(backend, meeting_id, user_a):
    await backend.register_participant(
        meeting_id, user_a, "Alice", "speaker", "server-1"
    )
    await backend.unregister_participant(meeting_id, user_a)
    # Internal state should be cleaned up
    assert meeting_id not in backend._meetings


async def test_publish_is_noop(backend, meeting_id):
    """Memory backend publish is a no-op (ConnectionManager handles local delivery)."""
    await backend.publish_message(meeting_id, {"type": "test"})
    # No error — just verifies it doesn't crash


async def test_close_clears_state(backend, meeting_id, user_a):
    await backend.register_participant(
        meeting_id, user_a, "Alice", "speaker", "server-1"
    )
    await backend.close()
    assert len(backend._meetings) == 0
