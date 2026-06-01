import logging

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app import crud
from app.core.config import settings
from app.models import User, UserCreate

logger = logging.getLogger(__name__)

connect_args = {}
if settings.DATABASE_URL:
    connect_args["sslmode"] = "require"

engine = create_async_engine(
    str(settings.SQLALCHEMY_DATABASE_URI),
    connect_args=connect_args,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE_SECONDS,
    pool_pre_ping=settings.DB_POOL_PRE_PING,
)
logger.info(
    "DB pool configured: pool_size=%s max_overflow=%s recycle=%ss pre_ping=%s",
    settings.DB_POOL_SIZE,
    settings.DB_MAX_OVERFLOW,
    settings.DB_POOL_RECYCLE_SECONDS,
    settings.DB_POOL_PRE_PING,
)

# Session factory for non-DI contexts (WebSocket handlers, background tasks).
# Unlike get_db() in deps.py (request-scoped), this can create sessions anywhere.
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# make sure all SQLModel models are imported (app.models) before initializing DB
# otherwise, SQLModel might fail to initialize relationships properly
# for more details: https://github.com/fastapi/full-stack-fastapi-template/issues/28


async def init_db(session: AsyncSession) -> None:
    # Tables should be created with Alembic migrations
    # But if you don't want to use migrations, create
    # the tables un-commenting the next lines
    # from sqlmodel import SQLModel

    # This works because the models are already imported and registered from app.models
    # SQLModel.metadata.create_all(engine)

    result = await session.exec(
        select(User).where(User.email == settings.FIRST_SUPERUSER)
    )
    user = result.first()
    if not user:
        user_in = UserCreate(
            email=settings.FIRST_SUPERUSER,
            password=settings.FIRST_SUPERUSER_PASSWORD,
            is_superuser=True,
        )
        user = await crud.create_user(session=session, user_create=user_in)
