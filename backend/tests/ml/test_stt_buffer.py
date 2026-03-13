"""Tests for StreamingSTTBuffer — both fixed and utterance modes."""

import numpy as np
import pytest

from app.ml.stt import StreamingSTTBuffer


def _sine_wave(duration: float, freq: float = 440.0, sr: int = 16000) -> np.ndarray:
    """Generate a sine wave (loud — clearly above silence threshold)."""
    t = np.linspace(0, duration, int(sr * duration), dtype=np.float32)
    return 0.5 * np.sin(2 * np.pi * freq * t)


def _silence(duration: float, sr: int = 16000) -> np.ndarray:
    """Generate silence."""
    return np.zeros(int(sr * duration), dtype=np.float32)


# ── Fixed Mode (regression tests) ──


class TestFixedMode:
    def test_ready_after_chunk_duration(self):
        buf = StreamingSTTBuffer(mode="fixed", chunk_duration=2.0)
        buf.feed(_sine_wave(1.5))
        assert not buf.ready
        buf.feed(_sine_wave(0.6))
        assert buf.ready

    def test_get_chunk_returns_audio(self):
        buf = StreamingSTTBuffer(mode="fixed", chunk_duration=1.0)
        buf.feed(_sine_wave(1.5))
        chunk = buf.get_chunk()
        assert chunk is not None
        assert isinstance(chunk, np.ndarray)
        assert len(chunk) >= 16000  # 1s of audio

    def test_get_chunk_returns_none_for_silence(self):
        buf = StreamingSTTBuffer(mode="fixed", chunk_duration=1.0)
        buf.feed(_silence(1.5))
        chunk = buf.get_chunk()
        assert chunk is None

    def test_flush_returns_remaining(self):
        buf = StreamingSTTBuffer(mode="fixed", chunk_duration=2.0)
        buf.feed(_sine_wave(0.5))
        assert not buf.ready
        result = buf.flush()
        assert result is not None
        assert isinstance(result, np.ndarray)


# ── Utterance Mode ──


class TestUtteranceMode:
    def test_ready_false_below_max_duration(self):
        buf = StreamingSTTBuffer(mode="utterance", max_utterance_duration=10.0)
        buf.feed(_sine_wave(3.0))
        assert not buf.ready

    def test_ready_true_at_max_duration(self):
        """Safety cap: buffer exceeds max_utterance_duration."""
        buf = StreamingSTTBuffer(mode="utterance", max_utterance_duration=2.0)
        buf.feed(_sine_wave(2.5))
        assert buf.ready

    def test_flush_utterance_returns_audio_and_id(self):
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(1.0))
        result = buf.flush_utterance()
        assert result is not None
        audio, uid = result
        assert isinstance(audio, np.ndarray)
        assert len(uid) > 0

    def test_flush_utterance_returns_none_for_short_buffer(self):
        """Edge Case #2: buffer < 100ms returns None."""
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(0.05))  # 50ms — below MIN_UTTERANCE_SAMPLES
        result = buf.flush_utterance()
        assert result is None

    def test_flush_utterance_idempotent(self):
        """Edge Case #2: consecutive calls on empty buffer return None."""
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(0.5))
        result1 = buf.flush_utterance()
        assert result1 is not None
        result2 = buf.flush_utterance()
        assert result2 is None
        result3 = buf.flush_utterance()
        assert result3 is None

    def test_utterance_id_rotates_after_safety_cap(self):
        """Edge Case #1: utterance_id changes after safety-cap flush."""
        buf = StreamingSTTBuffer(mode="utterance", max_utterance_duration=1.0)
        buf.feed(_sine_wave(1.5))
        assert buf.ready

        result = buf.get_chunk()
        assert result is not None
        _, uid_a = result

        # Feed more audio — should get a new utterance_id
        buf.feed(_sine_wave(0.5))
        assert buf.utterance_id is not None
        assert buf.utterance_id != uid_a

    def test_utterance_id_rotates_after_flush(self):
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(1.0))
        result = buf.flush_utterance()
        assert result is not None
        _, uid_a = result

        buf.feed(_sine_wave(1.0))
        assert buf.utterance_id != uid_a

    def test_has_partial(self):
        buf = StreamingSTTBuffer(
            mode="utterance", partial_threshold=1.0
        )
        buf.feed(_sine_wave(0.5))
        assert not buf.has_partial
        buf.feed(_sine_wave(0.6))
        assert buf.has_partial

    def test_has_partial_false_in_fixed_mode(self):
        buf = StreamingSTTBuffer(mode="fixed")
        buf.feed(_sine_wave(5.0))
        assert not buf.has_partial

    def test_peek_utterance_does_not_consume(self):
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(1.0))
        peek1 = buf.peek_utterance()
        assert peek1 is not None
        peek2 = buf.peek_utterance()
        assert peek2 is not None
        # Buffer still has audio
        assert buf.duration > 0.9

    def test_flush_returns_tuple_in_utterance_mode(self):
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(0.5))
        result = buf.flush()
        assert result is not None
        assert isinstance(result, tuple)
        audio, uid = result
        assert isinstance(audio, np.ndarray)

    def test_clear_resets_everything(self):
        buf = StreamingSTTBuffer(mode="utterance")
        buf.feed(_sine_wave(1.0))
        assert buf.utterance_id is not None
        buf.clear()
        assert buf.duration == 0.0
        assert buf.utterance_id is None
