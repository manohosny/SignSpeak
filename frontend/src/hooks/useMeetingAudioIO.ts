import { useCallback, useEffect, useState } from "react"

import { useAudioPlayer } from "./useAudioPlayer"
import { useAudioRecorder } from "./useAudioRecorder"

// ─────────────────────────────────────────────────────────────────────
// Player half — independent of the WebSocket. Declared first in the
// facade so the WS handler can use playAudio from its onBinaryMessage.
// ─────────────────────────────────────────────────────────────────────

interface UseMeetingAudioPlayerResult {
  playAudio: (data: ArrayBuffer) => void
  stopAudio: () => void
  unlockAudio: () => void
  hasPendingAudio: boolean
}

export function useMeetingAudioPlayer(): UseMeetingAudioPlayerResult {
  return useAudioPlayer()
}

// ─────────────────────────────────────────────────────────────────────
// Recorder half — depends on the WebSocket's sendBinary / sendJson.
// Declared after useWebSocket in the facade.
// ─────────────────────────────────────────────────────────────────────

interface UseMeetingAudioRecorderOptions {
  /** Speaker is the only role that records; reader's mic is irrelevant. */
  role: "speaker" | "reader" | null
  /** Recorder is gated on the meeting being live. */
  isActive: boolean
  /** Mic + player auto-stop once the meeting reaches a terminal state. */
  isTerminated: boolean
  sendBinary: (data: ArrayBuffer) => void
  sendJson: (msg: { type: "control"; action: "utterance_end" }) => void
  /** AudioContext unlock to invoke during the user's mic-toggle gesture. */
  unlockAudio: () => void
  /** Player stop, fired when meeting terminates or the user ends. */
  stopAudio: () => void
}

interface UseMeetingAudioRecorderResult {
  isMicOn: boolean
  isSpeaking: boolean
  /** Surfaces `getUserMedia` / worklet failures to the UI. */
  micError: string | null
  toggleMic: () => void
  /** Stop both recorder and player. */
  stopAll: () => void
}

export function useMeetingAudioRecorder({
  role,
  isActive,
  isTerminated,
  sendBinary,
  sendJson,
  unlockAudio,
  stopAudio,
}: UseMeetingAudioRecorderOptions): UseMeetingAudioRecorderResult {
  const [isMicOn, setIsMicOn] = useState(false)

  const handleAudioChunk = useCallback(
    (pcm16: ArrayBuffer) => {
      sendBinary(pcm16)
    },
    [sendBinary],
  )

  const handleVadChange = useCallback(
    (speaking: boolean) => {
      if (!speaking) {
        sendJson({ type: "control", action: "utterance_end" })
      }
    },
    [sendJson],
  )

  const {
    isRecording,
    isSpeaking,
    error: micError,
    startRecording,
    stopRecording,
  } = useAudioRecorder({
    onAudioChunk: handleAudioChunk,
    onVadChange: handleVadChange,
    enabled: role === "speaker" && isActive,
  })

  // If the recorder failed to start, the underlying state is already off —
  // sync `isMicOn` so the UI button doesn't stay "on" after a failure.
  useEffect(() => {
    if (micError) setIsMicOn(false)
  }, [micError])

  const toggleMic = useCallback(() => {
    unlockAudio()
    if (isRecording) {
      stopRecording()
      setIsMicOn(false)
    } else {
      startRecording()
      setIsMicOn(true)
    }
  }, [isRecording, startRecording, stopRecording, unlockAudio])

  const stopAll = useCallback(() => {
    stopRecording()
    stopAudio()
  }, [stopRecording, stopAudio])

  useEffect(() => {
    if (isTerminated) stopAll()
  }, [isTerminated, stopAll])

  return { isMicOn, isSpeaking, micError, toggleMic, stopAll }
}
