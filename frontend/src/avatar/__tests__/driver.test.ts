import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// A stand-in for the CWASA runtime. `_fire` replays a hook event the way the
// real runtime would dispatch it.
function makeCwasa() {
  const hooks: Record<string, ((evt: unknown) => void)[]> = {}
  return {
    init: vi.fn(),
    playSiGMLText: vi.fn(() => "Played SiGML for avatar 0"),
    stopSiGML: vi.fn(),
    addHook: vi.fn((event: string, fn: (evt: unknown) => void) => {
      const list = hooks[event] ?? []
      hooks[event] = list
      list.push(fn)
    }),
    _fire: (event: string) => {
      for (const fn of hooks[event] ?? []) fn({ typ: event, msg: null, av: 0 })
    },
  }
}

function installCwasa(cwasa: unknown): void {
  window.CWASA = cwasa as Window["CWASA"]
}

beforeEach(() => {
  // Fresh module state per test (driver keeps a module-level `initialised`).
  vi.resetModules()
})

afterEach(() => {
  window.CWASA = undefined
})

describe("driver", () => {
  it("loadCwasaRuntime resolves immediately when CWASA is already present", async () => {
    installCwasa(makeCwasa())
    const { loadCwasaRuntime } = await import("../driver")
    await expect(loadCwasaRuntime()).resolves.toBeUndefined()
  })

  it("initAvatar initialises the runtime only once", async () => {
    const cwasa = makeCwasa()
    installCwasa(cwasa)
    const { initAvatar } = await import("../driver")
    initAvatar()
    initAvatar()
    expect(cwasa.init).toHaveBeenCalledTimes(1)
  })

  it("playSigml hands the SiGML document to CWASA", async () => {
    const cwasa = makeCwasa()
    installCwasa(cwasa)
    const { playSigml } = await import("../driver")
    playSigml("<sigml><hns_sign/></sigml>")
    expect(cwasa.playSiGMLText).toHaveBeenCalledWith(
      "<sigml><hns_sign/></sigml>",
    )
  })

  it("onAnimIdle registers an animidle hook and forwards completion", async () => {
    const cwasa = makeCwasa()
    installCwasa(cwasa)
    const { onAnimIdle } = await import("../driver")

    const onIdle = vi.fn()
    expect(onAnimIdle(onIdle)).toBe(true)
    expect(cwasa.addHook).toHaveBeenCalledWith(
      "animidle",
      expect.any(Function),
      "*",
    )

    cwasa._fire("animidle")
    expect(onIdle).toHaveBeenCalledTimes(1)
  })

  it("onAnimIdle returns false when the runtime is not loaded", async () => {
    installCwasa(undefined)
    const { onAnimIdle } = await import("../driver")
    expect(onAnimIdle(vi.fn())).toBe(false)
  })

  it("stop swallows the error CWASA throws when nothing is playing", async () => {
    const cwasa = makeCwasa()
    cwasa.stopSiGML = vi.fn(() => {
      throw new Error("no animation active")
    })
    installCwasa(cwasa)
    const { stop } = await import("../driver")
    expect(() => stop()).not.toThrow()
  })
})
