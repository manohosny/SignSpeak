import secrets
import warnings
from typing import Annotated, Any, Literal

from pydantic import (
    AnyUrl,
    BeforeValidator,
    EmailStr,
    HttpUrl,
    PostgresDsn,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing_extensions import Self


def parse_cors(v: Any) -> list[str] | str:
    if isinstance(v, str) and not v.startswith("["):
        return [i.strip() for i in v.split(",") if i.strip()]
    elif isinstance(v, list | str):
        return v
    raise ValueError(v)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Use top level .env file (one level above ./backend/)
        env_file="../.env",
        env_ignore_empty=True,
        extra="ignore",
    )
    API_V1_STR: str = "/api/v1"
    # SECRET_KEY must be provided explicitly in non-local environments.
    # In local mode we synthesize one in `_require_secret_key` so dev
    # bootstrap doesn't require touching `.env`. The class-level default
    # is `None` rather than an auto-generated random because that random
    # would silently pass any "is this still the default?" check while
    # producing per-process keys that break JWT validation across workers.
    SECRET_KEY: str | None = None
    # JWT audience / issuer markers — included on every signed token and
    # validated on decode. A leak of the SECRET_KEY no longer permits
    # cross-purpose forgery between access, refresh, and reset tokens.
    JWT_ISSUER: str = "signspeak"
    # Short-lived access tokens (rotated via refresh) close the window
    # for stolen-credential abuse. Refresh tokens carry the long horizon.
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 14
    FRONTEND_HOST: str = "http://localhost:5173"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"

    BACKEND_CORS_ORIGINS: Annotated[
        list[AnyUrl] | str, BeforeValidator(parse_cors)
    ] = []

    @computed_field  # type: ignore[prop-decorator]
    @property
    def all_cors_origins(self) -> list[str]:
        return [str(origin).rstrip("/") for origin in self.BACKEND_CORS_ORIGINS] + [
            self.FRONTEND_HOST
        ]

    PROJECT_NAME: str
    SENTRY_DSN: HttpUrl | None = None

    # Supabase / cloud: single connection string (takes precedence)
    DATABASE_URL: str | None = None

    # Legacy / local Docker: separate components (fallback)
    POSTGRES_SERVER: str = ""
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = ""
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = ""

    @staticmethod
    def _normalize_postgres_url(url: str) -> str:
        """Normalize various PostgreSQL URL schemes to use psycopg driver."""
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+psycopg://", 1)
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+psycopg://", 1)
        return url

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SQLALCHEMY_DATABASE_URI(self) -> PostgresDsn:
        if self.DATABASE_URL:
            return PostgresDsn(self._normalize_postgres_url(self.DATABASE_URL))
        return PostgresDsn.build(
            scheme="postgresql+psycopg",
            username=self.POSTGRES_USER,
            password=self.POSTGRES_PASSWORD,
            host=self.POSTGRES_SERVER,
            port=self.POSTGRES_PORT,
            path=self.POSTGRES_DB,
        )

    # ── ML / Audio Pipeline ──
    STT_BUFFER_MODE: str = "utterance"  # "utterance" | "fixed"

    # ── Translation (mBART-50 ASL) ──
    TRANSLATION_MODEL_NAME: str = "manohonsy/asl-mbart-50-lora"
    TRANSLATION_DEVICE: str = "auto"        # auto | cuda | mps | cpu
    TRANSLATION_NUM_BEAMS: int = 1          # 1 = greedy (CPU/MPS); 4 = beam search (CUDA only)
    TRANSLATION_DTYPE: str = "auto"         # auto | fp16 | fp32
    TRANSLATION_MAX_LENGTH: int = 128
    TRANSLATION_ENABLED: bool = True        # kill switch

    # ── Sign-to-Text (Uni-Sign, gloss-free signs -> English) ──
    SIGN_TO_TEXT_ENABLED: bool = True       # kill switch (Direction B signs path)
    SIGN_TO_TEXT_REPO_DIR: str = "third_party/Uni-Sign"     # vendored Uni-Sign clone
    SIGN_TO_TEXT_CHECKPOINT: str = "~/.signspeak/models/uni-sign/how2sign_pose_only_slt.pth"
    SIGN_TO_TEXT_MT5_DIR: str = "~/.signspeak/models/mt5-base"
    SIGN_TO_TEXT_DEVICE: str = "auto"       # auto | cuda | mps | cpu
    SIGN_TO_TEXT_NUM_BEAMS: int = 1         # 1 = greedy (CPU/MPS)
    SIGN_TO_TEXT_MAX_NEW_TOKENS: int = 100
    SIGN_TO_TEXT_MAX_FRAMES: int = 256      # model T cap; segment buffer force-flush
    SIGN_TO_TEXT_DTYPE: str = "fp32"        # fp32 on MPS (no bf16)
    # Sentence segmentation (the gap not covered by the released model):
    SIGN_TO_TEXT_PAUSE_MS: int = 700        # low-motion duration that ends a sentence
    SIGN_TO_TEXT_MOTION_THRESHOLD: float = 0.01  # mean hand-kp displacement threshold

    # ── Redis (optional, for multi-server WebSocket scaling) ──
    REDIS_URL: str | None = None

    # ── WebSocket lifecycle ──
    # On graceful shutdown, broadcast a `server_shutdown` notice to active
    # clients and pause this many seconds before tearing down the process,
    # giving the FE time to display "Reconnecting…" and start its retry loop.
    WS_SHUTDOWN_GRACE_SECONDS: float = 3.0

    # ── Refresh-token blacklist housekeeping ──
    # The lifespan loop deletes expired rows on this cadence. Set to 0
    # to disable the periodic pass (only the startup prune runs). Defaults
    # to one hour, well below the 14-day refresh expiry so tombstones
    # never accumulate for long.
    REVOKED_TOKEN_PRUNE_INTERVAL_SECONDS: int = 3600

    # ── REST rate limiting (auth endpoints) ──
    # Per-IP token bucket applied to login + refresh + register. Defaults
    # are chosen for "rare legitimate retries" (e.g. typo, network blip)
    # while making credential brute-force impractical. Multi-replica
    # deployments need a Redis-backed limiter; this in-memory version is
    # adequate while the system is single-replica.
    AUTH_RATE_LIMIT_PER_MIN: int = 10
    AUTH_RATE_LIMIT_BURST: int = 15

    # IPs / CIDRs of upstream proxies whose `X-Forwarded-For` header the
    # rate limiter should trust. Empty (the default) means we treat the
    # immediate peer as authoritative — appropriate when there is no
    # proxy in front. In production set this to the proxy's egress IP
    # (or its subnet) so legitimate client IPs propagate without
    # allowing arbitrary clients to spoof the header.
    RATE_LIMIT_TRUSTED_PROXIES: Annotated[
        list[str] | str, BeforeValidator(parse_cors)
    ] = []

    # ── Database connection pool ──
    # Size the pool for the expected concurrent request load.
    # Each WebSocket message that touches the DB (e.g. message persistence)
    # acquires a connection; under-sizing here will stall the event loop.
    # Defaults assume a small single-replica deployment — tune up per
    # replica's concurrent meeting count.
    DB_POOL_SIZE: int = 30
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE_SECONDS: int = 1800
    DB_POOL_PRE_PING: bool = True

    # ── Worker topology ──
    # The handler registry and ML pipelines are per-process, so a
    # multi-worker deployment splits meeting state across workers and
    # produces incoherent ML output. The lifespan hook hard-fails at
    # startup if it detects a child process unless this is set to True
    # (which acknowledges that the operator has wired Redis-backed
    # session sharing for the WS layer).
    ALLOW_MULTI_WORKER: bool = False

    SMTP_TLS: bool = True
    SMTP_SSL: bool = False
    SMTP_PORT: int = 587
    SMTP_HOST: str | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    EMAILS_FROM_EMAIL: EmailStr | None = None
    EMAILS_FROM_NAME: str | None = None

    @model_validator(mode="after")
    def _set_default_emails_from(self) -> Self:
        if not self.EMAILS_FROM_NAME:
            self.EMAILS_FROM_NAME = self.PROJECT_NAME
        return self

    @model_validator(mode="after")
    def _validate_email_config(self) -> Self:
        # Surface partial SMTP config explicitly. Otherwise emails_enabled
        # silently returns False and password reset / account creation
        # paths fail without any operational signal that they are
        # misconfigured. Local environments only get a warning so dev
        # bootstrap doesn't require a working SMTP.
        smtp_host = bool(self.SMTP_HOST)
        emails_from = bool(self.EMAILS_FROM_EMAIL)
        if smtp_host != emails_from:
            message = (
                "SMTP_HOST and EMAILS_FROM_EMAIL must both be set or both unset; "
                f"got SMTP_HOST={self.SMTP_HOST!r}, EMAILS_FROM_EMAIL={self.EMAILS_FROM_EMAIL!r}"
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)
        return self

    EMAIL_RESET_TOKEN_EXPIRE_HOURS: int = 48

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        return bool(self.SMTP_HOST and self.EMAILS_FROM_EMAIL)

    EMAIL_TEST_USER: EmailStr = "test@example.com"
    FIRST_SUPERUSER: EmailStr
    FIRST_SUPERUSER_PASSWORD: str

    def _check_default_secret(self, var_name: str, value: str | None) -> None:
        if value == "changethis":
            message = (
                f'The value of {var_name} is "changethis", '
                "for security, please change it, at least for deployments."
            )
            if self.ENVIRONMENT == "local":
                warnings.warn(message, stacklevel=1)
            else:
                raise ValueError(message)

    @model_validator(mode="after")
    def _require_secret_key(self) -> Self:
        if not self.SECRET_KEY:
            if self.ENVIRONMENT == "local":
                # Dev convenience only — every process gets a different
                # random, so JWTs do not survive a restart.
                self.SECRET_KEY = secrets.token_urlsafe(32)
            else:
                raise ValueError(
                    "SECRET_KEY must be set explicitly in non-local environments"
                )
        return self

    @model_validator(mode="after")
    def _enforce_non_default_secrets(self) -> Self:
        self._check_default_secret("SECRET_KEY", self.SECRET_KEY)
        if not self.DATABASE_URL:
            self._check_default_secret("POSTGRES_PASSWORD", self.POSTGRES_PASSWORD)
        self._check_default_secret(
            "FIRST_SUPERUSER_PASSWORD", self.FIRST_SUPERUSER_PASSWORD
        )

        return self


settings = Settings()  # type: ignore
