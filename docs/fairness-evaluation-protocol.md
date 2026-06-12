# Fairness Evaluation Protocol — Pose → Sign Pipeline (Direction B)

The README states honestly that no fairness evaluation across signer demographics has been run yet. This document is the concrete, executable protocol for closing that gap. It covers the **perception half** of Direction B: browser-side YOLOX + RTMW pose extraction → keypoint streaming → segmentation gates → Uni-Sign ISLR recognition.

## Scope — what this protocol does and does not cover

**Covered:** whether the pose extractor, segmentation gates, and sign recognizer perform equitably across skin tone, lighting, signing speed, and hand size. These are perception-stage properties that can vary with signer appearance and camera conditions.

**Not covered:** the ASL/ISL lexicon mismatch documented in the README ("Privacy & Known Model Limitations") — the avatar renders ASL gloss with a ~1,168-sign **Indian Sign Language** lexicon. That is a known, documented bias, but it is a **lexicon-content issue, not a perception issue**: it affects every user identically regardless of appearance, and no amount of keypoint-level evaluation can detect or fix it. It stays tracked in the README limitations list, not here.

## Participant matrix

Recruit adult signers to fill every cell of the matrix below. Minimum one signer per skin-tone bin; two or more per bin strongly preferred so individual signing style does not masquerade as a group effect.

| Dimension | Levels |
| --- | --- |
| Skin tone (Fitzpatrick scale) | I, II, III, IV, V, VI — one bin each |
| Lighting | bright/even (≥ 500 lux frontal), dim indoor (~100 lux), strong backlight (window or lamp behind signer) |
| Signing speed | slow (deliberate, ~50% natural pace), natural, fast (conversational-rushed) |
| Hand size | record signer hand length (wrist crease → middle fingertip); ensure the cohort spans at least the 16–21 cm adult range |

Each signer records the full 20-sign session (below) under each of the 3 lighting conditions at each of the 3 speeds: 9 sessions per signer. Hand size is a measured covariate, not a session variable.

## Data collection

- Sessions are recorded through the **existing browser extractor** (the same ONNX web-worker path production uses): per the README privacy section, **only the 133 RTMW pose keypoints (x, y, confidence) leave the device — never video**. This protocol inherits that property: the stored evaluation artifact is the keypoint stream plus session metadata (anonymous signer ID, Fitzpatrick bin, lighting condition, speed, hand length), no raw pixels.
- **Demo vocabulary:** a fixed list of 20 WLASL signs within the Uni-Sign checkpoint's vocabulary, chosen once and committed alongside the first results table (mix of one- and two-handed signs, varied handshapes). Every session signs all 20, in randomized order shown on a prompt screen, with hands returned to rest between signs.
- Participants give informed consent for keypoint recording and aggregate reporting; self-reported Fitzpatrick bin is confirmed against a reference chart at recording time.

## Metrics per matrix cell

Computed offline from the recorded keypoint streams, replaying them through the production segmentation and recognition code with production thresholds (`SIGN_TO_TEXT_*` in `backend/app/core/config.py`):

1. **Mean RTMW hand-keypoint confidence** — mean detection confidence over the 42 hand keypoints across all signing frames in the session. This is the most direct probe of whether pose extraction degrades for darker skin tones or poor lighting.
2. **Gate-fire rate** — fraction of attempted signs rejected by the production gates: the min-confidence gate (`SIGN_TO_TEXT_MIN_CONFIDENCE`, hand confidence below 0.3 ⇒ segment dropped) and the min-length gate (`SIGN_TO_TEXT_MIN_FRAMES`, fewer than 18 signing frames ⇒ dropped). A gate that fires disproportionately for one group silently erases that group's signs.
3. **ISLR top-1 accuracy** — fraction of the 20 demo-vocabulary signs recognized correctly (top-1) among segments that passed the gates.

## Acceptance bar

For each of **mean hand-keypoint confidence** and **ISLR top-1 accuracy**, aggregate per skin-tone bin (across lighting and speed) and compute the maximum relative disparity:

```
disparity = (best_bin − worst_bin) / best_bin
```

- **Pass:** disparity < 10% on both metrics.
- **Fail:** disparity ≥ 10% on either metric ⇒ the result must be investigated before the change ships: isolate whether the gap is extraction (metric 1), gating (metric 2), or recognition (metric 3), and either fix it or document the limitation in the README alongside the existing known limitations.

Gate-fire rate has no fixed bar but is reported per cell and must be examined whenever the disparity check fails — it is usually the mechanism by which an extraction-confidence gap becomes a user-visible one.

## Cadence

Run this protocol **before each model or threshold change reaches production** — i.e., any change to the RTMW/YOLOX extractor models, the Uni-Sign checkpoint, or the `SIGN_TO_TEXT_*` segmentation/gating thresholds. Recorded keypoint sessions are reusable: a threshold-only change replays the existing sessions; new extractor models require re-recording (the keypoints themselves change).

## Reporting

Append one results table per evaluation run to the **Results log** below: date, git commit, model/threshold versions, per-bin mean confidence, gate-fire rate, top-1 accuracy, computed disparities, and pass/fail. Failures link to the investigation issue.

## Results log

*No runs recorded yet.*

| Date | Commit | Change under test | Confidence disparity | Top-1 disparity | Pass | Notes |
| --- | --- | --- | --- | --- | --- | --- |
