"""Unit tests for app.services.metrics -- P2-ADR-04's pure derived-number functions
(T-18). No database and no fixtures beyond plain values: metrics.py takes no
dependency on models/, matching plan_generator.py's own P2-ADR-01 boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from app.services import metrics


def test_estimate_one_rep_max_uses_the_epley_formula() -> None:
    # spec §5.7's own worked example: weight_kg=60, reps=8 -> e1rm_kg=76.
    assert metrics.estimate_one_rep_max(Decimal("60"), 8) == Decimal("76")


def test_estimate_one_rep_max_at_one_rep_is_above_the_weight_lifted() -> None:
    # Epley's formula never returns exactly the weight lifted except at reps=0; at
    # reps=1 it is weight * 31/30 = 103.333..., quantized to 103.33 (two decimal
    # places, weight_kg's own Numeric(6,2) precision) -- a small but real markup over
    # the raw weight.
    result = metrics.estimate_one_rep_max(Decimal("100"), 1)
    assert result == Decimal("103.33")
    assert result > Decimal("100")


def test_set_volume_kg_is_reps_times_weight() -> None:
    # spec §5.7's own worked example: weight_kg=60, reps=8 -> volume_kg=480.
    assert metrics.set_volume_kg(Decimal("60"), 8) == Decimal("480")


def test_session_volume_kg_sums_only_non_warmup_sets() -> None:
    sets = [
        metrics.SetMetricInput(weight_kg=Decimal("20"), reps=10, is_warmup=True),
        metrics.SetMetricInput(weight_kg=Decimal("60"), reps=8, is_warmup=False),
        metrics.SetMetricInput(weight_kg=Decimal("60"), reps=6, is_warmup=False),
    ]
    assert metrics.session_volume_kg(sets) == Decimal("480") + Decimal("360")


def test_session_volume_kg_of_an_all_warmup_session_is_zero() -> None:
    sets = [metrics.SetMetricInput(weight_kg=Decimal("20"), reps=10, is_warmup=True)]
    assert metrics.session_volume_kg(sets) == Decimal("0")


def test_session_volume_kg_of_no_sets_is_zero() -> None:
    assert metrics.session_volume_kg([]) == Decimal("0")


def test_session_duration_is_last_logged_at_minus_started_at() -> None:
    started_at = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    last_logged_at = datetime(2026, 8, 13, 18, 40, tzinfo=UTC)
    assert metrics.session_duration_seconds(started_at, last_logged_at) == 40 * 60


def test_session_duration_ignores_a_finish_the_next_morning() -> None:
    # This task's own "done when": a session whose last set was logged at 18:40 but
    # finished the next morning at 09:00 reports its real (40-minute) duration.
    # ended_at is never even passed to this function, so there is nothing here that
    # could leak the fourteen-hour gap in.
    started_at = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    last_logged_at = datetime(2026, 8, 13, 18, 40, tzinfo=UTC)
    duration = metrics.session_duration_seconds(started_at, last_logged_at)
    assert duration == 2400

    ended_at_next_morning = datetime(2026, 8, 14, 9, 0, tzinfo=UTC)
    assert duration != int((ended_at_next_morning - started_at).total_seconds())


def test_session_duration_is_zero_with_no_sets() -> None:
    started_at = datetime(2026, 8, 13, 18, 0, tzinfo=UTC)
    assert metrics.session_duration_seconds(started_at, None) == 0
