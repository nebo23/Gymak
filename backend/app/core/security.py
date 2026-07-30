"""Security primitives: spec §6.1 (Argon2id), §6.2 (password policy), §6.3 (tokens),
and P1-ADR-07 (peppered reset codes).

This module deliberately imports **only** `app.config` -- never `app.database`, never a
model, never anything that touches HTTP. Two reasons:

1.  `app.database` runs a live privilege check at import (`database.py`'s
    `_assert_connection_is_not_privileged`), so importing it here would make every
    cryptographic primitive, and every test of one, require a running PostgreSQL.
2.  These are pure functions over bytes and strings. Anything that needs a user row
    belongs in `dependencies.py` or a repository, which is where it lives.

`RESET_CODE_PEPPER` is required with no default, so `from app.config import settings`
below makes a deployment missing the pepper fail at **import**, before a single request
is served -- the fail-fast that P1-ADR-07's consequence row requires.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import jwt
from argon2 import PasswordHasher, Type
from argon2.exceptions import (
    InvalidHashError,
    VerificationError,
    VerifyMismatchError,
)

from app.config import settings
from app.core.errors import TokenExpiredError, TokenInvalidError, ValidationError

# =========================================================================================
# §6.1 · Argon2id password hashing
# =========================================================================================

# Parameters come from config, which forces the reduced cost ONLY under ENV=test (§6.1's
# "Test override" row). Bound once at import: PasswordHasher is stateless and thread-safe,
# and re-deriving it per call would re-read settings on the login hot path for no gain.
_hasher = PasswordHasher(
    time_cost=settings.ARGON2_TIME_COST,
    memory_cost=settings.ARGON2_MEMORY_KIB,
    parallelism=settings.ARGON2_PARALLELISM,
    hash_len=32,
    salt_len=16,
    type=Type.ID,  # Argon2*id*, explicitly. §6.1: not Argon2i, not Argon2d.
)


def argon2_parameters() -> dict[str, int]:
    """The cost parameters actually in force. Exposed so a test can assert the ENV=test
    override applies under test and nowhere else, without reaching into a private."""
    return {
        "memory_cost": _hasher.memory_cost,
        "time_cost": _hasher.time_cost,
        "parallelism": _hasher.parallelism,
    }


@dataclass(frozen=True, slots=True)
class PasswordVerification:
    """The result of a verify, plus the rehash-on-verify upgrade §6.1 requires.

    `upgraded_hash` is non-None only when the password was correct AND the stored hash was
    produced at parameters that no longer match the current configuration. The caller
    persists it; this module does not know about a database.
    """

    ok: bool
    upgraded_hash: str | None = None


def normalise_password(password: str) -> str:
    """§6.2: NFKC before hashing, so the same password typed on different devices produces
    the same bytes. Arabic presentation forms and full-width Latin are the cases that
    actually bite -- U+FEFB (the LAM-ALEF ligature an Arabic keyboard may emit) normalises
    to the two-codepoint U+0644 U+0627, and without this a user could set a password on one
    keyboard and be unable to log in from another.

    Whitespace is NOT stripped: leading or trailing spaces are part of a password the user
    chose, and silently trimming them changes the credential.
    """
    return unicodedata.normalize("NFKC", password)


def hash_password(password: str) -> str:
    return _hasher.hash(normalise_password(password))


def verify_password(password: str, password_hash: str) -> PasswordVerification:
    """Verify, and carry out the §6.1 rehash-on-verify check in the same step.

    Returns a result object instead of raising: at the call site (§5.3 login) every failure
    cause collapses into one generic INVALID_CREDENTIALS, so distinguishing "wrong password"
    from "stored hash is corrupt" by exception type would only invite a caller to leak that
    difference into a response.
    """
    normalised = normalise_password(password)
    try:
        _hasher.verify(password_hash, normalised)
    except (VerifyMismatchError, InvalidHashError, VerificationError):
        return PasswordVerification(ok=False)

    if _hasher.check_needs_rehash(password_hash):
        return PasswordVerification(ok=True, upgraded_hash=_hasher.hash(normalised))
    return PasswordVerification(ok=True)


def password_needs_rehash(password_hash: str) -> bool:
    """Whether a stored hash predates the current cost parameters. Exposed separately
    because §6.1's upgrade is conditional on a *successful* verify, and a caller may want
    to ask the question without one."""
    return bool(_hasher.check_needs_rehash(password_hash))


# =========================================================================================
# §6.2 / §7.1 · Password policy
# =========================================================================================

PASSWORD_MIN_LENGTH: Final = 8
PASSWORD_MAX_LENGTH: Final = 128

# §6.2: "Reject a small denylist of obvious values (the top ~1000 common passwords, plus
# the local part of the user's own email)."
#
# Inline rather than a data file: no dependency in Appendix A.2 ships a wordlist, and T-03's
# file list has no room for a data file. This set is curated, not the real top 1000 -- see
# the report accompanying this task. Swapping in a vetted list (SecLists / the Pwned
# Passwords top 1k) is a one-constant change and does not alter any signature here.
#
# Membership is tested case-insensitively against the NFKC-normalised password, so every
# entry is stored lowercase.
_COMMON_PASSWORDS: Final[frozenset[str]] = frozenset(
    """
    123456 password 123456789 12345678 12345 1234567 1234567890 qwerty abc123 111111
    123123 1234 iloveyou 1q2w3e4r 000000 qwerty123 zaq12wsx dragon sunshine princess
    letmein 654321 monkey 27653 1qaz2wsx 123321 qwertyuiop superman asdfghjkl 1q2w3e
    football welcome jesus ninja mustang password1 password123 passw0rd p@ssword
    p@ssw0rd admin administrator root toor guest test test123 user username default
    changeme secret letmein123 trustno1 whatever qazwsx qwe123 asdf asdfgh zxcvbnm
    zxcvbn 1qazxsw2 q1w2e3r4 aa123456 abcd1234 abc12345 a1b2c3d4 123qwe 112233
    121212 131313 101010 987654321 11111111 22222222 00000000 55555 666666 777777
    888888 999999 123abc 1q2w3e4r5t michael jennifer jordan hunter harley ranger
    shadow master killer batman thomas robert daniel matthew joshua andrew charlie
    tigger charlie1 hannah maggie ashley amanda samantha jessica sarah nicole
    chelsea taylor summer flower angel baby love lovely loveme forever family
    friend friends freedom soccer basketball baseball hockey golfer boomer starwars
    computer internet samsung google gmail yahoo facebook twitter instagram youtube
    snoopy scooby cookie chocolate pepper cheese banana orange apple purple yellow
    silver gold diamond bailey buster jackson pookie snickers midnight ginger
    peanut smokey oliver soleil pussy fuckyou fuckme asshole bitch dick pussy1
    football1 iloveyou1 princess1 blessed jesus1 heaven angels prayer amen
    ahmed mohamed mohammed muhammad ali omar hassan hussein khaled mahmoud
    fatima aisha maryam zainab yousef ibrahim abdullah abdulrahman
    kuwait egypt saudi jordan1 dubai riyadh cairo amman
    gymak gymak123 fitness fitness1 workout gym gym123 muscle protein trainer
    qwertz azerty 147258369 159753 741852963 963852741 1122334455
    iloveu ilovegod loveyou lover lovers kisses kiss cutie sweetie
    hello hello123 hi hey welcome1 welcome123 access access14 login logon
    system server database backup temp temp123 demo demo123 sample example
    dummy nothing nopass none null empty blank space asdfasdf qwerqwer
    trustme believe hopeless nevermore whatever1 anything something everything
    michelle stephanie christina elizabeth alexander benjamin nicholas
    liverpool arsenal chelsea1 barcelona realmadrid madrid manutd juventus
    metallica nirvana slipknot eminem rihanna beyonce justin bieber
    pokemon naruto onepiece minecraft fortnite roblox playstation xbox nintendo
    dragonball spiderman ironman avengers thanos joker gandalf frodo legolas
    """.split()
)


def is_common_password(password: str) -> bool:
    return normalise_password(password).casefold() in _COMMON_PASSWORDS


def email_local_part(email: str) -> str:
    """The part before the last '@'. rpartition, not split, because a quoted local part may
    legally contain '@' and the domain never does."""
    local, separator, _domain = email.rpartition("@")
    return local if separator else email


def validate_password(password: str, *, email: str | None = None) -> str:
    """§6.2 / §7.1. Returns the NFKC-normalised password ready for hashing, or raises
    VALIDATION_ERROR with the field code the client switches on.

    Length is measured **after** normalisation, deliberately: normalisation is what decides
    the bytes Argon2 actually consumes, so measuring before it would let a 130-character
    input that normalises to 126 be rejected, and -- worse -- let a 7-character input that
    normalises to 8 be accepted by the hasher but rejected here, inconsistently between
    registration and any later re-validation.

    `email` is optional because §6.2's email rule only applies where an address is in hand;
    a password-change flow that has the user already may pass it, a policy check in
    isolation need not.
    """
    normalised = normalise_password(password)

    if len(normalised) < PASSWORD_MIN_LENGTH:
        raise ValidationError(
            detail=f"Password must be at least {PASSWORD_MIN_LENGTH} characters.",
            errors=[{"field": "password", "code": "TOO_SHORT"}],
        )
    if len(normalised) > PASSWORD_MAX_LENGTH:
        raise ValidationError(
            detail=f"Password must be at most {PASSWORD_MAX_LENGTH} characters.",
            errors=[{"field": "password", "code": "TOO_LONG"}],
        )

    folded = normalised.casefold()
    if folded in _COMMON_PASSWORDS:
        raise ValidationError(
            detail="This password is too common. Choose something less predictable.",
            errors=[{"field": "password", "code": "TOO_COMMON"}],
        )
    if email is not None and folded == email_local_part(email).strip().casefold():
        raise ValidationError(
            detail="Your password must not be the first part of your email address.",
            errors=[{"field": "password", "code": "TOO_COMMON"}],
        )

    return normalised


# =========================================================================================
# §6.3 · Access tokens (JWT, Ed25519)
# =========================================================================================

# P1-ADR-02 / §6.3: EdDSA over Ed25519, pinned. Never read from the token's own header --
# see verify_access_token.
ACCESS_TOKEN_ALGORITHM: Final = "EdDSA"

# P1-ADR-02: "Carries sub, tv, iat, exp, jti, aud and nothing else." No profile data, no
# email, no health field. This tuple is the whole contract, and verification requires every
# one of them to be present.
ACCESS_TOKEN_REQUIRED_CLAIMS: Final = ("sub", "tv", "jti", "iat", "exp", "aud")


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    sub: uuid.UUID
    tv: int
    jti: str
    iat: datetime
    exp: datetime
    aud: str


def create_access_token(*, user_id: uuid.UUID, token_version: int) -> tuple[str, int]:
    """Returns (token, expires_in_seconds). `expires_in` is returned rather than recomputed
    by the caller so the value in the §5.2 response body cannot drift from the real `exp`."""
    issued_at = datetime.now(UTC)
    ttl = settings.ACCESS_TOKEN_TTL_SECONDS
    payload = {
        "sub": str(user_id),
        "tv": token_version,
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=ttl),
        "aud": settings.JWT_AUDIENCE,
    }
    token = jwt.encode(
        payload,
        settings.JWT_PRIVATE_KEY_PEM,
        algorithm=ACCESS_TOKEN_ALGORITHM,
    )
    return token, ttl


def verify_access_token(token: str) -> AccessTokenClaims:
    """Verify signature, audience and expiry. Raises TOKEN_EXPIRED or TOKEN_INVALID per §7.3.

    `algorithms` is a fixed one-element allowlist, so the header's `alg` is never consulted
    as an instruction -- only checked against this list. That closes the two classic JWT
    forgeries in one line: `alg: none` (accept an unsigned token) and `alg: HS256` keyed with
    the *public* key, which is public by definition and would otherwise let anyone mint a
    valid token.

    `tv` is parsed here but NOT compared: this function has no user row. The staleness check
    is `assert_token_version_current`, called by `get_current_user` once the user is loaded.
    """
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.JWT_PUBLIC_KEY_PEM,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
            options={
                "require": list(ACCESS_TOKEN_REQUIRED_CLAIMS),
                "verify_signature": True,
                "verify_exp": True,
                "verify_iat": True,
                "verify_aud": True,
            },
        )
    except jwt.ExpiredSignatureError as exc:
        # §7.3: distinct from TOKEN_INVALID because the client's correct response differs --
        # refresh and retry once, rather than log the user out.
        raise TokenExpiredError(detail="The access token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        # Bad signature, wrong audience, missing claim, unpermitted alg -- all one generic
        # code (§7.3), so a probing client learns nothing about which check failed.
        raise TokenInvalidError(detail="The access token could not be verified.") from exc

    try:
        subject = uuid.UUID(str(payload["sub"]))
    except (ValueError, AttributeError, TypeError) as exc:
        raise TokenInvalidError(detail="The access token subject is not a valid id.") from exc

    token_version = payload["tv"]
    if not isinstance(token_version, int) or isinstance(token_version, bool):
        # A string "0" or a bool would otherwise compare unequal (or, for bool, *equal*) to
        # the integer token_version in a way that silently mis-decides revocation.
        raise TokenInvalidError(detail="The access token version claim is malformed.")

    return AccessTokenClaims(
        sub=subject,
        tv=token_version,
        jti=str(payload["jti"]),
        iat=datetime.fromtimestamp(payload["iat"], tz=UTC),
        exp=datetime.fromtimestamp(payload["exp"], tz=UTC),
        aud=str(payload["aud"]),
    )


def assert_token_version_current(claims: AccessTokenClaims, current_token_version: int) -> None:
    """P1-ADR-02: bumping `users.token_version` invalidates every outstanding access token
    instantly. A token carrying a stale `tv` is TOKEN_INVALID, not TOKEN_EXPIRED -- the
    client must log out, not refresh (§7.3)."""
    if claims.tv != current_token_version:
        raise TokenInvalidError(detail="This token was invalidated. Sign in again.")


# =========================================================================================
# §6.3 · Opaque tokens (refresh, reset) -- 32 bytes, stored as SHA-256 only
# =========================================================================================

OPAQUE_TOKEN_BYTES: Final = 32


def generate_opaque_token() -> str:
    """§6.3: 32 random bytes, URL-safe base64. Used for both the refresh token and the
    5-minute reset token; the raw value exists in exactly one response body, once."""
    return secrets.token_urlsafe(OPAQUE_TOKEN_BYTES)


def hash_opaque_token(token: str) -> str:
    """§4.4 / §6.3: plain SHA-256 is correct *here* and only here. These tokens are 256 bits
    of uniform entropy, so there is nothing to brute-force and no pepper to add -- unlike a
    reset code, which is 39 bits and therefore needs the keyed hash below (P1-ADR-07)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def opaque_token_matches(presented_token: str, stored_hash: str) -> bool:
    """Constant-time. Single expression, no branch, no early return: see the note on
    reset_code_matches."""
    return secrets.compare_digest(hash_opaque_token(presented_token), stored_hash)


# =========================================================================================
# P1-ADR-07 · Reset codes: 8 chars from a reduced Base32 alphabet, HMAC-SHA256 with a pepper
# =========================================================================================

# RFC 4648 Base32 (A-Z, 2-7) with the visually ambiguous I and O removed. 0, 1 and lowercase
# l are absent from that alphabet already. 30 characters, 8 positions: 30**8 is about
# 6.6e11, ~39 bits.
RESET_CODE_ALPHABET: Final = "ABCDEFGHJKLMNPQRSTUVWXYZ234567"
RESET_CODE_LENGTH: Final = 8


def generate_reset_code() -> str:
    """§5.6: drawn with `secrets.choice` -- never `random`, which is a Mersenne Twister whose
    internal state is recoverable from a modest number of outputs, and reset codes are
    handed to attackers by design (request one for any address, §5.6 always returns 202)."""
    return "".join(secrets.choice(RESET_CODE_ALPHABET) for _ in range(RESET_CODE_LENGTH))


def normalise_reset_code(code: str) -> str:
    """§5.6: "Uppercase the submitted value before comparing." Surrounding whitespace goes
    too -- it is a paste artefact, not part of an 8-character code from a fixed alphabet.
    (Contrast normalise_password, which must not strip.)"""
    return code.strip().upper()


def _reset_code_pepper() -> bytes:
    """Read at call time, not bound at import, so a rotated pepper needs no process restart
    to be picked up by the next code issued. Absence still fails at import, because
    `settings` is constructed when `app.config` loads and the field is required."""
    return settings.RESET_CODE_PEPPER.encode("utf-8")


def hash_reset_code(user_id: uuid.UUID, code: str) -> str:
    """P1-ADR-07: HMAC-SHA256(key=RESET_CODE_PEPPER, msg=user_id ‖ code).

    The pepper -- not the user_id -- is what makes this resistant. The superseded design
    salted with `user_id`, which is stored in the same row as the digest, so a single row
    read plus a million SHA-256 passes recovered the code. Without the key, an attacker
    holding the entire table cannot compute even one candidate digest.

    The user_id remains in the message so a digest is bound to one account and cannot be
    replayed against another, but it is not doing the security work.
    """
    message = f"{user_id}{normalise_reset_code(code)}".encode()
    return hmac.new(_reset_code_pepper(), message, hashlib.sha256).hexdigest()


def reset_code_matches(user_id: uuid.UUID, presented_code: str, stored_hash: str) -> bool:
    """§5.6: `secrets.compare_digest` on the HMAC digests, constant time.

    Written as a single return expression on purpose. No length check, no `if`, no early
    return can precede the comparison -- any of those would leak information through timing
    or control flow and make the constant-time comparison decorative. Both operands are
    fixed-width hex digests of the same length whatever the presented code looks like,
    because hashing happens first. A test asserts this structurally, not by wall clock.
    """
    return secrets.compare_digest(hash_reset_code(user_id, presented_code), stored_hash)
