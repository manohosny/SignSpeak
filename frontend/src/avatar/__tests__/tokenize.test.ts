import { describe, expect, it } from "vitest"

import { tokeniseGlosses } from "../tokenize"

describe("tokeniseGlosses", () => {
  it("splits on whitespace and uppercases", () => {
    expect(tokeniseGlosses("ix want bake")).toEqual(["IX", "WANT", "BAKE"])
  })

  it("preserves the '#' fingerspelling marker", () => {
    expect(tokeniseGlosses("#john WANT")).toEqual(["#JOHN", "WANT"])
  })

  it("preserves the 'cl:' classifier prefix", () => {
    expect(tokeniseGlosses("cl:vehicle DRIVE")).toEqual(["CL:VEHICLE", "DRIVE"])
  })

  it("strips other punctuation and drops empty tokens", () => {
    expect(tokeniseGlosses("hello,  world!")).toEqual(["HELLO", "WORLD"])
  })

  it("keeps hyphens inside a token", () => {
    expect(tokeniseGlosses("ICE-CREAM")).toEqual(["ICE-CREAM"])
  })
})
