from __future__ import annotations

import base64
import binascii
from functools import lru_cache
from typing import Literal

from pydantic import ValidationInfo, field_validator, model_validator
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


class Settings(BaseSettings):
    """Every variable in Appendix A.1. Missing required values fail Settings() at import time."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

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
    FIREBASE_CREDENTIALS_JSON: str

    EMAIL_BACKEND: Literal["console", "http"] = "console"
    EMAIL_API_KEY: str | None = None
    EMAIL_FROM: str = "Gymak <no-reply@gymak.fitness>"

    REDIS_URL: str | None = None

    CORS_ORIGINS: str = "http://localhost:8081,http://localhost:19006"
    LOG_LEVEL: str = "INFO"

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
    def _enforce_cross_field_rules(self) -> Settings:
        # Spec 6.1: the reduced Argon2 cost exists only to keep the test suite fast,
        # and must never be reachable outside ENV=test.
        if self.ENV == "test":
            self.ARGON2_MEMORY_KIB = 8192
            self.ARGON2_TIME_COST = 1
        if self.EMAIL_BACKEND == "http" and not self.EMAIL_API_KEY:
            raise ValueError("EMAIL_API_KEY is required when EMAIL_BACKEND=http")
        return self

    @property
    def cors_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    # Required fields have no default because pydantic-settings sources them from the
    # environment/.env at runtime, which mypy cannot see from this zero-argument call.
    return Settings()  # type: ignore[call-arg]


settings = get_settings()
