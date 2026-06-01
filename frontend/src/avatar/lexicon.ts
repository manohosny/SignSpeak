// SiGML lexicon: resolves UPPERCASE gloss tokens to HamNoSys-encoded
// <hns_sign> fragments that the CWASA runtime can render.
//
// Most of the vocabulary lives in the auto-generated sigml-lexicon.gen.ts —
// ~1,200 Indian Sign Language signs imported from the human-divanshu
// Text-to-Sign-Language corpus. The three hand-written builtins below are
// kept as a reference set; the generated data takes precedence when it
// covers the same gloss.

import { SIGML_LEXICON } from "./sigml-lexicon.gen"

// SiGML fragments for the three CWASA built-in examples (I, MUG, TAKE).
// These are HamNoSys-encoded XML the CWASA runtime knows how to render.
// Source: provided by user, derived from CWASA vhg.2026 reference content.

const SIGML_I = `<hns_sign gloss="i">
  <hamnosys_nonmanual>
    <hnm_mouthpicture picture="a_I"/>
  </hamnosys_nonmanual>
  <hamnosys_manual>
    <hamfinger2/> <hamthumbacrossmod/>
    <hamextfingeril/> <hampalmr/>
    <hamchest/> <hamtouch/>
  </hamnosys_manual>
</hns_sign>`

const SIGML_MUG = `<hns_sign gloss="mug">
  <hamnosys_nonmanual>
    <hnm_mouthpicture picture="mVg"/>
  </hamnosys_nonmanual>
  <hamnosys_manual>
    <hamfist/> <hamthumbacrossmod/>
    <hamextfingerol/> <hampalml/>
    <hamshoulders/>
    <hamparbegin/> <hammoveu/> <hamarcu/>
    <hamreplace/> <hamextfingerul/> <hampalmdl/>
    <hamparend/>
  </hamnosys_manual>
</hns_sign>`

const SIGML_TAKE = `<hns_sign gloss="take">
  <hamnosys_nonmanual>
    <hnm_mouthpicture picture="te_Ik"/>
  </hamnosys_nonmanual>
  <hamnosys_manual>
    <hamceeall/> <hamextfingerol/> <hampalml/>
    <hamlrbeside/> <hamshoulders/> <hamarmextended/>
    <hamreplace/> <hamextfingerl/> <hampalml/>
    <hamchest/> <hamclose/>
  </hamnosys_manual>
</hns_sign>`

export type BuiltinGloss = "I" | "MUG" | "TAKE"

export const BUILTIN_SIGML: Record<BuiltinGloss, string> = {
  I: SIGML_I,
  MUG: SIGML_MUG,
  TAKE: SIGML_TAKE,
}

// Fingerspell a gloss that has no dedicated sign: emit one manual-alphabet
// sign per character. The generated lexicon contains a sign for every letter
// A-Z and digit 0-9, so each character is just another lexicon lookup.
// Characters with no sign (e.g. a stray "-" from a hyphenated gloss) are
// skipped. This mirrors how a human interpreter handles names and words
// outside the signed vocabulary.
function fingerspell(word: string): string[] {
  const fragments: string[] = []
  for (const char of word) {
    if (char in SIGML_LEXICON) {
      fragments.push(SIGML_LEXICON[char])
    }
  }
  return fragments
}

// ASL gloss aliases — tokens that are a single gloss, NOT a word to spell out.
// The translation model (manohonsy/asl-mbart-50-lora) emits `IX` for the
// index/pointing sign (deixis); its model card and examples use bare `IX` for
// the signer ("I"/"me"), so it resolves to the "I" sign rather than the
// letters I + X. Hand-maintained: each entry maps a raw token to a canonical
// lexicon key, resolved normally afterwards. Add directional points like
// `IX-1`/`IX-2` here only if the model is observed to emit them.
const GLOSS_ALIASES: Record<string, string> = {
  IX: "I",
}

// Resolve a classifier predicate (cl:...). A classifier is a productive
// handshape, not a fixed sign — but the gloss often names a concrete referent
// (cl:car, cl:car-drive-away). When the first element after "cl:" is a known
// dictionary word, sign that referent noun and drop the un-renderable motion.
// Handshape codes (cl:3, cl:B) and unknown referents have nothing to show, so
// the token is skipped.
//
// KNOWN LIMITATION: the motion predicate is discarded — `cl:car-drive-away`
// signs only CAR. Classifier motion is core ASL grammar; rendering it would
// need productive sign synthesis the fixed lexicon cannot express. See
// src/avatar/README.md.
function resolveClassifier(raw: string): string[] {
  // `referent` is the text after "CL:", up to the first "-".
  const referent = raw.slice(3).split("-")[0]
  if (referent.length > 1 && referent in SIGML_LEXICON) {
    return [SIGML_LEXICON[referent]]
  }
  return []
}

// Resolve one gloss token to an ordered list of <hns_sign> fragments,
// honoring the conventions of the model's pseudo-gloss:
//   cl:...   classifier predicate — see resolveClassifier (referent or skip).
//   #WORD    word the model fingerspelled — the '#' marker is dropped and the
//            word resolved normally (dictionary first, then fingerspelling).
//   IX, ...  gloss aliases resolved via GLOSS_ALIASES.
// Any other token resolves to its dedicated dictionary sign, or — failing
// that — is fingerspelled letter by letter.
export function lookupGloss(gloss: string): string[] {
  const raw = gloss.toUpperCase()

  if (raw.startsWith("CL:")) {
    return resolveClassifier(raw)
  }

  // Drop a leading '#' (the model's fingerspelling marker) and resolve the
  // word normally: a dedicated sign is preferred, with fingerspelling — what
  // the marker asked for — as the fallback when no sign exists.
  const unmarked = raw.startsWith("#") ? raw.slice(1) : raw

  const key = unmarked in GLOSS_ALIASES ? GLOSS_ALIASES[unmarked] : unmarked
  if (key in SIGML_LEXICON) {
    return [SIGML_LEXICON[key]]
  }
  if (key in BUILTIN_SIGML) {
    return [BUILTIN_SIGML[key as BuiltinGloss]]
  }
  return fingerspell(key)
}
