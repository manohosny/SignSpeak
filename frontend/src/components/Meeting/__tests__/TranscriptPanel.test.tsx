import { render, screen } from "@testing-library/react"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { TranscriptEntry } from "@/lib/meeting-types"

import { TranscriptPanel } from "../TranscriptPanel"

// jsdom doesn't implement scrollIntoView; the panel calls it on each append.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

function makeEntry(overrides: Partial<TranscriptEntry> = {}): TranscriptEntry {
  return {
    id: "t-1",
    type: "transcript",
    content: "hello world",
    senderId: "u-1",
    senderRole: "speaker",
    timestamp: "2026-05-06T10:00:00.000Z",
    ...overrides,
  }
}

describe("TranscriptPanel", () => {
  it("renders each entry's content with its sender label", () => {
    render(
      <TranscriptPanel
        entries={[
          makeEntry(),
          makeEntry({
            id: "m-1",
            type: "text_message",
            content: "typed reply",
            senderId: "u-2",
            senderRole: "reader",
          }),
        ]}
        currentRole="speaker"
      />,
    )

    expect(screen.getByText("hello world")).toBeInTheDocument()
    expect(screen.getByText("Speaker")).toBeInTheDocument()
    expect(screen.getByText("typed reply")).toBeInTheDocument()
    expect(screen.getByText("Reader")).toBeInTheDocument()
  })

  it("dims a partial transcript entry while STT is still working", () => {
    render(
      <TranscriptPanel
        entries={[makeEntry({ isPartial: true })]}
        currentRole="speaker"
      />,
    )

    expect(screen.getByText("hello world")).toHaveClass("opacity-50")
  })

  it("shows speaker-facing guidance when the speaker's feed is empty", () => {
    render(<TranscriptPanel entries={[]} currentRole="speaker" />)
    expect(
      screen.getByText(/your words will appear here as you speak/i),
    ).toBeInTheDocument()
  })

  it("shows reader-facing guidance when the reader's feed is empty", () => {
    render(<TranscriptPanel entries={[]} currentRole="reader" />)
    expect(
      screen.getByText(/waiting for the speaker to start talking/i),
    ).toBeInTheDocument()
  })
})
