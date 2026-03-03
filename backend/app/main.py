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


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(dsn=str(settings.SENTRY_DSN), enable_tracing=True)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup: load ML models. Shutdown: release them.

    Gracefully handles missing ML dependencies — the REST API
    and WebSocket text messaging still work without them.
    """
    try:
        from app.ml.stt import stt_engine

        stt_engine.load_model()
    except Exception as e:
        logger.warning("STT model not loaded: %s", e)
    try:
        from app.ml.tts import tts_engine

        tts_engine.load_model()
    except Exception as e:
        logger.warning("TTS model not loaded: %s", e)

    yield

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
