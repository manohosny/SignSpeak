import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI
from fastapi.routing import APIRoute
from starlette.middleware.cors import CORSMiddleware

from app.api.main import api_router
from app.core.config import settings
from app.ws.router import router as ws_router

logger = logging.getLogger(__name__)

# Readiness flag — False until ML models are loaded.
# Health check returns 503 while this is False.
_models_ready = False


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


def models_ready() -> bool:
    return _models_ready


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: load ML models in parallel. Shutdown: release them.

    Gracefully handles missing ML dependencies — the REST API
    and WebSocket text messaging still work without them.
    """
    global _models_ready

    async def _load_stt() -> None:
        try:
            from app.ml.stt import stt_engine

            await asyncio.to_thread(stt_engine.load_model)
        except Exception as e:
            logger.warning("STT model not loaded: %s", e)

    async def _load_tts() -> None:
        try:
            from app.ml.tts import tts_engine

            await asyncio.to_thread(tts_engine.load_model)
        except Exception as e:
            logger.warning("TTS model not loaded: %s", e)

    await asyncio.gather(_load_stt(), _load_tts())
    _models_ready = True
    logger.info("ML models ready")

    # Initialize Redis session backend if configured
    redis_backend = None
    if settings.REDIS_URL:
        try:
            from app.ws.backends.redis import RedisSessionBackend
            from app.ws.connection_manager import manager

            redis_backend = RedisSessionBackend(settings.REDIS_URL)
            await redis_backend.connect()
            manager.set_backend(redis_backend)
            logger.info("Redis session backend initialized")
        except Exception as e:
            logger.warning(
                "Redis session backend not available, using memory: %s", e
            )
            redis_backend = None

    yield

    # Shutdown
    if redis_backend:
        await redis_backend.close()
    _models_ready = False
    try:
        from app.ml.stt import stt_engine

        stt_engine.unload()
    except Exception:
        pass
    try:
        from app.ml.tts import tts_engine

        tts_engine.unload()
    except Exception:
        pass


app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# REST API (under /api/v1)
app.include_router(api_router, prefix=settings.API_V1_STR)

# WebSocket (at root: /ws/{meeting_id})
app.include_router(ws_router)
