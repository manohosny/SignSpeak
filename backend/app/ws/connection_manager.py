"""WebSocket Connection Manager.

Tracks active meeting sessions, routes messages between participants.
Each meeting has at most 2 participants (speaker + reader).

Supports pluggable session backends:
- MemorySessionBackend (default): in-memory, single-process
- RedisSessionBackend: distributed, multi-process with pub/sub
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from app.ws.backends.memory import MemorySessionBackend

logger = logging.getLogger(__name__)


@dataclass
class Participant:
    user_id: uuid.UUID
    display_name: str
    role: str  # "speaker" | "reader"
    websocket: WebSocket


class ConnectionManager:
    """Manages all active WebSocket meeting sessions.

    Delegates session state to a pluggable backend (memory or Redis).
    Always maintains local WebSocket references — WebSocket objects
    are not serializable, so even with Redis, local delivery uses
    the in-process dict.
    """

    def __init__(self) -> None:
        self._backend = MemorySessionBackend()
        self._server_id = str(uuid.uuid4())
        # Local WebSocket references: meeting_id -> {user_id -> Participant}
        self._local: dict[uuid.UUID, dict[uuid.UUID, Participant]] = {}
        # Per-meeting subscribe tasks: forward backend pub/sub messages to
        # local WebSockets. Started on first local participant, cancelled
        # when the last leaves. Memory backend's subscribe is a no-op.
        self._subscribe_tasks: dict[uuid.UUID, asyncio.Task[None]] = {}

    def set_backend(self, backend: object) -> None:
        """Switch to a different session backend (e.g., Redis)."""
        self._backend = backend  # type: ignore[assignment]
        logger.info("Session backend switched to %s", type(backend).__name__)

    def _get_local_session(
        self, meeting_id: uuid.UUID
    ) -> dict[uuid.UUID, Participant]:
        if meeting_id not in self._local:
            self._local[meeting_id] = {}
        return self._local[meeting_id]

    def get_or_create_session(
        self, meeting_id: uuid.UUID
    ) -> dict[uuid.UUID, Participant]:
        """For backward compatibility with code that calls this method."""
        return self._get_local_session(meeting_id)

    def get_session(self, meeting_id: uuid.UUID) -> "_SessionView | None":
        """Get a view of the session for message routing."""
        local = self._local.get(meeting_id)
        if not local:
            return None
        return _SessionView(meeting_id, local)

    async def add_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        websocket: WebSocket,
    ) -> Participant:
        # Enforce 2-participant limit (speaker + reader)
        existing = self._local.get(meeting_id, {})
        if len(existing) >= 2 and user_id not in existing:
            raise ValueError("Meeting is full")

        participant = Participant(
            user_id=user_id,
            display_name=display_name,
            role=role,
            websocket=websocket,
        )

        # Register locally
        session = self._get_local_session(meeting_id)
        session[user_id] = participant

        # Register in backend (for Redis: creates key with TTL)
        await self._backend.register_participant(
            meeting_id=meeting_id,
            user_id=user_id,
            display_name=display_name,
            role=role,
            server_id=self._server_id,
        )

        # Spawn a subscribe task for this meeting if not already running.
        # The task forwards messages published by other replicas (or no-ops
        # under the memory backend) to local WebSockets.
        if meeting_id not in self._subscribe_tasks:
            self._subscribe_tasks[meeting_id] = asyncio.create_task(
                self._consume_remote_messages(meeting_id),
                name=f"ws-sub-{meeting_id}",
            )

        logger.info(
            "%s (%s) joined meeting %s", display_name, role, meeting_id
        )
        return participant

    async def remove_participant(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        local = self._local.get(meeting_id)
        if local and user_id in local:
            removed = local.pop(user_id)
            logger.info(
                "%s left meeting %s", removed.display_name, meeting_id
            )
            if not local:
                del self._local[meeting_id]
                logger.info("Destroyed empty local session: %s", meeting_id)
                # Last local participant left — stop forwarding remote messages.
                task = self._subscribe_tasks.pop(meeting_id, None)
                if task and not task.done():
                    task.cancel()

        await self._backend.unregister_participant(meeting_id, user_id)

    async def send_json_to_user(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID, data: dict[str, Any]
    ) -> bool:
        local = self._local.get(meeting_id)
        if not local:
            return False

        participant = local.get(user_id)
        if not participant:
            return False

        try:
            await participant.websocket.send_json(data)
            return True
        except Exception as e:
            logger.warning("Failed to send to %s: %s", user_id, e)
            return False

    async def send_bytes_to_user(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID, data: bytes
    ) -> bool:
        local = self._local.get(meeting_id)
        if not local:
            return False

        participant = local.get(user_id)
        if not participant:
            return False

        try:
            await participant.websocket.send_bytes(data)
            return True
        except Exception as e:
            logger.warning("Failed to send bytes to %s: %s", user_id, e)
            return False

    async def broadcast_json(
        self,
        meeting_id: uuid.UUID,
        data: dict[str, Any],
        exclude: uuid.UUID | None = None,
    ) -> None:
        """Broadcast JSON to all participants.

        Local-first delivery (Edge Case #3): delivers to local WebSockets
        in parallel with Redis publish, so same-node latency is near-zero.
        """
        local = self._local.get(meeting_id)

        async def _local_send() -> None:
            if not local:
                return
            tasks = []
            for uid, participant in local.items():
                if uid != exclude:
                    tasks.append(
                        self._safe_send_json(participant.websocket, data)
                    )
            if tasks:
                await asyncio.gather(*tasks)

        async def _backend_publish() -> None:
            try:
                await self._backend.publish_message(
                    meeting_id, data, exclude_user=exclude
                )
            except Exception as e:
                logger.warning("Backend publish failed: %s", e)

        # Run local delivery and backend publish concurrently
        await asyncio.gather(_local_send(), _backend_publish())

    async def _safe_send_json(self, ws: WebSocket, data: dict[str, Any]) -> None:
        try:
            await ws.send_json(data)
        except Exception as e:
            logger.debug("Broadcast send failed: %s", e)

    async def _consume_remote_messages(self, meeting_id: uuid.UUID) -> None:
        """Forward messages from the backend's subscribe stream to local WSs.

        The Redis backend already filters self-originated messages by
        server_id, so anything that reaches us here came from a *different*
        replica and should be delivered to our local participants.
        """
        try:
            async for envelope in self._backend.subscribe(meeting_id):
                msg = envelope.get("message") if isinstance(envelope, dict) else None
                if not isinstance(msg, dict):
                    continue
                exclude_raw = (
                    envelope.get("exclude_user")
                    if isinstance(envelope, dict)
                    else None
                )
                local = self._local.get(meeting_id)
                if not local:
                    continue
                tasks = []
                for uid, participant in local.items():
                    if exclude_raw and str(uid) == exclude_raw:
                        continue
                    tasks.append(self._safe_send_json(participant.websocket, msg))
                if tasks:
                    await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(
                "Remote subscribe loop for meeting %s exited: %s",
                meeting_id,
                e,
            )

    async def broadcast_all(self, data: dict[str, Any]) -> None:
        """Send a JSON frame to every active local WebSocket.

        Used at graceful shutdown so clients can transition to a
        "reconnecting" state instead of seeing a generic disconnect.
        """
        tasks = []
        for participants in self._local.values():
            for p in participants.values():
                tasks.append(self._safe_send_json(p.websocket, data))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def close_all(self) -> None:
        """Cancel any active subscribe tasks. Used at shutdown."""
        for task in list(self._subscribe_tasks.values()):
            if not task.done():
                task.cancel()
        # Let them settle so finally-blocks run.
        if self._subscribe_tasks:
            await asyncio.gather(
                *self._subscribe_tasks.values(), return_exceptions=True
            )
        self._subscribe_tasks.clear()

    @property
    def active_session_count(self) -> int:
        return len(self._local)


class _SessionView:
    """Lightweight view over a local meeting session for message routing."""

    def __init__(
        self,
        meeting_id: uuid.UUID,
        participants: dict[uuid.UUID, Participant],
    ) -> None:
        self.meeting_id = meeting_id
        self.participants = participants

    def get_by_role(self, role: str) -> Participant | None:
        return next(
            (p for p in self.participants.values() if p.role == role), None
        )

    @property
    def speaker(self) -> Participant | None:
        return self.get_by_role("speaker")

    @property
    def reader(self) -> Participant | None:
        return self.get_by_role("reader")

    def get_partner(self, user_id: uuid.UUID) -> Participant | None:
        return next(
            (p for p in self.participants.values() if p.user_id != user_id),
            None,
        )

    @property
    def is_full(self) -> bool:
        return len(self.participants) >= 2


# Singleton
manager = ConnectionManager()
