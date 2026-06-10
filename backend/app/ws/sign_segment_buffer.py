"""Per-reader keypoint accumulation + rest-pose sign segmentation (Direction B).

WLASL ISLR recognizes one *clean isolated sign* per clip. A live webcam produces
a continuous keypoint stream, so it must be split into single-sign clips. We do
this with a rest-pose state machine: the reader signs with hands up, then drops
their arms to the sides between signs. "Hands up" = signing; "hands at sides /
out of frame" = a sign boundary (see ``hands_at_rest``). Only SIGNING frames are
accumulated, so each emitted clip is rest-free — what ISLR recognizes well.

Flush triggers:
  1. Pause (auto): after >= ``min_frames`` of real signing motion, the hands go
     still for >= ``pause_ms`` (hands kept UP, in frame) -> flush. This is the
     natural per-sign boundary for seated/real-life use, where dropping hands to
     the sides would take them out of the camera frame.
  2. Rest (auto): hands drop out of frame / to rest for >= ``rest_debounce_ms``
     after a sign of >= ``min_frames`` frames -> flush.
  3. Safety cap: ``max_frames`` force-flushes a runaway (never-pausing) clip.
  4. Client cue: the reader taps stop -> the handler flushes + finalizes (speak).

Frames arrive batched inside one binary WebSocket frame; this buffer classifies
each frame and accumulates the signing ones across batches until a flush fires.
The class is pure/unit-testable — the caller supplies monotonic ms timestamps.
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
        min_frames: int = 8,
        rest_debounce_ms: int = 250,
        rest_drop_margin: float = 0.15,
        rest_hand_conf: float = 0.3,
        pause_ms: int = 350,
        motion_threshold: float = 0.04,
        motion_window: int = 6,  # frames sampled by motion_energy()
    ) -> None:
        self.max_frames = max_frames
        self.min_frames = min_frames
        self.rest_debounce_ms = rest_debounce_ms
        self.rest_drop_margin = rest_drop_margin
        self.rest_hand_conf = rest_hand_conf
        self.pause_ms = pause_ms
        self.motion_threshold = motion_threshold
        self.motion_window = motion_window
        self._kps: list[np.ndarray] = []     # each (133, 2) — SIGNING frames only
        self._scores: list[np.ndarray] = []  # each (133,)
        # now_ms of the most recent SIGNING frame; rest is measured from here.
        self._last_signing_ms: float | None = None
        # now_ms of the most recent ACTIVE-motion frame, and whether this clip
        # has seen real signing motion yet. A still pause ends a sign only after
        # genuine motion, so a motionless hold never flushes an empty "sign".
        self._last_motion_ms: float | None = None
        self._saw_motion: bool = False

    def __len__(self) -> int:
        return len(self._kps)

    def feed(self, keypoints: np.ndarray, scores: np.ndarray, now_ms: float) -> None:
        """Append a batch of frames. keypoints (T,133,2), scores (T,133).

        Only SIGNING frames (hands up) are accumulated; REST frames (hands
        dropped to the sides) are discarded so each clip stays rest-free.
        Also tracks hand motion so a still pause (hands kept up, in frame) can
        end a sign without requiring the hands to leave the frame.
        """
        keypoints = np.asarray(keypoints, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32)
        if keypoints.ndim != 3 or keypoints.shape[1:] != (NUM_KEYPOINTS, 2):
            raise ValueError(f"bad keypoints shape {keypoints.shape}")
        appended = False
        for i in range(keypoints.shape[0]):
            if hands_at_rest(
                keypoints[i],
                scores[i],
                drop_margin=self.rest_drop_margin,
                hand_conf=self.rest_hand_conf,
            ):
                continue  # boundary frame — don't pollute the clip
            self._kps.append(keypoints[i])
            self._scores.append(scores[i])
            self._last_signing_ms = now_ms
            appended = True
        # After accumulating this batch, refresh the active-motion timestamp. A
        # quiet stretch (no high-motion frame for pause_ms) marks a sign boundary.
        if appended and self.motion_energy(self.motion_window) >= self.motion_threshold:
            self._saw_motion = True
            self._last_motion_ms = now_ms

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
        """A clean single-sign clip is ready when the signing has paused.

        - hard cap: at/over the model's frame budget, flush now;
        - rest boundary: after >= min_frames signing frames, hands at rest
          (no new signing frame, e.g. dropped out of frame) for >= rest_debounce_ms;
        - pause boundary: after real signing motion, the hands go still
          (no active-motion frame) for >= pause_ms while staying in frame.
        """
        if len(self._kps) == 0:
            return False
        if len(self._kps) >= self.max_frames:
            return True
        if len(self._kps) < self.min_frames:
            return False
        if (
            self._last_signing_ms is not None
            and (now_ms - self._last_signing_ms) >= self.rest_debounce_ms
        ):
            return True
        return (
            self._saw_motion
            and self._last_motion_ms is not None
            and (now_ms - self._last_motion_ms) >= self.pause_ms
        )

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
        self._last_signing_ms = None
        self._last_motion_ms = None
        self._saw_motion = False
