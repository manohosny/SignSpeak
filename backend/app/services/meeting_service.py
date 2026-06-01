import uuid
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud_meeting
from app.errors import (
    raise_already_in_meeting,
    raise_code_generation_failed,
    raise_meeting_already_ended,
    raise_meeting_full,
    raise_meeting_in_progress,
    raise_meeting_not_found,
    raise_not_authorized_end_meeting,
    raise_not_meeting_participant,
)
from app.models import (
    Meeting,
    MeetingMessage,
    MeetingStatus,
    MessageType,
    ParticipantRole,
    User,
    generate_meeting_code,
)

# ============================================================
# MEETING OPERATIONS
# ============================================================


async def create_meeting(*, session: AsyncSession, host: User) -> Meeting:
    """Host creates a new meeting. They are automatically added
    as a participant with the 'speaker' role."""
    # Retry on code collision (UNIQUE constraint on Meeting.code)
    for _ in range(5):
        code = generate_meeting_code()
        try:
            meeting = await crud_meeting.create_meeting(
                session=session, host_id=host.id, code=code
            )
            await crud_meeting.add_participant(
                session=session,
                meeting_id=meeting.id,
                user_id=host.id,
                role=ParticipantRole.speaker,
            )
            await session.commit()
            break
        except IntegrityError:
            await session.rollback()
    else:
        raise_code_generation_failed()

    # Re-fetch with participants loaded
    return await _get_meeting_or_404(session=session, meeting_id=meeting.id)


async def get_meeting_by_code(*, session: AsyncSession, code: str) -> Meeting:
    meeting = await crud_meeting.get_meeting_by_code(session=session, code=code)
    if not meeting:
        raise_meeting_not_found()
    return meeting


async def join_meeting(
    *,
    session: AsyncSession,
    meeting: Meeting,
    user: User,
    role: ParticipantRole = ParticipantRole.reader,
) -> Meeting:
    """A user joins an existing meeting. Validates status, capacity, and uniqueness."""
    # Serialize concurrent joins on this meeting. Without a row lock the
    # participant-count check and the waiting→active transition below can
    # interleave: two readers joining at once both observe one participant,
    # both insert, and neither flips the meeting to `active` — leaving it
    # stuck in `waiting` with both people present. `refresh` with
    # `with_for_update=True` issues SELECT ... FOR UPDATE and re-reads the
    # row, so the status checks below see committed state. The lock is held
    # until this function commits.
    await session.refresh(meeting, with_for_update=True)

    if meeting.status == MeetingStatus.ended:
        raise_meeting_already_ended()

    if meeting.status == MeetingStatus.active:
        raise_meeting_in_progress()

    existing_participants = await crud_meeting.get_participants(
        session=session, meeting_id=meeting.id
    )

    if len(existing_participants) >= 2:
        raise_meeting_full()

    for participant in existing_participants:
        if participant.user_id == user.id:
            raise_already_in_meeting()

    # Prevent two participants from having the same role
    existing_roles = {participant.role for participant in existing_participants}
    if role in existing_roles:
        role = (
            ParticipantRole.reader
            if ParticipantRole.speaker in existing_roles
            else ParticipantRole.speaker
        )

    await crud_meeting.add_participant(
        session=session,
        meeting_id=meeting.id,
        user_id=user.id,
        role=role,
    )

    # Both participants present → activate the meeting
    if len(existing_participants) + 1 == 2:
        meeting.status = MeetingStatus.active
        meeting.started_at = datetime.now(timezone.utc)
        session.add(meeting)

    await session.commit()
    return await _get_meeting_or_404(session=session, meeting_id=meeting.id)


async def end_meeting(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    current_user: User,
) -> None:
    """End a meeting. Only the host or a participant can end it."""
    meeting = await _get_meeting_or_404(session=session, meeting_id=meeting_id)

    # Authorization: only host or participant can end
    participant = await crud_meeting.get_participant(
        session=session, meeting_id=meeting_id, user_id=current_user.id
    )
    if not participant and meeting.host_id != current_user.id:
        raise_not_authorized_end_meeting()

    if meeting.status == MeetingStatus.ended:
        raise_meeting_already_ended()

    now = datetime.now(timezone.utc)
    meeting.status = MeetingStatus.ended
    meeting.ended_at = now
    session.add(meeting)

    # Mark all active participants as left
    active_participants = await crud_meeting.get_active_participants(
        session=session, meeting_id=meeting_id
    )
    for participant in active_participants:
        await crud_meeting.mark_participant_left(
            session=session, participant=participant, left_at=now
        )

    await session.commit()


async def leave_meeting(
    *, session: AsyncSession, meeting_id: uuid.UUID, user_id: uuid.UUID
) -> None:
    """Mark a participant as having left the meeting."""
    participant = await crud_meeting.get_participant(
        session=session, meeting_id=meeting_id, user_id=user_id
    )
    if participant and participant.left_at is None:
        await crud_meeting.mark_participant_left(
            session=session,
            participant=participant,
            left_at=datetime.now(timezone.utc),
        )
        await session.commit()


async def get_user_meetings(
    *, session: AsyncSession, user_id: uuid.UUID, skip: int = 0, limit: int = 20
) -> tuple[list[Meeting], int]:
    return await crud_meeting.get_user_meetings(
        session=session, user_id=user_id, skip=skip, limit=limit
    )


# ============================================================
# MESSAGE OPERATIONS
# ============================================================


async def save_message(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    sender_id: uuid.UUID,
    content: str,
    msg_type: MessageType,
) -> MeetingMessage:
    message = await crud_meeting.save_message(
        session=session,
        meeting_id=meeting_id,
        sender_id=sender_id,
        content=content,
        msg_type=msg_type,
    )
    await session.commit()
    return message


async def get_meeting_messages(
    *,
    session: AsyncSession,
    meeting_id: uuid.UUID,
    user_id: uuid.UUID,
    limit: int = 50,
    before: datetime | None = None,
) -> tuple[list[MeetingMessage], str | None]:
    """Fetch messages with cursor-based pagination. Verifies user is a participant."""
    participant = await crud_meeting.get_participant(
        session=session, meeting_id=meeting_id, user_id=user_id
    )
    if not participant:
        raise_not_meeting_participant()

    messages = await crud_meeting.get_messages(
        session=session, meeting_id=meeting_id, limit=limit, before=before
    )

    next_cursor: str | None = None
    if len(messages) > limit:
        messages = messages[:limit]
        next_cursor = (
            messages[-1].created_at.isoformat() if messages[-1].created_at else None
        )

    # Return in chronological order
    messages.reverse()

    return messages, next_cursor


# ============================================================
# HELPERS
# ============================================================


async def _get_meeting_or_404(
    *, session: AsyncSession, meeting_id: uuid.UUID
) -> Meeting:
    meeting = await crud_meeting.get_meeting_by_id(
        session=session, meeting_id=meeting_id
    )
    if not meeting:
        raise_meeting_not_found()
    return meeting
