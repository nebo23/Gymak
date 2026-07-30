"""Business logic for §5.4 POST /auth/social/{provider} (P1-FR-003, §12 T-06). Google
only in Phase 1 -- decision 13.1.2 (A-15) -- Facebook stays out until Phase 2 picks this
file back up. No HTTP objects here (§3): the router passes plain values and gets a plain
dataclass back, the same convention auth_service uses for register/login/refresh.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import (
    AccountDisabledError,
    IdentityAlreadyLinkedError,
    ProviderNotSupportedError,
    SocialTokenInvalidError,
)
from app.integrations import firebase
from app.repositories import audit_repo, identity_repo, user_repo
from app.schemas.auth import normalise_email
from app.services.auth_service import IssuedSession, _issue_session

# §5.4 / T-06: "Structure the restriction as a value in one place, not a branch, so
# Phase 2 adds a provider without a rewrite." The key is the {provider} path segment;
# the value is the exact string Firebase puts in the firebase.sign_in_provider claim for
# that provider (Google's is "google.com", not "google") -- Phase 2 adding Facebook is
# `"facebook": "facebook.com"` here and nowhere else in this module.
SUPPORTED_PROVIDERS: Final[dict[str, str]] = {
    "google": "google.com",
}


@dataclass(frozen=True, slots=True)
class SocialSignInResult:
    issued: IssuedSession
    is_new_user: bool


@dataclass(frozen=True, slots=True)
class _ProviderClaims:
    """Only what §5.4 needs, and only from the verified token -- "Do not trust the
    client's claim about who it is ... The provider, the uid, and the email all come
    from the verified token -- never from the request body."
    """

    provider_uid: str
    firebase_uid: str
    email: str | None
    email_verified: bool


def _placeholder_email(provider: str, provider_uid: str) -> str:
    """§5.4 step 5: "If the provider returned no email at all, generate a placeholder of
    the form fb_{provider_uid}@social.gymak.local." The spec's own example is
    Facebook-shaped because it was written before decision 13.1.2 deferred Facebook to
    Phase 2; the scheme is provider-generic, so building and testing it now (Google
    only) is exactly what the task asks for -- "it is what Phase 2's Facebook work will
    land on."
    """
    return f"{provider}_{provider_uid}@social.gymak.local"


def _extract_claims(
    raw_claims: dict[str, Any], *, expected_sign_in_provider: str
) -> _ProviderClaims:
    """§5.4 step 2: assert firebase.sign_in_provider matches the path provider before
    trusting anything else in the token. "Without this check, a Google token would be
    accepted at the Facebook endpoint" -- checked here as the very first thing this
    function does, ahead of reading uid or email.
    """
    asserted_provider = raw_claims.get("firebase", {}).get("sign_in_provider")
    if asserted_provider != expected_sign_in_provider:
        raise SocialTokenInvalidError(
            detail="This token was not issued for the requested provider."
        )

    firebase_uid = raw_claims["uid"]
    # firebase.identities[<provider>] holds the provider's own subject id -- §4.2's
    # "provider_uid ... the provider's stable subject identifier" -- which is distinct
    # from Firebase's own uid (§4.2's "firebase_uid ... kept for support and debugging").
    identities = raw_claims.get("firebase", {}).get("identities", {})
    provider_subjects = identities.get(expected_sign_in_provider) or []
    provider_uid = provider_subjects[0] if provider_subjects else firebase_uid

    return _ProviderClaims(
        provider_uid=provider_uid,
        firebase_uid=firebase_uid,
        email=raw_claims.get("email"),
        email_verified=bool(raw_claims.get("email_verified", False)),
    )


async def _resolve_new_account_email(
    session: AsyncSession, *, provider: str, claims: _ProviderClaims
) -> tuple[str, bool]:
    """§5.4 step 5, once no identity and no link applies: decide the new account's own
    email and email_verified.

    `claims.email_verified` being true here already implies the address is unclaimed --
    `sign_in`'s own lookup for the link check (§5.4 step 4) only runs when the email is
    verified, and only reaches this function when that lookup came back empty -- so a
    second query in that branch would be redundant, not merely wasteful.

    An unverified email is never trusted with anything, including this: if it happens to
    collide with a live user's address -- the takeover attempt the "unverified email
    does NOT link" control test exercises -- using it here would violate users' own
    partial unique index (uq_users_email_live) and abort the request with a raw
    IntegrityError instead of creating the separate account §5.4 requires. So only a
    verified email is used unconditionally; an unverified one is checked for a collision
    first, and the placeholder scheme covers every case that is not a confirmed-free
    address.
    """
    if not claims.email:
        return _placeholder_email(provider, claims.provider_uid), False

    candidate = normalise_email(claims.email)
    if claims.email_verified:
        return candidate, True
    if await user_repo.get_by_email(session, candidate) is None:
        return candidate, False
    return _placeholder_email(provider, claims.provider_uid), False


async def _create_identity_or_conflict(
    session: AsyncSession, user_id: uuid.UUID, *, provider: str, claims: _ProviderClaims
) -> None:
    """§4.2's UNIQUE(provider, provider_uid) is the actual barrier against the same
    provider identity attaching to two Gymak users; the lookup in `sign_in` and this
    insert are not atomic, so a concurrent sign-in for the same identity can still race
    between them. This turns that constraint violation into §7.3's 409
    IDENTITY_ALREADY_LINKED instead of a raw 500, and rolls back so the session is usable
    again for whatever the caller (here: nothing, the request ends) does next.
    """
    try:
        await identity_repo.create_identity(
            session,
            user_id,
            provider=provider,
            provider_uid=claims.provider_uid,
            firebase_uid=claims.firebase_uid,
            email_at_provider=claims.email,
        )
    except IntegrityError as exc:
        await session.rollback()
        raise IdentityAlreadyLinkedError(
            detail="This social identity is already linked to a different Gymak account."
        ) from exc


async def sign_in(
    session: AsyncSession,
    provider: str,
    id_token: str,
    *,
    ip: str | None,
    user_agent: str | None,
) -> SocialSignInResult:
    """§5.4's six steps, in exactly that order."""
    expected_sign_in_provider = SUPPORTED_PROVIDERS.get(provider)
    if expected_sign_in_provider is None:
        raise ProviderNotSupportedError(detail=f"'{provider}' is not a supported sign-in provider.")

    # Step 1: verify with the admin SDK, never decode manually. "Any failure ->
    # 401 SOCIAL_TOKEN_INVALID" is deliberately broad here -- this call is a security
    # boundary, not a place to distinguish causes for the caller.
    try:
        raw_claims = firebase.verify_id_token(id_token)
    except Exception as exc:
        raise SocialTokenInvalidError(
            detail="The social sign-in token could not be verified."
        ) from exc

    # Step 2 happens inside _extract_claims.
    claims = _extract_claims(raw_claims, expected_sign_in_provider=expected_sign_in_provider)

    # Step 3: identity already known -> that is the user; nothing else about the token
    # (email, its verified state) is even consulted on this path.
    identity = await identity_repo.get_by_provider_uid(session, provider, claims.provider_uid)
    if identity is not None:
        user = await user_repo.get_active_user_by_id(session, identity.user_id)
        if user is None:
            # §4.2's ON DELETE CASCADE means this is normally impossible while the user
            # row exists; treated like §5.5 step 4's "no live account" -> TOKEN_INVALID
            # reasoning rather than as a distinct case.
            raise SocialTokenInvalidError(
                detail="This social identity does not identify an active account."
            )
        if not user.is_active:
            raise AccountDisabledError(detail="This account has been disabled.")
        is_new_user = False
    else:
        # Step 4: link only on a VERIFIED matching email -- an unverified assertion must
        # never grant access to an existing account.
        existing_user = None
        if claims.email and claims.email_verified:
            existing_user = await user_repo.get_by_email(session, normalise_email(claims.email))

        if existing_user is not None:
            await _create_identity_or_conflict(
                session, existing_user.id, provider=provider, claims=claims
            )
            await audit_repo.record(
                session,
                action="user.social_linked",
                actor_user_id=existing_user.id,
                entity="user",
                entity_id=existing_user.id,
                metadata={"provider": provider},
                ip=ip,
                user_agent=user_agent,
            )
            user = existing_user
            is_new_user = False
        else:
            # Step 5: no identity, no link -> a new user. password_hash NULL;
            # email_verified follows the provider claim, with the placeholder scheme
            # covering both "no email" and "unverified email that cannot safely be used"
            # (see _resolve_new_account_email's docstring).
            new_email, new_email_verified = await _resolve_new_account_email(
                session, provider=provider, claims=claims
            )
            user = await user_repo.create_user(
                session,
                email=new_email,
                password_hash=None,
                email_verified=new_email_verified,
            )
            await _create_identity_or_conflict(session, user.id, provider=provider, claims=claims)
            is_new_user = True

    # Step 6: issue the Gymak token pair. Reuses auth_service._issue_session rather than
    # re-implementing the pre-auth app.user_id bind (Appendix A.5 item 9) a third time --
    # see this task's report for the trade-off.
    issued = await _issue_session(session, user)
    await session.commit()
    return SocialSignInResult(issued=issued, is_new_user=is_new_user)
