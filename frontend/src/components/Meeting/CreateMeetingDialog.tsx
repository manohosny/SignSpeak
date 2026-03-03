import { useNavigate } from "@tanstack/react-router"
import { Check, Copy, Plus } from "lucide-react"
import { useState } from "react"
import { type MeetingPublic, MeetingsService } from "@/client"
import { Button } from "@/components/ui/button"
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog"
import { useCopyToClipboard } from "@/hooks/useCopyToClipboard"

export function CreateMeetingDialog() {
  const [isOpen, setIsOpen] = useState(false)
  const [meeting, setMeeting] = useState<MeetingPublic | null>(null)
  const [isPending, setIsPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [copiedText, copy] = useCopyToClipboard()
  const navigate = useNavigate()

  const handleCreate = async () => {
    setIsPending(true)
    setError(null)
    try {
      const m = await MeetingsService.createMeeting()
      setMeeting(m)
    } catch {
      setError("Failed to create meeting")
    } finally {
      setIsPending(false)
    }
  }

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open)
    if (!open) {
      setMeeting(null)
      setError(null)
    }
  }

  const handleJoin = () => {
    if (meeting) {
      navigate({ to: "/meeting/$code", params: { code: meeting.code } })
    }
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button>
          <Plus className="mr-2 h-4 w-4" />
          New Meeting
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>
            {meeting ? "Meeting Created" : "Create Meeting"}
          </DialogTitle>
          <DialogDescription>
            {meeting
              ? "Share this code with your partner to join the meeting."
              : "Start a new meeting as the speaker. You'll get a code to share."}
          </DialogDescription>
        </DialogHeader>

        {meeting ? (
          <div className="py-4">
            <div className="flex items-center gap-2 rounded-lg border bg-muted/50 p-4">
              <code className="flex-1 text-center text-2xl font-bold tracking-widest">
                {meeting.code}
              </code>
              <Button
                variant="outline"
                size="icon"
                onClick={() => copy(meeting.code)}
              >
                {copiedText ? (
                  <Check className="h-4 w-4 text-green-500" />
                ) : (
                  <Copy className="h-4 w-4" />
                )}
              </Button>
            </div>
          </div>
        ) : error ? (
          <p className="py-4 text-sm text-destructive">{error}</p>
        ) : null}

        <DialogFooter>
          {meeting ? (
            <>
              <DialogClose asChild>
                <Button variant="outline">Close</Button>
              </DialogClose>
              <Button onClick={handleJoin}>Join Meeting</Button>
            </>
          ) : (
            <>
              <DialogClose asChild>
                <Button variant="outline" disabled={isPending}>
                  Cancel
                </Button>
              </DialogClose>
              <Button onClick={handleCreate} disabled={isPending}>
                {isPending ? "Creating..." : "Create"}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
