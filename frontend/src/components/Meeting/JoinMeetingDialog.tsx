import { useNavigate } from "@tanstack/react-router"
import { LogIn } from "lucide-react"
import { useState } from "react"
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
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"

export function JoinMeetingDialog() {
  const [isOpen, setIsOpen] = useState(false)
  const [code, setCode] = useState("")
  const navigate = useNavigate()

  const handleJoin = () => {
    const trimmed = code.trim()
    if (trimmed) {
      navigate({ to: "/meeting/$code", params: { code: trimmed } })
    }
  }

  const handleOpenChange = (open: boolean) => {
    setIsOpen(open)
    if (!open) setCode("")
  }

  return (
    <Dialog open={isOpen} onOpenChange={handleOpenChange}>
      <DialogTrigger asChild>
        <Button variant="outline">
          <LogIn className="mr-2 h-4 w-4" />
          Join Meeting
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form
          onSubmit={(e) => {
            e.preventDefault()
            handleJoin()
          }}
        >
          <DialogHeader>
            <DialogTitle>Join Meeting</DialogTitle>
            <DialogDescription>
              Enter the meeting code shared by the speaker.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 py-4">
            <div className="grid gap-2">
              <Label htmlFor="meeting-code">Meeting Code</Label>
              <Input
                id="meeting-code"
                placeholder="Enter meeting code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
            <Button type="submit" disabled={!code.trim()}>
              Join
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
