/// <reference lib="webworker" />
/**
 * Web Worker: RTMW whole-body pose extraction in the browser (Direction B).
 *
 * Top-down pipeline (matches rtmlib lightweight mode, the Phase-0 extractor):
 *   1. YOLOX-tiny person detector (416x416 letterbox, BGR, NMS built-in)
 *   2. crop+affine the original frame to 192x256 around the person bbox
 *   3. RTMW-DW-L-M pose (BGR, ImageNet mean/std) -> SimCC -> argmax decode
 *   4. divide keypoints by [W,H] -> the 133-kpt [0,1] contract the server expects
 *
 * Runs off the main thread; only keypoints (never pixels) ever leave the worker.
 * The decode math is the parity-tested rtmwDecode.ts. Pixel preprocessing here
 * (canvas warp/letterbox) differs sub-pixel from cv2 but is robust.
 */
import * as ort from "onnxruntime-web"

import {
  bboxXyxy2cs,
  decodeSimcc,
  DET_INPUT,
  fixAspectRatio,
  getWarpMatrix,
  letterboxRatio,
  NUM_KEYPOINTS,
  POSE_INPUT_H,
  POSE_INPUT_W,
  POSE_MEAN,
  POSE_STD,
  selectPersonBox,
  type BBox,
} from "./rtmwDecode"

type InMsg =
  | { type: "init"; modelBase: string }
  | { type: "frame"; bitmap: ImageBitmap; width: number; height: number }

let detSession: ort.InferenceSession | null = null
let poseSession: ort.InferenceSession | null = null

// Reused offscreen canvases (avoid per-frame allocation).
const detCanvas = new OffscreenCanvas(DET_INPUT, DET_INPUT)
const detCtx = detCanvas.getContext("2d", { willReadFrequently: true })!
const poseCanvas = new OffscreenCanvas(POSE_INPUT_W, POSE_INPUT_H)
const poseCtx = poseCanvas.getContext("2d", { willReadFrequently: true })!

async function init(modelBase: string): Promise<void> {
  // Pin the wasm assets to a version-matched CDN so the glue JS and .wasm agree.
  ort.env.wasm.wasmPaths = `https://cdn.jsdelivr.net/npm/onnxruntime-web@${ort.env.versions.web}/dist/`
  // Prefer WebGPU; fall back to WASM where unavailable.
  const eps: ort.InferenceSession.SessionOptions["executionProviders"] = ["webgpu", "wasm"]
  detSession = await ort.InferenceSession.create(`${modelBase}/yolox_tiny.onnx`, {
    executionProviders: eps,
  })
  poseSession = await ort.InferenceSession.create(`${modelBase}/rtmw_dw_l_m.onnx`, {
    executionProviders: eps,
  })
}

/** Build a BGR NCHW float32 tensor from RGBA pixels, optional per-channel norm. */
function toBgrNchw(
  rgba: Uint8ClampedArray,
  w: number,
  h: number,
  mean?: readonly number[],
  std?: readonly number[],
): Float32Array {
  const out = new Float32Array(3 * w * h)
  const plane = w * h
  for (let i = 0; i < plane; i++) {
    const r = rgba[i * 4]
    const g = rgba[i * 4 + 1]
    const b = rgba[i * 4 + 2]
    // Channel order BGR (rtmlib feeds cv2 BGR without a swap).
    let c0 = b
    let c1 = g
    let c2 = r
    if (mean && std) {
      c0 = (b - mean[0]) / std[0]
      c1 = (g - mean[1]) / std[1]
      c2 = (r - mean[2]) / std[2]
    }
    out[i] = c0
    out[plane + i] = c1
    out[2 * plane + i] = c2
  }
  return out
}

async function detect(bitmap: ImageBitmap): Promise<BBox | null> {
  const ratio = letterboxRatio(bitmap.width, bitmap.height)
  const rw = Math.round(bitmap.width * ratio)
  const rh = Math.round(bitmap.height * ratio)
  detCtx.fillStyle = "rgb(114,114,114)" // YOLOX pad value
  detCtx.fillRect(0, 0, DET_INPUT, DET_INPUT)
  detCtx.drawImage(bitmap, 0, 0, rw, rh) // top-left, no offset
  const { data } = detCtx.getImageData(0, 0, DET_INPUT, DET_INPUT)
  const input = toBgrNchw(data, DET_INPUT, DET_INPUT) // YOLOX: no normalization
  const tensor = new ort.Tensor("float32", input, [1, 3, DET_INPUT, DET_INPUT])
  const out = await detSession!.run({ [detSession!.inputNames[0]]: tensor })
  const dets = out.dets.data as Float32Array
  const labels = out.labels.data as BigInt64Array
  const n = out.dets.dims[1] as number
  return selectPersonBox(dets, labels, n, ratio)
}

async function pose(
  bitmap: ImageBitmap,
  bbox: BBox,
): Promise<{ keypoints: Float32Array; scores: Float32Array }> {
  const { center, scale } = bboxXyxy2cs(bbox, 1.25)
  const scaleFixed = fixAspectRatio(scale)
  // Affine warp the ORIGINAL frame into 192x256. cv2 M=[a,b,tx,c,d,ty];
  // canvas setTransform(m11,m12,m21,m22,dx,dy): newX=m11*x+m21*y+dx.
  const [a, b, tx, c, d, ty] = getWarpMatrix(center, scaleFixed)
  poseCtx.setTransform(a, c, b, d, tx, ty)
  poseCtx.drawImage(bitmap, 0, 0)
  poseCtx.setTransform(1, 0, 0, 1, 0, 0)
  const { data } = poseCtx.getImageData(0, 0, POSE_INPUT_W, POSE_INPUT_H)
  const input = toBgrNchw(data, POSE_INPUT_W, POSE_INPUT_H, POSE_MEAN as number[], POSE_STD)
  const tensor = new ort.Tensor("float32", input, [1, 3, POSE_INPUT_H, POSE_INPUT_W])
  const out = await poseSession!.run({ [poseSession!.inputNames[0]]: tensor })
  const simccX = out.simcc_x.data as Float32Array
  const simccY = out.simcc_y.data as Float32Array
  const wx = out.simcc_x.dims[2]
  const wy = out.simcc_y.dims[2]
  const { keypoints, scores } = decodeSimcc(
    simccX,
    simccY,
    NUM_KEYPOINTS,
    wx,
    wy,
    center,
    scaleFixed,
  )
  // Normalize to the [0,1] contract: x/W, y/H (original frame size).
  const flat = new Float32Array(NUM_KEYPOINTS * 2)
  const sc = new Float32Array(NUM_KEYPOINTS)
  for (let i = 0; i < NUM_KEYPOINTS; i++) {
    flat[i * 2] = keypoints[i][0] / bitmap.width
    flat[i * 2 + 1] = keypoints[i][1] / bitmap.height
    sc[i] = scores[i]
  }
  return { keypoints: flat, scores: sc }
}

self.onmessage = async (e: MessageEvent<InMsg>) => {
  const msg = e.data
  try {
    if (msg.type === "init") {
      await init(msg.modelBase)
      ;(self as DedicatedWorkerGlobalScope).postMessage({ type: "ready" })
      return
    }
    if (msg.type === "frame") {
      if (!detSession || !poseSession) {
        // Model still loading — drop the frame but ACK so the main thread
        // clears its in-flight guard and keeps sending (otherwise the very
        // first frame, sent before the model is ready, wedges the loop).
        msg.bitmap.close()
        ;(self as DedicatedWorkerGlobalScope).postMessage({ type: "no_person" })
        return
      }
      const bbox = await detect(msg.bitmap)
      if (!bbox) {
        msg.bitmap.close()
        ;(self as DedicatedWorkerGlobalScope).postMessage({ type: "no_person" })
        return
      }
      const { keypoints, scores } = await pose(msg.bitmap, bbox)
      msg.bitmap.close()
      ;(self as DedicatedWorkerGlobalScope).postMessage(
        { type: "keypoints", keypoints, scores },
        [keypoints.buffer, scores.buffer],
      )
    }
  } catch (err) {
    ;(self as DedicatedWorkerGlobalScope).postMessage({
      type: "error",
      message: err instanceof Error ? err.message : String(err),
    })
  }
}
