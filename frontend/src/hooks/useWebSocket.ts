import { useCallback, useEffect, useRef, useState } from "react"

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
  token: string
  onMessage: (msg: WsServerMessage) => void
  onBinaryMessage: (data: ArrayBuffer) => void
  onDisconnect: () => void
  enabled: boolean
}

const MAX_RETRIES = 5
const BASE_DELAY = 1000 // 1 second

export function useWebSocket({
  meetingId,
  token,
  onMessage,
  onBinaryMessage,
  onDisconnect,
  enabled,
}: UseWebSocketOptions) {
  const [state, setState] = useState<WsState>("disconnected")
  const [error, setError] = useState<string | null>(null)
  const wsRef = useRef<WebSocket | null>(null)
  const callbacksRef = useRef({ onMessage, onBinaryMessage, onDisconnect })

  // Keep callbacks fresh without re-triggering the effect
  callbacksRef.current = { onMessage, onBinaryMessage, onDisconnect }

  useEffect(() => {
    if (!enabled || !meetingId || !token) return

    const apiUrl = import.meta.env.VITE_API_URL as string
    const wsUrl = `${apiUrl.replace(/^http/, "ws")}/ws/${meetingId}`

    let retryCount = 0
    let retryTimeout: ReturnType<typeof setTimeout> | null = null
    let intentionalClose = false
    let authFailed = false

    function connect() {
      setState(retryCount === 0 ? "connecting" : "reconnecting")
      setError(null)

      const ws = new WebSocket(wsUrl)
      ws.binaryType = "arraybuffer"
      wsRef.current = ws

      ws.onopen = () => {
        retryCount = 0
        setState("authenticating")
        ws.send(JSON.stringify({ type: "auth", token }))
      }

      ws.onmessage = (event) => {
        if (typeof event.data === "string") {
          try {
            const msg = JSON.parse(event.data) as WsServerMessage
            if (msg.type === "auth_ok") {
              setState("authenticated")
            } else if (msg.type === "auth_error") {
              authFailed = true
              setState("error")
              setError(msg.message)
              return
            }
            callbacksRef.current.onMessage(msg)
          } catch {
            // Non-JSON text frame — ignore
          }
        } else {
          callbacksRef.current.onBinaryMessage(event.data as ArrayBuffer)
        }
      }

      ws.onerror = () => {
        // onerror is always followed by onclose — let onclose handle retry
      }

      ws.onclose = () => {
        if (intentionalClose || authFailed) return

        if (retryCount < MAX_RETRIES) {
          setState("reconnecting")
          const delay = Math.min(BASE_DELAY * 2 ** retryCount, 30000)
          console.log(
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
      if (retryTimeout) clearTimeout(retryTimeout)
      const ws = wsRef.current
      if (ws?.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "leave" }))
      }
      ws?.close()
      wsRef.current = null
    }
  }, [enabled, meetingId, token])

  const sendJson = useCallback((msg: WsClientMessage) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg))
    }
  }, [])

  const sendBinary = useCallback((data: ArrayBuffer) => {
    const ws = wsRef.current
    if (ws?.readyState === WebSocket.OPEN) {
      ws.send(data)
    }
  }, [])

  return { sendJson, sendBinary, state, error }
}
