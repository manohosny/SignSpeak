interface CwasaApi {
  init: (opts?: unknown) => void
  playSiGMLText: (sigml: string) => Promise<void> | void
  stopSiGML: () => void
  addHook: (
    event: string,
    fn: (evt: { msg: unknown; av: string }) => void,
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
    const existing = document.querySelector<HTMLScriptElement>(
      `script[src="${CWASA_JS_SRC}"]`,
    )
    if (existing) {
      existing.addEventListener("load", () => resolve())
      existing.addEventListener("error", () =>
        reject(new Error("Failed to load CWASA runtime")),
      )
      return
    }

    const script = document.createElement("script")
    script.src = CWASA_JS_SRC
    script.async = true
    script.addEventListener("load", () => {
      if (window.CWASA) {
        resolve()
      } else {
        reject(new Error("CWASA script loaded but window.CWASA missing"))
      }
    })
    script.addEventListener("error", () =>
      reject(new Error("Failed to load CWASA runtime")),
    )
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
  if (initialised) return
  getCwasa().init()
  initialised = true
}

export async function playSigml(sigml: string): Promise<void> {
  const result = getCwasa().playSiGMLText(sigml)
  if (result instanceof Promise) {
    await result
  }
}

export function stop(): void {
  try {
    getCwasa().stopSiGML()
  } catch {
    // stopSiGML throws if no animation is active — safe to ignore.
  }
}
