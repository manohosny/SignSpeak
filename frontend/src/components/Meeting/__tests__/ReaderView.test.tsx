import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

// The avatar (CWASA runtime) and sign capture (webcam + worker) children are
// heavy browser integrations — stub them so this test exercises only the
// ReaderView composition.
vi.mock("../AvatarView", () => ({
  AvatarView: () => <div data-testid="avatar-view" />,
}))
vi.mock("../SignCaptureView", () => ({
  SignCaptureView: () => <div data-testid="sign-capture-view" />,
}))

import { ReaderView } from "../ReaderView"

function renderView(overrides: Partial<Parameters<typeof ReaderView>[0]> = {}) {
  return render(
    <ReaderView
      glosses={[]}
      onKeypointFrame={vi.fn()}
      onEndSentence={vi.fn()}
      signText={null}
      onSendText={vi.fn()}
      meetingId="meeting-1"
      {...overrides}
    />,
  )
}

describe("ReaderView", () => {
  it("mounts the avatar, the sign capture view and the manual text input", () => {
    renderView()

    expect(screen.getByTestId("avatar-view")).toBeInTheDocument()
    expect(screen.getByTestId("sign-capture-view")).toBeInTheDocument()
    expect(
      screen.getByRole("textbox", { name: /message text input/i }),
    ).toBeInTheDocument()
  })

  it("sends typed messages through onSendText (human override path)", () => {
    const onSendText = vi.fn()
    renderView({ onSendText })

    const input = screen.getByRole("textbox", { name: /message text input/i })
    fireEvent.change(input, { target: { value: "my signs keep failing" } })
    fireEvent.click(screen.getByRole("button", { name: /send message/i }))

    expect(onSendText).toHaveBeenCalledWith("my signs keep failing")
  })

  it("disables the text input while the meeting is not active", () => {
    renderView({ disabled: true })
    expect(
      screen.getByRole("textbox", { name: /message text input/i }),
    ).toBeDisabled()
  })
})
