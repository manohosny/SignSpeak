import { Hand, Loader2, Square } from "lucide-react"
import { useRef } from "react"

import { Button } from "@/components/ui/button"
import { usePoseCapture } from "@/hooks/usePoseCapture"
import { cn } from "@/lib/utils"

interface SignCaptureViewProps {
  /** Send a packed binary keypoint frame to the server (WebSocket.sendBinary). */
  onKeypointFrame: (frame: ArrayBuffer) => void
  /** Flush the final sentence on the server when the reader stops signing. */
  onEndSentence: () => void
  /** Latest English recognized from the reader's signing (server echo). */
  signText: string | null
  disabled?: boolean
}

/**
 * Direction B reader UI. The webcam preview is live as soon as the view opens.
 * One toggle button (like the speaker's mic) starts/stops the actual sign
 * capture: tap to begin streaming keypoints for recognition, tap again to stop.
 * Only keypoints leave the device; the camera keeps previewing regardless.
 * The first capture downloads the pose model (~143MB), so "Loading…" is shown.
 */
export function SignCaptureView({
  onKeypointFrame,
  onEndSentence,
  signText,
  disabled,
}: SignCaptureViewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const {
    isCameraOn,
    cameraError,
    isCapturing,
    isReady,
    error,
    framesSent,
    personDetected,
    startCapture,
    stopCapture,
  } = usePoseCapture({ onKeypointFrame, enabled: !disabled, videoRef })

  const handleToggle = () => {
    if (isCapturing) {
      stopCapture()
      onEndSentence() // flush whatever was signed as a final sentence
    } else {
      startCapture()
    }
  }

  const loadingModel = isCapturing && !isReady
  const status = cameraError
    ? cameraError
    : error
      ? error
      : !isCameraOn
        ? "Starting camera…"
        : loadingModel
          ? "Loading sign model… (first time can take ~10s)"
          : isCapturing
            ? "Sign, then drop your hands to your sides between signs — tap to stop"
            : "Tap to start signing"

  return (
    <div className="flex flex-1 flex-col items-center gap-4 p-4">
      {/* Live camera preview (independent of capture) */}
      <div className="relative w-full max-w-md overflow-hidden rounded-lg bg-black">
        <video
          ref={videoRef}
          className="aspect-video w-full -scale-x-100 object-cover"
          autoPlay
          playsInline
          muted
        />
        {!isCameraOn && !cameraError && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 text-sm text-white/70">
            <Loader2 className="h-4 w-4 animate-spin" /> Starting camera…
          </div>
        )}
        {cameraError && (
          <div className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-red-300">
            {cameraError}
          </div>
        )}
        {loadingModel && (
          <div className="absolute inset-0 flex items-center justify-center gap-2 bg-black/50 text-sm text-white">
            <Loader2 className="h-4 w-4 animate-spin" /> Loading model…
          </div>
        )}
        {/* Live capture feedback: are keypoints actually flowing? */}
        {isCapturing && isReady && (
          <div className="absolute bottom-2 left-2 rounded bg-black/60 px-2 py-1 text-xs text-white">
            {personDetected ? (
              <span className="text-green-300">● detected · {framesSent} frames</span>
            ) : (
              <span className="text-amber-300">○ no person — center yourself, good lighting</span>
            )}
          </div>
        )}
      </div>

      {/* Recognized English echo */}
      {signText && (
        <p className="w-full max-w-md rounded-md bg-muted px-3 py-2 text-sm">
          <span className="text-muted-foreground">Recognized:</span> {signText}
        </p>
      )}

      {/* Single toggle button (mic-button style) — gates capture only */}
      <div className="flex flex-col items-center gap-3">
        <div className="relative">
          {isCapturing && isReady && (
            <div className="absolute -inset-2 animate-ping rounded-full bg-red-500/30" />
          )}
          <Button
            size="lg"
            variant={isCapturing ? "destructive" : "default"}
            className="relative h-24 w-24 rounded-full transition-all duration-300"
            onClick={handleToggle}
            disabled={disabled || !isCameraOn}
            aria-label={isCapturing ? "Stop signing" : "Start signing"}
            aria-pressed={isCapturing}
          >
            {loadingModel ? (
              <Loader2 className="h-10 w-10 animate-spin" aria-hidden="true" />
            ) : isCapturing ? (
              <Square className="h-9 w-9" aria-hidden="true" />
            ) : (
              <Hand className="h-10 w-10" aria-hidden="true" />
            )}
          </Button>
        </div>
        <span className={cn("text-sm", cameraError || error ? "text-red-500" : "text-muted-foreground")}>
          {status}
        </span>
      </div>
    </div>
  )
}
