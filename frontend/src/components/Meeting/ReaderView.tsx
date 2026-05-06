import { useMemo } from "react"

import type { GlossEntry } from "@/lib/meeting-types"
import { AvatarView } from "./AvatarView"
import { GlossFeed } from "./GlossFeed"
import { GlossInput } from "./GlossInput"

interface ReaderViewProps {
  glosses: GlossEntry[]
  onSendGloss: (gloss: string) => void
  disabled?: boolean
}

export function ReaderView({
  glosses,
  onSendGloss,
  disabled,
}: ReaderViewProps) {
  const ownGlosses = useMemo(
    () => glosses.filter((entry) => entry.isOwn),
    [glosses],
  )

  return (
    <div className="relative flex flex-1 flex-col">
      <GlossFeed
        entries={ownGlosses}
        emptyMessage="Type a gloss below to send it as speech."
      />
      <GlossInput onSend={onSendGloss} disabled={disabled} />
      <AvatarView entries={glosses} />
    </div>
  )
}
