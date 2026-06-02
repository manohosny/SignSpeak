from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, Literal

import jwt
from fastapi import Response

if TYPE_CHECKING:
    from app.models import TokenPayload
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash(
    (
        Argon2Hasher(),
        BcryptHasher(),
    )
)


ALGORITHM = "HS256"

TokenType = Literal["access", "refresh"]

# JWT audience values — one per token kind. Including these in the
# signed payload AND validating them on decode means a leaked SECRET_KEY
# cannot be used to forge a cross-purpose token (e.g. mint a password
# reset using an access-token signing key).
JWT_AUD_ACCESS = "signspeak:access"
JWT_AUD_REFRESH = "signspeak:refresh"
JWT_AUD_PASSWORD_RESET = "signspeak:password-reset"


def create_access_token(subject: str | Any, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    # `type` and `aud` claims distinguish access vs refresh tokens — a
    # refresh token must not authenticate API calls and vice versa.
    to_encode = {
        "exp": expire,
        "nbf": now,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": JWT_AUD_ACCESS,
        "sub": str(subject),
        "type": "access",
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def create_refresh_token(subject: str | Any, expires_delta: timedelta) -> str:
    """Issue a long-lived refresh token bearing a unique JTI.

    The JTI is recorded in `revoked_refresh_token` after a successful
    rotation so the old token cannot be replayed.
    """
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    to_encode = {
        "exp": expire,
        "nbf": now,
        "iat": now,
        "iss": settings.JWT_ISSUER,
        "aud": JWT_AUD_REFRESH,
        "sub": str(subject),
        "type": "refresh",
        "jti": uuid.uuid4().hex,
    }
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)


def verify_password(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    return password_hash.verify_and_update(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)


_TYPE_TO_AUDIENCE: dict[str, str] = {
    "access": JWT_AUD_ACCESS,
    "refresh": JWT_AUD_REFRESH,
}


# ─────────────────────────────────────────────────────────────────────
# Cookie auth helpers
# ─────────────────────────────────────────────────────────────────────
#
# Three cookies make up a session:
#
#   ACCESS_TOKEN_COOKIE    — HttpOnly, short-lived. Sent on every API call.
#   REFRESH_TOKEN_COOKIE   — HttpOnly, long-lived. Path-scoped to /login so
#                            it isn't sent on regular API calls (reduces the
#                            chance of accidental forwarding to a 3rd party).
#   SESSION_MARKER_COOKIE  — non-HttpOnly, value `"1"`. Lets JS check
#                            "is the user logged in?" synchronously without
#                            exposing the token. An attacker stealing this
#                            cookie via XSS gets a `1` — worthless without
#                            the HttpOnly access token alongside.
#
# In production (`ENVIRONMENT != "local"`) the cookies are issued with
# `Secure` set; in local dev `Secure` is dropped so http://localhost works.

ACCESS_TOKEN_COOKIE = "ss_access"
REFRESH_TOKEN_COOKIE = "ss_refresh"
SESSION_MARKER_COOKIE = "ss_session"

# Path-scoping the refresh cookie to the login routes means it isn't
# sent on every API call — only on /refresh and /logout where it matters.
_REFRESH_COOKIE_PATH = f"{settings.API_V1_STR}/login"


def _is_secure_cookie() -> bool:
    """Cookies use Secure outside local dev so http://localhost still works."""
    return settings.ENVIRONMENT != "local"


def _samesite_policy() -> Literal["lax", "strict", "none"]:
    """SameSite=Lax for first-party flows; bumps to None when cross-site
    (the browser then requires Secure, which we already set in non-local)."""
    # Same-origin SPA → backend? Lax is fine and protects against most CSRF.
    # Cross-site (FE on signspeak.app, API on api.signspeak.app)? Still
    # technically same-site (eTLD+1) so Lax remains correct. Use "none"
    # only if you actually deploy on unrelated domains.
    return "lax"


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    access_max_age: int | None = None,
    refresh_max_age: int | None = None,
) -> None:
    """Write the access + refresh + session-marker cookies onto a response.

    Caller still returns the JSON Token body so non-browser API clients
    keep working unchanged — the cookies are additive.
    """
    secure = _is_secure_cookie()
    samesite = _samesite_policy()
    domain = settings.COOKIE_DOMAIN or None

    if access_max_age is None:
        access_max_age = settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    if refresh_max_age is None:
        refresh_max_age = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60

    response.set_cookie(
        key=ACCESS_TOKEN_COOKIE,
        value=access_token,
        max_age=access_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE,
        value=refresh_token,
        max_age=refresh_max_age,
        httponly=True,
        secure=secure,
        samesite=samesite,
        domain=domain,
        path=_REFRESH_COOKIE_PATH,
    )
    # Session-marker mirrors the refresh token's lifetime: while it's set,
    # the FE believes the user has a session. Cleared on logout.
    response.set_cookie(
        key=SESSION_MARKER_COOKIE,
        value="1",
        max_age=refresh_max_age,
        httponly=False,
        secure=secure,
        samesite=samesite,
        domain=domain,
        path="/",
    )


def clear_auth_cookies(response: Response) -> None:
    """Reset all three auth cookies. Used on logout."""
    domain = settings.COOKIE_DOMAIN or None
    response.delete_cookie(key=ACCESS_TOKEN_COOKIE, path="/", domain=domain)
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE, path=_REFRESH_COOKIE_PATH, domain=domain
    )
    response.delete_cookie(key=SESSION_MARKER_COOKIE, path="/", domain=domain)


def decode_token(
    token: str, expected_type: TokenType | None = None
) -> TokenPayload | None:
    """Decode and validate a JWT.

    Validates signature, expiry, issuer, and (when `expected_type` is
    given) audience and explicit `type` claim. Tokens missing the type
    claim are rejected — the migration from typeless tokens shipped with
    refresh-rotation, so any still in flight are well past expiry.

    Returns TokenPayload on success, None on any validation failure.
    """
    from app.models import TokenPayload

    decode_kwargs: dict[str, Any] = {
        "key": settings.SECRET_KEY,
        "algorithms": [ALGORITHM],
        "issuer": settings.JWT_ISSUER,
    }
    if expected_type is not None:
        audience = _TYPE_TO_AUDIENCE.get(expected_type)
        if audience is None:
            return None
        decode_kwargs["audience"] = audience
    else:
        # When the caller doesn't constrain the type, accept either
        # access or refresh audiences but still require *some* match
        # (PyJWT validates the aud claim is present and is one of these).
        decode_kwargs["audience"] = [JWT_AUD_ACCESS, JWT_AUD_REFRESH]

    try:
        payload = jwt.decode(token, **decode_kwargs)
    except jwt.exceptions.InvalidTokenError:
        return None

    sub: str | None = payload.get("sub")
    if sub is None:
        return None

    token_type = payload.get("type")
    if token_type not in ("access", "refresh"):
        return None
    if expected_type is not None and token_type != expected_type:
        return None

    return TokenPayload(
        sub=sub,
        jti=payload.get("jti"),
        exp=payload.get("exp"),
        type=token_type,
    )
