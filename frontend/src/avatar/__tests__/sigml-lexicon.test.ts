import { describe, expect, it } from "vitest"

import { assembleSigml } from "../assemble"
import { SIGML_LEXICON } from "../sigml-lexicon.gen"

// Contract validation for the generated lexicon: every entry must survive
// exactly what assemble.ts does to it — concatenation inside
// <sigml>...</sigml> — and come out as well-formed XML the CWASA runtime can
// render. CWASA is a black box that fails silently (or never fires animidle)
// on malformed input, so the build-time corpus is verified here instead of at
// the user's expense.
//
// An entry may hold SEVERAL concatenated <hns_sign> fragments — compound
// signs like ANOTHERTIME (= ANOTHER + TIME) or BSL (= B + S + L) — so the
// parse check wraps each value the same way assemble.ts does rather than
// requiring a single root.
//
// Failures are collected per check and asserted empty, so a regression in
// the generator points at the offending gloss keys instead of just "false".

// Known data defects in the upstream ISL corpus: signs whose HamNoSys body is
// completely empty (no manual, no non-manual content). They render as a blank
// pause. Pinned exactly so a regenerated lexicon that fixes them — or one
// that introduces NEW blanks — fails this suite and gets looked at.
const KNOWN_BLANK_SIGNS = [
  "ANDHRAPRADESH",
  "ARRANGE",
  "BERTH",
  "BLACKBOARD",
  "BUDHPOORNIMA",
  "BULLOCKCART",
  "CHANGE1",
  "ERASER",
  "FAIL-LOSER",
  "FEED",
  "LAKHNOW",
  "LANGUAGES",
  "TICKETCHECKER",
  "WEAPON",
]

const entries = Object.entries(SIGML_LEXICON)
const parser = new DOMParser()

// Mirror assemble.ts: fragments are concatenated inside <sigml>...</sigml>.
function parseAsAssembled(fragment: string): Document {
  return parser.parseFromString(`<sigml>${fragment}</sigml>`, "application/xml")
}

describe("SIGML_LEXICON contract", () => {
  it("bundles the full generated corpus", () => {
    expect(entries.length).toBeGreaterThan(1000)
  })

  it("every entry XML-parses once wrapped the way assemble.ts wraps it", () => {
    const invalid: string[] = []
    for (const [key, fragment] of entries) {
      if (parseAsAssembled(fragment).querySelector("parsererror") !== null) {
        invalid.push(key)
      }
    }
    expect(invalid).toEqual([])
  })

  it("every entry is made of <hns_sign> fragments with gloss + manual/non-manual sections", () => {
    const invalid: string[] = []
    for (const [key, fragment] of entries) {
      const doc = parseAsAssembled(fragment)
      if (doc.querySelector("parsererror") !== null) continue // counted above
      const signs = Array.from(doc.documentElement.children)
      const wellShaped =
        signs.length > 0 &&
        signs.every(
          (sign) =>
            sign.tagName === "hns_sign" &&
            !!sign.getAttribute("gloss") &&
            sign.querySelector("hamnosys_manual") !== null &&
            sign.querySelector("hamnosys_nonmanual") !== null,
        )
      if (!wellShaped) invalid.push(key)
    }
    expect(invalid).toEqual([])
  })

  it("every entry carries non-empty sign content, modulo the known corpus blanks", () => {
    const blank: string[] = []
    for (const [key, fragment] of entries) {
      const doc = parseAsAssembled(fragment)
      if (doc.querySelector("parsererror") !== null) continue // counted above
      const signs = Array.from(doc.documentElement.children)
      const hasContent = signs.some((sign) => {
        const manual = sign.querySelector("hamnosys_manual")
        const nonManual = sign.querySelector("hamnosys_nonmanual")
        return (
          (manual?.children.length ?? 0) > 0 ||
          (nonManual?.children.length ?? 0) > 0
        )
      })
      if (!hasContent) blank.push(key)
    }
    expect(blank.sort()).toEqual([...KNOWN_BLANK_SIGNS].sort())
  })

  it("no entry smuggles in a nested document wrapper", () => {
    // assemble.ts supplies the <sigml> wrapper and XML declaration; a
    // fragment containing its own would corrupt the assembled document.
    const invalid: string[] = []
    for (const [key, fragment] of entries) {
      if (fragment.includes("<sigml") || fragment.includes("<?xml")) {
        invalid.push(key)
      }
    }
    expect(invalid).toEqual([])
  })

  it("assembles the whole corpus into one well-formed SiGML document", () => {
    // End-to-end shape check against the real assemble.ts: every fragment
    // must survive being concatenated inside <sigml>...</sigml>.
    const doc = assembleSigml(Object.keys(SIGML_LEXICON))
    expect(doc).not.toBeNull()

    const parsed = parser.parseFromString(doc as string, "application/xml")
    expect(parsed.querySelector("parsererror")).toBeNull()
    expect(parsed.documentElement.tagName).toBe("sigml")
    // Each lexicon key resolves to at least its own <hns_sign> fragment.
    expect(
      parsed.documentElement.getElementsByTagName("hns_sign").length,
    ).toBeGreaterThanOrEqual(entries.length)
  })
})
