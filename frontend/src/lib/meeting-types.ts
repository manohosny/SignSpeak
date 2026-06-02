// Server → Client message types are inferred from runtime schemas in
// `meeting-schemas.ts` (single source of truth). Client → Server types
// remain hand-written here since they're emitted by us, not validated.

export type {
  WsAuthError,
  WsAuthOk,
  WsError,
  WsGloss,
  WsGlossError,
  WsGlossMsg,
  WsMeetingEnded,
  WsServerMessage,
  WsServerShutdown,
  WsSignText,
  WsTextMsg,
  WsTranscript,
  WsTtsEnd,
  WsTtsStart,
  WsUserJoined,
  WsUserLeft,
} from "./meeting-schemas"

// ── Client → Server (JSON) ──
export type WsAuthMessage = { type: "auth"; token: string }
export type WsTextMessage = { type: "text_message"; content: string }
export type WsLeaveMessage = { type: "leave" }
export type WsEndMeetingMessage = { type: "end_meeting" }
export type WsControlMessage = {
  type: "control"
  action: "utterance_end" | "sign_segment_end"
}
export type WsGlossMessage = { type: "gloss_message"; content: string }

export type WsClientMessage =
  | WsAuthMessage
  | WsTextMessage
  | WsLeaveMessage
  | WsEndMeetingMessage
  | WsControlMessage
  | WsGlossMessage

// ── UI state ──

export type MeetingState =
  | "connecting"
  | "authenticating"
  | "waiting"
  | "active"
  | "ended"
  | "error"

export type TranscriptEntry = {
  id: string
  type: "transcript" | "text_message"
  content: string
  senderId: string
  senderRole: "speaker" | "reader"
  timestamp: string
  isPartial?: boolean
}

export type GlossEntry = {
  id: string
  type: "gloss" | "gloss_message"
  text: string
  utterance_id?: string
  timestamp: string
  isOwn: boolean
}
