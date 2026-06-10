import { describe, expect, it } from "vitest"
import {
  NUM_KEYPOINTS,
  type PoseFrame,
  packKeypointFrame,
  parseKeypointFrame,
} from "../keypointFrame"
import {
  type BBox,
  bboxXyxy2cs,
  decodeSimcc,
  fixAspectRatio,
  getWarpMatrix,
  type Point,
} from "../rtmwDecode"
import fixture from "./fixtures/rtmpose_decode.json"

// Ground truth produced by the verbatim Python rtmlib math (gen_fixture.py).
// These assertions are the cross-language parity guarantee: the browser's
// keypoints must match the distribution the Uni-Sign checkpoint was trained on.

const TOL = 1e-3

describe("rtmwDecode parity vs Python rtmlib", () => {
  it("bboxXyxy2cs matches", () => {
    const { center, scale } = bboxXyxy2cs(fixture.bbox as BBox, 1.25)
    expect(center[0]).toBeCloseTo(fixture.center[0], 4)
    expect(center[1]).toBeCloseTo(fixture.center[1], 4)
    expect(scale[0]).toBeCloseTo(fixture.scale[0], 4)
    expect(scale[1]).toBeCloseTo(fixture.scale[1], 4)
  })

  it("fixAspectRatio matches", () => {
    const sf = fixAspectRatio(fixture.scale as Point)
    expect(sf[0]).toBeCloseTo(fixture.scale_fixed[0], 4)
    expect(sf[1]).toBeCloseTo(fixture.scale_fixed[1], 4)
  })

  it("getWarpMatrix matches cv2.getAffineTransform", () => {
    const m = getWarpMatrix(
      fixture.center as Point,
      fixture.scale_fixed as Point,
    )
    // m = [a,b,tx,c,d,ty]; cv2 M = [[a,b,tx],[c,d,ty]]
    const expected = [...fixture.warp_mat[0], ...fixture.warp_mat[1]]
    for (let i = 0; i < 6; i++) expect(m[i]).toBeCloseTo(expected[i], 4)
  })

  it("decodeSimcc reproduces keypoints + scores", () => {
    const simccX = new Float32Array(fixture.simcc_x)
    const simccY = new Float32Array(fixture.simcc_y)
    const { keypoints, scores } = decodeSimcc(
      simccX,
      simccY,
      fixture.K,
      fixture.Wx,
      fixture.Wy,
      fixture.center as Point,
      fixture.scale_fixed as Point,
    )
    expect(keypoints.length).toBe(fixture.K)
    for (let j = 0; j < fixture.K; j++) {
      expect(keypoints[j][0]).toBeCloseTo(fixture.keypoints[j][0], 2)
      expect(keypoints[j][1]).toBeCloseTo(fixture.keypoints[j][1], 2)
      expect(scores[j]).toBeCloseTo(fixture.scores[j], TOL)
    }
  })
})

describe("keypointFrame codec round-trip", () => {
  it("packs + parses back identical data", () => {
    const frames: PoseFrame[] = []
    for (let t = 0; t < 4; t++) {
      const kp = new Float32Array(NUM_KEYPOINTS * 2)
      const sc = new Float32Array(NUM_KEYPOINTS)
      for (let k = 0; k < NUM_KEYPOINTS; k++) {
        kp[k * 2] = (k + t) / 200
        kp[k * 2 + 1] = (k * 2 + t) / 300
        sc[k] = (k % 10) / 10
      }
      frames.push({ keypoints: kp, scores: sc })
    }
    const buf = packKeypointFrame(frames, 640, 480)
    // header (8) + T*133*3*4
    expect(buf.byteLength).toBe(8 + 4 * NUM_KEYPOINTS * 3 * 4)
    const { frames: out, width, height } = parseKeypointFrame(buf)
    expect([width, height]).toEqual([640, 480])
    expect(out.length).toBe(4)
    for (let t = 0; t < 4; t++) {
      for (let k = 0; k < NUM_KEYPOINTS * 2; k++) {
        expect(out[t].keypoints[k]).toBeCloseTo(frames[t].keypoints[k], 5)
      }
    }
  })

  it("tags the first byte as KEYPOINT_FRAME (0x01)", () => {
    const kp = new Float32Array(NUM_KEYPOINTS * 2)
    const sc = new Float32Array(NUM_KEYPOINTS)
    const buf = packKeypointFrame([{ keypoints: kp, scores: sc }], 10, 10)
    expect(new Uint8Array(buf)[0]).toBe(0x01)
  })
})
