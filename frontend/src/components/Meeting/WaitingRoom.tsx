import { Check, Copy, Loader2 } from "lucide-react"

import { Button } from "@/components/ui/button"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

interface WaitingRoomProps {
  code: string
}

export function WaitingRoom({ code }: WaitingRoomProps) {
  const [copiedText, copy] = useCopyToClipboard()

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 p-8">
      <div className="text-center">
        <h2 className="text-2xl font-bold">Meeting Code</h2>
        <p className="mt-1 text-muted-foreground">
          Share this code with your partner to join
        </p>
      </div>

      <div className="flex items-center gap-3 rounded-xl border bg-muted/50 px-8 py-4">
        <code className="text-4xl font-bold tracking-widest">{code}</code>
        <Button variant="outline" size="icon" onClick={() => copy(code)}>
          {copiedText ? (
            <Check className="h-5 w-5 text-green-500" />
          ) : (
            <Copy className="h-5 w-5" />
          )}
        </Button>
      </div>

      <div className="flex items-center gap-2 text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        <span>Waiting for partner to join...</span>
      </div>
    </div>
  )
}
