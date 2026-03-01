import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.errors import EMAIL_ALREADY_EXISTS, SUPERUSER_CANNOT_DELETE_SELF
from app.models import User, UserCreate
from app.services.user_service import (
    _ensure_email_available,
    create_user,
    delete_user_me,
)


def test_ensure_email_available_raises_on_duplicate() -> None:
    """_ensure_email_available should raise HTTPException when email is taken."""
    mock_session = MagicMock()
    existing_user = User(
        id=uuid.uuid4(),
        email="taken@example.com",
        hashed_password="fakehash",
        is_active=True,
        is_superuser=False,
    )

    with patch("app.services.user_service.crud") as mock_crud:
        mock_crud.get_user_by_email.return_value = existing_user

        with pytest.raises(HTTPException) as exc_info:
            _ensure_email_available(session=mock_session, email="taken@example.com")

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == EMAIL_ALREADY_EXISTS


def test_ensure_email_available_allows_same_user() -> None:
    """_ensure_email_available should not raise when the existing user is the excluded user."""
    mock_session = MagicMock()
    user_id = uuid.uuid4()
    existing_user = User(
        id=user_id,
        email="myemail@example.com",
        hashed_password="fakehash",
        is_active=True,
        is_superuser=False,
    )

    with patch("app.services.user_service.crud") as mock_crud:
        mock_crud.get_user_by_email.return_value = existing_user

        # Should not raise when exclude_user_id matches the existing user's id
        _ensure_email_available(
            session=mock_session,
            email="myemail@example.com",
            exclude_user_id=user_id,
        )


def test_create_user_sends_email_when_enabled() -> None:
    """create_user should send account email when emails are enabled."""
    mock_session = MagicMock()
    user_in = UserCreate(email="new@example.com", password="securepassword123")
    created_user = User(
        id=uuid.uuid4(),
        email="new@example.com",
        hashed_password="hashedpw",
        is_active=True,
        is_superuser=False,
    )

    with (
        patch("app.services.user_service.crud") as mock_crud,
        patch("app.services.user_service.send_email") as mock_send_email,
        patch("app.services.user_service.generate_new_account_email") as mock_gen_email,
        patch("app.services.user_service.settings") as mock_settings,
    ):
        mock_crud.get_user_by_email.return_value = None
        mock_crud.create_user.return_value = created_user
        mock_settings.emails_enabled = True
        mock_gen_email.return_value = MagicMock(
            subject="Welcome", html_content="<p>Hello</p>"
        )

        result = create_user(session=mock_session, user_in=user_in)

        assert result == created_user
        mock_send_email.assert_called_once_with(
            email_to="new@example.com",
            subject="Welcome",
            html_content="<p>Hello</p>",
        )


def test_create_user_skips_email_when_disabled() -> None:
    """create_user should not send email when emails are disabled."""
    mock_session = MagicMock()
    user_in = UserCreate(email="new@example.com", password="securepassword123")
    created_user = User(
        id=uuid.uuid4(),
        email="new@example.com",
        hashed_password="hashedpw",
        is_active=True,
        is_superuser=False,
    )

    with (
        patch("app.services.user_service.crud") as mock_crud,
        patch("app.services.user_service.send_email") as mock_send_email,
        patch("app.services.user_service.settings") as mock_settings,
    ):
        mock_crud.get_user_by_email.return_value = None
        mock_crud.create_user.return_value = created_user
        mock_settings.emails_enabled = False

        result = create_user(session=mock_session, user_in=user_in)

        assert result == created_user
        mock_send_email.assert_not_called()


def test_delete_user_me_rejects_superuser() -> None:
    """delete_user_me should raise HTTPException for superusers."""
    mock_session = MagicMock()
    superuser = User(
        id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="fakehash",
        is_active=True,
        is_superuser=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        delete_user_me(session=mock_session, current_user=superuser)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == SUPERUSER_CANNOT_DELETE_SELF
