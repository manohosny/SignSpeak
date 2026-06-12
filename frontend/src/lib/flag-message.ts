/**
 * Flag a wrong sign-to-speech translation.
 *
 * POSTs to /api/v1/meetings/{meeting_id}/messages/{message_id}/flag. Auth
 * rides on the HttpOnly session cookie (`credentials: "include"`), same as
 * the rest of the app — see `auth-tokens.ts` for the cookie-session model.
 *
 * Uses raw fetch rather than the generated OpenAPI client: the endpoint is
 * being added server-side in parallel and isn't in the generated client yet.
 *
 * Returns true on a 2xx response. Failures are non-fatal — the reader's
 * meeting must never break because feedback capture hiccupped — so errors
 * are logged and reported as `false`.
 */

import { logWarn } from "./logger"

export async function flagMessage(
  meetingId: string,
  messageId: string,
  reason: string | null = null,
): Promise<boolean> {
  const apiUrl = import.meta.env.VITE_API_URL as string
  try {
    const r = await fetch(
      `${apiUrl}/api/v1/meetings/${meetingId}/messages/${messageId}/flag`,
      {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason }),
      },
    )
    if (!r.ok) {
      logWarn("Flagging translation failed", { status: r.status, messageId })
    }
    return r.ok
  } catch (err) {
    logWarn("Flagging translation failed", { err, messageId })
    return false
  }
}
