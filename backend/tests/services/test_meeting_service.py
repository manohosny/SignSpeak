"""Service-layer tests for meeting_service.

Focuses on the concurrency contract of join_meeting: two participants joining
the same meeting at once must serialize on the meeting row, so capacity and
the waiting→active transition stay consistent.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud_meeting
from app.core.db import async_session_factory
from app.core.security import get_password_hash
from app.models import (
    Meeting,
    MeetingStatus,
    ParticipantRole,
    User,
)
from app.services import meeting_service


async def _make_user(session: AsyncSession, label: str) -> User:
    user = User(
        email=f"{label}-{uuid.uuid4().hex[:8]}@test.com",
        hashed_password=get_password_hash("testpass123"),
        is_active=True,
        full_name=f"{label} user",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def test_concurrent_joins_serialize_and_respect_capacity() -> None:
    """Two readers joining the same waiting meeting simultaneously must not
    both get in.

    Without the row lock in join_meeting both joins observe one participant,
    both insert, and the meeting ends up with three participants. The lock
    serializes them: exactly one join succeeds, the other is rejected, and the
    meeting ends with two participants in the `active` state.
    """
    # async_session_factory sets expire_on_commit=False, so user/meeting
    # attributes stay populated across the multiple commits below (and after
    # the session closes) — avoiding a sync lazy-load in async context.
    async with async_session_factory() as setup:
        host = await _make_user(setup, "host")
        reader_a = await _make_user(setup, "reader-a")
        reader_b = await _make_user(setup, "reader-b")

        meeting = Meeting(host_id=host.id, status=MeetingStatus.waiting)
        setup.add(meeting)
        await setup.commit()
        await setup.refresh(meeting)
        meeting_id = meeting.id

        # Host is the first participant (speaker).
        await crud_meeting.add_participant(
            session=setup,
            meeting_id=meeting_id,
            user_id=host.id,
            role=ParticipantRole.speaker,
        )
        await setup.commit()

    async def _join(user: User) -> Meeting | HTTPException:
        # Each join runs in its own session/connection so the two genuinely
        # contend for the meeting row lock.
        async with async_session_factory() as session:
            joined = await crud_meeting.get_meeting_by_id(
                session=session, meeting_id=meeting_id
            )
            assert joined is not None
            try:
                return await meeting_service.join_meeting(
                    session=session, meeting=joined, user=user
                )
            except HTTPException as exc:
                return exc

    try:
        results = await asyncio.gather(_join(reader_a), _join(reader_b))

        successes = [r for r in results if isinstance(r, Meeting)]
        rejections = [r for r in results if isinstance(r, HTTPException)]

        assert len(successes) == 1, (
            "exactly one concurrent join should succeed"
        )
        assert len(rejections) == 1, (
            "the losing join should be rejected, not silently allowed"
        )

        # Final state: capacity respected (host + one reader), meeting active.
        async with async_session_factory() as verify:
            participants = await crud_meeting.get_participants(
                session=verify, meeting_id=meeting_id
            )
            assert len(participants) == 2, (
                f"expected 2 participants, got {len(participants)} — "
                "concurrent joins bypassed the capacity check"
            )
            final = await crud_meeting.get_meeting_by_id(
                session=verify, meeting_id=meeting_id
            )
            assert final is not None
            assert final.status == MeetingStatus.active
    finally:
        # Clean up so the session-scoped `delete(User)` teardown isn't
        # blocked by the meeting's host_id foreign key.
        async with async_session_factory() as cleanup:
            for p in await crud_meeting.get_participants(
                session=cleanup, meeting_id=meeting_id
            ):
                await cleanup.delete(p)
            stale = await crud_meeting.get_meeting_by_id(
                session=cleanup, meeting_id=meeting_id
            )
            if stale is not None:
                await cleanup.delete(stale)
            for user in (host, reader_a, reader_b):
                db_user = await cleanup.get(User, user.id)
                if db_user is not None:
                    await cleanup.delete(db_user)
            await cleanup.commit()
