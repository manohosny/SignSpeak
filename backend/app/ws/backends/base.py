"""Abstract session backend protocol for WebSocket connection management.

Defines the interface that all session backends (memory, Redis, etc.)
must implement. The ConnectionManager delegates state storage and
cross-process messaging to whatever backend is configured.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class SessionBackend(Protocol):
    """Pluggable backend for session state and cross-process messaging."""

    async def register_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        server_id: str,
    ) -> None:
        """Register a participant in a meeting."""
        ...

    async def unregister_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Remove a participant from a meeting."""
        ...

    async def get_participants(
        self,
        meeting_id: uuid.UUID,
    ) -> list[dict[str, Any]]:
        """Get all participants in a meeting.

        Returns list of dicts with keys: user_id, display_name, role, server_id.
        """
        ...

    async def is_meeting_full(self, meeting_id: uuid.UUID) -> bool:
        """Check if meeting has reached max participants (2)."""
        ...

    async def publish_message(
        self,
        meeting_id: uuid.UUID,
        message: dict[str, Any],
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        """Publish a message to all participants in a meeting.

        For memory backend: delivers directly to local WebSockets.
        For Redis backend: publishes to Redis channel for cross-server delivery.
        """
        ...

    async def subscribe(
        self,
        meeting_id: uuid.UUID,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Subscribe to messages for a meeting.

        Only used by Redis backend for cross-server message routing.
        Memory backend can yield nothing (messages are delivered directly).
        """
        ...
        yield  # type: ignore[misc]  # pragma: no cover

    async def close(self) -> None:
        """Clean up resources (connections, subscriptions, etc.)."""
        ...
