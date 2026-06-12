import { Flag, Hand, Loader2, Square } from "lucide-react"
import { useRef, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { usePoseCapture } from "@/hooks/usePoseCapture"
import { flagMessage } from "@/lib/flag-message"
import type { SignTextState } from "@/lib/meeting-types"
import { cn } from "@/lib/utils"

interface SignCaptureViewProps {
  /** Send a packed binary keypoint frame to the server (WebSocket.sendBinary). */
  onKeypointFrame: (frame: ArrayBuffer) => void
  /** Flush the final sentence on the server when the reader stops signing. */
  onEndSentence: () => void
  /** Latest English recognized from the reader's signing (server echo). */
  signText: SignTextState | null
  /** Meeting UUID — needed to flag a wrong translation (null until fetched). */
  meetingId?: string | null
  disabled?: boolean
}

// Below this the recognizer is guessing more than recognizing — surface a
// subtle hint so the reader knows to re-sign or type instead.
const LOW_CONFIDENCE_THRESHOLD = 0.5

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
  meetingId,
  disabled,
}: SignCaptureViewProps) {
  const videoRef = useRef<HTMLVideoElement | null>(null)
  // message_id of the last sentence the reader flagged — keyed on the id so
  // the "Flagged ✓" confirmation resets when the next sentence arrives.
  const [flaggedId, setFlaggedId] = useState<string | null>(null)
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

  const handleFlag = async () => {
    if (!signText?.messageId || !meetingId) return
    const id = signText.messageId
    if (await flagMessage(meetingId, id)) {
      setFlaggedId(id)
    }
  }

  const isLowConfidence =
    signText?.confidence !== undefined &&
    signText.confidence < LOW_CONFIDENCE_THRESHOLD

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
            ? "Sign, then pause a moment between signs (keep hands up) — tap to stop"
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
              <span className="text-green-300">
                ● detected · {framesSent} frames
              </span>
            ) : (
              <span className="text-amber-300">
                ○ no person — center yourself, good lighting
              </span>
            )}
          </div>
        )}
      </div>

      {/* Recognized English echo */}
      {signText && (
        <div className="w-full max-w-md rounded-md bg-muted px-3 py-2 text-sm">
          <p>
            <span className="text-muted-foreground">Recognized:</span>{" "}
            {signText.content}
            {isLowConfidence && (
              <Badge
                variant="outline"
                className="ml-2 border-dashed text-muted-foreground"
                title="The recognizer was unsure — consider re-signing or typing instead"
              >
                low confidence
              </Badge>
            )}
          </p>
          {/* Finalized sentences carry a message_id — offer feedback capture. */}
          {signText.messageId &&
            meetingId &&
            (flaggedId === signText.messageId ? (
              <p className="mt-1 text-xs text-muted-foreground">Flagged ✓</p>
            ) : (
              <Button
                variant="ghost"
                size="sm"
                className="mt-1 h-6 px-2 text-xs text-muted-foreground"
                onClick={handleFlag}
              >
                <Flag className="h-3 w-3" aria-hidden="true" />
                Flag wrong translation
              </Button>
            ))}
        </div>
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
        <span
          className={cn(
            "text-sm",
            cameraError || error ? "text-red-500" : "text-muted-foreground",
          )}
        >
          {status}
        </span>
      </div>
    </div>
  )
}
