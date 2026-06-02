import { type RefObject, useCallback, useEffect, useRef, useState } from "react"

import { packKeypointFrame, type PoseFrame } from "@/pose/keypointFrame"

interface UsePoseCaptureOptions {
  /** Called with a packed binary keypoint frame ready for WebSocket.sendBinary. */
  onKeypointFrame: (frame: ArrayBuffer) => void
  /** When true, acquire the camera + show the live preview (independent of capture). */
  enabled: boolean
  /** Visible <video> element to preview + capture from. */
  videoRef: RefObject<HTMLVideoElement | null>
  /** Frames per packed batch sent to the server (server segments the stream). */
  batchFrames?: number
  /** Throttle worker inference to roughly this many fps (RTMW is heavy). */
  targetFps?: number
}

type WorkerMsg =
  | { type: "ready" }
  | { type: "keypoints"; keypoints: Float32Array; scores: Float32Array }
  | { type: "no_person" }
  | { type: "error"; message: string }

// Defaults to same-origin assets; set VITE_MODEL_BASE (build-time) to a CDN /
// bucket URL to offload the ~71 MB pose models from the app server.
const MODEL_BASE = import.meta.env.VITE_MODEL_BASE || "/models/rtmw"

/**
 * Two independent lifecycles:
 *   - CAMERA: acquired automatically while `enabled`, so the reader sees their
 *     live preview as soon as the view opens (before pressing anything).
 *   - CAPTURE (button-gated): starts the RTMW Web Worker + frame loop that
 *     extracts 133 keypoints and streams batched binary frames to the server.
 *     Only keypoints leave the device; the camera keeps previewing either way.
 */
export function usePoseCapture({
  onKeypointFrame,
  enabled,
  videoRef,
  batchFrames = 10,
  targetFps = 12,
}: UsePoseCaptureOptions) {
  const [isCameraOn, setIsCameraOn] = useState(false)
  const [cameraError, setCameraError] = useState<string | null>(null)
  const [isCapturing, setIsCapturing] = useState(false)
  const [isReady, setIsReady] = useState(false) // pose model loaded in worker
  const [error, setError] = useState<string | null>(null) // capture/worker error
  // Live diagnostics so the reader can see keypoints actually flowing.
  const [framesSent, setFramesSent] = useState(0) // worker keypoint results emitted
  const [personDetected, setPersonDetected] = useState(false)

  const streamRef = useRef<MediaStream | null>(null)
  const workerRef = useRef<Worker | null>(null)
  const accRef = useRef<PoseFrame[]>([])
  const inFlightRef = useRef(false)
  const rafRef = useRef<number | null>(null)
  const onFrameRef = useRef(onKeypointFrame)
  onFrameRef.current = onKeypointFrame

  const flushBatch = useCallback(() => {
    const frames = accRef.current
    if (frames.length === 0) return
    const v = videoRef.current
    onFrameRef.current(packKeypointFrame(frames, v?.videoWidth ?? 0, v?.videoHeight ?? 0))
    accRef.current = []
  }, [videoRef])

  // ── Capture (worker) — button-gated ──────────────────────────────────────
  const stopCapture = useCallback(() => {
    if (rafRef.current != null) clearInterval(rafRef.current)
    rafRef.current = null
    flushBatch() // send whatever was buffered before tearing the worker down
    workerRef.current?.terminate()
    workerRef.current = null
    accRef.current = []
    inFlightRef.current = false
    setIsCapturing(false)
    setIsReady(false)
    setPersonDetected(false)
    setFramesSent(0)
  }, [flushBatch, videoRef])

  const startCapture = useCallback(() => {
    // Needs a live camera; the button is disabled until then, but guard anyway.
    if (!streamRef.current || !videoRef.current || workerRef.current) return
    setError(null)

    const worker = new Worker(new URL("../pose/rtmwWorker.ts", import.meta.url), {
      type: "module",
    })
    workerRef.current = worker
    // Surface worker load/runtime failures instead of hanging silently — the
    // worker pulls onnxruntime-web + a ~143MB model and can fail (WebGPU,
    // network, OOM). Without this the UI would sit on "Loading model" forever.
    worker.onerror = (ev) =>
      setError(`Pose model failed to load${ev.message ? `: ${ev.message}` : ""}`)
    worker.onmessageerror = () => setError("Pose worker message error")
    worker.onmessage = (e: MessageEvent<WorkerMsg>) => {
      const msg = e.data
      if (msg.type === "ready") {
        setIsReady(true)
        return
      }
      if (msg.type === "keypoints") {
        inFlightRef.current = false
        setPersonDetected(true)
        setFramesSent((n) => n + 1)
        accRef.current.push({ keypoints: msg.keypoints, scores: msg.scores })
        if (accRef.current.length >= batchFrames) flushBatch()
        return
      }
      if (msg.type === "no_person") {
        inFlightRef.current = false
        setPersonDetected(false)
        return
      }
      if (msg.type === "error") {
        inFlightRef.current = false
        setError(msg.message)
      }
    }
    worker.postMessage({ type: "init", modelBase: MODEL_BASE })

    // Drive the capture loop with a timer, NOT requestVideoFrameCallback:
    // rVFC only fires when frames are presented to a compositor, so it stalls
    // in headless and can be flaky; a timer captures frames regardless. The
    // in-flight guard skips ticks while the worker is still busy with a frame.
    const tick = () => {
      const v = videoRef.current
      const wk = workerRef.current
      if (!v || !wk || inFlightRef.current || v.videoWidth === 0) return
      inFlightRef.current = true
      createImageBitmap(v)
        .then((bitmap) => {
          wk.postMessage(
            { type: "frame", bitmap, width: v.videoWidth, height: v.videoHeight },
            [bitmap],
          )
        })
        .catch(() => {
          inFlightRef.current = false
        })
    }
    rafRef.current = window.setInterval(tick, 1000 / targetFps)
    setIsCapturing(true)
  }, [batchFrames, targetFps, flushBatch, videoRef])

  // ── Camera — auto-acquired while enabled ──────────────────────────────────
  const startCamera = useCallback(async () => {
    if (streamRef.current) return // already on
    setCameraError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: "user" },
      })
      streamRef.current = stream
      const video = videoRef.current
      if (video) {
        video.srcObject = stream
        video.muted = true
        video.playsInline = true
        video.play().catch(() => {})
      }
      setIsCameraOn(true)
    } catch (err) {
      const msg =
        err instanceof DOMException && err.name === "NotAllowedError"
          ? "Camera permission denied — allow camera access and reload"
          : err instanceof DOMException && err.name === "NotFoundError"
            ? "No camera found"
            : "Could not access the camera"
      setCameraError(msg)
    }
  }, [videoRef])

  const stopCamera = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    if (videoRef.current) videoRef.current.srcObject = null
    setIsCameraOn(false)
  }, [videoRef])

  // Acquire the camera on mount/enable; tear capture + camera down on exit.
  useEffect(() => {
    if (enabled) void startCamera()
    return () => {
      stopCapture()
      stopCamera()
    }
  }, [enabled, startCamera, stopCamera, stopCapture])

  return {
    isCameraOn,
    cameraError,
    isCapturing,
    isReady,
    error,
    framesSent,
    personDetected,
    startCapture,
    stopCapture,
  }
}
