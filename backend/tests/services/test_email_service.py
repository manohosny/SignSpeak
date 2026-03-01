from unittest.mock import patch

import pytest

from app.errors import EMAILS_NOT_CONFIGURED
from app.services.email_service import _build_smtp_options, send_email


def test_send_email_raises_when_not_configured() -> None:
    """send_email should raise RuntimeError when SMTP is not configured."""
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.emails_enabled = False
        with pytest.raises(RuntimeError, match=EMAILS_NOT_CONFIGURED):
            send_email(
                email_to="test@example.com",
                subject="Test",
                html_content="<p>Hello</p>",
            )


def test_build_smtp_options_with_tls() -> None:
    """_build_smtp_options should include tls=True when SMTP_TLS is True."""
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.SMTP_HOST = "smtp.example.com"
        mock_settings.SMTP_PORT = 587
        mock_settings.SMTP_TLS = True
        mock_settings.SMTP_SSL = False
        mock_settings.SMTP_USER = "user@example.com"
        mock_settings.SMTP_PASSWORD = "secret"

        options = _build_smtp_options()

        assert options["host"] == "smtp.example.com"
        assert options["port"] == 587
        assert options["tls"] is True
        assert "ssl" not in options
        assert options["user"] == "user@example.com"
        assert options["password"] == "secret"


def test_build_smtp_options_with_ssl() -> None:
    """_build_smtp_options should include ssl=True when SMTP_SSL is True and SMTP_TLS is False."""
    with patch("app.services.email_service.settings") as mock_settings:
        mock_settings.SMTP_HOST = "smtp.example.com"
        mock_settings.SMTP_PORT = 465
        mock_settings.SMTP_TLS = False
        mock_settings.SMTP_SSL = True
        mock_settings.SMTP_USER = None
        mock_settings.SMTP_PASSWORD = None

        options = _build_smtp_options()

        assert options["host"] == "smtp.example.com"
        assert options["port"] == 465
        assert options["ssl"] is True
        assert "tls" not in options
        assert "user" not in options
        assert "password" not in options
