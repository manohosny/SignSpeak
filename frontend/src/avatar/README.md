# Avatar pipeline

Renders sign language with **CWASA**, a notation-driven signing avatar. CWASA
animates from **SiGML/HamNoSys** — a phonetic description of handshape,
location and movement — rather than from baked keyframes. Animation quality
therefore depends on the **lexicon data** and the **sequencing logic**, not the
renderer.

## Pipeline

```
gloss text → tokenize → lexicon → assemble SiGML → queue → driver → CWASA
```

| Module                 | Responsibility                                            |
| ---------------------- | --------------------------------------------------------- |
| `tokenize.ts`          | Normalise free-form gloss into UPPERCASE tokens.          |
| `lexicon.ts`           | Resolve a token to `<hns_sign>` SiGML fragment(s).        |
| `sigml-lexicon.gen.ts` | Auto-generated sign dictionary (see "Known limitations"). |
| `assemble.ts`          | Wrap fragments into one SiGML document.                   |
| `queue.ts`             | Serial FIFO playback — one sign sequence at a time.       |
| `driver.ts`            | Thin bridge to the `window.CWASA` runtime.                |

## Playback sequencing

`queue.ts` plays every incoming gloss in arrival order. CWASA renders one SiGML
document at a time, so the queue starts the next item only when the current one
finishes. Completion is CWASA's **`animidle`** hook event; a per-item watchdog
timeout (`driver.onAnimIdle` plus `estimateMs`) is the fallback if that event
never fires. When speech outruns the avatar, pending items are capped at
`MAX_QUEUE` and the **oldest** is dropped — real-time relevance favours the
newest message.

## Known limitations

These are intentional, accepted trade-offs in the current implementation, not
bugs to fix in passing.

### Lexicon is Indian Sign Language (placeholder)

`sigml-lexicon.gen.ts` contains ~1,168 **Indian Sign Language (ISL)** signs,
generated from the [`human-divanshu/Text-to-Sign-Language`](https://github.com/human-divanshu/Text-to-Sign-Language)
corpus. The translation model (`manohonsy/asl-mbart-50-lora`) emits **ASL**
gloss. As a result:

- ASL tokens that match a lexicon key render the **ISL** sign — a different
  language, not just an imperfect rendering.
- ASL tokens with no match are **fingerspelled with the ISL alphabet** (largely
  two-handed), which an ASL audience will not read as expected.

This is a stand-in proving the pipeline end to end. Replacing it with an ASL
SiGML lexicon (and ASL fingerspelling) is future work.

### Classifier motion is dropped

`resolveClassifier()` in `lexicon.ts` signs only the referent noun of a
classifier predicate: `cl:car-drive-away` renders just `CAR`. Classifier
predicates — productive handshapes tracing a path through signing space — are
core ASL grammar, but they require generative sign synthesis the fixed lexicon
cannot express, so the motion is discarded.

### Other accepted gaps

- Translation runs only on **final** transcripts, so the avatar lags speech by
  roughly 350 ms–1 s. Streaming/partial translation is out of scope.
- Non-manual grammar (eyebrow raises for questions, etc.) is not modelled.
- A single avatar (`av0`) is used; speed controls are not exposed.
