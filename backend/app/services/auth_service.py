"""Business logic for §5.2 (register) and §5.3 (login). No HTTP objects here (§3) --
callers pass plain values (ip, user_agent as strings) and get a plain dataclass back;
app/routers/auth.py is what shapes that into TokenPairResponse.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import (
    AccountDisabledError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    TokenExpiredError,
    TokenInvalidError,
    TokenReusedError,
    ValidationError,
)
from app.core.ids import new_id
from app.core.rate_limit import enforce, key_for_user
from app.core.security import (
    create_access_token,
    generate_opaque_token,
    hash_opaque_token,
    hash_password,
    validate_password,
    verify_password,
)
from app.database import set_rls_user
from app.models.user import User
from app.repositories import token_repo, user_repo
from app.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    normalise_email,
    validate_email_format,
)
from app.services import audit_service

_LANGUAGES = {"ar", "en"}

# §5.3: "always run the hash verification against a dummy hash when the user is not
# found, so the response time does not reveal whether the email exists." Computed once
# at import rather than per request, so every no-such-user (or no-password-set) login
# pays the same Argon2 cost a real verify would -- hashing a fresh random value per call
# would still leave a real hasher call in both branches, which is what actually matters
# here; the fixed hash just avoids paying the hashing cost itself on every miss.
_DUMMY_PASSWORD_HASH = hash_password(secrets.token_urlsafe(32))


@dataclass(frozen=True, slots=True)
class IssuedSession:
    user: User
    access_token: str
    expires_in: int
    refresh_token: str
    refresh_expires_in: int
    onboarding_completed: bool


def _validate_language(language: str) -> None:
    if language not in _LANGUAGES:
        raise ValidationError(
            detail="language must be 'ar' or 'en'.",
            errors=[{"field": "language", "code": "NOT_ALLOWED"}],
        )


async def _issue_session(session: AsyncSession, user: User) -> IssuedSession:
    """§5.2/§5.3's identical token-pair shape, and §6.3's opaque-refresh-token contract:
    a brand new family, stored hashed only, with the raw value returned exactly once.
    """
    # §4.7's RLS policy on refresh_tokens checks app.user_id on INSERT too (no WITH CHECK
    # is declared, so the USING clause doubles as one). dependencies.py binds this for
    # already-authenticated requests; register and login are pre-bearer-auth, so this is
    # the first point either flow knows *which* user_id the row about to be inserted
    # belongs to.
    await set_rls_user(session, str(user.id))
    access_token, expires_in = create_access_token(
        user_id=user.id, token_version=user.token_version
    )
    raw_refresh_token = generate_opaque_token()
    await token_repo.create_refresh_token(
        session,
        user.id,
        token_hash=hash_opaque_token(raw_refresh_token),
        family_id=new_id(),
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS),
    )
    return IssuedSession(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_refresh_token,
        refresh_expires_in=settings.REFRESH_TOKEN_TTL_SECONDS,
        # §5.2: "No profile row is created here." No profile_repo exists yet either
        # (T-08 territory) -- every account is mid-onboarding until then, for register
        # and login alike, so this is correct today rather than a placeholder guess.
        onboarding_completed=False,
    )


async def register(
    session: AsyncSession,
    request: RegisterRequest,
    *,
    ip: str | None,
    user_agent: str | None,
) -> IssuedSession:
    email = normalise_email(request.email)
    validate_email_format(email)
    _validate_language(request.language)
    normalised_password = validate_password(request.password, email=email)

    if await user_repo.get_by_email(session, email) is not None:
        # §5.2: the one endpoint where account enumeration is an accepted trade-off.
        raise EmailAlreadyRegisteredError(detail="An account with this email already exists.")

    user = await user_repo.create_user(
        session, email=email, password_hash=hash_password(normalised_password)
    )
    issued = await _issue_session(session, user)
    await audit_service.record_user_registered(
        session, user_id=user.id, ip=ip, user_agent=user_agent
    )
    await session.commit()
    return issued


async def login(
    session: AsyncSession,
    request: LoginRequest,
    *,
    ip: str | None,
    user_agent: str | None,
) -> IssuedSession:
    email = normalise_email(request.email)
    user = await user_repo.get_by_email(session, email)

    if user is None:
        # §5.3: burn the same Argon2 cost a real verify would, so a missing account is
        # not distinguishable from a wrong password by response time.
        verify_password(request.password, _DUMMY_PASSWORD_HASH)
        await audit_service.record_login_failed(
            session, user_id=None, reason="invalid_credentials", ip=ip, user_agent=user_agent
        )
        await session.commit()
        raise InvalidCredentialsError()

    if not user.is_active:
        # §5.3: "is_active = false is the one exception ... because the user needs to
        # know why." Checked ahead of the password so a disabled account is reported
        # consistently regardless of whether the attempted password happens to be
        # correct -- the explicit 403 already discloses account state on its own, so
        # there is nothing left for password-verify timing to protect on this branch.
        await audit_service.record_login_failed(
            session, user_id=user.id, reason="account_disabled", ip=ip, user_agent=user_agent
        )
        await session.commit()
        raise AccountDisabledError(detail="This account has been disabled.")

    stored_hash = user.password_hash
    verification = verify_password(
        request.password, stored_hash if stored_hash is not None else _DUMMY_PASSWORD_HASH
    )
    if not verification.ok or stored_hash is None:
        # stored_hash is None => a social-only account (P1-ADR-01, no password set).
        # Rejected exactly like any other credential failure, never revealed as a
        # distinct cause -- the `or` keeps a dummy-hash false positive from mattering.
        await audit_service.record_login_failed(
            session, user_id=user.id, reason="invalid_credentials", ip=ip, user_agent=user_agent
        )
        await session.commit()
        raise InvalidCredentialsError()

    if verification.upgraded_hash is not None:
        user.password_hash = verification.upgraded_hash  # §6.1 rehash-on-verify

    user.last_login_at = datetime.now(UTC)
    issued = await _issue_session(session, user)
    await audit_service.record_login_succeeded(
        session, user_id=user.id, ip=ip, user_agent=user_agent
    )
    await session.commit()
    return issued


async def refresh(
    session: AsyncSession,
    request: RefreshRequest,
    *,
    ip: str | None,
    user_agent: str | None,
) -> IssuedSession:
    """§5.5's algorithm, in the order the spec numbers it, inside the caller's
    transaction with the token row locked FOR UPDATE.

    There is no bearer token here: the caller presents an opaque refresh token, and
    which user it belongs to is unknown until a row is read, so app.user_id cannot be
    bound before that first lookup runs. Resolved in two phases (see
    token_repo.peek_user_id_by_hash's docstring for why a single locked SELECT cannot
    do this alone): an unscoped peek to discover the owning user, then app.user_id
    bound to that discovery -- the same technique _issue_session uses once a user row
    is in hand, which is Appendix A.5 item 9's pattern, extended here to a lookup that
    precedes the write rather than only a write that follows a fresh user row -- and
    only then the authoritative, locked read the rest of this function acts on.
    """
    token_hash = hash_opaque_token(request.refresh_token)
    peeked_user_id = await token_repo.peek_user_id_by_hash(session, token_hash)
    if peeked_user_id is None:
        # No user is knowable from a token that matches nothing, so there is no bucket
        # to charge the §6.4 60/hour limit against -- see the note below, where the
        # limit is enforced only once a row (and therefore a user) is in hand.
        raise TokenInvalidError(detail="This refresh token is unknown.")

    # The user is now known. Bind RLS before the locked read and any write below --
    # the locked read, consume, revoke-family, and insert-successor are all governed by
    # refresh_tokens' owner policy.
    await set_rls_user(session, str(peeked_user_id))

    row = await token_repo.get_for_update_by_hash(session, peeked_user_id, token_hash)
    if row is None:
        # Vanishingly rare: the row was deleted between the peek above and this locked
        # read (e.g. its user's account was hard-deleted, cascading the row away).
        # Same response as "unknown" -- there is nothing more to distinguish safely.
        await session.commit()
        raise TokenInvalidError(detail="This refresh token is unknown.")

    # §6.4: 60/hour, keyed on user. Charged here, against every attempt on a *known*
    # token -- valid, expired, revoked, or reused alike -- since all of those resolve to
    # a real user's bucket; only an unmatched token (above) cannot be charged to anyone.
    enforce(scope="auth.refresh", key=key_for_user(row.user_id), limit=60, window_seconds=3600)

    if row.consumed_at is not None:
        # §5.5 step 2: reuse. The legitimate holder's own next-in-chain token dies too --
        # that is the point, not a side effect: it forces a fresh login rather than
        # trusting a chain that a thief has also seen.
        await token_repo.revoke_family(session, row.user_id, row.family_id)
        await audit_service.record_token_reuse_detected(
            session, user_id=row.user_id, family_id=row.family_id, ip=ip, user_agent=user_agent
        )
        await audit_service.record_token_family_revoked(
            session,
            user_id=row.user_id,
            family_id=row.family_id,
            reason="reuse_detected",
            ip=ip,
            user_agent=user_agent,
        )
        await session.commit()
        raise TokenReusedError(detail="This refresh token was already used.")

    if row.revoked_at is not None:
        await session.commit()
        raise TokenInvalidError(detail="This refresh token has been revoked.")

    if row.expires_at <= datetime.now(UTC):
        await session.commit()
        raise TokenExpiredError(detail="This refresh token has expired.")

    user = await user_repo.get_active_user_by_id(session, row.user_id)
    if user is None or not user.is_active:
        # §5.5 step 4: "User missing, soft-deleted, or inactive -> 401 TOKEN_INVALID."
        # Deliberately TOKEN_INVALID rather than ACCOUNT_DISABLED -- unlike
        # get_current_user's bearer path, refresh is authenticated by the token itself,
        # and the spec states this divergence explicitly (see dependencies.py).
        await session.commit()
        raise TokenInvalidError(detail="This refresh token does not identify a live account.")

    await token_repo.mark_consumed(session, row.user_id, row.id)
    access_token, expires_in = create_access_token(
        user_id=user.id, token_version=user.token_version
    )
    raw_refresh_token = generate_opaque_token()
    await token_repo.create_refresh_token(
        session,
        user.id,
        token_hash=hash_opaque_token(raw_refresh_token),
        family_id=row.family_id,
        parent_id=row.id,
        expires_at=datetime.now(UTC) + timedelta(seconds=settings.REFRESH_TOKEN_TTL_SECONDS),
    )
    user.last_login_at = datetime.now(UTC)
    await audit_service.record_token_refreshed(
        session, user_id=user.id, ip=ip, user_agent=user_agent
    )
    await session.commit()
    return IssuedSession(
        user=user,
        access_token=access_token,
        expires_in=expires_in,
        refresh_token=raw_refresh_token,
        refresh_expires_in=settings.REFRESH_TOKEN_TTL_SECONDS,
        onboarding_completed=False,
    )


async def logout(
    session: AsyncSession,
    user: User,
    request: LogoutRequest,
    *,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """§5's /auth/logout: revoke the family the presented refresh token belongs to.

    The caller is already bearer-authenticated -- get_current_user has bound
    app.user_id to `user.id` before this runs -- so, unlike refresh()'s pre-auth path,
    there is no peek step here: get_for_update_by_hash is called directly, scoped to
    `user.id`. Its WHERE clause filters on that user_id as well as the hash, so a
    refresh token belonging to a *different* user comes back as None -- identical to an
    unknown token -- rather than ever being read and compared after the fact.
    """
    token_hash = hash_opaque_token(request.refresh_token)
    row = await token_repo.get_for_update_by_hash(session, user.id, token_hash)
    if row is None:
        raise TokenInvalidError(detail="This refresh token is unknown.")

    await token_repo.revoke_family(session, user.id, row.family_id)
    await audit_service.record_token_family_revoked(
        session,
        user_id=user.id,
        family_id=row.family_id,
        reason="logout",
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()


async def logout_all(
    session: AsyncSession,
    user: User,
    *,
    ip: str | None,
    user_agent: str | None,
) -> None:
    """§5's /auth/logout-all: every family dies, and token_version bumps so any access
    token already issued (P1-ADR-02) stops verifying immediately, not just at its own
    15-minute expiry.
    """
    await token_repo.revoke_all_for_user(session, user.id)
    user.token_version += 1
    await audit_service.record_token_family_revoked(
        session, user_id=user.id, family_id=None, reason="logout_all", ip=ip, user_agent=user_agent
    )
    await session.commit()
