from collections.abc import AsyncGenerator, Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlmodel import Session, delete, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.core.db import engine as async_engine
from app.core.security import get_password_hash
from app.main import app
from app.models import User
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers

# Sync test engine — psycopg3 supports both sync and async with same URL
_connect_args = {}
if settings.DATABASE_URL:
    _connect_args["sslmode"] = "require"

test_engine = create_engine(
    str(settings.SQLALCHEMY_DATABASE_URI), connect_args=_connect_args
)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    with Session(test_engine) as session:
        # Inline superuser init (init_db is now async)
        result = session.exec(
            select(User).where(User.email == settings.FIRST_SUPERUSER)
        )
        user = result.first()
        if not user:
            user = User(
                email=settings.FIRST_SUPERUSER,
                hashed_password=get_password_hash(settings.FIRST_SUPERUSER_PASSWORD),
                is_superuser=True,
                is_active=True,
            )
            session.add(user)
            session.commit()
            session.refresh(user)

        yield session

        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture()
async def async_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSession(async_engine) as session:
        yield session


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
