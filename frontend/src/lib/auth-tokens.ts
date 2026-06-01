/**
 * Auth-session helpers.
 *
 * Tokens themselves live in HttpOnly cookies set by the backend (see
 * `backend/app/core/security.py: set_auth_cookies`). JS can't read them
 * — that's the whole point of HttpOnly. The backend also sets a small
 * non-HttpOnly `ss_session` marker cookie containing just `"1"`, which
 * lets the FE answer "is this user logged in?" synchronously without
 * exposing the access token.
 *
 * Because tokens never enter JS land:
 * - There is no `getAccessToken` / `getRefreshToken` anymore — the
 *   browser sends them automatically on requests with `withCredentials`.
 * - `refreshTokens()` is just a fetch call to /login/refresh; the new
 *   token pair lands as cookies in the response.
 * - `clearLocalSession()` is best-effort: server-side revocation runs
 *   on /logout, this just nudges any local UI state.
 */

const SESSION_MARKER_COOKIE = "ss_session"

/**
 * Read a cookie value by name. Returns null if absent.
 *
 * Implemented by hand instead of pulling in a dependency — there are
 * exactly two callers and the cookie shape is stable.
 */
function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null
  const prefix = `${name}=`
  for (const part of document.cookie.split(";")) {
    const trimmed = part.trim()
    if (trimmed.startsWith(prefix)) {
      return decodeURIComponent(trimmed.slice(prefix.length))
    }
  }
  return null
}

/**
 * Synchronous "does this browser believe it has a session?" check.
 * Used by `beforeLoad` route guards before the user-fetch settles.
 *
 * The marker cookie contains no payload; an attacker who steals it via
 * XSS gets the string `"1"` — useless without the HttpOnly access token
 * alongside.
 */
export function hasSessionMarker(): boolean {
  return readCookie(SESSION_MARKER_COOKIE) === "1"
}

/**
 * Manually clear the session marker cookie. Server-side revocation
 * happens via the /logout endpoint; this is just a best-effort local
 * cleanup so the UI updates immediately.
 *
 * The HttpOnly cookies (`ss_access`, `ss_refresh`) cannot be touched
 * from JS — only the server can clear them via Set-Cookie headers.
 */
export function clearLocalSession(): void {
  if (typeof document === "undefined") return
  // The modern Cookie Store API would be cleaner, but it isn't shipped
  // in Firefox or Safari yet, and we only need to clear a single non-
  // HttpOnly marker — the legacy `document.cookie` setter is fine here.
  // biome-ignore lint/suspicious/noDocumentCookie: see comment above
  document.cookie = `${SESSION_MARKER_COOKIE}=; Max-Age=0; Path=/`
}

/**
 * Trigger a refresh-token rotation. The browser sends the HttpOnly
 * refresh-token cookie automatically; the response sets new cookies.
 *
 * Returns true if rotation succeeded; false otherwise (caller should
 * log out the user and redirect).
 *
 * Uses raw fetch — calling the generated OpenAPI client here would
 * recurse through the same global error handler that called us.
 */
export async function refreshTokens(): Promise<boolean> {
  const apiUrl = import.meta.env.VITE_API_URL as string
  try {
    const r = await fetch(`${apiUrl}/api/v1/login/refresh`, {
      method: "POST",
      // No body needed — the refresh token rides on the cookie.
      credentials: "include",
    })
    return r.ok
  } catch {
    return false
  }
}
