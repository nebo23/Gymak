"""split gymak_migrator and gymak_app roles (A.5 items 1, 11, answers §13.2 item 8)

Revision ID: 737d03a7c353
Revises: 2b58d76b93fb
Create Date: 2026-08-01 03:26:16.879312

A.5 item 1: before this migration, gymak_app both ran every prior migration and served
the application, so it OWNED all six tables -- and table ownership grants full ALTER/DROP
regardless of any GRANT/REVOKE. It could DROP POLICY or ALTER TABLE ... NO FORCE on its
own tables, and could re-GRANT itself UPDATE/DELETE on audit_log even after migration
ba41f8eb5985 revoked them, because an owner can always re-grant on its own object. FORCE
ROW LEVEL SECURITY was real but self-revocable; the audit_log append-only guarantee had
the same problem through a different door.

From this migration onward, Alembic connects as gymak_migrator (see alembic/env.py,
app/config.py's MIGRATOR_DATABASE_URL) and gymak_app connects only as the application.
gymak_migrator therefore creates -- and owns -- every table from this point in the
migration chain forward, on any database built by running the full chain from scratch
(see backend/README.md's rebuild instructions; this migration does not attempt to
reassign ownership of tables an already-split-unaware gymak_app might still own on an
existing, un-rebuilt database, since gymak_migrator has no privilege to reassign
ownership of an object it does not already own -- only a superuser or the current owner
can do that. Rebuilding from an empty database is the supported path).

What this migration does NOT do, and why: it does not touch schema- or database-level
privileges (CREATE/USAGE on schema public, CONNECT/CREATE on the database). Those are
owned by the cluster's bootstrap superuser (e.g. `postgres`), not by gymak_migrator or
gymak_app, so neither role has authority to GRANT or REVOKE at that level -- attempting
it here would just fail. That one-time provisioning step lives outside Alembic, in
environment setup: tests/conftest.py for the test suite, and backend/README.md's local
setup for a real database. This migration only does what gymak_migrator, as the new
owner of these six tables, actually has authority over: table-level DML grants to
gymak_app. That is also why it belongs in Alembic rather than one-off provisioning --
it is versioned schema, and changes if Phase 2 adds a table.

Grants below are scoped to what each repository module (app/repositories/*.py) actually
executes today, not "everything a table could need":
  - users: SELECT, INSERT, UPDATE (user_repo, auth_service -- password rehash,
    last_login_at, token_version). No DELETE: accounts are soft-deleted via UPDATE.
  - user_identities: SELECT, INSERT only (identity_repo). Never updated or deleted.
  - profiles: SELECT, INSERT, UPDATE (profile_repo). Never deleted directly.
  - refresh_tokens: SELECT, INSERT, UPDATE (token_repo -- consumed_at/revoked_at are
    set, rows are never deleted).
  - password_reset_codes: SELECT, INSERT, UPDATE, DELETE -- the one table that needs
    DELETE: reset_repo.redeem_reset_token spends the 5-minute reset token with a real
    `DELETE ... RETURNING`, not an UPDATE flag.
  - audit_log: unchanged. Already INSERT/SELECT-only from ba41f8eb5985; this migration
    does not re-touch it, but it is retroactively less revocable purely from the
    ownership transfer above, since gymak_app can no longer grant itself UPDATE/DELETE
    back the way an owning role could.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "737d03a7c353"
down_revision: str | None = "2b58d76b93fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "gymak_app"

_GRANTS: dict[str, str] = {
    "users": "SELECT, INSERT, UPDATE",
    "user_identities": "SELECT, INSERT",
    "profiles": "SELECT, INSERT, UPDATE",
    "refresh_tokens": "SELECT, INSERT, UPDATE",
    "password_reset_codes": "SELECT, INSERT, UPDATE, DELETE",
}


def upgrade() -> None:
    for table, privileges in _GRANTS.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table, privileges in _GRANTS.items():
        op.execute(f"REVOKE {privileges} ON {table} FROM {APP_ROLE}")
