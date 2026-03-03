import { Link } from "@tanstack/react-router"
import { Check, Copy, LogOut, PhoneOff } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"
import type { MeetingState } from "@/lib/meeting-types"

interface MeetingHeaderProps {
  code: string
  meetingState: MeetingState
  onEndMeeting: () => void
}

export function MeetingHeader({
  code,
  meetingState,
  onEndMeeting,
}: MeetingHeaderProps) {
  const [copiedText, copy] = useCopyToClipboard()

  return (
    <header className="flex items-center justify-between border-b px-4 py-3">
      <div className="flex items-center gap-3">
        <Link to="/" className="text-muted-foreground hover:text-foreground">
          <LogOut className="h-4 w-4" />
        </Link>
        <div className="flex items-center gap-2">
          <code className="font-mono text-sm font-medium">{code}</code>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            onClick={() => copy(code)}
          >
            {copiedText ? (
              <Check className="h-3 w-3 text-green-500" />
            ) : (
              <Copy className="h-3 w-3" />
            )}
          </Button>
        </div>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-2 w-2 rounded-full ${
              meetingState === "active"
                ? "bg-green-500"
                : meetingState === "waiting"
                  ? "bg-yellow-500"
                  : "bg-gray-400"
            }`}
          />
          <span className="text-xs text-muted-foreground capitalize">
            {meetingState}
          </span>
        </div>
      </div>
      {meetingState !== "ended" && (
        <Button variant="destructive" size="sm" onClick={onEndMeeting}>
          <PhoneOff className="mr-2 h-4 w-4" />
          End
        </Button>
      )}
    </header>
  )
}
