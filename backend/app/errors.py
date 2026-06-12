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

# Meeting error constants
MEETING_NOT_FOUND = "Meeting not found"
MESSAGE_NOT_FOUND = "Message not found"
MEETING_ALREADY_ENDED = "Meeting has already ended"
MEETING_IN_PROGRESS = "Meeting is already in progress"
MEETING_FULL = "Meeting is full (max 2 participants)"
ALREADY_IN_MEETING = "You are already in this meeting"
NOT_MEETING_PARTICIPANT = "Not a participant of this meeting"
NOT_AUTHORIZED_END_MEETING = "Not authorized to end this meeting"
CODE_GENERATION_FAILED = "Failed to generate unique meeting code"


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


def raise_meeting_not_found() -> NoReturn:
    raise HTTPException(status_code=404, detail=MEETING_NOT_FOUND)


def raise_message_not_found() -> NoReturn:
    raise HTTPException(status_code=404, detail=MESSAGE_NOT_FOUND)


def raise_meeting_already_ended() -> NoReturn:
    raise HTTPException(status_code=400, detail=MEETING_ALREADY_ENDED)


def raise_meeting_in_progress() -> NoReturn:
    raise HTTPException(status_code=400, detail=MEETING_IN_PROGRESS)


def raise_meeting_full() -> NoReturn:
    raise HTTPException(status_code=400, detail=MEETING_FULL)


def raise_already_in_meeting() -> NoReturn:
    raise HTTPException(status_code=400, detail=ALREADY_IN_MEETING)


def raise_not_meeting_participant() -> NoReturn:
    raise HTTPException(status_code=403, detail=NOT_MEETING_PARTICIPANT)


def raise_not_authorized_end_meeting() -> NoReturn:
    raise HTTPException(status_code=403, detail=NOT_AUTHORIZED_END_MEETING)


def raise_code_generation_failed() -> NoReturn:
    raise HTTPException(status_code=500, detail=CODE_GENERATION_FAILED)
