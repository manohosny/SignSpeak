import { lookupGloss } from "./lexicon"

const XML_DECL = '<?xml version="1.0" encoding="UTF-8"?>'

// Build a complete SiGML document from a list of glosses. Each gloss resolves
// to one or more <hns_sign> fragments (a dedicated dictionary sign, or several
// fingerspelled letters), which are concatenated inside <sigml>...</sigml>.
// Returns null when there is nothing to play.
export function assembleSigml(glosses: string[]): string | null {
  if (glosses.length === 0) {
    return null
  }
  const fragments = glosses.flatMap((gloss) => lookupGloss(gloss))
  if (fragments.length === 0) {
    return null
  }
  return `${XML_DECL}\n<sigml>\n${fragments.join("\n")}\n</sigml>\n`
}
