# Rest-Pose Sign Segmentation (Direction B) — Design

**Date:** 2026-06-03
**Status:** Approved (brainstorming) → ready for implementation plan

## Context & Problem

Direction B (sign → speech) recognizes isolated signs with the WLASL ISLR model
(`wlasl_pose_only_islr.pth`): one clean isolated-sign clip → one gloss word →
accumulated → mBART gloss→English → TTS. Recognition is **accurate on clean,
isolated clips** (verified: signing "hello" → "Hello!").

The failure is **segmentation**: splitting a continuous signing stream into
individual signs. The current trigger is a hand-**motion-magnitude** pause
(`SignSegmentBuffer`). It fails because signing-motion and inter-sign
rest-motion overlap (measured: signing ≈ 0.02–0.10, rests ≈ 0.003–0.01, with
heavy overlap), so clips merge (190-frame blobs) or fragment (6-frame bits),
and the model receives transition-contaminated, partial clips → fluent garbage.

## Goal & Success Criteria

- **Reliable, hands-free** segmentation that keeps a continuous capture session
  (no per-sign button clicks).
- **Accuracy first**: each emitted clip is a clean, rest-free single sign so
  ISLR performs like it does on deliberate isolated signs.
- **Fast on-screen feedback**: the reader sees acknowledgment the instant a sign
  ends, and the gloss within the CPU-inference floor (~0.5 s).
- Success = signing N deliberate signs (with a drop-hands beat between each)
  yields N gloss tokens, each correct at roughly the model's clean-clip rate,
  appearing live; tapping stop speaks the grammatical sentence.

## Approach: Pose-based rest detection (chosen)

Segment on a **geometric pose change**, not motion magnitude. The reader signs
with hands up in the signing zone, then **drops arms to their sides** between
signs. "Hands up" = signing; "hands at sides/down" = a sign boundary. This is a
high-contrast, low-overlap signal that carves clean single-sign clips.

Rejected alternative — continuous sliding-window recognition (fully fluid, no
boundaries): re-introduces transition contamination, needs debouncing, is
CPU-heavy (~0.5 s/inference), and is lower-accuracy. Wrong call when accuracy is
the priority. Documented as future work.

## Rest-Pose Detector

Input: 133 COCO-WholeBody keypoints per frame, normalized [0,1] (y increases
downward), with confidences. Relevant indices: wrists 9 (L) / 10 (R), shoulders
5/6, hips 11/12, hand keypoints 91–132.

`hands_at_rest(keypoints, scores) -> bool` is True when **arms are down at the
sides**, detected body-relative (no calibration) by EITHER:
1. **Lowered wrists:** both wrist `y` are below the hip line (`wrist_y > hip_y`),
   or — when hips are out of frame (low confidence) — below the shoulders by a
   margin (`wrist_y > shoulder_y + REST_DROP_MARGIN`). Arms at sides put wrists
   at ~hip level, well below the chest/face signing zone.
2. **Hands out of frame:** mean confidence of hand keypoints (91–132) below
   `REST_HAND_CONF` (hands dropped below/out of the frame when lowered).

"Signing" = not at rest. Body-relative thresholds make this robust across users
and camera framing; values are configurable for tuning.

## Segmentation State Machine (replaces motion `should_flush`)

`SignSegmentBuffer` becomes a two-state machine: `REST` ↔ `SIGNING`.

- Each fed frame is classified rest/signing.
- **Frames are accumulated only while SIGNING**; rest frames are discarded so
  the clip contains just the sign (no lead-in/out rest) — what ISLR wants.
- `REST → SIGNING` (hands raised): begin a new sign clip.
- `SIGNING → REST` sustained for `REST_DEBOUNCE_MS` (~250 ms): **flush** the
  accumulated clip if it has ≥ `SIGN_TO_TEXT_MIN_FRAMES` frames → recognize →
  append. Reset for the next sign.
- A too-short SIGNING span (< min_frames, e.g. an accidental raise) is dropped.
- The `max_frames` safety cap still force-flushes a runaway clip.
- The existing confidence/length and degenerate-output gates are retained.

## Fast On-Screen Feedback

- On `SIGNING → REST` (boundary detected, before inference), the handler
  immediately sends a partial `sign_text` of the accumulated glosses plus a
  trailing `…` pending marker → the reader instantly sees the sign was captured.
- When ISLR returns (~0.4–0.7 s, the CPU floor), the handler sends the updated
  accumulated glosses (no `…`) → the new word replaces the pending marker.
- Net UX: drop hands → instant "captured" → word appears in < ~1 s. The pending
  marker hides the unavoidable CPU inference latency behind immediate feedback.

## Downstream (unchanged)

Glosses accumulate live across the session → reader taps **stop**
(`sign_segment_end`) → flush any in-progress sign → translate the gloss sequence
to English (mBART `gloss_to_english`) → TTS to the speaker.

## Config (config.py)

Replaces the motion-pause knobs for Direction B segmentation:
- `SIGN_TO_TEXT_REST_DROP_MARGIN: float` — wrist-below-shoulder margin (normalized y) when hips aren't visible. Default ~0.15.
- `SIGN_TO_TEXT_REST_HAND_CONF: float` — hand-keypoint confidence below which hands count as out-of-frame. Default ~0.3.
- `SIGN_TO_TEXT_REST_DEBOUNCE_MS: int` — sustained rest before a flush. Default 250.
- Keep `SIGN_TO_TEXT_MIN_FRAMES` (min clean-clip length) and `SIGN_TO_TEXT_MAX_FRAMES`.
- Retire `SIGN_TO_TEXT_PAUSE_MS` / `SIGN_TO_TEXT_MOTION_THRESHOLD` from the flush path (keep the debug motion trace).

## Files to Change

- `backend/app/ws/sign_segment_buffer.py` — rest-pose state machine + `hands_at_rest()`; replace motion `should_flush`; accumulate only SIGNING frames.
- `backend/app/core/config.py` — new rest params (above).
- `backend/app/ws/handlers.py` — wire new params into the buffer; emit the `…` pending partial on boundary; recognize/accumulate path unchanged.
- `frontend/src/components/Meeting/SignCaptureView.tsx` — guidance copy ("sign, then drop your hands to your sides"); render the pending `…`.
- Tests — unit tests for `hands_at_rest()` + the state machine (synthetic up→down keypoint sequences); update the e2e smoke to feed a hands-up clip then a hands-down transition.

## Error Handling

- Person/hands not detected → treated as rest / no clip → no phantom signs.
- Sign clip below `min_frames` → dropped (accidental raises ignored).
- ISLR error or empty/degenerate output → gated (existing behavior).
- Explicit stop always finalizes whatever is accumulated.

## Testing

- Unit: `hands_at_rest()` returns correct rest/signing on crafted keypoint sets
  (wrists above/below hips; hands present/out-of-frame). State machine flushes
  exactly once per up→down cycle; ignores sub-min_frames raises.
- Integration: e2e smoke sends a SIGNING burst (hands up, ≥min_frames) followed
  by a REST transition → expects one recognized gloss; stop → English + TTS.
- Manual: sign a few deliberate signs with hands-to-sides between each; verify
  one gloss per sign, live, count matches.

## Out of Scope / Future Work

- Per-user calibration of the rest threshold (body-relative is enough for now).
- Fluid, no-rhythm continuous recognition (sliding-window or CSLR) — the harder,
  GPU/data-bound path, documented as future work.
