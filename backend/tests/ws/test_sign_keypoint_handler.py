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
    def test_cap_flush_translates_echoes_and_speaks(self):
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 5  # force a cap flush on a 6-frame batch
        mgr, speaker = _mock_manager_with_speaker()
        save_mock = AsyncMock(return_value=True)

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", save_mock):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _frame(6)))

        types = _collect_types(mgr)
        # Reader gets the recognized English echo...
        assert "sign_text" in types
        # ...and the speaker gets a TTS stream (mock yields >=1 wav chunk).
        assert "tts_start" in types and "tts_end" in types
        assert mgr.send_bytes_to_user.await_count >= 1
        # Persisted as a sign_translation.
        save_mock.assert_awaited()
        assert save_mock.await_args.kwargs["msg_type"].value == "sign_translation"

    def test_no_flush_below_threshold_is_silent(self):
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 1000
        handler.sign_segment_buffer.pause_ms = 10_000  # never pause-flush in-test
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _frame(4)))

        # Buffered, not yet a sentence -> nothing emitted.
        assert mgr.send_json_to_user.await_count == 0
        assert len(handler.sign_segment_buffer) == 4

    def test_segment_end_cue_force_flushes(self):
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 1000
        handler.sign_segment_buffer.pause_ms = 10_000
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            asyncio.run(handler.handle_keypoint_frames(reader_id, _frame(4)))
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
    def test_unloaded_engine_reports_error(self):
        reader_id = uuid.uuid4()
        handler = MeetingHandler(uuid.uuid4())
        handler.sign_segment_buffer.max_frames = 5
        mgr, _ = _mock_manager_with_speaker()

        with patch("app.ws.handlers.manager", mgr), \
             patch("app.ws.handlers.sign_to_text_engine") as eng, \
             patch.object(handler, "_save_message", AsyncMock(return_value=True)):
            eng.is_loaded = False
            asyncio.run(handler.handle_keypoint_frames(reader_id, _frame(6)))

        types = _collect_types(mgr)
        assert "error" in types
        assert "sign_text" not in types
