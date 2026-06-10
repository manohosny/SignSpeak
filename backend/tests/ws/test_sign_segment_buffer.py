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
    def test_feed_accumulates_only_signing_frames(self):
        buf = SignSegmentBuffer()
        sig_kp, sig_sc = _signing_frames(5)
        buf.feed(sig_kp, sig_sc, now_ms=0)
        assert len(buf) == 5
        rest_kp, rest_sc = _rest_frames(4)
        buf.feed(rest_kp, rest_sc, now_ms=100)  # rest frames discarded
        assert len(buf) == 5

    def test_flush_returns_clip_and_clears(self):
        buf = SignSegmentBuffer()
        sig_kp, sig_sc = _signing_frames(7)
        buf.feed(sig_kp, sig_sc, now_ms=0)
        out = buf.flush()
        assert out is not None
        kps, scores = out
        assert kps.shape == (7, NUM_KEYPOINTS, 2)
        assert scores.shape == (7, NUM_KEYPOINTS)
        assert len(buf) == 0

    def test_flush_empty_returns_none(self):
        assert SignSegmentBuffer().flush() is None


class TestFlushTriggers:
    def test_rest_after_sign_triggers_flush(self):
        buf = SignSegmentBuffer(min_frames=4, rest_debounce_ms=250)
        sig_kp, sig_sc = _signing_frames(6)
        buf.feed(sig_kp, sig_sc, now_ms=1000)   # last signing frame at t=1000
        assert not buf.should_flush(now_ms=1100)  # 100ms rest < debounce
        assert buf.should_flush(now_ms=1300)       # 300ms rest >= debounce

    def test_too_short_clip_does_not_flush(self):
        buf = SignSegmentBuffer(min_frames=8, rest_debounce_ms=250)
        sig_kp, sig_sc = _signing_frames(4)        # below min_frames
        buf.feed(sig_kp, sig_sc, now_ms=0)
        assert not buf.should_flush(now_ms=10_000)

    def test_max_frames_cap_forces_flush(self):
        buf = SignSegmentBuffer(max_frames=10, rest_debounce_ms=100_000)
        sig_kp, sig_sc = _signing_frames(10)
        buf.feed(sig_kp, sig_sc, now_ms=0)
        assert buf.should_flush(now_ms=1)

    def test_continuous_signing_does_not_flush(self):
        buf = SignSegmentBuffer(min_frames=4, rest_debounce_ms=250)
        for k in range(5):
            sig_kp, sig_sc = _signing_frames(4)
            buf.feed(sig_kp, sig_sc, now_ms=k * 100)  # last signing keeps advancing
        assert not buf.should_flush(now_ms=5 * 100)

    def test_empty_never_flushes(self):
        assert not SignSegmentBuffer().should_flush(now_ms=10_000)

    def test_pause_after_motion_triggers_flush(self):
        # Hands stay UP (never drop to rest) but go still after real signing
        # motion -> the pause ends the sign without the hands leaving the frame.
        buf = SignSegmentBuffer(
            min_frames=4, rest_debounce_ms=100_000,
            pause_ms=350, motion_threshold=0.005,
        )
        sig_kp, sig_sc = _signing_frames(6)         # energy ~0.007 > 0.005
        buf.feed(sig_kp, sig_sc, now_ms=1000)        # last active motion at t=1000
        assert buf._saw_motion                       # real motion registered
        assert not buf.should_flush(now_ms=1200)     # 200ms still < pause_ms
        assert buf.should_flush(now_ms=1400)         # 400ms still >= pause_ms

    def test_motionless_hold_never_flushes(self):
        # A hold that never produced real signing motion must not emit an empty
        # "sign" on the pause path (guards against flushing a motionless clip).
        buf = SignSegmentBuffer(
            min_frames=4, rest_debounce_ms=100_000,
            pause_ms=350, motion_threshold=0.05,
        )
        sig_kp, sig_sc = _signing_frames(8)          # energy ~0.007 < 0.05
        buf.feed(sig_kp, sig_sc, now_ms=1000)
        assert not buf._saw_motion
        assert not buf.should_flush(now_ms=10_000)

    def test_flush_rearms_pause_state(self):
        # After a flush, a fresh motionless stretch must not immediately re-flush.
        buf = SignSegmentBuffer(
            min_frames=4, rest_debounce_ms=100_000,
            pause_ms=350, motion_threshold=0.005,
        )
        buf.feed(*_signing_frames(6), now_ms=1000)
        assert buf.should_flush(now_ms=1400)
        buf.flush()
        assert not buf._saw_motion                   # motion state re-armed
        assert not buf.should_flush(now_ms=5000)


class TestMotionEnergy:
    def test_signing_has_motion(self):
        buf = SignSegmentBuffer()
        sig_kp, sig_sc = _signing_frames(8)
        buf.feed(sig_kp, sig_sc, now_ms=0)
        assert buf.motion_energy(6) > 0.0
