/**
 * Tiny logging shim — single seam to wire Sentry / PostHog / etc. later.
 *
 * Today this just delegates to `console`. The point is that fault-path
 * code throughout the app calls `logError(...)` instead of
 * `console.error(...)`, so swapping in a real error tracker is a
 * one-file change rather than a grep-and-replace through the codebase.
 */

type LogContext = Record<string, unknown>

export function logError(message: string, context?: LogContext): void {
  console.error(message, context ?? "")
}

export function logWarn(message: string, context?: LogContext): void {
  console.warn(message, context ?? "")
}

/** Use for high-frequency / per-frame logs that should be silent in prod. */
export function logDebug(message: string, context?: LogContext): void {
  if (import.meta.env.DEV) {
    console.log(message, context ?? "")
  }
}
