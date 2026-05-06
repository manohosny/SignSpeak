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

const BUILTIN_ROTATION: BuiltinGloss[] = ["I", "MUG", "TAKE"]

// Placeholder for the generated SiGML lexicon. Populate this with
// UPPERCASE gloss → <hns_sign> fragment mappings as the data lands.
// Example entry:
//   HELLO: `<hns_sign gloss="HELLO"><hamnosys_manual>...</hamnosys_manual></hns_sign>`,
//
// When this object is no longer empty, swap the body of `lookupGloss` to
// the production form documented inside that function.
export const customLexicon: Record<string, string> = {}

export function lookupGloss(_gloss: string, index: number): string {
  // Production form (enable once `customLexicon` has real entries):
  //   const key = _gloss.toUpperCase()
  //   return customLexicon[key] ?? BUILTIN_SIGML[BUILTIN_ROTATION[index % 3]]
  return BUILTIN_SIGML[BUILTIN_ROTATION[index % BUILTIN_ROTATION.length]]
}
