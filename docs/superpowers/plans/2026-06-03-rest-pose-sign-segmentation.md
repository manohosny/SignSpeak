# Rest-Pose Sign Segmentation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SignSegmentBuffer's motion-magnitude pause trigger with a body-relative rest-pose state machine (hands up = signing, hands dropped to sides = boundary) so each emitted clip is a clean isolated sign for WLASL ISLR, with instant on-screen feedback.

**Architecture:** A pure `hands_at_rest(frame)` classifier (COCO-WholeBody geometry) drives a REST↔SIGNING state machine in `SignSegmentBuffer`: only SIGNING frames accumulate; a sustained REST after a sign flushes a clean clip. Handler sends a "…" pending partial instantly on flush, then the recognized gloss when inference returns. Downstream (accumulate → stop → gloss→English → TTS) is unchanged.

**Tech Stack:** Python 3.10, numpy, pytest (asyncio_mode=auto), FastAPI WebSocket; React/TS frontend; CPU-only Docker deploy on GCP (iterate via `gcloud compute scp` + `docker compose ... build`).

**Spec:** `docs/superpowers/specs/2026-06-03-rest-pose-sign-segmentation-design.md`

---

## File Structure

- `backend/app/core/config.py` — add 3 rest params; `SIGN_TO_TEXT_MIN_FRAMES` default → 8.
- `backend/app/ws/sign_segment_buffer.py` — add `hands_at_rest()`; rewrite `SignSegmentBuffer` (`feed`/`should_flush`/`__init__`) to the rest-pose state machine; keep `motion_energy` (debug only).
- `backend/app/ws/handlers.py` — `_new_sign_segment_buffer()` passes new params; add `_send_pending_sign()` and call it on flush.
- `backend/tests/ws/test_sign_segment_buffer.py` — replace motion tests with rest-pose tests.
- `backend/scripts/e2e_sign_to_speech.py` — craft hands-up (signing) synthetic frames.
- `frontend/src/components/Meeting/SignCaptureView.tsx` — guidance copy ("drop hands to your sides between signs").

---

### Task 1: Config — rest-pose parameters

**Files:**
- Modify: `backend/app/core/config.py` (the `SIGN_TO_TEXT_*` block, ~line 118-122)
- Test: `backend/tests/core/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/core/test_config.py`:

```python
def test_rest_pose_segmentation_defaults():
    from app.core.config import settings
    assert settings.SIGN_TO_TEXT_REST_DROP_MARGIN == 0.15
    assert settings.SIGN_TO_TEXT_REST_HAND_CONF == 0.3
    assert settings.SIGN_TO_TEXT_REST_DEBOUNCE_MS == 250
    assert settings.SIGN_TO_TEXT_MIN_FRAMES == 8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/core/test_config.py::test_rest_pose_segmentation_defaults -v`
Expected: FAIL (AttributeError: SIGN_TO_TEXT_REST_DROP_MARGIN).

- [ ] **Step 3: Implement**

In `backend/app/core/config.py`, change the min-frames default and add the rest params. Replace:

```python
    SIGN_TO_TEXT_MIN_FRAMES: int = 16
```
with:
```python
    SIGN_TO_TEXT_MIN_FRAMES: int = 8        # min SIGNING frames for a real sign clip
    # ── Rest-pose segmentation (hands up = signing, hands to sides = boundary) ──
    SIGN_TO_TEXT_REST_DROP_MARGIN: float = 0.15  # wrist-below-shoulder margin when hips out of frame
    SIGN_TO_TEXT_REST_HAND_CONF: float = 0.3     # mean hand-kp confidence below which hands are "out of frame"
    SIGN_TO_TEXT_REST_DEBOUNCE_MS: int = 250     # sustained rest after a sign before flushing
```

(Leave the existing `SIGN_TO_TEXT_PAUSE_MS` / `SIGN_TO_TEXT_MOTION_THRESHOLD` fields in place — unused by the new flush path, harmless if set in `.env`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/core/test_config.py::test_rest_pose_segmentation_defaults -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/core/test_config.py
git commit -m "feat(config): rest-pose segmentation params"
```

---

### Task 2: `hands_at_rest()` classifier

**Files:**
- Modify: `backend/app/ws/sign_segment_buffer.py` (add helper + indices near top)
- Test: `backend/tests/ws/test_sign_segment_buffer.py`

- [ ] **Step 1: Write the failing test**

Replace the top of `backend/tests/ws/test_sign_segment_buffer.py` (imports + frame builders) with:

```python
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
    for i in range(t):       # add small motion so motion_energy works
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/ws/test_sign_segment_buffer.py::TestHandsAtRest -v`
Expected: FAIL (ImportError: cannot import name 'hands_at_rest').

- [ ] **Step 3: Implement the classifier**

In `backend/app/ws/sign_segment_buffer.py`, replace the index constants block (the `_HAND_SLICE` definition) with:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/ws/test_sign_segment_buffer.py::TestHandsAtRest -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ws/sign_segment_buffer.py backend/tests/ws/test_sign_segment_buffer.py
git commit -m "feat(segmentation): hands_at_rest pose classifier"
```

---

### Task 3: Rest-pose state machine in `SignSegmentBuffer`

**Files:**
- Modify: `backend/app/ws/sign_segment_buffer.py` (`__init__`, `feed`, `should_flush`)
- Test: `backend/tests/ws/test_sign_segment_buffer.py`

- [ ] **Step 1: Write the failing tests**

Replace the `TestAccumulation`, `TestFlushTriggers`, and `TestMotionEnergy` classes (everything below `TestHandsAtRest`) with:

```python
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


class TestMotionEnergy:
    def test_signing_has_motion(self):
        buf = SignSegmentBuffer()
        sig_kp, sig_sc = _signing_frames(8)
        buf.feed(sig_kp, sig_sc, now_ms=0)
        assert buf.motion_energy(6) > 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/ws/test_sign_segment_buffer.py -v`
Expected: FAIL (TypeError: unexpected kwarg `rest_debounce_ms`, and feed still accumulates rest frames).

- [ ] **Step 3: Implement the state machine**

In `backend/app/ws/sign_segment_buffer.py`, replace `__init__`, `feed`, and `should_flush` with:

```python
    def __init__(
        self,
        max_frames: int = 256,
        min_frames: int = 8,
        rest_debounce_ms: int = 250,
        rest_drop_margin: float = 0.15,
        rest_hand_conf: float = 0.3,
        motion_window: int = 6,
    ) -> None:
        self.max_frames = max_frames
        self.min_frames = min_frames
        self.rest_debounce_ms = rest_debounce_ms
        self.rest_drop_margin = rest_drop_margin
        self.rest_hand_conf = rest_hand_conf
        self.motion_window = motion_window
        self._kps: list[np.ndarray] = []     # each (133, 2) — SIGNING frames only
        self._scores: list[np.ndarray] = []  # each (133,)
        # now_ms of the most recent SIGNING frame; rest is measured from here.
        self._last_signing_ms: float | None = None

    def feed(self, keypoints: np.ndarray, scores: np.ndarray, now_ms: float) -> None:
        """Append a batch of frames. keypoints (T,133,2), scores (T,133).

        Only SIGNING frames (hands up) are accumulated; REST frames (hands
        dropped to the sides) are discarded so each clip stays rest-free.
        """
        keypoints = np.asarray(keypoints, dtype=np.float32)
        scores = np.asarray(scores, dtype=np.float32)
        if keypoints.ndim != 3 or keypoints.shape[1:] != (NUM_KEYPOINTS, 2):
            raise ValueError(f"bad keypoints shape {keypoints.shape}")
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

    def should_flush(self, now_ms: float) -> bool:
        """A clean single-sign clip is ready when the hands have dropped to rest.

        - hard cap: at/over the model's frame budget, flush now;
        - boundary: after >= min_frames signing frames, hands at rest (no new
          signing frame) for >= rest_debounce_ms.
        """
        if len(self._kps) == 0:
            return False
        if len(self._kps) >= self.max_frames:
            return True
        if len(self._kps) < self.min_frames:
            return False
        if self._last_signing_ms is None:
            return False
        return (now_ms - self._last_signing_ms) >= self.rest_debounce_ms
```

Then update `clear()` to reset the renamed field:

```python
    def clear(self) -> None:
        self._kps.clear()
        self._scores.clear()
        self._last_signing_ms = None
```

(Keep `motion_energy()` and `flush()` as they are — `motion_energy` stays for the handler's debug log.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/ws/test_sign_segment_buffer.py -v`
Expected: PASS (all classes).

- [ ] **Step 5: Commit**

```bash
git add backend/app/ws/sign_segment_buffer.py backend/tests/ws/test_sign_segment_buffer.py
git commit -m "feat(segmentation): rest-pose state machine in SignSegmentBuffer"
```

---

### Task 4: Wire config into the buffer factory

**Files:**
- Modify: `backend/app/ws/handlers.py` (`_new_sign_segment_buffer`, ~line 39-51)

- [ ] **Step 1: Update the factory**

Replace the `SignSegmentBuffer(...)` call in `_new_sign_segment_buffer()`:

```python
        return SignSegmentBuffer(
            max_frames=settings.SIGN_TO_TEXT_MAX_FRAMES,
            min_frames=settings.SIGN_TO_TEXT_MIN_FRAMES,
            rest_debounce_ms=settings.SIGN_TO_TEXT_REST_DEBOUNCE_MS,
            rest_drop_margin=settings.SIGN_TO_TEXT_REST_DROP_MARGIN,
            rest_hand_conf=settings.SIGN_TO_TEXT_REST_HAND_CONF,
        )
```

- [ ] **Step 2: Verify the app imports**

Run: `cd backend && uv run python -c "import app.ws.handlers"`
Expected: no error.

- [ ] **Step 3: Run the existing handler tests**

Run: `cd backend && uv run pytest tests/ws/test_sign_keypoint_handler.py -v`
Expected: PASS (if any reference removed buffer kwargs, fix them to the new names per Task 3 signature, then re-run to PASS).

- [ ] **Step 4: Commit**

```bash
git add backend/app/ws/handlers.py
git commit -m "feat(segmentation): build SignSegmentBuffer from rest-pose config"
```

---

### Task 5: Instant "…" pending feedback

**Files:**
- Modify: `backend/app/ws/handlers.py` (`handle_keypoint_frames` + new `_send_pending_sign`)

- [ ] **Step 1: Add the pending-feedback method**

Add this method to `MeetingHandler` (next to `_recognize_and_accumulate`):

```python
    async def _send_pending_sign(self, sender_id: uuid.UUID) -> None:
        """Instant feedback the moment a sign boundary is detected — shows the
        accumulated glosses plus a trailing '…' so the reader sees the sign was
        captured before the (CPU) recognition returns ~0.5s later."""
        pending = (" ".join(self._sign_words) + " …").strip()
        await manager.send_json_to_user(
            meeting_id=self.meeting_id,
            user_id=sender_id,
            data={
                "type": "sign_text",
                "content": pending,
                "sender_id": str(sender_id),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "is_partial": True,
            },
        )
```

- [ ] **Step 2: Call it on flush**

In `handle_keypoint_frames`, replace:

```python
        if flushed is None:
            return
        # Recognize this one sign and add it to the building sentence (no speech
        # yet — the full sentence is spoken when the reader ends it).
        await self._recognize_and_accumulate(sender_id, *flushed)
```
with:
```python
        if flushed is None:
            return
        # Instant "captured" feedback, then recognize + append (no speech yet —
        # the full sentence is spoken when the reader taps stop).
        await self._send_pending_sign(sender_id)
        await self._recognize_and_accumulate(sender_id, *flushed)
```

- [ ] **Step 3: Verify import + run ws tests**

Run: `cd backend && uv run python -c "import app.ws.handlers" && uv run pytest tests/ws/ -v`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add backend/app/ws/handlers.py
git commit -m "feat(ux): instant pending-sign feedback on segment flush"
```

---

### Task 6: Update the e2e smoke for hands-up frames

**Files:**
- Modify: `backend/scripts/e2e_sign_to_speech.py` (frame generation, ~line 49-52)

- [ ] **Step 1: Generate signing (hands-up) frames**

Replace the synthetic frame block (the `rng = ...; kp = ...; sc = ...` lines before `frame=pack_keypoint_frame(...)`) with:

```python
        rng = np.random.default_rng(0)
        T = 24
        kp = np.zeros((T, NUM_KEYPOINTS, 2), dtype=np.float32)
        kp[:, 5:7, 1] = 0.20       # shoulders
        kp[:, 11:13, 1] = 0.80     # hips
        kp[:, 9:11, 1] = 0.45      # wrists above the hip line -> SIGNING
        kp[:, 91:133, :] = 0.45 + rng.uniform(0, 0.05, (T, 42, 2)).astype(np.float32)
        sc = np.full((T, NUM_KEYPOINTS), 0.9, dtype=np.float32)
        frame = pack_keypoint_frame(kp, sc, 640, 480)
```

- [ ] **Step 2: Run the smoke against the deployed/local backend**

(See Task 8 for the deployed run.) The hands-up frames accumulate as one SIGNING clip; `sign_segment_end` force-flushes it → one recognized gloss → English + TTS.
Expected printed RESULT: `reader sign_text=True ... PASS`.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/e2e_sign_to_speech.py
git commit -m "test(e2e): hands-up signing frames for rest-pose segmentation"
```

---

### Task 7: Frontend guidance copy

**Files:**
- Modify: `frontend/src/components/Meeting/SignCaptureView.tsx` (status strings, ~line 62-64)

- [ ] **Step 1: Update the status copy**

Replace:

```tsx
            : isCapturing
              ? "Signing — tap to stop"
              : "Tap to start signing"
```
with:
```tsx
            : isCapturing
              ? "Sign, then drop your hands to your sides between signs — tap to stop"
              : "Tap to start signing"
```

- [ ] **Step 2: Typecheck the frontend**

Run: `cd frontend && bunx tsc -p tsconfig.build.json --noEmit`
Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/Meeting/SignCaptureView.tsx
git commit -m "feat(ux): reader guidance for hands-to-sides segmentation"
```

---

### Task 8: Deploy + manual verification

**Files:** none (deploy of committed changes)

- [ ] **Step 1: Copy changed files to the VM**

```bash
PROJECT=gen-lang-client-0460855531; Z="--zone=us-central1-a --project=$PROJECT"
for f in backend/app/core/config.py backend/app/ws/sign_segment_buffer.py \
         backend/app/ws/handlers.py backend/scripts/e2e_sign_to_speech.py \
         frontend/src/components/Meeting/SignCaptureView.tsx; do
  gcloud compute scp "$f" "signspeak:~/SignSpeak/$f" --zone=us-central1-a --project=$PROJECT
done
```

- [ ] **Step 2: Rebuild backend + frontend, recreate, wait ready**

```bash
gcloud compute ssh signspeak --zone=us-central1-a --project=$PROJECT --command='
cd ~/SignSpeak
DC="sudo docker compose -f compose.yml -f deploy/gcp/compose.cpu.yml"
$DC build backend frontend && $DC up -d
for i in $(seq 1 50); do c=$($DC exec -T backend curl -s -o /dev/null -w "%{http_code}" -H "Host: api.34.10.142.210.sslip.io" http://localhost:8000/api/v1/utils/healthz/ready 2>/dev/null||echo 000); [ "$c" = "200" ] && { echo READY; break; }; sleep 6; done'
```
Expected: `READY`.

- [ ] **Step 3: Run the pipeline smoke on the VM**

```bash
gcloud compute ssh signspeak --zone=us-central1-a --project=$PROJECT --command='
cd ~/SignSpeak
sudo docker compose -f compose.yml -f deploy/gcp/compose.cpu.yml exec -T backend python scripts/e2e_sign_to_speech.py 2>&1 | tail -8'
```
Expected: `PASS` (reader sign_text True, TTS start/end).

- [ ] **Step 4: Manual sign test (human)**

Hard-refresh `https://dashboard.34.10.142.210.sslip.io`, start capture, sign one sign, **drop hands to sides ~0.5s**, repeat 3-4 times, then tap stop. Expected: each gloss appears (with a brief "…" then the word) one-per-sign; stop speaks the English sentence.

- [ ] **Step 5: (If needed) tune via .env, no rebuild**

If boundaries are missed/over-eager, adjust on the VM and `docker compose up -d`:
```bash
# in ~/SignSpeak/.env: SIGN_TO_TEXT_REST_DEBOUNCE_MS, SIGN_TO_TEXT_REST_DROP_MARGIN,
# SIGN_TO_TEXT_REST_HAND_CONF, SIGN_TO_TEXT_MIN_FRAMES
```

---

## Self-Review

**Spec coverage:** rest-pose detector (Task 2) ✓; state machine accumulating only SIGNING frames (Task 3) ✓; config params (Task 1) ✓; handler wiring (Task 4) ✓; instant "…" feedback (Task 5) ✓; frontend copy (Task 6/7) ✓; tests (Tasks 1-3) + e2e (Task 6) ✓; deploy/verify (Task 8) ✓. Downstream (accumulate → stop → gloss→English → TTS) deliberately untouched.

**Placeholder scan:** none — every code step shows full code; commands have expected output.

**Type consistency:** `hands_at_rest(kp, sc, *, drop_margin, hand_conf)` used identically in Tasks 2/3; buffer kwargs (`max_frames, min_frames, rest_debounce_ms, rest_drop_margin, rest_hand_conf, motion_window`) match between Task 3 (`__init__`) and Task 4 (factory); `_send_pending_sign` defined and called in Task 5; `_sign_words`, `_recognize_and_accumulate`, `manager.send_json_to_user` already exist in `handlers.py`.
