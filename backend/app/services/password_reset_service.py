"""Business logic for spec §5.6's three-call password reset (P1-ADR-04, P1-ADR-07,
P1-ADR-05, §12 T-07). No HTTP objects here (§3) -- notably no `BackgroundTasks`: the
router owns scheduling the email, this module only decides *whether* one is needed and
hands back the plain values (`send_reset_code_email` / `send_password_changed_email`
below take no session and no framework object, so the router can pass either straight
to `BackgroundTasks.add_task`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.errors import (
    ResetCodeAttemptsExceededError,
    ResetCodeExpiredError,
    ResetCodeInvalidError,
    ResetTokenInvalidError,
)
from app.core.security import (
    generate_opaque_token,
    generate_reset_code,
    hash_opaque_token,
    hash_password,
    hash_reset_code,
    reset_code_matches,
    validate_password,
)
from app.database import set_rls_user
from app.integrations.email.base import EmailMessage, get_email_sender, render_template
from app.repositories import audit_repo, reset_repo, token_repo, user_repo
from app.schemas.auth import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    VerifyCodeRequest,
    VerifyCodeResponse,
    normalise_email,
)

_RESET_CODE_ATTEMPT_LIMIT = 5

_SUBJECTS = {
    "reset_code": {
        "ar": "رمز إعادة تعيين كلمة المرور - جيماك",
        "en": "Your Gymak password reset code",
    },
    "password_changed": {
        "ar": "تم تغيير كلمة المرور الخاصة بك - جيماك",
        "en": "Your Gymak password was changed",
    },
}


class ResetCodeAttemptsExceeded(ResetCodeAttemptsExceededError):
    """RESET_CODE_ATTEMPTS_EXCEEDED (§7.3) carrying `Retry-After` (§6.4: "every 429
    carries a Retry-After header"). Subclassed here rather than in `errors.py`, which
    is not in this task's file list -- the same pattern `RateLimited` uses over
    `RateLimitExceededError` in `core/rate_limit.py`, for the same reason: the
    exception handler reads `retry_after_seconds` via `getattr`, so any `AppError`
    subclass gets the header for free without `errors.py` needing to change.
    """

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(detail="Too many incorrect attempts. This code is now burned.")


@dataclass(frozen=True, slots=True)
class PendingResetCodeEmail:
    email: str
    code: str
    language: str


@dataclass(frozen=True, slots=True)
class PendingPasswordChangedEmail:
    email: str
    language: str


def _seconds_until(expires_at: datetime) -> int:
    """§6.4's Retry-After for a burned code: how long until it would have expired
    anyway, since that is when a fresh `forgot` call becomes the next legitimate step.
    Floored at 1 -- a Retry-After of 0 or negative is meaningless to a client.
    """
    return max(1, int((expires_at - datetime.now(UTC)).total_seconds()))


async def send_reset_code_email(to_email: str, code: str, language: str) -> None:
    """§5.6 / P1-ADR-05: the code email. Framework-free by design -- see the module
    docstring -- so the router can hand this straight to `BackgroundTasks.add_task`
    without this module ever importing Starlette.
    """
    ttl_minutes = str(settings.RESET_CODE_TTL_SECONDS // 60)
    html = render_template("reset_code", language, CODE=code, TTL_MINUTES=ttl_minutes)
    message = EmailMessage(to=to_email, subject=_SUBJECTS["reset_code"][language], html_body=html)
    await get_email_sender().send(message)


async def send_password_changed_email(to_email: str, language: str) -> None:
    """§5.6 reset: "sends a 'your password was changed' notification email." """
    html = render_template("password_changed", language)
    message = EmailMessage(
        to=to_email, subject=_SUBJECTS["password_changed"][language], html_body=html
    )
    await get_email_sender().send(message)


async def forgot(
    session: AsyncSession,
    request: ForgotPasswordRequest,
    *,
    ip: str | None,
) -> PendingResetCodeEmail | None:
    """§5.6 call 1. The router always answers 202 with the same body regardless of
    what this returns (§5.6: "identical body and latency envelope whether or not the
    account exists") -- a None return means "send nothing", not "something failed."

    Rate limiting is enforced in the router, before this function is ever called,
    keyed on the *submitted* address -- see auth.py's forgot_password_route. That is
    what satisfies §5.6's "count the attempt against the submitted address BEFORE
    looking the user up": the limiter never calls into this module at all.
    """
    email = normalise_email(request.email)
    user = await user_repo.get_by_email(session, email)

    if user is None or user.password_hash is None:
        # Unknown address, or a social-only account (§5.6: "Still returns 202 and
        # still sends nothing. Do not reveal that the account has no password.")
        # No RLS bind needed: nothing is written on this path.
        return None

    # password_reset_codes carries no RLS (§4.7: read/written pre-auth, like `users`),
    # so -- unlike `reset` below -- no set_rls_user call belongs on this path; A.5
    # item 9 is specifically about the FORCE-RLS `refresh_tokens` table, which forgot
    # never touches.
    await reset_repo.consume_previous_unconsumed(session, user.id)

    code = generate_reset_code()
    expires_at = datetime.now(UTC) + timedelta(seconds=settings.RESET_CODE_TTL_SECONDS)
    await reset_repo.create_code(
        session,
        user.id,
        code_hash=hash_reset_code(user.id, code),
        expires_at=expires_at,
        requested_ip=ip,
    )
    await audit_repo.record(
        session,
        action="password.reset_requested",
        actor_user_id=user.id,
        entity="user",
        entity_id=user.id,
        ip=ip,
        user_agent=None,
    )
    await session.commit()

    language = await reset_repo.get_language_for_user(session, user.id)
    return PendingResetCodeEmail(email=user.email, code=code, language=language)


async def verify_code(session: AsyncSession, request: VerifyCodeRequest) -> VerifyCodeResponse:
    """§5.6 call 2. Every failure -- unknown email, social-only account, wrong code,
    unknown code -- collapses to the same 422 RESET_CODE_INVALID (§7.3), so none of
    them is distinguishable by response shape.
    """
    email = normalise_email(request.email)
    user = await user_repo.get_by_email(session, email)
    if user is None or user.password_hash is None:
        raise ResetCodeInvalidError(detail="The code is incorrect or has expired.")

    row = await reset_repo.get_active_code_for_update(session, user.id)
    if row is not None:
        if row.attempt_count >= _RESET_CODE_ATTEMPT_LIMIT:
            await session.commit()
            raise ResetCodeAttemptsExceeded(retry_after_seconds=_seconds_until(row.expires_at))

        if reset_code_matches(user.id, request.code, row.code_hash):
            raw_token = generate_opaque_token()
            token_expires_at = datetime.now(UTC) + timedelta(
                seconds=settings.RESET_TOKEN_TTL_SECONDS
            )
            redeemed = await reset_repo.redeem_code_for_reset_token(
                session,
                row.id,
                token_hash=hash_opaque_token(raw_token),
                token_expires_at=token_expires_at,
            )
            await session.commit()
            if not redeemed:
                # §5.6: "two simultaneous redemptions must leave exactly one winner."
                # A concurrent verify already won this exact redemption.
                raise ResetCodeInvalidError(detail="The code is incorrect or has expired.")
            return VerifyCodeResponse(
                reset_token=raw_token, expires_in=settings.RESET_TOKEN_TTL_SECONDS
            )

        await reset_repo.increment_attempt(session, row.id)
        await session.commit()
        raise ResetCodeInvalidError(detail="The code is incorrect or has expired.")

    # §5.6: "attempt_count increments on every failed verify, including expired
    # ones" -- the primary lookup above already excluded expired rows via its own
    # WHERE, so a row found here (looser WHERE, no expires_at condition) must be one.
    expired_row = await reset_repo.get_unconsumed_code_for_update(session, user.id)
    if expired_row is not None:
        await reset_repo.increment_attempt(session, expired_row.id)
        await session.commit()
        raise ResetCodeExpiredError(detail="This code has expired.")

    raise ResetCodeInvalidError(detail="The code is incorrect or has expired.")


async def reset(
    session: AsyncSession,
    request: ResetPasswordRequest,
    *,
    ip: str | None,
    user_agent: str | None,
) -> PendingPasswordChangedEmail:
    """§5.6 call 3. Sets the new hash, bumps `token_version`, revokes every refresh
    family, and audits `password.reset_completed` -- `password.reset_requested` is
    audited earlier, in `forgot`, when the code that ultimately led here was issued.
    """
    token_hash = hash_opaque_token(request.reset_token)
    user_id = await reset_repo.redeem_reset_token(session, token_hash)
    if user_id is None:
        # §7.3: RESET_TOKEN_INVALID covers unknown, spent, and expired alike -- the
        # single DELETE ... WHERE ... RETURNING in redeem_reset_token already
        # collapses all three into "zero rows", so there is nothing further to
        # distinguish here.
        raise ResetTokenInvalidError()

    # A.5 item 9: the caller has no bearer (a reset token, not an access token,
    # authenticates this request), so app.user_id must be bound by hand before the
    # refresh_tokens write below, exactly as _issue_session does pre-auth.
    await set_rls_user(session, str(user_id))

    user = await user_repo.get_active_user_by_id(session, user_id)
    if user is None or not user.is_active:
        # Vanishingly rare: the account was soft-deleted or disabled in the window
        # between verify-code and reset. Same generic response as any other invalid
        # token -- the token is what is being rejected, not the account state
        # (mirrors get_current_user's reasoning for TOKEN_INVALID over a distinct
        # code here).
        await session.commit()
        raise ResetTokenInvalidError()

    normalised_password = validate_password(request.new_password, email=user.email)

    # A.5 item 14: this only ever *sets* password_hash on a row that already exists;
    # it can never null one out, so it cannot produce the credential-less row that
    # item 14 warns chk_credential_present's removal leaves undefended against.
    user.password_hash = hash_password(normalised_password)
    user.token_version += 1
    await token_repo.revoke_all_for_user(session, user.id)
    await audit_repo.record(
        session,
        action="password.reset_completed",
        actor_user_id=user.id,
        entity="user",
        entity_id=user.id,
        ip=ip,
        user_agent=user_agent,
    )
    await session.commit()

    language = await reset_repo.get_language_for_user(session, user.id)
    return PendingPasswordChangedEmail(email=user.email, language=language)
