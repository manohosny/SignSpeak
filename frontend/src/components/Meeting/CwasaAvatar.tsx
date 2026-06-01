import { useEffect, useState } from "react"

import { initAvatar, loadCwasaRuntime } from "@/avatar/driver"
import { initAvatarQueue } from "@/avatar/queue"
import { logError } from "@/lib/logger"

interface CwasaAvatarProps {
  /**
   * The plain-text gloss currently being signed. Surfaced to assistive
   * technologies via an aria-live region, and shown as a visible fallback if
   * the avatar runtime fails to load.
   */
  glossText?: string | null
  width?: number
  height?: number
}

export function CwasaAvatar({
  glossText,
  width = 260,
  height = 320,
}: CwasaAvatarProps) {
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    loadCwasaRuntime()
      .then(() => {
        if (cancelled) return
        initAvatar()
        // Wire the animation queue once the runtime is live: it registers the
        // CWASA `animidle` completion hook and drains anything already queued.
        initAvatarQueue()
        setReady(true)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        logError("CWASA runtime failed to load", { err })
        setFailed(true)
      })
    return () => {
      cancelled = true
    }
  }, [])

  return (
    <div
      role="img"
      aria-label="Sign-language avatar"
      aria-busy={!ready && !failed}
      className="cwasa-tv overflow-hidden rounded-xl border border-white/20 bg-zinc-900/70 shadow-lg backdrop-blur-sm"
      style={{
        width,
        height,
        opacity: ready || failed ? 1 : 0,
        transition: "opacity 200ms ease-in",
      }}
    >
      {failed ? (
        // Runtime failed to load — keep the conversation flowing by showing
        // the gloss text instead of an avatar that will never appear.
        <div
          className="flex flex-col items-center justify-center gap-2 p-4 text-center"
          style={{ width, height }}
        >
          <span className="text-xs font-medium text-white/60">
            Avatar unavailable
          </span>
          {glossText ? (
            <span className="text-sm text-white/90">{glossText}</span>
          ) : null}
        </div>
      ) : (
        <div
          aria-hidden="true"
          className="CWASAPanel av0"
          style={{ width, height }}
        />
      )}
      <span aria-live="polite" aria-atomic="true" className="sr-only">
        {failed
          ? glossText
            ? `Avatar unavailable. Gloss: ${glossText}`
            : "Sign-language avatar unavailable"
          : ready
            ? glossText
              ? `Signing: ${glossText}`
              : "Avatar ready"
            : "Loading sign-language avatar"}
      </span>
    </div>
  )
}
