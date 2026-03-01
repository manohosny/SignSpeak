"""
Backward-compatibility shim.
All functions have moved to app.services.email_service and app.services.auth_service.
"""
from app.services.auth_service import (  # noqa: F401
    generate_password_reset_token,
    verify_password_reset_token,
)
from app.services.email_service import (  # noqa: F401
    EmailData,
    generate_new_account_email,
    generate_reset_password_email,
    generate_test_email,
    render_email_template,
    send_email,
)
