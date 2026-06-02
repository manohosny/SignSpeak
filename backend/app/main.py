import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import sentry_sdk
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import Response

from app.api.main import api_router
from app.core.config import settings
from app.core.logging import bind_context, clear_context, setup_logging
from app.ws.router import router as ws_router

setup_logging()
logger = logging.getLogger(__name__)

# Readiness flag — False until ML models are loaded.
# Health check returns 503 while this is False.
_models_ready = False


def custom_generate_unique_id(route: APIRoute) -> str:
    return f"{route.tags[0]}-{route.name}"


def models_ready() -> bool:
    return _models_ready


_AUDIO_VAR_KEYWORDS = ("audio", "pcm", "wav", "buffer", "chunk")


def _scrub_sentry_event(event: dict, hint: dict) -> dict:
    """Strip audio data and large binary payloads from Sentry events."""
    if "exception" in event:
        for exc_info in event["exception"].get("values", []):
            for frame in exc_info.get("stacktrace", {}).get("frames", []):
                if frame.get("vars"):
                    for key in list(frame["vars"]):
                        if any(t in key.lower() for t in _AUDIO_VAR_KEYWORDS):
                            frame["vars"][key] = "[scrubbed]"
    return event


if settings.SENTRY_DSN and settings.ENVIRONMENT != "local":
    sentry_sdk.init(
        dsn=str(settings.SENTRY_DSN),
        enable_tracing=True,
        send_default_pii=False,
        before_send=_scrub_sentry_event,
        max_request_body_size="small",
    )
    logger.info("Sentry enabled (env=%s)", settings.ENVIRONMENT)
elif settings.SENTRY_DSN and settings.ENVIRONMENT == "local":
    logger.info(
        "Sentry DSN set but ENVIRONMENT=local — Sentry not initialized"
    )


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

    async def _load_translation() -> None:
        try:
            from app.core.config import settings

            if not settings.TRANSLATION_ENABLED:
                logger.info("Translation model disabled via TRANSLATION_ENABLED=false")
                return
            from app.ml.translation import translation_engine

            await asyncio.to_thread(
                translation_engine.load_model,
                model_name=settings.TRANSLATION_MODEL_NAME,
                device=settings.TRANSLATION_DEVICE,
                num_beams=settings.TRANSLATION_NUM_BEAMS,
                max_length=settings.TRANSLATION_MAX_LENGTH,
                dtype=settings.TRANSLATION_DTYPE,
            )
        except Exception as e:
            logger.warning("Translation model not loaded: %s", e)

    async def _load_sign_to_text() -> None:
        try:
            from app.core.config import settings

            if not settings.SIGN_TO_TEXT_ENABLED:
                logger.info("Sign-to-text model disabled via SIGN_TO_TEXT_ENABLED=false")
                return
            import os

            from app.ml.sign_to_text import sign_to_text_engine

            await asyncio.to_thread(
                sign_to_text_engine.load_model,
                repo_dir=settings.SIGN_TO_TEXT_REPO_DIR,
                checkpoint=os.path.expanduser(settings.SIGN_TO_TEXT_CHECKPOINT),
                mt5_dir=os.path.expanduser(settings.SIGN_TO_TEXT_MT5_DIR),
                device=settings.SIGN_TO_TEXT_DEVICE,
                num_beams=settings.SIGN_TO_TEXT_NUM_BEAMS,
                max_new_tokens=settings.SIGN_TO_TEXT_MAX_NEW_TOKENS,
                max_frames=settings.SIGN_TO_TEXT_MAX_FRAMES,
                dtype=settings.SIGN_TO_TEXT_DTYPE,
            )
        except Exception as e:
            logger.warning("Sign-to-text model not loaded: %s", e)

    # The handler registry, ML pipelines, and rate-limit buckets are all
    # per-process. Running multiple workers without a Redis-backed
    # registry produces split-brain meeting state, so refuse to start
    # in that configuration unless the operator has explicitly opted in.
    #
    # Note: `parent_process() is not None` is true for ANY process spawned
    # by `multiprocessing` — including the single reload worker that
    # `fastapi dev` runs. It cannot distinguish a lone reload worker from
    # real `--workers N` parallelism. Production/staging use `fastapi run`
    # (no reload), so a hard failure there still catches genuine multi-worker
    # misconfiguration; in `local` we only warn so `fastapi dev` works.
    import multiprocessing

    if multiprocessing.parent_process() is not None:
        if settings.ALLOW_MULTI_WORKER:
            logger.warning(
                "ML models loading in child worker — operator opted in "
                "via ALLOW_MULTI_WORKER=true; ensure Redis session backend "
                "and proxy-level meeting affinity are configured."
            )
        elif settings.ENVIRONMENT == "local":
            logger.warning(
                "Running in a worker subprocess (e.g. `fastapi dev` reload). "
                "Per-process meeting state assumes a single worker — fine for "
                "local development. Configure Redis session sharing and set "
                "ALLOW_MULTI_WORKER=true before running multiple workers."
            )
        else:
            raise RuntimeError(
                "Multiple workers detected but ALLOW_MULTI_WORKER is false. "
                "Run with --workers 1 or set ALLOW_MULTI_WORKER=true after "
                "configuring Redis session sharing."
            )

    # Pre-import transformers on the main thread before spawning worker threads.
    # Both the translation engine (mBART) and sign-to-text (mt5 via Uni-Sign)
    # call from_pretrained concurrently in asyncio.to_thread workers. transformers
    # resolves submodules lazily, so two threads racing the first access can see a
    # half-initialized module ("cannot import name X from transformers[.onnx]").
    # Fully warm the model/tokenizer classes (and the onnx submodule) up front so
    # every lazy import is already resolved before the threads start.
    try:
        import transformers  # noqa: F401
        from transformers import (  # noqa: F401
            MBart50TokenizerFast,
            MBartForConditionalGeneration,
            MT5ForConditionalGeneration,
            T5Tokenizer,
        )

        try:
            import transformers.onnx  # noqa: F401
        except Exception:
            pass
    except ImportError:
        pass

    # Load models SEQUENTIALLY, not via asyncio.gather. Constructing several
    # heavy models concurrently in to_thread workers was the single source of
    # repeated, hard-to-trace startup failures on Apple MPS:
    #   * two transformers `from_pretrained` calls racing -> meta-tensor params;
    #   * racing transformers lazy submodule init -> "cannot import name ... from
    #     transformers[.onnx]";
    #   * sign-to-text's sys.path mutation racing other imports;
    #   * concurrent MPS placement of the two heaviest models (NeMo STT +
    #     Uni-Sign mt5) deadlocking Metal context creation (0% CPU hang).
    # Sequential load trades a slower one-time startup for reliability. STT is
    # loaded last so a slow/failed STT doesn't gate the others. (See the
    # signspeak-direction-b memory note.)
    await _load_tts()
    await _load_translation()
    await _load_sign_to_text()
    await _load_stt()
    _models_ready = True
    logger.info("ML models ready")

    # GPU memory telemetry for capacity planning
    try:
        import torch

        if torch.cuda.is_available():
            allocated = torch.cuda.memory_allocated() / 1e6
            reserved = torch.cuda.memory_reserved() / 1e6
            logger.info(
                "GPU memory — allocated: %.0f MB, reserved: %.0f MB",
                allocated,
                reserved,
            )
    except ImportError:
        pass

    try:
        import onnxruntime as rt

        logger.info("ONNX Runtime providers: %s", rt.get_available_providers())
    except ImportError:
        pass

    # Prune expired refresh-token blacklist rows so the table doesn't grow
    # unboundedly. The startup pass is supplemented by a periodic loop
    # that re-runs every PRUNE_INTERVAL_SECONDS while the process is up,
    # so long-running deployments don't accumulate tombstones between
    # restarts. Failure is non-fatal.
    async def _prune_revoked_refresh_tokens() -> int:
        from datetime import datetime, timezone

        from sqlalchemy import delete

        from app.core.db import async_session_factory
        from app.models import RevokedRefreshToken

        async with async_session_factory() as _prune_session:
            now = datetime.now(timezone.utc)
            result = await _prune_session.execute(
                delete(RevokedRefreshToken).where(
                    RevokedRefreshToken.expires_at < now
                )
            )
            await _prune_session.commit()
            return result.rowcount or 0

    try:
        pruned = await _prune_revoked_refresh_tokens()
        if pruned:
            logger.info(
                "Pruned %d expired refresh-token blacklist rows", pruned
            )
    except Exception as e:
        logger.warning("Refresh-token blacklist prune failed: %s", e)

    async def _periodic_prune() -> None:
        interval = settings.REVOKED_TOKEN_PRUNE_INTERVAL_SECONDS
        while True:
            try:
                await asyncio.sleep(interval)
                pruned = await _prune_revoked_refresh_tokens()
                if pruned:
                    logger.info(
                        "Periodic prune dropped %d expired blacklist rows",
                        pruned,
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Periodic blacklist prune failed: %s", exc)

    prune_task: asyncio.Task | None = None
    if settings.REVOKED_TOKEN_PRUNE_INTERVAL_SECONDS > 0:
        prune_task = asyncio.create_task(
            _periodic_prune(), name="revoked-token-prune"
        )

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
    # Notify any active WebSocket clients before closing the loop, so the
    # FE displays "Reconnecting…" instead of "Connection lost". Then pause
    # briefly to let the message flush.
    try:
        from app.ws.connection_manager import manager

        await manager.broadcast_all(
            {"type": "server_shutdown", "reason": "deploy"}
        )
        if settings.WS_SHUTDOWN_GRACE_SECONDS > 0:
            await asyncio.sleep(settings.WS_SHUTDOWN_GRACE_SECONDS)
        await manager.close_all()
    except Exception as e:
        logger.warning("Graceful shutdown broadcast failed: %s", e)

    if prune_task is not None:
        prune_task.cancel()
        try:
            await prune_task
        except (asyncio.CancelledError, Exception):
            pass

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
    try:
        from app.ml.translation import translation_engine

        translation_engine.unload()
    except Exception:
        pass


# Expose the OpenAPI schema (and /docs, /redoc) in local development only.
# Staging and production disable it so the full API surface isn't enumerable
# by anyone who finds the endpoint. Client codegen runs against a local
# backend, so this does not affect `scripts/generate-client.sh`.
_openapi_url: str | None = (
    f"{settings.API_V1_STR}/openapi.json"
    if settings.ENVIRONMENT == "local"
    else None
)

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=_openapi_url,
    docs_url="/docs" if _openapi_url else None,
    redoc_url="/redoc" if _openapi_url else None,
    generate_unique_id_function=custom_generate_unique_id,
    lifespan=lifespan,
)

# Set all CORS enabled origins.
# Methods and headers are enumerated explicitly so that a stolen JWT in a
# browser context can only invoke the verbs the API actually serves —
# wildcards combined with `allow_credentials=True` form an unnecessary
# CSRF surface even with origin restrictions.
if settings.all_cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.all_cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "Idempotency-Key",
        ],
        expose_headers=["X-Request-ID"],
    )


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Bind a per-request `request_id` to log records for tracing.

    Honors an inbound `X-Request-ID` header (so upstream proxies / clients
    can propagate their trace IDs); generates a fresh UUID otherwise.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        token = bind_context(request_id=request_id, path=request.url.path)
        try:
            response = await call_next(request)
        finally:
            clear_context(token)
        response.headers["X-Request-ID"] = request_id
        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set conservative security headers on every HTTP response.

    Skipped for non-HTTP scopes (WebSocket upgrades) where the headers
    aren't meaningful. HSTS is only sent on HTTPS responses to avoid
    breaking local dev.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        # Default-deny CSP — relaxed for /docs and /redoc which load
        # CDN-hosted assets. The OpenAPI routes set their own headers
        # via FastAPI internals; keeping the default-src 'self' here
        # is appropriate for the API surface.
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; frame-ancestors 'none'",
        )
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security",
                "max-age=31536000; includeSubDomains",
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RequestContextMiddleware)

# Restrict the Host header to known good values so the app can't be
# tricked into emitting absolute links pointing at attacker-controlled
# hostnames. In local mode we accept anything to keep dev frictionless.
if settings.ENVIRONMENT != "local":
    _allowed_hosts: list[str] = []
    for origin in settings.all_cors_origins:
        # `all_cors_origins` is a list of stringified URLs; strip scheme
        # and trailing slash to extract the host[:port] part.
        host = origin.split("://", 1)[-1].rstrip("/")
        if host:
            _allowed_hosts.append(host)
    if _allowed_hosts:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=_allowed_hosts)

# REST API (under /api/v1)
app.include_router(api_router, prefix=settings.API_V1_STR)

# WebSocket (at root: /ws/{meeting_id})
app.include_router(ws_router)
