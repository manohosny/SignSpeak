import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, SessionDep, get_current_user
from app.models import (
    MeetingJoin,
    MeetingMessagePublic,
    MeetingMessagesPublic,
    MeetingPublic,
    MeetingsPublic,
    Message,
)
from app.services import meeting_service

router = APIRouter(prefix="/meetings", tags=["meetings"])


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
    limit: int = 50,
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
    skip: int = 0,
    limit: int = 20,
) -> MeetingsPublic:
    """Get the current user's meeting history."""
    meetings, count = await meeting_service.get_user_meetings(
        session=session, user_id=current_user.id, skip=skip, limit=limit
    )

    return MeetingsPublic(
        data=[MeetingPublic.model_validate(m) for m in meetings],
        count=count,
    )
