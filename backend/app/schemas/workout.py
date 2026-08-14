"""Request/response shapes for spec §5.6 (POST /workouts, GET /workouts/active),
§5.7 (POST/PATCH/DELETE .../sets) and §5.8 (POST /workouts/{id}/finish, POST
/workouts/{id}/abandon), P2-FR-005/006/007.

Following schemas/program.py's convention: request bodies stay plain and permissive
(`program_day_id`/`exercise_id` are bare `str`, parsed in the router the same way
routers/program.py parses a path `day_id` -- a malformed value gets §6.5's generic
404 rather than FastAPI's default body), and a module-level `build_*` function turns
an ORM row into the response model. §5.7's response shapes take plain scalars
(`volume_kg`, `e1rm_kg`, ...) rather than a service-layer dataclass, matching
`build_finished_summary`'s own precedent -- the router is what bridges a service
result to a schema builder's keyword arguments, not this module.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, ConfigDict, PlainSerializer

from app.models.workout import WorkoutSession, WorkoutSet

# Same convention as schemas/profile.py's DecimalAsFloat: Numeric columns parse into
# Decimal, but §5's wire format is a JSON number.
DecimalAsFloat = Annotated[
    Decimal, PlainSerializer(lambda value: float(value), return_type=float, when_used="json")
]


class WorkoutStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    program_day_id: str | None = None


class WorkoutFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    notes: str | None = None


class WorkoutSessionSummary(BaseModel):
    """§5.6's session object -- the shape POST /workouts and GET /workouts/active
    both return. `sets` is always `[]` here: no endpoint in this task can populate
    one (T-19 owns POST /workouts/{id}/sets and its response shape), the same kind
    of deliberate, documented placeholder schemas/program.py's
    `last_performance: None` is for the same T-18/T-19 gap."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    started_at: datetime
    local_date: date
    program_day_id: uuid.UUID | None
    sets: list[object] = []


class WorkoutStartResponse(BaseModel):
    session: WorkoutSessionSummary


class WorkoutFinishedSummary(BaseModel):
    """§5.8's session object -- returned by both finish and abandon. Abandon leaves
    `duration_seconds`/`total_volume_kg` null: "abandon ... computes nothing" (§5.8),
    so those two fields on the row are whatever they already were (always NULL,
    since a session that never finished never had them set)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    total_volume_kg: DecimalAsFloat | None
    set_count: int
    exercise_count: int


class WorkoutFinishResponse(BaseModel):
    session: WorkoutFinishedSummary
    # §5.8's example shows a `records_set` array. Computing it needs a read-time
    # aggregation over history (P2-ADR-05), which lives in metrics_repo.py --
    # not one of this task's files (T-21 owns metrics_repo.py and GET /records).
    # Always empty here, the same deliberate placeholder schemas/program.py's
    # `last_performance: None` is for T-18/T-19's own history gap.
    records_set: list[object] = []


class WorkoutAbandonResponse(BaseModel):
    session: WorkoutFinishedSummary


def build_session_summary(workout_session: WorkoutSession) -> WorkoutSessionSummary:
    return WorkoutSessionSummary(
        id=workout_session.id,
        status=workout_session.status,
        started_at=workout_session.started_at,
        local_date=workout_session.local_date,
        program_day_id=workout_session.program_day_id,
        sets=[],
    )


def build_finished_summary(
    workout_session: WorkoutSession, *, set_count: int, exercise_count: int
) -> WorkoutFinishedSummary:
    return WorkoutFinishedSummary(
        id=workout_session.id,
        status=workout_session.status,
        started_at=workout_session.started_at,
        ended_at=workout_session.ended_at,
        duration_seconds=workout_session.duration_seconds,
        total_volume_kg=workout_session.total_volume_kg,
        set_count=set_count,
        exercise_count=exercise_count,
    )


# =========================================================================================
# §5.7 POST/PATCH/DELETE /workouts/{id}/sets/{set_id} (T-19)
# =========================================================================================


class WorkoutSetCreateRequest(BaseModel):
    """§5.7 POST. `exercise_id` stays a bare `str` -- see the module docstring."""

    model_config = ConfigDict(extra="forbid")

    exercise_id: str
    reps: int
    weight_kg: Decimal
    rpe: Decimal | None = None
    is_warmup: bool = False


class WorkoutSetPatchRequest(BaseModel):
    """§5.7 PATCH: "Any of reps, weight_kg, rpe, is_warmup. Not exercise_id" --
    `exercise_id` has no field here at all, so `extra="forbid"` rejects it with
    FastAPI's own body-parsing error rather than a dedicated code, matching
    `ProfileUpdateRequest`/`WorkoutFinishRequest`'s own precedent for a field that
    must never be accepted. Every field optional, so `model_dump(exclude_unset=True)`
    in workout_service tells "not sent" from "sent" -- what a partial update needs
    (profile_service's `update_profile` sets the same convention).
    """

    model_config = ConfigDict(extra="forbid")

    reps: int | None = None
    weight_kg: Decimal | None = None
    rpe: Decimal | None = None
    is_warmup: bool | None = None


class SetDerived(BaseModel):
    """§5.7's `derived` block -- computed fresh every time (P2-ADR-04): never stored."""

    volume_kg: DecimalAsFloat
    e1rm_kg: DecimalAsFloat


class WorkoutSetData(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    exercise_id: uuid.UUID
    set_index: int
    reps: int
    weight_kg: DecimalAsFloat
    rpe: DecimalAsFloat | None
    is_warmup: bool
    logged_at: datetime
    derived: SetDerived


class SessionTotalsData(BaseModel):
    sets: int
    volume_kg: DecimalAsFloat


class SetRecordData(BaseModel):
    kind: str
    previous: DecimalAsFloat


class WorkoutSetActionResponse(BaseModel):
    """§5.7's POST response shape, reused for PATCH: both mutate a set and both need
    the same freshly computed `derived`/`session_totals`/`is_record` triple
    (P2-ADR-04: computed on read, never stored -- there is no reason POST's row gets
    fresher numbers than PATCH's edited one)."""

    set: WorkoutSetData
    session_totals: SessionTotalsData
    is_record: SetRecordData | None


def build_set_data(
    workout_set: WorkoutSet, *, volume_kg: Decimal, e1rm_kg: Decimal
) -> WorkoutSetData:
    return WorkoutSetData(
        id=workout_set.id,
        exercise_id=workout_set.exercise_id,
        set_index=workout_set.set_index,
        reps=workout_set.reps,
        weight_kg=workout_set.weight_kg,
        rpe=workout_set.rpe,
        is_warmup=workout_set.is_warmup,
        logged_at=workout_set.logged_at,
        derived=SetDerived(volume_kg=volume_kg, e1rm_kg=e1rm_kg),
    )
