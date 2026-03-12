import { useCallback, useEffect, useRef, useState } from "react"
import type { MeetingPublic } from "@/client"
import { MeetingsService } from "@/client"
import type {
  MeetingState,
  TranscriptEntry,
  WsServerMessage,
} from "@/lib/meeting-types"
import { useAudioPlayer } from "./useAudioPlayer"
import { useAudioRecorder } from "./useAudioRecorder"
import { useWebSocket } from "./useWebSocket"

export function useMeeting(meetingCode: string) {
  // ── Core state ──
  const [meetingState, setMeetingState] = useState<MeetingState>("connecting")
  const [meeting, setMeeting] = useState<MeetingPublic | null>(null)
  const [role, setRole] = useState<"speaker" | "reader" | null>(null)
  const [userId, setUserId] = useState<string | null>(null)
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [partnerJoined, setPartnerJoined] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isMicOn, setIsMicOn] = useState(false)

  // Stable refs (used in callbacks without re-triggering effects)
  const roleRef = useRef(role)
  roleRef.current = role
  const meetingRef = useRef(meeting)
  meetingRef.current = meeting

  // ── Step 1: Fetch meeting by code → get UUID ──
  const [meetingId, setMeetingId] = useState<string | null>(null)
  const fetchedRef = useRef(false)

  useEffect(() => {
    if (!meetingCode || fetchedRef.current) return
    fetchedRef.current = true

    // Join the meeting first (creates participant record),
    // then use the returned meeting data to connect via WS.
    // joinMeeting is idempotent for the host (backend rejects
    // with 400 "already in meeting", so we fall back to GET).
    MeetingsService.joinMeeting({ code: meetingCode })
      .then((m) => {
        setMeeting(m)
        setMeetingId(m.id)
        if (m.status === "ended") {
          setMeetingState("ended")
        }
      })
      .catch(async () => {
        // Host is already a participant — joinMeeting returns 400.
        // Fall back to fetching the meeting details.
        try {
          const m = await MeetingsService.getMeeting({ code: meetingCode })
          setMeeting(m)
          setMeetingId(m.id)
          if (m.status === "ended") {
            setMeetingState("ended")
          }
        } catch (err: unknown) {
          setMeetingState("error")
          const detail =
            err && typeof err === "object" && "body" in err
              ? (err as { body?: { detail?: string } }).body?.detail
              : undefined
          setError(detail || "Meeting not found")
        }
      })
  }, [meetingCode])

  // ── WS message handler ──
  const handleMessage = useCallback((msg: WsServerMessage) => {
    switch (msg.type) {
      case "auth_ok":
        setRole(msg.role)
        setUserId(msg.user_id)
        // If the meeting is already active (partner joined via REST before
        // we connected WS), go straight to active instead of waiting.
        if (meetingRef.current?.status === "active") {
          setMeetingState("active")
          setPartnerJoined(true)
        } else {
          setMeetingState("waiting")
        }
        break

      case "auth_error":
        setMeetingState("error")
        setError(msg.message)
        break

      case "user_joined":
        setPartnerJoined(true)
        setMeetingState("active")
        break

      case "user_left":
        setPartnerJoined(false)
        break

      case "transcript": {
        const entryId = msg.utterance_id || `t-${Date.now()}-${Math.random()}`
        setTranscript((prev) => {
          // If this transcript has an utterance_id and a partial with the
          // same ID already exists, replace it instead of appending.
          if (msg.utterance_id) {
            const idx = prev.findIndex((e) => e.id === entryId)
            if (idx !== -1) {
              const updated = [...prev]
              updated[idx] = {
                ...updated[idx],
                content: msg.text,
                timestamp: msg.timestamp,
              }
              return updated
            }
          }
          return [
            ...prev,
            {
              id: entryId,
              type: "transcript",
              content: msg.text,
              senderId: msg.sender_id,
              senderRole: "speaker",
              timestamp: msg.timestamp,
            },
          ]
        })
        break
      }

      case "text_message":
        setTranscript((prev) => [
          ...prev,
          {
            id: `m-${Date.now()}-${Math.random()}`,
            type: "text_message",
            content: msg.content,
            senderId: msg.sender_id,
            senderRole: roleRef.current === "speaker" ? "reader" : "speaker",
            timestamp: msg.timestamp,
          },
        ])
        break

      case "meeting_ended":
        setMeetingState("ended")
        break

      case "error":
        // Non-fatal: show error but don't change state
        setError(msg.message)
        break
    }
  }, [])

  // ── Audio player (Speaker receives TTS WAV) ──
  const { playAudio, stopAudio, unlockAudio } = useAudioPlayer()

  const handleBinaryMessage = useCallback(
    (data: ArrayBuffer) => {
      // Binary frames are WAV audio from TTS (sent to speaker)
      playAudio(data)
    },
    [playAudio],
  )

  const handleDisconnect = useCallback(() => {
    if (meetingState !== "ended") {
      setMeetingState("error")
      setError("Disconnected from meeting")
    }
  }, [meetingState])

  // ── Step 2: WebSocket connection ──
  const token = localStorage.getItem("access_token") || ""
  const wsEnabled = !!meetingId && meetingState !== "ended"

  const {
    sendJson,
    sendBinary,
    state: wsState,
  } = useWebSocket({
    meetingId: meetingId || "",
    token,
    onMessage: handleMessage,
    onBinaryMessage: handleBinaryMessage,
    onDisconnect: handleDisconnect,
    enabled: wsEnabled,
  })

  // Update meeting state based on WS connection state
  useEffect(() => {
    if (wsState === "authenticating") {
      setMeetingState("authenticating")
    }
  }, [wsState])

  // ── Audio recorder (Speaker sends PCM16 chunks) ──
  const handleAudioChunk = useCallback(
    (pcm16: ArrayBuffer) => {
      sendBinary(pcm16)
    },
    [sendBinary],
  )

  const handleVadChange = useCallback(
    (speaking: boolean) => {
      if (!speaking) {
        // Speaker stopped talking — tell the backend to flush STT buffer
        sendJson({ type: "control", action: "utterance_end" })
      }
    },
    [sendJson],
  )

  const { isRecording, isSpeaking, startRecording, stopRecording } =
    useAudioRecorder({
      onAudioChunk: handleAudioChunk,
      onVadChange: handleVadChange,
      enabled: role === "speaker" && meetingState === "active",
    })

  // ── Actions ──
  const sendTextMessage = useCallback(
    (content: string) => {
      if (content.trim()) {
        sendJson({ type: "text_message", content: content.trim() })
      }
    },
    [sendJson],
  )

  const endMeeting = useCallback(() => {
    sendJson({ type: "end_meeting" })
    setMeetingState("ended")
    stopRecording()
    stopAudio()
  }, [sendJson, stopRecording, stopAudio])

  const toggleMic = useCallback(() => {
    // Unlock AudioContext during this user gesture so TTS playback works
    unlockAudio()
    if (isRecording) {
      stopRecording()
      setIsMicOn(false)
    } else {
      startRecording()
      setIsMicOn(true)
    }
  }, [isRecording, startRecording, stopRecording, unlockAudio])

  // Auto-stop mic when meeting ends
  useEffect(() => {
    if (meetingState === "ended" || meetingState === "error") {
      stopRecording()
      stopAudio()
    }
  }, [meetingState, stopRecording, stopAudio])

  return {
    meetingState,
    meeting,
    role,
    userId,
    transcript,
    partnerJoined,
    error,
    sendTextMessage,
    endMeeting,
    toggleMic,
    isMicOn,
    isSpeaking,
    unlockAudio,
  }
}
