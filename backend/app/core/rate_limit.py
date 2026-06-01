"""Per-IP token-bucket rate limiter for REST endpoints.

Modeled on the same token-bucket pattern used in ws/router.py for text-
message rate limiting, just keyed by client IP and applied as a FastAPI
dependency. In-memory per-process — adequate while the service runs
single-replica. A multi-replica deployment will need a Redis-backed
implementation; the public surface (`auth_rate_limit` dependency) won't
change when that swap happens.
"""

from __future__ import annotations

import ipaddress
import logging
import threading
import time
from dataclasses import dataclass

from fastapi import HTTPException, Request, status

from app.core.config import settings

logger = logging.getLogger(__name__)


def _is_trusted_proxy(client_host: str | None) -> bool:
    """True iff the immediate peer is in the configured trusted-proxy list.

    Empty list means we are the edge — never trust X-Forwarded-For. This
    is the safe default; production deployments behind nginx/Traefik must
    set RATE_LIMIT_TRUSTED_PROXIES so legitimate forwarded-for can be
    honored without enabling spoofing from arbitrary clients.
    """
    if not client_host:
        return False
    trusted = settings.RATE_LIMIT_TRUSTED_PROXIES
    if not trusted:
        return False
    try:
        client_ip = ipaddress.ip_address(client_host)
    except ValueError:
        return False
    for entry in trusted:
        try:
            if "/" in entry:
                if client_ip in ipaddress.ip_network(entry, strict=False):
                    return True
            elif client_ip == ipaddress.ip_address(entry):
                return True
        except ValueError:
            continue
    return False


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class TokenBucketLimiter:
    """In-memory per-key token bucket.

    Thread-safe (uses a Lock around mutation) so it works under FastAPI's
    threadpool for sync dependency execution. The lock is uncontended in
    practice — auth endpoints aren't high-throughput.
    """

    def __init__(self, *, refill_per_sec: float, burst: int) -> None:
        self._refill_per_sec = refill_per_sec
        self._burst = burst
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str) -> bool:
        """Take one token for `key`. Returns True if allowed, False otherwise."""
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=float(self._burst), last_refill=now)
                self._buckets[key] = bucket
            else:
                elapsed = now - bucket.last_refill
                bucket.tokens = min(
                    self._burst, bucket.tokens + elapsed * self._refill_per_sec
                )
                bucket.last_refill = now

            if bucket.tokens < 1.0:
                return False
            bucket.tokens -= 1.0
            return True


# Singleton limiter for the auth endpoints.
_auth_limiter = TokenBucketLimiter(
    refill_per_sec=settings.AUTH_RATE_LIMIT_PER_MIN / 60.0,
    burst=settings.AUTH_RATE_LIMIT_BURST,
)


def reset_for_tests() -> None:
    """Wipe limiter state — for use in test fixtures only."""
    with _auth_limiter._lock:  # noqa: SLF001
        _auth_limiter._buckets.clear()  # noqa: SLF001


def _client_key(request: Request) -> str:
    """Identify the caller for rate-limiting purposes.

    Honors X-Forwarded-For only when the immediate peer is on the
    configured trusted-proxy list — otherwise the header is attacker-
    controlled and would let anyone bypass the limiter by rotating it.
    """
    direct_host = request.client.host if request.client else None
    if _is_trusted_proxy(direct_host):
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            # Take the first IP (the original client); the rest are proxies.
            return fwd.split(",")[0].strip()
    if direct_host:
        return direct_host
    return "unknown"


def auth_rate_limit(request: Request) -> None:
    """FastAPI dependency: 429 if the caller exceeds the per-IP auth budget."""
    key = _client_key(request)
    if not _auth_limiter.acquire(key):
        logger.warning("Auth rate limit hit for %s", key)
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests — please slow down",
        )
