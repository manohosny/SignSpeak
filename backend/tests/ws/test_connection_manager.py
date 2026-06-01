"""Tests for ConnectionManager — subscribe-loop forwarding and broadcast_all.

Uses a mock SessionBackend so we don't need a live Redis. The interesting
behaviors are:
  1. Joining a meeting starts a subscribe task that forwards remote messages
     to local WebSockets.
  2. Leaving a meeting (last local participant) cancels the subscribe task.
  3. broadcast_all delivers to every active local WS.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator

import pytest

from app.ws.connection_manager import ConnectionManager


class _FakeWebSocket:
    def __init__(self) -> None:
        self.json_sent: list[dict] = []
        self.bytes_sent: list[bytes] = []

    async def send_json(self, data: dict) -> None:
        self.json_sent.append(data)

    async def send_bytes(self, data: bytes) -> None:
        self.bytes_sent.append(data)


class _FakeBackend:
    """Minimal SessionBackend impl that pumps a controllable queue."""

    def __init__(self) -> None:
        self.registered: list[tuple] = []
        self.unregistered: list[tuple] = []
        self.published: list[tuple] = []
        self._queue: asyncio.Queue[dict] = asyncio.Queue()
        self.subscribed_for: list[uuid.UUID] = []

    async def register_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        server_id: str,
    ) -> None:
        self.registered.append(
            (meeting_id, user_id, display_name, role, server_id)
        )

    async def unregister_participant(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        self.unregistered.append((meeting_id, user_id))

    async def publish_message(
        self,
        meeting_id: uuid.UUID,
        message: dict,
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        self.published.append((meeting_id, message, exclude_user))

    async def subscribe(
        self, meeting_id: uuid.UUID
    ) -> AsyncIterator[dict]:
        self.subscribed_for.append(meeting_id)
        while True:
            envelope = await self._queue.get()
            yield envelope

    async def push(self, envelope: dict) -> None:
        await self._queue.put(envelope)

    async def close(self) -> None:
        pass


@pytest.fixture
def manager_with_backend() -> tuple[ConnectionManager, _FakeBackend]:
    cm = ConnectionManager()
    backend = _FakeBackend()
    cm.set_backend(backend)
    return cm, backend


async def test_join_starts_subscribe_task(manager_with_backend) -> None:
    cm, backend = manager_with_backend
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ws = _FakeWebSocket()

    await cm.add_participant(
        meeting_id=meeting_id,
        user_id=user_id,
        display_name="Alice",
        role="speaker",
        websocket=ws,  # type: ignore[arg-type]
    )

    # Yield once so the subscribe task can start.
    await asyncio.sleep(0)
    assert meeting_id in cm._subscribe_tasks  # noqa: SLF001
    assert backend.subscribed_for == [meeting_id]

    await cm.remove_participant(meeting_id, user_id)


async def test_remote_message_delivered_to_local_websocket(
    manager_with_backend,
) -> None:
    cm, backend = manager_with_backend
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ws = _FakeWebSocket()

    await cm.add_participant(
        meeting_id=meeting_id,
        user_id=user_id,
        display_name="Alice",
        role="reader",
        websocket=ws,  # type: ignore[arg-type]
    )

    # Push a remote message into the backend's stream.
    await backend.push(
        {
            "message": {"type": "transcript", "text": "hello"},
            "exclude_user": None,
        }
    )

    # Give the consumer task a moment to forward.
    for _ in range(20):
        await asyncio.sleep(0.01)
        if ws.json_sent:
            break

    assert ws.json_sent == [{"type": "transcript", "text": "hello"}]

    await cm.remove_participant(meeting_id, user_id)


async def test_exclude_user_skipped_in_remote_delivery(
    manager_with_backend,
) -> None:
    cm, backend = manager_with_backend
    meeting_id = uuid.uuid4()
    speaker_id = uuid.uuid4()
    reader_id = uuid.uuid4()
    speaker_ws = _FakeWebSocket()
    reader_ws = _FakeWebSocket()

    await cm.add_participant(
        meeting_id=meeting_id,
        user_id=speaker_id,
        display_name="A",
        role="speaker",
        websocket=speaker_ws,  # type: ignore[arg-type]
    )
    await cm.add_participant(
        meeting_id=meeting_id,
        user_id=reader_id,
        display_name="B",
        role="reader",
        websocket=reader_ws,  # type: ignore[arg-type]
    )

    # Remote message says "exclude speaker". Reader should still receive.
    await backend.push(
        {
            "message": {"type": "transcript", "text": "hi"},
            "exclude_user": str(speaker_id),
        }
    )

    for _ in range(20):
        await asyncio.sleep(0.01)
        if reader_ws.json_sent:
            break

    assert reader_ws.json_sent == [{"type": "transcript", "text": "hi"}]
    assert speaker_ws.json_sent == []

    await cm.remove_participant(meeting_id, speaker_id)
    await cm.remove_participant(meeting_id, reader_id)


async def test_last_leave_cancels_subscribe_task(
    manager_with_backend,
) -> None:
    cm, _ = manager_with_backend
    meeting_id = uuid.uuid4()
    user_id = uuid.uuid4()
    ws = _FakeWebSocket()

    await cm.add_participant(
        meeting_id=meeting_id,
        user_id=user_id,
        display_name="A",
        role="speaker",
        websocket=ws,  # type: ignore[arg-type]
    )
    assert meeting_id in cm._subscribe_tasks  # noqa: SLF001
    task = cm._subscribe_tasks[meeting_id]  # noqa: SLF001

    await cm.remove_participant(meeting_id, user_id)

    # Give the cancel a tick to settle.
    await asyncio.sleep(0.01)
    assert meeting_id not in cm._subscribe_tasks  # noqa: SLF001
    assert task.cancelled() or task.done()


async def test_broadcast_all_delivers_to_every_local_ws(
    manager_with_backend,
) -> None:
    cm, _ = manager_with_backend
    m1 = uuid.uuid4()
    m2 = uuid.uuid4()
    a = _FakeWebSocket()
    b = _FakeWebSocket()
    c = _FakeWebSocket()

    await cm.add_participant(m1, uuid.uuid4(), "A", "speaker", a)  # type: ignore[arg-type]
    await cm.add_participant(m1, uuid.uuid4(), "B", "reader", b)  # type: ignore[arg-type]
    await cm.add_participant(m2, uuid.uuid4(), "C", "speaker", c)  # type: ignore[arg-type]

    await cm.broadcast_all({"type": "server_shutdown", "reason": "deploy"})

    msg = {"type": "server_shutdown", "reason": "deploy"}
    assert a.json_sent == [msg]
    assert b.json_sent == [msg]
    assert c.json_sent == [msg]

    await cm.close_all()


async def test_close_all_cancels_outstanding_tasks(
    manager_with_backend,
) -> None:
    cm, _ = manager_with_backend
    meeting_id = uuid.uuid4()
    ws = _FakeWebSocket()
    await cm.add_participant(
        meeting_id, uuid.uuid4(), "A", "speaker", ws  # type: ignore[arg-type]
    )
    assert cm._subscribe_tasks  # noqa: SLF001

    await cm.close_all()
    assert cm._subscribe_tasks == {}  # noqa: SLF001
