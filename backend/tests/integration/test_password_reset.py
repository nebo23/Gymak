"""§5.6 (password reset, three calls), P1-ADR-04, P1-ADR-07, §12 T-07.

Per the rule this task was given, every test here asserts that a control prevents
something -- expiry, the sixth attempt, code reuse, token reuse, enumeration via the
202/429 split, concurrent double-redemption, and offline recovery of a code from its
stored digest -- rather than that the happy path works. The happy path only appears as
setup for those assertions, via `_get_valid_code` / `_get_reset_token`.

The rate limiter and `ConsoleEmailSender`'s sent-message list are both process-global
singletons, so both are reset before and after every test, the same reasoning
test_auth_register_login.py gives for the rate limiter alone.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.rate_limit import limiter
from app.core.security import RESET_CODE_ALPHABET, hash_reset_code
from app.database import set_rls_user
from app.integrations.email.console import ConsoleEmailSender
from app.models.refresh_token import RefreshToken
from app.models.reset_code import PasswordResetCode
from app.models.user import User
from tests.support import JSONDict, json_body

pytestmark = pytest.mark.asyncio

_REGISTER = "/api/v1/auth/register"
_FORGOT = "/api/v1/auth/password/forgot"
_VERIFY = "/api/v1/auth/password/verify-code"
_RESET = "/api/v1/auth/password/reset"
_REFRESH = "/api/v1/auth/refresh"
_PASSWORD = "correct horse battery"
_NEW_PASSWORD = "a different horse battery"

_CODE_RE = re.compile(f"[{RESET_CODE_ALPHABET}]{{8}}")


@pytest.fixture(autouse=True)
def _isolated_globals() -> Iterator[None]:
    limiter.reset()
    ConsoleEmailSender.reset()
    yield
    limiter.reset()
    ConsoleEmailSender.reset()


def _unique_email(prefix: str = "user") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}@example.com"


async def _register(client: AsyncClient, *, email: str | None = None) -> JSONDict:
    response = await client.post(
        _REGISTER, json={"email": email or _unique_email(), "password": _PASSWORD}
    )
    assert response.status_code == 201
    return json_body(response)


async def _forgot(client: AsyncClient, email: str) -> Response:
    return await client.post(_FORGOT, json={"email": email})


async def _verify(client: AsyncClient, *, email: str, code: str) -> Response:
    return await client.post(_VERIFY, json={"email": email, "code": code})


async def _reset(
    client: AsyncClient, *, reset_token: str, new_password: str = _NEW_PASSWORD
) -> Response:
    return await client.post(
        _RESET, json={"reset_token": reset_token, "new_password": new_password}
    )


def _last_sent_code() -> str:
    """Pulls the code out of the most recently "sent" email's rendered HTML -- the
    only place a raw code exists outside the request that generated it; the database
    only ever holds its peppered digest (P1-ADR-07).
    """
    assert ConsoleEmailSender.sent, "no email was sent"
    matches = _CODE_RE.findall(ConsoleEmailSender.sent[-1].html_body)
    assert len(matches) == 1, matches
    code = matches[0]
    assert isinstance(code, str)
    return code


async def _get_valid_code(client: AsyncClient, email: str) -> str:
    response = await _forgot(client, email)
    assert response.status_code == 202
    return _last_sent_code()


async def _get_reset_token(client: AsyncClient, email: str) -> str:
    code = await _get_valid_code(client, email)
    response = await _verify(client, email=email, code=code)
    assert response.status_code == 200
    reset_token = json_body(response)["reset_token"]
    assert isinstance(reset_token, str)
    return reset_token


async def _get_code_row(db_session: AsyncSession, user_id: uuid.UUID) -> PasswordResetCode:
    """Only ever called with exactly one live row for the user -- each test that uses
    this requests a single code and inspects it before requesting another.
    """
    result = await db_session.execute(
        select(PasswordResetCode).where(PasswordResetCode.user_id == user_id)
    )
    return result.scalar_one()


# --- forgot: the anti-enumeration controls ----------------------------------------------


async def test_forgot_returns_202_and_sends_nothing_for_an_unknown_email(
    client: AsyncClient,
) -> None:
    response = await _forgot(client, _unique_email("never-registered"))

    assert response.status_code == 202
    assert response.json() == {
        "message": "If an account exists for that address, a code has been sent."
    }
    assert ConsoleEmailSender.sent == []


async def test_forgot_returns_202_and_sends_nothing_for_a_social_only_account(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """§5.6: "Social-only account: Still returns 202 and still sends nothing. Do not
    reveal that the account has no password." A minimal social-only row (password_hash
    NULL) is enough to exercise forgot's own branch -- this test is not a claim about
    the linked-identity invariant A.5 item 14 tracks separately.
    """
    email = _unique_email("social-only")
    user = User(email=email, password_hash=None, email_verified=True)
    db_session.add(user)
    await db_session.commit()

    response = await _forgot(client, email)

    assert response.status_code == 202
    assert ConsoleEmailSender.sent == []


async def test_forgot_requesting_a_new_code_kills_the_previous_one(
    client: AsyncClient,
) -> None:
    """§4.5: "Requesting a new code marks every previous unconsumed code for that user
    as consumed, so only the newest code works." A stale first code must not still be
    redeemable once a second has been requested.
    """
    email = _unique_email()
    await _register(client, email=email)

    stale_code = await _get_valid_code(client, email)
    fresh_code = await _get_valid_code(client, email)
    assert stale_code != fresh_code

    stale_attempt = await _verify(client, email=email, code=stale_code)
    assert stale_attempt.status_code == 422
    assert stale_attempt.json()["code"] == "RESET_CODE_INVALID"

    fresh_attempt = await _verify(client, email=email, code=fresh_code)
    assert fresh_attempt.status_code == 200


async def test_forgot_per_email_rate_limit_trips_for_an_address_that_was_never_registered(
    client: AsyncClient,
) -> None:
    """§5.6's own warning: "the per-email rate limit must not become the enumeration
    oracle the 202 exists to prevent." An address with no account must still be able
    to trip the 3-per-hour limit -- if it could not, the 429-vs-202 split itself would
    tell an attacker whether the address has an account.
    """
    email = _unique_email("never-registered")

    for _ in range(3):
        response = await _forgot(client, email)
        assert response.status_code == 202

    tripped = await _forgot(client, email)
    assert tripped.status_code == 429
    assert tripped.json()["code"] == "RATE_LIMIT_EXCEEDED"
    assert "Retry-After" in tripped.headers
    assert ConsoleEmailSender.sent == []


# --- verify-code: the five controls the code itself enforces ----------------------------


async def test_verify_code_wrong_code_is_rejected_and_the_sixth_attempt_is_blocked_outright(
    client: AsyncClient,
) -> None:
    """§5.6: 5 attempts, then the code is burned -- even the *correct* code on the
    sixth try must fail, or the cap is decorative rather than a real barrier.
    """
    email = _unique_email()
    await _register(client, email=email)
    code = await _get_valid_code(client, email)

    for attempt in range(5):
        response = await _verify(client, email=email, code="ZZZZZZZZ")
        assert response.status_code == 422, f"attempt {attempt}"
        assert response.json()["code"] == "RESET_CODE_INVALID"

    burned = await _verify(client, email=email, code=code)
    assert burned.status_code == 429
    assert burned.json()["code"] == "RESET_CODE_ATTEMPTS_EXCEEDED"
    assert "Retry-After" in burned.headers


async def test_verify_code_expired_code_is_rejected_and_still_counts_as_an_attempt(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """§5.6: "attempt_count increments on every failed verify, including expired
    ones" -- and expiry is enforced in the SQL WHERE, not a Python comparison after
    the fetch, which this test cannot observe directly but the enforcement chain
    (reset_repo.get_active_code_for_update / get_unconsumed_code_for_update) is
    built around.
    """
    email = _unique_email()
    registered = await _register(client, email=email)
    user_id = uuid.UUID(registered["user"]["id"])
    code = await _get_valid_code(client, email)

    row = await _get_code_row(db_session, user_id)
    row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()

    response = await _verify(client, email=email, code=code)
    assert response.status_code == 422
    assert response.json()["code"] == "RESET_CODE_EXPIRED"

    await db_session.refresh(row)
    assert row.attempt_count == 1


async def test_verify_code_reusing_an_already_redeemed_code_fails(client: AsyncClient) -> None:
    """§4.5 / §5.6: consumed_at is single-use. A code that already won a reset token
    must not be usable to win a second one.
    """
    email = _unique_email()
    await _register(client, email=email)
    code = await _get_valid_code(client, email)

    first = await _verify(client, email=email, code=code)
    assert first.status_code == 200

    second = await _verify(client, email=email, code=code)
    assert second.status_code == 422
    assert second.json()["code"] == "RESET_CODE_INVALID"


async def test_verify_code_concurrent_redemption_of_the_same_code_leaves_exactly_one_winner(
    client: AsyncClient,
) -> None:
    """§5.6: "Two simultaneous redemptions must leave exactly one winner." The two
    requests race for real (asyncio.gather against the live ASGI app, each on its own
    DB session via the get_db dependency) rather than being serialised by the test.
    """
    email = _unique_email()
    await _register(client, email=email)
    code = await _get_valid_code(client, email)

    responses = await asyncio.gather(
        _verify(client, email=email, code=code),
        _verify(client, email=email, code=code),
    )

    statuses = sorted(response.status_code for response in responses)
    assert statuses == [200, 422]

    winners = [r for r in responses if r.status_code == 200]
    assert len(winners) == 1
    assert winners[0].json()["reset_token"]


async def test_stored_code_digest_cannot_be_verified_without_the_pepper(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """P1-ADR-07's whole point: the pepper, not the code length, is what defeats
    offline recovery. Even holding the exact plaintext code (extracted from the
    "sent" email, exactly as a table-reading attacker holding only the digest could
    never do) and the row's own user_id, recomputing the digest with anything other
    than the real `RESET_CODE_PEPPER` must not reproduce the stored value -- an
    unkeyed hash (the superseded design) or a wrong key both fail to verify.
    """
    email = _unique_email()
    registered = await _register(client, email=email)
    user_id = uuid.UUID(registered["user"]["id"])
    code = await _get_valid_code(client, email)

    row = await _get_code_row(db_session, user_id)

    unkeyed_digest = hashlib.sha256(f"{user_id}{code}".encode()).hexdigest()
    wrong_key_digest = hmac.new(
        b"a-completely-different-pepper", f"{user_id}{code}".encode(), hashlib.sha256
    ).hexdigest()

    assert row.code_hash != unkeyed_digest
    assert row.code_hash != wrong_key_digest
    # Only the real, configured pepper reproduces it -- proving the digest really is
    # keyed to a secret this test never had to read out of the database.
    assert row.code_hash == hash_reset_code(user_id, code)


async def test_verify_code_unknown_email_returns_the_same_generic_error_as_a_wrong_code(
    client: AsyncClient,
) -> None:
    """§5.6's anti-enumeration principle is not just about `forgot`: verify-code must
    not let a caller distinguish "this email never had an account" from "this email
    has an account but I guessed the code wrong" -- both are 422 RESET_CODE_INVALID.
    """
    response = await _verify(client, email=_unique_email("never-registered"), code="ZZZZZZZZ")
    assert response.status_code == 422
    assert response.json()["code"] == "RESET_CODE_INVALID"


# --- reset: the token's own controls -----------------------------------------------------


async def test_reset_with_an_unknown_reset_token_is_rejected(client: AsyncClient) -> None:
    response = await _reset(client, reset_token="rt_this-was-never-issued")
    assert response.status_code == 401
    assert response.json()["code"] == "RESET_TOKEN_INVALID"


async def test_reset_reusing_an_already_spent_reset_token_fails(client: AsyncClient) -> None:
    email = _unique_email()
    await _register(client, email=email)
    reset_token = await _get_reset_token(client, email)

    first = await _reset(client, reset_token=reset_token)
    assert first.status_code == 204

    second = await _reset(client, reset_token=reset_token, new_password="yet another password")
    assert second.status_code == 401
    assert second.json()["code"] == "RESET_TOKEN_INVALID"


async def test_reset_kills_every_existing_session(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """§5.6: "Effect on sessions: Every device is logged out." The refresh token
    issued at registration -- a session that has nothing to do with the reset flow --
    must be just as dead afterward as one that was active during it.
    """
    email = _unique_email()
    registered = await _register(client, email=email)
    user_id = uuid.UUID(registered["user"]["id"])
    old_refresh_token = registered["refresh_token"]

    reset_token = await _get_reset_token(client, email)
    completed = await _reset(client, reset_token=reset_token)
    assert completed.status_code == 204

    dead_refresh = await client.post(_REFRESH, json={"refresh_token": old_refresh_token})
    assert dead_refresh.status_code == 401
    assert dead_refresh.json()["code"] == "TOKEN_INVALID"

    await set_rls_user(db_session, str(user_id))
    result = await db_session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))
    rows = result.scalars().all()
    assert rows
    assert all(row.revoked_at is not None for row in rows)

    # The new password actually works -- this is not just "old session dead", it is
    # "reset genuinely happened."
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _NEW_PASSWORD}
    )
    assert login.status_code == 200

    still_old_password = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": _PASSWORD}
    )
    assert still_old_password.status_code == 401
