"""In-memory session backend — default when no Redis is configured.

Stores all session state in Python dicts. Works for single-process
deployments. Cannot share state across multiple server instances.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

MAX_PARTICIPANTS = 2


@dataclass
class _ParticipantInfo:
    user_id: uuid.UUID
    display_name: str
    role: str
    server_id: str


@dataclass
class _MeetingState:
    meeting_id: uuid.UUID
    participants: dict[uuid.UUID, _ParticipantInfo] = field(default_factory=dict)


class MemorySessionBackend:
    """In-memory session backend — identical to original ConnectionManager behavior."""

    def __init__(self) -> None:
        self._meetings: dict[uuid.UUID, _MeetingState] = {}

    async def register_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        server_id: str,
    ) -> None:
        if meeting_id not in self._meetings:
            self._meetings[meeting_id] = _MeetingState(meeting_id=meeting_id)
        state = self._meetings[meeting_id]
        state.participants[user_id] = _ParticipantInfo(
            user_id=user_id,
            display_name=display_name,
            role=role,
            server_id=server_id,
        )
        logger.info(
            "Memory backend: %s (%s) registered in meeting %s",
            display_name,
            role,
            meeting_id,
        )

    async def unregister_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        state = self._meetings.get(meeting_id)
        if state and user_id in state.participants:
            removed = state.participants.pop(user_id)
            logger.info(
                "Memory backend: %s left meeting %s",
                removed.display_name,
                meeting_id,
            )
            if not state.participants:
                del self._meetings[meeting_id]
                logger.info("Memory backend: destroyed empty meeting %s", meeting_id)

    async def get_participants(
        self,
        meeting_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        state = self._meetings.get(meeting_id)
        if not state:
            return []
        return [
            {
                "user_id": str(p.user_id),
                "display_name": p.display_name,
                "role": p.role,
                "server_id": p.server_id,
            }
            for p in state.participants.values()
        ]

    async def is_meeting_full(self, meeting_id: uuid.UUID) -> bool:
        state = self._meetings.get(meeting_id)
        if not state:
            return False
        return len(state.participants) >= MAX_PARTICIPANTS

    async def publish_message(
        self,
        meeting_id: uuid.UUID,
        message: dict[str, Any],
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        # In memory mode, publishing is a no-op — ConnectionManager
        # handles direct local delivery via WebSocket references.
        pass

    async def subscribe(
        self,
        meeting_id: uuid.UUID,
    ) -> AsyncGenerator[dict[str, Any], None]:
        # Memory backend has no cross-server messages to receive.
        return
        yield  # pragma: no cover — makes this a valid async generator

    async def close(self) -> None:
        self._meetings.clear()
