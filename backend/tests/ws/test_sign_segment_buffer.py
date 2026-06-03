"""Tests for SignSegmentBuffer — rest-pose segmentation + accumulation."""

import numpy as np

from app.ws.sign_segment_buffer import (
    NUM_KEYPOINTS,
    SignSegmentBuffer,
    hands_at_rest,
)

REST = dict(drop_margin=0.15, hand_conf=0.3)


def _signing_frames(t):
    """T frames with hands UP (wrists between shoulders and hips) = signing."""
    kp = np.zeros((t, NUM_KEYPOINTS, 2), dtype=np.float32)
    kp[:, 5:7, 1] = 0.20    # shoulders near top
    kp[:, 11:13, 1] = 0.80  # hips low
    kp[:, 9:11, 1] = 0.45   # wrists above the hip line -> signing
    kp[:, 91:133, :] = 0.45  # hands present, in frame
    for i in range(t):       # small motion so motion_energy works
        kp[i, 91:133, :] += i * 0.005
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    return kp, sc


def _rest_frames(t):
    """T frames with hands DOWN (wrists below hips) = rest/boundary."""
    kp = np.zeros((t, NUM_KEYPOINTS, 2), dtype=np.float32)
    kp[:, 5:7, 1] = 0.20
    kp[:, 11:13, 1] = 0.70
    kp[:, 9:11, 1] = 0.95   # wrists below the hip line -> rest
    kp[:, 91:133, :] = 0.95
    sc = np.full((t, NUM_KEYPOINTS), 0.9, dtype=np.float32)
    return kp, sc


class TestHandsAtRest:
    def test_hands_up_is_signing(self):
        kp, sc = _signing_frames(1)
        assert hands_at_rest(kp[0], sc[0], **REST) is False

    def test_hands_below_hips_is_rest(self):
        kp, sc = _rest_frames(1)
        assert hands_at_rest(kp[0], sc[0], **REST) is True

    def test_hands_out_of_frame_is_rest(self):
        kp, sc = _signing_frames(1)
        sc[0, 91:133] = 0.05  # hands lost confidence (dropped out of frame)
        assert hands_at_rest(kp[0], sc[0], **REST) is True

    def test_hips_out_of_frame_uses_shoulder_margin(self):
        kp, sc = _signing_frames(1)
        sc[0, 11:13] = 0.05         # hips not visible
        kp[0, 9:11, 1] = 0.90       # wrists well below shoulders (0.20 + 0.15)
        assert hands_at_rest(kp[0], sc[0], **REST) is True


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
