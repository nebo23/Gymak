"""exercises: user-owned custom rows, with RLS

Owner-authorised departure from spec §1.2 ("Custom user-created exercises ... do not
build") and from P2-ADR-02's read-only library. Nothing else in §1.2 is opened up.

Shape: `exercises.user_id uuid NULL REFERENCES users(id) ON DELETE CASCADE`. NULL means
a seeded, public row; non-null means that user's own. The rejected alternative -- a
separate `user_exercises` table -- cannot work here, because `workout_sets.exercise_id`
and `program_exercises.exercise_id` both REFERENCE `exercises(id)` ON DELETE RESTRICT
(verified against the live schema before this migration was written, both still exactly
that). A custom exercise living in another table could not be logged against without a
second nullable FK or a union view on every read.

RLS: P2-ADR-09 named `exercises` as the deliberate no-RLS exception -- "public reference
data with no user_id". That exception dies the moment user-owned rows live here, so RLS
is enabled AND forced in this same migration, never as a follow-up.

Three policies, not one. A single `user_id IS NULL OR user_id = <app user>` policy would
be correct for reads and *wrong* for writes: its WITH CHECK would let any caller INSERT a
row with `user_id = NULL` -- that is, forge a row into the public seeded library visible
to every user. Reads admit both; writes admit only the caller's own rows. Note
`user_id = <expr>` is already NULL-safe: NULL = uuid evaluates to NULL, never true, so a
seeded row can never satisfy the write policies.

Privileges: INSERT and UPDATE are granted to the app role; DELETE deliberately is NOT.
Retiring a custom exercise uses the existing `is_active = false` soft delete (the same
mechanism P2-ADR-02 built for retiring seeded rows, which `get_by_id` already resolves
and `list_active` already hides), because ON DELETE RESTRICT means a custom exercise that
has been logged against cannot be hard-deleted anyway. Withholding the DELETE privilege
makes that a database-enforced guarantee rather than a convention, and keeps
`test_gymak_app_cannot_delete_exercises` true and meaningful.

`uq_exercises_slug` is left alone on purpose. Slug collisions between users are avoided
by generating custom slugs with a per-user prefix (see `exercise_repo.build_custom_slug`)
rather than by scoping the constraint to `(slug, user_id)`. Scoping it would have broken
two things: `UNIQUE (slug, user_id)` treats NULLs as distinct by default, so two seeded
rows could then share a slug; and `exercise_repo.list_active` paginates by keyset on
`slug > cursor` ORDER BY slug, whose no-skip/no-repeat guarantee depends on `slug` being
globally unique. The prefix preserves both invariants and touches neither.

Latent interaction, recorded rather than left to be discovered: ON DELETE CASCADE here
meets ON DELETE RESTRICT on `workout_sets.exercise_id`. Hard-deleting a user row would
try to cascade away their custom exercises while their sets may still reference them, and
Postgres does not guarantee an ordering that satisfies the RESTRICT. This is not
reachable today -- `auth_service.delete_account` is a soft delete (`users.deleted_at`),
and no purge job exists -- but whoever writes that purge must delete `workout_sets`
before `exercises`.

Revision ID: a1c9f2e4b703
Revises: 3acc66b027b7
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1c9f2e4b703"
down_revision: str | None = "3acc66b027b7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "gymak_app"
MIGRATOR_ROLE = "gymak_migrator"

# The same guard every other policy in this database uses (ba41f8eb5985, 88d15c15b877):
# NULLIF(..., '') so an unbound or empty app.user_id yields NULL rather than raising on
# the ::uuid cast, and `true` so current_setting does not error when the GUC is unset.
_APP_USER_ID_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def upgrade() -> None:
    op.add_column("exercises", sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "exercises_user_id_fkey",
        "exercises",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    # Partial: seeded rows are the overwhelming majority and all share user_id IS NULL,
    # which no query filters on selectively -- only the custom rows need locating by
    # owner, so only they are worth indexing.
    op.execute("CREATE INDEX ix_exercises_user_id ON exercises (user_id) WHERE user_id IS NOT NULL")

    op.execute("ALTER TABLE exercises ENABLE ROW LEVEL SECURITY")
    # FORCE, not just ENABLE: gymak_migrator owns this table, and Postgres exempts a
    # table's owner from its own policies by default -- the footgun ba41f8eb5985 and
    # 88d15c15b877 both documented.
    op.execute("ALTER TABLE exercises FORCE ROW LEVEL SECURITY")

    # Reads: the seeded library plus the caller's own rows, and nothing else.
    op.execute(
        "CREATE POLICY p_exercises_read ON exercises FOR SELECT "
        f"USING (user_id IS NULL OR user_id = {_APP_USER_ID_EXPR})"
    )
    # Writes: the caller's own rows only. A seeded row (user_id IS NULL) satisfies
    # neither, so it can be neither forged nor edited through the app role.
    op.execute(
        "CREATE POLICY p_exercises_own_insert ON exercises FOR INSERT "
        f"WITH CHECK (user_id = {_APP_USER_ID_EXPR})"
    )
    op.execute(
        "CREATE POLICY p_exercises_own_update ON exercises FOR UPDATE "
        f"USING (user_id = {_APP_USER_ID_EXPR}) "
        f"WITH CHECK (user_id = {_APP_USER_ID_EXPR})"
    )

    # FORCE (above) subjects the table's OWNER to these policies too -- which is the
    # whole point for the six user-owned tables, but here it would also lock
    # gymak_migrator out of the seeded library it is responsible for: a seed row has
    # user_id IS NULL, which satisfies neither write policy, so 3acc66b027b7's own
    # INSERTs and every future seed migration would be rejected by their own database.
    # This role-scoped permissive policy restores exactly that and nothing more. It
    # cannot widen anything for the application: the API connects as gymak_app, which
    # this policy does not name, so the scoped policies above remain the only ones that
    # apply to it.
    op.execute(
        f"CREATE POLICY p_exercises_migrator ON exercises FOR ALL TO {MIGRATOR_ROLE} "
        "USING (true) WITH CHECK (true)"
    )

    # No DELETE -- see the module docstring; soft delete via is_active is an UPDATE.
    op.execute(f"GRANT INSERT, UPDATE ON exercises TO {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT, UPDATE ON exercises FROM {APP_ROLE}")

    op.execute("DROP POLICY IF EXISTS p_exercises_migrator ON exercises")
    op.execute("DROP POLICY IF EXISTS p_exercises_own_update ON exercises")
    op.execute("DROP POLICY IF EXISTS p_exercises_own_insert ON exercises")
    op.execute("DROP POLICY IF EXISTS p_exercises_read ON exercises")

    op.execute("ALTER TABLE exercises NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE exercises DISABLE ROW LEVEL SECURITY")

    op.execute("DROP INDEX IF EXISTS ix_exercises_user_id")
    op.drop_constraint("exercises_user_id_fkey", "exercises", type_="foreignkey")
    # Custom rows cannot survive the column that identifies them: without user_id every
    # remaining custom row would silently become a public seeded row visible to everyone.
    # They are removed first, and the sets referencing them (ON DELETE RESTRICT) with
    # them, so the downgrade is clean rather than blocked half-way by the FK.
    op.execute(
        "DELETE FROM workout_sets WHERE exercise_id IN "
        "(SELECT id FROM exercises WHERE user_id IS NOT NULL)"
    )
    op.execute(
        "DELETE FROM program_exercises WHERE exercise_id IN "
        "(SELECT id FROM exercises WHERE user_id IS NOT NULL)"
    )
    op.execute("DELETE FROM exercises WHERE user_id IS NOT NULL")
    op.drop_column("exercises", "user_id")
