import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.core.metrics import MESSAGE_FLAGS
from app.models import (
    MeetingJoin,
    MeetingMessagePublic,
    MeetingMessagesPublic,
    MeetingPublic,
    MeetingsPublic,
    Message,
    MessageFlag,
)
from app.services import meeting_service

router = APIRouter(prefix="/meetings", tags=["meetings"])

# Bound list endpoints so a malicious client can't request a page of
# millions of rows and turn the API into a memory bomb. Defaults match
# previous behavior; the cap is what's new.
_MAX_PAGE_LIMIT = 200


# ============================================================
# MEETING ENDPOINTS
# ============================================================


@router.post(
    "/",
    response_model=MeetingPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_meeting(
    session: SessionDep,
    current_user: CurrentUser,
) -> MeetingPublic:
    """Create a new meeting. The authenticated user becomes the host (speaker).
    Returns the meeting details including the shareable code."""
    meeting = await meeting_service.create_meeting(session=session, host=current_user)
    return MeetingPublic.model_validate(meeting)


@router.get(
    "/{code}",
    response_model=MeetingPublic,
    dependencies=[Depends(get_current_user)],
)
async def get_meeting(
    code: str,
    session: SessionDep,
) -> MeetingPublic:
    """Get meeting details by its shareable code."""
    meeting = await meeting_service.get_meeting_by_code(session=session, code=code)
    return MeetingPublic.model_validate(meeting)


@router.post(
    "/{code}/join",
    response_model=MeetingPublic,
    status_code=status.HTTP_201_CREATED,
)
async def join_meeting(
    code: str,
    session: SessionDep,
    current_user: CurrentUser,
    body: MeetingJoin = MeetingJoin(),
) -> MeetingPublic:
    """Join an existing meeting by code. The joiner defaults to 'reader' role."""
    meeting = await meeting_service.get_meeting_by_code(session=session, code=code)
    updated_meeting = await meeting_service.join_meeting(
        session=session, meeting=meeting, user=current_user, role=body.role
    )
    return MeetingPublic.model_validate(updated_meeting)


@router.post(
    "/{meeting_id}/end",
    response_model=Message,
)
async def end_meeting(
    meeting_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Message:
    """End a meeting. Only the host or a participant can end it."""
    await meeting_service.end_meeting(
        session=session, meeting_id=meeting_id, current_user=current_user
    )
    return Message(message="Meeting ended successfully")


# ============================================================
# MESSAGE ENDPOINTS
# ============================================================


@router.get(
    "/{meeting_id}/messages",
    response_model=MeetingMessagesPublic,
)
async def get_messages(
    meeting_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int = Query(50, ge=1, le=_MAX_PAGE_LIMIT),
    before: datetime | None = None,
) -> MeetingMessagesPublic:
    """Get messages for a meeting. Supports cursor-based pagination.
    The 'before' param is an ISO datetime for fetching older messages."""
    messages, next_cursor = await meeting_service.get_meeting_messages(
        session=session,
        meeting_id=meeting_id,
        user_id=current_user.id,
        limit=limit,
        before=before,
    )

    return MeetingMessagesPublic(
        data=[MeetingMessagePublic.model_validate(m) for m in messages],
        count=len(messages),
        next_cursor=next_cursor,
    )


@router.post(
    "/{meeting_id}/messages/{message_id}/flag",
    response_model=MeetingMessagePublic,
)
async def flag_message(
    meeting_id: uuid.UUID,
    message_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    body: MessageFlag = MessageFlag(),
) -> MeetingMessagePublic:
    """Flag a message as a wrong translation/transcription (user feedback).

    Participant-only. Flagged messages form the labeled correction dataset
    that drives threshold tuning and model re-tuning."""
    message = await meeting_service.flag_message(
        session=session,
        meeting_id=meeting_id,
        message_id=message_id,
        user_id=current_user.id,
        reason=body.reason,
    )
    MESSAGE_FLAGS.inc()
    return MeetingMessagePublic.model_validate(message)


# ============================================================
# USER MEETING HISTORY
# ============================================================


@router.get(
    "/",
    response_model=MeetingsPublic,
)
async def get_my_meetings(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=_MAX_PAGE_LIMIT),
) -> MeetingsPublic:
    """Get the current user's meeting history."""
    meetings, count = await meeting_service.get_user_meetings(
        session=session, user_id=current_user.id, skip=skip, limit=limit
    )

    return MeetingsPublic(
        data=[MeetingPublic.model_validate(m) for m in meetings],
        count=count,
    )
