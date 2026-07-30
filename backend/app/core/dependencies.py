"""FastAPI dependencies: get_db, get_current_user, require_active (§3).

Unlike `security.py`, this module does touch the database -- that is its job. It is the seam
where a verified token becomes a `User` row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AccountDisabledError, TokenInvalidError, TokenMissingError
from app.core.security import assert_token_version_current, verify_access_token
from app.database import get_db_session, set_rls_user
from app.models.user import User
from app.repositories import user_repo

# get_db is the name §3 gives this dependency; the engine and session factory stay in
# database.py. An alias, not a wrapper, so there is exactly one session-producing generator
# in the codebase -- a second one that looked equivalent would be a place for the two to
# drift apart.
get_db = get_db_session

# auto_error=False so a missing or malformed Authorization header reaches us instead of
# becoming FastAPI's own 403 with a plain-JSON body. §7.3 requires TOKEN_MISSING (401) inside
# the problem+json envelope, and HTTPBearer's default would produce neither.
_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    """Parse the bearer token, verify it, load the user, and bind RLS -- fail-closed.

    Order matters, and this order is chosen so nothing that costs a database round trip runs
    before the signature is known good:

    1.  No credentials                 -> 401 TOKEN_MISSING
    2.  Signature / aud / exp / claims -> 401 TOKEN_EXPIRED or TOKEN_INVALID (security.py)
    3.  User unknown or soft-deleted   -> 401 TOKEN_INVALID (never 404: the token is the
                                          thing being rejected, and confirming that a user
                                          id does not exist tells a prober something)
    4.  Stale `tv`                     -> 401 TOKEN_INVALID (P1-ADR-02 revocation)
    5.  is_active = false              -> 403 ACCOUNT_DISABLED (§7.3; the user needs to
                                          know why, per §5.3's reasoning)
    6.  Bind app.user_id for RLS       -> the §4.7 second barrier, active for the rest of
                                          this transaction

    Note a deliberate divergence: §5.5 step 4 makes an inactive user on **/auth/refresh**
    return 401 TOKEN_INVALID rather than 403. That endpoint states its own rule and does not
    use this dependency (refresh is authenticated by the refresh token, not a bearer), so
    T-04 implements it separately. Both readings are correct in their own place.
    """
    if credentials is None or not credentials.credentials.strip():
        raise TokenMissingError(detail="An Authorization: Bearer <access_token> header is required.")

    claims = verify_access_token(credentials.credentials)

    user = await user_repo.get_active_user_by_id(session, claims.sub)
    if user is None:
        raise TokenInvalidError(detail="This token does not identify a live account.")

    assert_token_version_current(claims, user.token_version)

    if not user.is_active:
        raise AccountDisabledError(detail="This account has been disabled.")

    # §4.7's second barrier. Bound here rather than in each repository because it is
    # transaction-scoped (see set_rls_user's docstring) and this is the first statement after
    # the transaction that will run the user-scoped queries has begun.
    await set_rls_user(session, str(user.id))

    return user


async def require_active(user: Annotated[User, Depends(get_current_user)]) -> User:
    """The §3 name for "authenticated and enabled", for use at the route.

    The is_active check lives in `get_current_user`, not here, on purpose: a dependency that
    is only safe when composed with a second one is a dependency that will eventually be used
    alone. `get_current_user` is therefore already fail-closed, and this exists as the
    self-documenting form at the route signature and as the seam for any future condition on
    "active" that should not gate every authenticated call.
    """
    return user
