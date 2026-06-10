
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import SessionDep
from app.models import UserCreate, UserPublic
from app.services import user_service

router = APIRouter(tags=["private"], prefix="/private")


class PrivateUserCreate(BaseModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(max_length=255)


@router.post("/users/", response_model=UserPublic)
async def create_user(user_in: PrivateUserCreate, session: SessionDep) -> Any:
    user_create = UserCreate(
        email=user_in.email,
        password=user_in.password,
        full_name=user_in.full_name,
    )
    return await user_service.create_user(session=session, user_in=user_create)
