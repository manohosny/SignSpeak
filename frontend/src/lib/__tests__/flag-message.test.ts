import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { flagMessage } from "../flag-message"

describe("flagMessage", () => {
  beforeEach(() => {
    vi.stubEnv("VITE_API_URL", "http://api.test")
  })

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.restoreAllMocks()
  })

  it("POSTs the flag with the cookie session and a null reason by default", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 200 }))

    expect(await flagMessage("meet-1", "msg-1")).toBe(true)
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://api.test/api/v1/meetings/meet-1/messages/msg-1/flag",
      expect.objectContaining({
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reason: null }),
      }),
    )
  })

  it("forwards an explicit reason in the body", async () => {
    const fetchSpy = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response("", { status: 200 }))

    await flagMessage("meet-1", "msg-1", "wrong word order")
    expect(fetchSpy).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        body: JSON.stringify({ reason: "wrong word order" }),
      }),
    )
  })

  it("returns false and warns on a non-2xx response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValueOnce(
      new Response("", { status: 403 }),
    )
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})

    expect(await flagMessage("meet-1", "msg-1")).toBe(false)
    expect(warnSpy).toHaveBeenCalled()
  })

  it("returns false and warns on a network failure", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValueOnce(new Error("net"))
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {})

    expect(await flagMessage("meet-1", "msg-1")).toBe(false)
    expect(warnSpy).toHaveBeenCalled()
  })
})
