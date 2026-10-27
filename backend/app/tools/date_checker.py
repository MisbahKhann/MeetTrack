"""Deterministic date checker tool.

Pure functions for resolving natural-language due-date text into concrete dates.
No function may read the system clock; all date logic is relative to an explicit
as_of argument.

Public API:
    parse_as_of(value) -> date
    resolve_due(due_text, as_of) -> DueResolution
    classify_due(due, as_of, status, due_soon_days) -> str
    days_overdue(due, as_of, status) -> int
"""

import calendar
import re
from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Named constants
# ---------------------------------------------------------------------------

# Working week: Monday (0) through Friday (4)
WORK_WEEK_START = 0  # Monday
WORK_WEEK_END = 4  # Friday

# If a guessed year puts the resolved date this many days BEFORE as_of, roll to
# the next year instead.
YEAR_ROLLOVER_DAYS = 183

MAX_DUE_TEXT_LENGTH = 100

# ---------------------------------------------------------------------------
# Month name tables (case-insensitive lookup)
# ---------------------------------------------------------------------------

_MONTH_ABBR: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_FULL: dict[str, int] = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_MONTH_NAMES: dict[str, int] = {**_MONTH_ABBR, **_MONTH_FULL}

# ---------------------------------------------------------------------------
# Weekday tables
# ---------------------------------------------------------------------------

_WEEKDAY_ABBR: dict[str, int] = {
    "mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
_WEEKDAY_FULL: dict[str, int] = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
_WEEKDAY_NAMES: dict[str, int] = {**_WEEKDAY_ABBR, **_WEEKDAY_FULL}

# Leading words and trailing punctuation to strip
_STRIP_PREFIX_RE = re.compile(
    r"^\s*(by|before|on|until|due|latest|no later than)\s+", re.IGNORECASE
)
_STRIP_SUFFIX_RE = re.compile(r"[.,;:!?]+$")


# ---------------------------------------------------------------------------
# DueResolution model
# ---------------------------------------------------------------------------


class DueResolution(BaseModel, frozen=True):
    """Result of resolving a natural-language due-date string."""

    status: Literal["none", "resolved", "approximate", "unparseable"]
    due_date: date | None
    rule: str
    in_past: bool


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_as_of(value: str) -> date:
    """Parse a strict ISO yyyy-mm-dd string into a date.

    Raises:
        ValueError: If the string is not a valid ISO date.
    """
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            f"as_of must be a valid ISO date (yyyy-mm-dd); got {value!r}"
        ) from exc


def _clean(text: str) -> str:
    """Strip leading qualifier words and trailing punctuation."""
    text = _STRIP_PREFIX_RE.sub("", text).strip()
    text = _STRIP_SUFFIX_RE.sub("", text).strip()
    return text


def _next_weekday_after(target_weekday: int, as_of: date) -> date:
    """Return the first occurrence of target_weekday STRICTLY after as_of.

    If as_of is that weekday, returns 7 days later (next week).
    """
    days_ahead = target_weekday - as_of.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return as_of + timedelta(days=days_ahead)


def _friday_of_week(d: date) -> date:
    """Return the Friday of the Monday-to-Sunday week containing d."""
    # Monday is weekday 0, Friday is weekday 4
    days_to_friday = WORK_WEEK_END - d.weekday()
    if days_to_friday < 0:
        days_to_friday += 7
    return d + timedelta(days=days_to_friday)


def _last_day_of_month(d: date) -> date:
    """Return the last day of the month containing d."""
    last_day = calendar.monthrange(d.year, d.month)[1]
    return date(d.year, d.month, last_day)


def _try_parse_date(text: str, as_of: date) -> date | None:
    """Try to parse text as a named-date expression. Returns None on failure."""
    # ISO date: yyyy-mm-dd
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    # "12 Oct", "12 October", "Oct 12", "12 Oct 2026", "Oct 12 2026"
    # Patterns: (day month [year]) or (month day [year])
    m = re.match(
        r"^(\d{1,2})\s+([a-zA-Z]+)(?:\s+(\d{4}))?$", text
    )
    if m:
        day, month_str, year_str = m.group(1), m.group(2), m.group(3)
        month = _MONTH_NAMES.get(month_str.lower())
        if month:
            year = int(year_str) if year_str else None
            return _resolve_month_day(int(day), month, year, as_of)

    m = re.match(
        r"^([a-zA-Z]+)\s+(\d{1,2})(?:\s+(\d{4}))?$", text
    )
    if m:
        month_str, day, year_str = m.group(1), m.group(2), m.group(3)
        month = _MONTH_NAMES.get(month_str.lower())
        if month:
            year = int(year_str) if year_str else None
            return _resolve_month_day(int(day), month, year, as_of)

    return None


def _resolve_month_day(day: int, month: int, year: int | None, as_of: date) -> date | None:
    """Resolve a (day, month, optional year) triple into a date with rollover logic."""
    if year is not None:
        try:
            return date(year, month, day)
        except ValueError:
            return None  # impossible date like 31 Feb

    # No year -- try as_of's year first
    try:
        candidate = date(as_of.year, month, day)
    except ValueError:
        return None  # impossible date

    # Rollover: if candidate is more than YEAR_ROLLOVER_DAYS before as_of, use next year
    if (as_of - candidate).days > YEAR_ROLLOVER_DAYS:
        try:
            candidate = date(as_of.year + 1, month, day)
        except ValueError:
            return None
    return candidate


# ---------------------------------------------------------------------------
# Main resolver
# ---------------------------------------------------------------------------


def resolve_due(due_text: str | None, as_of: date) -> DueResolution:
    """Resolve a natural-language due-date string relative to as_of.

    Rules are applied in priority order; the first match wins.
    Never reads the system clock.
    """

    def _make(
        status: Literal["none", "resolved", "approximate", "unparseable"],
        due_date: date | None,
        rule: str,
    ) -> DueResolution:
        in_past = due_date is not None and due_date < as_of
        return DueResolution(status=status, due_date=due_date, rule=rule, in_past=in_past)

    # Rule 1: None or blank
    if due_text is None or not due_text.strip():
        return _make("none", None, "no_due_date")

    # Rule 2: too long
    if len(due_text) > MAX_DUE_TEXT_LENGTH:
        return _make("unparseable", None, "too_long")

    cleaned = _clean(due_text).lower()

    # Rule 3: today / tonight / eod
    if cleaned in ("today", "tonight", "eod"):
        return _make("resolved", as_of, "today")

    # Rule 4: tomorrow
    if cleaned == "tomorrow":
        return _make("resolved", as_of + timedelta(days=1), "tomorrow")

    # Rule 5: "in N days" / "in N weeks"
    m = re.match(r"^in (\d+) (days?|weeks?)$", cleaned)
    if m:
        n = int(m.group(1))
        unit = m.group(2).rstrip("s")
        if 1 <= n <= 52:
            delta = timedelta(days=n) if unit == "day" else timedelta(weeks=n)
            return _make("resolved", as_of + delta, f"in_n_{unit}s")

    # Rule 6: "this week" / "end of week" / "eow"
    if cleaned in ("this week", "end of week", "eow"):
        return _make("approximate", _friday_of_week(as_of), "this_week")

    # Rule 7: "next week"
    if cleaned == "next week":
        next_monday = as_of + timedelta(days=7 - as_of.weekday())
        return _make("approximate", _friday_of_week(next_monday), "next_week")

    # Rule 8: "end of month" / "eom"
    if cleaned in ("end of month", "eom"):
        return _make("approximate", _last_day_of_month(as_of), "end_of_month")

    # Rule 9: "next <weekday>"
    m = re.match(r"^next\s+([a-zA-Z]+)$", cleaned)
    if m:
        wd = _WEEKDAY_NAMES.get(m.group(1).lower())
        if wd is not None:
            # "next <weekday>" means that weekday in the NEXT Mon-Sun week
            next_monday = as_of + timedelta(days=7 - as_of.weekday())
            target = next_monday + timedelta(days=(wd - next_monday.weekday()) % 7)
            return _make("resolved", target, "next_weekday")

    # Rule 10: plain weekday -- strictly after as_of
    wd = _WEEKDAY_NAMES.get(cleaned)
    if wd is not None:
        return _make("resolved", _next_weekday_after(wd, as_of), "plain_weekday")

    # Rule 11: named date (ISO, "12 Oct", "Oct 12", with/without year)
    # Use the original cleaned text (before lower()) for fromisoformat compatibility
    cleaned_orig = _clean(due_text)
    resolved_date = _try_parse_date(cleaned_orig, as_of)
    if resolved_date is not None:
        return _make("resolved", resolved_date, "named_date")

    # Fallback: unparseable
    return _make("unparseable", None, "unparseable")


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def classify_due(
    due: date | None,
    as_of: date,
    status: str,
    due_soon_days: int = 3,
) -> Literal["no_date", "closed", "overdue", "due_today", "due_soon", "upcoming"]:
    """Classify an action's urgency.

    Args:
        due: Resolved due date (or None).
        as_of: Reference date.
        status: The action's current status string.
        due_soon_days: Window (inclusive) for "due_soon".

    Returns:
        One of: no_date, closed, overdue, due_today, due_soon, upcoming.
    """
    if status == "done":
        return "closed"
    if due is None:
        return "no_date"
    if due < as_of:
        return "overdue"
    if due == as_of:
        return "due_today"
    if (due - as_of).days <= due_soon_days:
        return "due_soon"
    return "upcoming"


def days_overdue(due: date | None, as_of: date, status: str) -> int:
    """Return how many days overdue an action is (0 if not overdue or closed)."""
    if status == "done" or due is None or due >= as_of:
        return 0
    return (as_of - due).days
