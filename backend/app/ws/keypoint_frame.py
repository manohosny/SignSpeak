"""Binary wire format for RTMW keypoint frames (Direction B, Reader -> server).

The Reader's browser extracts COCO-WholeBody-133 keypoints (x/W, y/H normalized
+ score) and batches one segmented chunk into a single binary WebSocket frame.
Binary (not JSON) because T x 133 x 3 floats is ~10x smaller and avoids GC churn.

Layout (little-endian, matches JS DataView / Float32Array on x86 + ARM):

    offset 0      uint8    frame_type   (0x01 = KEYPOINT_FRAME)
    offset 1      uint8    version      (0x01)
    offset 2..3   uint16   frame_count  T
    offset 4..5   uint16   width        original capture W (audit)
    offset 6..7   uint16   height       original capture H (audit)
    offset 8..    float32  payload      T x 133 x 3  [x_norm, y_norm, score]

The first byte is a frame-type tag so the same binary channel can carry the
speaker's PCM16 audio (untagged) and, in future, other reader frame types — the
router distinguishes by role first, then tag.
"""

import struct
from typing import Any

import numpy as np
import numpy.typing as npt

KEYPOINT_FRAME_TYPE = 0x01
FRAME_VERSION = 0x01
NUM_KEYPOINTS = 133
_CHANNELS = 3  # x, y, score
HEADER_SIZE = 8
_HEADER = struct.Struct("<BBHHH")  # frame_type, version, T, W, H
_BYTES_PER_FRAME = NUM_KEYPOINTS * _CHANNELS * 4  # float32

# Guardrail so a malformed/huge header can't trigger a giant allocation. The
# model caps at ~256 frames; allow generous headroom for client batching.
MAX_FRAMES = 1024


class KeypointFrameError(ValueError):
    """Raised when a binary keypoint frame is malformed."""


def is_keypoint_frame(payload: bytes) -> bool:
    """Cheap tag check used by the router before full parsing."""
    return len(payload) >= 1 and payload[0] == KEYPOINT_FRAME_TYPE


def parse_keypoint_frame(payload: bytes) -> tuple[npt.NDArray[Any], npt.NDArray[Any], tuple[int, int]]:
    """Decode a binary keypoint frame.

    Returns (keypoints (T,133,2) float32, scores (T,133) float32, (W, H)).
    Raises KeypointFrameError on any inconsistency.
    """
    if len(payload) < HEADER_SIZE:
        raise KeypointFrameError(f"frame too short: {len(payload)} < {HEADER_SIZE}")

    frame_type, version, t, w, h = _HEADER.unpack_from(payload, 0)
    if frame_type != KEYPOINT_FRAME_TYPE:
        raise KeypointFrameError(f"bad frame_type {frame_type:#x}")
    if version != FRAME_VERSION:
        raise KeypointFrameError(f"unsupported version {version}")
    if t == 0:
        raise KeypointFrameError("empty frame (T=0)")
    if t > MAX_FRAMES:
        raise KeypointFrameError(f"frame_count {t} exceeds MAX_FRAMES {MAX_FRAMES}")

    expected = HEADER_SIZE + t * _BYTES_PER_FRAME
    if len(payload) != expected:
        raise KeypointFrameError(
            f"payload length {len(payload)} != expected {expected} for T={t}"
        )

    flat = np.frombuffer(payload, dtype="<f4", count=t * NUM_KEYPOINTS * _CHANNELS,
                         offset=HEADER_SIZE)
    arr = flat.reshape(t, NUM_KEYPOINTS, _CHANNELS)
    keypoints = np.ascontiguousarray(arr[:, :, :2], dtype=np.float32)
    scores = np.ascontiguousarray(arr[:, :, 2], dtype=np.float32)
    return keypoints, scores, (w, h)


def pack_keypoint_frame(
    keypoints: npt.NDArray[Any], scores: npt.NDArray[Any], width: int, height: int
) -> bytes:
    """Encode keypoints/scores into the binary layout (mirrors the JS client).

    keypoints: (T,133,2) float, scores: (T,133) float. Used by tests and as the
    reference for the browser packer.
    """
    keypoints = np.asarray(keypoints, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)
    t = keypoints.shape[0]
    if keypoints.shape != (t, NUM_KEYPOINTS, 2):
        raise KeypointFrameError(f"bad keypoints shape {keypoints.shape}")
    if scores.shape != (t, NUM_KEYPOINTS):
        raise KeypointFrameError(f"bad scores shape {scores.shape}")

    arr = np.concatenate([keypoints, scores[:, :, None]], axis=-1).astype("<f4")
    packed: bytes = (
        _HEADER.pack(KEYPOINT_FRAME_TYPE, FRAME_VERSION, t, width, height)
        + arr.tobytes()
    )
    return packed
