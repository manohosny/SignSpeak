import enum
import random
import string
import uuid
from datetime import datetime, timezone

from pydantic import EmailStr
from sqlalchemy import Column, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


def generate_meeting_code() -> str:
    """Generate a human-readable meeting code like 'XKF-8291'."""
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    digits = "".join(random.choices(string.digits, k=4))
    return f"{letters}-{digits}"


# ============================================================
# ENUMS
# ============================================================


class MeetingStatus(str, enum.Enum):
    waiting = "waiting"
    active = "active"
    ended = "ended"


class ParticipantRole(str, enum.Enum):
    speaker = "speaker"
    reader = "reader"


class MessageType(str, enum.Enum):
    speech_transcript = "speech_transcript"
    text_message = "text_message"
    gloss_translation = "gloss_translation"
    gloss_input = "gloss_input"


# ============================================================
# USER
# ============================================================


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: EmailStr | None = Field(default=None, max_length=255)  # type: ignore
    password: str | None = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    hashed_password: str
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    # --- Relationships ---
    hosted_meetings: list["Meeting"] = Relationship(back_populates="host")
    participations: list["MeetingParticipant"] = Relationship(
        back_populates="user"
    )
    sent_messages: list["MeetingMessage"] = Relationship(
        back_populates="sender"
    )


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: datetime | None = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# ============================================================
# MEETING
# ============================================================


class MeetingBase(SQLModel):
    """Shared readable properties of a meeting."""

    code: str = Field(
        default_factory=generate_meeting_code,
        max_length=10,
        unique=True,
        index=True,
    )
    status: MeetingStatus = Field(
        default=MeetingStatus.waiting,
        sa_column=Column(
            Enum(MeetingStatus, name="meetingstatus", create_constraint=True),
            nullable=False,
            server_default=MeetingStatus.waiting.value,
        ),
    )


class Meeting(MeetingBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    host_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        )
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    started_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    ended_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    # --- Relationships ---
    host: User = Relationship(back_populates="hosted_meetings")
    participants: list["MeetingParticipant"] = Relationship(
        back_populates="meeting",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    messages: list["MeetingMessage"] = Relationship(
        back_populates="meeting",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


# --- Meeting API Schemas ---


class MeetingJoin(SQLModel):
    """Body for POST /api/v1/meetings/{code}/join."""

    role: ParticipantRole = ParticipantRole.reader


class MeetingPublic(SQLModel):
    """Returned after creating or fetching a meeting."""

    model_config = {"from_attributes": True}  # type: ignore[assignment]

    id: uuid.UUID
    code: str
    status: MeetingStatus
    host_id: uuid.UUID
    created_at: datetime | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    participants: list["MeetingParticipantPublic"] = []


class MeetingsPublic(SQLModel):
    """Paginated list of meetings (e.g., user history)."""

    data: list[MeetingPublic]
    count: int


# ============================================================
# MEETING PARTICIPANT
# ============================================================


class MeetingParticipantBase(SQLModel):
    role: ParticipantRole = Field(
        sa_column=Column(
            Enum(
                ParticipantRole,
                name="participantrole",
                create_constraint=True,
            ),
            nullable=False,
        ),
    )


class MeetingParticipant(MeetingParticipantBase, table=True):
    __tablename__ = "meeting_participant"
    __table_args__ = (
        UniqueConstraint("meeting_id", "user_id", name="uq_meeting_user"),
    )

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meeting_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False
        )
    )
    user_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        )
    )
    joined_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    left_at: datetime | None = Field(
        default=None,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    # --- Relationships ---
    meeting: Meeting = Relationship(back_populates="participants")
    user: User = Relationship(back_populates="participations")


# --- Participant API Schemas ---


class MeetingParticipantPublic(SQLModel):
    model_config = {"from_attributes": True}  # type: ignore[assignment]

    id: uuid.UUID
    user_id: uuid.UUID
    role: ParticipantRole
    joined_at: datetime | None = None
    left_at: datetime | None = None


# ============================================================
# MEETING MESSAGE
# ============================================================


class MeetingMessageBase(SQLModel):
    content: str = Field(max_length=5000)
    msg_type: MessageType = Field(
        sa_column=Column(
            Enum(MessageType, name="messagetype", create_constraint=True),
            nullable=False,
        ),
    )


class MeetingMessage(MeetingMessageBase, table=True):
    __tablename__ = "meeting_message"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    meeting_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("meeting.id", ondelete="CASCADE"), nullable=False
        )
    )
    sender_id: uuid.UUID = Field(
        sa_column=Column(
            ForeignKey("user.id", ondelete="CASCADE"), nullable=False
        )
    )
    created_at: datetime | None = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )

    # --- Relationships ---
    meeting: Meeting = Relationship(back_populates="messages")
    sender: User = Relationship(back_populates="sent_messages")


# --- Message API Schemas ---


class MeetingMessageCreate(SQLModel):
    """Used internally when saving a message (not exposed as API body)."""

    content: str = Field(max_length=5000)
    msg_type: MessageType


class MeetingMessagePublic(SQLModel):
    model_config = {"from_attributes": True}  # type: ignore[assignment]

    id: uuid.UUID
    meeting_id: uuid.UUID
    sender_id: uuid.UUID
    content: str
    msg_type: MessageType
    created_at: datetime | None = None


class MeetingMessagesPublic(SQLModel):
    """Paginated message list for GET /api/v1/meetings/{id}/messages."""

    data: list[MeetingMessagePublic]
    count: int
    next_cursor: str | None = None


# ============================================================
# GENERIC SCHEMAS
# ============================================================


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: str | None = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
