"""Request/response shapes for spec §5.10 (PUT/GET/DELETE /body-weight), P2-FR-009/010,
P2-ADR-06.

Following schemas/workout.py's convention: the request body's `measured_on` stays a
plain `str`, not a pydantic `date` -- a malformed value must reach body_weight_service
as a VALIDATION_ERROR (§7.2's envelope), not FastAPI's default body, mirroring
`ProfileCreateRequest.birth_date`'s own documented reasoning. `entries`/
`moving_average_7d` deliberately carry only `measured_on`/`weight_kg` -- §5.10's own
worked example shows exactly those two fields per item, never `note` or `id`; both
DELETE (by `measured_on`) and a future PUT (upsert, also keyed by `measured_on`) never
need a row id to address an entry, so the list has nothing else to expose. The single
upserted `entry` PUT returns is the fuller row shape instead, matching
`WorkoutSetData`'s own precedent of returning everything for a direct single-row result.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.models.body_weight import BodyWeightEntry

# Same convention as schemas/workout.py's/profile.py's own DecimalAsFloat: Numeric
# columns parse into Decimal, but §5's wire format is a JSON number.
DecimalAsFloat = Annotated[
    Decimal, PlainSerializer(lambda value: float(value), return_type=float, when_used="json")
]


class BodyWeightUpsertRequest(BaseModel):
    """§5.10 PUT. `note` defaults to `None` -- PUT is a full replace (P2-ADR-06: "same-day
    writes replace"), so an omitted `note` clears one exactly the same as an explicit
    `null` would, matching the wire example's own `"note": null`.
    """

    model_config = ConfigDict(extra="forbid")

    measured_on: str
    weight_kg: Decimal
    note: str | None = None


class BodyWeightEntryData(BaseModel):
    """The full row shape -- PUT's own `entry` object."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    measured_on: date
    weight_kg: DecimalAsFloat
    note: str | None
    created_at: datetime
    updated_at: datetime


class BodyWeightUpsertResponse(BaseModel):
    entry: BodyWeightEntryData
    # §5.10: "True when this entry was the newest and therefore updated
    # profiles.weight_kg ... makes the P2-ADR-06 coupling visible in the contract."
    profile_weight_updated: bool


class BodyWeightPoint(BaseModel):
    """§5.10 GET's own worked example shape, shared by `entries` and
    `moving_average_7d` -- both are lean `{measured_on, weight_kg}` pairs, nothing more.
    """

    measured_on: date
    weight_kg: DecimalAsFloat


class BodyWeightSummaryData(BaseModel):
    """§5.10's `summary` block. All four are null/zero on an empty range -- there is no
    entry to report `first`/`latest`/`change_kg` from, and that is a well-formed 200,
    not an error (P2-FR-009 is a log the caller may legitimately have zero rows in for
    any given window, unlike GET /program's "never generated one" 404)."""

    first: DecimalAsFloat | None
    latest: DecimalAsFloat | None
    change_kg: DecimalAsFloat | None
    entry_count: int


class BodyWeightListResponse(BaseModel):
    entries: list[BodyWeightPoint]
    moving_average_7d: list[BodyWeightPoint]
    summary: BodyWeightSummaryData


def build_entry_data(entry: BodyWeightEntry) -> BodyWeightEntryData:
    return BodyWeightEntryData.model_validate(entry)
