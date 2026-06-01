"""Tests for the per-IP token-bucket rate limiter."""

from app.core.rate_limit import TokenBucketLimiter


def test_burst_capacity_drains_then_denies() -> None:
    """A fresh bucket allows up to `burst` calls, then denies until refill."""
    limiter = TokenBucketLimiter(refill_per_sec=0.0, burst=3)
    assert limiter.acquire("1.2.3.4") is True
    assert limiter.acquire("1.2.3.4") is True
    assert limiter.acquire("1.2.3.4") is True
    # Refill is zero — fourth call must be denied.
    assert limiter.acquire("1.2.3.4") is False


def test_separate_keys_have_independent_buckets() -> None:
    limiter = TokenBucketLimiter(refill_per_sec=0.0, burst=1)
    assert limiter.acquire("client-a") is True
    # client-a is exhausted, but client-b's bucket is untouched.
    assert limiter.acquire("client-a") is False
    assert limiter.acquire("client-b") is True


def test_refill_replenishes_tokens_over_time() -> None:
    """Sleeping `1/refill` seconds should add roughly one token back."""
    import time

    limiter = TokenBucketLimiter(refill_per_sec=10.0, burst=1)
    assert limiter.acquire("k") is True
    assert limiter.acquire("k") is False
    # 10 tokens/sec → ~0.1s for one token. Use 0.15s to absorb scheduler jitter.
    time.sleep(0.15)
    assert limiter.acquire("k") is True


def test_xff_only_honored_for_trusted_proxies(monkeypatch) -> None:
    """X-Forwarded-For must be ignored when the immediate peer is not in
    the trusted-proxy list — otherwise any client can spoof their IP."""
    from types import SimpleNamespace

    from app.core import rate_limit
    from app.core.config import settings

    monkeypatch.setattr(settings, "RATE_LIMIT_TRUSTED_PROXIES", ["10.0.0.1"])

    untrusted = SimpleNamespace(
        client=SimpleNamespace(host="203.0.113.7"),
        headers={"x-forwarded-for": "1.2.3.4"},
    )
    # Untrusted peer — the spoofed XFF must NOT be honored.
    assert rate_limit._client_key(untrusted) == "203.0.113.7"

    trusted = SimpleNamespace(
        client=SimpleNamespace(host="10.0.0.1"),
        headers={"x-forwarded-for": "1.2.3.4, 10.0.0.1"},
    )
    # Trusted proxy — the original client IP propagates.
    assert rate_limit._client_key(trusted) == "1.2.3.4"


def test_no_xff_no_trusted_uses_direct_host() -> None:
    """With no XFF header set, the immediate peer is the bucket key
    regardless of the trusted-proxy configuration."""
    from types import SimpleNamespace

    from app.core import rate_limit

    req = SimpleNamespace(
        client=SimpleNamespace(host="198.51.100.9"),
        headers={},
    )
    assert rate_limit._client_key(req) == "198.51.100.9"
