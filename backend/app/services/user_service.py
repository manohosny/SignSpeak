import uuid

from fastapi import HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.errors import (
    INCORRECT_PASSWORD,
    SAME_PASSWORD,
    SUPERUSER_CANNOT_DELETE_SELF,
    raise_email_exists,
    raise_insufficient_privileges,
    raise_user_not_found,
)
from app.models import (
    Message,
    UpdatePassword,
    User,
    UserCreate,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.services.auth_service import generate_password_reset_token
from app.services.email_service import generate_new_account_email, send_email


async def _ensure_email_available(
    *, session: AsyncSession, email: str, exclude_user_id: uuid.UUID | None = None
) -> None:
    existing_user = await crud.get_user_by_email(session=session, email=email)
    if existing_user and (exclude_user_id is None or existing_user.id != exclude_user_id):
        raise_email_exists()


async def list_users(
    *, session: AsyncSession, skip: int = 0, limit: int = 100
) -> UsersPublic:
    users, count = await crud.get_users(session=session, skip=skip, limit=limit)
    return UsersPublic(data=users, count=count)


async def create_user(*, session: AsyncSession, user_in: UserCreate) -> User:
    await _ensure_email_available(session=session, email=user_in.email)
    user = await crud.create_user(session=session, user_create=user_in)
    if settings.emails_enabled and user_in.email:
        # Send a password-reset-style setup link rather than the plaintext
        # password the admin chose. The user picks their own credential on
        # first visit; the original is never transmitted in cleartext.
        token = generate_password_reset_token(email=user_in.email)
        setup_link = f"{settings.FRONTEND_HOST}/reset-password?token={token}"
        email_data = generate_new_account_email(
            email_to=user_in.email,
            username=user_in.email,
            setup_link=setup_link,
        )
        send_email(
            email_to=user_in.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return user


async def register_user(*, session: AsyncSession, user_in: UserRegister) -> User:
    await _ensure_email_available(session=session, email=user_in.email)
    user_create = UserCreate.model_validate(user_in)
    return await crud.create_user(session=session, user_create=user_create)


async def update_user_me(
    *, session: AsyncSession, user_in: UserUpdateMe, current_user: User
) -> User:
    if user_in.email:
        await _ensure_email_available(
            session=session, email=user_in.email, exclude_user_id=current_user.id
        )
    user_data = user_in.model_dump(exclude_unset=True)
    return await crud.update_user_partial(
        session=session, db_user=current_user, update_data=user_data
    )


async def update_password_me(
    *, session: AsyncSession, body: UpdatePassword, current_user: User
) -> Message:
    verified, _ = verify_password(body.current_password, current_user.hashed_password)
    if not verified:
        raise HTTPException(status_code=400, detail=INCORRECT_PASSWORD)
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail=SAME_PASSWORD)
    hashed_password = get_password_hash(body.new_password)
    await crud.set_password(session=session, user=current_user, hashed_password=hashed_password)
    return Message(message="Password updated successfully")


async def get_user_by_id(
    *, session: AsyncSession, user_id: uuid.UUID, current_user: User
) -> User:
    user = await crud.get_user_by_id(session=session, user_id=user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise_insufficient_privileges()
    if user is None:
        raise_user_not_found()
    return user


async def update_user(
    *, session: AsyncSession, user_id: uuid.UUID, user_in: UserUpdate
) -> User:
    db_user = await crud.get_user_by_id(session=session, user_id=user_id)
    if not db_user:
        raise_user_not_found()
    if user_in.email:
        await _ensure_email_available(
            session=session, email=user_in.email, exclude_user_id=user_id
        )
    return await crud.update_user(session=session, db_user=db_user, user_in=user_in)


async def delete_user_me(*, session: AsyncSession, current_user: User) -> Message:
    if current_user.is_superuser:
        raise HTTPException(status_code=403, detail=SUPERUSER_CANNOT_DELETE_SELF)
    await crud.delete_user(session=session, user=current_user)
    return Message(message="User deleted successfully")


async def delete_user(
    *, session: AsyncSession, current_user: User, user_id: uuid.UUID
) -> Message:
    user = await crud.get_user_by_id(session=session, user_id=user_id)
    if not user:
        raise_user_not_found()
    if user == current_user:
        raise HTTPException(status_code=403, detail=SUPERUSER_CANNOT_DELETE_SELF)
    await crud.delete_user(session=session, user=user)
    return Message(message="User deleted successfully")
