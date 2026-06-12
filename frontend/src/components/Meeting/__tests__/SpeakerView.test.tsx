import { fireEvent, render, screen } from "@testing-library/react"
import { beforeAll, describe, expect, it, vi } from "vitest"

import type { TranscriptEntry } from "@/lib/meeting-types"

import { SpeakerView } from "../SpeakerView"

// jsdom doesn't implement scrollIntoView; TranscriptPanel calls it on append.
beforeAll(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

const transcript: TranscriptEntry[] = [
  {
    id: "t-1",
    type: "transcript",
    content: "good morning everyone",
    senderId: "u-1",
    senderRole: "speaker",
    timestamp: "2026-05-06T10:00:00.000Z",
  },
]

function renderView(
  overrides: Partial<Parameters<typeof SpeakerView>[0]> = {},
) {
  return render(
    <SpeakerView
      isMicOn={false}
      onToggleMic={vi.fn()}
      transcript={[]}
      {...overrides}
    />,
  )
}

describe("SpeakerView", () => {
  it("renders the mic toggle and forwards clicks", () => {
    const onToggleMic = vi.fn()
    renderView({ onToggleMic })

    const mic = screen.getByRole("button", { name: /turn microphone on/i })
    fireEvent.click(mic)
    expect(onToggleMic).toHaveBeenCalledTimes(1)
  })

  it("shows the live transcript so the speaker can verify STT heard them", () => {
    renderView({ transcript })

    expect(
      screen.getByRole("region", { name: /conversation transcript/i }),
    ).toBeInTheDocument()
    expect(screen.getByText("good morning everyone")).toBeInTheDocument()
  })

  it("shows speaker-facing guidance while the transcript is empty", () => {
    renderView()
    expect(
      screen.getByText(/your words will appear here as you speak/i),
    ).toBeInTheDocument()
  })

  it("announces when the partner is speaking", () => {
    renderView({ isPartnerSpeaking: true })
    expect(screen.getByText(/partner is speaking/i)).toBeInTheDocument()
  })
})
