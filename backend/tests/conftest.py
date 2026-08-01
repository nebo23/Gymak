from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
from collections.abc import AsyncGenerator, Iterator

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


def _generate_fake_service_account_json(project_id: str) -> str:
    """A structurally valid, offline-only service-account credential.

    T-06's app/integrations/firebase.py initialises firebase-admin eagerly, at import,
    mirroring config.py's own "fail fast at import" posture for its other secrets. That
    means firebase_admin.credentials.Certificate() must be able to *parse* whatever
    FIREBASE_CREDENTIALS_JSON holds in every test run, even though -- per T-06 -- the
    suite mocks app.integrations.firebase.verify_id_token and never calls Firebase for
    real. A minimal placeholder (just type + project_id, as this used to be) is not
    enough: Certificate() validates the required fields (token_uri, client_email,
    private_key, ...) at construction time, entirely locally, no network involved --
    confirmed empirically against firebase-admin 7.5, not assumed. So this needs a real,
    freshly generated RSA key for the same reason conftest generates a real Ed25519 pair
    above: something has to actually parse as the shape it claims to be.
    """
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return json.dumps(
        {
            "type": "service_account",
            "project_id": project_id,
            "private_key_id": "test-key-id",
            "private_key": private_pem,
            "client_email": f"test@{project_id}.iam.gserviceaccount.com",
            "client_id": "000000000000000000000",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    )


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
    "FIREBASE_CREDENTIALS_JSON": _generate_fake_service_account_json("gymak-2d4ab-test"),
    "EMAIL_BACKEND": "console",
}

# A.5 item 1: two roles, not one. gymak_migrator owns the schema and runs Alembic;
# gymak_app is DML-only and serves the application -- name matches .env.example's
# DATABASE_URL so behaviour under test matches behaviour outside it. Neither is the
# testcontainers bootstrap role, which is always a Postgres superuser (it is the
# initdb-created role for a fresh cluster) -- a passing RLS test under a superuser
# connection would be a false guarantee, since RLS is bypassed for superusers and
# BYPASSRLS roles regardless of policy.
_MIGRATOR_ROLE = "gymak_migrator"
_MIGRATOR_ROLE_PASSWORD = "gymak_migrator_test_password"  # noqa: S105 -- throwaway, ephemeral
_APP_ROLE = "gymak_app"
_APP_ROLE_PASSWORD = "gymak_app_test_password"  # noqa: S105 -- throwaway, ephemeral container only

_container: PostgresContainer | None = None


async def _provision_roles(
    host: str, port: int, superuser: str, superuser_password: str, dbname: str
) -> None:
    """Create the two non-superuser roles the split (A.5 item 1) relies on.

    NOSUPERUSER and NOBYPASSRLS are the two attributes that matter for both roles:
    either one bypasses RLS entirely regardless of policy, which would make gymak_app's
    connection a false guarantee for every RLS test in tests/security/test_rls.py.

    gymak_migrator gets CONNECT + CREATE on the database and CREATE + USAGE on schema
    public -- the schema-level grant lets it create the six Phase 1 tables (and
    everything it subsequently owns), and CREATE on the *database* (not merely the
    schema) is specifically what CREATE EXTENSION citext checks for a non-superuser role
    installing a "trusted" extension on Postgres 13+ -- confirmed empirically against a
    real container: schema-only CREATE fails with "Must have CREATE privilege on
    current database to create this extension," which is not the error the previous,
    single-role version of this function's docstring assumed. See backend/README.md.

    gymak_app gets CONNECT on the database and USAGE (never CREATE) on schema public --
    no privilege to create anything, anywhere. Its actual data access -- SELECT/INSERT/
    UPDATE/DELETE on specific tables -- is granted by migration 737d03a7c353, not here,
    because by the time that migration runs, gymak_migrator (not this bootstrap
    superuser) owns those tables and is the only role with authority to grant on them.
    """
    conn = await asyncpg.connect(
        host=host, port=port, user=superuser, password=superuser_password, database=dbname
    )
    try:
        await conn.execute(
            f"CREATE ROLE {_MIGRATOR_ROLE} LOGIN PASSWORD '{_MIGRATOR_ROLE_PASSWORD}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        )
        await conn.execute(f"GRANT CONNECT, CREATE ON DATABASE {dbname} TO {_MIGRATOR_ROLE}")
        await conn.execute(f"GRANT CREATE, USAGE ON SCHEMA public TO {_MIGRATOR_ROLE}")

        await conn.execute(
            f"CREATE ROLE {_APP_ROLE} LOGIN PASSWORD '{_APP_ROLE_PASSWORD}' "
            "NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS"
        )
        await conn.execute(f"GRANT CONNECT ON DATABASE {dbname} TO {_APP_ROLE}")
        await conn.execute(f"GRANT USAGE ON SCHEMA public TO {_APP_ROLE}")
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
        _provision_roles(
            host=host,
            port=port,
            superuser=_container.username,
            superuser_password=_container.password,
            dbname=dbname,
        )
    )

    # Both settings are in place before app.config.Settings is ever constructed (that
    # first happens inside _run_migrations_to_head, when alembic/env.py imports it) --
    # so there is no mutate-after-construction hazard here, unlike DATABASE_URL alone
    # would have if it were flipped from one role to another after the fact.
    os.environ["MIGRATOR_DATABASE_URL"] = (
        f"postgresql+asyncpg://{_MIGRATOR_ROLE}:{_MIGRATOR_ROLE_PASSWORD}@{host}:{port}/{dbname}"
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
def migrator_database_url() -> str:
    """A DATABASE_URL authenticated as gymak_migrator -- the schema-owning, DDL-capable
    role Alembic connects as (see MIGRATOR_DATABASE_URL). Used only by
    tests/integration/test_startup_privilege_check.py, to prove the application refuses
    to start if DATABASE_URL is ever pointed at this role instead of the DML-only
    gymak_app -- the exact misconfiguration A.5 item 1 names as unacceptable ("the
    application must never be able to connect as the migrator").
    """
    assert _container is not None
    host = _container.get_container_host_ip()
    port = int(_container.get_exposed_port(5432))
    return (
        f"postgresql+asyncpg://{_MIGRATOR_ROLE}:{_MIGRATOR_ROLE_PASSWORD}"
        f"@{host}:{port}/{_container.dbname}"
    )


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


# §11.1's log-capture test needs every line the WHOLE suite printed, but pytest's own
# capsys buffer resets per test. tests/support.ALL_CAPTURED_OUTPUT accumulates it
# process-wide -- see that module for why the list lives there rather than here.
# structlog's PrintLogger writes with `print(message, file=None)`, which resolves to
# whatever `sys.stdout` is at call time (confirmed against the installed structlog
# version), i.e. exactly what capsys is already redirecting for every test.


@pytest.fixture(autouse=True)
def _accumulate_captured_output(capsys: pytest.CaptureFixture[str]) -> Iterator[None]:
    from tests.support import ALL_CAPTURED_OUTPUT

    yield
    captured = capsys.readouterr()
    if captured.out:
        ALL_CAPTURED_OUTPUT.extend(captured.out.splitlines())
    if captured.err:
        ALL_CAPTURED_OUTPUT.extend(captured.err.splitlines())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Pins tests/security/test_no_secret_logging.py's cases to run last.

    Nothing else in this suite depends on execution order, but that test's result
    would otherwise depend on how much of the suite happened to run before it in
    whatever order pytest collected -- "the whole suite" (§11.1) means all of it, so
    this makes that true regardless of collection order rather than by accident.
    """
    log_capture_items = [item for item in items if "test_no_secret_logging" in str(item.fspath)]
    if not log_capture_items:
        return
    other_items = [item for item in items if item not in log_capture_items]
    items[:] = other_items + log_capture_items
