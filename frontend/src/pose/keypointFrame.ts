/**
 * Binary keypoint-frame packer — the client side of the wire format defined by
 * the backend in app/ws/keypoint_frame.py. Keep the two BYTE-FOR-BYTE in sync.
 *
 * Layout (little-endian):
 *   0      uint8    frame_type (0x01)
 *   1      uint8    version    (0x01)
 *   2..3   uint16   frame_count T
 *   4..5   uint16   width
 *   6..7   uint16   height
 *   8..    float32  T x 133 x 3  [x_norm, y_norm, score]
 */

export const KEYPOINT_FRAME_TYPE = 0x01
export const FRAME_VERSION = 0x01
export const NUM_KEYPOINTS = 133
const CHANNELS = 3
const HEADER_SIZE = 8

export interface PoseFrame {
  /** 133 * 2 normalized [0,1] coords, interleaved [x0,y0,x1,y1,...] */
  keypoints: Float32Array
  /** 133 confidence scores */
  scores: Float32Array
}

/** Pack accumulated per-frame keypoints into one binary frame for the WS. */
export function packKeypointFrame(
  frames: PoseFrame[],
  width: number,
  height: number,
): ArrayBuffer {
  const t = frames.length
  const buf = new ArrayBuffer(HEADER_SIZE + t * NUM_KEYPOINTS * CHANNELS * 4)
  const view = new DataView(buf)
  view.setUint8(0, KEYPOINT_FRAME_TYPE)
  view.setUint8(1, FRAME_VERSION)
  view.setUint16(2, t, true)
  view.setUint16(4, width, true)
  view.setUint16(6, height, true)

  let off = HEADER_SIZE
  for (const f of frames) {
    for (let k = 0; k < NUM_KEYPOINTS; k++) {
      view.setFloat32(off, f.keypoints[k * 2], true)
      view.setFloat32(off + 4, f.keypoints[k * 2 + 1], true)
      view.setFloat32(off + 8, f.scores[k], true)
      off += 12
    }
  }
  return buf
}

/** Inverse of packKeypointFrame — used by parity/round-trip tests. */
export function parseKeypointFrame(buf: ArrayBuffer): {
  frames: PoseFrame[]
  width: number
  height: number
} {
  const view = new DataView(buf)
  if (view.getUint8(0) !== KEYPOINT_FRAME_TYPE)
    throw new Error("bad frame_type")
  const t = view.getUint16(2, true)
  const width = view.getUint16(4, true)
  const height = view.getUint16(6, true)
  const frames: PoseFrame[] = []
  let off = HEADER_SIZE
  for (let i = 0; i < t; i++) {
    const keypoints = new Float32Array(NUM_KEYPOINTS * 2)
    const scores = new Float32Array(NUM_KEYPOINTS)
    for (let k = 0; k < NUM_KEYPOINTS; k++) {
      keypoints[k * 2] = view.getFloat32(off, true)
      keypoints[k * 2 + 1] = view.getFloat32(off + 4, true)
      scores[k] = view.getFloat32(off + 8, true)
      off += 12
    }
    frames.push({ keypoints, scores })
  }
  return { frames, width, height }
}
