/**
 * Pure decode math for the browser RTMW pipeline — a faithful TypeScript port of
 * rtmlib's RTMPose/YOLOX pre/post-processing (sign_to_gloss/Uni-Sign/demo/rtmlib-main).
 *
 * Keeping this pure (no DOM, no onnxruntime) lets it be unit-tested against
 * golden vectors captured from Python rtmlib, so the keypoints the browser
 * produces match the distribution the Uni-Sign checkpoint was trained on.
 *
 * Pipeline: YOLOX person detect -> bbox -> center/scale -> affine warp to
 * 192x256 -> RTMW SimCC -> argmax decode -> rescale to image coords.
 */

export type Point = [number, number]
export type BBox = [number, number, number, number] // x1,y1,x2,y2

export const POSE_INPUT_W = 192
export const POSE_INPUT_H = 256
export const DET_INPUT = 416
export const SIMCC_SPLIT_RATIO = 2.0
export const NUM_KEYPOINTS = 133
// ImageNet mean/std used by RTMPose (RGB).
export const POSE_MEAN: Point | [number, number, number] = [
  123.675, 116.28, 103.53,
]
export const POSE_STD: [number, number, number] = [58.395, 57.12, 57.375]

// ── bbox -> center/scale (bbox_xyxy2cs) ──────────────────────────────────────
export function bboxXyxy2cs(
  bbox: BBox,
  padding = 1.25,
): { center: Point; scale: Point } {
  const [x1, y1, x2, y2] = bbox
  return {
    center: [(x1 + x2) * 0.5, (y1 + y2) * 0.5],
    scale: [(x2 - x1) * padding, (y2 - y1) * padding],
  }
}

// Reshape scale to the model's fixed aspect ratio (top_down_affine).
export function fixAspectRatio(
  scale: Point,
  w = POSE_INPUT_W,
  h = POSE_INPUT_H,
): Point {
  const aspect = w / h
  const [bw, bh] = scale
  return bw > bh * aspect ? [bw, bw / aspect] : [bh * aspect, bh]
}

function get3rdPoint(a: Point, b: Point): Point {
  const dir: Point = [a[0] - b[0], a[1] - b[1]]
  return [b[0] - dir[1], b[1] + dir[0]]
}

/**
 * 2x3 affine mapping src triangle -> dst triangle (cv2.getAffineTransform).
 * Returned as [a, b, tx, c, d, ty] with dst = [a*x+b*y+tx, c*x+d*y+ty].
 */
export function getAffineTransform(
  src: [Point, Point, Point],
  dst: [Point, Point, Point],
): number[] {
  // Solve two 3x3 systems: [x y 1] · [a b tx]^T = dst_x  (and dst_y).
  const A = [
    [src[0][0], src[0][1], 1],
    [src[1][0], src[1][1], 1],
    [src[2][0], src[2][1], 1],
  ]
  const solve3 = (bx: number[]): [number, number, number] => {
    // Cramer's rule on the 3x3 system A·t = bx.
    const det = (m: number[][]) =>
      m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1]) -
      m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0]) +
      m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    const D = det(A)
    const col = (i: number) =>
      A.map((row, r) => row.map((v, c) => (c === i ? bx[r] : v)))
    return [det(col(0)) / D, det(col(1)) / D, det(col(2)) / D]
  }
  const [a, b, tx] = solve3([dst[0][0], dst[1][0], dst[2][0]])
  const [c, d, ty] = solve3([dst[0][1], dst[1][1], dst[2][1]])
  return [a, b, tx, c, d, ty]
}

/** Forward warp matrix (src image -> 192x256 model input), rot = 0. */
export function getWarpMatrix(
  center: Point,
  scale: Point,
  w = POSE_INPUT_W,
  h = POSE_INPUT_H,
): number[] {
  const srcW = scale[0]
  const srcDir: Point = [0, srcW * -0.5]
  const dstDir: Point = [0, w * -0.5]
  const src: [Point, Point, Point] = [
    [center[0], center[1]],
    [center[0] + srcDir[0], center[1] + srcDir[1]],
    get3rdPoint(
      [center[0], center[1]],
      [center[0] + srcDir[0], center[1] + srcDir[1]],
    ),
  ]
  const dstC: Point = [w * 0.5, h * 0.5]
  const dst: [Point, Point, Point] = [
    dstC,
    [dstC[0] + dstDir[0], dstC[1] + dstDir[1]],
    get3rdPoint(dstC, [dstC[0] + dstDir[0], dstC[1] + dstDir[1]]),
  ]
  return getAffineTransform(src, dst)
}

// ── SimCC decode (get_simcc_maximum) ─────────────────────────────────────────
/**
 * Argmax over the x and y SimCC bins per keypoint.
 * simccX: Float32Array length K*Wx, simccY: length K*Wy (N=1).
 * Returns image-space keypoints (K,2) + scores (K).
 */
export function decodeSimcc(
  simccX: Float32Array,
  simccY: Float32Array,
  k: number,
  wx: number,
  wy: number,
  center: Point,
  scale: Point,
  inputW = POSE_INPUT_W,
  inputH = POSE_INPUT_H,
): { keypoints: Point[]; scores: number[] } {
  const keypoints: Point[] = []
  const scores: number[] = []
  for (let j = 0; j < k; j++) {
    let xMax = -Infinity
    let xLoc = 0
    for (let i = 0; i < wx; i++) {
      const v = simccX[j * wx + i]
      if (v > xMax) {
        xMax = v
        xLoc = i
      }
    }
    let yMax = -Infinity
    let yLoc = 0
    for (let i = 0; i < wy; i++) {
      const v = simccY[j * wy + i]
      if (v > yMax) {
        yMax = v
        yLoc = i
      }
    }
    const val = 0.5 * (xMax + yMax)
    // locs / split_ratio, then rescale: loc/input_size * scale + center - scale/2
    let px = xLoc / SIMCC_SPLIT_RATIO
    let py = yLoc / SIMCC_SPLIT_RATIO
    if (val <= 0) {
      px = -1
      py = -1
    }
    const imgX = (px / inputW) * scale[0] + center[0] - scale[0] / 2
    const imgY = (py / inputH) * scale[1] + center[1] - scale[1] / 2
    keypoints.push([imgX, imgY])
    scores.push(val)
  }
  return { keypoints, scores }
}

// ── YOLOX person detection ───────────────────────────────────────────────────
// The rtmlib SDK YOLOX export has NMS built in: outputs `dets` (1,N,5) as
// [x1,y1,x2,y2,score] in the 416x416 letterboxed space + `labels` (1,N) class
// ids. We just pick the highest-scoring person (class 0) and undo the letterbox
// (divide by ratio = min(416/H, 416/W), top-left padded — no offset).
export function selectPersonBox(
  dets: Float32Array,
  labels: BigInt64Array | Int32Array | number[],
  n: number,
  ratio: number,
  scoreThr = 0.3,
): BBox | null {
  let best: BBox | null = null
  let bestScore = scoreThr
  for (let i = 0; i < n; i++) {
    if (Number(labels[i]) !== 0) continue // person class
    const score = dets[i * 5 + 4]
    if (score < bestScore) continue
    bestScore = score
    best = [
      dets[i * 5 + 0] / ratio,
      dets[i * 5 + 1] / ratio,
      dets[i * 5 + 2] / ratio,
      dets[i * 5 + 3] / ratio,
    ]
  }
  return best
}

/** Letterbox ratio for YOLOX (resize keeping aspect, pad bottom/right with 114). */
export function letterboxRatio(
  imgW: number,
  imgH: number,
  input = DET_INPUT,
): number {
  return Math.min(input / imgH, input / imgW)
}
