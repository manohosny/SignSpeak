import { Send } from "lucide-react"
import { useState } from "react"

import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"

interface TextInputProps {
  onSend: (message: string) => void
  disabled?: boolean
}

export function TextInput({ onSend, disabled }: TextInputProps) {
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
      <Input
        aria-label="Message text input"
        placeholder="Type a message..."
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault()
            handleSend()
          }
        }}
        disabled={disabled}
        autoFocus
      />
      <Button
        size="icon"
        aria-label="Send message"
        onClick={handleSend}
        disabled={disabled || !value.trim()}
      >
        <Send className="h-4 w-4" aria-hidden="true" />
      </Button>
    </div>
  )
}
