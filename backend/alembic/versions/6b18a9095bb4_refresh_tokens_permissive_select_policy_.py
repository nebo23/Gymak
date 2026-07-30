"""refresh tokens permissive select policy for pre-auth lookup

Revision ID: 6b18a9095bb4
Revises: ba41f8eb5985
Create Date: 2026-07-31 00:38:16.121594

T-05 / spec 5.5 step 1: /auth/refresh receives an opaque token, not a bearer, so it
does not know which user it belongs to until *after* the row is read -- there is no
value to bind app.user_id to before this SELECT runs. The owner policy from the initial
migration (ba41f8eb5985) has no FOR clause, so it governs SELECT too, and with
app.user_id unset it evaluates to `user_id = NULL`, which is never true for any row
(confirmed empirically in tests/security/test_rls.py::
test_rls_with_no_app_user_id_set_returns_zero_rows_not_all_rows). FORCE ROW LEVEL
SECURITY means gymak_app gets no owner exemption either, so the lookup by token_hash
that spec 5.5 step 1 requires cannot succeed under the existing policy at all.

This adds a second, permissive policy scoped to SELECT only: `USING (true)`. Postgres
OR-combines multiple permissive policies for the same command, so SELECT becomes
unconditionally allowed while INSERT/UPDATE/DELETE remain governed solely by the
existing owner policy (unchanged -- it still requires app.user_id to match for any
write). The security argument for opening SELECT specifically: the real secret here is
the 256-bit token_hash value itself, not row visibility -- rows are found only by
already knowing an unguessable hash, never by enumeration. Every write path
(consume, revoke, insert-successor) still requires the caller to have bound
app.user_id to the row's actual owner first (app/repositories/token_repo.py), so a
repository function that forgets a WHERE user_id=... is still caught by RLS for every
mutating statement, same as before -- this migration narrows the second barrier for
reads only, on this one table.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6b18a9095bb4"
down_revision: str | None = "ba41f8eb5985"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE POLICY p_refresh_tokens_lookup ON refresh_tokens FOR SELECT USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS p_refresh_tokens_lookup ON refresh_tokens")
