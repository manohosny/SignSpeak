import { Mic, MicOff } from "lucide-react"

import { Button } from "@/components/ui/button"
import { cn } from "@/lib/utils"

interface MicButtonProps {
  isOn: boolean
  isSpeaking?: boolean
  onToggle: () => void
  disabled?: boolean
  error?: string | null
}

export function MicButton({
  isOn,
  isSpeaking,
  onToggle,
  disabled,
  error,
}: MicButtonProps) {
  return (
    <div className="flex flex-col items-center gap-3">
      <div className="relative">
        {isOn && (
          <div
            className={cn(
              "absolute -inset-2 rounded-full transition-colors duration-300",
              isSpeaking ? "animate-ping bg-green-500/30" : "bg-amber-500/20",
            )}
          />
        )}
        <Button
          size="lg"
          variant={isOn ? "destructive" : "default"}
          className={cn(
            "relative h-24 w-24 rounded-full transition-all duration-300",
            isOn && isSpeaking && "ring-4 ring-green-500/60",
          )}
          onClick={onToggle}
          disabled={disabled}
          aria-label={isOn ? "Turn microphone off" : "Turn microphone on"}
          aria-pressed={isOn}
        >
          {isOn ? (
            <MicOff className="h-10 w-10" aria-hidden="true" />
          ) : (
            <Mic className="h-10 w-10" aria-hidden="true" />
          )}
        </Button>
      </div>
      <span className="text-sm text-muted-foreground">
        {error ??
          (isOn
            ? isSpeaking
              ? "Listening..."
              : "Waiting for speech..."
            : "Tap to speak")}
      </span>
    </div>
  )
}
