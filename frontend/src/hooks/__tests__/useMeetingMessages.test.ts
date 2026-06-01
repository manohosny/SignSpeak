import { act, renderHook } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import type { WsServerMessage } from "@/lib/meeting-types"

import { useMeetingMessages } from "../useMeetingMessages"

const T0 = "2026-05-07T10:00:00.000Z"

describe("useMeetingMessages", () => {
  it("appends a final transcript", () => {
    const { result } = renderHook(() => useMeetingMessages("speaker"))

    act(() => {
      const msg: WsServerMessage = {
        type: "transcript",
        text: "hello",
        is_partial: false,
        sender_id: "u1",
        timestamp: T0,
        utterance_id: "utt-1",
      }
      expect(result.current.apply(msg)).toBe(true)
    })

    expect(result.current.transcript).toHaveLength(1)
    expect(result.current.transcript[0]).toMatchObject({
      id: "utt-1",
      content: "hello",
      isPartial: false,
      senderRole: "speaker",
    })
  })

  it("replaces a partial transcript with the same utterance_id", () => {
    const { result } = renderHook(() => useMeetingMessages("speaker"))

    act(() => {
      result.current.apply({
        type: "transcript",
        text: "hel",
        is_partial: true,
        sender_id: "u1",
        timestamp: T0,
        utterance_id: "utt-9",
      })
    })
    act(() => {
      result.current.apply({
        type: "transcript",
        text: "hello",
        is_partial: false,
        sender_id: "u1",
        timestamp: T0,
        utterance_id: "utt-9",
      })
    })

    expect(result.current.transcript).toHaveLength(1)
    expect(result.current.transcript[0].content).toBe("hello")
    expect(result.current.transcript[0].isPartial).toBe(false)
  })

  it("derives the partner role on text_message based on local role", () => {
    const { result } = renderHook(() => useMeetingMessages("reader"))

    act(() => {
      result.current.apply({
        type: "text_message",
        content: "hi",
        sender_id: "u1",
        timestamp: T0,
      })
    })

    // Local user is reader → counterpart is speaker.
    expect(result.current.transcript[0].senderRole).toBe("speaker")
  })

  it("appends incoming glosses with isOwn=false", () => {
    const { result } = renderHook(() => useMeetingMessages("reader"))

    act(() => {
      result.current.apply({
        type: "gloss",
        text: "HELLO",
        sender_id: "u1",
        timestamp: T0,
        utterance_id: "g-1",
      })
    })

    expect(result.current.glosses).toHaveLength(1)
    expect(result.current.glosses[0]).toMatchObject({
      id: "g-1",
      text: "HELLO",
      isOwn: false,
    })
  })

  it("appends own glosses with isOwn=true on gloss_message", () => {
    const { result } = renderHook(() => useMeetingMessages("reader"))

    act(() => {
      result.current.apply({
        type: "gloss_message",
        content: "BYE",
        sender_id: "u1",
        timestamp: T0,
      })
    })

    expect(result.current.glosses).toHaveLength(1)
    expect(result.current.glosses[0]).toMatchObject({
      text: "BYE",
      isOwn: true,
    })
  })

  it("captures non-fatal error and gloss_error into the error field", () => {
    const { result } = renderHook(() => useMeetingMessages("reader"))

    act(() => {
      result.current.apply({ type: "error", message: "rate limit" })
    })
    expect(result.current.error).toBe("rate limit")

    act(() => {
      result.current.apply({
        type: "gloss_error",
        message: "translation failed",
      })
    })
    expect(result.current.error).toBe("translation failed")

    act(() => result.current.clearError())
    expect(result.current.error).toBe(null)
  })

  it("returns false for messages it doesn't own (lifecycle events)", () => {
    const { result } = renderHook(() => useMeetingMessages("speaker"))

    act(() => {
      // Lifecycle events go through the orchestrator, not the message list.
      const handled = result.current.apply({
        type: "auth_ok",
        user_id: "u1",
        role: "speaker",
        meeting_id: "m1",
      })
      expect(handled).toBe(false)
    })
    expect(result.current.transcript).toHaveLength(0)
    expect(result.current.glosses).toHaveLength(0)
  })
})
