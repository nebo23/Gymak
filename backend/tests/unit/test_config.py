"""Appendix A.1 permits the JWT keys to be supplied as raw PEM or as base64-wrapped PEM
("base64 if multiline is awkward"). config.py normalises both at load time; these tests
pin both accepted paths and every rejection, including that the rejection names the field
and never echoes the key material.
"""

from __future__ import annotations

import base64
import textwrap

import pytest
from pydantic_settings import SettingsConfigDict

from app.config import ConfigurationError, Settings

# A genuine Ed25519 key, generated with `openssl genpkey -algorithm ed25519`. This is the
# PUBLIC half deliberately: the validator only inspects PEM structure, so a public key
# exercises it identically, and committing anything shaped like a private key would
# violate spec §6.5 ("no secret in the repository") and trip secret scanners.
_REAL_PEM = (
    "-----BEGIN PUBLIC KEY-----\n"
    "MCowBQYDK2VwAyEAMmrT6Y+wU4reJQWeIRsSab2BZWCvah4YhVqHZBgSX64=\n"
    "-----END PUBLIC KEY-----\n"
)


class _HermeticSettings(Settings):
    """Identical to Settings -- every field and both validators are inherited -- but with
    dotenv loading switched off, so a developer's real backend/.env cannot change what
    these tests prove."""

    model_config = SettingsConfigDict(env_file=None, extra="ignore")


def _settings(
    *,
    private_key: str = _REAL_PEM,
    public_key: str = _REAL_PEM,
    pepper: str = "test-pepper-not-a-real-secret",
) -> Settings:
    return _HermeticSettings(
        DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
        JWT_PRIVATE_KEY_PEM=private_key,
        JWT_PUBLIC_KEY_PEM=public_key,
        RESET_CODE_PEPPER=pepper,
        FIREBASE_CREDENTIALS_JSON="{}",
    )


# --- accepted: raw PEM ----------------------------------------------------------------


def test_raw_pem_passes_through_unchanged() -> None:
    settings = _settings()
    assert settings.JWT_PRIVATE_KEY_PEM == _REAL_PEM
    assert settings.JWT_PUBLIC_KEY_PEM == _REAL_PEM


def test_raw_pem_missing_its_trailing_newline_gains_one() -> None:
    settings = _settings(private_key=_REAL_PEM.rstrip("\n"))
    assert settings.JWT_PRIVATE_KEY_PEM == _REAL_PEM


# --- accepted: base64-wrapped PEM -----------------------------------------------------


def test_base64_wrapped_pem_is_decoded_to_the_same_raw_pem() -> None:
    encoded = base64.b64encode(_REAL_PEM.encode()).decode()
    settings = _settings(private_key=encoded, public_key=encoded)
    assert settings.JWT_PRIVATE_KEY_PEM == _REAL_PEM
    assert settings.JWT_PUBLIC_KEY_PEM == _REAL_PEM


def test_base64_split_across_lines_is_decoded() -> None:
    """What `base64` and `openssl base64` emit by default, and what a developer gets from
    pasting a wrapped block into .env."""
    encoded = "\n".join(textwrap.wrap(base64.b64encode(_REAL_PEM.encode()).decode(), 64))
    assert "\n" in encoded
    assert _settings(private_key=encoded).JWT_PRIVATE_KEY_PEM == _REAL_PEM


def test_base64_of_a_crlf_pem_is_accepted() -> None:
    """openssl on Windows writes CRLF, so the base64 a developer produces there decodes
    to a CRLF PEM. It is still a PEM and must not be rejected."""
    crlf_pem = _REAL_PEM.replace("\n", "\r\n")
    encoded = base64.b64encode(crlf_pem.encode()).decode()
    assert "-----BEGIN PUBLIC KEY-----" in _settings(private_key=encoded).JWT_PRIVATE_KEY_PEM


def test_single_line_pem_with_literal_backslash_n_is_normalised() -> None:
    """A PEM pasted as one line with literal \\n escapes is PEM-shaped, so it would slip
    past a structural check and then fail deep inside the key parser instead."""
    escaped = _REAL_PEM.replace("\n", "\\n")
    assert "\n" not in escaped
    assert _settings(private_key=escaped).JWT_PRIVATE_KEY_PEM == _REAL_PEM


# --- rejected, with the field named ---------------------------------------------------


def test_value_that_is_neither_pem_nor_base64_is_rejected_naming_the_field() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(private_key="!!! not pem and not base64 !!!")
    message = str(exc_info.value)
    assert "JWT_PRIVATE_KEY_PEM" in message
    assert "neither a raw PEM block nor valid base64" in message


def test_valid_base64_that_is_not_a_pem_is_rejected_naming_the_field() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(private_key=base64.b64encode(b"just some bytes").decode())
    message = str(exc_info.value)
    assert "JWT_PRIVATE_KEY_PEM" in message
    assert "does not contain a PEM block once decoded" in message


def test_empty_value_is_rejected() -> None:
    """`JWT_PRIVATE_KEY_PEM=` in .env is an empty string, not a missing variable, so
    pydantic's required-field check cannot catch it -- copying .env.example verbatim
    lands here."""
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(private_key="   ")
    message = str(exc_info.value)
    assert "JWT_PRIVATE_KEY_PEM" in message
    assert "set but empty" in message


def test_the_failing_field_is_identified_specifically_not_generically() -> None:
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(public_key="!!! not a key !!!")
    message = str(exc_info.value)
    assert "JWT_PUBLIC_KEY_PEM" in message
    assert "JWT_PRIVATE_KEY_PEM" not in message


def test_blank_reset_code_pepper_is_rejected() -> None:
    """Covers config.py's `_reject_blank_pepper`. An empty HMAC key is not a weak key, it
    is no key, so this must fail closed rather than quietly produce unkeyed digests
    (P1-ADR-07). Same empty-string-is-not-a-missing-variable trap as the JWT keys."""
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(pepper="   ")
    message = str(exc_info.value)
    assert "RESET_CODE_PEPPER" in message
    assert "set but empty" in message


def test_error_never_echoes_the_key_material() -> None:
    """Error strings reach logs; §6.5 forbids key material there. Only the length is
    reported, so a malformed *private* key cannot leak via a startup error."""
    secret_ish = base64.b64encode(b"SUPERSECRETKEYBODY-do-not-log-me").decode()
    with pytest.raises(ConfigurationError) as exc_info:
        _settings(private_key=secret_ish)
    message = str(exc_info.value)
    assert "SUPERSECRETKEYBODY" not in message
    assert secret_ish not in message
