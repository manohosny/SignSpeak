// Hook events carry the event type, an optional payload, and the avatar index.
type CwasaHookEvent = { typ: string; msg: unknown; av: string | number }

interface CwasaApi {
  init: (opts?: unknown) => void
  // playSiGMLText schedules playback synchronously and returns a status
  // string — NOT a Promise that resolves on animation end. Completion is
  // reported via the `animidle` hook instead (see onAnimIdle).
  playSiGMLText: (sigml: string) => unknown
  stopSiGML: () => void
  addHook: (
    event: string,
    fn: (evt: CwasaHookEvent) => void,
    av?: number | "*",
  ) => void
}

declare global {
  interface Window {
    CWASA?: CwasaApi
  }
}

// We intentionally do NOT load /cwasa/cwa/cwasa.css. That stylesheet contains
// global rules (html/body/h-tag selectors) that override the SignSpeak theme.
// The avatar-canvas rules we actually need are inlined in src/index.css.
const CWASA_JS_SRC = "/cwasa/cwa/allcsa.js"

let loadPromise: Promise<void> | null = null
let initialised = false

export function loadCwasaRuntime(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("CWASA can only load in the browser"))
  }
  if (window.CWASA) {
    return Promise.resolve()
  }
  if (loadPromise) {
    return loadPromise
  }

  loadPromise = new Promise<void>((resolve, reject) => {
    // Attach load/error listeners that detach themselves once they fire, so a
    // mounted/unmounted avatar never accumulates stale listeners on the tag.
    const attach = (script: HTMLScriptElement) => {
      const cleanup = () => {
        script.removeEventListener("load", onLoad)
        script.removeEventListener("error", onError)
      }
      const onLoad = () => {
        cleanup()
        if (window.CWASA) {
          resolve()
        } else {
          reject(new Error("CWASA script loaded but window.CWASA missing"))
        }
      }
      const onError = () => {
        cleanup()
        reject(new Error("Failed to load CWASA runtime"))
      }
      script.addEventListener("load", onLoad)
      script.addEventListener("error", onError)
    }

    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${CWASA_JS_SRC}"]`,
    )
    if (existing) {
      attach(existing)
      return
    }

    const script = document.createElement("script")
    script.src = CWASA_JS_SRC
    script.async = true
    attach(script)
    document.head.appendChild(script)
  })

  return loadPromise
}

function getCwasa(): CwasaApi {
  const cw = window.CWASA
  if (!cw) {
    throw new Error("CWASA runtime not loaded. Call loadCwasaRuntime() first.")
  }
  return cw
}

export function initAvatar(): void {
  // CWASA exposes no clean teardown/re-init, so this stays true for the page
  // lifetime: a remounted avatar reuses the already-initialised runtime.
  if (initialised) return
  getCwasa().init()
  initialised = true
}

// Register a listener for the avatar finishing an animation. CWASA fires
// `animidle` exactly once per playSiGMLText call — including the
// no-valid-signs path — which makes it the queue's completion signal. CWASA
// has no public delHook, so callers register exactly once. Returns false if
// the runtime is not loaded yet.
export function onAnimIdle(fn: () => void): boolean {
  const cw = window.CWASA
  if (!cw) return false
  cw.addHook("animidle", () => fn(), "*")
  return true
}

export function playSigml(sigml: string): void {
  getCwasa().playSiGMLText(sigml)
}

export function stop(): void {
  try {
    getCwasa().stopSiGML()
  } catch {
    // stopSiGML throws if no animation is active — safe to ignore.
  }
}
