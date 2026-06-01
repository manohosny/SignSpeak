import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { useAudioRecorder } from "../useAudioRecorder"

// ─────────────────────────────────────────────────────────────────────
// Minimal mocks for getUserMedia, AudioContext, AudioWorkletNode.
// ─────────────────────────────────────────────────────────────────────

const tracks: Array<{ stop: ReturnType<typeof vi.fn> }> = []

function fakeStream() {
  const t = { stop: vi.fn() }
  tracks.push(t)
  return {
    getTracks: () => [t],
  } as unknown as MediaStream
}

class FakeAudioWorkletNode {
  port = { onmessage: null as ((ev: MessageEvent) => void) | null }
  connect = vi.fn()
}

class FakeAudioContext {
  closed = false
  audioWorklet = { addModule: vi.fn().mockResolvedValue(undefined) }
  destination = {} as unknown
  createMediaStreamSource = vi.fn().mockReturnValue({ connect: vi.fn() })
  close = vi.fn(() => {
    this.closed = true
    return Promise.resolve()
  })
}

const getUserMedia = vi.fn()

beforeEach(() => {
  tracks.length = 0
  getUserMedia.mockReset()
  vi.stubGlobal("AudioContext", FakeAudioContext)
  vi.stubGlobal("AudioWorkletNode", FakeAudioWorkletNode)
  Object.defineProperty(globalThis.navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("useAudioRecorder", () => {
  it("starts recording when getUserMedia resolves", async () => {
    getUserMedia.mockResolvedValue(fakeStream())

    const onAudioChunk = vi.fn()
    const { result } = renderHook(() =>
      useAudioRecorder({ onAudioChunk, enabled: true }),
    )

    await act(async () => {
      await result.current.startRecording()
    })

    expect(result.current.isRecording).toBe(true)
    expect(getUserMedia).toHaveBeenCalledWith({
      audio: expect.objectContaining({ sampleRate: 16000, channelCount: 1 }),
    })
  })

  it("surfaces a friendly error when permission is denied", async () => {
    getUserMedia.mockRejectedValue(
      Object.assign(new Error("denied"), {
        name: "NotAllowedError",
        constructor: DOMException,
      }),
    )
    // jsdom supplies DOMException; ensure instanceof check passes.
    const denial = new (
      globalThis as { DOMException: typeof DOMException }
    ).DOMException("denied", "NotAllowedError")
    getUserMedia.mockRejectedValue(denial)

    const { result } = renderHook(() =>
      useAudioRecorder({ onAudioChunk: vi.fn(), enabled: true }),
    )

    await act(async () => {
      await result.current.startRecording()
    })

    await waitFor(() => {
      expect(result.current.error).toBe("Microphone permission denied")
    })
    expect(result.current.isRecording).toBe(false)
  })

  it("stops tracks and closes the AudioContext on stopRecording", async () => {
    getUserMedia.mockResolvedValue(fakeStream())

    const { result } = renderHook(() =>
      useAudioRecorder({ onAudioChunk: vi.fn(), enabled: true }),
    )

    await act(async () => {
      await result.current.startRecording()
    })

    act(() => {
      result.current.stopRecording()
    })

    expect(result.current.isRecording).toBe(false)
    expect(tracks[0].stop).toHaveBeenCalled()
  })

  it("is a no-op when enabled=false", async () => {
    const { result } = renderHook(() =>
      useAudioRecorder({ onAudioChunk: vi.fn(), enabled: false }),
    )

    await act(async () => {
      await result.current.startRecording()
    })
    expect(getUserMedia).not.toHaveBeenCalled()
    expect(result.current.isRecording).toBe(false)
  })
})
