import { Volume2 } from "lucide-react"

import type { TranscriptEntry } from "@/lib/meeting-types"

import { MicButton } from "./MicButton"
import { TranscriptPanel } from "./TranscriptPanel"

interface SpeakerViewProps {
  isMicOn: boolean
  isSpeaking?: boolean
  /** True while the partner's gloss is being spoken back as TTS. */
  isPartnerSpeaking?: boolean
  onToggleMic: () => void
  micError?: string | null
  hasPendingAudio?: boolean
  /** Live STT feed — lets the speaker verify what the system heard. */
  transcript: TranscriptEntry[]
}

export function SpeakerView({
  isMicOn,
  isSpeaking,
  isPartnerSpeaking,
  onToggleMic,
  micError,
  hasPendingAudio,
  transcript,
}: SpeakerViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex flex-col items-center justify-center gap-6 px-4 py-8">
        <div className="text-center">
          <h2 className="text-xl font-semibold">You are the Speaker</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Speak into your microphone — your partner will see the transcript.
            <br />
            Their replies will be read aloud to you.
          </p>
        </div>
        {hasPendingAudio && (
          <div className="animate-pulse rounded-lg bg-primary/10 px-4 py-2 text-sm text-primary">
            Tap anywhere to enable audio
          </div>
        )}
        <MicButton
          isOn={isMicOn}
          isSpeaking={isSpeaking}
          onToggle={onToggleMic}
          error={micError}
        />
        {/* `<output>` carries an implicit role=status, so screen-reader
            users get the same speaking signal that sighted users see. */}
        <output
          aria-live="polite"
          className="flex h-6 items-center gap-2 text-sm text-muted-foreground"
        >
          {isPartnerSpeaking ? (
            <>
              <Volume2
                className="h-4 w-4 animate-pulse text-primary"
                aria-hidden="true"
              />
              <span>Partner is speaking…</span>
            </>
          ) : null}
        </output>
      </div>
      {/* What the system heard — scrollable, below the mic so it never
          crowds the primary control. */}
      <section
        aria-label="Conversation transcript"
        className="flex min-h-0 flex-1 flex-col border-t"
      >
        <TranscriptPanel entries={transcript} currentRole="speaker" />
      </section>
    </div>
  )
}
