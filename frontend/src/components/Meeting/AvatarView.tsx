import { useEffect, useMemo, useRef, useState } from "react"

import { assembleSigml } from "@/avatar/assemble"
import { tokeniseGlosses } from "@/avatar/tokenize"
import type { GlossEntry } from "@/lib/meeting-types"

import { CwasaAvatar } from "./CwasaAvatar"

interface AvatarViewProps {
  entries: GlossEntry[]
}

export function AvatarView({ entries }: AvatarViewProps) {
  const [sigml, setSigml] = useState<string | null>(null)
  const lastPlayedIdRef = useRef<string | null>(null)

  const latestIncoming = useMemo(() => {
    for (let i = entries.length - 1; i >= 0; i--) {
      if (!entries[i].isOwn) return entries[i]
    }
    return null
  }, [entries])

  useEffect(() => {
    if (!latestIncoming) return
    if (lastPlayedIdRef.current === latestIncoming.id) return
    const tokens = tokeniseGlosses(latestIncoming.text)
    if (tokens.length === 0) return
    const doc = assembleSigml(tokens)
    if (!doc) return
    lastPlayedIdRef.current = latestIncoming.id
    setSigml(doc)
  }, [latestIncoming])

  return (
    <div className="pointer-events-none absolute bottom-32 left-4 z-20">
      <CwasaAvatar sigml={sigml} />
    </div>
  )
}
