"""WebSocket message handlers.

Processes incoming audio (from speaker) through STT, persists transcripts,
broadcasts to the reader, and generates TTS audio for the speaker.
"""

import logging
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


class MeetingHandler:
    """Handles all message processing for one active meeting.

    Buffers Speaker audio, runs STT/TTS, routes results.
    One handler per meeting (not per connection).
    """

    def __init__(self, meeting_id: uuid.UUID) -> None:
        self.meeting_id = meeting_id
        self.stt_buffer = StreamingSTTBuffer()
        self._active = True

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

        audio_float32 = pcm16_bytes_to_float32(audio_bytes)
        self.stt_buffer.feed(audio_float32)

        if not self.stt_buffer.ready:
            return

        # Returns None if chunk is silent
        audio_chunk = self.stt_buffer.get_chunk()
        if audio_chunk is None:
            return

        transcript = await stt_engine.transcribe(audio_chunk)
        if not transcript:
            return

        logger.debug("STT: %s...", transcript[:80])
        await self._broadcast_transcript(sender_id, transcript)

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

        # Synthesize and send audio to Speaker
        if speaker and tts_engine.is_loaded:
            try:
                wav_bytes = await tts_engine.synthesize(content)
                await manager.send_bytes_to_user(
                    meeting_id=self.meeting_id,
                    user_id=speaker.user_id,
                    data=wav_bytes,
                )
            except Exception as e:
                logger.error("TTS failed: %s", e)
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
        remaining_audio = self.stt_buffer.flush()
        if remaining_audio is None:
            return

        transcript = await stt_engine.transcribe(remaining_audio)
        if not transcript:
            return

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
        self, sender_id: uuid.UUID, transcript: str
    ) -> None:
        """Build transcript message, send to both participants, and persist."""
        session = manager.get_session(self.meeting_id)
        if not session:
            return

        timestamp = datetime.now(timezone.utc).isoformat()
        transcript_msg = {
            "type": "transcript",
            "text": transcript,
            "is_partial": False,
            "sender_id": str(sender_id),
            "timestamp": timestamp,
        }

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
