import { fireEvent, render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import type { SignTextState } from "@/lib/meeting-types"

// The webcam + RTMW worker pipeline can't run in jsdom — stub the hook with
// a steady "camera on, not capturing" state so the view renders its UI.
vi.mock("@/hooks/usePoseCapture", () => ({
  usePoseCapture: vi.fn(() => ({
    isCameraOn: true,
    cameraError: null,
    isCapturing: false,
    isReady: false,
    error: null,
    framesSent: 0,
    personDetected: false,
    startCapture: vi.fn(),
    stopCapture: vi.fn(),
  })),
}))

vi.mock("@/lib/flag-message", () => ({
  flagMessage: vi.fn(),
}))

import { flagMessage } from "@/lib/flag-message"

import { SignCaptureView } from "../SignCaptureView"

const flagMessageMock = vi.mocked(flagMessage)

function renderView(
  signText: SignTextState | null,
  meetingId: string | null = "meeting-1",
) {
  return render(
    <SignCaptureView
      onKeypointFrame={vi.fn()}
      onEndSentence={vi.fn()}
      signText={signText}
      meetingId={meetingId}
    />,
  )
}

beforeEach(() => {
  flagMessageMock.mockReset()
})

describe("SignCaptureView — low-confidence indicator", () => {
  it("shows a low-confidence badge when confidence is below 0.5", () => {
    renderView({ content: "hello world", confidence: 0.3 })

    expect(screen.getByText(/hello world/)).toBeInTheDocument()
    const badge = screen.getByText(/low confidence/i)
    expect(badge).toBeInTheDocument()
    expect(badge).toHaveAttribute("title")
  })

  it("shows no badge when confidence is 0.5 or above", () => {
    renderView({ content: "hello world", confidence: 0.5 })
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument()
  })

  it("shows no badge when confidence is absent (older servers)", () => {
    renderView({ content: "hello world" })
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument()
  })
})

describe("SignCaptureView — flag wrong translation", () => {
  it("offers the flag action only for finalized sentences with a message_id", () => {
    renderView({ content: "hello world", messageId: "msg-1" })
    expect(
      screen.getByRole("button", { name: /flag wrong translation/i }),
    ).toBeInTheDocument()
  })

  it("hides the flag action when message_id is absent (partial echo)", () => {
    renderView({ content: "hello …" })
    expect(
      screen.queryByRole("button", { name: /flag wrong translation/i }),
    ).not.toBeInTheDocument()
  })

  it("hides the flag action when the meeting id is not known yet", () => {
    renderView({ content: "hello world", messageId: "msg-1" }, null)
    expect(
      screen.queryByRole("button", { name: /flag wrong translation/i }),
    ).not.toBeInTheDocument()
  })

  it("flags the message and shows the confirmation on success", async () => {
    flagMessageMock.mockResolvedValueOnce(true)
    renderView({ content: "hello world", messageId: "msg-1" })

    fireEvent.click(
      screen.getByRole("button", { name: /flag wrong translation/i }),
    )

    expect(await screen.findByText("Flagged ✓")).toBeInTheDocument()
    expect(flagMessageMock).toHaveBeenCalledWith("meeting-1", "msg-1")
    expect(
      screen.queryByRole("button", { name: /flag wrong translation/i }),
    ).not.toBeInTheDocument()
  })

  it("keeps the flag action available when the request fails", async () => {
    flagMessageMock.mockResolvedValueOnce(false)
    renderView({ content: "hello world", messageId: "msg-1" })

    fireEvent.click(
      screen.getByRole("button", { name: /flag wrong translation/i }),
    )

    // Non-2xx is non-fatal: no confirmation, the button stays for a retry.
    expect(screen.queryByText("Flagged ✓")).not.toBeInTheDocument()
    expect(
      await screen.findByRole("button", { name: /flag wrong translation/i }),
    ).toBeInTheDocument()
  })
})
