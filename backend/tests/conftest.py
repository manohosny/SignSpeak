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

# ── Remote-database guard ───────────────────────────────────
# This suite is DESTRUCTIVE: the session fixture's teardown deletes every
# user (cascading to meetings/messages). Refuse to run against anything but
# a local database. Beware: `env_ignore_empty=True` in app.core.config means
# `DATABASE_URL=''` does NOT clear the .env value — that exact mistake sent
# test runs to the remote production DB on 2026-06-12 and wiped its users.
# Point DATABASE_URL at an explicit local DSN instead, e.g.
#   DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:55432/app
import os

from sqlalchemy.engine import make_url

_LOCAL_DB_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}
_db_url = make_url(str(settings.SQLALCHEMY_DATABASE_URI))
if _db_url.host not in _LOCAL_DB_HOSTS and not os.environ.get("ALLOW_REMOTE_TEST_DB"):
    raise RuntimeError(
        f"Refusing to run the test suite against non-local database host "
        f"{_db_url.host!r} — teardown deletes all users. Set DATABASE_URL to "
        f"a local DSN, or ALLOW_REMOTE_TEST_DB=1 to override deliberately."
    )

# Sync test engine — psycopg3 supports both sync and async with same URL.
# sslmode=require only makes sense for remote (hosted) databases; a local
# throwaway Postgres has no TLS.
_connect_args = {}
if settings.DATABASE_URL and _db_url.host not in _LOCAL_DB_HOSTS:
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


@pytest.fixture(autouse=True)
def _reset_auth_rate_limit() -> Generator[None, None, None]:
    """Wipe the auth-endpoint rate-limit singleton between tests so prior
    test traffic doesn't deplete the bucket and trip 429s in unrelated tests."""
    from app.core.rate_limit import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


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
