import { describe, expect, it } from "vitest"

import { WsServerMessageSchema } from "../meeting-schemas"

describe("WsServerMessageSchema", () => {
  const baseTimestamp = "2026-05-06T10:00:00.000Z"

  it.each([
    [
      "auth_ok",
      {
        type: "auth_ok",
        user_id: "u1",
        role: "speaker",
        meeting_id: "m1",
      },
    ],
    ["auth_error", { type: "auth_error", message: "bad token" }],
    [
      "transcript",
      {
        type: "transcript",
        text: "hello world",
        is_partial: false,
        sender_id: "u1",
        timestamp: baseTimestamp,
      },
    ],
    [
      "text_message",
      {
        type: "text_message",
        content: "hi",
        sender_id: "u1",
        timestamp: baseTimestamp,
      },
    ],
    [
      "user_joined",
      {
        type: "user_joined",
        user_id: "u2",
        display_name: "Alice",
        role: "reader",
      },
    ],
    ["user_left", { type: "user_left", user_id: "u2", display_name: "Alice" }],
    ["meeting_ended", { type: "meeting_ended" }],
    ["error", { type: "error", message: "boom" }],
    ["tts_start", { type: "tts_start" }],
    ["tts_end", { type: "tts_end" }],
    [
      "gloss",
      {
        type: "gloss",
        text: "HELLO",
        sender_id: "u1",
        timestamp: baseTimestamp,
      },
    ],
    [
      "gloss_message",
      {
        type: "gloss_message",
        content: "HELLO",
        sender_id: "u2",
        timestamp: baseTimestamp,
      },
    ],
    ["gloss_error", { type: "gloss_error", message: "translation failed" }],
  ])("accepts a valid %s message", (_, msg) => {
    const result = WsServerMessageSchema.safeParse(msg)
    expect(result.success).toBe(true)
  })

  it("rejects an unknown type", () => {
    const result = WsServerMessageSchema.safeParse({
      type: "totally_unknown",
      foo: 1,
    })
    expect(result.success).toBe(false)
  })

  it("rejects a transcript with missing required fields", () => {
    const result = WsServerMessageSchema.safeParse({
      type: "transcript",
      text: "hello",
      // missing is_partial, sender_id, timestamp
    })
    expect(result.success).toBe(false)
  })

  it("rejects a transcript with wrong field types", () => {
    const result = WsServerMessageSchema.safeParse({
      type: "transcript",
      text: 42,
      is_partial: "no",
      sender_id: "u1",
      timestamp: baseTimestamp,
    })
    expect(result.success).toBe(false)
  })

  it("rejects auth_ok with an unknown role", () => {
    const result = WsServerMessageSchema.safeParse({
      type: "auth_ok",
      user_id: "u1",
      role: "admin",
      meeting_id: "m1",
    })
    expect(result.success).toBe(false)
  })
})
