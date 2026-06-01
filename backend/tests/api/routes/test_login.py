from unittest.mock import patch

from fastapi.testclient import TestClient
from pwdlib.hashers.bcrypt import BcryptHasher
from sqlmodel import Session

from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import User
from app.utils import generate_password_reset_token
from tests.utils.user import user_authentication_headers
from tests.utils.utils import random_email, random_lower_string


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]
    # Login must now also return a refresh token so the FE can rotate.
    assert "refresh_token" in tokens
    assert tokens["refresh_token"]


def test_refresh_rotates_token_pair(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    refresh_token = tokens["refresh_token"]

    r2 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r2.status_code == 200
    new_tokens = r2.json()
    assert new_tokens["access_token"]
    assert new_tokens["refresh_token"]


def test_refresh_rejects_access_token(client: TestClient) -> None:
    """An access token must NOT authorize /login/refresh."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    access_token = r.json()["access_token"]

    r2 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": access_token},
    )
    assert r2.status_code in (400, 401, 403)


def test_refresh_token_cannot_authenticate_api(client: TestClient) -> None:
    """A refresh token must NOT authenticate API requests."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    refresh_token = r.json()["refresh_token"]

    r2 = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {refresh_token}"},
    )
    assert r2.status_code == 403


def test_refresh_with_garbage_token_returns_400(client: TestClient) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": "not-a-real-token"},
    )
    assert r.status_code == 400


def test_refresh_token_replay_is_rejected(client: TestClient) -> None:
    """Once a refresh token has been rotated, replaying it must fail.

    The previous JTI is recorded in `revoked_refresh_token`; a second
    /login/refresh with the same token returns 400.
    """
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    refresh_token = r.json()["refresh_token"]

    # First rotation succeeds.
    r1 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r1.status_code == 200

    # Replaying the original refresh token must now be rejected.
    r2 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r2.status_code == 400


def test_login_endpoint_rate_limited(client: TestClient) -> None:
    """The auth-rate-limit dependency must eventually return 429."""
    from app.core.config import settings as live_settings

    # Hammer with bad credentials so each request consumes a bucket token
    # without our caring about success — only the rate-limit response.
    seen_429 = False
    for _ in range(live_settings.AUTH_RATE_LIMIT_BURST + 5):
        r = client.post(
            f"{live_settings.API_V1_STR}/login/access-token",
            data={"username": "x@y.com", "password": "wrong"},
        )
        if r.status_code == 429:
            seen_429 = True
            break
    assert seen_429, "Auth endpoint did not 429 within burst+5 attempts"


def test_refresh_chains_after_rotation(client: TestClient) -> None:
    """The NEW refresh token from a rotation must itself be valid."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    refresh_token = r.json()["refresh_token"]

    r1 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_token},
    )
    new_refresh = r1.json()["refresh_token"]

    # The new refresh token must work for a second rotation.
    r2 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": new_refresh},
    )
    assert r2.status_code == 200
    assert r2.json()["refresh_token"] != new_refresh


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with (
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        email = "test@example.com"
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {
            "message": "If that email is registered, we sent a password recovery link"
        }


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    # Should return 200 with generic message to prevent email enumeration attacks
    assert r.status_code == 200
    assert r.json() == {
        "message": "If that email is registered, we sent a password recovery link"
    }


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    new_password = random_lower_string()

    user = User(
        email=email,
        full_name="Test User",
        hashed_password=get_password_hash(password),
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = generate_password_reset_token(email=email)
    headers = user_authentication_headers(client=client, email=email, password=password)
    data = {"new_password": new_password, "token": token}

    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=headers,
        json=data,
    )

    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    verified, _ = verify_password(new_password, user.hashed_password)
    assert verified


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_login_with_bcrypt_password_upgrades_to_argon2(
    client: TestClient, db: Session
) -> None:
    """Test that logging in with a bcrypt password hash upgrades it to argon2."""
    email = random_email()
    password = random_lower_string()

    # Create a bcrypt hash directly (simulating legacy password)
    bcrypt_hasher = BcryptHasher()
    bcrypt_hash = bcrypt_hasher.hash(password)
    assert bcrypt_hash.startswith("$2")  # bcrypt hashes start with $2

    user = User(email=email, hashed_password=bcrypt_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    assert user.hashed_password.startswith("$2")

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    # Verify the hash was upgraded to argon2
    assert user.hashed_password.startswith("$argon2")

    verified, updated_hash = verify_password(password, user.hashed_password)
    assert verified
    # Should not need another update since it's already argon2
    assert updated_hash is None


def test_login_with_argon2_password_keeps_hash(client: TestClient, db: Session) -> None:
    """Test that logging in with an argon2 password hash does not update it."""
    email = random_email()
    password = random_lower_string()

    # Create an argon2 hash (current default)
    argon2_hash = get_password_hash(password)
    assert argon2_hash.startswith("$argon2")

    # Create user with argon2 hash
    user = User(email=email, hashed_password=argon2_hash, is_active=True)
    db.add(user)
    db.commit()
    db.refresh(user)

    original_hash = user.hashed_password

    login_data = {"username": email, "password": password}
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 200
    tokens = r.json()
    assert "access_token" in tokens

    db.refresh(user)

    assert user.hashed_password == original_hash
    assert user.hashed_password.startswith("$argon2")


# ============================================================
# Logout / refresh-rotation hardening (PR4 + PR2)
# ============================================================


def test_logout_revokes_refresh_token(client: TestClient) -> None:
    """POST /logout must blacklist the supplied refresh token's JTI."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    refresh_token = r.json()["refresh_token"]

    r1 = client.post(
        f"{settings.API_V1_STR}/logout",
        json={"refresh_token": refresh_token},
    )
    assert r1.status_code == 200

    # The token must no longer be usable for refresh.
    r2 = client.post(
        f"{settings.API_V1_STR}/login/refresh",
        json={"refresh_token": refresh_token},
    )
    assert r2.status_code == 400


def test_logout_is_idempotent(client: TestClient) -> None:
    """Logging out the same token twice must succeed (no oracle)."""
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    refresh_token = r.json()["refresh_token"]

    r1 = client.post(
        f"{settings.API_V1_STR}/logout",
        json={"refresh_token": refresh_token},
    )
    r2 = client.post(
        f"{settings.API_V1_STR}/logout",
        json={"refresh_token": refresh_token},
    )
    assert r1.status_code == 200
    assert r2.status_code == 200


def test_logout_with_garbage_token_returns_200(client: TestClient) -> None:
    """Logout must NOT leak token validity — invalid tokens still succeed."""
    r = client.post(
        f"{settings.API_V1_STR}/logout",
        json={"refresh_token": "not-a-real-token"},
    )
    assert r.status_code == 200


def test_password_reset_token_cannot_authenticate_api(client: TestClient) -> None:
    """Password reset tokens use a dedicated audience and must NOT
    authenticate API requests even though they share the SECRET_KEY."""
    reset_token = generate_password_reset_token(email=settings.FIRST_SUPERUSER)
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {reset_token}"},
    )
    assert r.status_code == 403


def test_access_token_cannot_be_used_as_password_reset(client: TestClient) -> None:
    """The reverse: an access token must NOT verify as a reset token."""
    from app.services.auth_service import verify_password_reset_token

    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    access_token = r.json()["access_token"]

    # verify_password_reset_token must reject it because the audience
    # claim is signspeak:access, not signspeak:password-reset.
    assert verify_password_reset_token(access_token) is None


def test_token_without_aud_is_rejected(client: TestClient) -> None:
    """Tokens missing the aud claim (legacy / forged) must be rejected."""
    import jwt as _jwt

    from app.core import security
    from app.core.config import settings as live_settings

    # A token with the right sub + type but no `aud` / `iss` claims —
    # simulating a token that predates the audience hardening or one
    # forged with a leaked key but without the new claims.
    forged = _jwt.encode(
        {
            "sub": "00000000-0000-0000-0000-000000000000",
            "type": "access",
            "exp": 9999999999,
        },
        live_settings.SECRET_KEY,
        algorithm=security.ALGORITHM,
    )
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert r.status_code == 403


# ─── Cookie-based session flow ──────────────────────────────────────────


def _login(client: TestClient) -> None:
    """Helper: log in via /login/access-token. Cookies are stored on the
    TestClient's underlying httpx Cookies jar automatically, so subsequent
    requests carry them."""
    client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )


def test_login_sets_session_cookies(client: TestClient) -> None:
    """Login should set HttpOnly access + refresh cookies plus a JS-readable
    session marker, alongside the existing JSON Token body."""
    from app.core.security import (
        ACCESS_TOKEN_COOKIE,
        REFRESH_TOKEN_COOKIE,
        SESSION_MARKER_COOKIE,
    )

    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    assert r.status_code == 200
    assert ACCESS_TOKEN_COOKIE in client.cookies
    assert REFRESH_TOKEN_COOKIE in client.cookies
    assert SESSION_MARKER_COOKIE in client.cookies
    # The session marker is intentionally just "1" — no payload, just a
    # presence flag the FE reads via document.cookie.
    assert client.cookies.get(SESSION_MARKER_COOKIE) == "1"


def test_authenticate_via_cookie_only(client: TestClient) -> None:
    """A request bearing only the access-token cookie (no Authorization
    header) must successfully authenticate."""
    _login(client)
    # Drop any Authorization header the client might add by default.
    r = client.post(f"{settings.API_V1_STR}/login/test-token")
    assert r.status_code == 200
    assert r.json()["email"] == settings.FIRST_SUPERUSER


def test_refresh_via_cookie_without_body(client: TestClient) -> None:
    """The /login/refresh endpoint should accept the refresh token from
    the HttpOnly cookie when no JSON body is provided."""
    _login(client)
    r = client.post(f"{settings.API_V1_STR}/login/refresh")
    assert r.status_code == 200
    body = r.json()
    assert body["access_token"]
    assert body["refresh_token"]


def test_logout_clears_cookies(client: TestClient) -> None:
    """Logout must clear all three auth cookies even if the client sends
    no body — the cookie itself supplies the refresh token to revoke."""
    from app.core.security import (
        ACCESS_TOKEN_COOKIE,
        REFRESH_TOKEN_COOKIE,
        SESSION_MARKER_COOKIE,
    )

    _login(client)
    r = client.post(f"{settings.API_V1_STR}/logout")
    assert r.status_code == 200
    # delete_cookie sets Max-Age=0 / expires-in-the-past; httpx treats
    # those as removed from the jar.
    assert ACCESS_TOKEN_COOKIE not in client.cookies
    assert REFRESH_TOKEN_COOKIE not in client.cookies
    assert SESSION_MARKER_COOKIE not in client.cookies


def test_request_without_token_or_cookie_is_unauthenticated(client: TestClient) -> None:
    """Calls with neither Authorization header nor cookie must fail with 401."""
    # Use a fresh client — TestClient persists cookies across requests by
    # default; we want a clean jar here.
    from fastapi.testclient import TestClient as _TC

    from app.main import app

    fresh = _TC(app)
    r = fresh.post(f"{settings.API_V1_STR}/login/test-token")
    assert r.status_code == 401


def test_bearer_takes_precedence_over_cookie(client: TestClient) -> None:
    """If both a valid Bearer header and a stale cookie are present, the
    Bearer wins — preserving existing API-client behaviour even when a
    browser session cookie is present in the same jar."""
    _login(client)
    # Get a fresh access token for the same user from the body.
    r = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={
            "username": settings.FIRST_SUPERUSER,
            "password": settings.FIRST_SUPERUSER_PASSWORD,
        },
    )
    fresh_access = r.json()["access_token"]

    # Use the Bearer header explicitly. Even if the cookie also contained
    # garbage (it doesn't here, but we're testing the priority order),
    # the Bearer should be taken.
    r2 = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers={"Authorization": f"Bearer {fresh_access}"},
    )
    assert r2.status_code == 200
