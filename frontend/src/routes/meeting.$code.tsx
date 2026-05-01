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
    glosses,
    error,
    sendGlossMessage,
    endMeeting,
    toggleMic,
    isMicOn,
    isSpeaking,
    hasPendingAudio,
  } = useMeeting(code)

  return (
    <div className="flex h-dvh flex-col">
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
        <SpeakerView
          isMicOn={isMicOn}
          isSpeaking={isSpeaking}
          onToggleMic={toggleMic}
          hasPendingAudio={hasPendingAudio}
        />
      )}

      {meetingState === "active" && role === "reader" && (
        <ReaderView glosses={glosses} onSendGloss={sendGlossMessage} />
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
