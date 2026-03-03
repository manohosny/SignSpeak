import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"

import { MeetingHeader } from "@/components/Meeting/MeetingHeader"
import { ReaderView } from "@/components/Meeting/ReaderView"
import { SpeakerView } from "@/components/Meeting/SpeakerView"
import { WaitingRoom } from "@/components/Meeting/WaitingRoom"
import { Button } from "@/components/ui/button"
import { isLoggedIn } from "@/hooks/useAuth"
import { useMeeting } from "@/hooks/useMeeting"

export const Route = createFileRoute("/meeting/$code")({
  component: MeetingRoom,
  beforeLoad: async () => {
    if (!isLoggedIn()) {
      throw redirect({ to: "/login" })
    }
  },
  head: () => ({
    meta: [{ title: "Meeting - SignSpeak" }],
  }),
})

function MeetingRoom() {
  const { code } = Route.useParams()
  const {
    meetingState,
    role,
    transcript,
    error,
    sendTextMessage,
    endMeeting,
    toggleMic,
    isMicOn,
    unlockAudio,
  } = useMeeting(code)

  return (
    // biome-ignore lint/a11y/useKeyWithClickEvents: audio unlock doesn't need keyboard
    // biome-ignore lint/a11y/noStaticElementInteractions: unlocks audio on first click
    <div className="flex h-dvh flex-col" onClick={unlockAudio}>
      <MeetingHeader
        code={code}
        meetingState={meetingState}
        onEndMeeting={endMeeting}
      />

      {(meetingState === "connecting" || meetingState === "authenticating") && (
        <div className="flex flex-1 items-center justify-center">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      )}

      {meetingState === "waiting" && <WaitingRoom code={code} />}

      {meetingState === "active" && role === "speaker" && (
        <SpeakerView isMicOn={isMicOn} onToggleMic={toggleMic} />
      )}

      {meetingState === "active" && role === "reader" && (
        <ReaderView transcript={transcript} onSendMessage={sendTextMessage} />
      )}

      {meetingState === "ended" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <h2 className="text-2xl font-bold">Meeting Ended</h2>
          <p className="text-muted-foreground">The meeting has been ended.</p>
          <Button asChild>
            <Link to="/">Back to Dashboard</Link>
          </Button>
        </div>
      )}

      {meetingState === "error" && (
        <div className="flex flex-1 flex-col items-center justify-center gap-4">
          <h2 className="text-2xl font-bold text-destructive">Error</h2>
          <p className="text-muted-foreground">
            {error || "Something went wrong."}
          </p>
          <Button asChild>
            <Link to="/">Back to Dashboard</Link>
          </Button>
        </div>
      )}
    </div>
  )
}
