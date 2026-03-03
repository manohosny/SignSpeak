import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.errors import INACTIVE_USER, INCORRECT_CREDENTIALS
from app.models import User
from app.services.auth_service import (
    generate_password_reset_token,
    login,
    verify_password_reset_token,
)


def test_generate_and_verify_reset_token_roundtrip() -> None:
    """generate_password_reset_token and verify_password_reset_token should round-trip."""
    email = "roundtrip@example.com"
    token = generate_password_reset_token(email=email)
    recovered_email = verify_password_reset_token(token=token)
    assert recovered_email == email


def test_verify_reset_token_invalid() -> None:
    """verify_password_reset_token should return None for an invalid token."""
    result = verify_password_reset_token(token="this-is-not-a-valid-jwt-token")
    assert result is None


async def test_login_raises_on_bad_credentials() -> None:
    """login should raise HTTPException with INCORRECT_CREDENTIALS when authentication fails."""
    mock_session = AsyncMock()

    with patch("app.services.auth_service.crud") as mock_crud:
        mock_crud.authenticate = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as exc_info:
            await login(
                session=mock_session, email="bad@example.com", password="wrongpass"
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == INCORRECT_CREDENTIALS


async def test_login_raises_on_inactive_user() -> None:
    """login should raise HTTPException with INACTIVE_USER when user is inactive."""
    mock_session = AsyncMock()

    inactive_user = User(
        id=uuid.uuid4(),
        email="inactive@example.com",
        hashed_password="fakehash",
        is_active=False,
        is_superuser=False,
    )

    with patch("app.services.auth_service.crud") as mock_crud:
        mock_crud.authenticate = AsyncMock(return_value=inactive_user)

        with pytest.raises(HTTPException) as exc_info:
            await login(
                session=mock_session,
                email="inactive@example.com",
                password="somepassword",
            )

        assert exc_info.value.status_code == 400
        assert exc_info.value.detail == INACTIVE_USER
