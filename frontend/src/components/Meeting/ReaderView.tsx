import type { GlossEntry } from "@/lib/meeting-types"
import { GlossFeed } from "./GlossFeed"
import { GlossInput } from "./GlossInput"

interface ReaderViewProps {
  glosses: GlossEntry[]
  onSendGloss: (gloss: string) => void
  disabled?: boolean
}

export function ReaderView({ glosses, onSendGloss, disabled }: ReaderViewProps) {
  return (
    <div className="flex flex-1 flex-col">
      <GlossFeed entries={glosses} />
      <GlossInput onSend={onSendGloss} disabled={disabled} />
    </div>
  )
}
