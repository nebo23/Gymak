from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
