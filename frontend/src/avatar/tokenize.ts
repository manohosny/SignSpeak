// Normalise a free-form gloss string into an UPPERCASE token list.
// Mirrors the avatar project's tokeniser (App.tsx) so behaviour matches
// when the real lexicon is keyed on the same convention.
export function tokeniseGlosses(raw: string): string[] {
  return raw
    .split(/\s+/)
    .map((t) =>
      t
        .trim()
        .replace(/[^A-Za-z0-9-]/g, "")
        .toUpperCase(),
    )
    .filter((t) => t.length > 0)
}
