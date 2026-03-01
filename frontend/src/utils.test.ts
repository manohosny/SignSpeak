import { AxiosError } from "axios"
import { describe, expect, it, vi } from "vitest"
import { getInitials, handleError } from "./utils"

describe("getInitials", () => {
  it("returns initials from full name", () => {
    expect(getInitials("John Doe")).toBe("JD")
  })

  it("returns single initial for single name", () => {
    expect(getInitials("Alice")).toBe("A")
  })

  it("limits to two initials", () => {
    expect(getInitials("John Michael Doe")).toBe("JM")
  })

  it("returns uppercase initials", () => {
    expect(getInitials("jane doe")).toBe("JD")
  })
})

describe("handleError", () => {
  it("extracts message from AxiosError", () => {
    const callback = vi.fn()
    const err = new AxiosError("Network Error")
    handleError.call(callback, err as any)
    expect(callback).toHaveBeenCalledWith("Network Error")
  })

  it("extracts string detail from error body", () => {
    const callback = vi.fn()
    const err = { body: { detail: "User not found" } }
    handleError.call(callback, err as any)
    expect(callback).toHaveBeenCalledWith("User not found")
  })

  it("extracts first message from array detail", () => {
    const callback = vi.fn()
    const err = { body: { detail: [{ msg: "Field required" }] } }
    handleError.call(callback, err as any)
    expect(callback).toHaveBeenCalledWith("Field required")
  })

  it("falls back to default message when no detail", () => {
    const callback = vi.fn()
    const err = { body: {} }
    handleError.call(callback, err as any)
    expect(callback).toHaveBeenCalledWith("Something went wrong.")
  })
})
