import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useWebSocket } from "../useWebSocket"

// ─────────────────────────────────────────────────────────────────────
// Minimal WebSocket double — we drive the lifecycle by calling
// `lastSocket.simulateOpen()` etc. from the test.
// ─────────────────────────────────────────────────────────────────────

interface FakeSocket {
  url: string
  readyState: number
  binaryType: string
  onopen: ((this: FakeSocket) => void) | null
  onmessage:
    | ((this: FakeSocket, ev: { data: string | ArrayBuffer }) => void)
    | null
  onclose: ((this: FakeSocket) => void) | null
  onerror: ((this: FakeSocket) => void) | null
  sent: Array<string | ArrayBuffer>
  send: (data: string | ArrayBuffer) => void
  close: () => void
  simulateOpen: () => void
  simulateMessage: (data: string | ArrayBuffer) => void
  simulateClose: () => void
}

const sockets: FakeSocket[] = []

function makeFakeWebSocket() {
  return class FakeWS {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSING = 2
    static CLOSED = 3

    url: string
    readyState = 0
    binaryType = ""
    onopen: FakeSocket["onopen"] = null
    onmessage: FakeSocket["onmessage"] = null
    onclose: FakeSocket["onclose"] = null
    onerror: FakeSocket["onerror"] = null
    sent: Array<string | ArrayBuffer> = []

    constructor(url: string) {
      this.url = url
      sockets.push(this as unknown as FakeSocket)
    }

    send(data: string | ArrayBuffer) {
      this.sent.push(data)
    }

    close() {
      this.readyState = 3
      this.onclose?.call(this as unknown as FakeSocket)
    }

    simulateOpen() {
      this.readyState = 1
      this.onopen?.call(this as unknown as FakeSocket)
    }

    simulateMessage(data: string | ArrayBuffer) {
      this.onmessage?.call(this as unknown as FakeSocket, { data })
    }

    simulateClose() {
      this.readyState = 3
      this.onclose?.call(this as unknown as FakeSocket)
    }
  }
}

const noop = () => {}

const baseOptions = {
  meetingId: "m-1",
  onMessage: noop,
  onBinaryMessage: noop,
  onDisconnect: noop,
  enabled: true,
}

beforeEach(() => {
  sockets.length = 0
  vi.stubGlobal("WebSocket", makeFakeWebSocket())
  vi.stubEnv("VITE_API_URL", "http://api.test")
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
})

describe("useWebSocket", () => {
  it("connects with no token in the URL and reaches authenticated", () => {
    const onMessage = vi.fn()
    const { result } = renderHook(() =>
      useWebSocket({ ...baseOptions, onMessage }),
    )

    expect(sockets).toHaveLength(1)
    // Auth rides on the HttpOnly cookie — the URL must not leak the JWT.
    expect(sockets[0].url).toBe("ws://api.test/ws/m-1")
    expect(sockets[0].binaryType).toBe("arraybuffer")
    expect(result.current.state).toBe("connecting")

    act(() => {
      sockets[0].simulateOpen()
    })
    expect(result.current.state).toBe("authenticating")

    act(() => {
      sockets[0].simulateMessage(
        JSON.stringify({
          type: "auth_ok",
          user_id: "u-1",
          role: "speaker",
          meeting_id: "m-1",
        }),
      )
    })
    expect(result.current.state).toBe("authenticated")
    expect(onMessage).toHaveBeenCalledTimes(1)
  })

  it("closes the socket if auth_ok doesn't arrive within AUTH_TIMEOUT_MS", () => {
    const { result } = renderHook(() => useWebSocket(baseOptions))

    act(() => {
      sockets[0].simulateOpen()
    })
    expect(result.current.state).toBe("authenticating")

    // 8 seconds is the documented timeout; advance just past it.
    act(() => {
      vi.advanceTimersByTime(8001)
    })

    // Timeout fired → close → reconnect path takes over.
    expect(sockets[0].readyState).toBe(3)
  })

  it("backs off exponentially on close and stops after MAX_RETRIES", () => {
    const onDisconnect = vi.fn()
    renderHook(() => useWebSocket({ ...baseOptions, onDisconnect }))

    // Drive 5 close → reconnect cycles. Delay schedule: 1000, 2000, 4000, 8000, 16000.
    const delays = [1000, 2000, 4000, 8000, 16000]
    for (const delay of delays) {
      act(() => {
        sockets[sockets.length - 1].simulateClose()
      })
      act(() => {
        vi.advanceTimersByTime(delay)
      })
    }

    // 1 initial + 5 retries = 6 sockets total.
    expect(sockets).toHaveLength(6)

    // The 6th socket also closes — exhausts the budget.
    act(() => {
      sockets[5].simulateClose()
    })
    expect(onDisconnect).toHaveBeenCalledTimes(1)
  })

  it("ignores messages that don't match the schema", () => {
    const onMessage = vi.fn()
    renderHook(() => useWebSocket({ ...baseOptions, onMessage }))

    act(() => {
      sockets[0].simulateOpen()
    })

    act(() => {
      sockets[0].simulateMessage(JSON.stringify({ type: "totally_unknown" }))
    })
    expect(onMessage).not.toHaveBeenCalled()

    act(() => {
      sockets[0].simulateMessage("not-json{{{")
    })
    expect(onMessage).not.toHaveBeenCalled()
  })

  it("dispatches binary frames to onBinaryMessage", () => {
    const onBinaryMessage = vi.fn()
    renderHook(() => useWebSocket({ ...baseOptions, onBinaryMessage }))

    act(() => {
      sockets[0].simulateOpen()
    })
    const buf = new ArrayBuffer(8)
    act(() => {
      sockets[0].simulateMessage(buf)
    })
    expect(onBinaryMessage).toHaveBeenCalledWith(buf)
  })

  it("retry() re-arms the connection effect", () => {
    const { result } = renderHook(() => useWebSocket(baseOptions))

    expect(sockets).toHaveLength(1)
    act(() => {
      result.current.retry()
    })
    expect(sockets).toHaveLength(2)
  })

  it("does not connect when disabled", () => {
    renderHook(() => useWebSocket({ ...baseOptions, enabled: false }))
    expect(sockets).toHaveLength(0)
  })
})
