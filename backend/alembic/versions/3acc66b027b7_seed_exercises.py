"""seed the exercise library from app/data/exercises.json (P2-ADR-02, spec §4.1, A.3)

Revision ID: 3acc66b027b7
Revises: 88d15c15b877
Create Date: 2026-08-14 00:00:00.000000

Idempotent (T-16 done-when): ON CONFLICT (id) DO NOTHING means running this twice
inserts nothing the second time and updates nothing silently -- a second run is a
plain no-op, never a silent overwrite of a row someone may have reviewed and adjusted
directly in a later, hand-written migration.

Also installs the `unaccent` extension: spec §5.2's `q` filter matches "case- and
diacritic-insensitively", and `exercise_repo.list_active` wraps both sides of its
ILIKE comparison in `unaccent(...)` to do that. Like `citext` in ba41f8eb5985,
`unaccent` is one of Postgres's "trusted" extensions (installable by any non-superuser
role holding CREATE on the database since PG13) -- gymak_migrator already holds
exactly that, so this needs no extra provisioning. Installed here, in the migration
that first needs it, rather than retroactively added to 88d15c15b877.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import insert as pg_insert

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3acc66b027b7"
down_revision: str | None = "88d15c15b877"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Three directories up from alembic/versions/<file>.py is backend/; app/data/exercises.json
# from there. Resolved from this file's own path rather than the working directory, so
# `alembic upgrade` behaves the same regardless of where it is invoked from.
_DATA_FILE = Path(__file__).resolve().parents[2] / "app" / "data" / "exercises.json"

# A lightweight, local column set -- not the ORM model in app/models/exercise.py.
# Migrations in this codebase never import app.models (see ba41f8eb5985, 737d03a7c353):
# a historical migration must keep working even after a future model change, and this
# is what keeps the two independent.
exercises_table = sa.table(
    "exercises",
    sa.column("id", sa.Uuid(as_uuid=True)),
    sa.column("slug", sa.Text()),
    sa.column("name_en", sa.Text()),
    sa.column("name_ar", sa.Text()),
    sa.column("primary_muscle", sa.Text()),
    sa.column("secondary_muscles", ARRAY(sa.Text())),
    sa.column("equipment", sa.Text()),
    sa.column("movement_pattern", sa.Text()),
    sa.column("is_compound", sa.Boolean()),
    sa.column("difficulty", sa.Text()),
    sa.column("instructions_en", sa.Text()),
    sa.column("instructions_ar", sa.Text()),
    sa.column("is_active", sa.Boolean()),
)


def _load_exercises() -> list[dict[str, Any]]:
    with _DATA_FILE.open(encoding="utf-8") as f:
        rows: list[dict[str, Any]] = json.load(f)
    for row in rows:
        row["id"] = uuid.UUID(row["id"])
    return rows


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")

    rows = _load_exercises()
    connection = op.get_bind()
    connection.execute(
        pg_insert(exercises_table).on_conflict_do_nothing(index_elements=["id"]), rows
    )


def downgrade() -> None:
    rows = _load_exercises()
    ids = [row["id"] for row in rows]
    connection = op.get_bind()
    # Deletes exactly the ids this file's exercises.json carries, not a blanket
    # DELETE FROM exercises -- a downgrade must never remove a row some other
    # migration or hand fix added later.
    connection.execute(sa.delete(exercises_table).where(exercises_table.c.id.in_(ids)))

    op.execute("DROP EXTENSION IF EXISTS unaccent")
