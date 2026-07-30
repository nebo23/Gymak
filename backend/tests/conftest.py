from __future__ import annotations

import asyncio
import base64
import os
import secrets
from collections.abc import AsyncGenerator

import asyncpg
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.community.postgres import PostgresContainer


def _generate_ed25519_pem_pair() -> tuple[str, str]:
    """A real, freshly generated Ed25519 keypair for the suite.

    T-01 could get away with PEM-*shaped* placeholders because nothing parsed them. T-03
    signs and verifies with these, so they must be genuine keys. Generated per run rather
    than committed: §6.5 forbids a private key in the repository, and a per-run key also
    means no test can accidentally depend on a fixed `kid` or signature.

    The private half is handed over base64-wrapped and the public half as raw PEM, so the
    suite exercises *both* branches of config.py's `_normalise_pem` the way real deployments
    do -- backend/.env supplies both keys base64-encoded (Appendix A.1 permits it).
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ed25519

    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_pem = (
        private_key.public_key()
        .public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode()
    )
    return base64.b64encode(private_pem.encode()).decode(), public_pem


_TEST_PRIVATE_KEY_PEM_B64, _TEST_PUBLIC_KEY_PEM = _generate_ed25519_pem_pair()

# Values so pydantic-settings' required fields (Settings() fails fast on anything genuinely
# missing) are satisfied in tests. Real secrets are never committed (see .env.example).
_REQUIRED_TEST_ENV = {
    "ENV": "test",
    "JWT_PRIVATE_KEY_PEM": _TEST_PRIVATE_KEY_PEM_B64,
    "JWT_PUBLIC_KEY_PEM": _TEST_PUBLIC_KEY_PEM,
    # P1-ADR-07: required, no default, so the suite cannot even import app.config without
    # it. Throwaway and per-run; a pepper is a secret and none is committed.
    "RESET_CODE_PEPPER": secrets.token_urlsafe(32),
    "FIREBASE_PROJECT_ID": "gymak-2d4ab-test",
    "FIREBASE_CREDENTIALS_JSON": '{"type": "service_account", "project_id": "gymak-2d4ab-test"}',
    "EMAIL_BACKEND": "console",
}

# The role the app connects as everywhere -- name matches .env.example's DATABASE_URL so
# behaviour under test matches behaviour outside it. Deliberately NOT the testcontainers
# bootstrap role, which is always a Postgres superuser (it is the initdb-created role for
# a fresh cluster) -- a passing RLS test under a superuser connection would be a false
# guarantee, since RLS is bypassed for superusers and BYPASSRLS roles regardless of policy.
_APP_ROLE = "gymak_app"
_APP_ROLE_PASSWORD = "gymak_app_test_password"  # noqa: S105 -- throwaway, ephemeral container only

_container: PostgresContainer | None = None


async def _provision_app_role(
    host: str, port: int, superuser: str, superuser_password: str, dbname: str
) -> None:
    """Create the dedicated non-superuser role migrations and the app both connect as.

    NOSUPERUSER and NOBYPASSRLS are the two attributes that matter: either one bypasses
    RLS entirely regardless of policy. GRANT ALL on the database and public schema (not
    superuser, not BYPASSRLS) is enough privilege to run the migration -- verified
    empirically against a real container, including CREATE EXTENSION citext, which is a
    "trusted" extension installable by a sufficiently-privileged non-superuser on
    Postgres 13+.
    """
    conn = await asyncpg.connect(
        host=host, port=port, user=superuser, password=superuser_password, database=dbname
    )
    try:
        await conn.execute(
            f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_ROLE_PASSWORD}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        )
        await conn.execute(f"GRANT ALL PRIVILEGES ON DATABASE {dbname} TO {_APP_ROLE}")
        await conn.execute(f"GRANT ALL PRIVILEGES ON SCHEMA public TO {_APP_ROLE}")
    finally:
        await conn.close()


def _run_migrations_to_head() -> None:
    from alembic.config import Config

    from alembic import command

    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(backend_dir, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    command.upgrade(cfg, "head")


def pytest_configure(config: pytest.Config) -> None:
    """Runs before test modules are imported, so app.config sees every required var."""
    global _container
    for key, value in _REQUIRED_TEST_ENV.items():
        os.environ.setdefault(key, value)

    _container = PostgresContainer("postgres:16")
    _container.start()

    host = _container.get_container_host_ip()
    port = int(_container.get_exposed_port(5432))
    dbname = _container.dbname
    asyncio.run(
        _provision_app_role(
            host=host,
            port=port,
            superuser=_container.username,
            superuser_password=_container.password,
            dbname=dbname,
        )
    )

    os.environ["DATABASE_URL"] = (
        f"postgresql+asyncpg://{_APP_ROLE}:{_APP_ROLE_PASSWORD}@{host}:{port}/{dbname}"
    )

    _run_migrations_to_head()


def pytest_unconfigure(config: pytest.Config) -> None:
    if _container is not None:
        _container.stop()


@pytest.fixture(scope="session")
def postgres_url() -> str:
    return os.environ["DATABASE_URL"]


@pytest.fixture(scope="session")
def superuser_database_url() -> str:
    """A DATABASE_URL for the same database, authenticated as the testcontainer's
    bootstrap superuser role -- the role app/database.py's
    assert_connection_is_not_privileged must refuse to start against. Used only by the
    startup privilege-check tests; every other fixture and test connects as the
    unprivileged `_APP_ROLE` (see the module docstring above `_provision_app_role`).
    """
    assert _container is not None
    host = _container.get_container_host_ip()
    port = int(_container.get_exposed_port(5432))
    return (
        f"postgresql+asyncpg://{_container.username}:{_container.password}"
        f"@{host}:{port}/{_container.dbname}"
    )


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import create_app

    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as async_client:
        yield async_client


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A fresh session per test. Nothing is ever committed here -- session.close() (the
    async context manager's exit) rolls back whatever the test flushed, so tests never
    need unique data to stay isolated from each other, including after an expected
    constraint violation leaves the transaction aborted.
    """
    from app.database import async_session_factory

    async with async_session_factory() as session:
        yield session
