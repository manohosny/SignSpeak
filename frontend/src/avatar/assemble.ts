import { lookupGloss } from "./lexicon"

const XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'

// Build a complete SiGML document from a list of glosses by looking up each
// gloss and wrapping the resulting <hns_sign> fragments in <sigml>...</sigml>.
// Returns null when there is nothing to play.
export function assembleSigml(glosses: string[]): string | null {
  if (glosses.length === 0) {
    return null
  }
  const fragments = glosses.map((g, i) => lookupGloss(g, i))
  return `${XML_DECL}\n<sigml>\n${fragments.join("\n")}\n</sigml>\n`
}
