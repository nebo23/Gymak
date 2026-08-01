from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Any, Literal

from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from pydantic import ValidationError, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_PEM_BEGIN = "-----BEGIN "
_PEM_END = "-----END "


class ConfigurationError(Exception):
    """A malformed secret-bearing setting, raised so startup fails with a clear message.

    Deliberately **not** a ValueError. Pydantic collects ValueError from a validator into
    a ValidationError whose string form appends `input_value='...'` -- and since a bad key
    crashes the process, that string is exactly what lands in stdout and the crash log.
    For `JWT_PRIVATE_KEY_PEM` that would write private key material to the logs, which
    spec §6.5 forbids. A non-ValueError propagates out of the validator untouched, so the
    message below is the entire message. Verified against pydantic, not assumed.
    """


def _looks_like_pem(text: str) -> bool:
    return _PEM_BEGIN in text and _PEM_END in text


def _normalise_pem(raw: str, field_name: str) -> str:
    """Accept a raw PEM block or that same PEM base64-encoded (Appendix A.1 permits both,
    since a multiline value is awkward in a .env file).

    Fails with a message naming the field rather than letting a malformed key reach
    `cryptography` and surface as an unattributed stack trace at first token sign --
    by which point the process is already serving traffic.

    Never interpolates the value into an error: this is private key material, and error
    strings reach logs. Only its length is reported.
    """
    value = raw.strip()
    if not value:
        raise ConfigurationError(
            f"{field_name} is set but empty. It is required. Note that copying "
            f".env.example verbatim leaves it blank, which is an empty string rather "
            f"than a missing variable, so pydantic's required-field check cannot catch "
            f"it. Generate an Ed25519 pair with: "
            f"openssl genpkey -algorithm ed25519 -out jwt_private.pem && "
            f"openssl pkey -in jwt_private.pem -pubout -out jwt_public.pem"
        )

    # A PEM pasted into .env as a single line with literal backslash-n escapes. This is
    # structurally PEM-shaped, so it would pass the check below and then fail deep inside
    # the key parser -- exactly the unattributed failure this function exists to prevent.
    if _PEM_BEGIN in value and "\n" not in value and "\\n" in value:
        value = value.replace("\\n", "\n")

    if _looks_like_pem(value):
        return value if value.endswith("\n") else value + "\n"

    try:
        decoded = base64.b64decode(value, validate=False).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ConfigurationError(
            f"{field_name} is neither a raw PEM block nor valid base64. Expected either "
            f"a PEM starting '{_PEM_BEGIN}', or that PEM base64-encoded. Got "
            f"{len(value)} characters that decode as neither ({type(exc).__name__})."
        ) from exc

    if not _looks_like_pem(decoded):
        raise ConfigurationError(
            f"{field_name} is valid base64, but does not contain a PEM block once "
            f"decoded -- expected '{_PEM_BEGIN}...' inside it. Check that the value is "
            f"base64 of the whole PEM file, not of the key body alone, and that it is "
            f"not double-encoded. Decoded to {len(decoded)} characters."
        )

    return decoded if decoded.endswith("\n") else decoded + "\n"


def _parse_private_key_or_fail(pem: str, field_name: str) -> None:
    """A.5 item 3: `_normalise_pem` above only checks PEM *shape* -- '-----BEGIN '/'
    -----END ' markers -- so a structurally valid PEM whose body is truncated, corrupted,
    or simply the wrong key type for EdDSA (P1-ADR-02) passed startup and only broke the
    first time `security.py` called `jwt.encode`. Parsing for real here moves that
    failure to startup, where §6.3 says it belongs.

    Never interpolates the key or the parse error's own message into the raised error --
    only the exception's type name -- for the same reason `_normalise_pem` never echoes
    the value: this is private key material, and error strings reach logs (§6.5).
    """
    try:
        key = load_pem_private_key(pem.encode("utf-8"), password=None)
    except (ValueError, TypeError, UnsupportedAlgorithm) as exc:
        raise ConfigurationError(
            f"{field_name} is a structurally valid PEM block but could not be parsed as "
            f"a private key ({type(exc).__name__}). Generate an Ed25519 pair with: "
            f"openssl genpkey -algorithm ed25519 -out jwt_private.pem"
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ConfigurationError(
            f"{field_name} parses as a valid private key, but is not Ed25519. P1-ADR-02 "
            f"requires EdDSA over Ed25519; got {type(key).__name__}."
        )


def _parse_public_key_or_fail(pem: str, field_name: str) -> None:
    """The public-key counterpart of `_parse_private_key_or_fail` -- see its docstring."""
    try:
        key = load_pem_public_key(pem.encode("utf-8"))
    except (ValueError, UnsupportedAlgorithm) as exc:
        raise ConfigurationError(
            f"{field_name} is a structurally valid PEM block but could not be parsed as "
            f"a public key ({type(exc).__name__})."
        ) from exc
    if not isinstance(key, Ed25519PublicKey):
        raise ConfigurationError(
            f"{field_name} parses as a valid public key, but is not Ed25519. P1-ADR-02 "
            f"requires EdDSA over Ed25519; got {type(key).__name__}."
        )


class Settings(BaseSettings):
    """Every variable in Appendix A.1. Missing required values fail Settings() at import time."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    def __init__(self, **values: Any) -> None:
        """Construction is the one place every field in Appendix A.1 converges, so it is
        also the one place a leak-safe rewrite protects every field -- present and
        future -- rather than needing a bespoke validator each time a new secret is
        added.

        A field that is simply absent never reaches a field_validator: there is no value
        to validate, so `_accept_raw_or_base64_pem` and `_reject_blank_pepper` below
        never run, and pydantic raises its own ValidationError instead. That error's
        `errors()` entry for a `missing` field carries `input` set to the *entire*
        mapping passed to Settings() -- every other field, secrets included -- because
        there is no single offending value to report in its place. Whether
        JWT_PRIVATE_KEY_PEM or RESET_CODE_PEPPER happens to fall inside that dump then
        depends only on which other field is missing and the declared field order, and
        on where pydantic's own repr truncation lands -- not a control. Verified against
        pydantic 2.13, not assumed: see test_config.py.

        `errors(include_input=False, include_context=False)` is used rather than reading
        `.errors()` and simply not touching `input` -- so a later edit that carelessly
        adds `error["input"]` to the message below hits a KeyError instead of a leak.

        Re-raised after this handler exits, not with `from None` alone: `from None` only
        suppresses the chain from *display* (traceback, logging), but the original
        ValidationError -- and the secrets it carries -- remains reachable via
        `__context__` for any caller that inspects it directly. Building the replacement
        inside the handler and raising it once control has left the `except` block
        leaves `__context__` genuinely `None`, not merely hidden.
        """
        configuration_error: ConfigurationError | None = None
        try:
            super().__init__(**values)
        except ValidationError as exc:
            field_names = sorted(
                {
                    ".".join(str(part) for part in error["loc"]) or "<root>"
                    for error in exc.errors(include_input=False, include_context=False)
                }
            )
            configuration_error = ConfigurationError(
                "Settings failed to construct because of a problem with: "
                + ", ".join(field_names)
                + ". Check that every required variable in Appendix A.1 is set and "
                "well-formed. No value is included in this message, deliberately."
            )
        if configuration_error is not None:
            raise configuration_error

    ENV: Literal["development", "test", "staging", "production"] = "development"

    DATABASE_URL: str

    JWT_PRIVATE_KEY_PEM: str
    JWT_PUBLIC_KEY_PEM: str
    JWT_AUDIENCE: str = "gymak-app"

    ACCESS_TOKEN_TTL_SECONDS: int = 900
    REFRESH_TOKEN_TTL_SECONDS: int = 5_184_000
    RESET_CODE_TTL_SECONDS: int = 600
    RESET_TOKEN_TTL_SECONDS: int = 300

    # P1-ADR-07: the HMAC key for reset-code hashing. Required, no default, never written to
    # the database. A deployment missing it must fail to start rather than silently fall back
    # to an unkeyed hash -- read the ADR's "Which one carries it" row: the pepper is the
    # control that defeats offline recovery, so degrading it is not a partial loss of margin,
    # it is the whole barrier.
    RESET_CODE_PEPPER: str

    ARGON2_MEMORY_KIB: int = 65536
    ARGON2_TIME_COST: int = 3
    ARGON2_PARALLELISM: int = 4

    FIREBASE_PROJECT_ID: str = "gymak-2d4ab"

    # A.5 item 15: optional, not required. app.integrations.firebase used to be imported
    # -- and initialised -- as a side effect of importing app.main, which made this field
    # a hidden hard requirement for anything that merely imports the app (uvicorn,
    # scripts/export_openapi.py, any test). Firebase init now happens in main.py's
    # lifespan handler instead, so the app can start (and social sign-in alone is
    # unavailable) without it. `None` and "set but blank" are treated the same --
    # copying .env.example verbatim leaves this blank, and a blank string is not
    # meaningfully different from an absent one here.
    FIREBASE_CREDENTIALS_JSON: str | None = None

    EMAIL_BACKEND: Literal["console", "http"] = "console"
    EMAIL_API_KEY: str | None = None
    EMAIL_FROM: str = "Gymak <no-reply@gymak.fitness>"

    REDIS_URL: str | None = None

    CORS_ORIGINS: str = "http://localhost:8081,http://localhost:19006"
    LOG_LEVEL: str = "INFO"

    @field_validator("FIREBASE_CREDENTIALS_JSON", mode="after")
    @classmethod
    def _blank_firebase_credentials_is_absent(cls, value: str | None) -> str | None:
        """`FIREBASE_CREDENTIALS_JSON=` in .env is an empty string, not a missing
        variable -- the same trap the JWT keys and the pepper guard against elsewhere in
        this file. Collapsing it to None here means every downstream consumer (today,
        just app.integrations.firebase) has exactly one "not configured" value to check,
        rather than two.
        """
        if value is not None and not value.strip():
            return None
        return value

    @field_validator("RESET_CODE_PEPPER", mode="after")
    @classmethod
    def _reject_blank_pepper(cls, value: str) -> str:
        """`RESET_CODE_PEPPER=` in .env is an empty string, not a missing variable, so the
        required-field check above cannot catch it -- and copying .env.example verbatim
        lands exactly there. An empty HMAC key is not a weak key, it is no key: every
        digest becomes computable by anyone holding the table, which is the one outcome
        P1-ADR-07 exists to make impossible.

        ConfigurationError, not ValueError, for the reason in that class's docstring: the
        pepper is secret material, and pydantic's ValidationError string appends
        `input_value='...'` straight into the crash log.
        """
        if not value.strip():
            raise ConfigurationError(
                "RESET_CODE_PEPPER is set but empty. It is required (P1-ADR-07) and has no "
                "default: an empty key makes reset-code hashing unkeyed, so anyone able to "
                "read password_reset_codes could recover every outstanding code offline. "
                'Generate one with: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )
        return value

    @field_validator("JWT_PRIVATE_KEY_PEM", "JWT_PUBLIC_KEY_PEM", mode="after")
    @classmethod
    def _accept_raw_or_base64_pem(cls, value: str, info: ValidationInfo) -> str:
        # Normalised here, at load time, so every consumer downstream receives a raw PEM
        # and no module has to re-implement the base64 question.
        return _normalise_pem(value, info.field_name or "JWT key")

    @model_validator(mode="after")
    def _parse_jwt_keys_for_real(self) -> Settings:
        # Runs after _accept_raw_or_base64_pem (a field_validator, which always completes
        # before any model_validator(mode="after") regardless of declaration order), so
        # both fields are already normalised to raw PEM here -- A.5 item 3.
        _parse_private_key_or_fail(self.JWT_PRIVATE_KEY_PEM, "JWT_PRIVATE_KEY_PEM")
        _parse_public_key_or_fail(self.JWT_PUBLIC_KEY_PEM, "JWT_PUBLIC_KEY_PEM")
        return self

    @model_validator(mode="after")
    def _enforce_cross_field_rules(self) -> Settings:
        # Spec 6.1: the reduced Argon2 cost exists only to keep the test suite fast,
        # and must never be reachable outside ENV=test.
        if self.ENV == "test":
            self.ARGON2_MEMORY_KIB = 8192
            self.ARGON2_TIME_COST = 1
        if self.EMAIL_BACKEND == "http" and not self.EMAIL_API_KEY:
            # ConfigurationError, not ValueError, for the same reason as the field
            # validators above and __init__'s handler: this is a model_validator, so a
            # ValueError here would be collected into a ValidationError whose errors()
            # embeds every other field supplied to Settings() -- JWT_PRIVATE_KEY_PEM and
            # RESET_CODE_PEPPER included -- as `input` on the resulting error entry.
            raise ConfigurationError("EMAIL_API_KEY is required when EMAIL_BACKEND=http")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
