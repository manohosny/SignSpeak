import { memo, useEffect, useRef } from "react"

import type { TranscriptEntry } from "@/lib/meeting-types"
import { cn } from "@/lib/utils"

interface TranscriptPanelProps {
  entries: TranscriptEntry[]
  currentRole: "speaker" | "reader"
}

function formatTime(timestamp: string) {
  return new Date(timestamp).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
  })
}

const TranscriptBubble = memo(function TranscriptBubble({
  entry,
  isOwn,
}: {
  entry: TranscriptEntry
  isOwn: boolean
}) {
  return (
    <div
      className={cn(
        "flex flex-col gap-1 max-w-[80%]",
        isOwn ? "self-end items-end" : "self-start items-start",
      )}
    >
      <div className="flex items-center gap-2 text-xs text-muted-foreground">
        <span className="font-medium">
          {entry.senderRole === "speaker" ? "Speaker" : "Reader"}
        </span>
        <span>{formatTime(entry.timestamp)}</span>
      </div>
      <div
        className={cn(
          "rounded-2xl px-4 py-2 text-sm",
          isOwn ? "bg-primary text-primary-foreground" : "bg-muted",
          entry.type === "transcript" && "italic",
        )}
      >
        {entry.content}
      </div>
    </div>
  )
})

export function TranscriptPanel({
  entries,
  currentRole,
}: TranscriptPanelProps) {
  const bottomRef = useRef<HTMLDivElement>(null)

  // Scroll to bottom when a new entry is added (not on partial content updates)
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [entries.length])

  if (entries.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-muted-foreground">
        Waiting for the speaker to start talking...
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-4">
      {entries.map((entry) => (
        <TranscriptBubble
          key={entry.id}
          entry={entry}
          isOwn={entry.senderRole === currentRole}
        />
      ))}
      <div ref={bottomRef} />
    </div>
  )
}
