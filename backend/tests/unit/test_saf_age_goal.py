"""P1-SAF-001 at its boundaries (§11.1: "17y 364d, exactly 18, 18y 1d"). Pure functions,
no I/O -- app/services/profile_service.py deliberately keeps compute_age and
assert_goal_permitted free of any database or HTTP dependency so this file needs
neither.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.core.errors import GoalNotPermittedForMinorError
from app.services.profile_service import assert_goal_permitted, compute_age

# A fixed "now" so every boundary is pinned to a date, not a moving clock -- both
# functions take `today` as a parameter for exactly this reason.
_TODAY = date(2026, 7, 31)


# --- compute_age at the three named boundaries -------------------------------------------


def test_compute_age_at_17_years_364_days_is_17() -> None:
    # 18th birthday is one day in the future relative to _TODAY.
    assert compute_age(date(2008, 8, 1), today=_TODAY) == 17


def test_compute_age_at_exactly_18_years_is_18() -> None:
    # 18th birthday is today.
    assert compute_age(date(2008, 7, 31), today=_TODAY) == 18


def test_compute_age_at_18_years_1_day_is_18() -> None:
    # 18th birthday was yesterday.
    assert compute_age(date(2008, 7, 30), today=_TODAY) == 18


# --- assert_goal_permitted: the control this whole function exists for -------------------


def test_assert_goal_permitted_blocks_lose_at_17_years_364_days() -> None:
    with pytest.raises(GoalNotPermittedForMinorError) as exc_info:
        assert_goal_permitted(date(2008, 8, 1), "lose", today=_TODAY)
    assert "maintain" in exc_info.value.detail
    assert "gain" in exc_info.value.detail


def test_assert_goal_permitted_allows_lose_at_exactly_18() -> None:
    assert_goal_permitted(date(2008, 7, 31), "lose", today=_TODAY)  # must not raise


def test_assert_goal_permitted_allows_lose_at_18_years_1_day() -> None:
    assert_goal_permitted(date(2008, 7, 30), "lose", today=_TODAY)  # must not raise


def test_assert_goal_permitted_allows_maintain_and_gain_for_a_minor() -> None:
    minor_birth_date = date(2008, 8, 1)  # 17 years old relative to _TODAY
    assert_goal_permitted(minor_birth_date, "maintain", today=_TODAY)  # must not raise
    assert_goal_permitted(minor_birth_date, "gain", today=_TODAY)  # must not raise


def test_assert_goal_permitted_ignores_a_non_restricted_goal_regardless_of_age() -> None:
    # An adult choosing 'lose' is the unrestricted case either way; asserted here so the
    # function's branch on `goal == RESTRICTED_GOAL` is exercised for a goal other than
    # the three-value enum's only restricted member.
    assert_goal_permitted(date(1990, 1, 1), "maintain", today=_TODAY)  # must not raise
