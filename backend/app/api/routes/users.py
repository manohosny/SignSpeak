import uuid

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    CurrentUser,
    SessionDep,
    get_current_active_superuser,
)
from app.core.rate_limit import auth_rate_limit
from app.models import (
    Message,
    UpdatePassword,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

# Cap the maximum page so a single GET can't ask for the full table.
_MAX_USER_PAGE_LIMIT = 200


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
async def read_users(
    session: SessionDep,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=_MAX_USER_PAGE_LIMIT),
) -> UsersPublic:
    return await user_service.list_users(session=session, skip=skip, limit=limit)


@router.post(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
    status_code=status.HTTP_201_CREATED,
)
async def create_user(*, session: SessionDep, user_in: UserCreate) -> UserPublic:
    return await user_service.create_user(session=session, user_in=user_in)


@router.patch("/me", response_model=UserPublic)
async def update_user_me(
    *, session: SessionDep, user_in: UserUpdateMe, current_user: CurrentUser
) -> UserPublic:
    return await user_service.update_user_me(
        session=session, user_in=user_in, current_user=current_user
    )


@router.patch("/me/password", response_model=Message)
async def update_password_me(
    *, session: SessionDep, body: UpdatePassword, current_user: CurrentUser
) -> Message:
    return await user_service.update_password_me(
        session=session, body=body, current_user=current_user
    )


@router.get("/me", response_model=UserPublic)
async def read_user_me(current_user: CurrentUser) -> UserPublic:
    return current_user


@router.delete("/me", response_model=Message)
async def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Message:
    return await user_service.delete_user_me(session=session, current_user=current_user)


@router.post(
    "/signup",
    response_model=UserPublic,
    dependencies=[Depends(auth_rate_limit)],
    status_code=status.HTTP_201_CREATED,
)
async def register_user(session: SessionDep, user_in: UserRegister) -> UserPublic:
    return await user_service.register_user(session=session, user_in=user_in)


@router.get("/{user_id}", response_model=UserPublic)
async def read_user_by_id(
    user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser
) -> UserPublic:
    return await user_service.get_user_by_id(
        session=session, user_id=user_id, current_user=current_user
    )


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
async def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
) -> UserPublic:
    return await user_service.update_user(
        session=session, user_id=user_id, user_in=user_in
    )


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
async def delete_user(
    session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID
) -> Message:
    return await user_service.delete_user(
        session=session, current_user=current_user, user_id=user_id
    )
