import { useEffect, useState } from "react"

import { initAvatar, loadCwasaRuntime, playSigml } from "@/avatar/driver"

interface CwasaAvatarProps {
  sigml: string | null
  width?: number
  height?: number
}

export function CwasaAvatar({
  sigml,
  width = 260,
  height = 320,
}: CwasaAvatarProps) {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false
    loadCwasaRuntime()
      .then(() => {
        if (cancelled) return
        initAvatar()
        setReady(true)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        console.error("CWASA runtime failed to load:", err)
      })
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!ready || !sigml) return
    playSigml(sigml).catch((err) => {
      console.error("CWASA playSigml failed:", err)
    })
  }, [sigml, ready])

  return (
    <div
      className="cwasa-tv overflow-hidden rounded-xl border border-white/20 bg-zinc-900/70 shadow-lg backdrop-blur-sm"
      style={{
        width,
        height,
        opacity: ready ? 1 : 0,
        transition: "opacity 200ms ease-in",
      }}
    >
      <div className="CWASAPanel av0" style={{ width, height }} />
    </div>
  )
}
