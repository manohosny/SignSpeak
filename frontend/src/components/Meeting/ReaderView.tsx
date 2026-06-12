import type { GlossEntry, SignTextState } from "@/lib/meeting-types"
import { AvatarView } from "./AvatarView"
import { SignCaptureView } from "./SignCaptureView"
import { TextInput } from "./TextInput"

interface ReaderViewProps {
  /** Direction A: gloss entries the avatar signs (the speaker's translated speech). */
  glosses: GlossEntry[]
  /** Direction B: send packed binary keypoint frames from the reader's webcam. */
  onKeypointFrame: (frame: ArrayBuffer) => void
  /** Direction B: force a sentence boundary (control: sign_segment_end). */
  onEndSentence: () => void
  /** Direction B: English recognized from the reader's signing (server echo). */
  signText: SignTextState | null
  /** Manual override: type a message instead of signing (text_message → TTS). */
  onSendText: (content: string) => void
  /** Meeting UUID — lets the reader flag a wrong translation. */
  meetingId?: string | null
  disabled?: boolean
}

export function ReaderView({
  glosses,
  onKeypointFrame,
  onEndSentence,
  signText,
  onSendText,
  meetingId,
  disabled,
}: ReaderViewProps) {
  return (
    <div className="relative flex flex-1 flex-col">
      {/* Direction A: watch the speaker's words signed by the avatar. */}
      <AvatarView entries={glosses} />
      {/* Direction B: sign to speak — webcam -> keypoints -> English -> TTS. */}
      <SignCaptureView
        onKeypointFrame={onKeypointFrame}
        onEndSentence={onEndSentence}
        signText={signText}
        meetingId={meetingId}
        disabled={disabled}
      />
      {/* Fallback for when recognition keeps gating the reader's signs:
          typed messages take the same text_message → TTS path. */}
      <TextInput onSend={onSendText} disabled={disabled} />
    </div>
  )
}
