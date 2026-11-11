"""Date helpers shared by the planner, the API, and the daily analysis."""

from datetime import UTC, date, datetime, timedelta


def parse_iso_date(value: object) -> date:
    """Parse a ``YYYY-MM-DD`` calendar date.

    Rejects datetimes, single-digit months, and impossible days such as
    February 31. Callers map :class:`ValueError` to HTTP 400.
    """
    if not isinstance(value, str):
        raise ValueError(f"invalid date: {value!r}")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"invalid date: {value!r}") from exc
    if parsed.isoformat() != value:
        raise ValueError(f"invalid date: {value!r}")
    return parsed


def yesterday_utc(today: date | None = None) -> date:
    """The UTC calendar day before ``today`` (default: now).

    UCAR publishes a day's near-real-time files after that day has closed,
    so the morning schedule processes yesterday.
    """
    current = today if today is not None else datetime.now(UTC).date()
    return current - timedelta(days=1)


def inclusive_days(start: date, end: date) -> int:
    """Count of calendar days in ``start..end``, both ends included."""
    if end < start:
        raise ValueError("from must be on or before to")
    return (end - start).days + 1


def ranges_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """True when the two inclusive date ranges share a day."""
    return a_start <= b_end and b_start <= a_end
