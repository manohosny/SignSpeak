from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic.networks import EmailStr

from app.api.deps import get_current_active_superuser
from app.models import Message
from app.services.email_service import generate_test_email, send_email

router = APIRouter(prefix="/utils", tags=["utils"])


@router.post(
    "/test-email/",
    dependencies=[Depends(get_current_active_superuser)],
    status_code=201,
)
async def test_email(email_to: EmailStr) -> Message:
    email_data = generate_test_email(email_to=email_to)
    send_email(
        email_to=email_to,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )
    return Message(message="Test email sent")


@router.get("/health-check/")
async def health_check() -> JSONResponse:
    from app.main import models_ready

    if not models_ready():
        return JSONResponse(
            status_code=503,
            content={"status": "loading", "detail": "ML models not ready"},
        )
    return JSONResponse(content={"status": "ok"})
