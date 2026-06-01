import { useQuery } from "@tanstack/react-query"

import type { MeetingPublic } from "@/client"
import { type ApiError, MeetingsService } from "@/client"

interface UseMeetingFetchResult {
  meeting: MeetingPublic | null
  meetingId: string | null
  /** Set if the meeting record itself couldn't be loaded. */
  fetchError: string | null
  /** True once the meeting record was loaded with status === "ended". */
  alreadyEnded: boolean
  /** Re-run the fetch — exposed so the route can offer a Retry CTA. */
  retry: () => void
}

/**
 * Resolves a meeting code into a meeting record + UUID.
 *
 * Tries `joinMeeting` first (creates the participant if needed). Falls
 * back to `getMeeting` for hosts who are already participants — the
 * backend rejects re-joins with a 400 ("already in meeting"), so this
 * is the documented two-step.
 *
 * Wrapped in `useQuery` so transient network failures retry automatically
 * and so changing the URL `code` param re-fetches without remounting.
 */
export function useMeetingFetch(meetingCode: string): UseMeetingFetchResult {
  const query = useQuery<MeetingPublic, ApiError | Error>({
    queryKey: ["meeting", meetingCode],
    queryFn: async () => {
      try {
        return await MeetingsService.joinMeeting({ code: meetingCode })
      } catch {
        // Hosts already in the meeting get rejected with 400 — fall back
        // to the read-only endpoint. Any other failure bubbles.
        return await MeetingsService.getMeeting({ code: meetingCode })
      }
    },
    enabled: Boolean(meetingCode),
    // We only need it once — let the WebSocket drive subsequent state.
    staleTime: Number.POSITIVE_INFINITY,
    retry: 1,
  })

  const meeting = query.data ?? null
  const fetchError = query.isError
    ? (extractDetail(query.error) ?? "Meeting not found")
    : null

  return {
    meeting,
    meetingId: meeting?.id ?? null,
    fetchError,
    alreadyEnded: meeting?.status === "ended",
    retry: () => {
      query.refetch()
    },
  }
}

function extractDetail(err: unknown): string | null {
  if (err && typeof err === "object" && "body" in err) {
    const body = (err as { body?: { detail?: string } }).body
    if (body?.detail) return body.detail
  }
  return null
}
