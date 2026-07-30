"""drop chk_credential_present for social placeholder accounts

Revision ID: 2b58d76b93fb
Revises: 6b18a9095bb4
Create Date: 2026-07-31 01:35:56.243451

T-06 / spec 5.4 step 5: a social sign-in with no usable email creates a user with
password_hash NULL and email_verified false, reachable only through its linked
user_identities row. T-02's chk_credential_present --
"password_hash IS NOT NULL OR email_verified = true" -- rejects exactly that row,
because it was written before social sign-in existed and assumed a password and a
verified email were the only two ways into an account.

The real invariant is now three-way: password, OR verified email, OR a linked social
identity. Postgres CHECK constraints cannot reference another table, so it cannot be
expressed as one CHECK on users alone -- and encoding only the first two, as before,
would make a row that is genuinely orphaned (no password, no verified email, no
identity, created by a bug rather than social sign-in) indistinguishable at the
database level from the legitimate third case this migration exists to allow. Dropped
rather than narrowed, for the same reason migration 6b18a9095bb4 added a second policy
instead of leaving the first one silently wrong: a check that looks protective but
lets through exactly what it names is worse than no check. The guarantee moves to
app/services/social_service.py, which always inserts the users row and its
user_identities row in the same transaction and rolls both back together if either
fails.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b58d76b93fb"
down_revision: str | None = "6b18a9095bb4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE users DROP CONSTRAINT chk_credential_present")


def downgrade() -> None:
    # Reversible only while no row currently violates the original rule -- a live
    # password_hash-NULL, email_verified-false user (i.e. any placeholder-email social
    # account created after this migration ran) will make this ALTER TABLE fail, same
    # as any other downgrade across a constraint that real data has since relied on.
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT chk_credential_present "
        "CHECK (password_hash IS NOT NULL OR email_verified = true)"
    )
