"""phase 1 schema: users, user_identities, profiles, refresh_tokens,
password_reset_codes, audit_log (spec section 4)

Revision ID: ba41f8eb5985
Revises:
Create Date: 2026-07-30 03:04:45.132075

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import CITEXT, INET, JSONB

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'ba41f8eb5985'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must already exist before this migration runs (provisioned as part of environment
# setup, same role DATABASE_URL connects as -- see .env.example). Non-superuser,
# without BYPASSRLS: app/database.py asserts this at startup.
APP_ROLE = "gymak_app"


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("email", CITEXT(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("token_version", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "password_hash IS NOT NULL OR email_verified = true", name="chk_credential_present"
        ),
    )
    # Partial, not a plain UNIQUE on the column: a soft-deleted row's email must be
    # reusable by a fresh registration (spec 4.1).
    op.create_index(
        "uq_users_email_live",
        "users",
        ["email"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "user_identities",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_uid", sa.Text(), nullable=False),
        sa.Column("firebase_uid", sa.Text(), nullable=False),
        sa.Column("email_at_provider", CITEXT(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        # 'apple' allowed now, ahead of use, so Phase 3's Apple Sign-In needs no migration.
        sa.CheckConstraint(
            "provider IN ('google', 'facebook', 'apple')", name="chk_user_identities_provider"
        ),
        sa.UniqueConstraint("provider", "provider_uid", name="uq_user_identities_provider_uid"),
    )

    op.create_table(
        "profiles",
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("gender", sa.Text(), nullable=False),
        sa.Column("birth_date", sa.Date(), nullable=False),
        sa.Column("height_cm", sa.Numeric(5, 1), nullable=False),
        sa.Column("weight_kg", sa.Numeric(5, 2), nullable=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("experience_level", sa.Text(), nullable=False),
        sa.Column("activity_level", sa.Text(), nullable=True),
        sa.Column("unit_system", sa.Text(), nullable=False, server_default=sa.text("'metric'")),
        sa.Column("language", sa.Text(), nullable=False, server_default=sa.text("'ar'")),
        sa.Column(
            "onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "char_length(btrim(name)) BETWEEN 2 AND 60", name="chk_profiles_name_length"
        ),
        sa.CheckConstraint("gender IN ('male', 'female')", name="chk_profiles_gender"),
        sa.CheckConstraint(
            "birth_date <= current_date - INTERVAL '13 years' AND "
            "birth_date >= current_date - INTERVAL '100 years'",
            name="chk_profiles_birth_date",
        ),
        sa.CheckConstraint("height_cm BETWEEN 100 AND 250", name="chk_profiles_height_cm"),
        sa.CheckConstraint("weight_kg BETWEEN 30 AND 300", name="chk_profiles_weight_kg"),
        sa.CheckConstraint("goal IN ('lose', 'gain', 'maintain')", name="chk_profiles_goal"),
        sa.CheckConstraint(
            "experience_level IN ('beginner', 'intermediate', 'advanced')",
            name="chk_profiles_experience_level",
        ),
        sa.CheckConstraint(
            "activity_level IN ('sedentary', 'light', 'moderate', 'high', 'very_high')",
            name="chk_profiles_activity_level",
        ),
        sa.CheckConstraint(
            "unit_system IN ('metric', 'imperial')", name="chk_profiles_unit_system"
        ),
        sa.CheckConstraint("language IN ('ar', 'en')", name="chk_profiles_language"),
    )

    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.Text(), nullable=False, unique=True),
        sa.Column("family_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column(
            "parent_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("refresh_tokens.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", INET(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )
    op.create_index(
        "idx_rt_user_active",
        "refresh_tokens",
        ["user_id"],
        postgresql_where=sa.text("consumed_at IS NULL AND revoked_at IS NULL"),
    )
    op.create_index("idx_rt_family", "refresh_tokens", ["family_id"])

    op.create_table(
        "password_reset_codes",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("requested_ip", INET(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        # No FK to users.id, deliberately: ON DELETE SET NULL/CASCADE would each require
        # UPDATE or DELETE privilege on audit_log to fire, which conflicts with the
        # INSERT/SELECT-only grant below (confirmed empirically -- with a real FK here,
        # deleting a user under the app role failed with "permission denied for
        # audit_log"). entity_id below is unconstrained for the same append-only reason.
        sa.Column("actor_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity", sa.Text(), nullable=True),
        sa.Column("entity_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
    )

    # updated_at trigger -- only the two mutable tables (spec: "every mutable table gets
    # updated_at maintained by a trigger"). user_identities/refresh_tokens/
    # password_reset_codes/audit_log have no updated_at column at all.
    op.execute(
        """
        CREATE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        "CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )
    op.execute(
        "CREATE TRIGGER trg_profiles_updated_at BEFORE UPDATE ON profiles "
        "FOR EACH ROW EXECUTE FUNCTION set_updated_at()"
    )

    # Row-level security: a second, independent barrier behind repository scoping (spec
    # 4.7). Deliberately NOT enabled on users/user_identities/password_reset_codes: all
    # three are looked up during pre-authentication flows (register, login, social
    # sign-in, forgot-password) where app.user_id is not yet set, and a naive owner
    # policy would make those lookups return zero rows. audit_log's protection is the
    # GRANT restriction below, not RLS -- it is written across many different users'
    # authenticated contexts and has no single owner column.
    op.execute("ALTER TABLE profiles ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens ENABLE ROW LEVEL SECURITY")
    # FORCE, not just ENABLE: Postgres exempts a table's OWNER from its own RLS policies
    # by default. APP_ROLE both runs this migration (so it owns these tables) and is the
    # role the application connects as -- there is one role in this design (Appendix
    # A.1's single DATABASE_URL), not a separate migration-owner vs. app-runtime split.
    # Without FORCE, every policy below is silently a no-op for that role: confirmed
    # empirically against a live database (every row was visible regardless of
    # app.user_id until FORCE was added) before landing this line.
    op.execute("ALTER TABLE profiles FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens FORCE ROW LEVEL SECURITY")
    # NULLIF(..., '') guards a real, confirmed footgun, not a hypothetical one: once a
    # session has ever touched app.user_id via set_config(is_local=true), Postgres's
    # reset value for it (after that transaction's COMMIT/ROLLBACK) is '', not NULL --
    # confirmed empirically against a live database. Casting ''::uuid directly is a hard
    # Postgres error, not a graceful "no match", which would turn "no app.user_id set"
    # into a crash instead of the intended zero-rows fail-closed behaviour. NULLIF folds
    # '' back to NULL first, so the comparison is safely NULL (no rows) either way.
    op.execute(
        "CREATE POLICY p_profiles_owner ON profiles "
        "USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"
    )
    op.execute(
        "CREATE POLICY p_refresh_tokens_owner ON refresh_tokens "
        "USING (user_id = NULLIF(current_setting('app.user_id', true), '')::uuid)"
    )

    # audit_log is append-only at the database level, not by convention: the app role
    # gets INSERT and SELECT only, never UPDATE or DELETE.
    op.execute(f"GRANT INSERT, SELECT ON audit_log TO {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {APP_ROLE}")


def downgrade() -> None:
    op.execute(f"REVOKE INSERT, SELECT ON audit_log FROM {APP_ROLE}")

    op.execute("DROP POLICY IF EXISTS p_refresh_tokens_owner ON refresh_tokens")
    op.execute("DROP POLICY IF EXISTS p_profiles_owner ON profiles")
    op.execute("ALTER TABLE refresh_tokens NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE profiles NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE refresh_tokens DISABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE profiles DISABLE ROW LEVEL SECURITY")

    op.execute("DROP TRIGGER IF EXISTS trg_profiles_updated_at ON profiles")
    op.execute("DROP TRIGGER IF EXISTS trg_users_updated_at ON users")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")

    op.drop_table("audit_log")
    op.drop_table("password_reset_codes")
    op.drop_index("idx_rt_family", table_name="refresh_tokens")
    op.drop_index("idx_rt_user_active", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("profiles")
    op.drop_table("user_identities")
    op.drop_index("uq_users_email_live", table_name="users")
    op.drop_table("users")
