"""spec 10.1's performance row (P2-NFR-01): GET /dashboard and GET /workouts under
p95 < 400ms against a seeded account with ~12 months of history (~150 sessions,
~2,700 sets, 365 weight entries). The seed helper itself lives in
tests/support.py's `seed_workout_history` -- "the seed helper is committed, so the
number is reproducible rather than anecdotal" (spec 10.1).

GET /workouts (history, paginated) and GET /workouts/{id} (one session in full) --
the literal endpoints spec 5.9 names for P2-FR-008, and the ones the spec's own
"/workouts" wording in the performance row most naturally refers to -- do not exist
in this codebase. Spec 5.1's catalogue lists them, but no task in the pack (T-18
through T-21) ever implemented them: T-18 built session start/active/finish/abandon,
T-19 built set logging, T-20 body weight, T-21 records/dashboard, and none of their
requirements name a history read. T-22's own file list does not include
routers/workouts.py, services/workout_service.py or schemas/workout.py, so building
them here would be both an invented endpoint (against this task's own rules) and a
file outside this task's scope. Per this task's own confirmed direction, GET
/workouts/active -- the one existing GET under the /workouts prefix -- stands in for
the "/workouts" measurement below; the missing P2-FR-008 endpoints are a real gap
that stays open, not a thing this substitution should be read as closing.

workout_sets' RLS policy (spec 4.10) is a parent-EXISTS subquery evaluated per row --
the single most likely place 2,700 seeded sets blows the 400ms budget on
GET /dashboard, whose records/streak queries (metrics_repo.list_completed_non_warmup_
sets, list_completed_session_local_dates) join workout_sessions into workout_sets.
This test's job is to measure that honestly and assert the real budget, not to
pre-empt a fix (an index, or a policy change) before there is a number to justify one
-- if it fails, that failure IS the finding to report, per this task's own
instruction.
"""

from __future__ import annotations

import time
import uuid
from datetime import date

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import set_rls_user
from app.models.exercise import Exercise
from tests.support import JSONDict, json_body, p95, seed_workout_history

_P95_BUDGET_MS = 400.0
_WARMUP_REQUESTS = 5
_MEASURED_REQUESTS = 40

_PASSWORD = "correct horse battery"  # noqa: S105 -- the shared test literal, see test_cross_tenant.py
_REGISTER = "/api/v1/auth/register"
_PROFILE = "/api/v1/profile"
_DASHBOARD = "/api/v1/dashboard"
_WORKOUTS_ACTIVE = "/api/v1/workouts/active"


def _unique_email() -> str:
    return f"perf-{uuid.uuid4().hex[:12]}@example.com"


async def _register_and_onboard(client: AsyncClient) -> JSONDict:
    register = await client.post(_REGISTER, json={"email": _unique_email(), "password": _PASSWORD})
    assert register.status_code == 201
    user = json_body(register)

    onboard = await client.post(
        _PROFILE,
        json={
            "name": "Seeded Load User",
            "gender": "male",
            "birth_date": date.today().replace(year=date.today().year - 30).isoformat(),
            "height_cm": 178,
            "weight_kg": 82.0,
            "goal": "maintain",
            "experience_level": "intermediate",
            "activity_level": "moderate",
            "unit_system": "metric",
            "language": "en",
        },
        headers={"Authorization": f"Bearer {user['access_token']}"},
    )
    assert onboard.status_code == 201
    return user


async def _timed_get(client: AsyncClient, path: str, headers: dict[str, str]) -> float:
    start = time.perf_counter()
    response = await client.get(path, headers=headers)
    elapsed_ms = (time.perf_counter() - start) * 1000
    assert response.status_code in (200, 204), response.text
    return elapsed_ms


@pytest.mark.perf
async def test_seeded_dashboard_and_workouts_active_meet_p2_nfr_01(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    """Seeds one account with ~150 completed sessions / ~2,700 sets / 365 body-weight
    entries, then measures GET /dashboard and GET /workouts/active p95 against spec
    P2-NFR-01's 400ms budget. Asserts the budget rather than only reporting it -- see
    this module's own docstring on workout_sets' RLS policy for why a failure here is
    a real, reportable finding rather than something to quietly work around.
    """
    user = await _register_and_onboard(client)
    user_id = uuid.UUID(user["user"]["id"])
    headers = {"Authorization": f"Bearer {user['access_token']}"}

    exercise_ids = (await db_session.execute(select(Exercise.id).limit(10))).scalars().all()
    assert len(exercise_ids) >= 3, "the exercise seed migration must have run before this test"

    # RLS (P2-ADR-09): workout_sessions/workout_sets/body_weight_entries are all
    # FORCE-RLS with an owner policy -- app.user_id must be this user's own id for
    # every insert seed_workout_history issues to pass its WITH CHECK.
    await set_rls_user(db_session, str(user_id))
    await seed_workout_history(db_session, user_id, list(exercise_ids))
    await db_session.commit()

    for _ in range(_WARMUP_REQUESTS):
        await _timed_get(client, _DASHBOARD, headers)
        await _timed_get(client, _WORKOUTS_ACTIVE, headers)

    dashboard_samples = [
        await _timed_get(client, _DASHBOARD, headers) for _ in range(_MEASURED_REQUESTS)
    ]
    workouts_active_samples = [
        await _timed_get(client, _WORKOUTS_ACTIVE, headers) for _ in range(_MEASURED_REQUESTS)
    ]

    dashboard_p95 = p95(dashboard_samples)
    workouts_active_p95 = p95(workouts_active_samples)

    print(
        "P2-NFR-01 seeded-load measurement (150 sessions / 2,700 sets / 365 weight "
        f"entries, n={_MEASURED_REQUESTS} per endpoint after {_WARMUP_REQUESTS} "
        f"warmup requests): GET /dashboard p95={dashboard_p95:.1f}ms, "
        f"GET /workouts/active p95={workouts_active_p95:.1f}ms "
        f"(P2-NFR-01 budget {_P95_BUDGET_MS:.0f}ms)"
    )

    assert dashboard_p95 < _P95_BUDGET_MS, (
        f"GET /dashboard p95 {dashboard_p95:.1f}ms exceeds the {_P95_BUDGET_MS:.0f}ms "
        "P2-NFR-01 budget under 150 sessions / 2,700 sets / 365 weight entries -- see "
        "this module's docstring on workout_sets' parent-EXISTS RLS policy as the "
        "likely cause. Report this number; do not add an index or change the policy "
        "to make this assertion pass without that being a reviewed decision."
    )
    assert workouts_active_p95 < _P95_BUDGET_MS, (
        f"GET /workouts/active p95 {workouts_active_p95:.1f}ms exceeds the "
        f"{_P95_BUDGET_MS:.0f}ms P2-NFR-01 budget."
    )
