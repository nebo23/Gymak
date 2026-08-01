"""Fixed-window rate limiting (§6.4), plus exponential backoff for the one scope §6.4
names for it (`/auth/login`, A.5 item 8).

>>> SINGLE-INSTANCE ONLY. The counters below live in this process's memory. <<<
>>>
>>> Run two API instances behind a load balancer and each enforces its own private copy of
>>> every limit, so the effective limit becomes N x the configured one -- and a restart
>>> clears every window. §6.4 permits this for Phase 1 ("Redis if it is already running;
>>> otherwise an in-memory fixed-window limiter is acceptable for Phase 1, with a comment
>>> marking it as single-instance only"), and REDIS_URL already exists in Appendix A.1 as
>>> optional. The multi-instance path is Redis: replace `_InMemoryFixedWindow.consume` with
>>> an INCR plus EXPIRE on the same bucket key. Nothing above that method needs to change --
>>> `enforce` and `rate_limit` are written against the decision, not the storage.

Two entry points, because §6.4 needs both shapes:

*   `rate_limit(...)` -- a FastAPI dependency, for limits keyed on the request alone (IP).
*   `enforce(...)` -- a direct call, for limits keyed on something only the handler knows.
    §5.6's per-email limit is the reason this exists: it must be counted against the
    **submitted** address *before* any user lookup, identically for an unknown address, a
    social-only account and a live one. A dependency cannot do that without reading the body,
    and the limiter must not know what a user is.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from fastapi import Request

from app.core.errors import RateLimitExceededError


@dataclass(frozen=True, slots=True)
class RateLimitDecision:
    allowed: bool
    remaining: int
    retry_after_seconds: int


class RateLimited(RateLimitExceededError):
    """RATE_LIMIT_EXCEEDED (§7.3) carrying the value the `Retry-After` header needs.

    Subclassed here rather than in errors.py, which T-03 may not touch, and it inherits
    code/status/title unchanged so the envelope is identical -- this adds data, not a new
    error. NOTE: emitting the actual header still needs one line in `errors.py`'s
    `_problem_response`; §6.4 requires it and no T-03 route applies a limit yet, so it is
    flagged for T-04 rather than smuggled in here.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail=f"Too many requests. Retry after {retry_after_seconds} seconds.")


# A.5 item 8 / §6.4: "/auth/login ... 10 / 15 min, then exponential backoff." The base
# fixed window below enforces the "10 / 15 min" half on its own; these two constants are
# the "then exponential backoff" half, applied only to the scope named in
# `_ESCALATED_SCOPES`. Base delay chosen so the FIRST trip (the case the existing
# test_login_is_rate_limited_at_ten_per_fifteen_minutes test already asserts on) still
# lands well inside a sane Retry-After, and doubles from there; capped so a very long
# streak cannot make the header itself absurd.
_BACKOFF_BASE_SECONDS: Final[int] = 30
_BACKOFF_MAX_SECONDS: Final[int] = 3600
_ESCALATED_SCOPES: Final[frozenset[str]] = frozenset({"auth.login"})


class _InMemoryFixedWindow:
    """Counters keyed by bucket, reset on a wall-clock-independent window boundary.

    `time.monotonic` rather than `time.time`: a fixed window derived from wall time can be
    widened or reset by an NTP step or a DST change, and a limiter that a clock adjustment can
    unlock is not a limiter.

    Fixed window, not sliding: it permits up to 2x the limit across a boundary (limit at the
    end of one window, limit at the start of the next). That is the known and accepted cost of
    §6.4's choice of algorithm, and it is bounded -- a sliding window is the Phase 2 upgrade
    alongside Redis, not something to hand-roll here.
    """

    def __init__(self) -> None:
        self._counts: dict[tuple[str, int], int] = {}
        # A.5 item 8: escalating penalty state, kept separate from the fixed-window
        # counts above -- bucket -> (violation streak, monotonic time the penalty
        # expires). Only touched for buckets built from an `_ESCALATED_SCOPES` scope.
        self._violations: dict[str, tuple[int, float]] = {}
        # FastAPI runs sync dependencies in a worker thread pool, so `consume` is not
        # guaranteed to be called only from the event loop thread. The lock is uncontended in
        # the normal case and makes the read-modify-write atomic regardless.
        self._lock = threading.Lock()

    def consume(
        self, bucket: str, *, limit: int, window_seconds: int, escalate: bool = False
    ) -> RateLimitDecision:
        now = time.monotonic()

        with self._lock:
            window_index = int(now // window_seconds)
            window_ends_at = (window_index + 1) * window_seconds
            retry_after = max(1, math.ceil(window_ends_at - now))

            if escalate:
                self._evict_stale_violations(now)
                locked_until = self._active_lock(bucket, now)
                if locked_until is not None:
                    # Still serving a penalty from an earlier violation -- hammering the
                    # endpoint again while locked out is itself another violation, so
                    # this extends (escalates) the penalty rather than merely reporting
                    # the remaining wait on the current one. As with the window-limit
                    # branch below, the header must never promise earlier than the base
                    # window itself will allow.
                    return RateLimitDecision(
                        allowed=False,
                        remaining=0,
                        retry_after_seconds=max(retry_after, self._penalise(bucket, now)),
                    )

            self._evict_expired_windows(window_index)
            key = (bucket, window_index)
            used = self._counts.get(key, 0)
            if used >= limit:
                if escalate:
                    retry_after = max(retry_after, self._penalise(bucket, now))
                return RateLimitDecision(
                    allowed=False, remaining=0, retry_after_seconds=retry_after
                )
            self._counts[key] = used + 1
            if escalate:
                # A request that cleared both the window count and any active lock is a
                # clean one -- the streak represents CONSECUTIVE abuse, not lifetime
                # abuse, so it resets here rather than only on lock expiry.
                self._violations.pop(bucket, None)
            return RateLimitDecision(
                allowed=True, remaining=limit - used - 1, retry_after_seconds=retry_after
            )

    def _active_lock(self, bucket: str, now: float) -> float | None:
        entry = self._violations.get(bucket)
        if entry is None:
            return None
        _streak, locked_until = entry
        return locked_until if locked_until > now else None

    def _penalise(self, bucket: str, now: float) -> int:
        """Record one more violation for `bucket` and return the new Retry-After.

        Delay doubles with every consecutive violation (30s, 60s, 120s, ...), capped at
        `_BACKOFF_MAX_SECONDS` -- true exponential backoff, distinct from the base fixed
        window's own Retry-After (which only ever reflects time-to-window-boundary).
        """
        streak, _ = self._violations.get(bucket, (0, 0.0))
        streak += 1
        delay: int = min(_BACKOFF_MAX_SECONDS, _BACKOFF_BASE_SECONDS * (2 ** (streak - 1)))
        self._violations[bucket] = (streak, now + delay)
        return max(1, delay)

    def _evict_expired_windows(self, current_window_index: int) -> None:
        """Without this the dict grows for the life of the process, one entry per distinct
        key per window -- and the keys include client IPs and submitted email addresses, so an
        attacker choosing fresh values is choosing how much memory we allocate. Callers hold
        the lock."""
        stale = [key for key in self._counts if key[1] < current_window_index]
        for key in stale:
            del self._counts[key]

    def _evict_stale_violations(self, now: float) -> None:
        """Same memory concern as `_evict_expired_windows`, for the penalty table: once a
        bucket's lock has been expired for longer than the maximum possible penalty, it
        cannot still be "mid-streak" in any meaningful sense, so it is safe to drop --
        the next violation from that bucket, if any, just starts a fresh streak at 1.
        """
        stale = [
            b
            for b, (_streak, locked_until) in self._violations.items()
            if locked_until < now - _BACKOFF_MAX_SECONDS
        ]
        for b in stale:
            del self._violations[b]

    def reset(self) -> None:
        """Clear every counter. For tests, and for nothing else."""
        with self._lock:
            self._counts.clear()
            self._violations.clear()


limiter: Final = _InMemoryFixedWindow()


# --- key strategies ---------------------------------------------------------------------
#
# A key strategy is any Callable[[Request], str]. The scope is kept separate from the key so
# two limits on the same IP (register 5/hour, social 20/hour -- §6.4) cannot share a counter.

KeyStrategy = Callable[[Request], str]


def ip_key(request: Request) -> str:
    """The client address. `request.client` is None for an ASGI transport that reports no
    peer (an in-process test client, for one), and every such caller must land in the same
    bucket rather than each getting a free allowance.

    Deliberately does NOT read X-Forwarded-For: that header is client-controlled, so trusting
    it here would let anyone reset their own limit by varying it. Behind a real proxy the
    correct fix is uvicorn's --proxy-headers with trusted hosts configured, which rewrites
    request.client itself.
    """
    return request.client.host if request.client is not None else "unknown"


def key_for_email(email: str) -> str:
    """§5.6: keyed on the submitted address, lowercased to match §5's "emails are lowercased
    and trimmed before any lookup" convention -- otherwise `A@x.com` and `a@x.com` are two
    buckets and the 3-per-hour limit is trivially doubled."""
    return f"email:{email.strip().casefold()}"


def key_for_user(user_id: object) -> str:
    return f"user:{user_id}"


# --- enforcement ------------------------------------------------------------------------


def enforce(*, scope: str, key: str, limit: int, window_seconds: int) -> RateLimitDecision:
    """Consume one unit and raise RateLimited if the window is full.

    Returns the decision on success so a caller can surface the remaining allowance.

    A.5 item 8: `scope` alone decides whether exponential backoff applies, rather than
    a parameter every call site would need to pass -- `/auth/login` (auth.py) calls
    this function exactly as T-04 wrote it, keyed on IP and then on email, "whichever
    trips first" per §6.4; naming the scope here is what lets that call site stay
    unchanged while still getting the escalation §6.4 asks for.
    """
    decision = limiter.consume(
        f"{scope}:{key}",
        limit=limit,
        window_seconds=window_seconds,
        escalate=scope in _ESCALATED_SCOPES,
    )
    if not decision.allowed:
        raise RateLimited(decision.retry_after_seconds)
    return decision


def rate_limit(
    scope: str,
    *,
    limit: int,
    window_seconds: int,
    key: KeyStrategy = ip_key,
) -> Callable[[Request], None]:
    """Build a dependency enforcing one §6.4 row. Usage at the route is a single line:

        @router.post("/register", dependencies=[Depends(
            rate_limit("auth.register", limit=5, window_seconds=3600))])

    `key` defaults to `ip_key` because most §6.4 rows are IP-keyed, and is a parameter
    because §5.6's is not.
    """

    def dependency(request: Request) -> None:
        enforce(scope=scope, key=key(request), limit=limit, window_seconds=window_seconds)

    return dependency
