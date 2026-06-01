from datetime import datetime, timedelta, timezone

import jwt
from jwt.exceptions import InvalidTokenError
from sqlalchemy.exc import IntegrityError
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud
from app.core import security
from app.core.config import settings
from app.errors import (
    raise_inactive_user,
    raise_incorrect_credentials,
    raise_invalid_token,
)
from app.models import (
    Message,
    RevokedRefreshToken,
    Token,
    User,
    UserUpdate,
)
from app.services.email_service import (
    generate_reset_password_email,
    send_email,
)


def _issue_token_pair(subject: str) -> Token:
    """Mint a fresh access + refresh token pair for a subject (user id)."""
    access_expires = timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    refresh_expires = timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    return Token(
        access_token=security.create_access_token(
            subject, expires_delta=access_expires
        ),
        refresh_token=security.create_refresh_token(
            subject, expires_delta=refresh_expires
        ),
    )


async def login(*, session: AsyncSession, email: str, password: str) -> Token:
    """Authenticate user and return access + refresh tokens."""
    user = await crud.authenticate(session=session, email=email, password=password)
    if not user:
        raise_incorrect_credentials()
    elif not user.is_active:
        raise_inactive_user()
    return _issue_token_pair(str(user.id))


async def refresh_access_token(
    *, session: AsyncSession, refresh_token: str
) -> Token:
    """Validate a refresh token and rotate the token pair.

    On a successful exchange the OLD token's `jti` is recorded in the
    `revoked_refresh_token` blacklist so it can never be replayed —
    presenting it again (even before its `exp`) returns 400. This is
    the "rotation with revocation" pattern: stolen refresh tokens
    have at most one use, and a replay deterministically logs out
    whichever party is holding the rotated copy.
    """
    payload = security.decode_token(refresh_token, expected_type="refresh")
    if not payload or not payload.sub or not payload.jti or payload.exp is None:
        raise_invalid_token()
    # Reject replays: the JTI must not already be in the blacklist.
    existing = await session.get(RevokedRefreshToken, payload.jti)
    if existing is not None:
        raise_invalid_token()
    user = await session.get(User, payload.sub)
    if not user:
        raise_invalid_token()
    if not user.is_active:
        raise_inactive_user()

    # Revoke the presented JTI atomically BEFORE issuing the new pair.
    # If two clients race the same refresh token, the IntegrityError
    # rejects the second one — at most one rotation succeeds per JTI.
    # If the commit fails for any other reason, no fresh tokens are
    # returned, so a replay of the old token still hits an empty
    # blacklist next time and the user can recover by retrying.
    session.add(
        RevokedRefreshToken(
            jti=payload.jti,
            expires_at=datetime.fromtimestamp(payload.exp, tz=timezone.utc),
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        raise_invalid_token()

    return _issue_token_pair(str(user.id))


async def logout(*, session: AsyncSession, refresh_token: str) -> Message:
    """Revoke the supplied refresh token.

    Idempotent — if the JTI is already revoked or the token is invalid,
    we still return success. The caller's response message must not leak
    whether the token was meaningful, since logout is one of the few
    endpoints attackers can probe with arbitrary input.
    """
    payload = security.decode_token(refresh_token, expected_type="refresh")
    if payload and payload.jti and payload.exp is not None:
        existing = await session.get(RevokedRefreshToken, payload.jti)
        if existing is None:
            session.add(
                RevokedRefreshToken(
                    jti=payload.jti,
                    expires_at=datetime.fromtimestamp(
                        payload.exp, tz=timezone.utc
                    ),
                )
            )
            try:
                await session.commit()
            except IntegrityError:
                # Concurrent logout / rotation already revoked it.
                await session.rollback()
    return Message(message="Logged out")


async def recover_password(*, session: AsyncSession, email: str) -> Message:
    """Send a password recovery email if the user exists.

    Always returns the same message to prevent email enumeration. The
    SMTP send is wrapped in a thread to avoid leaking timing information
    to a careful attacker (who could otherwise distinguish "user exists"
    via response latency).
    """
    import asyncio

    user = await crud.get_user_by_email(session=session, email=email)

    async def _send_real() -> None:
        password_reset_token = generate_password_reset_token(email=email)
        email_data = generate_reset_password_email(
            email_to=user.email, email=email, token=password_reset_token
        )
        await asyncio.to_thread(
            send_email,
            email_to=user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )

    async def _send_dummy() -> None:
        # Match the typical SMTP roundtrip so the response latency is
        # the same shape whether or not the email is registered.
        await asyncio.sleep(0.1)

    try:
        if user:
            await _send_real()
        else:
            await _send_dummy()
    except Exception as e:
        # Never surface SMTP errors here — the response would also be a
        # user-existence oracle.
        import logging

        logging.getLogger(__name__).warning("Password recovery send failed: %s", e)

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
    """Generate a short-lived JWT token for password reset.

    Carries a dedicated audience claim so a leaked SECRET_KEY still
    cannot be repurposed to forge access or refresh tokens.
    """
    delta = timedelta(hours=settings.EMAIL_RESET_TOKEN_EXPIRE_HOURS)
    now = datetime.now(timezone.utc)
    expires = now + delta
    encoded_jwt = jwt.encode(
        {
            "exp": expires,
            "nbf": now,
            "iat": now,
            "iss": settings.JWT_ISSUER,
            "aud": security.JWT_AUD_PASSWORD_RESET,
            "sub": email,
        },
        settings.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    return encoded_jwt


def verify_password_reset_token(token: str) -> str | None:
    """Verify a password reset token and return the email, or None if invalid."""
    try:
        decoded_token = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[security.ALGORITHM],
            audience=security.JWT_AUD_PASSWORD_RESET,
            issuer=settings.JWT_ISSUER,
        )
        return str(decoded_token["sub"])
    except InvalidTokenError:
        return None
