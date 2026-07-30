"""§6.4 fixed-window rate limiting.

The limiter is deliberately storage-dumb and clock-driven, so these tests drive a fake
monotonic clock rather than sleeping. A test that sleeps for a window boundary is a test
nobody runs.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.rate_limit import (
    RateLimited,
    enforce,
    ip_key,
    key_for_email,
    key_for_user,
    limiter,
    rate_limit,
)


@pytest.fixture(autouse=True)
def _clean_limiter() -> Any:
    """Counters are process-global, so one test's consumption must not become another's."""
    limiter.reset()
    yield
    limiter.reset()


class _FakeClock:
    """Starts on an exact window boundary for every window length these tests use.

    3 600 000 is a whole multiple of 3600, 900 and 60. This matters because the windows are
    *aligned to absolute multiples* of the window length rather than started at the first
    request -- see test_windows_are_aligned_not_started_by_the_first_request. Beginning at an
    arbitrary instant like 1000.0 would put the first request 40 seconds into a 60-second
    window, and every "advance by N" below would then be reasoning about the wrong boundary.
    """

    def __init__(self) -> None:
        self.now = 3_600_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    """Drives window boundaries without sleeping. A test that sleeps for an hour-long window
    is a test nobody runs, and shortening the window to make sleeping bearable would stop
    testing the boundary arithmetic the real limits use."""
    fake = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", fake)
    limiter.reset()
    return fake


# --- the window ------------------------------------------------------------------------


def test_requests_up_to_the_limit_are_allowed_and_the_next_is_not(clock: _FakeClock) -> None:
    for expected_remaining in (2, 1, 0):
        decision = limiter.consume("bucket", limit=3, window_seconds=3600)
        assert decision.allowed is True
        assert decision.remaining == expected_remaining

    refused = limiter.consume("bucket", limit=3, window_seconds=3600)
    assert refused.allowed is False
    assert refused.remaining == 0


def test_the_window_resets_at_the_boundary(clock: _FakeClock) -> None:
    for _ in range(3):
        assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is True
    assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is False

    clock.advance(60)
    assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is True


def test_the_window_does_not_reset_early(clock: _FakeClock) -> None:
    assert limiter.consume("bucket", limit=1, window_seconds=60).allowed is True
    clock.advance(59)
    assert limiter.consume("bucket", limit=1, window_seconds=60).allowed is False


def test_windows_are_aligned_not_started_by_the_first_request(clock: _FakeClock) -> None:
    """Pinning a real characteristic of a fixed-window limiter rather than papering over it.

    Windows are absolute -- floor(now / window) -- not per-caller stopwatches started by the
    first request. A caller who arrives late in a window therefore gets a *shorter* effective
    window, and Retry-After reflects the real boundary rather than a full window length. This
    is what a Redis INCR-plus-EXPIRE implementation does too, so the Phase 2 swap named in
    rate_limit.py's header preserves the behaviour instead of changing it.
    """
    clock.advance(55)  # 55 seconds into a 60-second window
    refused_at = limiter.consume("bucket", limit=1, window_seconds=60)
    assert refused_at.allowed is True
    assert limiter.consume("bucket", limit=1, window_seconds=60).retry_after_seconds == 5

    clock.advance(5)  # the boundary, not 60 seconds after the first request
    assert limiter.consume("bucket", limit=1, window_seconds=60).allowed is True


def test_the_fixed_window_admits_up_to_twice_the_limit_across_a_boundary(
    clock: _FakeClock,
) -> None:
    """The known and accepted cost of §6.4's choice of algorithm: the limit at the end of one
    window plus the limit at the start of the next. Bounded at 2x, and documented rather than
    discovered later -- a sliding window is the Phase 2 upgrade alongside Redis."""
    clock.advance(59)
    for _ in range(3):
        assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is True
    clock.advance(1)
    for _ in range(3):
        assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is True
    assert limiter.consume("bucket", limit=3, window_seconds=60).allowed is False


def test_retry_after_counts_down_to_the_boundary_and_is_never_zero(clock: _FakeClock) -> None:
    """§6.4: "Every 429 carries a Retry-After header." A Retry-After of 0 invites an immediate
    retry that is guaranteed to fail, so the floor is 1 second."""
    limiter.consume("bucket", limit=1, window_seconds=60)
    first = limiter.consume("bucket", limit=1, window_seconds=60)
    assert first.allowed is False
    assert 1 <= first.retry_after_seconds <= 60

    clock.advance(59.9)
    late = limiter.consume("bucket", limit=1, window_seconds=60)
    assert late.allowed is False
    assert late.retry_after_seconds == 1


def test_separate_buckets_do_not_share_a_counter(clock: _FakeClock) -> None:
    assert limiter.consume("a", limit=1, window_seconds=60).allowed is True
    assert limiter.consume("a", limit=1, window_seconds=60).allowed is False
    assert limiter.consume("b", limit=1, window_seconds=60).allowed is True


def test_expired_windows_are_evicted_so_the_dict_cannot_grow_without_bound(
    clock: _FakeClock,
) -> None:
    """Buckets contain client-chosen values (IPs, submitted email addresses), so unbounded
    retention means an attacker picks how much memory we allocate."""
    for index in range(50):
        limiter.consume(f"key-{index}", limit=5, window_seconds=60)
    assert len(limiter._counts) == 50

    clock.advance(60)
    limiter.consume("key-0", limit=5, window_seconds=60)
    assert len(limiter._counts) == 1, "only the current window's entry should survive"


# --- scope and key strategies ----------------------------------------------------------


def test_the_scope_keeps_two_limits_on_the_same_key_apart(clock: _FakeClock) -> None:
    """§6.4 gives /auth/register 5/hour and /auth/social 20/hour, both keyed on IP. Sharing a
    counter would make the tighter limit silently govern both."""
    enforce(scope="auth.register", key="1.2.3.4", limit=1, window_seconds=3600)
    with pytest.raises(RateLimited):
        enforce(scope="auth.register", key="1.2.3.4", limit=1, window_seconds=3600)

    enforce(scope="auth.social", key="1.2.3.4", limit=1, window_seconds=3600)


def test_enforce_raises_rate_limit_exceeded_carrying_retry_after(clock: _FakeClock) -> None:
    enforce(scope="s", key="k", limit=1, window_seconds=900)
    with pytest.raises(RateLimited) as exc_info:
        enforce(scope="s", key="k", limit=1, window_seconds=900)

    error = exc_info.value
    assert error.code == "RATE_LIMIT_EXCEEDED"
    assert error.status == 429
    assert 1 <= error.retry_after_seconds <= 900
    assert str(error.retry_after_seconds) in (error.detail or "")


def test_the_email_key_is_case_and_whitespace_insensitive() -> None:
    """§5's convention is that emails are lowercased and trimmed before any lookup. If the
    limiter disagreed, `A@x.com` and `a@x.com` would be two buckets and §5.6's 3-per-hour
    limit would be doubled by pressing shift."""
    assert key_for_email("  Nabil@Example.COM ") == key_for_email("nabil@example.com")
    assert key_for_email("a@x.com") != key_for_email("b@x.com")


def test_an_email_key_needs_no_user_to_exist(clock: _FakeClock) -> None:
    """§5.6's oracle note: the count is against the submitted address, whether or not it
    resolves to a live account, and the 429 must be reachable for an address that has never
    registered. The limiter therefore takes a string and knows nothing about users."""
    for _ in range(3):
        enforce(
            scope="auth.password.forgot",
            key=key_for_email("never-registered@example.com"),
            limit=3,
            window_seconds=3600,
        )
    with pytest.raises(RateLimited):
        enforce(
            scope="auth.password.forgot",
            key=key_for_email("never-registered@example.com"),
            limit=3,
            window_seconds=3600,
        )


def test_the_user_key_is_distinct_per_user() -> None:
    assert key_for_user("018f-a") != key_for_user("018f-b")


# --- the dependency --------------------------------------------------------------------


async def test_the_dependency_returns_429_with_the_error_envelope(clock: _FakeClock) -> None:
    from app.core.errors import register_exception_handlers

    app = FastAPI()
    register_exception_handlers(app)

    @app.get(
        "/limited",
        dependencies=[Depends(rate_limit("test.scope", limit=2, window_seconds=3600))],
    )
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/limited")).status_code == 200
        assert (await client.get("/limited")).status_code == 200

        refused = await client.get("/limited")
        assert refused.status_code == 429
        assert refused.headers["content-type"].startswith("application/problem+json")
        body = refused.json()
        assert body["code"] == "RATE_LIMIT_EXCEEDED"
        assert body["status"] == 429
        assert body["trace_id"]


async def test_a_custom_key_strategy_is_honoured(clock: _FakeClock) -> None:
    """The key strategy is a parameter, so a route can be limited on something other than the
    IP without the limiter learning what that something is."""
    app = FastAPI()

    @app.get(
        "/by-header",
        dependencies=[
            Depends(
                rate_limit(
                    "test.header",
                    limit=1,
                    window_seconds=3600,
                    key=lambda request: request.headers.get("x-tenant", "none"),
                )
            )
        ],
    )
    async def by_header() -> dict[str, bool]:
        return {"ok": True}

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        assert (await client.get("/by-header", headers={"x-tenant": "a"})).status_code == 200
        # A different key is a different bucket, so still allowed.
        assert (await client.get("/by-header", headers={"x-tenant": "b"})).status_code == 200
        # The first key is now spent.
        with pytest.raises(RateLimited):
            await client.get("/by-header", headers={"x-tenant": "a"})


def test_ip_key_falls_back_to_one_shared_bucket_when_there_is_no_peer() -> None:
    """`request.client` is None for a transport that reports no peer. Returning a unique value
    per call would hand every such caller its own fresh allowance."""

    class _NoClientRequest:
        client = None
        headers: dict[str, str] = {}

    assert ip_key(_NoClientRequest()) == "unknown"  # type: ignore[arg-type]


def test_ip_key_ignores_x_forwarded_for() -> None:
    """The header is client-controlled: trusting it would let anyone reset their own limit by
    varying it. Behind a real proxy the fix is uvicorn --proxy-headers, which rewrites
    request.client itself."""

    class _SpoofingRequest:
        class client:  # noqa: N801
            host = "10.0.0.1"

        headers = {"x-forwarded-for": "1.2.3.4"}

    assert ip_key(_SpoofingRequest()) == "10.0.0.1"  # type: ignore[arg-type]
