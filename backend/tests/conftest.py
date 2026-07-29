from __future__ import annotations

import os
from collections.abc import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from testcontainers.community.postgres import PostgresContainer

# Dummy, non-functional values so pydantic-settings' required fields (Settings() fails
# fast on anything genuinely missing) are satisfied in tests. Nothing in T-01 parses these;
# they exist only so config.py can load. Real secrets are never committed (see .env.example).
_REQUIRED_TEST_ENV = {
    "ENV": "test",
    "JWT_PRIVATE_KEY_PEM": (
        "-----BEGIN PRIVATE KEY-----\ntest-key-not-a-real-secret\n-----END PRIVATE KEY-----\n"
    ),
    "JWT_PUBLIC_KEY_PEM": (
        "-----BEGIN PUBLIC KEY-----\ntest-key-not-a-real-secret\n-----END PUBLIC KEY-----\n"
    ),
    "FIREBASE_PROJECT_ID": "gymak-2d4ab-test",
    "FIREBASE_CREDENTIALS_JSON": '{"type": "service_account", "project_id": "gymak-2d4ab-test"}',
    "EMAIL_BACKEND": "console",
}

_container: PostgresContainer | None = None


def _as_asyncpg_url(raw_url: str) -> str:
    """testcontainers defaults to a sync driver in its connection URL; force asyncpg."""
    scheme, _, rest = raw_url.partition("://")
    base_scheme = scheme.split("+", 1)[0]
    return f"{base_scheme}+asyncpg://{rest}"


def pytest_configure(config: pytest.Config) -> None:
    """Runs before test modules are imported, so app.config sees every required var."""
    global _container
    for key, value in _REQUIRED_TEST_ENV.items():
        os.environ.setdefault(key, value)
    _container = PostgresContainer("postgres:16")
    _container.start()
    os.environ["DATABASE_URL"] = _as_asyncpg_url(_container.get_connection_url())


def pytest_unconfigure(config: pytest.Config) -> None:
    if _container is not None:
        _container.stop()


@pytest.fixture(scope="session")
def postgres_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client
