// ── WebSocket message types (not in OpenAPI, defined manually) ──

// Client → Server (JSON)
export type WsAuthMessage = { type: "auth"; token: string }
export type WsTextMessage = { type: "text_message"; content: string }
export type WsLeaveMessage = { type: "leave" }
export type WsEndMeetingMessage = { type: "end_meeting" }

export type WsClientMessage =
  | WsAuthMessage
  | WsTextMessage
  | WsLeaveMessage
  | WsEndMeetingMessage

// Server → Client (JSON)
export type WsAuthOk = {
  type: "auth_ok"
  user_id: string
  role: "speaker" | "reader"
  meeting_id: string
}
export type WsAuthError = { type: "auth_error"; message: string }
export type WsTranscript = {
  type: "transcript"
  text: string
  is_partial: boolean
  sender_id: string
  timestamp: string
}
export type WsTextMsg = {
  type: "text_message"
  content: string
  sender_id: string
  timestamp: string
}
export type WsUserJoined = {
  type: "user_joined"
  user_id: string
  display_name: string
  role: "speaker" | "reader"
}
export type WsUserLeft = {
  type: "user_left"
  user_id: string
  display_name: string
}
export type WsMeetingEnded = { type: "meeting_ended" }
export type WsError = { type: "error"; message: string }

export type WsServerMessage =
  | WsAuthOk
  | WsAuthError
  | WsTranscript
  | WsTextMsg
  | WsUserJoined
  | WsUserLeft
  | WsMeetingEnded
  | WsError

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
}
