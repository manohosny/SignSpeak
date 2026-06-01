import { act, renderHook } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useAudioPlayer } from "../useAudioPlayer"

// ─────────────────────────────────────────────────────────────────────
// Minimal AudioContext + AudioBufferSourceNode doubles. We only need
// what the hook touches.
// ─────────────────────────────────────────────────────────────────────

class FakeBufferSource {
  buffer: unknown = null
  onended: (() => void) | null = null
  connected = false
  started = false
  connect() {
    this.connected = true
  }
  start() {
    this.started = true
  }
}

class FakeAudioContext {
  state: "suspended" | "running" | "closed" = "suspended"
  destination = {} as unknown
  static lastDecodedBytes: number | null = null
  static lastSource: FakeBufferSource | null = null

  resume() {
    this.state = "running"
    return Promise.resolve()
  }
  decodeAudioData(buf: ArrayBuffer) {
    FakeAudioContext.lastDecodedBytes = buf.byteLength
    return Promise.resolve({ duration: 0.1 } as unknown as AudioBuffer)
  }
  createBufferSource() {
    const src = new FakeBufferSource()
    FakeAudioContext.lastSource = src
    return src as unknown as AudioBufferSourceNode
  }
}

beforeEach(() => {
  vi.stubGlobal("AudioContext", FakeAudioContext)
  FakeAudioContext.lastDecodedBytes = null
  FakeAudioContext.lastSource = null
})

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("useAudioPlayer", () => {
  it("queues audio while suspended and reports hasPendingAudio", () => {
    const { result } = renderHook(() => useAudioPlayer())

    act(() => {
      result.current.playAudio(new ArrayBuffer(64))
    })
    expect(result.current.hasPendingAudio).toBe(true)
  })

  it("drains the queue once the AudioContext resumes", async () => {
    const { result } = renderHook(() => useAudioPlayer())

    act(() => {
      result.current.playAudio(new ArrayBuffer(64))
    })
    await act(async () => {
      result.current.unlockAudio()
      // Let the resume() promise resolve so playNext fires.
      await Promise.resolve()
      await Promise.resolve()
    })

    // decodeAudioData was called with the queued chunk.
    expect(FakeAudioContext.lastDecodedBytes).toBe(64)
    expect(FakeAudioContext.lastSource?.connected).toBe(true)
    expect(FakeAudioContext.lastSource?.started).toBe(true)
  })

  it("clears the queue on stopAudio", () => {
    const { result } = renderHook(() => useAudioPlayer())

    act(() => {
      result.current.playAudio(new ArrayBuffer(8))
      result.current.playAudio(new ArrayBuffer(8))
    })
    expect(result.current.hasPendingAudio).toBe(true)

    act(() => {
      result.current.stopAudio()
    })
    expect(result.current.hasPendingAudio).toBe(false)
  })
})
