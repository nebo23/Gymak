"""users credential present enforced by deferred constraint trigger (A.5 item 14)

Revision ID: ae026cea6d8d
Revises: 737d03a7c353
Create Date: 2026-08-01 03:26:17.389835

T-06 dropped chk_credential_present (migration 2b58d76b93fb) because a CHECK constraint
cannot reference another table, and the real invariant is three-way: password_hash IS
NOT NULL, OR email_verified = true, OR the user has a linked user_identities row (§5.4
step 5's placeholder-email social account). The guarantee moved entirely into
social_service.py inserting both rows in one transaction -- a convention, not a barrier
the database enforces, and A.5 item 14 flagged that as the kind of guarantee that should
not live only in application code.

It could not be revisited before now for a concrete reason: gymak_app both owned this
table and served the application, so any trigger enforcing this would have been exactly
as self-revocable as the FORCE ROW LEVEL SECURITY problem migration 737d03a7c353 (the
previous revision) closes -- gymak_app could simply DROP TRIGGER on its own table.
Now that gymak_migrator owns users and gymak_app holds DML only, this becomes a real
barrier: gymak_app cannot alter or drop it (see tests/security/test_rls.py).

A CHECK constraint permitting the '@social.gymak.local' placeholder domain was the other
option considered, and is NOT what this migration does. Trade-off: a CHECK is simpler
DDL, but only narrows the check by shape (any row whose email happens to match that
suffix passes, whether or not it actually has a linked identity) -- it cannot verify the
one thing that actually matters, because CHECK constraints still cannot see across
tables. A trigger can, and can therefore enforce the real invariant precisely instead of
a proxy for it.

DEFERRABLE INITIALLY DEFERRED, not an immediate AFTER trigger: social_service.py inserts
the users row, then the user_identities row, in the same transaction, and the user row
alone is genuinely invalid between those two statements. An immediate trigger would fire
-- and fail -- on the first INSERT, before the identity insert ever runs. Deferring to
COMMIT lets the transaction finish inserting both rows first, exactly matching how
Postgres's own deferrable FOREIGN KEY constraints behave, and exactly what §5.4 step 5's
"insert both in one transaction" already assumes is safe.

Scoped to `AFTER INSERT OR UPDATE OF password_hash, email_verified` rather than every
UPDATE on users: last_login_at and token_version are updated far more often than either
of those two columns, and neither can affect this invariant, so there is no reason to
evaluate it on writes that cannot violate it.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ae026cea6d8d"
down_revision: str | None = "737d03a7c353"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION chk_credential_present_at_commit() RETURNS trigger AS $$
        BEGIN
            IF NEW.password_hash IS NULL
               AND NEW.email_verified = false
               AND NOT EXISTS (
                   SELECT 1 FROM user_identities WHERE user_id = NEW.id
               )
            THEN
                RAISE EXCEPTION
                    'users.id=% has no password, no verified email, and no linked '
                    'identity (A.5 item 14)', NEW.id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE CONSTRAINT TRIGGER trg_users_credential_present "
        "AFTER INSERT OR UPDATE OF password_hash, email_verified ON users "
        "DEFERRABLE INITIALLY DEFERRED "
        "FOR EACH ROW EXECUTE FUNCTION chk_credential_present_at_commit()"
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_users_credential_present ON users")
    op.execute("DROP FUNCTION IF EXISTS chk_credential_present_at_commit()")
