"""spec §6, P2-ADR-01: the plan generator. One pure function, `generate_plan`, taking
`PlanInput` and returning `GeneratedPlan`. No I/O, no randomness, no network, and --
per P2-ADR-01's boundary -- nothing imported from `models/`, `repositories/` or
`routers/`; this module imports only the standard library.

The exercise "lookup table" P2-ADR-01 refers to lives entirely below, as
`_SLOT_CANDIDATES`: for every §6.3 slot, a fixed-priority list of (slug, difficulty,
primary_muscle) drawn from the T-16 seed library (`backend/app/data/exercises.json`).
`available_exercise_slugs` (passed in, never queried) filters that fixed list down to
what the caller says actually exists -- which is what keeps this function pure and lets
a test drive it with a five-exercise library, per §6.1.

>>> ⚠️  §6.4's sets/reps/rest table is transcribed here verbatim from a table the spec's
>>> own warning box calls unreviewed by anyone who trains. Do not "fix" a number that
>>> looks off -- a correction is a version bump (`GENERATOR_VERSION`), not a silent edit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, cast

ExperienceLevel = Literal["beginner", "intermediate", "advanced"]
Goal = Literal["lose", "gain", "maintain"]
ActivityLevel = Literal["sedentary", "light", "moderate", "high", "very_high"]

GENERATOR_VERSION: Final[int] = 1

_BEGINNER_DAY_CAP: Final[int] = 4
_BEGINNER_CAPPED_NOTES_KEY: Final[str] = "plan.notes.beginnerCappedDays"
_REST_FLOOR_SECONDS: Final[int] = 30
_REST_CAP_SECONDS: Final[int] = 300
_MINOR_AGE: Final[int] = 18


class PlanGenerationError(Exception):
    """§6.1/§6.4/§6.5: raised when the library cannot satisfy a required slot, when a
    composed week would exceed §6.4's per-muscle ceiling, or when P2-SAF-002's asserted
    invariant (no `lose` plan for a minor) is violated. Never caught inside this module;
    the caller (program_service, T-17) decides how to surface it."""


# --- §6.1 input / output shapes ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanInput:
    experience_level: ExperienceLevel
    goal: Goal
    activity_level: ActivityLevel
    days_per_week: int
    age: int
    available_exercise_slugs: frozenset[str]


@dataclass(frozen=True, slots=True)
class GeneratedExercise:
    slug: str
    position: int
    is_compound: bool
    target_sets: int
    target_reps_min: int
    target_reps_max: int
    rest_seconds: int


@dataclass(frozen=True, slots=True)
class GeneratedDay:
    day_index: int
    label_key: str
    focus_muscles: tuple[str, ...]
    exercises: tuple[GeneratedExercise, ...]


@dataclass(frozen=True, slots=True)
class GeneratedPlan:
    split_type: str
    generator_version: int
    days: tuple[GeneratedDay, ...]
    # §6.2: "the response's notes_key explains why" -- e.g. the beginner day cap. Never
    # includes a deficit/weight-loss key (§6.5, P2-SAF-002).
    notes_keys: tuple[str, ...]
    # Exposed so a caller can run its own belt-and-braces recheck (§5.3) against
    # independently-sourced muscle data, without duplicating this module's private table.
    ceiling_sets_per_muscle_per_week: int


# --- §6.2 split selection ----------------------------------------------------------------

_SPLIT_TABLE: Final[dict[int, tuple[str, tuple[str, ...]]]] = {
    2: ("full_body", ("full_body", "full_body")),
    3: ("full_body", ("full_body", "full_body", "full_body")),
    4: ("upper_lower", ("upper", "lower", "upper", "lower")),
    5: ("upper_lower", ("upper", "lower", "full_body", "upper", "lower")),
    6: ("push_pull_legs", ("push", "pull", "legs", "push", "pull", "legs")),
}

_DAY_LABEL_KEYS: Final[dict[str, str]] = {
    "full_body": "plan.day.fullBody",
    "upper": "plan.day.upper",
    "lower": "plan.day.lower",
    "push": "plan.day.push",
    "pull": "plan.day.pull",
    "legs": "plan.day.legs",
}

# --- §6.3 day composition: fixed slot order per day type ---------------------------------
#
# A slot is ("pattern", movement_pattern) or ("isolation", primary_muscle). Isolation
# slots are last in every row below, which is what gives "compounds first" for free from
# the fixed order itself, rather than a second sorting pass.

_Slot = tuple[str, str]

_DAY_SLOTS: Final[dict[str, tuple[_Slot, ...]]] = {
    "full_body": (
        ("pattern", "squat"),
        ("pattern", "horizontal_push"),
        ("pattern", "horizontal_pull"),
        ("pattern", "hinge"),
        ("isolation", "abs"),
    ),
    "upper": (
        ("pattern", "horizontal_push"),
        ("pattern", "vertical_pull"),
        ("pattern", "vertical_push"),
        ("pattern", "horizontal_pull"),
        ("isolation", "biceps"),
        ("isolation", "triceps"),
    ),
    "lower": (
        ("pattern", "squat"),
        ("pattern", "hinge"),
        ("pattern", "lunge"),
        ("isolation", "calves"),
        ("isolation", "abs"),
    ),
    "push": (
        ("pattern", "horizontal_push"),
        ("pattern", "vertical_push"),
        ("isolation", "side_delts"),
        ("isolation", "triceps"),
    ),
    "pull": (
        ("pattern", "vertical_pull"),
        ("pattern", "horizontal_pull"),
        ("isolation", "rear_delts"),
        ("isolation", "biceps"),
    ),
    "legs": (
        ("pattern", "squat"),
        ("pattern", "hinge"),
        ("pattern", "lunge"),
        ("isolation", "calves"),
    ),
}


@dataclass(frozen=True, slots=True)
class _Candidate:
    slug: str
    difficulty: ExperienceLevel
    primary_muscle: str


_DIFFICULTY_RANK: Final[dict[ExperienceLevel, int]] = {
    "beginner": 0,
    "intermediate": 1,
    "advanced": 2,
}

# The lookup table itself (P2-ADR-01): every slug below is drawn from
# backend/app/data/exercises.json (T-16), in priority order per slot -- index 0 is the
# day-A pick, index 1 is day-B's (§6.3's "second-priority exercise where one exists").
_SLOT_CANDIDATES: Final[dict[_Slot, tuple[_Candidate, ...]]] = {
    ("pattern", "squat"): (
        _Candidate("barbell-back-squat", "beginner", "quads"),
        _Candidate("leg-press", "beginner", "quads"),
        _Candidate("dumbbell-goblet-squat", "beginner", "quads"),
        _Candidate("bodyweight-squat", "beginner", "quads"),
        _Candidate("barbell-front-squat", "intermediate", "quads"),
    ),
    ("pattern", "hinge"): (
        _Candidate("barbell-deadlift", "intermediate", "hamstrings"),
        _Candidate("romanian-deadlift", "intermediate", "hamstrings"),
        _Candidate("kettlebell-swing", "beginner", "glutes"),
        _Candidate("good-morning", "advanced", "hamstrings"),
    ),
    ("pattern", "horizontal_push"): (
        _Candidate("barbell-bench-press", "beginner", "chest"),
        _Candidate("dumbbell-bench-press", "beginner", "chest"),
        _Candidate("machine-chest-press", "beginner", "chest"),
        _Candidate("push-up", "beginner", "chest"),
        _Candidate("incline-barbell-bench-press", "intermediate", "chest"),
    ),
    ("pattern", "vertical_push"): (
        _Candidate("dumbbell-shoulder-press", "beginner", "front_delts"),
        _Candidate("machine-shoulder-press", "beginner", "front_delts"),
        _Candidate("barbell-overhead-press", "intermediate", "front_delts"),
    ),
    ("pattern", "horizontal_pull"): (
        _Candidate("seated-cable-row", "beginner", "back"),
        _Candidate("dumbbell-row", "beginner", "back"),
        _Candidate("machine-row", "beginner", "back"),
        _Candidate("barbell-bent-over-row", "intermediate", "back"),
        _Candidate("inverted-row", "intermediate", "back"),
    ),
    ("pattern", "vertical_pull"): (
        _Candidate("lat-pulldown", "beginner", "lats"),
        _Candidate("pull-up", "advanced", "lats"),
        _Candidate("chin-up", "advanced", "lats"),
    ),
    ("pattern", "lunge"): (
        _Candidate("dumbbell-walking-lunge", "beginner", "quads"),
        _Candidate("kettlebell-lunge", "beginner", "quads"),
        _Candidate("barbell-reverse-lunge", "intermediate", "quads"),
    ),
    ("isolation", "abs"): (
        _Candidate("plank", "beginner", "abs"),
        _Candidate("cable-crunch", "beginner", "abs"),
        _Candidate("hanging-leg-raise", "intermediate", "abs"),
    ),
    ("isolation", "biceps"): (
        _Candidate("dumbbell-bicep-curl", "beginner", "biceps"),
        _Candidate("barbell-bicep-curl", "beginner", "biceps"),
        _Candidate("cable-bicep-curl", "beginner", "biceps"),
    ),
    ("isolation", "triceps"): (
        _Candidate("triceps-pushdown", "beginner", "triceps"),
        _Candidate("overhead-triceps-extension", "beginner", "triceps"),
        _Candidate("skull-crusher", "intermediate", "triceps"),
    ),
    ("isolation", "calves"): (
        _Candidate("calf-raise", "beginner", "calves"),
        _Candidate("standing-calf-raise", "beginner", "calves"),
    ),
    ("isolation", "side_delts"): (
        _Candidate("lateral-raise", "beginner", "side_delts"),
        _Candidate("cable-lateral-raise", "beginner", "side_delts"),
        _Candidate("band-lateral-raise", "beginner", "side_delts"),
    ),
    ("isolation", "rear_delts"): (
        _Candidate("rear-delt-fly", "beginner", "rear_delts"),
        _Candidate("face-pull", "beginner", "rear_delts"),
        _Candidate("machine-rear-delt-fly", "beginner", "rear_delts"),
    ),
}


# --- §6.4 sets, reps and rest --------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Prescription:
    compound_sets: int
    compound_reps: tuple[int, int]
    isolation_sets: int
    isolation_reps: tuple[int, int]
    compound_rest_seconds: int
    isolation_rest_seconds: int
    ceiling_sets_per_muscle_per_week: int


_GoalBucket = Literal["any", "gain", "lose_maintain"]

# Transcribed verbatim from §6.4's table. Do not "improve" a number here -- see this
# module's docstring and this task's report for the number that looks wrong.
_PRESCRIPTIONS: Final[dict[tuple[ExperienceLevel, _GoalBucket], _Prescription]] = {
    ("beginner", "any"): _Prescription(3, (8, 12), 2, (10, 15), 120, 60, 12),
    ("intermediate", "gain"): _Prescription(4, (6, 10), 3, (10, 15), 150, 75, 18),
    ("intermediate", "lose_maintain"): _Prescription(3, (8, 12), 3, (12, 15), 90, 60, 16),
    ("advanced", "gain"): _Prescription(5, (4, 8), 3, (8, 12), 180, 90, 22),
    ("advanced", "lose_maintain"): _Prescription(4, (6, 10), 3, (12, 15), 120, 75, 20),
}


def _prescription_for(experience_level: ExperienceLevel, goal: Goal) -> _Prescription:
    if experience_level == "beginner":
        return _PRESCRIPTIONS[("beginner", "any")]
    bucket: _GoalBucket = "gain" if goal == "gain" else "lose_maintain"
    return _PRESCRIPTIONS[(experience_level, bucket)]


def adjust_rest_seconds(base_seconds: int, activity_level: ActivityLevel) -> int:
    """§6.4: "activity_level adjusts rest only -- sedentary/light add 15 seconds ...
    high/very_high subtract 15, floored at 30 and capped at 300 (§4.5)." """
    if activity_level in ("sedentary", "light"):
        adjusted = base_seconds + 15
    elif activity_level in ("high", "very_high"):
        adjusted = base_seconds - 15
    else:
        adjusted = base_seconds
    return max(_REST_FLOOR_SECONDS, min(_REST_CAP_SECONDS, adjusted))


# --- selection -----------------------------------------------------------------------------


def _select_candidate(
    slot: _Slot,
    variant_index: int,
    experience_level: ExperienceLevel,
    available_exercise_slugs: frozenset[str],
) -> _Candidate:
    """§6.3: "the highest-priority available exercise for each slot ... that the user's
    experience level permits ... preferring compounds" -- compound preference is already
    encoded in slot order (see `_DAY_SLOTS`), so this only filters by availability and
    difficulty, then by priority. `variant_index` is 0 for a day's first occurrence in
    the week (the "A" day) and 1 for its second ("B"); §6.3: "use the second-priority
    exercise for each slot where one exists" -- clamped to the last permitted candidate
    when a second one does not exist, so an A/B pair with only one option reuses it.
    """
    max_rank = _DIFFICULTY_RANK[experience_level]
    permitted = [
        candidate
        for candidate in _SLOT_CANDIDATES[slot]
        if candidate.slug in available_exercise_slugs
        and _DIFFICULTY_RANK[candidate.difficulty] <= max_rank
    ]
    if not permitted:
        kind, value = slot
        pattern_description = value if kind == "pattern" else f"isolation:{value}"
        raise PlanGenerationError(
            f"no available exercise satisfies the '{pattern_description}' slot "
            f"for experience_level={experience_level}"
        )
    index = min(variant_index, len(permitted) - 1)
    return permitted[index]


def generate_plan(spec: PlanInput) -> GeneratedPlan:
    """§6: the one entry point. Deterministic -- the same `PlanInput` always produces an
    equal `GeneratedPlan` (every field below is built from fixed tables and `spec`
    alone, in a fixed order; no set/dict iteration order is ever exposed in the output).
    """
    # §6.5, P2-SAF-002: "the generator asserts it anyway and raises if it sees it,
    # because a safety check that exists in exactly one place is one refactor away from
    # existing in none." P1-SAF-001 already blocks this at the profile layer.
    if spec.age < _MINOR_AGE and spec.goal == "lose":
        raise PlanGenerationError(
            "goal 'lose' is not permitted for an account under 18 (P2-SAF-002)"
        )

    notes_keys: list[str] = []
    days_per_week = spec.days_per_week
    if spec.experience_level == "beginner" and days_per_week > _BEGINNER_DAY_CAP:
        # §6.2: "a cap, not a rejection."
        days_per_week = _BEGINNER_DAY_CAP
        notes_keys.append(_BEGINNER_CAPPED_NOTES_KEY)

    split_type, day_type_sequence = _SPLIT_TABLE[days_per_week]
    prescription = _prescription_for(spec.experience_level, spec.goal)

    occurrence_counts: dict[str, int] = {}
    muscle_set_totals: dict[str, int] = {}
    days: list[GeneratedDay] = []

    for day_index, day_type in enumerate(day_type_sequence, start=1):
        variant_index = min(occurrence_counts.get(day_type, 0), 1)
        occurrence_counts[day_type] = occurrence_counts.get(day_type, 0) + 1

        exercises: list[GeneratedExercise] = []
        focus_muscles: list[str] = []
        for position, slot in enumerate(_DAY_SLOTS[day_type], start=1):
            candidate = _select_candidate(
                slot, variant_index, spec.experience_level, spec.available_exercise_slugs
            )
            is_isolation = slot[0] == "isolation"
            sets = prescription.isolation_sets if is_isolation else prescription.compound_sets
            reps_min, reps_max = (
                prescription.isolation_reps if is_isolation else prescription.compound_reps
            )
            rest_seconds = adjust_rest_seconds(
                prescription.isolation_rest_seconds
                if is_isolation
                else prescription.compound_rest_seconds,
                spec.activity_level,
            )

            exercises.append(
                GeneratedExercise(
                    slug=candidate.slug,
                    position=position,
                    is_compound=not is_isolation,
                    target_sets=sets,
                    target_reps_min=reps_min,
                    target_reps_max=reps_max,
                    rest_seconds=rest_seconds,
                )
            )
            muscle_set_totals[candidate.primary_muscle] = (
                muscle_set_totals.get(candidate.primary_muscle, 0) + sets
            )
            if candidate.primary_muscle not in focus_muscles:
                focus_muscles.append(candidate.primary_muscle)

        days.append(
            GeneratedDay(
                day_index=day_index,
                label_key=_DAY_LABEL_KEYS[day_type],
                focus_muscles=tuple(focus_muscles),
                exercises=tuple(exercises),
            )
        )

    # §6.4: "The ceiling is checked, not assumed ... Exceeding it is a
    # PlanGenerationError, which is a bug in the table."
    for muscle, total_sets in muscle_set_totals.items():
        if total_sets > prescription.ceiling_sets_per_muscle_per_week:
            raise PlanGenerationError(
                f"{muscle} would receive {total_sets} sets/week, exceeding the "
                f"{prescription.ceiling_sets_per_muscle_per_week}-set ceiling for "
                f"experience_level={spec.experience_level}, goal={spec.goal}"
            )

    return GeneratedPlan(
        split_type=split_type,
        generator_version=GENERATOR_VERSION,
        days=tuple(days),
        notes_keys=tuple(notes_keys),
        ceiling_sets_per_muscle_per_week=prescription.ceiling_sets_per_muscle_per_week,
    )


# Re-exported so callers that only have the base Literal-eligible strings from a database
# column (e.g. program_service.py, reading `profiles.experience_level: str`) can narrow
# them for `PlanInput` without this module depending on anything outside itself.
def as_experience_level(value: str) -> ExperienceLevel:
    return cast(ExperienceLevel, value)


def as_goal(value: str) -> Goal:
    return cast(Goal, value)


def as_activity_level(value: str) -> ActivityLevel:
    return cast(ActivityLevel, value)
