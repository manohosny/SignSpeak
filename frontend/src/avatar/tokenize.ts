// Normalise a free-form gloss string into an UPPERCASE token list.
//
// The translation model (manohonsy/asl-mbart-50-lora) emits pseudo-gloss with
// two structural markers that must survive tokenisation: a leading '#' on
// fingerspelled words/acronyms, and a 'cl:' prefix on classifier predicates.
// So ':' and '#' are kept here — lookupGloss() interprets them. Every other
// character outside [A-Za-z0-9-] is dropped.
export function tokeniseGlosses(raw: string): string[] {
  return raw
    .split(/\s+/)
    .map((t) =>
      t
        .trim()
        .replace(/[^A-Za-z0-9:#-]/g, "")
        .toUpperCase(),
    )
    .filter((t) => t.length > 0)
}
