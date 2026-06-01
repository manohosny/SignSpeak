import { fireEvent, render, screen } from "@testing-library/react"
import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  type Mock,
  vi,
} from "vitest"

// TanStack Router's <Link> needs a router context we don't have in unit tests.
// Stub it with a plain anchor so the fallback can render in isolation.
vi.mock("@tanstack/react-router", () => ({
  Link: ({
    to,
    children,
    ...rest
  }: {
    to: string
    children: React.ReactNode
  } & React.AnchorHTMLAttributes<HTMLAnchorElement>) => (
    <a href={to} {...rest}>
      {children}
    </a>
  ),
}))

import { MeetingErrorBoundary } from "../MeetingErrorBoundary"

function Boom({ shouldThrow }: { shouldThrow: boolean }) {
  if (shouldThrow) {
    throw new Error("kaboom")
  }
  return <div data-testid="ok">recovered</div>
}

describe("MeetingErrorBoundary", () => {
  let consoleErrorSpy: Mock

  beforeEach(() => {
    // React always logs caught errors to the console; silence them so the
    // test runner output is clean.
    consoleErrorSpy = vi.fn()
    vi.spyOn(console, "error").mockImplementation(consoleErrorSpy)
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("renders children when no error is thrown", () => {
    render(
      <MeetingErrorBoundary resetKey={0}>
        <Boom shouldThrow={false} />
      </MeetingErrorBoundary>,
    )
    expect(screen.getByTestId("ok")).toBeInTheDocument()
  })

  it("renders the fallback when a child throws", () => {
    render(
      <MeetingErrorBoundary resetKey={0}>
        <Boom shouldThrow={true} />
      </MeetingErrorBoundary>,
    )
    expect(screen.getByRole("alert")).toBeInTheDocument()
    expect(screen.getByText(/something went wrong/i)).toBeInTheDocument()
    expect(screen.getByText(/kaboom/i)).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: /rejoin meeting/i }),
    ).toBeInTheDocument()
  })

  it("calls onReset when the user clicks Rejoin meeting", () => {
    const onReset = vi.fn()
    render(
      <MeetingErrorBoundary resetKey={0} onReset={onReset}>
        <Boom shouldThrow={true} />
      </MeetingErrorBoundary>,
    )
    fireEvent.click(screen.getByRole("button", { name: /rejoin meeting/i }))
    expect(onReset).toHaveBeenCalledTimes(1)
  })
})
