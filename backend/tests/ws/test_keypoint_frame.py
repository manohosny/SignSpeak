"""Round-trip + validation tests for the binary keypoint-frame codec."""

import numpy as np
import pytest

from app.ws.keypoint_frame import (
    HEADER_SIZE,
    KEYPOINT_FRAME_TYPE,
    KeypointFrameError,
    MAX_FRAMES,
    NUM_KEYPOINTS,
    is_keypoint_frame,
    pack_keypoint_frame,
    parse_keypoint_frame,
)


def _clip(t=10):
    rng = np.random.default_rng(0)
    kp = rng.uniform(0, 1, (t, NUM_KEYPOINTS, 2)).astype(np.float32)
    sc = rng.uniform(0, 1, (t, NUM_KEYPOINTS)).astype(np.float32)
    return kp, sc


class TestRoundTrip:
    def test_pack_parse_roundtrip(self):
        kp, sc = _clip(12)
        payload = pack_keypoint_frame(kp, sc, 640, 480)
        kp2, sc2, (w, h) = parse_keypoint_frame(payload)
        assert (w, h) == (640, 480)
        np.testing.assert_allclose(kp, kp2, rtol=0, atol=1e-6)
        np.testing.assert_allclose(sc, sc2, rtol=0, atol=1e-6)

    def test_payload_length(self):
        kp, sc = _clip(5)
        payload = pack_keypoint_frame(kp, sc, 100, 100)
        assert len(payload) == HEADER_SIZE + 5 * NUM_KEYPOINTS * 3 * 4

    def test_tag_first_byte(self):
        kp, sc = _clip(1)
        payload = pack_keypoint_frame(kp, sc, 10, 10)
        assert payload[0] == KEYPOINT_FRAME_TYPE
        assert is_keypoint_frame(payload)
        assert not is_keypoint_frame(b"\x00rawaudio")


class TestValidation:
    def test_too_short(self):
        with pytest.raises(KeypointFrameError, match="too short"):
            parse_keypoint_frame(b"\x01\x01")

    def test_bad_type(self):
        with pytest.raises(KeypointFrameError, match="frame_type"):
            parse_keypoint_frame(b"\x09\x01" + b"\x00" * 6)

    def test_truncated_payload(self):
        kp, sc = _clip(4)
        payload = pack_keypoint_frame(kp, sc, 1, 1)
        with pytest.raises(KeypointFrameError, match="length"):
            parse_keypoint_frame(payload[:-12])

    def test_empty_frame_rejected(self):
        import struct
        bad = struct.pack("<BBHHH", KEYPOINT_FRAME_TYPE, 1, 0, 10, 10)
        with pytest.raises(KeypointFrameError, match="empty"):
            parse_keypoint_frame(bad)

    def test_exceeds_max_frames(self):
        import struct
        bad = struct.pack("<BBHHH", KEYPOINT_FRAME_TYPE, 1, MAX_FRAMES + 1, 10, 10)
        with pytest.raises(KeypointFrameError, match="MAX_FRAMES"):
            parse_keypoint_frame(bad)
