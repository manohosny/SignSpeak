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

    def get_or_create_session(self, meeting_id: uuid.UUID) -> dict:
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

        await self._backend.unregister_participant(meeting_id, user_id)

    async def send_json_to_user(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID, data: dict
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
        data: dict,
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

    async def _safe_send_json(self, ws: WebSocket, data: dict) -> None:
        try:
            await ws.send_json(data)
        except Exception as e:
            logger.debug("Broadcast send failed: %s", e)

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
