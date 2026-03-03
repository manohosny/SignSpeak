import { Mic, MicOff } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface MicButtonProps {
  isOn: boolean
  onToggle: () => void
  disabled?: boolean
  error?: string | null
}

export function MicButton({ isOn, onToggle, disabled, error }: MicButtonProps) {
  return (
    <div className="flex flex-col items-center gap-3">
      <Button
        size="lg"
        variant={isOn ? "destructive" : "default"}
        className={cn("h-24 w-24 rounded-full", isOn && "animate-pulse")}
        onClick={onToggle}
        disabled={disabled}
      >
        {isOn ? (
          <MicOff className="h-10 w-10" />
        ) : (
          <Mic className="h-10 w-10" />
        )}
      </Button>
      <span className="text-sm text-muted-foreground">
        {error ?? (isOn ? "Tap to mute" : "Tap to speak")}
      </span>
    </div>
  )
}
