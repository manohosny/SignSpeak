"""Redis session backend for horizontally scalable WebSocket management.

Uses Redis for:
- Participant presence: per-participant keys with short TTL + heartbeat
- Cross-server messaging: Pub/Sub channels per meeting

Requires: redis[hiredis]>=5.0.0
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator

logger = logging.getLogger(__name__)

PARTICIPANT_TTL_SECONDS = 15
HEARTBEAT_INTERVAL_SECONDS = 5
MAX_PARTICIPANTS = 2


class RedisSessionBackend:
    """Redis-backed session backend with heartbeat-based presence."""

    def __init__(self, redis_url: str, server_id: str | None = None) -> None:
        self._redis_url = redis_url
        self._server_id = server_id or str(uuid.uuid4())
        self._redis = None
        self._pubsub = None
        self._heartbeat_task: asyncio.Task | None = None
        # Track locally-registered participants for heartbeat refresh
        self._local_participants: dict[
            uuid.UUID, set[uuid.UUID]
        ] = {}  # meeting_id -> {user_ids}

    async def connect(self) -> None:
        """Establish Redis connection and start heartbeat."""
        import redis.asyncio as aioredis

        self._redis = aioredis.from_url(
            self._redis_url,
            decode_responses=True,
        )
        await self._redis.ping()
        logger.info("Redis session backend connected: %s", self._redis_url)
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    def _participant_key(
        self, meeting_id: uuid.UUID, user_id: uuid.UUID
    ) -> str:
        return f"meeting:{meeting_id}:participant:{user_id}"

    def _participants_pattern(self, meeting_id: uuid.UUID) -> str:
        return f"meeting:{meeting_id}:participant:*"

    def _channel_name(self, meeting_id: uuid.UUID) -> str:
        return f"meeting:{meeting_id}:messages"

    async def register_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
        display_name: str,
        role: str,
        server_id: str,
    ) -> None:
        if not self._redis:
            raise RuntimeError("Redis not connected")

        key = self._participant_key(meeting_id, user_id)
        value = json.dumps(
            {
                "user_id": str(user_id),
                "display_name": display_name,
                "role": role,
                "server_id": server_id or self._server_id,
            }
        )
        await self._redis.set(key, value, ex=PARTICIPANT_TTL_SECONDS)

        # Track for heartbeat
        if meeting_id not in self._local_participants:
            self._local_participants[meeting_id] = set()
        self._local_participants[meeting_id].add(user_id)

        logger.info(
            "Redis backend: %s (%s) registered in meeting %s",
            display_name,
            role,
            meeting_id,
        )

    async def unregister_participant(
        self,
        meeting_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        if not self._redis:
            return

        key = self._participant_key(meeting_id, user_id)
        await self._redis.delete(key)

        # Remove from heartbeat tracking
        if meeting_id in self._local_participants:
            self._local_participants[meeting_id].discard(user_id)
            if not self._local_participants[meeting_id]:
                del self._local_participants[meeting_id]

        logger.info(
            "Redis backend: %s left meeting %s", user_id, meeting_id
        )

    async def get_participants(
        self,
        meeting_id: uuid.UUID,
    ) -> list[dict]:
        if not self._redis:
            return []

        pattern = self._participants_pattern(meeting_id)
        participants = []
        async for key in self._redis.scan_iter(match=pattern):
            value = await self._redis.get(key)
            if value:
                participants.append(json.loads(value))
        return participants

    async def is_meeting_full(self, meeting_id: uuid.UUID) -> bool:
        participants = await self.get_participants(meeting_id)
        return len(participants) >= MAX_PARTICIPANTS

    async def publish_message(
        self,
        meeting_id: uuid.UUID,
        message: dict,
        exclude_user: uuid.UUID | None = None,
    ) -> None:
        if not self._redis:
            return

        payload = json.dumps(
            {
                "message": message,
                "exclude_user": str(exclude_user) if exclude_user else None,
                "server_id": self._server_id,
            }
        )
        channel = self._channel_name(meeting_id)
        await self._redis.publish(channel, payload)

    async def subscribe(
        self,
        meeting_id: uuid.UUID,
    ) -> AsyncGenerator[dict, None]:
        """Subscribe to messages for a meeting.

        Yields message dicts from other servers (skips self-originated).
        """
        if not self._redis:
            return


        pubsub = self._redis.pubsub()
        channel = self._channel_name(meeting_id)
        await pubsub.subscribe(channel)

        try:
            async for raw_message in pubsub.listen():
                if raw_message["type"] != "message":
                    continue
                try:
                    payload = json.loads(raw_message["data"])
                except (json.JSONDecodeError, TypeError):
                    continue

                # Skip self-originated messages (Edge Case #3)
                if payload.get("server_id") == self._server_id:
                    continue

                yield {
                    "message": payload.get("message", {}),
                    "exclude_user": payload.get("exclude_user"),
                }
        except asyncio.CancelledError:
            pass
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

    async def _heartbeat_loop(self) -> None:
        """Refresh TTL for all locally-connected participants every 5 seconds."""
        try:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL_SECONDS)
                if not self._redis:
                    break
                for meeting_id, user_ids in list(
                    self._local_participants.items()
                ):
                    for user_id in list(user_ids):
                        key = self._participant_key(meeting_id, user_id)
                        try:
                            await self._redis.expire(
                                key, PARTICIPANT_TTL_SECONDS
                            )
                        except Exception as e:
                            logger.warning(
                                "Heartbeat failed for %s in %s: %s",
                                user_id,
                                meeting_id,
                                e,
                            )
        except asyncio.CancelledError:
            pass

    async def close(self) -> None:
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
        if self._redis:
            await self._redis.close()
            self._redis = None
        logger.info("Redis session backend closed")
