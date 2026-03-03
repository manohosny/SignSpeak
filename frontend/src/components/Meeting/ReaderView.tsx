import type { TranscriptEntry } from "@/lib/meeting-types"
import { TextInput } from "./TextInput"
import { TranscriptPanel } from "./TranscriptPanel"

interface ReaderViewProps {
  transcript: TranscriptEntry[]
  onSendMessage: (message: string) => void
  disabled?: boolean
}

export function ReaderView({
  transcript,
  onSendMessage,
  disabled,
}: ReaderViewProps) {
  return (
    <div className="flex flex-1 flex-col">
      <TranscriptPanel entries={transcript} currentRole="reader" />
      <TextInput onSend={onSendMessage} disabled={disabled} />
    </div>
  )
}
