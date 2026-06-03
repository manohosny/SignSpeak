"""Per-reader keypoint accumulation + sentence segmentation (Direction B).

Uni-Sign is a *sentence-level* model (clip -> sentence). A live webcam produces a
continuous keypoint stream, so it must be chunked into sentence-like units before
each translation call. This is THE gap the released model does not cover.

Two flush triggers, defence-in-depth:
  1. Client cue (reliable): the Reader presses "end sentence" -> the handler calls
     force_flush(). This always works regardless of heuristic quality.
  2. Server heuristic (auto): a pause in signing (hand motion-energy stays below a
     threshold for `pause_ms`) ends a sentence. Plus a hard `max_frames` safety cap
     so a non-stop signer still gets periodic translations.

Frames arrive already batched inside one binary WebSocket frame; this buffer
accumulates across batches until a flush trigger fires.
"""

from __future__ import annotations

import numpy as np

NUM_KEYPOINTS = 133
# COCO-WholeBody indices used for rest-pose detection.
_LEFT_WRIST, _RIGHT_WRIST = 9, 10
_LEFT_SHOULDER, _RIGHT_SHOULDER = 5, 6
_LEFT_HIP, _RIGHT_HIP = 11, 12
_HAND_SLICE = slice(91, 133)  # left hand 91..111 + right hand 112..132
_HIP_VISIBLE_CONF = 0.3       # below this, hips are treated as out of frame


def hands_at_rest(
    kp: np.ndarray,
    sc: np.ndarray,
    *,
    drop_margin: float,
    hand_conf: float,
) -> bool:
    """True when both arms are down at the sides (a sign boundary).

    kp: (133, 2) keypoints normalized [0,1], y increasing downward.
    sc: (133,) per-keypoint confidence in [0,1]. Body-relative (no calibration):
      - hands dropped out of frame -> mean hand-keypoint confidence < hand_conf;
      - else both wrists below the hip line (or, if hips are out of frame,
        below the shoulders by drop_margin).
    """
    if float(np.mean(sc[_HAND_SLICE])) < hand_conf:
        return True
    wl_y = float(kp[_LEFT_WRIST, 1])
    wr_y = float(kp[_RIGHT_WRIST, 1])
    shoulder_y = float((kp[_LEFT_SHOULDER, 1] + kp[_RIGHT_SHOULDER, 1]) / 2.0)
    hips_conf = float((sc[_LEFT_HIP] + sc[_RIGHT_HIP]) / 2.0)
    if hips_conf >= _HIP_VISIBLE_CONF:
        line = float((kp[_LEFT_HIP, 1] + kp[_RIGHT_HIP, 1]) / 2.0)
    else:
        line = shoulder_y + drop_margin
    return wl_y > line and wr_y > line


class SignSegmentBuffer:
    """Accumulates (keypoints, scores) frames and decides sentence boundaries.

    Units: keypoints are (133,2) normalized [0,1]; scores (133,). Timestamps are
    server-side monotonic milliseconds supplied by the caller (keeps this class
    pure and unit-testable — no time.* calls inside).
    """

    def __init__(
        self,
        max_frames: int = 256,
        pause_ms: int = 700,
        motion_threshold: float = 0.01,
        motion_window: int = 6,
        min_frames: int = 16,
    ) -> None:
        self.max_frames = max_frames
        self.pause_ms = pause_ms
        self.motion_threshold = motion_threshold
        self.motion_window = motion_window
        self.min_frames = min_frames
        self._kps: list[np.ndarray] = []   # each (133, 2)
        self._scores: list[np.ndarray] = []  # each (133,)
        # Server-receive time (ms) of the most recent frame that showed motion
        # above threshold. Pause = now - last_active_ms.
        self._last_active_ms: float | None = None

    def __len__(self) -> int:
        return len(self._kps)

    def feed(self, keypoints: np.ndarray, scores: np.ndarray, now_ms: float) -> None:
        """Append a batch of frames. keypoints (T,133,2), scores (T,133)."""
        keypoints = np.asarray(keypoints, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32)
        if keypoints.ndim != 3 or keypoints.shape[1:] != (NUM_KEYPOINTS, 2):
            raise ValueError(f"bad keypoints shape {keypoints.shape}")
        if self._last_active_ms is None:
            self._last_active_ms = now_ms
        for i in range(keypoints.shape[0]):
            self._kps.append(keypoints[i])
            self._scores.append(scores[i])
        # If this batch carried motion, refresh the activity timestamp.
        if self.motion_energy(self.motion_window) >= self.motion_threshold:
            self._last_active_ms = now_ms

    def motion_energy(self, window: int) -> float:
        """Mean per-joint hand displacement over the last `window` frames.

        Higher = more active signing. Returns 0.0 when there is too little
        history to measure motion.
        """
        if len(self._kps) < 2:
            return 0.0
        recent = self._kps[-(window + 1):]
        diffs = [
            np.linalg.norm(recent[i][_HAND_SLICE] - recent[i - 1][_HAND_SLICE], axis=-1)
            for i in range(1, len(recent))
        ]
        if not diffs:
            return 0.0
        return float(np.mean(diffs))

    def should_flush(self, now_ms: float) -> bool:
        """Whether the accumulated frames form a complete sentence unit.

        Heuristic v1 (tunable — see SIGN_TO_TEXT_PAUSE_MS / _MOTION_THRESHOLD):
          - hard cap: at/over the model's frame budget, flush now;
          - pause: signing went quiet (no motion) for >= pause_ms.
        TODO(segmentation): replace with a learned boundary detector; the pause
        heuristic over/under-segments on hesitant or run-on signing.
        """
        if len(self._kps) == 0:
            return False
        if len(self._kps) >= self.max_frames:
            return True
        # Don't end a sentence on a pause until enough frames have built up —
        # avoids translating brief motion blips into hallucinated text.
        if len(self._kps) < self.min_frames:
            return False
        if self._last_active_ms is None:
            return False
        return (now_ms - self._last_active_ms) >= self.pause_ms

    def flush(self) -> tuple[np.ndarray, np.ndarray] | None:
        """Return accumulated (keypoints (T,133,2), scores (T,133)) and clear.

        Returns None if empty.
        """
        if not self._kps:
            return None
        keypoints = np.stack(self._kps, axis=0)
        scores = np.stack(self._scores, axis=0)
        self.clear()
        return keypoints, scores

    def clear(self) -> None:
        self._kps.clear()
        self._scores.clear()
        self._last_active_ms = None
