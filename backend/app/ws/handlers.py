"""WebSocket message handlers.

Processes incoming audio (from speaker) through STT, persists transcripts,
broadcasts to the reader, and generates TTS audio for the speaker.
"""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone

from app import crud_meeting
from app.core.db import async_session_factory
from app.core.logging import time_stage
from app.ml.audio_utils import pcm16_bytes_to_float32
from app.ml.sign_to_text import sign_to_text_engine
from app.ml.stt import StreamingSTTBuffer, stt_engine
from app.ml.translation import translation_engine
from app.ml.tts import tts_engine
from app.models import MessageType
from app.ws.connection_manager import manager
from app.ws.keypoint_frame import KeypointFrameError, parse_keypoint_frame
from app.ws.sign_segment_buffer import SignSegmentBuffer

logger = logging.getLogger(__name__)


def _is_degenerate_text(text: str) -> bool:
    """Detect hallucinated, degenerate output — a single token repeated, e.g.
    'Oh, yeah, yeah, yeah, ...' that gloss-free Uni-Sign emits on weak/short
    input. Suppressing it avoids speaking confident nonsense to the speaker."""
    words = text.lower().split()
    if len(words) < 6:
        return False
    counts: dict[str, int] = {}
    for w in words:
        counts[w] = counts.get(w, 0) + 1
    return max(counts.values()) / len(words) > 0.5


def _get_stt_buffer_mode() -> str:
    """Read buffer mode from settings (import deferred to avoid circular)."""
    try:
        from app.core.config import settings

        return getattr(settings, "STT_BUFFER_MODE", "utterance")
    except Exception:
        return "utterance"


def _new_sign_segment_buffer() -> SignSegmentBuffer:
    """Build a segment buffer from settings (import deferred to avoid circular)."""
    try:
        from app.core.config import settings

        return SignSegmentBuffer(
            max_frames=settings.SIGN_TO_TEXT_MAX_FRAMES,
            pause_ms=settings.SIGN_TO_TEXT_PAUSE_MS,
            motion_threshold=settings.SIGN_TO_TEXT_MOTION_THRESHOLD,
            min_frames=settings.SIGN_TO_TEXT_MIN_FRAMES,
        )
    except Exception:
        return SignSegmentBuffer()


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
        # Per-reader keypoint accumulation + sentence segmentation (Direction B).
        self.sign_segment_buffer = _new_sign_segment_buffer()
        # Serialize segmentation feed/flush so overlapping keypoint frames can't
        # interleave a half-built sentence (mirrors _stt_lock).
        self._sign_lock = asyncio.Lock()
        # Recognized isolated signs (WLASL words) accumulate here across
        # per-sign segments and are spoken as one sentence when the reader ends
        # the sentence (stops signing / sign_segment_end).
        self._sign_words: list[str] = []
        self._active = True
        self._last_partial_time: float = 0.0
        # Audio rate limiting state
        self._audio_tokens: float = float(self.AUDIO_BURST_LIMIT)
        self._audio_last_refill: float = time.monotonic()
        # Serialize STT state-machine transitions. The current dispatch
        # path serializes naturally per-speaker, but defending the buffer's
        # peek/get/flush sequence with an explicit lock means a future
        # parallel transcription path can't interleave half-finished
        # utterances on the shared StreamingSTTBuffer.
        self._stt_lock = asyncio.Lock()

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
            # Tell the sender instead of dropping silently — otherwise the
            # speaker sees no transcript and has no idea their audio was
            # rejected for being too large.
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=sender_id,
                data={
                    "type": "error",
                    "message": "Audio chunk too large — dropped",
                },
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

        async with self._stt_lock:
            await self._handle_audio_chunk_locked(sender_id, audio_bytes)

    async def _handle_audio_chunk_locked(
        self, sender_id: uuid.UUID, audio_bytes: bytes
    ) -> None:
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
            with time_stage("stt", logger=logger, source="safety_cap"):
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
            with time_stage("stt", logger=logger, source="fixed_chunk"):
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

        async with self._stt_lock:
            await self._handle_utterance_end_locked(sender_id)

    async def _handle_utterance_end_locked(self, sender_id: uuid.UUID) -> None:
        result = self.stt_buffer.flush_utterance()
        if result is None:
            # Buffer empty or too short (< 100ms) — nothing to transcribe
            return

        audio, uid = result
        with time_stage("stt", logger=logger, source="utterance_end"):
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
                tts_stream = tts_engine.synthesize_sentences_streaming(content)
                with time_stage(
                    "tts",
                    logger=logger,
                    source="text_message",
                    chars=len(content),
                ):
                    try:
                        async for wav_chunk in tts_stream:
                            sent = await manager.send_bytes_to_user(
                                meeting_id=self.meeting_id,
                                user_id=speaker.user_id,
                                data=wav_chunk,
                            )
                            if not sent:
                                # Speaker disconnected mid-stream —
                                # close the generator so the producer
                                # thread can stop instead of draining
                                # into a dead queue.
                                logger.info(
                                    "TTS abort — speaker disconnected after %d chunks",
                                    chunk_count,
                                )
                                break
                            chunk_count += 1
                    finally:
                        aclose = getattr(tts_stream, "aclose", None)
                        if aclose is not None:
                            try:
                                await aclose()
                            except Exception as exc:
                                # Don't mask the original streaming outcome,
                                # but a failed cleanup can leave the producer
                                # in a bad state — make it visible.
                                logger.warning(
                                    "TTS generator cleanup (aclose) failed: %s",
                                    exc,
                                    exc_info=True,
                                )

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

        await self._persist_user_message(
            sender_id=sender_id,
            content=content,
            msg_type=MessageType.text_message,
            notify_label="your message",
        )

    async def handle_gloss_message(
        self,
        sender_id: uuid.UUID,
        content: str,
    ) -> None:
        """Reader sent ASL gloss input.

        Translate glosses to English -> TTS -> stream audio to Speaker.
        Reader sees only gloss UX; translated English stays invisible to reader.
        """
        if not self._active:
            return

        content = content.strip().upper()  # Normalize to uppercase
        if not content:
            return

        session = manager.get_session(self.meeting_id)
        if not session:
            return

        timestamp = datetime.now(timezone.utc).isoformat()

        # Echo gloss back to reader for confirmation
        gloss_echo = {
            "type": "gloss_message",
            "content": content,
            "sender_id": str(sender_id),
            "timestamp": timestamp,
        }
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data=gloss_echo,
        )

        # Translate gloss -> English
        if not translation_engine.is_loaded:
            logger.warning("Translation skipped — engine not loaded")
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=sender_id,
                data={"type": "error", "message": "Translation engine not available"},
            )
            await self._persist_user_message(
                sender_id=sender_id,
                content=content,
                msg_type=MessageType.gloss_input,
                notify_label="your gloss",
            )
            return

        try:
            with time_stage("translation", logger=logger, direction="gloss_to_english"):
                english = await translation_engine.gloss_to_english(content)
        except Exception as e:
            logger.error("Gloss translation error: %s", e)
            english = None

        if not english:
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=sender_id,
                data={"type": "error", "message": "Could not translate gloss"},
            )
            await self._persist_user_message(
                sender_id=sender_id,
                content=content,
                msg_type=MessageType.gloss_input,
                notify_label="your gloss",
            )
            return

        # Persist both: raw gloss input and translated English. Notify the
        # user only once on failure (the gloss carries the user-originated
        # signal — the English derivation rides on the same intent).
        gloss_ok = await self._persist_user_message(
            sender_id=sender_id,
            content=content,
            msg_type=MessageType.gloss_input,
            notify_label="your gloss",
        )
        if gloss_ok:
            # Best-effort save of the derived English; failure here is
            # already covered by the gloss save's error path semantics.
            await self._save_message(
                sender_id=sender_id,
                content=english,
                msg_type=MessageType.text_message,
            )

        # TTS: stream English to speaker (shared with the sign path).
        await self._stream_tts_to_speaker(english, source="gloss_message")

    async def _stream_tts_to_speaker(self, text: str, source: str) -> None:
        """Synthesize `text` and stream WAV chunks to the meeting's speaker.

        Shared by the gloss path (handle_gloss_message) and the gloss-free sign
        path (handle_keypoint_frames). No-ops (with a log) when there is no
        connected speaker or the TTS engine isn't loaded.
        """
        session = manager.get_session(self.meeting_id)
        speaker = session.speaker if session else None
        if not speaker:
            logger.warning("TTS skipped — no speaker connected")
            return
        if not tts_engine.is_loaded:
            logger.warning("TTS skipped — engine not loaded")
            return

        try:
            logger.info("TTS (from %s): streaming %d chars...", source, len(text))
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=speaker.user_id,
                data={"type": "tts_start"},
            )
            chunk_count = 0
            tts_stream = tts_engine.synthesize_sentences_streaming(text)
            with time_stage("tts", logger=logger, source=source, chars=len(text)):
                try:
                    async for wav_chunk in tts_stream:
                        sent = await manager.send_bytes_to_user(
                            meeting_id=self.meeting_id,
                            user_id=speaker.user_id,
                            data=wav_chunk,
                        )
                        if not sent:
                            logger.info(
                                "TTS (%s) abort — speaker disconnected after %d chunks",
                                source,
                                chunk_count,
                            )
                            break
                        chunk_count += 1
                finally:
                    aclose = getattr(tts_stream, "aclose", None)
                    if aclose is not None:
                        try:
                            await aclose()
                        except Exception as exc:
                            # Don't mask the original streaming outcome, but a
                            # failed cleanup can leave the producer in a bad
                            # state — make it visible.
                            logger.warning(
                                "TTS generator cleanup (aclose) failed: %s",
                                exc,
                                exc_info=True,
                            )
            logger.info("TTS (from %s): streamed %d chunks to speaker", source, chunk_count)
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=speaker.user_id,
                data={"type": "tts_end"},
            )
        except Exception as e:
            logger.error("TTS streaming (from %s) failed: %s", source, e)
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=speaker.user_id,
                data={"type": "error", "message": "Audio synthesis failed"},
            )

    async def handle_keypoint_frames(
        self,
        sender_id: uuid.UUID,
        frame: bytes,
    ) -> None:
        """Reader sent a binary RTMW keypoint frame (gloss-free Direction B).

        Accumulate into the per-reader segment buffer; on a sentence boundary,
        translate keypoints -> English via Uni-Sign, echo to the reader, persist,
        and stream TTS to the speaker. Inference only runs on flush, not per frame.
        """
        if not self._active:
            return

        try:
            keypoints, scores, _ = parse_keypoint_frame(frame)
        except KeypointFrameError as e:
            logger.warning("Bad keypoint frame from %s: %s", sender_id, e)
            return

        now_ms = time.monotonic() * 1000.0
        async with self._sign_lock:
            self.sign_segment_buffer.feed(keypoints, scores, now_ms)
            flush = self.sign_segment_buffer.should_flush(now_ms)
            # Debug-level motion trace (raise to INFO to retune the pause
            # threshold against real signing: compare `motion` here vs
            # SIGN_TO_TEXT_MOTION_THRESHOLD to see if rests register as pauses).
            logger.debug(
                "kp seg: +%d -> buffered=%d motion=%.4f flush=%s",
                keypoints.shape[0],
                len(self.sign_segment_buffer),
                self.sign_segment_buffer.motion_energy(
                    self.sign_segment_buffer.motion_window
                ),
                flush,
            )
            if not flush:
                return
            flushed = self.sign_segment_buffer.flush()
        if flushed is None:
            return
        # Recognize this one sign and add it to the building sentence (no speech
        # yet — the full sentence is spoken when the reader ends it).
        await self._recognize_and_accumulate(sender_id, *flushed)

    async def handle_sign_segment_end(self, sender_id: uuid.UUID) -> None:
        """Reader stopped the signing session — flush any in-progress sign,
        then translate the accumulated signs to English and speak the sentence.

        During the session, each sign is auto-recognized on a motion pause and
        appended live (reader sees the glosses build up); this finalizes and
        voices the whole sentence when the reader taps stop.
        """
        if not self._active:
            return
        async with self._sign_lock:
            flushed = self.sign_segment_buffer.flush()
        if flushed is not None:
            await self._recognize_and_accumulate(sender_id, *flushed)
        await self._finalize_sign_sentence(sender_id)

    async def _recognize_and_accumulate(
        self,
        sender_id: uuid.UUID,
        keypoints,
        scores,
    ) -> None:
        """Recognize ONE isolated sign and append it to the sentence buffer.

        Updates the reader's partial 'Recognized:' display as the sentence
        builds; does NOT speak — the full sentence is spoken on end-of-sentence.
        """
        from app.core.config import settings

        # Confidence / length gating — skip segments too short or too poorly
        # detected to recognize reliably (avoids hallucinated words).
        n_frames = len(keypoints)
        hand_conf = float(scores[:, 91:133].mean()) if n_frames else 0.0
        if (
            n_frames < settings.SIGN_TO_TEXT_MIN_FRAMES
            or hand_conf < settings.SIGN_TO_TEXT_MIN_CONFIDENCE
        ):
            logger.info(
                "sign gated: frames=%d hand_conf=%.2f (min_frames=%d, min_conf=%.2f)",
                n_frames,
                hand_conf,
                settings.SIGN_TO_TEXT_MIN_FRAMES,
                settings.SIGN_TO_TEXT_MIN_CONFIDENCE,
            )
            return

        if not sign_to_text_engine.is_loaded:
            logger.warning("Sign-to-text skipped — engine not loaded")
            return

        try:
            with time_stage("sign_to_text", logger=logger, frames=n_frames):
                word = await sign_to_text_engine.translate_keypoints(keypoints, scores)
        except Exception as e:
            logger.error("Sign-to-text inference error: %s", e)
            word = None

        if not word or _is_degenerate_text(word):
            logger.info("sign gated (empty/degenerate): %r", word)
            return

        self._sign_words.append(word.strip())
        # Partial feedback: show the sentence building up (no speech yet).
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data={
                "type": "sign_text",
                "content": " ".join(self._sign_words),
                "sender_id": str(sender_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "is_partial": True,
            },
        )

    async def _finalize_sign_sentence(self, sender_id: uuid.UUID) -> None:
        """End of sentence: turn the accumulated ASL-gloss words into grammatical
        English (gloss->English model), then speak it as one utterance.

        ISLR yields signs in ASL word order ("me name john"); the gloss->English
        model adds grammar ("My name is John"). Falls back to the raw gloss
        sequence if translation is unavailable or fails, so output is never lost.
        """
        if not self._sign_words:
            return
        gloss = " ".join(self._sign_words)
        self._sign_words = []

        english: str | None = None
        try:
            with time_stage("gloss_to_english", logger=logger, source="sign_frames"):
                english = await translation_engine.gloss_to_english(gloss.upper())
        except Exception as e:
            logger.warning("gloss->English failed, speaking raw gloss: %s", e)
        spoken = (english or "").strip() or gloss
        logger.info("sign sentence: gloss=%r -> english=%r", gloss, spoken)

        timestamp = datetime.now(timezone.utc).isoformat()
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data={
                "type": "sign_text",
                "content": spoken,
                "sender_id": str(sender_id),
                "timestamp": timestamp,
            },
        )
        await self._save_message(
            sender_id=sender_id,
            content=spoken,
            msg_type=MessageType.sign_translation,
        )
        await self._stream_tts_to_speaker(spoken, source="sign_frames")

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

        # Speaker always gets the original transcript
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data=transcript_msg,
        )

        # Flow 1: send gloss to reader for final transcripts only
        reader = session.reader
        if reader:
            if is_partial:
                pass  # reader never sees partials
            else:
                gloss = None
                if translation_engine.is_loaded:
                    try:
                        with time_stage(
                            "translation",
                            logger=logger,
                            direction="english_to_gloss",
                        ):
                            gloss = await translation_engine.english_to_gloss(transcript)
                    except Exception as e:
                        logger.error("Translation error in broadcast: %s", e)

                if gloss:
                    await manager.send_json_to_user(
                        meeting_id=self.meeting_id,
                        user_id=reader.user_id,
                        data={
                            "type": "gloss",
                            "text": gloss,
                            "utterance_id": utterance_id or "",
                            "sender_id": str(sender_id),
                            "timestamp": timestamp,
                        },
                    )
                    await self._save_message(
                        sender_id=sender_id,
                        content=gloss,
                        msg_type=MessageType.gloss_translation,
                    )
                else:
                    await manager.send_json_to_user(
                        meeting_id=self.meeting_id,
                        user_id=reader.user_id,
                        data={
                            "type": "gloss_error",
                            "utterance_id": utterance_id or "",
                            "message": "Translation unavailable",
                        },
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
    ) -> bool:
        """Save message to DB. Returns True on success, False on failure.

        Callers persisting user-originated content (text/gloss) should
        check the return value and surface an `error` to the sender so
        the user knows their message was not stored. Callers persisting
        auto-generated content (transcripts) can ignore the return value
        — sending a delayed error after a real-time transcript is more
        confusing than helpful, and Sentry already captures the failure.
        """
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
            return True
        except Exception as e:
            logger.error("Failed to save message: %s", e, exc_info=True)
            return False

    async def _persist_user_message(
        self,
        sender_id: uuid.UUID,
        content: str,
        msg_type: MessageType,
        notify_label: str,
    ) -> bool:
        """Persist user-originated content; on failure, notify the sender.

        `notify_label` is shown to the user in the error toast, e.g.
        "your message" or "your gloss". Returns the underlying save
        result so callers can branch if they need to.
        """
        ok = await self._save_message(
            sender_id=sender_id, content=content, msg_type=msg_type
        )
        if not ok:
            await manager.send_json_to_user(
                meeting_id=self.meeting_id,
                user_id=sender_id,
                data={
                    "type": "error",
                    "message": (
                        f"Could not save {notify_label} — "
                        "it was delivered but won't appear on reload"
                    ),
                },
            )
        return ok

    async def cleanup(self) -> None:
        """Quiesce a handler. Async so future cleanup steps (cancelling
        in-flight TTS/STT tasks, draining queues) can be awaited without
        a sync-vs-async mismatch."""
        self._active = False
        self.stt_buffer.clear()


# ── Handler Registry ──────────────────────────────────────────
_handlers: dict[uuid.UUID, MeetingHandler] = {}


def get_or_create_handler(meeting_id: uuid.UUID) -> MeetingHandler:
    if meeting_id not in _handlers:
        _handlers[meeting_id] = MeetingHandler(meeting_id)
    return _handlers[meeting_id]


async def remove_handler(meeting_id: uuid.UUID) -> None:
    handler = _handlers.pop(meeting_id, None)
    if handler:
        await handler.cleanup()
