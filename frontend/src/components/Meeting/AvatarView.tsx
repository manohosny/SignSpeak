import { useEffect, useState } from "react"

import { assembleSigml } from "@/avatar/assemble"
import {
  type AvatarQueueItem,
  clearAvatarQueue,
  enqueueSigml,
  subscribeCurrent,
} from "@/avatar/queue"
import { tokeniseGlosses } from "@/avatar/tokenize"
import type { GlossEntry } from "@/lib/meeting-types"

import { CwasaAvatar } from "./CwasaAvatar"

interface AvatarViewProps {
  entries: GlossEntry[]
}

export function AvatarView({ entries }: AvatarViewProps) {
  const [current, setCurrent] = useState<AvatarQueueItem | null>(null)

  // Mirror the queue's "currently signing" item so the aria-live caption
  // tracks the avatar, not whichever message arrived most recently.
  useEffect(() => subscribeCurrent(setCurrent), [])

  // Enqueue every incoming gloss in arrival order. The queue dedupes by id,
  // so re-running this whenever `entries` changes is safe and cheap — each
  // utterance is signed exactly once, none dropped when speech outruns the
  // avatar.
  useEffect(() => {
    for (const entry of entries) {
      if (entry.isOwn) continue
      const tokens = tokeniseGlosses(entry.text)
      if (tokens.length === 0) continue
      const doc = assembleSigml(tokens)
      if (doc === null) continue
      enqueueSigml({ id: entry.id, sigml: doc, glossText: entry.text })
    }
  }, [entries])

  // Stop playback and flush pending signs when the view unmounts.
  useEffect(() => () => clearAvatarQueue(), [])

  return (
    <div className="pointer-events-none absolute bottom-32 left-4 z-20">
      <CwasaAvatar glossText={current?.glossText ?? null} />
    </div>
  )
}
