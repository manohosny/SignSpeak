import { Send } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"

interface GlossInputProps {
  onSend: (gloss: string) => void
  disabled?: boolean
}

export function GlossInput({ onSend, disabled }: GlossInputProps) {
  const [value, setValue] = useState("")

  const handleSend = () => {
    const trimmed = value.trim()
    if (trimmed) {
      onSend(trimmed)
      setValue("")
    }
  }

  return (
    <div className="flex gap-2 border-t p-4">
      <textarea
        placeholder="Type ASL gloss, e.g. IX WANT BAKE CHOCOLATE CAKE"
        value={value}
        onChange={(e) => setValue(e.target.value.toUpperCase())}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            handleSend()
          }
        }}
        disabled={disabled}
        autoFocus
        rows={2}
        className="flex w-full resize-none rounded-md border border-input bg-transparent px-3 py-2 text-sm font-mono tracking-wide shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
      />
      <Button
        size="icon"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        className="self-end"
      >
        <Send className="h-4 w-4" />
      </Button>
    </div>
  )
}
