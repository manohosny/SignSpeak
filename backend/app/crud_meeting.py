import uuid
from datetime import datetime

from sqlalchemy.orm import selectinload
from sqlmodel import func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models import (
    Meeting,
    MeetingMessage,
    MeetingParticipant,
    MeetingStatus,
    MessageType,
    ParticipantRole,
)

# ============================================================
# MEETING
# ============================================================


async def create_meeting(
    *, session: AsyncSession, host_id: uuid.UUID, code: str
) -> Meeting:
    meeting = Meeting(host_id=host_id, code=code, status=MeetingStatus.waiting)
    session.add(meeting)
    await session.flush()
    await session.refresh(meeting)
    return meeting


async def get_meeting_by_code(
    *, session: AsyncSession, code: str
) -> Meeting | None:
    statement = (
        select(Meeting)
        .where(Meeting.code == code)
        .options(selectinload(Meeting.participants))  # type: ignore
    )
    result = await session.exec(statement)
    return result.first()


async def get_meeting_by_id(
    *, session: AsyncSession, meeting_id: uuid.UUID
) -> Meeting | None:
    statement = (
        select(Meeting)
        .where(Meeting.id == meeting_id)
        .options(selectinload(Meeting.participants))  # type: ignore
    )
    result = await session.exec(statement)
    return result.first()


async def update_meeting(*, session: AsyncSession, meeting: Meeting) -> Meeting:
    session.add(meeting)
    await session.flush()
    await session.refresh(meeting)
    return meeting


# ============================================================
# PARTICIPANT
# ============================================================


async def get_participants(
    *, session: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingParticipant]:
    statement = select(MeetingParticipant).where(
        MeetingParticipant.meeting_id == meeting_id
    )
    result = await session.exec(statement)
    return list(result.all())


async def get_participant(
    *, session: AsyncSession, meeting_id: uuid.UUID, user_id: uuid.UUID
) -> MeetingParticipant | None:
    statement = select(MeetingParticipant).where(
        MeetingParticipant.meeting_id == meeting_id,
        MeetingParticipant.user_id == user_id,
    )
    result = await session.exec(statement)
    return result.first()


async def add_participant(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    user_id: uuid.UUID,
    role: ParticipantRole,
) -> MeetingParticipant:
    participant = MeetingParticipant(
        meeting_id=meeting_id, user_id=user_id, role=role
    )
    session.add(participant)
    await session.flush()
    await session.refresh(participant)
    return participant


async def mark_participant_left(
    *, session: AsyncSession, participant: MeetingParticipant, left_at: datetime
) -> None:
    participant.left_at = left_at
    session.add(participant)


async def get_active_participants(
    *, session: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingParticipant]:
    statement = select(MeetingParticipant).where(
        MeetingParticipant.meeting_id == meeting_id,
        MeetingParticipant.left_at.is_(None),  # type: ignore
    )
    result = await session.exec(statement)
    return list(result.all())


# ============================================================
# MESSAGE
# ============================================================


async def save_message(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    msg_type: MessageType,
) -> MeetingMessage:
    message = MeetingMessage(
        meeting_id=meeting_id,
        sender_id=sender_id,
        content=content,
        msg_type=msg_type,
    )
    session.add(message)
    await session.flush()
    await session.refresh(message)
    return message


async def get_messages(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    limit: int = 50,
    before: datetime | None = None,
) -> list[MeetingMessage]:
    statement = select(MeetingMessage).where(
        MeetingMessage.meeting_id == meeting_id
    )
    if before:
        statement = statement.where(
            MeetingMessage.created_at < before  # type: ignore
        )
    statement = (
        statement.order_by(MeetingMessage.created_at.desc())  # type: ignore
        .limit(limit + 1)  # fetch one extra to determine next page
    )
    result = await session.exec(statement)
    return list(result.all())


# ============================================================
# USER MEETINGS
# ============================================================


async def get_user_meetings(
    *, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 20
) -> tuple[list[Meeting], int]:
    # Subquery: meeting IDs where user is a participant
    participant_subq = select(MeetingParticipant.meeting_id).where(
        MeetingParticipant.user_id == user_id
    )

    # Count total
    count_statement = (
        select(func.count())
        .select_from(MeetingParticipant)
        .where(MeetingParticipant.user_id == user_id)
    )
    count_result = await session.exec(count_statement)
    count = count_result.one()

    # Fetch paginated meetings
    statement = (
        select(Meeting)
        .where(Meeting.id.in_(participant_subq))  # type: ignore
        .options(selectinload(Meeting.participants))  # type: ignore
        .order_by(Meeting.created_at.desc())  # type: ignore
        .offset(skip)
        .limit(limit)
    )
    result = await session.exec(statement)
    meetings = list(result.all())

    return meetings, count
