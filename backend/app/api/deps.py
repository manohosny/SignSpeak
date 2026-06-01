from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core import security
from app.core.config import settings
from app.core.db import async_session_factory
from app.core.security import ACCESS_TOKEN_COOKIE
from app.errors import (
    raise_insufficient_privileges,
)
from app.models import User

# `auto_error=False` so we can fall through to the cookie path. With the
# default `True`, missing Authorization header would raise 401 before our
# handler runs and the cookie would never be checked.
reusable_oauth2 = OAuth2PasswordBearer(
    tokenUrl=f"{settings.API_V1_STR}/login/access-token",
    auto_error=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_db)]
TokenDep = Annotated[str | None, Depends(reusable_oauth2)]


async def get_current_user(
    session: SessionDep,
    token: TokenDep,
    # `include_in_schema=False` keeps this cookie out of the OpenAPI spec.
    # Browsers attach it implicitly with `withCredentials`; documenting it
    # would force every generated SDK method to take a redundant
    # `ssAccess?` argument that no caller would ever pass.
    cookie_token: Annotated[
        str | None,
        Cookie(alias=ACCESS_TOKEN_COOKIE, include_in_schema=False),
    ] = None,
) -> User:
    # Prefer the Authorization: Bearer header so existing API clients
    # (CLIs, server-to-server, the OpenAPI tester) keep working unchanged;
    # fall back to the HttpOnly cookie for browser clients.
    raw_token = token or cookie_token
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )

    # decode_token validates signature, expiry, issuer, audience, and the
    # explicit `type=access` claim — rejecting refresh tokens, password
    # reset tokens, and any token signed by a different service that
    # happens to share our key.
    payload = security.decode_token(raw_token, expected_type="access")
    if payload is None or payload.sub is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Could not validate credentials",
        )
    user = await session.get(User, payload.sub)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inactive user",
        )
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_current_active_superuser(current_user: CurrentUser) -> User:
    if not current_user.is_superuser:
        raise_insufficient_privileges()
    return current_user
