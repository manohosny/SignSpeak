import { describe, expect, it } from "vitest"

import { assembleSigml } from "../assemble"
import { lookupGloss } from "../lexicon"
import { SIGML_LEXICON } from "../sigml-lexicon.gen"
import { tokeniseGlosses } from "../tokenize"

describe("SIGML_LEXICON", () => {
  it("bundles the full ISL corpus", () => {
    expect(Object.keys(SIGML_LEXICON).length).toBeGreaterThan(1000)
  })

  it("stores bare <hns_sign> fragments, not whole documents", () => {
    for (const fragment of Object.values(SIGML_LEXICON)) {
      expect(fragment.startsWith("<hns_sign")).toBe(true)
      expect(fragment).not.toContain("<sigml>")
    }
  })

  it("includes the full manual alphabet and digits for fingerspelling", () => {
    for (const ch of "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789") {
      expect(SIGML_LEXICON).toHaveProperty(ch)
    }
  })
})

describe("lookupGloss", () => {
  it("returns the dedicated sign for a known gloss", () => {
    expect(lookupGloss("HELLO")).toEqual([SIGML_LEXICON.HELLO])
  })

  it("is case-insensitive", () => {
    expect(lookupGloss("hello")).toEqual(lookupGloss("HELLO"))
  })

  it("resolves the IX index gloss to the I sign, not letters I + X", () => {
    expect(lookupGloss("IX")).toEqual([SIGML_LEXICON.I])
  })

  it("resolves #-marked words: dictionary sign first, else fingerspell", () => {
    // '#' marks a word the model fingerspelled. Prefer a real sign when the
    // dictionary has one; a name with no sign falls back to fingerspelling.
    expect(lookupGloss("#HELLO")).toEqual([SIGML_LEXICON.HELLO])
    expect(lookupGloss("#JOHN")).toEqual([
      SIGML_LEXICON.J,
      SIGML_LEXICON.O,
      SIGML_LEXICON.H,
      SIGML_LEXICON.N,
    ])
  })

  it("signs a classifier's referent noun when it names one", () => {
    // cl:car and cl:car-drive-away both sign CAR; the motion is dropped.
    expect(lookupGloss("CL:CAR")).toEqual([SIGML_LEXICON.CAR])
    expect(lookupGloss("CL:CAR-DRIVE-AWAY")).toEqual([SIGML_LEXICON.CAR])
  })

  it("skips classifiers with no signable referent", () => {
    // Handshape codes (cl:3) and unknown referents have nothing to show.
    expect(lookupGloss("CL:3")).toEqual([])
    expect(lookupGloss("CL:VEHICLE")).toEqual([])
  })

  it("fingerspells an unknown gloss letter by letter", () => {
    // A nonsense token has no dedicated sign, so it is spelled out.
    expect(lookupGloss("ZXJQ")).toEqual([
      SIGML_LEXICON.Z,
      SIGML_LEXICON.X,
      SIGML_LEXICON.J,
      SIGML_LEXICON.Q,
    ])
  })

  it("skips characters with no sign when fingerspelling", () => {
    // The hyphen has no manual-alphabet sign and is dropped.
    expect(lookupGloss("A-Z")).toEqual([SIGML_LEXICON.A, SIGML_LEXICON.Z])
  })
})

describe("assembleSigml", () => {
  it("wraps looked-up glosses in a single SiGML document", () => {
    const doc = assembleSigml(tokeniseGlosses("HELLO"))
    expect(doc).toContain('<?xml version="1.0"')
    expect(doc).toContain("<sigml>")
    expect(doc).toContain(SIGML_LEXICON.HELLO)
    expect(doc).toContain("</sigml>")
  })

  it("expands an unknown gloss into several fingerspelled signs", () => {
    const doc = assembleSigml(["QWXZ"]) ?? ""
    const signCount = (doc.match(/<hns_sign\b/g) ?? []).length
    expect(signCount).toBe(4)
  })

  it("returns null when there is nothing to play", () => {
    expect(assembleSigml([])).toBeNull()
  })
})
