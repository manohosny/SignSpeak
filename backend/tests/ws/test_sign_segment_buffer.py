"""Tests for SignSegmentBuffer — sentence segmentation triggers + accumulation."""

import numpy as np

from app.ws.sign_segment_buffer import NUM_KEYPOINTS, SignSegmentBuffer


def _static_frames(t, value=0.5):
    """T frames with no motion (constant keypoints)."""
    kp = np.full((t, NUM_KEYPOINTS, 2), value, dtype=np.float32)
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    return kp, sc


def _moving_frames(t, step=0.05):
    """T frames where the hands drift each frame (clear motion)."""
    kp = np.zeros((t, NUM_KEYPOINTS, 2), dtype=np.float32)
    for i in range(t):
        kp[i, 91:133, :] = 0.3 + i * step  # hands move
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    return kp, sc


class TestAccumulation:
    def test_feed_accumulates(self):
        buf = SignSegmentBuffer()
        kp, sc = _moving_frames(5)
        buf.feed(kp, sc, now_ms=0)
        assert len(buf) == 5
        kp2, sc2 = _moving_frames(3)
        buf.feed(kp2, sc2, now_ms=100)
        assert len(buf) == 8

    def test_flush_returns_and_clears(self):
        buf = SignSegmentBuffer()
        kp, sc = _moving_frames(7)
        buf.feed(kp, sc, now_ms=0)
        out = buf.flush()
        assert out is not None
        kps, scores = out
        assert kps.shape == (7, NUM_KEYPOINTS, 2)
        assert scores.shape == (7, NUM_KEYPOINTS)
        assert len(buf) == 0

    def test_flush_empty_returns_none(self):
        assert SignSegmentBuffer().flush() is None


class TestFlushTriggers:
    def test_max_frames_cap_forces_flush(self):
        buf = SignSegmentBuffer(max_frames=10, pause_ms=100_000)
        kp, sc = _moving_frames(10)
        buf.feed(kp, sc, now_ms=0)
        assert buf.should_flush(now_ms=1)  # cap hit even though "active"

    def test_pause_triggers_flush(self):
        buf = SignSegmentBuffer(max_frames=1000, pause_ms=700, motion_threshold=0.01)
        kp, sc = _moving_frames(6)
        buf.feed(kp, sc, now_ms=0)            # active at t=0
        # No further motion; 800ms later the pause window has elapsed.
        assert not buf.should_flush(now_ms=500)
        assert buf.should_flush(now_ms=800)

    def test_active_signing_does_not_flush(self):
        buf = SignSegmentBuffer(max_frames=1000, pause_ms=700, motion_threshold=0.01)
        # Keep feeding moving frames with advancing timestamps -> stays active.
        for k in range(5):
            kp, sc = _moving_frames(4)
            buf.feed(kp, sc, now_ms=k * 200)
        assert not buf.should_flush(now_ms=5 * 200)

    def test_empty_never_flushes(self):
        buf = SignSegmentBuffer()
        assert not buf.should_flush(now_ms=10_000)


class TestMotionEnergy:
    def test_static_low_energy(self):
        buf = SignSegmentBuffer()
        kp, sc = _static_frames(8)
        buf.feed(kp, sc, now_ms=0)
        assert buf.motion_energy(6) < 1e-6

    def test_moving_high_energy(self):
        buf = SignSegmentBuffer()
        kp, sc = _moving_frames(8, step=0.05)
        buf.feed(kp, sc, now_ms=0)
        assert buf.motion_energy(6) > 0.01
