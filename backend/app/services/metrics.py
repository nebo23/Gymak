"""spec §4.7's note and P2-ADR-04: derived numbers -- e1RM, set volume, session
volume -- are computed on read, never stored. This module holds that arithmetic as
pure functions: no I/O, no randomness, no network, and no import from `models/`,
`repositories/` or `routers/` -- the same boundary P2-ADR-01 states explicitly for
`plan_generator.py`, applied here for the same reason (trivial to unit-test, nothing
to mock).

`session_duration_seconds` lives here too, even though §12's T-18 task text names
only e1RM/set volume/session volume: it is exactly this kind of pure, easily-misread
arithmetic (§5.8: "last_logged_at - started_at, not ended_at - started_at"), and
isolating it here is what makes it independently unit-testable in
tests/unit/test_metrics.py rather than only exercised indirectly through HTTP.

>>> Epley is the reviewed default (P2-ADR-04's own note: "a reasonable default and
>>> Brzycki is a defensible alternative"). Do not swap it for another formula without
>>> a spec change.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True, slots=True)
class SetMetricInput:
    """The three fields §4.7/P2-ADR-04's derived numbers actually need from a set --
    deliberately not `app.models.workout.WorkoutSet` itself, so this module takes no
    dependency on `models/` (see the module docstring's boundary note)."""

    weight_kg: Decimal
    reps: int
    is_warmup: bool


def estimate_one_rep_max(weight_kg: Decimal, reps: int) -> Decimal:
    """P2-ADR-04: "Estimated one-rep max (Epley: weight x (1 + reps/30))." Quantized to
    two decimal places -- weight_kg's own Numeric(6,2) precision -- because reps/30 is
    a repeating decimal for most rep counts, and Decimal's default context otherwise
    leaves a trailing rounding artifact (e.g. 76.00000000000000000000000002) instead of
    the clean 76 the spec's own §5.7 worked example gives.
    """
    raw = weight_kg * (Decimal(30) + Decimal(reps)) / Decimal(30)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def set_volume_kg(weight_kg: Decimal, reps: int) -> Decimal:
    """P2-ADR-04: "set volume (reps x weight)." """
    return weight_kg * Decimal(reps)


def session_volume_kg(sets: Iterable[SetMetricInput]) -> Decimal:
    """P2-ADR-04/§5.8: "the sum over non-warm-up sets only." """
    total = Decimal("0")
    for one_set in sets:
        if not one_set.is_warmup:
            total += set_volume_kg(one_set.weight_kg, one_set.reps)
    return total


def session_duration_seconds(started_at: datetime, last_logged_at: datetime | None) -> int:
    """§5.8, verbatim: "duration_seconds is last_logged_at - started_at, not
    ended_at - started_at ... If the session has no sets, duration is zero." In
    practice `workout_service.finish_session` rejects an empty session before this
    can be called with `last_logged_at=None` (422 EMPTY_SESSION, this task's own
    requirement), but the zero-set case is still handled here directly per §5.8's
    own wording rather than assumed unreachable.
    """
    if last_logged_at is None:
        return 0
    return max(0, int((last_logged_at - started_at).total_seconds()))
