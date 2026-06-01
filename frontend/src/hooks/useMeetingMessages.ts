import { useCallback, useRef, useState } from "react"

import type {
  GlossEntry,
  TranscriptEntry,
  WsServerMessage,
} from "@/lib/meeting-types"

type Role = "speaker" | "reader" | null

interface UseMeetingMessagesResult {
  transcript: TranscriptEntry[]
  glosses: GlossEntry[]
  /** Non-fatal `error` / `gloss_error` payloads surface here. */
  error: string | null
  clearError: () => void
  /**
   * Apply a server message to the message-list state.
   * Returns true if the message was handled, false otherwise — callers
   * can use this to decide whether to dispatch the message elsewhere.
   */
  apply: (msg: WsServerMessage) => boolean
}

/**
 * Owns the meeting's transcript + gloss feeds plus non-fatal error toasts.
 *
 * Pure reducer over WS message events — no side effects, no audio, no
 * connection state. Pulled out of `useMeeting` so that the message-list
 * logic can be unit-tested independently of the WS lifecycle.
 */
export function useMeetingMessages(role: Role): UseMeetingMessagesResult {
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([])
  const [glosses, setGlosses] = useState<GlossEntry[]>([])
  const [error, setError] = useState<string | null>(null)

  // Avoid re-creating `apply` on every role change.
  const roleRef = useRef(role)
  roleRef.current = role

  const apply = useCallback((msg: WsServerMessage): boolean => {
    switch (msg.type) {
      case "transcript": {
        const entryId = msg.utterance_id || `t-${Date.now()}-${Math.random()}`
        setTranscript((prev) => {
          if (msg.utterance_id) {
            const idx = prev.findIndex((e) => e.id === entryId)
            if (idx !== -1) {
              const updated = [...prev]
              updated[idx] = {
                ...updated[idx],
                content: msg.text,
                timestamp: msg.timestamp,
                isPartial: msg.is_partial,
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
              isPartial: msg.is_partial,
            },
          ]
        })
        return true
      }

      case "text_message": {
        // Defensive guard: the protocol forbids text_message before
        // `auth_ok`, but if the server ever does, we'd misattribute the
        // sender by negating a null role. Drop the message in that case
        // rather than fabricate a role.
        const localRole = roleRef.current
        if (localRole === null) return true
        setTranscript((prev) => [
          ...prev,
          {
            id: `m-${Date.now()}-${Math.random()}`,
            type: "text_message",
            content: msg.content,
            senderId: msg.sender_id,
            senderRole: localRole === "speaker" ? "reader" : "speaker",
            timestamp: msg.timestamp,
          },
        ])
        return true
      }

      case "gloss":
        setGlosses((prev) => [
          ...prev,
          {
            id: msg.utterance_id || `g-${Date.now()}-${Math.random()}`,
            type: "gloss",
            text: msg.text,
            utterance_id: msg.utterance_id,
            timestamp: msg.timestamp,
            isOwn: false,
          },
        ])
        return true

      case "gloss_message":
        setGlosses((prev) => [
          ...prev,
          {
            id: `gm-${Date.now()}-${Math.random()}`,
            type: "gloss_message",
            text: msg.content,
            timestamp: msg.timestamp,
            isOwn: true,
          },
        ])
        return true

      case "error":
      case "gloss_error":
        setError(msg.message)
        return true

      default:
        return false
    }
  }, [])

  const clearError = useCallback(() => setError(null), [])

  return { transcript, glosses, error, clearError, apply }
}
