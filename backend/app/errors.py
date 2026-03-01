from typing import NoReturn

from fastapi import HTTPException

# Error message constants
EMAIL_ALREADY_EXISTS = "A user with this email already exists"
USER_NOT_FOUND = "User not found"
INACTIVE_USER = "Inactive user"
INSUFFICIENT_PRIVILEGES = "The user doesn't have enough privileges"
INCORRECT_PASSWORD = "Incorrect password"
SAME_PASSWORD = "New password cannot be the same as the current one"
SUPERUSER_CANNOT_DELETE_SELF = "Super users are not allowed to delete themselves"
INCORRECT_CREDENTIALS = "Incorrect email or password"
INVALID_TOKEN = "Invalid token"
EMAILS_NOT_CONFIGURED = "Email sending is not configured"


def raise_email_exists() -> NoReturn:
    raise HTTPException(status_code=409, detail=EMAIL_ALREADY_EXISTS)


def raise_user_not_found() -> NoReturn:
    raise HTTPException(status_code=404, detail=USER_NOT_FOUND)


def raise_inactive_user() -> NoReturn:
    raise HTTPException(status_code=400, detail=INACTIVE_USER)


def raise_insufficient_privileges() -> NoReturn:
    raise HTTPException(status_code=403, detail=INSUFFICIENT_PRIVILEGES)


def raise_incorrect_credentials() -> NoReturn:
    raise HTTPException(status_code=400, detail=INCORRECT_CREDENTIALS)


def raise_invalid_token() -> NoReturn:
    raise HTTPException(status_code=400, detail=INVALID_TOKEN)
