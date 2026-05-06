import { memo, type ReactNode, useEffect, useRef } from "react"

import type { GlossEntry } from "@/lib/meeting-types"
import { cn } from "@/lib/utils"

interface GlossFeedProps {
  entries: GlossEntry[]
  emptyMessage?: ReactNode
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  })
}

const GlossBubble = memo(function GlossBubble({
  entry,
}: {
  entry: GlossEntry
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 max-w-[80%]",
        entry.isOwn ? "self-end items-end" : "self-start items-start",
      )}
    >
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium">{entry.isOwn ? "You" : "Speaker"}</span>
        <span>{formatTime(entry.timestamp)}</span>
      </div>
      <div
        className={cn(
          "rounded-2xl px-4 py-2 text-sm font-mono tracking-wide",
          entry.isOwn ? "bg-primary text-primary-foreground" : "bg-muted",
        )}
      >
        {entry.text}
      </div>
    </div>
  )
})

export function GlossFeed({ entries, emptyMessage }: GlossFeedProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [])

  if (entries.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        {emptyMessage ?? "Waiting for the speaker to sign..."}
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
      {entries.map((entry) => (
        <GlossBubble key={entry.id} entry={entry} />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
