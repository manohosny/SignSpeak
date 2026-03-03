"""WebSocket Connection Manager.

Tracks active meeting sessions, routes messages between participants.
Each meeting has at most 2 participants (speaker + reader).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field

from fastapi import WebSocket

logger = logging.getLogger(__name__)


@dataclass
class Participant:
    user_id: uuid.UUID
    display_name: str
    role: str  # "speaker" | "reader"
    websocket: WebSocket


@dataclass
class MeetingSession:
    """In-memory state for an active meeting."""

    meeting_id: uuid.UUID
    participants: dict[uuid.UUID, Participant] = field(default_factory=dict)

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


class ConnectionManager:
    """Singleton that manages all active WebSocket meeting sessions.

    Thread-safety note: designed for asyncio single-threaded concurrency.
    All methods must be called from the same event loop.
    For multi-worker deployments, this would need Redis pub/sub.
    """

    def __init__(self) -> None:
        self._sessions: dict[uuid.UUID, MeetingSession] = {}

    def get_or_create_session(self, meeting_id: uuid.UUID) -> MeetingSession:
        if meeting_id not in self._sessions:
            self._sessions[meeting_id] = MeetingSession(meeting_id=meeting_id)
            logger.info("Created meeting session: %s", meeting_id)
        return self._sessions[meeting_id]

    def get_session(self, meeting_id: uuid.UUID) -> MeetingSession | None:
        return self._sessions.get(meeting_id)

    def add_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        websocket: WebSocket,
    ) -> Participant:
        session = self.get_or_create_session(meeting_id)
        participant = Participant(
            user_id=user_id,
            display_name=display_name,
            role=role,
            websocket=websocket,
        )
        session.participants[user_id] = participant
        logger.info(
            "%s (%s) joined meeting %s", display_name, role, meeting_id
        )
        return participant

    def remove_participant(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> None:
        session = self._sessions.get(meeting_id)
        if session and user_id in session.participants:
            removed = session.participants.pop(user_id)
            logger.info(
                "%s left meeting %s", removed.display_name, meeting_id
            )

            if not session.participants:
                del self._sessions[meeting_id]
                logger.info("Destroyed empty session: %s", meeting_id)

    async def send_json_to_user(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID, data: dict
    ) -> bool:
        session = self._sessions.get(meeting_id)
        if not session:
            return False

        participant = session.participants.get(user_id)
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
        session = self._sessions.get(meeting_id)
        if not session:
            return False

        participant = session.participants.get(user_id)
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
        session = self._sessions.get(meeting_id)
        if not session:
            return

        tasks = []
        for uid, participant in session.participants.items():
            if uid != exclude:
                tasks.append(self._safe_send_json(participant.websocket, data))

        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_send_json(self, ws: WebSocket, data: dict) -> None:
        try:
            await ws.send_json(data)
        except Exception as e:
            logger.debug("Broadcast send failed: %s", e)

    @property
    def active_session_count(self) -> int:
        return len(self._sessions)


# Singleton
manager = ConnectionManager()
