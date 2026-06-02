"""Pydantic schemas for WebSocket client → server messages.

Server → client messages are documented in `app/ws/router.py` and
`frontend/src/lib/meeting-schemas.ts`; only the client-side schema is
strictly enforced because that's the trust boundary. Each variant carries
a literal `type` discriminator so a discriminated-union parse rejects
unknown / malformed payloads up-front.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _WsMessageBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WsAuthMessage(_WsMessageBase):
    type: Literal["auth"]
    token: str = Field(min_length=1, max_length=4096)


class WsGlossMessage(_WsMessageBase):
    type: Literal["gloss_message"]
    content: str = Field(min_length=1, max_length=5000)


class WsLeaveMessage(_WsMessageBase):
    type: Literal["leave"]


class WsEndMeetingMessage(_WsMessageBase):
    type: Literal["end_meeting"]


class WsControlMessage(_WsMessageBase):
    type: Literal["control"]
    # utterance_end: speaker VAD boundary (STT). sign_segment_end: reader's
    # explicit "end sentence" cue (Direction B) -> force-flush the segment buffer.
    action: Literal["utterance_end", "sign_segment_end"]


class WsTextMessage(_WsMessageBase):
    """Text chat message (separate from STT transcripts)."""

    type: Literal["text_message"]
    content: str = Field(min_length=1, max_length=5000)


WsClientMessage = Annotated[
    Union[
        WsAuthMessage,
        WsGlossMessage,
        WsLeaveMessage,
        WsEndMeetingMessage,
        WsControlMessage,
        WsTextMessage,
    ],
    Field(discriminator="type"),
]
