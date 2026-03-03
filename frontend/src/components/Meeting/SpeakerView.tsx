import { MicButton } from "./MicButton"

interface SpeakerViewProps {
  isMicOn: boolean
  onToggleMic: () => void
  micError?: string | null
}

export function SpeakerView({
  isMicOn,
  onToggleMic,
  micError,
}: SpeakerViewProps) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6">
      <div className="text-center">
        <h2 className="text-xl font-semibold">You are the Speaker</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Speak into your microphone — your partner will see the transcript.
          <br />
          Their replies will be read aloud to you.
        </p>
      </div>
      <MicButton isOn={isMicOn} onToggle={onToggleMic} error={micError} />
    </div>
  )
}
