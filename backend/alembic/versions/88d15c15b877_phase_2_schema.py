"""phase 2 schema: exercises, programs, program_days, program_exercises,
workout_sessions, workout_sets, body_weight_entries, profiles.timezone (spec section 4)

Revision ID: 88d15c15b877
Revises: ae026cea6d8d
Create Date: 2026-08-13 00:00:00.000000

Runs as gymak_migrator (see alembic/env.py, migration 737d03a7c353's role split): this
migration both creates and owns the seven tables below, and is therefore the only role
with authority to GRANT on them to gymak_app -- the same reasoning 737d03a7c353's own
docstring gives for why table-level grants belong in Alembic, not one-off provisioning.

Per-table grants (P2-ADR-09, spec 4.10) are scoped to what the Phase 2 API contract
(spec section 5) actually needs, not "every table gets every verb", mirroring
737d03a7c353's own approach for Phase 1:
  - exercises: SELECT only. Read-only reference data seeded by a data migration (T-16,
    P2-ADR-02); no endpoint ever writes to it.
  - programs: SELECT, INSERT, UPDATE. Generation inserts a row; regeneration updates the
    previous row's is_current/superseded_at (§4.3). Never DELETE -- old programs are kept.
  - program_days, program_exercises: SELECT, INSERT. Written once, together, at
    generation time; never updated or deleted independently of their parent program.
  - workout_sessions: SELECT, INSERT, UPDATE. Start inserts; finish/abandon update
    status/ended_at/duration_seconds/total_volume_kg/notes (§5.8). Never DELETE --
    sessions are kept as history.
  - workout_sets: SELECT, INSERT, UPDATE, DELETE -- the one table besides body weight
    that needs all four (§5.7's POST/PATCH/DELETE).
  - body_weight_entries: SELECT, INSERT, UPDATE, DELETE (§5.10's PUT upsert and DELETE).

RLS (P2-ADR-09, spec 4.10): every user-owned table gets ENABLE ROW LEVEL SECURITY,
FORCE ROW LEVEL SECURITY, and an owner policy in this same migration -- not a follow-up,
per Phase 1's own lesson (A.5 items 1 and 13). `programs`, `workout_sessions`, and
`body_weight_entries` carry `user_id` directly, so their policy is the same
NULLIF(current_setting(...)) pattern Phase 1 used for `profiles`. `program_days`,
`program_exercises`, and `workout_sets` carry no `user_id` of their own -- ownership
reads through a parent chain (program_days -> programs, program_exercises ->
program_days -> programs, workout_sets -> workout_sessions), the same parent-EXISTS
shape spec 4.10 spells out explicitly for `workout_sets` and P2-ADR-09 names for all
three. `exercises` is public reference data: SELECT granted, no policy, no RLS at all
(§4.10's stated exception).
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "88d15c15b877"
down_revision: str | None = "ae026cea6d8d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "gymak_app"

_APP_USER_ID_EXPR = "NULLIF(current_setting('app.user_id', true), '')::uuid"

_GRANTS: dict[str, str] = {
    "programs": "SELECT, INSERT, UPDATE",
    "program_days": "SELECT, INSERT",
    "program_exercises": "SELECT, INSERT",
    "workout_sessions": "SELECT, INSERT, UPDATE",
    "workout_sets": "SELECT, INSERT, UPDATE, DELETE",
    "body_weight_entries": "SELECT, INSERT, UPDATE, DELETE",
}


def upgrade() -> None:
    # --- §4.2: the one altered column -------------------------------------------------
    op.add_column(
        "profiles",
        sa.Column("timezone", sa.Text(), nullable=False, server_default=sa.text("'Africa/Cairo'")),
    )

    # --- §4.1 exercises (P2-ADR-02) -----------------------------------------------------
    op.create_table(
        "exercises",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name_en", sa.Text(), nullable=False),
        sa.Column("name_ar", sa.Text(), nullable=False),
        sa.Column("primary_muscle", sa.Text(), nullable=False),
        sa.Column(
            "secondary_muscles",
            ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("equipment", sa.Text(), nullable=False),
        sa.Column("movement_pattern", sa.Text(), nullable=False),
        sa.Column("is_compound", sa.Boolean(), nullable=False),
        sa.Column("difficulty", sa.Text(), nullable=False),
        sa.Column("instructions_en", sa.Text(), nullable=False),
        sa.Column("instructions_ar", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.UniqueConstraint("slug", name="uq_exercises_slug"),
        sa.CheckConstraint(
            "primary_muscle IN ('chest', 'back', 'lats', 'traps', 'front_delts', "
            "'side_delts', 'rear_delts', 'biceps', 'triceps', 'forearms', 'quads', "
            "'hamstrings', 'glutes', 'calves', 'abs', 'obliques', 'lower_back')",
            name="chk_exercises_primary_muscle",
        ),
        sa.CheckConstraint(
            "equipment IN ('barbell', 'dumbbell', 'machine', 'cable', 'bodyweight', "
            "'kettlebell', 'band')",
            name="chk_exercises_equipment",
        ),
        sa.CheckConstraint(
            "movement_pattern IN ('squat', 'hinge', 'horizontal_push', 'vertical_push', "
            "'horizontal_pull', 'vertical_pull', 'lunge', 'carry', 'isolation')",
            name="chk_exercises_movement_pattern",
        ),
        sa.CheckConstraint(
            "difficulty IN ('beginner', 'intermediate', 'advanced')",
            name="chk_exercises_difficulty",
        ),
    )

    # --- §4.3 programs -------------------------------------------------------------------
    op.create_table(
        "programs",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("days_per_week", sa.Integer(), nullable=False),
        sa.Column("split_type", sa.Text(), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("experience_level", sa.Text(), nullable=False),
        sa.Column("generator_version", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("days_per_week BETWEEN 2 AND 6", name="chk_programs_days_per_week"),
        sa.CheckConstraint(
            "split_type IN ('full_body', 'upper_lower', 'push_pull_legs')",
            name="chk_programs_split_type",
        ),
        sa.CheckConstraint("goal IN ('lose', 'gain', 'maintain')", name="chk_programs_goal"),
        sa.CheckConstraint(
            "experience_level IN ('beginner', 'intermediate', 'advanced')",
            name="chk_programs_experience_level",
        ),
    )
    # §4.3: "Exactly one true per user, enforced by a partial unique index" -- the same
    # database-level invariant pattern as §4.6's ux_one_active_session below.
    op.create_index(
        "ux_one_current_program",
        "programs",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    # --- §4.4 program_days -----------------------------------------------------------
    op.create_table(
        "program_days",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "program_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("programs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_index", sa.Integer(), nullable=False),
        sa.Column("label_key", sa.Text(), nullable=False),
        sa.Column("focus_muscles", ARRAY(sa.Text()), nullable=False),
        sa.CheckConstraint("day_index BETWEEN 1 AND 6", name="chk_program_days_day_index"),
        sa.UniqueConstraint("program_id", "day_index", name="uq_program_days_program_day_index"),
    )

    # --- §4.5 program_exercises --------------------------------------------------------
    op.create_table(
        "program_exercises",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "program_day_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("program_days.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("target_sets", sa.Integer(), nullable=False),
        sa.Column("target_reps_min", sa.Integer(), nullable=False),
        sa.Column("target_reps_max", sa.Integer(), nullable=False),
        sa.Column("rest_seconds", sa.Integer(), nullable=False),
        sa.CheckConstraint("target_sets BETWEEN 1 AND 8", name="chk_program_exercises_target_sets"),
        sa.CheckConstraint(
            "target_reps_min >= 1 AND target_reps_min <= target_reps_max AND target_reps_max <= 30",
            name="chk_program_exercises_target_reps",
        ),
        sa.CheckConstraint(
            "rest_seconds BETWEEN 30 AND 300", name="chk_program_exercises_rest_seconds"
        ),
        sa.UniqueConstraint("program_day_id", "position", name="uq_program_exercises_day_position"),
    )

    # --- §4.6 workout_sessions (P2-ADR-03) ----------------------------------------------
    op.create_table(
        "workout_sessions",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "program_day_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("program_days.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("total_volume_kg", sa.Numeric(9, 2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("local_date", sa.Date(), nullable=False),
        sa.CheckConstraint(
            "status IN ('in_progress', 'completed', 'abandoned')",
            name="chk_workout_sessions_status",
        ),
    )
    # §4.6, verbatim: at most one in_progress session per user, in the database.
    op.execute(
        "CREATE UNIQUE INDEX ux_one_active_session ON workout_sessions (user_id) "
        "WHERE status = 'in_progress'"
    )

    # --- §4.7 workout_sets (P2-ADR-04) --------------------------------------------------
    op.create_table(
        "workout_sets",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "session_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("workout_sessions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "exercise_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("exercises.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("set_index", sa.Integer(), nullable=False),
        sa.Column("reps", sa.Integer(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(6, 2), nullable=False),
        sa.Column("rpe", sa.Numeric(3, 1), nullable=True),
        sa.Column("is_warmup", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column(
            "logged_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("reps BETWEEN 1 AND 100", name="chk_workout_sets_reps"),
        sa.CheckConstraint("weight_kg BETWEEN 0 AND 500", name="chk_workout_sets_weight_kg"),
        sa.CheckConstraint("rpe IS NULL OR rpe BETWEEN 5 AND 10", name="chk_workout_sets_rpe"),
        sa.UniqueConstraint(
            "session_id",
            "exercise_id",
            "set_index",
            name="uq_workout_sets_session_exercise_index",
        ),
    )

    # --- §4.8 body_weight_entries (P2-ADR-06) -------------------------------------------
    op.create_table(
        "body_weight_entries",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("measured_on", sa.Date(), nullable=False),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "weight_kg BETWEEN 30 AND 300", name="chk_body_weight_entries_weight_kg"
        ),
        sa.UniqueConstraint(
            "user_id", "measured_on", name="uq_body_weight_entries_user_measured_on"
        ),
    )
    # Reuses set_updated_at(), created by migration ba41f8eb5985 -- only the second
    # mutable table (after profiles/users) that needs it in this phase (see the
    # column-by-column notes in app/models/*.py for why the other five tables don't).
    op.execute(
        "CREATE TRIGGER trg_body_weight_entries_updated_at BEFORE UPDATE ON body_weight_entries "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # --- §4.9 indexes, verbatim ----------------------------------------------------------
    op.create_index("ix_sessions_user_status", "workout_sessions", ["user_id", "status"])
    op.execute(
        "CREATE INDEX ix_sessions_user_local_date ON workout_sessions (user_id, local_date DESC)"
    )
    op.create_index("ix_sets_session", "workout_sets", ["session_id"])
    op.execute(
        "CREATE INDEX ix_sets_exercise ON workout_sets (exercise_id) WHERE is_warmup = false"
    )
    op.execute(
        "CREATE INDEX ix_bodyweight_user_date ON body_weight_entries (user_id, measured_on DESC)"
    )
    op.create_index("ix_program_days_program", "program_days", ["program_id", "day_index"])

    # --- §4.10 RLS (P2-ADR-09) -----------------------------------------------------------
    for table in (
        "programs",
        "program_days",
        "program_exercises",
        "workout_sessions",
        "workout_sets",
        "body_weight_entries",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        # FORCE, not just ENABLE: gymak_migrator owns these tables (it created them), and
        # Postgres exempts a table's owner from its own policies by default -- the same
        # footgun ba41f8eb5985 documented and confirmed empirically for Phase 1.
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")

    # Direct user_id columns: the same NULLIF(...) owner-policy shape Phase 1 used for
    # profiles/refresh_tokens, now with an explicit WITH CHECK (spec 4.10 shows both).
    for table in ("programs", "workout_sessions", "body_weight_entries"):
        op.execute(
            f"CREATE POLICY p_{table}_owner ON {table} "
            f"USING (user_id = {_APP_USER_ID_EXPR}) "
            f"WITH CHECK (user_id = {_APP_USER_ID_EXPR})"
        )

    # No user_id of their own -- ownership reads through the parent chain (P2-ADR-09).
    op.execute(
        "CREATE POLICY p_program_days_owner ON program_days "
        "USING (EXISTS (SELECT 1 FROM programs p "
        f"WHERE p.id = program_days.program_id AND p.user_id = {_APP_USER_ID_EXPR})) "
        "WITH CHECK (EXISTS (SELECT 1 FROM programs p "
        f"WHERE p.id = program_days.program_id AND p.user_id = {_APP_USER_ID_EXPR}))"
    )
    op.execute(
        "CREATE POLICY p_program_exercises_owner ON program_exercises "
        "USING (EXISTS (SELECT 1 FROM program_days d JOIN programs p ON p.id = d.program_id "
        f"WHERE d.id = program_exercises.program_day_id AND p.user_id = {_APP_USER_ID_EXPR})) "
        "WITH CHECK (EXISTS (SELECT 1 FROM program_days d JOIN programs p ON p.id = d.program_id "
        f"WHERE d.id = program_exercises.program_day_id AND p.user_id = {_APP_USER_ID_EXPR}))"
    )
    # §4.10, verbatim: workout_sets' policy reads through workout_sessions.
    op.execute(
        "CREATE POLICY p_workout_sets_owner ON workout_sets "
        "USING (EXISTS (SELECT 1 FROM workout_sessions s "
        f"WHERE s.id = workout_sets.session_id AND s.user_id = {_APP_USER_ID_EXPR})) "
        "WITH CHECK (EXISTS (SELECT 1 FROM workout_sessions s "
        f"WHERE s.id = workout_sets.session_id AND s.user_id = {_APP_USER_ID_EXPR}))"
    )

    # exercises: public reference data, no user_id, no RLS at all -- SELECT only (§4.10).
    op.execute(f"GRANT SELECT ON exercises TO {APP_ROLE}")

    for table, privileges in _GRANTS.items():
        op.execute(f"GRANT {privileges} ON {table} TO {APP_ROLE}")


def downgrade() -> None:
    for table, privileges in _GRANTS.items():
        op.execute(f"REVOKE {privileges} ON {table} FROM {APP_ROLE}")
    op.execute(f"REVOKE SELECT ON exercises FROM {APP_ROLE}")

    op.execute("DROP POLICY IF EXISTS p_workout_sets_owner ON workout_sets")
    op.execute("DROP POLICY IF EXISTS p_program_exercises_owner ON program_exercises")
    op.execute("DROP POLICY IF EXISTS p_program_days_owner ON program_days")
    for table in ("body_weight_entries", "workout_sessions", "programs"):
        op.execute(f"DROP POLICY IF EXISTS p_{table}_owner ON {table}")

    for table in (
        "body_weight_entries",
        "workout_sets",
        "workout_sessions",
        "program_exercises",
        "program_days",
        "programs",
    ):
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")

    op.drop_index("ix_program_days_program", table_name="program_days")
    op.execute("DROP INDEX IF EXISTS ix_bodyweight_user_date")
    op.execute("DROP INDEX IF EXISTS ix_sets_exercise")
    op.drop_index("ix_sets_session", table_name="workout_sets")
    op.execute("DROP INDEX IF EXISTS ix_sessions_user_local_date")
    op.drop_index("ix_sessions_user_status", table_name="workout_sessions")

    op.execute("DROP TRIGGER IF EXISTS trg_body_weight_entries_updated_at ON body_weight_entries")

    op.drop_table("body_weight_entries")
    op.execute("DROP INDEX IF EXISTS ux_one_active_session")
    op.drop_table("workout_sets")
    op.drop_table("workout_sessions")
    op.drop_table("program_exercises")
    op.drop_table("program_days")
    op.drop_index("ux_one_current_program", table_name="programs")
    op.drop_table("programs")
    op.drop_table("exercises")

    op.drop_column("profiles", "timezone")
