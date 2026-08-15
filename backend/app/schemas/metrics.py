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
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.models.body_weight import BodyWeightEntry
from app.models.exercise import Exercise
from app.models.workout import WorkoutSession, WorkoutSet
from app.schemas.workout import WorkoutSessionSummary, build_session_summary

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


def _resolved_name(exercise: Exercise, language: str) -> str:
    """Same resolution as schemas/exercise.py's own (private) `_resolved_name` --
    reimplemented here rather than imported, matching schemas/program.py's own
    `build_program_day_detail` precedent of resolving a caller's-language name inside
    the schema builder itself, not the service that fetched the row."""
    return exercise.name_ar if language == "ar" else exercise.name_en


# =========================================================================================
# §5.11 GET /records (T-21), P2-ADR-05
# =========================================================================================


class RecordExerciseRef(BaseModel):
    id: uuid.UUID
    slug: str
    name: str


class HeaviestSetData(BaseModel):
    weight_kg: DecimalAsFloat
    reps: int
    session_id: uuid.UUID
    local_date: date


class BestE1rmData(BaseModel):
    value_kg: DecimalAsFloat
    weight_kg: DecimalAsFloat
    reps: int
    local_date: date


class BestSessionVolumeData(BaseModel):
    volume_kg: DecimalAsFloat
    session_id: uuid.UUID
    local_date: date


class RecordEntryData(BaseModel):
    exercise: RecordExerciseRef
    heaviest_set: HeaviestSetData
    best_e1rm: BestE1rmData
    best_session_volume: BestSessionVolumeData
    total_sets: int


class RecordsResponse(BaseModel):
    records: list[RecordEntryData]


def build_record_entry(
    *,
    exercise: Exercise,
    language: str,
    heaviest_set: WorkoutSet,
    heaviest_set_local_date: date,
    best_e1rm_set: WorkoutSet,
    best_e1rm_value_kg: Decimal,
    best_e1rm_local_date: date,
    best_session_volume_kg: Decimal,
    best_session_volume_session_id: uuid.UUID,
    best_session_volume_local_date: date,
    total_sets: int,
) -> RecordEntryData:
    return RecordEntryData(
        exercise=RecordExerciseRef(
            id=exercise.id, slug=exercise.slug, name=_resolved_name(exercise, language)
        ),
        heaviest_set=HeaviestSetData(
            weight_kg=heaviest_set.weight_kg,
            reps=heaviest_set.reps,
            session_id=heaviest_set.session_id,
            local_date=heaviest_set_local_date,
        ),
        best_e1rm=BestE1rmData(
            value_kg=best_e1rm_value_kg,
            weight_kg=best_e1rm_set.weight_kg,
            reps=best_e1rm_set.reps,
            local_date=best_e1rm_local_date,
        ),
        best_session_volume=BestSessionVolumeData(
            volume_kg=best_session_volume_kg,
            session_id=best_session_volume_session_id,
            local_date=best_session_volume_local_date,
        ),
        total_sets=total_sets,
    )


# =========================================================================================
# §5.12 GET /dashboard (T-21), P2-ADR-07
# =========================================================================================


class NextWorkoutData(BaseModel):
    program_day_id: uuid.UUID
    day_index: int
    label_key: str
    exercise_count: int
    estimated_minutes: int


class StreakData(BaseModel):
    current_days: int
    longest_days: int
    last_workout_local_date: date | None


class ThisWeekData(BaseModel):
    completed: int
    target: int
    local_week_start: date


class RecentRecordData(BaseModel):
    exercise_name: str
    kind: str
    value: DecimalAsFloat
    local_date: date


class DashboardResponse(BaseModel):
    greeting_name: str
    active_session: WorkoutSessionSummary | None
    next_workout: NextWorkoutData | None
    streak: StreakData
    this_week: ThisWeekData
    # A plain dict, not a fixed model: P2-SAF-002 requires `change_30d_kg` to be
    # physically absent from the JSON for a minor, not merely null -- a declared
    # pydantic field always serialises, so ProgramResponse.stale's own "plain dict,
    # not a nested model" precedent (schemas/program.py) is reused here for the same
    # reason, one level more consequential (a safety requirement, not a convenience).
    weight: dict[str, Any]
    recent_records: list[RecentRecordData]
    program_stale: dict[str, str] | None
    disclaimer_key: str


def build_recent_record(
    *, exercise: Exercise, language: str, value_kg: Decimal, local_date: date
) -> RecentRecordData:
    return RecentRecordData(
        exercise_name=_resolved_name(exercise, language),
        kind="e1rm",
        value=value_kg,
        local_date=local_date,
    )


def build_dashboard_response(
    *,
    greeting_name: str,
    active_session: WorkoutSession | None,
    next_workout: NextWorkoutData | None,
    streak: StreakData,
    this_week: ThisWeekData,
    weight: dict[str, Any],
    recent_records: list[RecentRecordData],
    program_stale: dict[str, str] | None,
    disclaimer_key: str,
) -> DashboardResponse:
    return DashboardResponse(
        greeting_name=greeting_name,
        active_session=(
            build_session_summary(active_session) if active_session is not None else None
        ),
        next_workout=next_workout,
        streak=streak,
        this_week=this_week,
        weight=weight,
        recent_records=recent_records,
        program_stale=program_stale,
        disclaimer_key=disclaimer_key,
    )
