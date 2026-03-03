"""WebSocket endpoint for real-time meeting communication.

Protocol:
1. Client connects to /ws/{meeting_id}
2. Client sends: { "type": "auth", "token": "<JWT>" }
3. Server responds: auth_ok or auth_error
4. Message loop until disconnect

Client -> Server:
- Binary frame: PCM16 audio (16kHz mono) from Speaker
- { "type": "text_message", "content": "..." } from Reader
- { "type": "leave" }
- { "type": "end_meeting" }

Server -> Client:
- { "type": "transcript", ... }
- { "type": "text_message", ... }
- Binary frame: TTS WAV audio
- { "type": "user_joined", ... }
- { "type": "user_left", ... }
- { "type": "meeting_ended" }
- { "type": "error", ... }
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app import crud_meeting
from app.core.db import async_session_factory
from app.core.security import decode_token
from app.models import Meeting, MeetingStatus, User
from app.ws.connection_manager import manager
from app.ws.handlers import MeetingHandler, get_or_create_handler, remove_handler

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/{meeting_id}")
async def meeting_websocket(
    websocket: WebSocket,
    meeting_id: uuid.UUID,
) -> None:
    await websocket.accept()

    # ── Phase 1: Authenticate ──
    auth_result = await _authenticate(websocket, meeting_id)
    if auth_result is None:
        return

    user_id, display_name, role = auth_result

    # ── Phase 2: Register ──
    # Capture existing participants BEFORE adding the new user so we can
    # notify the newcomer about who is already in the room.
    existing_session = manager.get_session(meeting_id)
    existing_participants = (
        list(existing_session.participants.values())
        if existing_session
        else []
    )

    manager.add_participant(
        meeting_id=meeting_id,
        user_id=user_id,
        display_name=display_name,
        role=role,
        websocket=websocket,
    )

    handler = get_or_create_handler(meeting_id)

    # Send auth_ok FIRST so the client sets up its state
    await websocket.send_json({
        "type": "auth_ok",
        "user_id": str(user_id),
        "role": role,
        "meeting_id": str(meeting_id),
    })

    # Notify the newcomer about each participant already in the room
    for p in existing_participants:
        await websocket.send_json({
            "type": "user_joined",
            "user_id": str(p.user_id),
            "display_name": p.display_name,
            "role": p.role,
        })

    # Broadcast the new user's arrival to everyone else
    await handler.handle_user_joined(user_id, display_name, role)

    # ── Phase 3: Message Loop ──
    speaker_flushed = False
    try:
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                await _handle_binary(handler, user_id, role, message["bytes"])

            elif "text" in message and message["text"]:
                should_break, flushed = await _handle_text(
                    websocket, handler, user_id, role, meeting_id,
                    message["text"],
                )
                if flushed:
                    speaker_flushed = True
                if should_break:
                    break

    except WebSocketDisconnect:
        logger.info("%s disconnected from meeting %s", display_name, meeting_id)
    except Exception as e:
        logger.error(
            "WebSocket error for %s: %s", display_name, e, exc_info=True
        )
    finally:
        # ── Phase 4: Cleanup ──
        if role == "speaker" and not speaker_flushed:
            await handler.handle_speaker_stopped(sender_id=user_id)

        await handler.handle_user_left(user_id, display_name)
        manager.remove_participant(meeting_id, user_id)

        await _mark_participant_left(meeting_id, user_id)

        session = manager.get_session(meeting_id)
        if session is None:
            remove_handler(meeting_id)
            logger.info(
                "Meeting %s — all gone, handler cleaned up", meeting_id
            )


# ============================================================
# MESSAGE DISPATCH
# ============================================================


async def _handle_binary(
    handler: MeetingHandler,
    user_id: uuid.UUID,
    role: str,
    audio_bytes: bytes,
) -> None:
    """Route binary (audio) frames from Speaker."""
    if role == "speaker":
        await handler.handle_audio_chunk(sender_id=user_id, audio_bytes=audio_bytes)
    else:
        logger.warning("Reader %s sent audio — ignoring", user_id)


async def _handle_text(
    websocket: WebSocket,
    handler: MeetingHandler,
    user_id: uuid.UUID,
    role: str,
    meeting_id: uuid.UUID,
    raw_text: str,
) -> tuple[bool, bool]:
    """Route JSON text frames. Returns (should_break, speaker_flushed)."""
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        await websocket.send_json({"type": "error", "message": "Invalid JSON"})
        return False, False

    msg_type = data.get("type")

    if msg_type == "text_message":
        content = data.get("content", "").strip()
        if content:
            await handler.handle_text_message(sender_id=user_id, content=content)
        return False, False

    if msg_type == "leave":
        flushed = False
        if role == "speaker":
            await handler.handle_speaker_stopped(sender_id=user_id)
            flushed = True
        return True, flushed

    if msg_type == "end_meeting":
        flushed = False
        if role == "speaker":
            await handler.handle_speaker_stopped(sender_id=user_id)
            flushed = True
        await handler.handle_meeting_ended()
        await _end_meeting_in_db(meeting_id)
        return True, flushed

    await websocket.send_json({
        "type": "error",
        "message": f"Unknown message type: {msg_type}",
    })
    return False, False


# ============================================================
# AUTH
# ============================================================


_AUTH_TIMEOUT_SECONDS = 10


async def _authenticate(
    websocket: WebSocket,
    meeting_id: uuid.UUID,
) -> tuple[uuid.UUID, str, str] | None:
    """Wait for auth message, validate JWT, verify participant.

    Returns (user_id, display_name, role) or None on failure.
    """
    try:
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=_AUTH_TIMEOUT_SECONDS,
            )
        except TimeoutError:
            await websocket.send_json({
                "type": "auth_error",
                "message": "Auth timeout — send auth message within 10s",
            })
            await websocket.close(code=4000, reason="Auth timeout")
            return None

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            await websocket.send_json({
                "type": "auth_error",
                "message": "Invalid JSON in auth message",
            })
            await websocket.close(code=4001, reason="Invalid JSON")
            return None

        if data.get("type") != "auth" or "token" not in data:
            await websocket.send_json({
                "type": "auth_error",
                "message": "First message must be: { type: 'auth', token: '...' }",
            })
            await websocket.close(code=4001, reason="Auth required")
            return None

        token = data["token"]

        payload = decode_token(token)
        if payload is None or payload.sub is None:
            await websocket.send_json({
                "type": "auth_error",
                "message": "Invalid or expired token",
            })
            await websocket.close(code=4001, reason="Invalid token")
            return None

        user_id = uuid.UUID(payload.sub)

        async with async_session_factory() as session:
            user = await session.get(User, user_id)
            if not user:
                await websocket.send_json({
                    "type": "auth_error",
                    "message": "User not found",
                })
                await websocket.close(code=4001, reason="User not found")
                return None

            if not user.is_active:
                await websocket.send_json({
                    "type": "auth_error",
                    "message": "Inactive user",
                })
                await websocket.close(code=4001, reason="Inactive user")
                return None

            meeting = await session.get(Meeting, meeting_id)
            if not meeting or meeting.status == MeetingStatus.ended:
                await websocket.send_json({
                    "type": "auth_error",
                    "message": "Meeting has ended or does not exist",
                })
                await websocket.close(code=4003, reason="Meeting ended")
                return None

            participant = await crud_meeting.get_participant(
                session=session, meeting_id=meeting_id, user_id=user_id
            )

            if not participant:
                await websocket.send_json({
                    "type": "auth_error",
                    "message": "Not a participant in this meeting",
                })
                await websocket.close(
                    code=4003, reason="Not a participant"
                )
                return None

            return (
                user.id,
                user.full_name or user.email,
                participant.role.value,
            )

    except Exception as e:
        logger.error("Auth failed: %s", e, exc_info=True)
        try:
            await websocket.send_json({
                "type": "auth_error",
                "message": "Authentication failed",
            })
            await websocket.close(code=4000, reason="Auth error")
        except Exception as send_err:
            logger.debug("Failed to send auth error to client: %s", send_err)
        return None


# ============================================================
# DB HELPERS
# ============================================================


async def _mark_participant_left(
    meeting_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Mark a participant as left via existing CRUD layer."""
    try:
        async with async_session_factory() as session:
            participant = await crud_meeting.get_participant(
                session=session, meeting_id=meeting_id, user_id=user_id
            )
            if participant and participant.left_at is None:
                await crud_meeting.mark_participant_left(
                    session=session,
                    participant=participant,
                    left_at=datetime.now(timezone.utc),
                )
                await session.commit()
    except Exception as e:
        logger.error("Failed to update participant left_at: %s", e)


async def _end_meeting_in_db(meeting_id: uuid.UUID) -> None:
    """Mark meeting as ended in DB."""
    try:
        async with async_session_factory() as session:
            meeting = await session.get(Meeting, meeting_id)
            if meeting and meeting.status != MeetingStatus.ended:
                meeting.status = MeetingStatus.ended
                meeting.ended_at = datetime.now(timezone.utc)
                session.add(meeting)
                await session.commit()
    except Exception as e:
        logger.error("Failed to end meeting in DB: %s", e)
