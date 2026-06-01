import { createFileRoute, Link, redirect } from "@tanstack/react-router"
import { Loader2 } from "lucide-react"
import { useState } from "react"

import { MeetingErrorBoundary } from "@/components/Meeting/MeetingErrorBoundary"
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
  // Bump to force a clean remount of the meeting subtree when the user clicks
  // "Rejoin meeting" from the error fallback.
  const [resetKey, setResetKey] = useState(0)
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
    isPartnerSpeaking,
    micError,
    hasPendingAudio,
    retry,
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
        <MeetingErrorBoundary
          resetKey={resetKey}
          onReset={() => setResetKey((k) => k + 1)}
        >
          <SpeakerView
            key={resetKey}
            isMicOn={isMicOn}
            isSpeaking={isSpeaking}
            isPartnerSpeaking={isPartnerSpeaking}
            onToggleMic={toggleMic}
            micError={micError}
            hasPendingAudio={hasPendingAudio}
          />
        </MeetingErrorBoundary>
      )}

      {meetingState === "active" && role === "reader" && (
        <MeetingErrorBoundary
          resetKey={resetKey}
          onReset={() => setResetKey((k) => k + 1)}
        >
          <ReaderView
            key={resetKey}
            glosses={glosses}
            onSendGloss={sendGlossMessage}
          />
        </MeetingErrorBoundary>
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
          <div className="flex gap-2">
            <Button onClick={retry}>Retry</Button>
            <Button variant="outline" asChild>
              <Link to="/">Back to Dashboard</Link>
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
