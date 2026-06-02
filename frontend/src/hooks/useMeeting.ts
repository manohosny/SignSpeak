import { useCallback, useEffect, useRef, useState } from "react"

import type { MeetingState, WsServerMessage } from "@/lib/meeting-types"

import {
  useMeetingAudioPlayer,
  useMeetingAudioRecorder,
} from "./useMeetingAudioIO"
import { useMeetingFetch } from "./useMeetingFetch"
import { useMeetingMessages } from "./useMeetingMessages"
import { useWebSocket } from "./useWebSocket"

/**
 * Orchestrates a meeting session by composing four focused hooks:
 *
 *   1. useMeetingFetch         — REST: resolve the meeting code
 *   2. useMeetingMessages      — transcript / gloss feeds + non-fatal errors
 *   3. useMeetingAudioPlayer   — TTS playback (declared before WS)
 *   4. useWebSocket            — connection lifecycle + reconnect
 *   5. useMeetingAudioRecorder — mic capture (declared after WS)
 *
 * This hook is intentionally thin: its job is the meeting-state machine
 * (connecting → waiting → active → ended/error) and routing WS messages
 * to whichever sub-hook owns them.
 */
export function useMeeting(meetingCode: string) {
  // ── Meeting-record fetch ──
  const {
    meeting,
    meetingId,
    fetchError,
    alreadyEnded,
    retry: refetch,
  } = useMeetingFetch(meetingCode)

  // ── Top-level meeting state ──
  const [meetingState, setMeetingState] = useState<MeetingState>("connecting")
  const [role, setRole] = useState<"speaker" | "reader" | null>(null)
  const [userId, setUserId] = useState<string | null>(null)
  const [partnerJoined, setPartnerJoined] = useState(false)
  const [authError, setAuthError] = useState<string | null>(null)
  // True between `tts_start` and `tts_end` — drives the partner-speaking dot.
  const [isPartnerSpeaking, setIsPartnerSpeaking] = useState(false)
  // Latest English recognized from the reader's signing (Direction B echo).
  const [signText, setSignText] = useState<string | null>(null)

  // Apply fetch outcomes to the state machine.
  useEffect(() => {
    if (fetchError) {
      setMeetingState("error")
      setAuthError(fetchError)
    } else if (alreadyEnded) {
      setMeetingState("ended")
    }
  }, [fetchError, alreadyEnded])

  // Recover from the auth_ok-before-meeting-loaded race: if the WS finished
  // authenticating before the REST fetch resolved, we'd have dropped into
  // "waiting" even for a meeting whose status is already "active". Once the
  // record arrives, promote the state.
  useEffect(() => {
    if (meeting?.status === "active" && meetingState === "waiting") {
      setMeetingState("active")
    }
  }, [meeting, meetingState])

  // ── Message-list state (transcripts, glosses, non-fatal errors) ──
  const messages = useMeetingMessages(role)

  // ── Audio player (must be before useWebSocket — onBinaryMessage uses playAudio) ──
  const player = useMeetingAudioPlayer()

  // ── WS connection ──
  // `meeting` is read inside the auth_ok branch — keep it in a ref so the
  // callback identity stays stable across re-renders (avoids re-arming the
  // WS effect just because the meeting record just arrived).
  const meetingRef = useRef(meeting)
  meetingRef.current = meeting

  const handleMessage = useCallback(
    (msg: WsServerMessage) => {
      // Try the message-list reducer first; if it doesn't handle the
      // event, fall through to the lifecycle/auth state machine.
      if (messages.apply(msg)) return

      switch (msg.type) {
        case "auth_ok":
          setRole(msg.role)
          setUserId(msg.user_id)
          if (meetingRef.current?.status === "active") {
            setMeetingState("active")
            setPartnerJoined(true)
          } else {
            setMeetingState("waiting")
          }
          break

        case "auth_error":
          setMeetingState("error")
          setAuthError(msg.message)
          break

        case "user_joined":
          setPartnerJoined(true)
          setMeetingState("active")
          break

        case "user_left":
          setPartnerJoined(false)
          break

        case "meeting_ended":
          setMeetingState("ended")
          break

        case "tts_start":
          setIsPartnerSpeaking(true)
          break

        case "tts_end":
          setIsPartnerSpeaking(false)
          break

        case "sign_text":
          setSignText(msg.content)
          break
      }
    },
    [messages.apply],
  )

  const handleDisconnect = useCallback(() => {
    // Read latest state via setter without producing side effects inside
    // the updater — React 19 strict mode runs updaters twice in dev.
    setMeetingState((prev) => (prev === "ended" ? prev : "error"))
    setAuthError((prev) => prev ?? "Disconnected from meeting")
  }, [])

  const wsEnabled = !!meetingId && meetingState !== "ended"

  const {
    sendJson,
    sendBinary,
    state: wsState,
    retry: retryWs,
  } = useWebSocket({
    meetingId: meetingId || "",
    onMessage: handleMessage,
    onBinaryMessage: player.playAudio,
    onDisconnect: handleDisconnect,
    enabled: wsEnabled,
  })

  // Reflect WS-level transitions into the meeting state machine. A socket
  // that is re-authenticating or reconnecting does NOT mean the meeting
  // left "active" — only the transport hiccupped. Keep an already-active
  // meeting on screen so ReaderView/CwasaAvatar stays mounted instead of
  // being destroyed and re-initialised on every brief reconnect; the
  // reconnect runs in the background, and a genuinely exhausted reconnect
  // still surfaces via onDisconnect → "error".
  useEffect(() => {
    if (wsState === "authenticating") {
      setMeetingState((prev) => (prev === "active" ? prev : "authenticating"))
    } else if (wsState === "reconnecting") {
      setMeetingState((prev) => (prev === "active" ? prev : "connecting"))
    }
  }, [wsState])

  // ── Audio recorder (depends on the WebSocket's send fns) ──
  const recorder = useMeetingAudioRecorder({
    role,
    isActive: meetingState === "active",
    isTerminated: meetingState === "ended" || meetingState === "error",
    sendBinary,
    sendJson,
    unlockAudio: player.unlockAudio,
    stopAudio: player.stopAudio,
  })

  // ── Actions ──
  const sendTextMessage = useCallback(
    (content: string) => {
      const trimmed = content.trim()
      if (trimmed) sendJson({ type: "text_message", content: trimmed })
    },
    [sendJson],
  )

  const sendGlossMessage = useCallback(
    (content: string) => {
      // GlossInput already uppercases on each keystroke — trust the caller
      // to deliver normalised gloss tokens here.
      const trimmed = content.trim()
      if (trimmed) sendJson({ type: "gloss_message", content: trimmed })
    },
    [sendJson],
  )

  // ── Direction B: gloss-free sign capture ──
  const sendKeypointFrame = useCallback(
    (frame: ArrayBuffer) => {
      sendBinary(frame)
    },
    [sendBinary],
  )

  const sendSignSegmentEnd = useCallback(() => {
    sendJson({ type: "control", action: "sign_segment_end" })
  }, [sendJson])

  const endMeeting = useCallback(() => {
    sendJson({ type: "end_meeting" })
    setMeetingState("ended")
    recorder.stopAll()
  }, [sendJson, recorder])

  // Re-fetch the meeting record + force the WS effect to re-arm.
  const retry = useCallback(() => {
    setAuthError(null)
    setMeetingState("connecting")
    refetch()
    retryWs()
  }, [refetch, retryWs])

  return {
    meetingState,
    meeting,
    role,
    userId,
    transcript: messages.transcript,
    glosses: messages.glosses,
    partnerJoined,
    error: authError ?? messages.error,
    sendTextMessage,
    sendGlossMessage,
    sendKeypointFrame,
    sendSignSegmentEnd,
    signText,
    endMeeting,
    toggleMic: recorder.toggleMic,
    isMicOn: recorder.isMicOn,
    isSpeaking: recorder.isSpeaking,
    isPartnerSpeaking,
    micError: recorder.micError,
    unlockAudio: player.unlockAudio,
    hasPendingAudio: player.hasPendingAudio,
    retry,
  }
}
