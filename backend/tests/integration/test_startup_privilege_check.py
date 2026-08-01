"""Spec 4.7/6.5: the app must refuse to start against a superuser or BYPASSRLS
connection, because RLS is silently bypassed for either -- see
app.database.assert_connection_is_not_privileged. This is exercised through the real
FastAPI lifespan (app.router.lifespan_context), not by calling the helper directly, so
these tests fail if the lifespan wiring in app/main.py is ever removed, not just if the
check itself is deleted.
"""

import pytest

from app.config import settings
from app.main import create_app


async def test_app_fails_to_start_when_connection_role_is_privileged(
    monkeypatch: pytest.MonkeyPatch, superuser_database_url: str
) -> None:
    monkeypatch.setattr(settings, "DATABASE_URL", superuser_database_url)
    app = create_app()

    with pytest.raises(RuntimeError, match="superuser or BYPASSRLS"):
        async with app.router.lifespan_context(app):
            pass


async def test_app_fails_to_start_when_connection_role_can_create_in_schema(
    monkeypatch: pytest.MonkeyPatch, migrator_database_url: str
) -> None:
    """A.5 item 1: DATABASE_URL must never resolve to gymak_migrator, whether by a
    misconfigured .env or any other mixup -- that role can CREATE in schema public, and
    therefore ALTER TABLE or DROP POLICY on its own tables, the exact self-revocable
    barrier the role split exists to close. See app.database.assert_connection_is_not_
    privileged's CREATE check, added alongside the existing superuser/BYPASSRLS one.
    """
    monkeypatch.setattr(settings, "DATABASE_URL", migrator_database_url)
    app = create_app()

    with pytest.raises(RuntimeError, match="CREATE objects in schema"):
        async with app.router.lifespan_context(app):
            pass


async def test_app_starts_when_connection_role_is_not_privileged() -> None:
    # Uses the suite's normal settings.DATABASE_URL, which is already the unprivileged
    # gymak_app role provisioned in conftest.pytest_configure.
    app = create_app()

    async with app.router.lifespan_context(app):
        pass
