import { z } from "zod"

const role = z.enum(["speaker", "reader"])

// ── Server → Client (JSON, runtime-validated) ──

const WsAuthOkSchema = z.object({
  type: z.literal("auth_ok"),
  user_id: z.string(),
  role,
  meeting_id: z.string(),
})

const WsAuthErrorSchema = z.object({
  type: z.literal("auth_error"),
  message: z.string(),
})

const WsTranscriptSchema = z.object({
  type: z.literal("transcript"),
  text: z.string(),
  is_partial: z.boolean(),
  utterance_id: z.string().optional(),
  sender_id: z.string(),
  timestamp: z.string(),
})

const WsTextMessageSchema = z.object({
  type: z.literal("text_message"),
  content: z.string(),
  sender_id: z.string(),
  timestamp: z.string(),
})

const WsUserJoinedSchema = z.object({
  type: z.literal("user_joined"),
  user_id: z.string(),
  display_name: z.string(),
  role,
})

const WsUserLeftSchema = z.object({
  type: z.literal("user_left"),
  user_id: z.string(),
  display_name: z.string(),
})

const WsMeetingEndedSchema = z.object({ type: z.literal("meeting_ended") })

const WsErrorSchema = z.object({
  type: z.literal("error"),
  message: z.string(),
})

const WsTtsStartSchema = z.object({ type: z.literal("tts_start") })
const WsTtsEndSchema = z.object({ type: z.literal("tts_end") })

const WsGlossSchema = z.object({
  type: z.literal("gloss"),
  text: z.string(),
  utterance_id: z.string().optional(),
  sender_id: z.string(),
  timestamp: z.string(),
})

const WsGlossMessageSchema = z.object({
  type: z.literal("gloss_message"),
  content: z.string(),
  sender_id: z.string(),
  timestamp: z.string(),
})

const WsGlossErrorSchema = z.object({
  type: z.literal("gloss_error"),
  utterance_id: z.string().optional(),
  message: z.string(),
})

// Recognized English from gloss-free sign recognition (Direction B), echoed
// back to the Reader for confirmation (the Speaker hears it via TTS). The
// same message type carries the pending-sign feedback ("HELLO …"), the
// partial sentence as it builds, and the finalized sentence.
const WsSignTextSchema = z.object({
  type: z.literal("sign_text"),
  content: z.string(),
  sender_id: z.string(),
  timestamp: z.string(),
  // Recognition certainty in 0..1 — optional because older servers don't
  // send it. The UI shows a "low confidence" hint when present and < 0.5.
  confidence: z.number().optional(),
  // Persisted-message UUID, present only on the finalized sentence — lets
  // the reader flag a wrong translation via the REST flag endpoint.
  message_id: z.string().optional(),
})

const WsServerShutdownSchema = z.object({
  type: z.literal("server_shutdown"),
  reason: z.string().optional(),
})

export const WsServerMessageSchema = z.discriminatedUnion("type", [
  WsAuthOkSchema,
  WsAuthErrorSchema,
  WsTranscriptSchema,
  WsTextMessageSchema,
  WsUserJoinedSchema,
  WsUserLeftSchema,
  WsMeetingEndedSchema,
  WsErrorSchema,
  WsTtsStartSchema,
  WsTtsEndSchema,
  WsGlossSchema,
  WsGlossMessageSchema,
  WsGlossErrorSchema,
  WsSignTextSchema,
  WsServerShutdownSchema,
])

export type WsServerMessage = z.infer<typeof WsServerMessageSchema>
export type WsAuthOk = z.infer<typeof WsAuthOkSchema>
export type WsAuthError = z.infer<typeof WsAuthErrorSchema>
export type WsTranscript = z.infer<typeof WsTranscriptSchema>
export type WsTextMsg = z.infer<typeof WsTextMessageSchema>
export type WsUserJoined = z.infer<typeof WsUserJoinedSchema>
export type WsUserLeft = z.infer<typeof WsUserLeftSchema>
export type WsMeetingEnded = z.infer<typeof WsMeetingEndedSchema>
export type WsError = z.infer<typeof WsErrorSchema>
export type WsTtsStart = z.infer<typeof WsTtsStartSchema>
export type WsTtsEnd = z.infer<typeof WsTtsEndSchema>
export type WsGloss = z.infer<typeof WsGlossSchema>
export type WsGlossMsg = z.infer<typeof WsGlossMessageSchema>
export type WsGlossError = z.infer<typeof WsGlossErrorSchema>
export type WsSignText = z.infer<typeof WsSignTextSchema>
export type WsServerShutdown = z.infer<typeof WsServerShutdownSchema>
