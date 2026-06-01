import { fireEvent, render, screen } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { TextInput } from "../TextInput"

describe("TextInput", () => {
  it("exposes accessible names for the input and send button", () => {
    // SignSpeak is an accessibility platform — screen-reader users must be
    // able to identify both controls without relying on placeholder text.
    render(<TextInput onSend={vi.fn()} />)
    expect(
      screen.getByRole("textbox", { name: /message text input/i }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /send message/i }),
    ).toBeInTheDocument()
  })

  it("sends trimmed input and clears the field", () => {
    const onSend = vi.fn()
    render(<TextInput onSend={onSend} />)
    const input = screen.getByRole("textbox", { name: /message text input/i })
    fireEvent.change(input, { target: { value: "  hello  " } })
    fireEvent.click(screen.getByRole("button", { name: /send message/i }))
    expect(onSend).toHaveBeenCalledWith("hello")
    expect(input).toHaveValue("")
  })
})
