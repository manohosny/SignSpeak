"""Handler-level tests for the gloss-free keypoint path (Direction B).

Drives MeetingHandler.handle_keypoint_frames / handle_sign_segment_end with the
sign_to_text engine in MOCK_MODE, mocking the connection manager + DB persistence
so we exercise segmentation -> translate -> echo -> TTS without real models/DB.
"""

import asyncio
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import numpy as np
import pytest

from app.ws.handlers import MeetingHandler
from app.ws.keypoint_frame import NUM_KEYPOINTS, pack_keypoint_frame


def _frame(t=6):
    rng = np.random.default_rng(0)
    kp = rng.uniform(0, 1, (t, NUM_KEYPOINTS, 2)).astype(np.float32)
    sc = rng.uniform(0.5, 1, (t, NUM_KEYPOINTS)).astype(np.float32)
    return pack_keypoint_frame(kp, sc, 640, 480)


def _signing_frame(t=6):
    """Frames guaranteed to pass the rest-pose filter (wrists above hip line).

    Sets wrist Y near 0 (top of frame) and hip/shoulder Y near 1 (bottom),
    with high confidence on all keypoints, so hands_at_rest always returns False.
    """
    rng = np.random.default_rng(42)
    kp = rng.uniform(0, 1, (t, NUM_KEYPOINTS, 2)).astype(np.float32)
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    # Indices: left_wrist=9, right_wrist=10, left_hip=11, right_hip=12,
    #          left_shoulder=5, right_shoulder=6
    kp[:, 9, 1] = 0.1   # left wrist Y = top
    kp[:, 10, 1] = 0.1  # right wrist Y = top
    kp[:, 11, 1] = 0.9  # left hip Y = bottom
    kp[:, 12, 1] = 0.9  # right hip Y = bottom
    return pack_keypoint_frame(kp, sc, 640, 480)


def _mock_manager_with_speaker():
    """A manager whose session has a connected speaker; async send methods."""
    speaker = MagicMock()
    speaker.user_id = uuid.uuid4()
    session = MagicMock()
    session.speaker = speaker
    mgr = MagicMock()
    mgr.get_session.return_value = session
    mgr.send_json_to_user = AsyncMock(return_value=True)
    mgr.send_bytes_to_user = AsyncMock(return_value=True)
    return mgr, speaker


def _collect_types(mgr):
    return [c.kwargs["data"]["type"] for c in mgr.send_json_to_user.call_args_list]


class TestKeypointFlush:
    def test_cap_flush_sends_pending_and_recognized_sign(self):
        """Cap flush emits instant pending '…' feedback then the recognized word."""
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        # Force a cap flush on a 10-frame batch using signing frames that pass
        # the rest-pose filter (wrists above hips).
        handler.sign_segment_buffer.max_frames = 8
        handler.sign_segment_buffer.min_frames = 5
        mgr, speaker = _mock_manager_with_speaker()
        save_mock = AsyncMock(return_value=True)

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", save_mock):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _signing_frame(10)))

        types = _collect_types(mgr)
        # Reader gets at least one sign_text message (pending + recognized).
        assert types.count("sign_text") >= 1
        # The first sign_text is the instant pending feedback (is_partial=True).
        first_sign_text = next(
            c for c in mgr.send_json_to_user.call_args_list
            if c.kwargs["data"]["type"] == "sign_text"
        )
        assert first_sign_text.kwargs["data"]["is_partial"] is True
        assert "…" in first_sign_text.kwargs["data"]["content"]
        # TTS is NOT triggered by a mid-sentence cap flush (only on segment end).
        assert "tts_start" not in types

    def test_no_flush_below_min_frames_is_silent(self):
        """Fewer buffered frames than min_frames → nothing emitted."""
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 1000
        # High rest_debounce_ms prevents rest-triggered flush; use signing frames
        # that pass the rest-pose filter so all 4 accumulate.
        handler.sign_segment_buffer.rest_debounce_ms = 10_000
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _signing_frame(4)))

        # Buffered (4 < default min_frames=8), not yet a sentence -> nothing emitted.
        assert mgr.send_json_to_user.await_count == 0
        assert len(handler.sign_segment_buffer) == 4

    def test_segment_end_cue_force_flushes(self):
        """handle_sign_segment_end flushes remaining frames, recognizes, and speaks."""
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 1000
        handler.sign_segment_buffer.rest_debounce_ms = 10_000
        # Send 10 signing frames — well above the default SIGN_TO_TEXT_MIN_FRAMES=8
        # so recognition gating passes.
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _signing_frame(10)))
            assert mgr.send_json_to_user.await_count == 0  # buffered only
            asyncio.run(handler.handle_sign_segment_end(reader_id))  # explicit cue

        assert "sign_text" in _collect_types(mgr)
        assert len(handler.sign_segment_buffer) == 0

    def test_bad_frame_is_dropped(self):
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        mgr, _ = _mock_manager_with_speaker()
        with patch("app.ws.handlers.manager", mgr):
            asyncio.run(handler.handle_keypoint_frames(reader_id, b"\x01\x01garbage"))
        assert mgr.send_json_to_user.await_count == 0
        assert len(handler.sign_segment_buffer) == 0


class TestEngineNotLoaded:
    def test_unloaded_engine_no_word_accumulated(self):
        """When the sign-to-text engine is not loaded, pending feedback fires but
        no word is accumulated — the sentence stays empty so TTS is never triggered."""
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 5
        handler.sign_segment_buffer.min_frames = 4
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch("app.ws.handlers.sign_to_text_engine") as eng, \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            eng.is_loaded = False
            asyncio.run(handler.handle_keypoint_frames(reader_id, _signing_frame(6)))

        types = _collect_types(mgr)
        # Pending feedback fires immediately on flush.
        assert "sign_text" in types
        pending = next(
            c.kwargs["data"] for c in mgr.send_json_to_user.call_args_list
            if c.kwargs["data"]["type"] == "sign_text"
        )
        assert pending["is_partial"] is True
        # No word was accumulated (engine not loaded), so no TTS is triggered.
        assert "tts_start" not in types
        assert handler._sign_words == []
