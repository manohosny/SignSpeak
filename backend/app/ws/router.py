"""WebSocket endpoint for real-time meeting communication.

Protocol:
1. Client connects to /ws/{meeting_id}
2. Client sends: { "type": "auth", "token": "<JWT>" }
3. Server responds: auth_ok or auth_error
4. Message loop until disconnect

Client -> Server:
- Binary frame: PCM16 audio (16kHz mono) from Speaker
- { "type": "gloss_message", "content": "..." } from Reader (ASL gloss notation)
- { "type": "leave" }
- { "type": "end_meeting" }

Server -> Client:
- { "type": "transcript", ... }           Speaker sees own English transcript
- { "type": "gloss", "text": "..." }      Reader sees ASL gloss translation
- { "type": "gloss_message", ... }        Echo of reader's gloss input
- { "type": "gloss_error", ... }          Translation failure notification
- Binary frame: TTS WAV audio
- { "type": "tts_start" / "tts_end" }
- { "type": "user_joined", ... }
- { "type": "user_left", ... }
- { "type": "meeting_ended" }
- { "type": "error", ... }
"""

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import TypeAdapter, ValidationError

from app import crud_meeting
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.logging import bind_context, clear_context
from app.core.security import ACCESS_TOKEN_COOKIE, decode_token
from app.models import Meeting, MeetingStatus, TokenPayload, User
from app.ws.connection_manager import manager
from app.ws.handlers import MeetingHandler, get_or_create_handler, remove_handler
from app.ws.schemas import WsClientMessage

logger = logging.getLogger(__name__)

# Text message rate limiting (token bucket)
_TEXT_MSG_RATE_LIMIT = 10  # max text messages per second
_TEXT_MSG_BURST = 20

# Gloss message rate limiting (token bucket). Each gloss frame triggers
# translation + TTS inference (CPU/GPU-bound), so it is capped tighter than
# text_message to keep one reader from starving the meeting.
_GLOSS_MSG_RATE_LIMIT = 3  # max gloss messages per second
_GLOSS_MSG_BURST = 6

# Per-frame size caps. Audio frames are typically 16 kB at 16 kHz × 1 s; cap
# generously above that. Text frames carry control messages and short gloss
# strings (≤5 kB enforced server-side); cap an order of magnitude above.
_MAX_BINARY_BYTES = 1 << 20      # 1 MB
_MAX_TEXT_BYTES = 64 << 10       # 64 KB

# Pydantic discriminated-union adapter for incoming text messages. Using
# this surfaces malformed payloads immediately instead of letting handlers
# duck-type their way to a confusing 500.
_CLIENT_MSG_ADAPTER: TypeAdapter[WsClientMessage] = TypeAdapter(WsClientMessage)

router = APIRouter()


def _take_token(
    tokens: float, last_refill: float, rate: int, burst: int
) -> tuple[bool, float, float]:
    """Advance a token bucket and try to consume one token.

    Returns (allowed, new_tokens, new_last_refill). When ``allowed`` is
    False the caller should reject the frame; the bucket state is still
    returned so the refill clock keeps advancing.
    """
    now = time.monotonic()
    tokens = min(burst, tokens + (now - last_refill) * rate)
    if tokens < 1.0:
        return False, tokens, now
    return True, tokens - 1.0, now


@router.websocket("/ws/{meeting_id}")
async def meeting_websocket(
    websocket: WebSocket,
    meeting_id: uuid.UUID,
) -> None:
    # ── Phase 0: Pre-accept hardening ──
    # Reject disallowed origins before consuming a server-side socket. The
    # CORS middleware doesn't apply to WS upgrades, so this check has to
    # be explicit. Empty origin (non-browser clients) is allowed through.
    origin = websocket.headers.get("origin")
    if origin and origin not in settings.all_cors_origins:
        await websocket.close(code=4403, reason="Origin not allowed")
        return

    # Pre-accept JWT validation eliminates the unauthenticated-socket DoS
    # surface for browser clients. Token sources, in priority order:
    #
    #   1. HttpOnly access-token cookie (preferred — not visible in logs,
    #      sent automatically on the WS upgrade like any other cookie).
    #   2. `?token=` query string (legacy, kept for clients that can't
    #      set cookies; tolerated until callers migrate).
    #   3. First-message `{"type":"auth","token":...}` (fallback for
    #      non-browser clients that can't set headers either).
    pre_accept_payload: TokenPayload | None = None
    pre_accept_token = (
        websocket.cookies.get(ACCESS_TOKEN_COOKIE)
        or websocket.query_params.get("token")
    )
    if pre_accept_token:
        pre_accept_payload = decode_token(pre_accept_token, expected_type="access")
        if pre_accept_payload is None or pre_accept_payload.sub is None:
            await websocket.close(code=4001, reason="Invalid token")
            return

    await websocket.accept()

    # ── Phase 1: Authenticate ──
    if pre_accept_payload is not None:
        auth_result = await _resolve_pre_validated(
            websocket, meeting_id, pre_accept_payload
        )
    else:
        auth_result = await _authenticate(websocket, meeting_id)
    if auth_result is None:
        return

    user_id, display_name, role = auth_result

    # Bind correlation context for every log line emitted while this socket
    # is alive (including handler stages, ML timings, DB writes).
    log_token = bind_context(
        meeting_id=str(meeting_id),
        user_id=str(user_id),
        role=role,
    )

    # ── Phase 2: Register ──
    # Capture existing participants BEFORE adding the new user so we can
    # notify the newcomer about who is already in the room.
    existing_session = manager.get_session(meeting_id)
    existing_participants = (
        list(existing_session.participants.values())
        if existing_session
        else []
    )

    try:
        await manager.add_participant(
            meeting_id=meeting_id,
            user_id=user_id,
            display_name=display_name,
            role=role,
            websocket=websocket,
        )
    except ValueError:
        await websocket.send_json({
            "type": "auth_error",
            "message": "Meeting is full",
        })
        await websocket.close(code=4003, reason="Meeting full")
        return

    # Anything after this point that raises must roll back the
    # participant registration — otherwise a slot leaks and the meeting
    # can permanently appear "full" without a live socket.
    try:
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
    except Exception:
        logger.exception(
            "Failed to finalize WS registration for %s in %s — rolling back",
            display_name,
            meeting_id,
        )
        try:
            await manager.remove_participant(meeting_id, user_id)
        except Exception:
            logger.exception("Rollback remove_participant also failed")
        # `get_or_create_handler` above may have created a fresh handler.
        # This early-return path skips Phase 4 cleanup, so if this socket
        # was the last/only participant the handler would leak (STT buffer,
        # rate-limit tokens, audio state). Mirror Phase 4's empty-session
        # check — a handler still shared with a live participant is kept.
        if manager.get_session(meeting_id) is None:
            try:
                await remove_handler(meeting_id)
            except Exception:
                logger.exception("Rollback remove_handler also failed")
        try:
            await websocket.close(code=1011, reason="Registration failed")
        except Exception:
            pass
        return

    # ── Phase 3: Message Loop ──
    speaker_flushed = False
    # Per-socket rate-limit buckets: text messages and (heavier) gloss messages.
    text_tokens: float = float(_TEXT_MSG_BURST)
    text_last_refill: float = time.monotonic()
    gloss_tokens: float = float(_GLOSS_MSG_BURST)
    gloss_last_refill: float = time.monotonic()
    try:
        while True:
            # No application-level idle timeout here: a reader watching the
            # avatar legitimately sends nothing upstream for long stretches,
            # and an idle-data timeout would wrongly drop a healthy socket.
            # Dead connections are detected by uvicorn's WebSocket ping/pong
            # and surface below as a `websocket.disconnect` message.
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                payload = message["bytes"]
                if len(payload) > _MAX_BINARY_BYTES:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Binary frame too large",
                    })
                    await websocket.close(code=1009, reason="Frame too large")
                    break
                await _handle_binary(handler, user_id, role, payload)

            elif "text" in message and message["text"]:
                raw_text = message["text"]
                # Reject oversize text BEFORE allocating a JSON parser.
                if len(raw_text) > _MAX_TEXT_BYTES:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Text frame too large",
                    })
                    await websocket.close(code=1009, reason="Frame too large")
                    break

                # Rate limit non-critical messages (not leave/end/control).
                # text_message and gloss_message each get their own bucket;
                # gloss is capped tighter because it drives ML inference.
                try:
                    msg_type = json.loads(raw_text).get("type")
                except (json.JSONDecodeError, AttributeError):
                    msg_type = None

                if msg_type == "text_message":
                    allowed, text_tokens, text_last_refill = _take_token(
                        text_tokens, text_last_refill,
                        _TEXT_MSG_RATE_LIMIT, _TEXT_MSG_BURST,
                    )
                    if not allowed:
                        await websocket.send_json(
                            {"type": "error", "message": "Rate limited"}
                        )
                        continue
                elif msg_type == "gloss_message":
                    allowed, gloss_tokens, gloss_last_refill = _take_token(
                        gloss_tokens, gloss_last_refill,
                        _GLOSS_MSG_RATE_LIMIT, _GLOSS_MSG_BURST,
                    )
                    if not allowed:
                        await websocket.send_json(
                            {"type": "error", "message": "Rate limited"}
                        )
                        continue

                should_break, flushed = await _handle_text(
                    websocket, handler, user_id, role, meeting_id,
                    raw_text,
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
        await manager.remove_participant(meeting_id, user_id)

        await _mark_participant_left(meeting_id, user_id)

        session = manager.get_session(meeting_id)
        if session is None:
            await remove_handler(meeting_id)
            logger.info(
                "Meeting %s — all gone, handler cleaned up", meeting_id
            )

        clear_context(log_token)


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

    try:
        msg = _CLIENT_MSG_ADAPTER.validate_python(data)
    except ValidationError as e:
        # Preserve the legacy "Unknown message type: <type>" wording
        # whenever the failure is specifically the discriminator field —
        # clients (and the existing test suite) pattern-match that string.
        # `union_tag_invalid` is raised only when the `type` discriminator
        # matches no union member, so the error type alone identifies it.
        # Its `loc` is the empty tuple `()` — do NOT index into it (`()[0]`
        # raises IndexError, which previously escaped and killed the socket).
        first_error = e.errors()[0]
        is_unknown_type = first_error.get("type") == "union_tag_invalid"
        if is_unknown_type:
            await websocket.send_json({
                "type": "error",
                "message": f"Unknown message type: {data.get('type')}",
            })
        else:
            await websocket.send_json({
                "type": "error",
                "message": f"Invalid message: {first_error.get('msg', 'validation error')}",
            })
        return False, False

    if msg.type == "gloss_message":
        content = msg.content.strip()
        if content:
            await handler.handle_gloss_message(sender_id=user_id, content=content)
        return False, False

    if msg.type == "leave":
        flushed = False
        if role == "speaker":
            await handler.handle_speaker_stopped(sender_id=user_id)
            flushed = True
        return True, flushed

    if msg.type == "end_meeting":
        flushed = False
        if role == "speaker":
            await handler.handle_speaker_stopped(sender_id=user_id)
            flushed = True
        await handler.handle_meeting_ended()
        await _end_meeting_in_db(meeting_id)
        return True, flushed

    if msg.type == "control":
        if msg.action == "utterance_end" and role == "speaker":
            await handler.handle_utterance_end(sender_id=user_id)
        return False, False

    if msg.type == "text_message":
        # text_message frames are passed through here just so they aren't
        # rejected as "unknown" by the dispatch — the actual rate-limit and
        # routing happens before this call. They are not stored or echoed
        # by the backend yet.
        return False, False

    if msg.type == "auth":
        # Re-sending auth mid-session is not meaningful; ignore quietly.
        return False, False

    await websocket.send_json({
        "type": "error",
        "message": f"Unknown message type: {msg.type}",
    })
    return False, False


async def _resolve_pre_validated(
    websocket: WebSocket,
    meeting_id: uuid.UUID,
    payload: TokenPayload,
) -> tuple[uuid.UUID, str, str] | None:
    """Finish auth for a token that was already JWT-validated pre-accept.

    Mirrors `_authenticate` but skips JWT parsing — the signature, expiry,
    and `type=access` claim were already checked before the upgrade
    completed. This function still confirms user, meeting, and participant
    state against the DB, and emits the same auth_error/close on failure.
    """
    if not payload.sub:
        await websocket.send_json({
            "type": "auth_error",
            "message": "Invalid token",
        })
        await websocket.close(code=4001, reason="Invalid token")
        return None
    try:
        user_id = uuid.UUID(payload.sub)
    except ValueError:
        await websocket.send_json({
            "type": "auth_error",
            "message": "Invalid token",
        })
        await websocket.close(code=4001, reason="Invalid token")
        return None

    async with async_session_factory() as session:
        user = await session.get(User, user_id)
        if not user or not user.is_active:
            await websocket.send_json({
                "type": "auth_error",
                "message": "User not found or inactive",
            })
            await websocket.close(code=4001, reason="User invalid")
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
            await websocket.close(code=4003, reason="Not a participant")
            return None

        return (
            user.id,
            user.full_name or user.email,
            participant.role.value,
        )


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
        except (TimeoutError, asyncio.TimeoutError):
            await websocket.send_json({
                "type": "auth_error",
                "message": "Auth timeout — send auth message within 10s",
            })
            await websocket.close(code=4000, reason="Auth timeout")
            return None

        if len(raw) > _MAX_TEXT_BYTES:
            await websocket.close(code=1009, reason="Auth frame too large")
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

        payload = decode_token(token, expected_type="access")
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
