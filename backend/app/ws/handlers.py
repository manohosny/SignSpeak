"""WebSocket message handlers.

Processes incoming audio (from speaker) through STT, persists transcripts,
broadcasts to the reader, and generates TTS audio for the speaker.
"""

import logging
import time
import uuid
from datetime import datetime, timezone

from app import crud_meeting
from app.core.db import async_session_factory
from app.ml.audio_utils import pcm16_bytes_to_float32
from app.ml.stt import StreamingSTTBuffer, stt_engine
from app.ml.tts import tts_engine
from app.models import MessageType
from app.ws.connection_manager import manager

logger = logging.getLogger(__name__)


def _get_stt_buffer_mode() -> str:
    """Read buffer mode from settings (import deferred to avoid circular)."""
    try:
        from app.core.config import settings

        return getattr(settings, "STT_BUFFER_MODE", "utterance")
    except Exception:
        return "utterance"


class MeetingHandler:
    """Handles all message processing for one active meeting.

    Buffers Speaker audio, runs STT/TTS, routes results.
    One handler per meeting (not per connection).
    """

    # Minimum interval between partial transcript emissions (seconds)
    PARTIAL_INTERVAL = 3.0

    # Audio rate limiting (token bucket)
    MAX_AUDIO_CHUNKS_PER_SEC = 5
    AUDIO_BURST_LIMIT = 8
    MAX_AUDIO_CHUNK_BYTES = 32_000  # 1 second of 16kHz PCM16 = 32KB

    def __init__(self, meeting_id: uuid.UUID) -> None:
        self.meeting_id = meeting_id
        self.stt_buffer = StreamingSTTBuffer(mode=_get_stt_buffer_mode())
        self._active = True
        self._last_partial_time: float = 0.0
        # Audio rate limiting state
        self._audio_tokens: float = float(self.AUDIO_BURST_LIMIT)
        self._audio_last_refill: float = time.monotonic()

    async def handle_audio_chunk(
        self,
        sender_id: uuid.UUID,
        audio_bytes: bytes,
    ) -> None:
        """Speaker sent PCM16 audio.

        Convert -> buffer -> STT when ready -> send transcript.
        """
        if not self._active:
            return

        # ── Rate limiting ──
        if len(audio_bytes) > self.MAX_AUDIO_CHUNK_BYTES:
            logger.warning(
                "Oversized audio chunk (%d bytes) from %s — dropped",
                len(audio_bytes), sender_id,
            )
            return

        now = time.monotonic()
        elapsed = now - self._audio_last_refill
        self._audio_tokens = min(
            self.AUDIO_BURST_LIMIT,
            self._audio_tokens + elapsed * self.MAX_AUDIO_CHUNKS_PER_SEC,
        )
        self._audio_last_refill = now

        if self._audio_tokens < 1.0:
            return  # silently drop — client is sending too fast

        self._audio_tokens -= 1.0

        audio_float32 = pcm16_bytes_to_float32(audio_bytes)
        self.stt_buffer.feed(audio_float32)

        # Emit partial transcript if enough audio accumulated (utterance mode)
        # Rate-limited to avoid excessive STT calls on every 250ms chunk
        now = time.monotonic()
        if (
            self.stt_buffer.has_partial
            and now - self._last_partial_time >= self.PARTIAL_INTERVAL
        ):
            result = self.stt_buffer.peek_utterance()
            if result is not None:
                audio, uid = result
                partial_text = await stt_engine.transcribe(audio)
                if partial_text:
                    self._last_partial_time = now
                    await self._broadcast_transcript(
                        sender_id,
                        partial_text,
                        is_partial=True,
                        utterance_id=uid,
                    )

        if not self.stt_buffer.ready:
            return

        # Buffer is ready: fixed-mode chunk or utterance-mode safety cap
        chunk_result = self.stt_buffer.get_chunk()
        if chunk_result is None:
            return

        if isinstance(chunk_result, tuple):
            # Utterance mode — safety-cap flush: (audio, utterance_id)
            audio_chunk, uid = chunk_result
            transcript = await stt_engine.transcribe(audio_chunk)
            if transcript:
                logger.debug("STT (safety-cap): %s...", transcript[:80])
                await self._broadcast_transcript(
                    sender_id,
                    transcript,
                    is_partial=False,
                    utterance_id=uid,
                )
        else:
            # Fixed mode — original behavior
            transcript = await stt_engine.transcribe(chunk_result)
            if transcript:
                logger.debug("STT: %s...", transcript[:80])
                await self._broadcast_transcript(sender_id, transcript)

    async def handle_utterance_end(
        self,
        sender_id: uuid.UUID,
    ) -> None:
        """Frontend signaled end of utterance (VAD silence transition).

        Flush the STT buffer and transcribe the complete utterance.
        Idempotent: returns early if buffer is too short (Edge Case #2).
        """
        if not self._active:
            return

        result = self.stt_buffer.flush_utterance()
        if result is None:
            # Buffer empty or too short (< 100ms) — nothing to transcribe
            return

        audio, uid = result
        transcript = await stt_engine.transcribe(audio)
        if not transcript:
            return

        logger.debug("STT (utterance): %s...", transcript[:80])
        await self._broadcast_transcript(
            sender_id,
            transcript,
            is_partial=False,
            utterance_id=uid,
        )
        # Note: _broadcast_transcript already persists final transcripts to DB

    async def handle_text_message(
        self,
        sender_id: uuid.UUID,
        content: str,
    ) -> None:
        """Reader sent text.

        Forward text to Speaker -> TTS -> send audio to Speaker.
        """
        if not self._active:
            return

        content = content.strip()
        if not content:
            return

        session = manager.get_session(self.meeting_id)
        if not session:
            return

        speaker = session.speaker
        timestamp = datetime.now(timezone.utc).isoformat()

        text_msg = {
            "type": "text_message",
            "content": content,
            "sender_id": str(sender_id),
            "timestamp": timestamp,
        }

        # Send text to Speaker immediately
        if speaker:
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=speaker.user_id,
                data=text_msg,
            )

        # Echo to Reader (confirmation)
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data=text_msg,
        )

        # Synthesize and stream audio to Speaker chunk-by-chunk
        if not speaker:
            logger.warning("TTS skipped — no speaker connected")
        elif not tts_engine.is_loaded:
            logger.warning("TTS skipped — engine not loaded")
        else:
            try:
                logger.info("TTS: streaming %d chars...", len(content))

                await manager.send_json_to_user(
                    meeting_id=self.meeting_id,
                    user_id=speaker.user_id,
                    data={"type": "tts_start"},
                )

                chunk_count = 0
                async for wav_chunk in tts_engine.synthesize_sentences_streaming(content):
                    await manager.send_bytes_to_user(
                        meeting_id=self.meeting_id,
                        user_id=speaker.user_id,
                        data=wav_chunk,
                    )
                    chunk_count += 1

                logger.info("TTS: streamed %d chunks to speaker", chunk_count)

                await manager.send_json_to_user(
                    meeting_id=self.meeting_id,
                    user_id=speaker.user_id,
                    data={"type": "tts_end"},
                )

            except Exception as e:
                logger.error("TTS streaming failed: %s", e)
                await manager.send_json_to_user(
                    meeting_id=self.meeting_id,
                    user_id=speaker.user_id,
                    data={
                        "type": "error",
                        "message": "Audio synthesis failed for this message",
                    },
                )

        await self._save_message(
            sender_id=sender_id,
            content=content,
            msg_type=MessageType.text_message,
        )

    async def handle_speaker_stopped(
        self,
        sender_id: uuid.UUID,
    ) -> None:
        """Flush remaining audio when Speaker stops mic or leaves."""
        remaining = self.stt_buffer.flush()
        if remaining is None:
            return

        if isinstance(remaining, tuple):
            # Utterance mode: (audio, utterance_id)
            audio, uid = remaining
            transcript = await stt_engine.transcribe(audio)
            if transcript:
                await self._broadcast_transcript(
                    sender_id,
                    transcript,
                    is_partial=False,
                    utterance_id=uid,
                )
        else:
            # Fixed mode: np.ndarray
            transcript = await stt_engine.transcribe(remaining)
            if transcript:
                await self._broadcast_transcript(sender_id, transcript)

    async def handle_user_joined(
        self, user_id: uuid.UUID, display_name: str, role: str
    ) -> None:
        await manager.broadcast_json(
            meeting_id=self.meeting_id,
            data={
                "type": "user_joined",
                "user_id": str(user_id),
                "display_name": display_name,
                "role": role,
            },
            exclude=user_id,
        )

    async def handle_user_left(
        self, user_id: uuid.UUID, display_name: str
    ) -> None:
        await manager.broadcast_json(
            meeting_id=self.meeting_id,
            data={
                "type": "user_left",
                "user_id": str(user_id),
                "display_name": display_name,
            },
            exclude=user_id,
        )

    async def handle_meeting_ended(self) -> None:
        await manager.broadcast_json(
            meeting_id=self.meeting_id,
            data={"type": "meeting_ended"},
        )
        self._active = False
        self.stt_buffer.clear()

    async def _broadcast_transcript(
        self,
        sender_id: uuid.UUID,
        transcript: str,
        is_partial: bool = False,
        utterance_id: str | None = None,
    ) -> None:
        """Build transcript message, send to both participants, and persist."""
        session = manager.get_session(self.meeting_id)
        if not session:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        transcript_msg: dict = {
            "type": "transcript",
            "text": transcript,
            "is_partial": is_partial,
            "sender_id": str(sender_id),
            "timestamp": timestamp,
        }
        if utterance_id:
            transcript_msg["utterance_id"] = utterance_id

        reader = session.reader
        if reader:
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=reader.user_id,
                data=transcript_msg,
            )

        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data=transcript_msg,
        )

        # Only persist final transcripts, not partials
        if not is_partial:
            await self._save_message(
                sender_id=sender_id,
                content=transcript,
                msg_type=MessageType.speech_transcript,
            )

    async def _save_message(
        self,
        sender_id: uuid.UUID,
        content: str,
        msg_type: MessageType,
    ) -> None:
        """Save message to DB via existing CRUD layer. Non-blocking, non-critical."""
        try:
            async with async_session_factory() as session:
                await crud_meeting.save_message(
                    session=session,
                    meeting_id=self.meeting_id,
                    sender_id=sender_id,
                    content=content,
                    msg_type=msg_type,
                )
                await session.commit()
        except Exception as e:
            logger.error("Failed to save message: %s", e)

    def cleanup(self) -> None:
        self._active = False
        self.stt_buffer.clear()


# ── Handler Registry ──────────────────────────────────────────
_handlers: dict[uuid.UUID, MeetingHandler] = {}


def get_or_create_handler(meeting_id: uuid.UUID) -> MeetingHandler:
    if meeting_id not in _handlers:
        _handlers[meeting_id] = MeetingHandler(meeting_id)
    return _handlers[meeting_id]


def remove_handler(meeting_id: uuid.UUID) -> None:
    handler = _handlers.pop(meeting_id, None)
    if handler:
        handler.cleanup()
