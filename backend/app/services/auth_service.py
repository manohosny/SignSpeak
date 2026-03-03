from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud
from app.core import security
from app.core.config import settings
from app.errors import (
    raise_inactive_user,
    raise_incorrect_credentials,
    raise_invalid_token,
)
from app.models import Message, Token, UserUpdate
from app.services.email_service import (
    generate_reset_password_email,
    send_email,
)


async def login(*, session: AsyncSession, email: str, password: str) -> Token:
    """Authenticate user and return an access token."""
    user = await crud.authenticate(session=session, email=email, password=password)
    if not user:
        raise_incorrect_credentials()
    elif not user.is_active:
        raise_inactive_user()
    access_token_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    return Token(
        access_token=security.create_access_token(
            user.id, expires_delta=access_token_expires
        )
    )


async def recover_password(*, session: AsyncSession, email: str) -> Message:
    """Send a password recovery email if the user exists.

    Always returns the same message to prevent email enumeration attacks.
    """
    user = await crud.get_user_by_email(session=session, email=email)

    if user:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        send_email(
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    return Message(
        message="If that email is registered, we sent a password recovery link"
    )


async def reset_password(*, session: AsyncSession, token: str, new_password: str) -> Message:
    """Verify a password reset token and update the user's password."""
    email = verify_password_reset_token(token=token)
    if not email:
        raise_invalid_token()
    user = await crud.get_user_by_email(session=session, email=email)
    if not user:
        raise_invalid_token()
    elif not user.is_active:
        raise_inactive_user()
    user_in_update = UserUpdate(password=new_password)
    await crud.update_user(session=session, db_user=user, user_in=user_in_update)
    return Message(message="Password updated successfully")


def generate_password_reset_token(email: str) -> str:
    """Generate a JWT token for password reset."""
    delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    expires = now + delta
    exp = expires.timestamp()
    encoded_jwt = jwt.encode(
        {"exp": exp, "nbf": now, "sub": email},
        settings.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> str | None:
    """Verify a password reset token and return the email, or None if invalid."""
    try:
        decoded_token = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[security.ALGORITHM]
        )
        return str(decoded_token["sub"])
    except InvalidTokenError:
        return None
