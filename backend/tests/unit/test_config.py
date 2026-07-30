"""Appendix A.1 permits the JWT keys to be supplied as raw PEM or as base64-wrapped PEM
("base64 if multiline is awkward"). config.py normalises both at load time; these tests
pin both accepted paths and every rejection, including that the rejection names the field
and never echoes the key material.
"""

from __future__ import annotations

import base64
import textwrap

import pytest
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict

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
    """Identical to Settings -- every field and both validators are inherited -- but reads
    from constructor kwargs only.

    `env_file=None` alone disables just the *dotenv* source; pydantic-settings still
    consults `os.environ` as a separate, higher-priority source regardless of env_file, so
    on its own it does nothing about a value already sitting in the process environment.
    Under the real suite, conftest.py's `pytest_configure` seeds `os.environ` with every
    required variable -- including a real `DATABASE_URL` pointing at the test container --
    before any test module is imported. A test that only omitted a field from its kwargs
    was therefore still getting that field from the environment: the field was never
    actually missing, `Settings()` constructed successfully, and a test asserting
    `pytest.raises(ConfigurationError)` failed with "DID NOT RAISE" -- passing only under
    `--noconftest`, which is the one invocation where that seeding never happens (verified;
    this is not hypothetical -- see the two tests below).

    `settings_customise_sources` drops the env and dotenv sources entirely, so omitting a
    kwarg here means the field is genuinely absent from every source Settings() would
    consult, regardless of what conftest.py, a real backend/.env, or the developer's own
    shell happens to have set.
    """

    model_config = SettingsConfigDict(env_file=None, extra="ignore")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings,)


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


# --- the Settings() construction boundary: a *missing* field must not leak either ------
#
# Unlike the cases above, a field that is simply absent never reaches a field_validator
# -- there is no value to run one on -- so none of the ConfigurationErrors above are what
# fires. Left alone, pydantic raises its own ValidationError, and that error's `errors()`
# entry for the missing field carries `input` set to the *entire* mapping passed to
# Settings(), not just the missing field: every other field supplied, secrets included.
# Whether a real key stayed out of that dump used to depend on which other field was
# missing and on pydantic's own truncation of a long repr in str() -- an accident of
# field order and string length, not a control.


def test_missing_field_alongside_a_real_key_does_not_leak_it() -> None:
    """JWT_PRIVATE_KEY_PEM and RESET_CODE_PEPPER are both present and well-formed;
    DATABASE_URL is the one omitted. Checks the exception *type*, not only message
    content: reordering the fields declared on Settings cannot turn this back into a raw
    ValidationError, so the test does not depend on today's field order to catch a
    regression. It also checks for the untruncated key material directly rather than for
    a truncated string, so it does not depend on pydantic's repr-truncation length either.
    """
    pepper = "super-secret-pepper-do-not-leak-me"
    with pytest.raises(ConfigurationError) as exc_info:
        _HermeticSettings(  # type: ignore[call-arg]
            JWT_PRIVATE_KEY_PEM=_REAL_PEM,
            JWT_PUBLIC_KEY_PEM=_REAL_PEM,
            RESET_CODE_PEPPER=pepper,
            FIREBASE_CREDENTIALS_JSON="{}",
            # DATABASE_URL deliberately omitted -- this is the field that is "missing".
        )
    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "BEGIN PUBLIC KEY" not in message
    assert "MmrT6Y" not in message  # the PEM body, present verbatim in _REAL_PEM
    assert pepper not in message


def test_missing_field_error_names_every_missing_field() -> None:
    """Two fields missing at once must both be named, not just the first one pydantic
    happens to report, or whoever reads the crash log fixes one problem and restarts
    into the next."""
    with pytest.raises(ConfigurationError) as exc_info:
        _HermeticSettings(  # type: ignore[call-arg]
            JWT_PRIVATE_KEY_PEM=_REAL_PEM, JWT_PUBLIC_KEY_PEM=_REAL_PEM
        )
    message = str(exc_info.value)
    assert "DATABASE_URL" in message
    assert "RESET_CODE_PEPPER" in message
    assert "FIREBASE_CREDENTIALS_JSON" in message


def test_email_api_key_missing_under_http_backend_raises_configuration_error() -> None:
    """`_enforce_cross_field_rules` used to raise ValueError here, which pydantic
    collects into a ValidationError -- and, this being a model_validator that runs after
    every field, `errors()`'s `input` for that entry is the whole settings mapping, the
    same leak shape as the missing-field case above. ConfigurationError avoids it the
    same way the field validators do, and it is raised directly rather than routed
    through __init__'s handler."""
    with pytest.raises(ConfigurationError) as exc_info:
        _HermeticSettings(
            DATABASE_URL="postgresql+asyncpg://user:pass@localhost:5432/db",
            JWT_PRIVATE_KEY_PEM=_REAL_PEM,
            JWT_PUBLIC_KEY_PEM=_REAL_PEM,
            RESET_CODE_PEPPER="test-pepper-not-a-real-secret",
            FIREBASE_CREDENTIALS_JSON="{}",
            EMAIL_BACKEND="http",
            # EMAIL_API_KEY deliberately omitted while EMAIL_BACKEND=http.
        )
    message = str(exc_info.value)
    assert "EMAIL_API_KEY" in message
    assert "BEGIN PUBLIC KEY" not in message
