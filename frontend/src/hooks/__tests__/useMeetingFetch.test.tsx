import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { renderHook, waitFor } from "@testing-library/react"
import type { ReactNode } from "react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useMeetingFetch } from "../useMeetingFetch"

// Mock the generated SDK so we can drive responses deterministically.
vi.mock("@/client", async () => {
  const actual = await vi.importActual<typeof import("@/client")>("@/client")
  return {
    ...actual,
    MeetingsService: {
      joinMeeting: vi.fn(),
      getMeeting: vi.fn(),
    },
  }
})

import { MeetingsService } from "@/client"

function makeWrapper() {
  // retries off so failing tests fail fast.
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return function Wrapper({ children }: { children: ReactNode }) {
    return <QueryClientProvider client={client}>{children}</QueryClientProvider>
  }
}

const meeting = {
  id: "uuid-1",
  code: "ABCD",
  status: "active" as const,
  created_at: "2026-01-01T00:00:00Z",
  host_id: "u-1",
} as unknown as Awaited<ReturnType<typeof MeetingsService.joinMeeting>>

beforeEach(() => {
  vi.clearAllMocks()
})

afterEach(() => {
  vi.restoreAllMocks()
})

describe("useMeetingFetch", () => {
  it("resolves a meeting via joinMeeting on success", async () => {
    vi.mocked(MeetingsService.joinMeeting).mockResolvedValue(meeting)

    const { result } = renderHook(() => useMeetingFetch("ABCD"), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.meetingId).toBe("uuid-1")
    })
    expect(result.current.fetchError).toBeNull()
    expect(result.current.alreadyEnded).toBe(false)
    expect(MeetingsService.getMeeting).not.toHaveBeenCalled()
  })

  it("falls back to getMeeting when joinMeeting throws (host already joined)", async () => {
    vi.mocked(MeetingsService.joinMeeting).mockRejectedValue(
      Object.assign(new Error("already in meeting"), {
        body: { detail: "already in meeting" },
      }),
    )
    vi.mocked(MeetingsService.getMeeting).mockResolvedValue(meeting)

    const { result } = renderHook(() => useMeetingFetch("ABCD"), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.meetingId).toBe("uuid-1")
    })
    expect(MeetingsService.getMeeting).toHaveBeenCalledTimes(1)
  })

  it("surfaces the server-side detail when both calls fail", async () => {
    vi.mocked(MeetingsService.joinMeeting).mockRejectedValue(new Error("net"))
    vi.mocked(MeetingsService.getMeeting).mockRejectedValue(
      Object.assign(new Error("not found"), {
        body: { detail: "Meeting not found" },
      }),
    )

    const { result } = renderHook(() => useMeetingFetch("ABCD"), {
      wrapper: makeWrapper(),
    })

    await waitFor(
      () => {
        expect(result.current.fetchError).toBe("Meeting not found")
      },
      { timeout: 3000 },
    )
    expect(result.current.meetingId).toBeNull()
  })

  it("flags alreadyEnded when the meeting status is ended", async () => {
    vi.mocked(MeetingsService.joinMeeting).mockResolvedValue({
      ...meeting,
      status: "ended",
    } as never)

    const { result } = renderHook(() => useMeetingFetch("ABCD"), {
      wrapper: makeWrapper(),
    })

    await waitFor(() => {
      expect(result.current.alreadyEnded).toBe(true)
    })
  })

  it("does nothing when meetingCode is empty", () => {
    renderHook(() => useMeetingFetch(""), { wrapper: makeWrapper() })
    expect(MeetingsService.joinMeeting).not.toHaveBeenCalled()
  })
})
