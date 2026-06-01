import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import {
  clearLocalSession,
  hasSessionMarker,
  refreshTokens,
} from "../auth-tokens"

// `document.cookie` behaves like a setter that accumulates entries; for
// tests we need a mock that supports both `=` writes and Max-Age=0
// removals so `clearLocalSession` is observable.
function installCookieStub(initial: Record<string, string> = {}) {
  const jar = new Map<string, string>(Object.entries(initial))
  Object.defineProperty(document, "cookie", {
    configurable: true,
    get: () =>
      Array.from(jar.entries())
        .map(([k, v]) => `${k}=${v}`)
        .join("; "),
    set: (raw: string) => {
      const [pair] = raw.split(";", 1)
      const eq = pair.indexOf("=")
      const k = pair.slice(0, eq).trim()
      const v = pair.slice(eq + 1).trim()
      if (/max-age=0/i.test(raw) || v === "") {
        jar.delete(k)
      } else {
        jar.set(k, v)
      }
    },
  })
}

describe("auth-tokens (cookie session)", () => {
  beforeEach(() => {
    installCookieStub()
    vi.stubEnv("VITE_API_URL", "http://api.test")
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  describe("hasSessionMarker", () => {
    it("returns false when no marker cookie is set", () => {
      expect(hasSessionMarker()).toBe(false)
    })

    it("returns true only when the marker cookie equals '1'", () => {
      installCookieStub({ ss_session: "1" })
      expect(hasSessionMarker()).toBe(true)
    })

    it("returns false for any non-'1' marker value", () => {
      installCookieStub({ ss_session: "garbage" })
      expect(hasSessionMarker()).toBe(false)
    })
  })

  describe("clearLocalSession", () => {
    it("removes the marker cookie", () => {
      installCookieStub({ ss_session: "1" })
      clearLocalSession()
      expect(hasSessionMarker()).toBe(false)
    })
  })

  describe("refreshTokens", () => {
    it("returns true when /login/refresh returns 200", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("", { status: 200 }),
      )
      expect(await refreshTokens()).toBe(true)
    })

    it("returns false on a non-2xx response", async () => {
      vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
        new Response("", { status: 401 }),
      )
      expect(await refreshTokens()).toBe(false)
    })

    it("returns false on a network failure", async () => {
      vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("net"))
      expect(await refreshTokens()).toBe(false)
    })

    it("calls /login/refresh with credentials included", async () => {
      const fetchSpy = vi
        .spyOn(globalThis, "fetch")
        .mockResolvedValueOnce(new Response("", { status: 200 }))
      await refreshTokens()
      expect(fetchSpy).toHaveBeenCalledWith(
        "http://api.test/api/v1/login/refresh",
        expect.objectContaining({
          method: "POST",
          credentials: "include",
        }),
      )
    })
  })
})
