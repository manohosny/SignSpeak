from typing import Annotated, Any

from fastapi import APIRouter, Cookie, Depends, HTTPException, Response
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.rate_limit import auth_rate_limit
from app.core.security import (
    REFRESH_TOKEN_COOKIE,
    clear_auth_cookies,
    set_auth_cookies,
)
from app.models import Message, NewPassword, RefreshTokenRequest, Token, UserPublic
from app.services import auth_service
from app.services.email_service import generate_reset_password_email

router = APIRouter(tags=["login"])


@router.post(
    "/login/access-token",
    dependencies=[Depends(auth_rate_limit)],
)
async def login_access_token(
    session: SessionDep,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    token = await auth_service.login(
        session=session, email=form_data.username, password=form_data.password
    )
    if token.refresh_token is not None:
        # Set HttpOnly cookies in addition to returning the JSON body.
        # Browser clients use the cookies; non-browser API consumers (CLI
        # tooling, server-to-server) keep using the body unchanged.
        set_auth_cookies(
            response,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
        )
    return token


@router.post(
    "/login/refresh",
    dependencies=[Depends(auth_rate_limit)],
)
async def refresh_token(
    session: SessionDep,
    response: Response,
    # Body is optional now — browser clients send the refresh token via
    # the HttpOnly cookie automatically; only API consumers still pass it
    # in the request body.
    body: RefreshTokenRequest | None = None,
    cookie_refresh: Annotated[
        str | None,
        Cookie(alias=REFRESH_TOKEN_COOKIE, include_in_schema=False),
    ] = None,
) -> Token:
    """Exchange a valid refresh token for a fresh access + refresh pair."""
    refresh_value = (body.refresh_token if body is not None else None) or cookie_refresh
    if not refresh_value:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    token = await auth_service.refresh_access_token(
        session=session, refresh_token=refresh_value
    )
    if token.refresh_token is not None:
        set_auth_cookies(
            response,
            access_token=token.access_token,
            refresh_token=token.refresh_token,
        )
    return token


@router.post("/login/test-token", response_model=UserPublic)
async def test_token(current_user: CurrentUser) -> UserPublic:
    return current_user


@router.post("/logout")
async def logout(
    session: SessionDep,
    response: Response,
    body: RefreshTokenRequest | None = None,
    cookie_refresh: Annotated[
        str | None,
        Cookie(alias=REFRESH_TOKEN_COOKIE, include_in_schema=False),
    ] = None,
) -> Message:
    """Revoke a refresh token. Always returns 200 to avoid token-validity
    oracles; if the supplied token is invalid the call is a no-op."""
    refresh_value = (body.refresh_token if body is not None else None) or cookie_refresh
    # Always clear the cookies — even if no token was supplied, the client
    # asked to log out; honour that visibly.
    clear_auth_cookies(response)
    if refresh_value:
        return await auth_service.logout(session=session, refresh_token=refresh_value)
    return Message(message="Logout successful")


@router.post(
    "/password-recovery/{email}",
    dependencies=[Depends(auth_rate_limit)],
)
async def recover_password(email: str, session: SessionDep) -> Message:
    return await auth_service.recover_password(session=session, email=email)


@router.post("/reset-password/")
async def reset_password(session: SessionDep, body: NewPassword) -> Message:
    return await auth_service.reset_password(
        session=session, token=body.token, new_password=body.new_password
    )


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
async def recover_password_html_content(email: str, session: SessionDep) -> Any:
    user = await crud.get_user_by_email(session=session, email=email)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    password_reset_token = auth_service.generate_password_reset_token(email=email)
    email_data = generate_reset_password_email(
        email_to=user.email, email=email, token=password_reset_token
    )
    return HTMLResponse(
        content=email_data.html_content, headers={"subject:": email_data.subject}
    )
