import { useCallback, useEffect, useReducer, useRef, useState } from "react"

import { logDebug, logError, logWarn } from "@/lib/logger"
import { WsServerMessageSchema } from "@/lib/meeting-schemas"
import type { WsClientMessage, WsServerMessage } from "@/lib/meeting-types"

type WsState =
  | "connecting"
  | "authenticating"
  | "authenticated"
  | "reconnecting"
  | "disconnected"
  | "error"

interface UseWebSocketOptions {
  meetingId: string
  onMessage: (msg: WsServerMessage) => void
  onBinaryMessage: (data: ArrayBuffer) => void
  onDisconnect: () => void
  enabled: boolean
}

const MAX_RETRIES = 5
const BASE_DELAY = 1000 // 1 second
// How long the server has to send `auth_ok` after the upgrade completes
// before we treat the socket as stalled and close it. Picked to absorb
// realistic network jitter but bail out fast enough that the user isn't
// staring at a frozen "Connecting…" screen indefinitely.
const AUTH_TIMEOUT_MS = 8000

export function useWebSocket({
  meetingId,
  onMessage,
  onBinaryMessage,
  onDisconnect,
  enabled,
}: UseWebSocketOptions) {
  const [state, setState] = useState<WsState>("disconnected")
  const [error, setError] = useState<string | null>(null)
  // `retryAttempt` is bumped by the returned `retry()` to force the connect
  // effect to re-run after MAX_RETRIES exhaustion — used by the user-facing
  // "Reconnect" CTA. The value is read inside the effect so biome's
  // unused-variable check sees it.
  const [retryAttempt, retry] = useReducer((n: number) => n + 1, 0)
  const wsRef = useRef<WebSocket | null>(null)
  const callbacksRef = useRef({ onMessage, onBinaryMessage, onDisconnect })

  // Keep callbacks fresh without re-triggering the effect
  callbacksRef.current = { onMessage, onBinaryMessage, onDisconnect }

  useEffect(() => {
    if (!enabled || !meetingId) return

    const apiUrl = import.meta.env.VITE_API_URL as string
    // Auth rides on the HttpOnly access-token cookie — the browser sends
    // it on the WS upgrade request automatically (same-site rules apply,
    // and SameSite=Lax/Strict is fine because the upgrade is a GET).
    // The backend reads the cookie pre-accept, so the unauthenticated-
    // socket DoS surface stays closed without leaking the JWT into URLs.
    const wsUrl = `${apiUrl.replace(/^http/, "ws")}/ws/${meetingId}`

    let retryCount = 0
    let retryTimeout: ReturnType<typeof setTimeout> | null = null
    let authTimeout: ReturnType<typeof setTimeout> | null = null
    let intentionalClose = false
    let authFailed = false

    const clearAuthTimeout = () => {
      if (authTimeout) {
        clearTimeout(authTimeout)
        authTimeout = null
      }
    }

    function connect() {
      // Read retryAttempt so biome's noUnusedVariables sees it; the value
      // is informational only — actual retry budgeting uses `retryCount`.
      void retryAttempt
      setState(retryCount === 0 ? "connecting" : "reconnecting")
      setError(null)

      const ws = new WebSocket(wsUrl)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        // Auth rode on the cookie sent with the upgrade request. The
        // server validates pre-accept and replies with auth_ok. No
        // client-side auth message is required.
        setState("authenticating")
        // Guard against a hung server that accepted the upgrade but never
        // responds — close and let onclose drive the standard retry.
        authTimeout = setTimeout(() => {
          if (ws.readyState === WebSocket.OPEN) {
            logWarn(
              `[WebSocket] auth_ok not received within ${AUTH_TIMEOUT_MS}ms — closing`,
            )
            ws.close()
          }
        }, AUTH_TIMEOUT_MS)
      }

      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          let raw: unknown
          try {
            raw = JSON.parse(event.data)
          } catch {
            logWarn("[WebSocket] non-JSON text frame ignored")
            return
          }
          const parsed = WsServerMessageSchema.safeParse(raw)
          if (!parsed.success) {
            logError("[WebSocket] invalid server message — schema mismatch", {
              issues: parsed.error.issues,
              raw,
            })
            return
          }
          const msg: WsServerMessage = parsed.data
          if (msg.type === "auth_ok") {
            clearAuthTimeout()
            // Successful auth resets the retry budget for the next cycle.
            retryCount = 0
            setState("authenticated")
          } else if (msg.type === "auth_error") {
            clearAuthTimeout()
            authFailed = true
            setState("error")
            setError(msg.message)
            return
          } else if (msg.type === "server_shutdown") {
            // Server is rolling/restarting. Surface "reconnecting" early —
            // the server will close the socket shortly, and the existing
            // onclose path will retry through the standard backoff.
            logDebug(
              "[WebSocket] server_shutdown received, awaiting reconnect",
              {
                reason: msg.reason,
              },
            )
            setState("reconnecting")
            // Don't dispatch downstream — meeting state stays consistent.
            return
          }
          callbacksRef.current.onMessage(msg)
        } else {
          callbacksRef.current.onBinaryMessage(event.data as ArrayBuffer)
        }
      }

      ws.onerror = () => {
        // onerror is always followed by onclose — let onclose handle retry
      }

      ws.onclose = () => {
        clearAuthTimeout()
        if (intentionalClose || authFailed) return

        if (retryCount < MAX_RETRIES) {
          setState("reconnecting")
          const delay = Math.min(BASE_DELAY * 2 ** retryCount, 30000)
          logDebug(
            `[WebSocket] reconnecting in ${delay}ms (attempt ${retryCount + 1}/${MAX_RETRIES})`,
          )
          retryTimeout = setTimeout(() => {
            retryCount++
            connect()
          }, delay)
        } else {
          setState("error")
          setError("Connection lost — please refresh")
          callbacksRef.current.onDisconnect()
        }
      }
    }

    connect()

    return () => {
      intentionalClose = true
      clearAuthTimeout()
      if (retryTimeout) clearTimeout(retryTimeout)
      const ws = wsRef.current
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "leave" }))
      }
      ws?.close()
      wsRef.current = null
    }
  }, [enabled, meetingId, retryAttempt])

  // sendJson/sendBinary return whether the frame was actually sent. A frame
  // submitted while the socket is connecting/reconnecting cannot be queued
  // safely (ordering and staleness — stale audio is worse than dropped
  // audio), so it is dropped — but never silently: the drop is logged and
  // the boolean lets callers surface a "not sent" state to the user.
  const sendJson = useCallback((msg: WsClientMessage): boolean => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
      return true
    }
    logWarn("[WebSocket] sendJson dropped — socket not open", {
      type: msg.type,
    })
    return false
  }, [])

  const sendBinary = useCallback((data: ArrayBuffer): boolean => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(data)
      return true
    }
    // Audio is high-frequency; log at debug so a reconnect window does
    // not flood the console with one warning per dropped chunk.
    logDebug("[WebSocket] sendBinary dropped — socket not open")
    return false
  }, [])

  return { sendJson, sendBinary, state, error, retry }
}
