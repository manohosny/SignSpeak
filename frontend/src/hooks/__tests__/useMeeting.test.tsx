import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, renderHook } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import type { WsServerMessage } from "@/lib/meeting-types"

// ─────────────────────────────────────────────────────────────────────
// Mock all of useMeeting's collaborators so we can isolate the
// state-machine logic.
// ─────────────────────────────────────────────────────────────────────

let capturedOnMessage: ((msg: WsServerMessage) => void) | null = null
let capturedOnDisconnect: (() => void) | null = null
const wsRetry = vi.fn()
const fetchRetry = vi.fn()

vi.mock("../useMeetingFetch", () => ({
  useMeetingFetch: vi.fn(),
}))

vi.mock("../useMeetingMessages", () => ({
  useMeetingMessages: vi.fn(() => ({
    transcript: [],
    glosses: [],
    error: null,
    clearError: vi.fn(),
    apply: vi.fn(() => false),
  })),
}))

vi.mock("../useMeetingAudioIO", () => ({
  useMeetingAudioPlayer: vi.fn(() => ({
    playAudio: vi.fn(),
    stopAudio: vi.fn(),
    unlockAudio: vi.fn(),
    hasPendingAudio: false,
  })),
  useMeetingAudioRecorder: vi.fn(() => ({
    isMicOn: false,
    isSpeaking: false,
    micError: null,
    toggleMic: vi.fn(),
    stopAll: vi.fn(),
  })),
}))

vi.mock("../useWebSocket", () => ({
  useWebSocket: vi.fn(
    (opts: {
      onMessage: (m: WsServerMessage) => void
      onDisconnect: () => void
      enabled: boolean
    }) => {
      capturedOnMessage = opts.onMessage
      capturedOnDisconnect = opts.onDisconnect
      return {
        sendJson: vi.fn(),
        sendBinary: vi.fn(),
        // Mirror real-hook behaviour: when disabled, no connection happens.
        state: opts.enabled
          ? ("authenticating" as const)
          : ("disconnected" as const),
        error: null,
        retry: wsRetry,
      }
    },
  ),
}))

// No auth-tokens mock needed anymore — useMeeting no longer reads any
// token from JS land. The WS hook receives auth via the HttpOnly cookie
// at upgrade time, transparently to the orchestrator.

import { useMeeting } from "../useMeeting"
import { useMeetingFetch } from "../useMeetingFetch"

function makeWrapper() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const mockFetch = vi.mocked(useMeetingFetch)

beforeEach(() => {
  capturedOnMessage = null
  capturedOnDisconnect = null
  wsRetry.mockClear()
  fetchRetry.mockClear()
  mockFetch.mockReturnValue({
    meeting: { id: "uuid-1", status: "active", code: "ABCD" } as never,
    meetingId: "uuid-1",
    fetchError: null,
    alreadyEnded: false,
    retry: fetchRetry,
  })
})

afterEach(() => {
  vi.clearAllMocks()
})

describe("useMeeting state machine", () => {
  it("transitions to active on auth_ok when meeting.status is active", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnMessage?.({
        type: "auth_ok",
        user_id: "u-1",
        role: "speaker",
        meeting_id: "uuid-1",
      })
    })

    expect(result.current.role).toBe("speaker")
    expect(result.current.userId).toBe("u-1")
    expect(result.current.meetingState).toBe("active")
    expect(result.current.partnerJoined).toBe(true)
  })

  it("transitions to waiting on auth_ok when meeting.status is not active", () => {
    mockFetch.mockReturnValue({
      meeting: { id: "uuid-1", status: "pending", code: "ABCD" } as never,
      meetingId: "uuid-1",
      fetchError: null,
      alreadyEnded: false,
      retry: fetchRetry,
    })

    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnMessage?.({
        type: "auth_ok",
        user_id: "u-1",
        role: "speaker",
        meeting_id: "uuid-1",
      })
    })

    expect(result.current.meetingState).toBe("waiting")
    expect(result.current.partnerJoined).toBe(false)
  })

  it("toggles isPartnerSpeaking on tts_start / tts_end", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnMessage?.({ type: "tts_start" })
    })
    expect(result.current.isPartnerSpeaking).toBe(true)

    act(() => {
      capturedOnMessage?.({ type: "tts_end" })
    })
    expect(result.current.isPartnerSpeaking).toBe(false)
  })

  it("captures sign_text content plus optional confidence and message_id", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    // Partial echo from an older server: no confidence, no message_id.
    act(() => {
      capturedOnMessage?.({
        type: "sign_text",
        content: "hello …",
        sender_id: "u-2",
        timestamp: "2026-05-06T10:00:00.000Z",
      })
    })
    expect(result.current.signText).toEqual({
      content: "hello …",
      confidence: undefined,
      messageId: undefined,
    })

    // Finalized sentence from a newer server carries both fields.
    act(() => {
      capturedOnMessage?.({
        type: "sign_text",
        content: "hello world",
        sender_id: "u-2",
        timestamp: "2026-05-06T10:00:01.000Z",
        confidence: 0.42,
        message_id: "msg-1",
      })
    })
    expect(result.current.signText).toEqual({
      content: "hello world",
      confidence: 0.42,
      messageId: "msg-1",
    })
  })

  it("transitions to ended on meeting_ended", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnMessage?.({ type: "meeting_ended" })
    })
    expect(result.current.meetingState).toBe("ended")
  })

  it("transitions to error on auth_error and surfaces the message", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnMessage?.({ type: "auth_error", message: "bad token" })
    })
    expect(result.current.meetingState).toBe("error")
    expect(result.current.error).toBe("bad token")
  })

  it("retry() refetches the meeting record and re-arms the WS", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      result.current.retry()
    })

    expect(fetchRetry).toHaveBeenCalledTimes(1)
    expect(wsRetry).toHaveBeenCalledTimes(1)
    expect(result.current.meetingState).toBe("connecting")
  })

  it("on WS disconnect, transitions to error unless already ended", () => {
    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    act(() => {
      capturedOnDisconnect?.()
    })
    expect(result.current.meetingState).toBe("error")
    expect(result.current.error).toBe("Disconnected from meeting")
  })

  it("respects fetchError by entering error state", () => {
    mockFetch.mockReturnValue({
      meeting: null,
      meetingId: null,
      fetchError: "Meeting not found",
      alreadyEnded: false,
      retry: fetchRetry,
    })

    const { result } = renderHook(() => useMeeting("ABCD"), {
      wrapper: makeWrapper(),
    })

    expect(result.current.meetingState).toBe("error")
    expect(result.current.error).toBe("Meeting not found")
  })
})
