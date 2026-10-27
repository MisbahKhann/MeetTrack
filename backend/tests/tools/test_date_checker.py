"""Tests for app.tools.date_checker.

All tests use as_of = 2026-10-05 (a Monday) unless stated otherwise.
"""

from datetime import date
from unittest.mock import patch

import pytest
from app.tools.date_checker import (
    classify_due,
    days_overdue,
    parse_as_of,
    resolve_due,
)

AS_OF = date(2026, 10, 5)  # Monday


# ---------------------------------------------------------------------------
# parse_as_of
# ---------------------------------------------------------------------------


def test_parse_as_of_valid() -> None:
    assert parse_as_of("2026-10-05") == date(2026, 10, 5)


def test_parse_as_of_invalid() -> None:
    with pytest.raises(ValueError, match="ISO date"):
        parse_as_of("05/10/2026")


# ---------------------------------------------------------------------------
# resolve_due -- parametrized cases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected_date,expected_status",
    [
        # Named weekdays -- strictly after as_of (Monday 2026-10-05)
        ("Friday", date(2026, 10, 9), "resolved"),
        ("by Friday", date(2026, 10, 9), "resolved"),
        ("fri", date(2026, 10, 9), "resolved"),
        # Monday is today -- so "Monday" means next Monday (7 days later)
        ("Monday", date(2026, 10, 12), "resolved"),
        # "next <weekday>" -- weekday in the week AFTER as_of's Mon-Sun week
        ("next Friday", date(2026, 10, 16), "resolved"),
        ("next Monday", date(2026, 10, 12), "resolved"),
        # Relative day keywords
        ("tomorrow", date(2026, 10, 6), "resolved"),
        ("today", date(2026, 10, 5), "resolved"),
        ("eod", date(2026, 10, 5), "resolved"),
        ("tonight", date(2026, 10, 5), "resolved"),
        # Named dates without year
        ("12 Oct", date(2026, 10, 12), "resolved"),
        ("12 October", date(2026, 10, 12), "resolved"),
        ("Oct 12", date(2026, 10, 12), "resolved"),
        ("20 Oct", date(2026, 10, 20), "resolved"),
        # Named date with explicit year in the past
        ("12 Oct 2025", date(2025, 10, 12), "resolved"),
        # Rollover: 1 Jan with as_of 2026-10-05; candidate 2026-01-01 is >183 days before
        ("1 Jan", date(2027, 1, 1), "resolved"),
        # Week-level approximates
        ("next week", date(2026, 10, 16), "approximate"),
        ("this week", date(2026, 10, 9), "approximate"),
        ("end of week", date(2026, 10, 9), "approximate"),
        ("eow", date(2026, 10, 9), "approximate"),
        # Month-level approximate
        ("end of month", date(2026, 10, 31), "approximate"),
        ("eom", date(2026, 10, 31), "approximate"),
        # Relative intervals
        ("in 2 weeks", date(2026, 10, 19), "resolved"),
        ("in 3 days", date(2026, 10, 8), "resolved"),
        # Unparseable vague strings
        ("soon", None, "unparseable"),
        ("asap", None, "unparseable"),
        ("sometime", None, "unparseable"),
        ("later", None, "unparseable"),
        # None and blank
        (None, None, "none"),
        ("", None, "none"),
        ("   ", None, "none"),
    ],
)
def test_resolve_due_cases(
    text: str | None, expected_date: date | None, expected_status: str
) -> None:
    result = resolve_due(text, AS_OF)
    assert result.due_date == expected_date, f"text={text!r}: date mismatch"
    assert result.status == expected_status, f"text={text!r}: status mismatch"


def test_resolve_due_impossible_date() -> None:
    result = resolve_due("31 Feb", AS_OF)
    assert result.status == "unparseable"


def test_resolve_due_too_long() -> None:
    result = resolve_due("x" * 101, AS_OF)
    assert result.status == "unparseable"


def test_resolve_due_in_past_flag() -> None:
    result = resolve_due("12 Oct 2025", AS_OF)
    assert result.in_past is True


def test_resolve_due_not_in_past() -> None:
    result = resolve_due("12 Oct", AS_OF)
    assert result.in_past is False


# ---------------------------------------------------------------------------
# Edge case: as_of is a Friday
# ---------------------------------------------------------------------------


def test_friday_means_next_week_when_as_of_is_friday() -> None:
    """When as_of is Friday, 'Friday' must resolve to 7 days later."""
    as_of_friday = date(2026, 10, 9)  # Friday
    result = resolve_due("Friday", as_of_friday)
    assert result.due_date == date(2026, 10, 16)


# ---------------------------------------------------------------------------
# classify_due
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "due,status,expected",
    [
        (None, "open", "no_date"),
        (date(2026, 9, 30), "open", "overdue"),        # before as_of
        (date(2026, 10, 5), "open", "due_today"),       # same as as_of
        (date(2026, 10, 7), "open", "due_soon"),        # within 3 days
        (date(2026, 10, 20), "open", "upcoming"),       # far future
        (date(2026, 9, 30), "done", "closed"),          # done even if past
        (None, "done", "closed"),                       # done with no date
    ],
)
def test_classify_due(due: date | None, status: str, expected: str) -> None:
    result = classify_due(due, AS_OF, status)
    assert result == expected


# ---------------------------------------------------------------------------
# days_overdue
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "due,status,expected",
    [
        (date(2026, 10, 3), "open", 2),       # 2 days overdue
        (date(2026, 10, 5), "open", 0),       # due today, not overdue
        (date(2026, 10, 7), "open", 0),       # future
        (None, "open", 0),
        (date(2026, 10, 3), "done", 0),       # done -- not counted
    ],
)
def test_days_overdue(due: date | None, status: str, expected: int) -> None:
    assert days_overdue(due, AS_OF, status) == expected


# ---------------------------------------------------------------------------
# No system clock access
# ---------------------------------------------------------------------------


def test_no_system_clock_access() -> None:
    """Verify that resolve_due, classify_due and days_overdue never call the clock.

    We patch datetime.date so that today() raises RuntimeError. If any function
    reads the system clock it will raise and the test fails.
    """
    import app.tools.date_checker as dc_module

    class NoClockDate(date):
        @classmethod
        def today(cls) -> "NoClockDate":  # type: ignore[override]
            raise RuntimeError("System clock must not be accessed in date_checker")

    # Patch the date class used inside the module
    with patch.object(dc_module, "date", NoClockDate):
        # These must not raise
        r = resolve_due("next week", date(2026, 10, 5))
        classify_due(r.due_date, date(2026, 10, 5), "open")
        days_overdue(r.due_date, date(2026, 10, 5), "open")
