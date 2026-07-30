"""§6 security primitives and P1-ADR-07.

These are deliberately negative tests. A JWT verifier that accepts good tokens is easy; the
value is in proving it rejects a *validly signed* token from the wrong key, a swapped `alg`
header, a stale `tv`, and a wrong audience. Likewise for reset codes: the property that
matters is not that hashing works, it is that the digest is useless without the pepper.

On timing: §11.1 asks for constant-time comparison, and there is no wall-clock assertion
below. A timing assertion on a shared CI runner is noise -- it fails on an unlucky scheduling
quantum and passes on a genuinely branchy implementation often enough to be worthless. The
comparison paths are instead asserted *structurally*, over the AST: exactly one return,
`secrets.compare_digest` in it, and no branch or early return anywhere before it. That is the
property a timing test is trying to approximate, tested directly.
"""

from __future__ import annotations

import ast
import base64
import hashlib
import hmac
import inspect
import json
import os
import secrets
import subprocess
import sys
import textwrap
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt
import pytest
from argon2 import PasswordHasher, Type
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

from app.config import settings
from app.core import security
from app.core.errors import TokenExpiredError, TokenInvalidError, ValidationError
from app.core.security import (
    ACCESS_TOKEN_ALGORITHM,
    ACCESS_TOKEN_REQUIRED_CLAIMS,
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    RESET_CODE_ALPHABET,
    RESET_CODE_LENGTH,
    argon2_parameters,
    assert_token_version_current,
    create_access_token,
    email_local_part,
    generate_opaque_token,
    generate_reset_code,
    hash_opaque_token,
    hash_password,
    hash_reset_code,
    is_common_password,
    normalise_password,
    normalise_reset_code,
    opaque_token_matches,
    password_needs_rehash,
    reset_code_matches,
    validate_password,
    verify_access_token,
    verify_password,
)

_BACKEND_DIR = Path(__file__).resolve().parents[2]

# Captured before any test can patch it, so a spy can delegate to the genuine article.
_REAL_COMPARE_DIGEST = secrets.compare_digest


# =========================================================================================
# helpers
# =========================================================================================


def _second_ed25519_keypair() -> tuple[str, str]:
    """A REAL second keypair -- not a corrupted copy of the first.

    The point of the wrong-key test is a token that is cryptographically perfect in every
    respect except that it was signed by someone else. Flipping bytes in a signature proves
    only that the verifier notices corruption; this proves it notices a different signer.
    """
    key = ed25519.Ed25519PrivateKey.generate()
    private_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return private_pem, public_pem


def _valid_payload(**overrides: Any) -> dict[str, Any]:
    issued_at = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(uuid.uuid4()),
        "tv": 0,
        "jti": uuid.uuid4().hex,
        "iat": issued_at,
        "exp": issued_at + timedelta(minutes=15),
        "aud": settings.JWT_AUDIENCE,
    }
    payload.update(overrides)
    return payload


def _sign_with(private_key_pem: str, payload: dict[str, Any]) -> str:
    return jwt.encode(payload, private_key_pem, algorithm=ACCESS_TOKEN_ALGORITHM)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _forge_hs256(payload: dict[str, Any], *, secret: str) -> str:
    """Build an HS256 token by hand, bypassing PyJWT's refusal to use a PEM as an HMAC secret.

    That refusal is a good guardrail on the *signing* side and irrelevant on the verifying
    side: an attacker mounting algorithm confusion is not calling our library.
    """
    claims = {
        key: int(value.timestamp()) if isinstance(value, datetime) else value
        for key, value in payload.items()
    }
    signing_input = (
        f"{_b64url(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode())}"
        f".{_b64url(json.dumps(claims).encode())}"
    )
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(signature)}"


def _function_ast(func: Callable[..., Any]) -> ast.FunctionDef:
    module = ast.parse(textwrap.dedent(inspect.getsource(func)))
    node = module.body[0]
    assert isinstance(node, ast.FunctionDef)
    return node


def _run_python(code: str, *, env_overrides: dict[str, str | None], cwd: Path) -> tuple[int, str]:
    """Run `code` in a fresh interpreter with a controlled environment.

    `cwd` is a temp directory on purpose: `Settings.model_config` loads `.env` relative to the
    working directory, so running from backend/ would let the developer's real .env supply the
    very variable the test is trying to remove. A variable "unset" while .env still provides
    it is not unset at all, and the test would silently prove nothing.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_BACKEND_DIR)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(cwd),
        timeout=180,
    )
    return completed.returncode, completed.stdout + completed.stderr


# =========================================================================================
# §6.1 · Argon2id
# =========================================================================================


def test_hash_is_argon2id_and_salted_per_call() -> None:
    first = hash_password("correct horse battery")
    second = hash_password("correct horse battery")
    assert first.startswith("$argon2id$")
    assert first != second, "a per-hash random salt is what makes a rainbow table useless"


def test_verify_succeeds_on_the_correct_password() -> None:
    stored = hash_password("correct horse battery")
    result = verify_password("correct horse battery", stored)
    assert result.ok is True
    assert result.upgraded_hash is None


def test_verify_fails_on_a_wrong_password() -> None:
    stored = hash_password("correct horse battery")
    assert verify_password("correct horse batteries", stored).ok is False


def test_verify_fails_rather_than_raising_on_a_corrupt_stored_hash() -> None:
    """A malformed hash column must not become a 500. §5.3 collapses every login failure
    into one generic INVALID_CREDENTIALS, and that includes this one."""
    assert verify_password("anything", "not-an-argon2-hash").ok is False
    assert verify_password("anything", "").ok is False


def test_check_needs_rehash_triggers_the_upgrade_path_when_parameters_change() -> None:
    """§6.1's rehash-on-verify. The stored hash below was produced at a *higher* time cost
    than the current configuration, exactly as a hash written before a parameter change would
    be. A correct verify must return a replacement hash at today's parameters."""
    current = argon2_parameters()
    stale_hasher = PasswordHasher(
        time_cost=current["time_cost"] + 1,
        memory_cost=current["memory_cost"],
        parallelism=current["parallelism"],
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    stale_hash = stale_hasher.hash("correct horse battery")
    assert password_needs_rehash(stale_hash) is True

    result = verify_password("correct horse battery", stale_hash)
    assert result.ok is True
    assert result.upgraded_hash is not None
    assert result.upgraded_hash != stale_hash

    # The upgrade must be usable and must not itself need upgrading, or every login rehashes.
    assert verify_password("correct horse battery", result.upgraded_hash).ok is True
    assert password_needs_rehash(result.upgraded_hash) is False


def test_a_wrong_password_never_triggers_a_rehash() -> None:
    """Rehashing on a failed verify would hand an attacker a free Argon2 computation per
    guess, and §6.1 conditions the upgrade on success."""
    current = argon2_parameters()
    stale_hash = PasswordHasher(
        time_cost=current["time_cost"] + 1,
        memory_cost=current["memory_cost"],
        parallelism=current["parallelism"],
    ).hash("correct horse battery")
    result = verify_password("wrong password entirely", stale_hash)
    assert result.ok is False
    assert result.upgraded_hash is None


def test_password_needs_rehash_is_false_for_a_hash_at_current_parameters() -> None:
    assert password_needs_rehash(hash_password("correct horse battery")) is False


def test_test_mode_argon2_parameters_are_in_force_under_env_test() -> None:
    """In-process: conftest sets ENV=test, so §6.1's "Test override" row applies."""
    assert settings.ENV == "test"
    assert argon2_parameters() == {"memory_cost": 8192, "time_cost": 1, "parallelism": 4}


_ARGON2_PROBE = "from app.core.security import argon2_parameters; print(argon2_parameters())"


def test_production_argon2_cost_is_the_default_with_env_unset(tmp_path: Path) -> None:
    """Empirical, in a subprocess, not inferred from reading config.py: the reduced cost must
    be unreachable unless ENV is exactly "test". With ENV absent, config's default is
    "development", which is not test."""
    code, output = _run_python(_ARGON2_PROBE, env_overrides={"ENV": None}, cwd=tmp_path)
    assert code == 0, output
    assert "'memory_cost': 65536" in output
    assert "'time_cost': 3" in output
    assert "'parallelism': 4" in output


@pytest.mark.parametrize("env", ["development", "staging", "production"])
def test_test_mode_argon2_parameters_never_leak_into_another_environment(
    env: str, tmp_path: Path
) -> None:
    code, output = _run_python(_ARGON2_PROBE, env_overrides={"ENV": env}, cwd=tmp_path)
    assert code == 0, output
    assert "'memory_cost': 65536" in output
    assert "'time_cost': 3" in output
    assert "8192" not in output


def test_env_test_reduces_the_cost_in_a_subprocess_too(tmp_path: Path) -> None:
    """The other side of the same coin: the override does apply where it is meant to, so the
    test above is proving isolation rather than a broken override."""
    code, output = _run_python(_ARGON2_PROBE, env_overrides={"ENV": "test"}, cwd=tmp_path)
    assert code == 0, output
    assert "'memory_cost': 8192" in output
    assert "'time_cost': 1" in output


# =========================================================================================
# §6.2 / §7.1 · Password policy -- every boundary
# =========================================================================================


def _password_error_code(password: str, *, email: str | None = None) -> str:
    with pytest.raises(ValidationError) as exc_info:
        validate_password(password, email=email)
    error = exc_info.value
    assert error.code == "VALIDATION_ERROR"
    assert error.status == 422
    assert len(error.errors) == 1
    assert error.errors[0]["field"] == "password"
    return error.errors[0]["code"]


def test_seven_characters_is_rejected() -> None:
    assert PASSWORD_MIN_LENGTH == 8
    assert _password_error_code("a" * 7) == "TOO_SHORT"


def test_eight_characters_is_accepted() -> None:
    assert validate_password("aX7$kQ2m") == "aX7$kQ2m"


def test_one_hundred_and_twenty_eight_characters_is_accepted() -> None:
    assert PASSWORD_MAX_LENGTH == 128
    password = "q" * 127 + "Z"
    assert validate_password(password) == password


def test_one_hundred_and_twenty_nine_characters_is_rejected() -> None:
    assert _password_error_code("q" * 128 + "Z") == "TOO_LONG"


def test_a_denylisted_password_is_rejected() -> None:
    assert _password_error_code("password123") == "TOO_COMMON"


def test_the_denylist_is_case_insensitive() -> None:
    """`PassWord123` is the same guess as `password123` to anyone running a wordlist."""
    assert _password_error_code("PassWord123") == "TOO_COMMON"
    assert is_common_password("QWERTY123") is True


def test_the_local_part_of_the_users_own_email_is_rejected() -> None:
    assert _password_error_code("nabilhaddad", email="nabilhaddad@example.com") == "TOO_COMMON"


def test_the_email_local_part_rule_is_case_insensitive() -> None:
    assert _password_error_code("NabilHaddad", email="nabilhaddad@example.com") == "TOO_COMMON"


def test_the_email_local_part_rule_does_not_reject_an_unrelated_password() -> None:
    assert validate_password("aX7$kQ2mZ", email="nabilhaddad@example.com") == "aX7$kQ2mZ"


def test_the_email_rule_is_skipped_when_no_address_is_supplied() -> None:
    """§6.2 scopes the rule to "the local part of the user's own email"; with no address in
    hand there is no such thing, and the check must not invent one."""
    assert validate_password("nabilhaddad") == "nabilhaddad"


def test_email_local_part_splits_on_the_last_at_sign() -> None:
    assert email_local_part("nabil@example.com") == "nabil"
    assert email_local_part('"odd@name"@example.com') == '"odd@name"'
    assert email_local_part("no-at-sign") == "no-at-sign"


# --- NFKC ------------------------------------------------------------------------------


_LAM_ALEF_LIGATURE = "ﻻ"  # ARABIC LIGATURE LAM WITH ALEF ISOLATED FORM
_LAM_PLUS_ALEF = "لا"  # the two letters it decomposes to under NFKC


def test_nfkc_normalisation_makes_an_arabic_password_verify_consistently() -> None:
    """The real failure this prevents: a user sets a password on a keyboard that emits the
    LAM-ALEF ligature and then cannot log in from one that emits the two letters separately.
    Same password to the user, different bytes on the wire, and without NFKC a different hash.
    """
    typed_with_ligature = f"كلمة{_LAM_ALEF_LIGATURE}سر1"
    typed_decomposed = f"كلمة{_LAM_PLUS_ALEF}سر1"
    assert typed_with_ligature != typed_decomposed, "the two inputs must genuinely differ"
    assert normalise_password(typed_with_ligature) == normalise_password(typed_decomposed)

    stored = hash_password(typed_with_ligature)
    assert verify_password(typed_decomposed, stored).ok is True, (
        "an Arabic password set on one keyboard must verify from another"
    )
    assert verify_password(typed_with_ligature, stored).ok is True


def test_nfkc_normalisation_applies_to_full_width_latin_too() -> None:
    stored = hash_password("ＰＡＳＳＷＯＲＤＸ")  # full-width
    assert verify_password("PASSWORDX", stored).ok is True


def test_length_is_measured_after_normalisation() -> None:
    """Seven codepoints in, eight out, because the ligature expands. Measuring before
    normalisation would reject a password the hasher would then happily accept -- and the
    inconsistency, not the direction, is the bug."""
    seven_codepoints = f"كلم{_LAM_ALEF_LIGATURE}سر1"
    assert len(seven_codepoints) == 7
    assert len(normalise_password(seven_codepoints)) == 8
    assert validate_password(seven_codepoints) == normalise_password(seven_codepoints)


def test_validate_password_returns_the_normalised_form_for_hashing() -> None:
    raw = f"كلمة{_LAM_ALEF_LIGATURE}سر1"
    assert validate_password(raw) == normalise_password(raw) != raw


def test_whitespace_inside_a_password_is_not_stripped() -> None:
    """ "correct horse battery" is the §5.2 example password; spaces are content. Trimming
    would silently change the credential and the user could not reproduce it."""
    padded = "  aX7$kQ2m  "
    assert validate_password(padded) == padded
    assert verify_password(padded, hash_password(padded)).ok is True
    assert verify_password(padded.strip(), hash_password(padded)).ok is False


def test_an_emoji_password_round_trips() -> None:
    password = "🏋️‍♂️🏋️‍♂️correct"
    assert verify_password(password, hash_password(validate_password(password))).ok is True


# =========================================================================================
# §6.3 · Access tokens
# =========================================================================================


def test_access_token_round_trip_carries_the_expected_claims() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id=user_id, token_version=7)

    assert expires_in == settings.ACCESS_TOKEN_TTL_SECONDS
    claims = verify_access_token(token)
    assert claims.sub == user_id
    assert claims.tv == 7
    assert claims.aud == settings.JWT_AUDIENCE
    assert claims.jti
    assert claims.exp - claims.iat == timedelta(seconds=settings.ACCESS_TOKEN_TTL_SECONDS)


def test_the_token_carries_those_claims_and_nothing_else() -> None:
    """P1-ADR-02: "Carries sub, tv, iat, exp, jti, aud and nothing else." No email, no
    profile field, no health field -- a JWT is readable by anyone holding it."""
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    payload = jwt.decode(token, options={"verify_signature": False}, audience=settings.JWT_AUDIENCE)
    assert set(payload) == set(ACCESS_TOKEN_REQUIRED_CLAIMS)


def test_the_signing_algorithm_is_eddsa() -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    assert jwt.get_unverified_header(token)["alg"] == "EdDSA"


def test_a_token_signed_with_a_different_ed25519_key_is_rejected() -> None:
    """A validly signed token from the wrong issuer. Every claim is right, the algorithm is
    right, the signature verifies -- against the wrong public key. This is the test that a
    verifier trusting the token's own contents would fail."""
    other_private_key, other_public_key = _second_ed25519_keypair()
    forged = _sign_with(other_private_key, _valid_payload())

    # Prove the forgery is genuinely well-formed -- it verifies against ITS OWN public key --
    # so the rejection below is about the signing key and nothing else.
    assert jwt.get_unverified_header(forged)["alg"] == "EdDSA"
    assert (
        jwt.decode(
            forged,
            other_public_key,
            algorithms=[ACCESS_TOKEN_ALGORITHM],
            audience=settings.JWT_AUDIENCE,
        )["tv"]
        == 0
    )

    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


def test_the_wrong_key_rejection_is_about_the_key_not_the_payload() -> None:
    """Sign the *same* payload with our key and with a foreign key: ours verifies, theirs
    does not. Nothing but the signing key differs."""
    payload = _valid_payload()
    ours = _sign_with(settings.JWT_PRIVATE_KEY_PEM, payload)
    theirs = _sign_with(_second_ed25519_keypair()[0], payload)
    assert verify_access_token(ours).jti == payload["jti"]
    with pytest.raises(TokenInvalidError):
        verify_access_token(theirs)


def test_a_tampered_signature_is_rejected() -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    header, payload, signature = token.split(".")
    flipped = "B" if signature[0] != "B" else "C"
    with pytest.raises(TokenInvalidError):
        verify_access_token(f"{header}.{payload}.{flipped}{signature[1:]}")


def test_a_tampered_payload_is_rejected() -> None:
    """Escalating `tv` in the body without resigning -- the whole point of the signature.

    The claims are rewritten in place rather than replaced wholesale, so the forged token
    differs from the real one in exactly one value.
    """
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=0)
    header, payload, signature = token.split(".")

    claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    assert claims["tv"] == 0
    claims["tv"] = 999
    forged_payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")

    with pytest.raises(TokenInvalidError):
        verify_access_token(f"{header}.{forged_payload}.{signature}")


def test_a_wrong_audience_is_rejected() -> None:
    forged = _sign_with(settings.JWT_PRIVATE_KEY_PEM, _valid_payload(aud="some-other-service"))
    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


def test_an_expired_token_is_rejected_with_token_expired_not_token_invalid() -> None:
    """§7.3 keeps these separate because the client's correct reaction differs: refresh and
    retry once for EXPIRED, log out for INVALID."""
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    forged = _sign_with(
        settings.JWT_PRIVATE_KEY_PEM,
        _valid_payload(iat=expired_at - timedelta(minutes=15), exp=expired_at),
    )
    with pytest.raises(TokenExpiredError):
        verify_access_token(forged)


def test_an_expired_token_produced_by_our_own_signer_is_rejected() -> None:
    """The same thing through the real code path rather than a hand-built payload: a negative
    TTL makes create_access_token mint an already-dead token."""
    original_ttl = settings.ACCESS_TOKEN_TTL_SECONDS
    try:
        settings.ACCESS_TOKEN_TTL_SECONDS = -10
        token, expires_in = create_access_token(user_id=uuid.uuid4(), token_version=0)
        assert expires_in == -10
        with pytest.raises(TokenExpiredError):
            verify_access_token(token)
    finally:
        settings.ACCESS_TOKEN_TTL_SECONDS = original_ttl


@pytest.mark.parametrize("missing", ACCESS_TOKEN_REQUIRED_CLAIMS)
def test_a_token_missing_any_required_claim_is_rejected(missing: str) -> None:
    payload = _valid_payload()
    del payload[missing]
    forged = _sign_with(settings.JWT_PRIVATE_KEY_PEM, payload)
    with pytest.raises((TokenInvalidError, TokenExpiredError)):
        verify_access_token(forged)


def test_a_stale_token_version_is_rejected() -> None:
    """P1-ADR-02: bumping users.token_version kills every outstanding access token at once --
    the mechanism behind logout-all, password reset and account deletion."""
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=3)
    claims = verify_access_token(token)
    assert_token_version_current(claims, 3)  # current: fine
    with pytest.raises(TokenInvalidError):
        assert_token_version_current(claims, 4)  # bumped: dead


def test_a_token_version_from_the_future_is_also_rejected() -> None:
    token, _ = create_access_token(user_id=uuid.uuid4(), token_version=5)
    with pytest.raises(TokenInvalidError):
        assert_token_version_current(verify_access_token(token), 4)


@pytest.mark.parametrize("bad_tv", ["3", True, None, 3.0])
def test_a_non_integer_token_version_claim_is_rejected(bad_tv: object) -> None:
    """`"3" != 3` and `True == 1` in Python. Either would make the revocation comparison
    decide wrongly -- silently, and in the direction of accepting a dead token."""
    forged = _sign_with(settings.JWT_PRIVATE_KEY_PEM, _valid_payload(tv=bad_tv))
    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


def test_a_subject_that_is_not_a_uuid_is_rejected() -> None:
    forged = _sign_with(settings.JWT_PRIVATE_KEY_PEM, _valid_payload(sub="not-a-uuid"))
    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


@pytest.mark.parametrize("garbage", ["", "   ", "not.a.token", "a.b", "....", "Bearer x.y.z"])
def test_structurally_invalid_input_is_rejected_without_raising_something_else(
    garbage: str,
) -> None:
    with pytest.raises(TokenInvalidError):
        verify_access_token(garbage)


# --- algorithm pinning -----------------------------------------------------------------


def test_an_alg_none_token_is_rejected() -> None:
    """The oldest JWT forgery: declare the token unsigned and hope the verifier obliges."""
    unsigned = jwt.encode(_valid_payload(), key="", algorithm="none")
    assert jwt.get_unverified_header(unsigned)["alg"] == "none"
    with pytest.raises(TokenInvalidError):
        verify_access_token(unsigned)


def test_an_hs256_token_signed_with_the_public_key_is_rejected() -> None:
    """The algorithm-confusion attack. The public key is public by definition, so a verifier
    that took `alg` from the header would accept a token anyone could mint -- it would use
    that public value as an HMAC secret. Pinning EdDSA is what closes it.

    Hand-rolled rather than built with `jwt.encode`, which refuses a PEM as an HMAC secret
    and so cannot produce this forgery. An attacker is not using our library's guardrails,
    and a test that relies on them is testing PyJWT rather than our verifier.
    """
    forged = _forge_hs256(_valid_payload(), secret=settings.JWT_PUBLIC_KEY_PEM)
    assert jwt.get_unverified_header(forged)["alg"] == "HS256"

    # Prove the forgery is a genuinely well-MACed HS256 token, so this test is passing on
    # algorithm pinning rather than on the token being malformed. Verified by recomputing the
    # MAC directly: PyJWT refuses a PEM as an HMAC secret on the decode side too, and that
    # refusal is a property of PyJWT, not the control under test.
    signing_input, _, signature = forged.rpartition(".")
    expected_mac = hmac.new(
        settings.JWT_PUBLIC_KEY_PEM.encode(), signing_input.encode(), hashlib.sha256
    ).digest()
    assert signature == _b64url(expected_mac), "the forgery must be a correctly MACed token"

    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


@pytest.mark.parametrize("algorithm", ["HS256", "HS384", "HS512"])
def test_no_symmetric_algorithm_is_accepted_whatever_the_secret(algorithm: str) -> None:
    forged = jwt.encode(_valid_payload(), key="s" * 64, algorithm=algorithm)
    with pytest.raises(TokenInvalidError):
        verify_access_token(forged)


def test_the_verifier_pins_eddsa_from_a_literal_and_never_reads_the_header() -> None:
    """Structural, not behavioural: the two tests above show *these* forgeries fail, this one
    shows the reason generalises. `algorithms` is a one-element list built from a module
    constant, so there is no path by which a caller-supplied `alg` reaches the decision.
    """
    assert ACCESS_TOKEN_ALGORITHM == "EdDSA"

    node = _function_ast(verify_access_token)
    decode_calls = [
        call
        for call in ast.walk(node)
        if isinstance(call, ast.Call) and ast.unparse(call.func) == "jwt.decode"
    ]
    assert len(decode_calls) == 1, "one decode call, so there is one place to audit"

    algorithms = {kw.arg: kw.value for kw in decode_calls[0].keywords}.get("algorithms")
    assert isinstance(algorithms, ast.List), "a literal list, not a value derived at runtime"
    assert [ast.unparse(element) for element in algorithms.elts] == ["ACCESS_TOKEN_ALGORITHM"]

    source = inspect.getsource(verify_access_token)
    assert "get_unverified_header" not in source
    assert "unverified" not in source


def test_signature_verification_is_never_switched_off() -> None:
    node = _function_ast(verify_access_token)
    literals = {
        ast.unparse(key): ast.unparse(value)
        for dict_node in ast.walk(node)
        if isinstance(dict_node, ast.Dict)
        for key, value in zip(dict_node.keys, dict_node.values, strict=True)
        if key is not None
    }
    assert literals["'verify_signature'"] == "True"
    assert literals["'verify_exp'"] == "True"
    assert literals["'verify_aud'"] == "True"


# =========================================================================================
# §6.3 · Opaque tokens (refresh, reset)
# =========================================================================================


def test_opaque_tokens_are_32_bytes_of_urlsafe_entropy() -> None:
    token = generate_opaque_token()
    # token_urlsafe(32) is 32 bytes base64url-encoded without padding.
    assert len(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))) == 32
    assert set(token) <= set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def test_opaque_tokens_do_not_repeat() -> None:
    assert len({generate_opaque_token() for _ in range(2000)}) == 2000


def test_opaque_token_hash_is_sha256_hex_and_deterministic() -> None:
    token = generate_opaque_token()
    digest = hash_opaque_token(token)
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest == hash_opaque_token(token)
    assert digest != hash_opaque_token(generate_opaque_token())


def test_opaque_token_matching() -> None:
    token = generate_opaque_token()
    stored = hash_opaque_token(token)
    assert opaque_token_matches(token, stored) is True
    assert opaque_token_matches(generate_opaque_token(), stored) is False
    assert opaque_token_matches(token.upper(), stored) is False, "case-sensitive, unlike a code"


# =========================================================================================
# P1-ADR-07 · Reset codes
# =========================================================================================


def test_the_alphabet_is_the_reduced_base32_set_from_the_adr() -> None:
    assert RESET_CODE_ALPHABET == "ABCDEFGHJKLMNPQRSTUVWXYZ234567"
    assert len(RESET_CODE_ALPHABET) == 30
    assert len(set(RESET_CODE_ALPHABET)) == 30, "no duplicate weights the draw"
    assert RESET_CODE_LENGTH == 8


@pytest.mark.parametrize("ambiguous", ["I", "O", "0", "1", "l", "i", "o"])
def test_the_alphabet_excludes_every_visually_ambiguous_character(ambiguous: str) -> None:
    assert ambiguous not in RESET_CODE_ALPHABET


def test_generated_codes_never_emit_an_ambiguous_character_over_a_large_sample() -> None:
    """20 000 codes is 160 000 draws. If any of I, O, 0 or 1 were reachable at a per-draw
    probability of even 1/30, the chance of this sample missing it is nil -- so a pass here
    is evidence about the generator, not about luck."""
    sample = [generate_reset_code() for _ in range(20_000)]
    seen = set("".join(sample))

    assert not seen & set("IO01"), f"ambiguous characters emitted: {sorted(seen & set('IO01'))}"
    assert seen <= set(RESET_CODE_ALPHABET)
    assert seen == set(RESET_CODE_ALPHABET), (
        "every alphabet character should appear across 160 000 draws; a missing one means the "
        "generator is drawing from a narrower set than it claims"
    )


def test_every_generated_code_is_exactly_eight_characters_from_the_alphabet() -> None:
    for code in (generate_reset_code() for _ in range(20_000)):
        assert len(code) == 8
        assert set(code) <= set(RESET_CODE_ALPHABET)


def test_codes_are_drawn_with_secrets_not_random() -> None:
    """§5.6: "drawn with secrets.choice -- never random". `random` is a Mersenne Twister whose
    state is recoverable from its output, and §5.6 hands codes to unauthenticated callers by
    design (forgot-password always returns 202)."""
    assert "secrets.choice" in {
        ast.unparse(node.func)
        for node in ast.walk(_function_ast(generate_reset_code))
        if isinstance(node, ast.Call)
    }
    module_source = Path(inspect.getfile(security)).read_text(encoding="utf-8")
    assert "import random" not in module_source
    assert "random." not in module_source


def test_generated_codes_are_not_obviously_repeating() -> None:
    codes = [generate_reset_code() for _ in range(5000)]
    assert len(set(codes)) == len(codes), "30**8 is ~6.6e11; 5000 draws colliding is a bug"


# --- hashing (the pepper is the control that matters) -----------------------------------


def test_the_same_code_under_two_different_peppers_produces_different_digests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The property P1-ADR-07 rests on. An attacker holding the whole table but not the key
    cannot compute a single candidate digest, whatever the code length -- which is why the
    ADR calls the pepper load-bearing and the code length defence in depth."""
    user_id = uuid.uuid4()
    code = "ABCD2345"

    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "pepper-one")
    with_first = hash_reset_code(user_id, code)

    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "pepper-two")
    with_second = hash_reset_code(user_id, code)

    assert with_first != with_second
    assert len(with_first) == len(with_second) == 64

    # And rotating back reproduces the first digest, so the pepper is the only variable.
    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "pepper-one")
    assert hash_reset_code(user_id, code) == with_first


def test_a_digest_made_under_a_rotated_pepper_no_longer_matches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P1-ADR-07's consequence: "Rotating the pepper invalidates every outstanding reset
    code", accepted against a 10-minute TTL."""
    user_id = uuid.uuid4()
    code = generate_reset_code()
    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "pepper-before-rotation")
    stored = hash_reset_code(user_id, code)
    assert reset_code_matches(user_id, code, stored) is True

    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "pepper-after-rotation")
    assert reset_code_matches(user_id, code, stored) is False


def test_the_pepper_is_never_recoverable_from_a_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    """A weak assertion by itself, but it pins the one mistake that would be catastrophic and
    easy to make: concatenating the pepper into the message instead of using it as the key."""
    monkeypatch.setattr(settings, "RESET_CODE_PEPPER", "a-very-distinctive-pepper-value")
    digest = hash_reset_code(uuid.uuid4(), "ABCD2345")
    assert "a-very-distinctive-pepper-value" not in digest
    assert base64.b16encode(b"a-very-distinctive-pepper-value").decode().lower() not in digest


def test_the_digest_is_bound_to_one_user() -> None:
    """user_id stays in the HMAC message so a digest cannot be replayed against another
    account, even though the pepper -- not the user_id -- is doing the security work."""
    code = "ABCD2345"
    assert hash_reset_code(uuid.uuid4(), code) != hash_reset_code(uuid.uuid4(), code)


def test_hash_reset_code_is_deterministic_and_sha256_sized() -> None:
    user_id = uuid.uuid4()
    digest = hash_reset_code(user_id, "ABCD2345")
    assert len(digest) == 64
    assert int(digest, 16) >= 0
    assert digest == hash_reset_code(user_id, "ABCD2345")


def test_a_different_code_produces_a_different_digest() -> None:
    user_id = uuid.uuid4()
    assert hash_reset_code(user_id, "ABCD2345") != hash_reset_code(user_id, "ABCD2346")


# --- input normalisation ---------------------------------------------------------------


def test_the_submitted_code_is_uppercased_before_comparison() -> None:
    """§5.6: "Uppercase the submitted value before comparing." The user typed it from an
    email; requiring the shift key would be a support burden with no security value, since
    the alphabet has no lowercase members to confuse it with."""
    user_id = uuid.uuid4()
    stored = hash_reset_code(user_id, "ABCD2345")
    assert reset_code_matches(user_id, "abcd2345", stored) is True
    assert reset_code_matches(user_id, "AbCd2345", stored) is True


def test_surrounding_whitespace_from_a_paste_is_ignored() -> None:
    user_id = uuid.uuid4()
    stored = hash_reset_code(user_id, "ABCD2345")
    assert reset_code_matches(user_id, "  ABCD2345\n", stored) is True


def test_normalise_reset_code_does_not_strip_interior_characters() -> None:
    assert normalise_reset_code(" abcd 2345 ") == "ABCD 2345"


def test_a_wrong_code_does_not_match() -> None:
    user_id = uuid.uuid4()
    stored = hash_reset_code(user_id, "ABCD2345")
    assert reset_code_matches(user_id, "ABCD2346", stored) is False
    assert reset_code_matches(user_id, "", stored) is False
    assert reset_code_matches(user_id, "SHORT", stored) is False
    assert reset_code_matches(user_id, "MUCHLONGERTHANEIGHT", stored) is False
    assert reset_code_matches(uuid.uuid4(), "ABCD2345", stored) is False


# --- constant-time comparison (§11.1), asserted structurally ---------------------------


@pytest.mark.parametrize("function", [reset_code_matches, opaque_token_matches])
def test_comparison_is_a_single_compare_digest_with_no_branch_before_it(
    function: Callable[..., bool],
) -> None:
    """§11.1 asks for constant-time comparison. This asserts the property directly instead of
    timing it: a wall-clock assertion on a shared runner is flaky in both directions -- it
    fails on an unlucky scheduling quantum and passes on a branchy implementation.

    What is checked: the body is exactly one `return`, its value is a call to
    `secrets.compare_digest`, and the function contains no `if`, no loop, no `try`, no
    short-circuiting `and`/`or` and no comparison operator anywhere. A length check or an
    early `return False` is precisely the leak that makes compare_digest decorative, and
    either would fail here.
    """
    node = _function_ast(function)

    body = [
        statement
        for statement in node.body
        if not (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
    ]
    assert len(body) == 1, f"expected one statement after the docstring, got {len(body)}"
    return_statement = body[0]
    assert isinstance(return_statement, ast.Return)
    assert return_statement.value is not None
    assert isinstance(return_statement.value, ast.Call)
    assert ast.unparse(return_statement.value.func) == "secrets.compare_digest"

    forbidden = (ast.If, ast.IfExp, ast.For, ast.While, ast.Try, ast.BoolOp, ast.Compare)
    offenders = [type(n).__name__ for n in ast.walk(node) if isinstance(n, forbidden)]
    assert not offenders, f"branching before the comparison leaks timing: {offenders}"

    returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
    assert len(returns) == 1, "an early return is an observable side channel"


def _compare_reset_code(candidate: str, stored_hash: str) -> bool:
    return reset_code_matches(uuid.uuid4(), candidate, stored_hash)


@pytest.mark.parametrize("compare", [_compare_reset_code, opaque_token_matches])
@pytest.mark.parametrize(
    "candidate", ["ABCD2345", "", "X", "WAY-TOO-LONG-TO-BE-A-CODE-OR-A-TOKEN", " \t\n"]
)
def test_compare_digest_is_actually_reached_whatever_the_submitted_length(
    monkeypatch: pytest.MonkeyPatch,
    compare: Callable[[str, str], bool],
    candidate: str,
) -> None:
    """The structural test proves no branch exists; this proves the call is reached -- for a
    plausible value, an empty one, a short one, an over-long one and pure whitespace alike. An
    implementation that short-circuited on any of them would leave the spy uncalled."""
    calls: list[tuple[str, str]] = []

    def spy(left: str, right: str) -> bool:
        calls.append((left, right))
        # _REAL_COMPARE_DIGEST, not secrets.compare_digest: the patch below lands on the
        # `secrets` module itself (security.py calls through to it rather than aliasing it),
        # so reading the name here would find the spy and recurse forever.
        return bool(_REAL_COMPARE_DIGEST(left, right))

    monkeypatch.setattr("app.core.security.secrets.compare_digest", spy)

    assert compare(candidate, "0" * 64) is False
    assert len(calls) == 1, f"compare_digest not reached for {candidate!r}"

    left, right = calls[0]
    assert len(left) == 64, "the submitted value must be hashed before it is compared"
    assert len(right) == 64, (
        "both operands are fixed-width digests, so the comparison cannot vary with the "
        "length of what the caller submitted"
    )


# =========================================================================================
# P1-ADR-07 · the pepper is required at import
# =========================================================================================


def test_the_app_fails_at_import_when_reset_code_pepper_is_absent(tmp_path: Path) -> None:
    """P1-ADR-07's consequence: "a deployment missing it will not start rather than silently
    falling back to an unkeyed hash".

    Run for real in a subprocess with the variable removed. `cwd=tmp_path` matters: from
    backend/ the developer's own .env would supply the pepper and this test would pass
    without proving anything.
    """
    code, output = _run_python(
        "import app.core.security", env_overrides={"RESET_CODE_PEPPER": None}, cwd=tmp_path
    )
    assert code != 0, f"import unexpectedly succeeded without a pepper:\n{output}"
    assert "RESET_CODE_PEPPER" in output
    # config.py's Settings.__init__ catches pydantic's own ValidationError at the
    # construction boundary and re-raises ConfigurationError naming only the field --
    # never pydantic's raw wording, whose `errors()` embeds every other field supplied
    # to Settings() (secrets included) as `input` on a missing-field error. See
    # test_config.py for the leak this replaces.
    assert "ConfigurationError" in output
    assert "validation error" not in output.lower()
    assert "Field required" not in output


def test_the_app_fails_at_import_when_reset_code_pepper_is_blank(tmp_path: Path) -> None:
    """`RESET_CODE_PEPPER=` is an empty string, not a missing variable, so the required-field
    check cannot catch it -- and copying .env.example verbatim lands exactly there. An empty
    HMAC key is not a weak key, it is no key."""
    code, output = _run_python(
        "import app.core.security", env_overrides={"RESET_CODE_PEPPER": "   "}, cwd=tmp_path
    )
    assert code != 0, f"import unexpectedly succeeded with a blank pepper:\n{output}"
    assert "RESET_CODE_PEPPER is set but empty" in output


def test_importing_security_needs_no_database(tmp_path: Path) -> None:
    """app.database asserts its connection is unprivileged at import, which requires a live
    PostgreSQL. security.py must not drag that in, or every primitive here becomes
    DB-coupled -- including the two tests above, which would then fail for the wrong reason.
    """
    code, output = _run_python(
        "import sys; import app.core.security; "
        "assert 'app.database' not in sys.modules, sorted(sys.modules); print('clean')",
        env_overrides={"DATABASE_URL": "postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none"},
        cwd=tmp_path,
    )
    assert code == 0, output
    assert "clean" in output
