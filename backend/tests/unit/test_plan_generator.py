"""spec §6 (the plan generator, P2-ADR-01). Pure function, no I/O, so this file needs
no database -- see plan_generator.py's own docstring for the boundary this protects.

T-17b's own "done when": a unit test drives all 225 input combinations (3 experience
levels x 3 goals x 5 activity levels x 5 day counts, matching §6.4's own "a unit test
over all 225 input combinations" and P2-ADR-01's "5 day counts" accounting) and asserts:
the ceiling, slot completeness, ordering, the beginner cap, A/B difference and
determinism.

Every days_per_week from 2 to 6 is now in the sweep, none excluded. T-17 had held
days_per_week=5 out of the matrix because the 5-day split's original full-body middle
day gave quads a third compound exposure and could exceed §6.4's ceiling for a
gain-focused plan -- see the "Why the 5-day split has no full-body day" note under
§6.3. That was a defect in the split table, now fixed by replacing the middle day with
an isolation-only Arms & delts day, so days_per_week=5 is exhaustively covered like
every other day count.
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from app.services.plan_generator import (
    GENERATOR_VERSION,
    ActivityLevel,
    ExperienceLevel,
    Goal,
    PlanGenerationError,
    PlanInput,
    adjust_rest_seconds,
    generate_plan,
)

_EXPERIENCE_LEVELS: tuple[ExperienceLevel, ...] = ("beginner", "intermediate", "advanced")
_GOALS: tuple[Goal, ...] = ("lose", "gain", "maintain")
_ACTIVITY_LEVELS: tuple[ActivityLevel, ...] = (
    "sedentary",
    "light",
    "moderate",
    "high",
    "very_high",
)
_DAYS_PER_WEEK: tuple[int, ...] = (2, 3, 4, 5, 6)

_LABEL_KEY_TO_SLOT_COUNT: dict[str, int] = {
    "plan.day.fullBody": 5,
    "plan.day.upper": 6,
    "plan.day.lower": 5,
    "plan.day.push": 4,
    "plan.day.pull": 4,
    "plan.day.legs": 4,
    "plan.day.armsDelts": 5,
}


def _seed_data() -> list[dict[str, object]]:
    data_path = Path(__file__).resolve().parents[2] / "app" / "data" / "exercises.json"
    loaded: list[dict[str, object]] = json.loads(data_path.read_text(encoding="utf-8"))
    return loaded


def _seed_slugs() -> frozenset[str]:
    return frozenset(str(row["slug"]) for row in _seed_data() if row["is_active"])


def _slug_to_primary_muscle() -> dict[str, str]:
    return {str(row["slug"]): str(row["primary_muscle"]) for row in _seed_data()}


_FULL_LIBRARY: frozenset[str] = _seed_slugs()
_MUSCLE_OF: dict[str, str] = _slug_to_primary_muscle()


def _spec(
    *,
    experience_level: ExperienceLevel,
    goal: Goal,
    activity_level: ActivityLevel,
    days_per_week: int,
    age: int = 30,
    available: frozenset[str] | None = None,
) -> PlanInput:
    return PlanInput(
        experience_level=experience_level,
        goal=goal,
        activity_level=activity_level,
        days_per_week=days_per_week,
        age=age,
        available_exercise_slugs=available if available is not None else _FULL_LIBRARY,
    )


_COMBINATIONS: list[tuple[ExperienceLevel, Goal, ActivityLevel, int]] = list(
    itertools.product(_EXPERIENCE_LEVELS, _GOALS, _ACTIVITY_LEVELS, _DAYS_PER_WEEK)
)
_COMBINATION_IDS = [f"{e}-{g}-{a}-{d}d" for e, g, a, d in _COMBINATIONS]


@pytest.mark.parametrize(
    "experience_level,goal,activity_level,days_per_week", _COMBINATIONS, ids=_COMBINATION_IDS
)
def test_every_combination_satisfies_the_generator_contract(
    experience_level: ExperienceLevel,
    goal: Goal,
    activity_level: ActivityLevel,
    days_per_week: int,
) -> None:
    """One test per combination, covering everything this task's "done when" names
    except the ceiling (its own dedicated parametrized test below, since it needs an
    independently-sourced muscle map rather than the generator's internal one)."""
    spec = _spec(
        experience_level=experience_level,
        goal=goal,
        activity_level=activity_level,
        days_per_week=days_per_week,
    )

    plan = generate_plan(spec)

    # determinism: the same input produces an equal (dataclass __eq__, deep) output.
    assert generate_plan(spec) == plan

    expected_day_count = min(days_per_week, 4) if experience_level == "beginner" else days_per_week
    assert len(plan.days) == expected_day_count
    assert plan.generator_version == GENERATOR_VERSION

    for day_position, day in enumerate(plan.days, start=1):
        assert day.day_index == day_position

        # slot completeness: no day is short a slot for its type.
        expected_slot_count = _LABEL_KEY_TO_SLOT_COUNT[day.label_key]
        assert len(day.exercises) == expected_slot_count

        # ordering: compounds precede isolation, with no isolation exercise appearing
        # before a compound one.
        seen_isolation = False
        for exercise in day.exercises:
            if seen_isolation:
                assert not exercise.is_compound, (
                    f"day {day.day_index}: an isolation exercise precedes a compound one"
                )
            seen_isolation = seen_isolation or not exercise.is_compound

        # every exercise chosen must actually be one the caller said was available.
        for exercise in day.exercises:
            assert exercise.slug in _FULL_LIBRARY


@pytest.mark.parametrize(
    "experience_level,goal,activity_level,days_per_week", _COMBINATIONS, ids=_COMBINATION_IDS
)
def test_every_combination_holds_the_volume_ceiling_independently_recomputed(
    experience_level: ExperienceLevel,
    goal: Goal,
    activity_level: ActivityLevel,
    days_per_week: int,
) -> None:
    """§6.4: "the ceiling is checked, not assumed." `generate_plan` already raises if it
    is exceeded (proven by every combination above completing without raising); this
    recomputes the same total from a muscle map sourced independently of the
    generator's own internal table -- the same shape of belt-and-braces check
    program_service performs before persisting (§5.3) -- so a bug shared between the
    generator's table and its own ceiling check could not hide from both.
    """
    spec = _spec(
        experience_level=experience_level,
        goal=goal,
        activity_level=activity_level,
        days_per_week=days_per_week,
    )
    plan = generate_plan(spec)

    totals: dict[str, int] = {}
    for day in plan.days:
        for exercise in day.exercises:
            muscle = _MUSCLE_OF[exercise.slug]
            totals[muscle] = totals.get(muscle, 0) + exercise.target_sets

    for muscle, total in totals.items():
        assert total <= plan.ceiling_sets_per_muscle_per_week, (
            f"{muscle}: {total} sets/week exceeds the "
            f"{plan.ceiling_sets_per_muscle_per_week}-set ceiling "
            f"({experience_level}/{goal}, {days_per_week}d)"
        )


# --- the beginner day cap (§6.2, P2-SAF-003) ------------------------------------------------


@pytest.mark.parametrize("requested_days", [5, 6])
def test_beginner_over_four_days_is_capped_with_notes_key(requested_days: int) -> None:
    plan = generate_plan(
        _spec(
            experience_level="beginner",
            goal="maintain",
            activity_level="moderate",
            days_per_week=requested_days,
        )
    )
    assert len(plan.days) == 4
    assert plan.split_type == "upper_lower"
    assert "plan.notes.beginnerCappedDays" in plan.notes_keys


def test_beginner_at_four_days_is_not_capped() -> None:
    plan = generate_plan(
        _spec(
            experience_level="beginner",
            goal="maintain",
            activity_level="moderate",
            days_per_week=4,
        )
    )
    assert len(plan.days) == 4
    assert plan.notes_keys == ()


def test_non_beginner_is_never_capped() -> None:
    plan = generate_plan(
        _spec(
            experience_level="advanced",
            goal="gain",
            activity_level="moderate",
            days_per_week=6,
        )
    )
    assert len(plan.days) == 6
    assert plan.notes_keys == ()


# --- A/B variants (§6.3) ---------------------------------------------------------------------


def test_ab_variant_differs_when_a_second_priority_candidate_exists() -> None:
    """Intermediate, 4-day upper_lower: Upper A and Upper B. The horizontal_push slot
    has multiple intermediate-permitted candidates, so the two days must not be
    identical."""
    plan = generate_plan(
        _spec(
            experience_level="intermediate",
            goal="gain",
            activity_level="moderate",
            days_per_week=4,
        )
    )
    upper_days = [day for day in plan.days if day.label_key == "plan.day.upper"]
    assert len(upper_days) == 2
    upper_a_slugs = [exercise.slug for exercise in upper_days[0].exercises]
    upper_b_slugs = [exercise.slug for exercise in upper_days[1].exercises]
    assert upper_a_slugs != upper_b_slugs


def test_ab_variant_reuses_same_exercise_when_only_one_candidate_exists() -> None:
    """Beginner, hinge slot: only kettlebell-swing is beginner-permitted, so Lower A
    and Lower B's hinge pick must be identical -- "the second-priority exercise ...
    where one exists" (§6.3) leaves it unchanged where one does not."""
    plan = generate_plan(
        _spec(
            experience_level="beginner",
            goal="maintain",
            activity_level="moderate",
            days_per_week=4,
        )
    )
    lower_days = [day for day in plan.days if day.label_key == "plan.day.lower"]
    assert len(lower_days) == 2
    # hinge is the second slot in the "lower" day (§6.3: squat, hinge, lunge, ...).
    assert lower_days[0].exercises[1].slug == "kettlebell-swing"
    assert lower_days[1].exercises[1].slug == "kettlebell-swing"


# --- P2-SAF-002: minors ----------------------------------------------------------------------


def test_minor_with_lose_goal_raises_plan_generation_error() -> None:
    with pytest.raises(PlanGenerationError):
        generate_plan(
            _spec(
                experience_level="beginner",
                goal="lose",
                activity_level="moderate",
                days_per_week=3,
                age=16,
            )
        )


def test_minor_with_maintain_goal_is_permitted() -> None:
    plan = generate_plan(
        _spec(
            experience_level="beginner",
            goal="maintain",
            activity_level="moderate",
            days_per_week=3,
            age=16,
        )
    )
    assert len(plan.days) == 3


# --- a five-exercise library (§6.1: "lets a test drive it with a five-exercise library") -----


_FIVE_EXERCISE_LIBRARY = frozenset(
    {
        "barbell-back-squat",  # squat
        "barbell-bench-press",  # horizontal_push
        "seated-cable-row",  # horizontal_pull
        "kettlebell-swing",  # hinge
        "plank",  # isolation:abs
    }
)


def test_five_exercise_library_produces_a_valid_two_day_plan() -> None:
    plan = generate_plan(
        _spec(
            experience_level="beginner",
            goal="maintain",
            activity_level="moderate",
            days_per_week=2,
            available=_FIVE_EXERCISE_LIBRARY,
        )
    )
    assert len(plan.days) == 2
    for day in plan.days:
        assert {exercise.slug for exercise in day.exercises} == _FIVE_EXERCISE_LIBRARY


def test_insufficient_library_raises_plan_generation_error_naming_the_pattern() -> None:
    """The five-exercise library above has no vertical_pull candidate at all, so a
    4-day upper_lower plan (which needs one) must fail loudly rather than silently
    produce a short day."""
    with pytest.raises(PlanGenerationError, match="vertical_pull"):
        generate_plan(
            _spec(
                experience_level="intermediate",
                goal="maintain",
                activity_level="moderate",
                days_per_week=4,
                available=_FIVE_EXERCISE_LIBRARY,
            )
        )


# --- days_per_week=5, all goals (§6.3's fix for the T-17 finding) --------------------------


@pytest.mark.parametrize(
    "experience_level,goal",
    [
        ("intermediate", "lose"),
        ("intermediate", "maintain"),
        ("intermediate", "gain"),
        ("advanced", "lose"),
        ("advanced", "maintain"),
        ("advanced", "gain"),
    ],
)
def test_days_per_week_five_holds_for_every_goal(
    experience_level: ExperienceLevel, goal: Goal
) -> None:
    """T-17 found that the 5-day split's original full-body middle day gave quads a
    third compound exposure, exceeding the ceiling for gain-focused plans at both
    levels that can reach 5 days (see the "Why the 5-day split has no full-body day"
    note under §6.3). §6.3 now replaces that middle day with an isolation-only Arms &
    delts day, which removes the third quad exposure entirely -- this test targets
    exactly the combinations that used to fail, gain included, and asserts they now
    produce a real plan rather than a `PlanGenerationError`."""
    plan = generate_plan(
        _spec(
            experience_level=experience_level,
            goal=goal,
            activity_level="moderate",
            days_per_week=5,
        )
    )
    assert len(plan.days) == 5


# --- §6.4: activity_level adjusts rest only ---------------------------------------------------


def test_activity_level_only_adjusts_rest_not_sets_or_reps() -> None:
    baseline = generate_plan(
        _spec(
            experience_level="intermediate",
            goal="gain",
            activity_level="moderate",
            days_per_week=4,
        )
    )
    sedentary = generate_plan(
        _spec(
            experience_level="intermediate",
            goal="gain",
            activity_level="sedentary",
            days_per_week=4,
        )
    )
    very_high = generate_plan(
        _spec(
            experience_level="intermediate",
            goal="gain",
            activity_level="very_high",
            days_per_week=4,
        )
    )

    for base_day, sed_day, vh_day in zip(
        baseline.days, sedentary.days, very_high.days, strict=True
    ):
        for base_ex, sed_ex, vh_ex in zip(
            base_day.exercises, sed_day.exercises, vh_day.exercises, strict=True
        ):
            assert base_ex.slug == sed_ex.slug == vh_ex.slug
            assert base_ex.target_sets == sed_ex.target_sets == vh_ex.target_sets
            assert base_ex.target_reps_min == sed_ex.target_reps_min == vh_ex.target_reps_min
            assert base_ex.target_reps_max == sed_ex.target_reps_max == vh_ex.target_reps_max
            assert sed_ex.rest_seconds == base_ex.rest_seconds + 15
            assert vh_ex.rest_seconds == base_ex.rest_seconds - 15


def test_rest_seconds_are_floored_and_capped() -> None:
    assert adjust_rest_seconds(30, "very_high") == 30  # would be 15 uncapped; floored at 30
    assert adjust_rest_seconds(300, "sedentary") == 300  # would be 315 uncapped; capped at 300
