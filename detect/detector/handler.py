"""Detector Lambda (Part 2 · Detect). First state in the daily Step Functions run.

Input from the schedule (date optional; default yesterday UTC)::

    {"date": "YYYY-MM-DD"}

The skeleton also accepts an inline ``series`` map so the scoring can be
tested and demoed before DynamoDB is wired. Keys are DailyCounts partition
keys (``baltic#planetiq``). Values::

    {"count": 35, "expected": 251.0, "history": [1.0, 0.95, ...]}

``history`` is prior days' ratios, oldest first, excluding today. When
``series`` is omitted the function scores nothing and logs the TODO.

Output (this object is the Cross-checker's input)::

    {
      "date": "YYYY-MM-DD",
      "windowDays": 30,
      "evaluated": <int>,
      "flagged": <int>,
      "anomalies": [
        {"date", "regionId", "provider", "count", "expected", "ratio", "z", "flagged"}
      ],
      "mode": "stub"
    }

``Anomalies`` stores the flagged rows. ``z`` is JSON ``null`` when the
trailing window is shorter than ``MIN_HISTORY_DAYS``; those rows are not
flagged.

TODO(Detect):
- Query DailyCounts for each seed region and provider over the trailing
  ``windowDays`` (env ``Z_WINDOW_DAYS``).
- Replace placeholder ``expected`` values with the latitude-band baseline
  (:func:`gnssiw.detection.expected_profiles`).
- Update DailyCounts.ratio and PutItem flagged rows into Anomalies
  (pk ``date``, sk ``region#provider``) with ratio and z. Leave
  ``gpsjamOverlap``, ``risk``, and ``summary`` for the Cross-checker.
"""

import logging
from typing import Any

from gnssiw.dates import parse_iso_date, yesterday_utc
from gnssiw.detection import density_ratio, is_flagged, rolling_zscore
from gnssiw.keys import split_daily_counts_pk
from gnssiw.runtime import stub_mode, trailing_window_days

logger = logging.getLogger(__name__)


def evaluate_series(
    *,
    region_id: str,
    provider: str,
    day: str,
    count: int,
    expected: float,
    history: list[float],
) -> dict[str, Any]:
    """Score one region/provider/day. Pure: no AWS calls."""
    ratio = density_ratio(count, expected)
    z_score = rolling_zscore(ratio, history)
    return {
        "date": day,
        "regionId": region_id,
        "provider": provider,
        "count": count,
        "expected": expected,
        "ratio": ratio,
        "z": z_score,
        "flagged": is_flagged(ratio, z_score),
    }


def _as_history(value: object) -> list[float]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("history must be a list of ratios")
    return [float(item) for item in value]


def score_series(day: str, series: dict[str, Any]) -> list[dict[str, Any]]:
    anomalies = []
    for pk, item in series.items():
        if not isinstance(item, dict):
            raise ValueError(f"series[{pk!r}] must be an object")
        region_id, provider = split_daily_counts_pk(str(pk))
        if "count" not in item or "expected" not in item:
            raise ValueError(f"series[{pk!r}] needs count and expected")
        anomalies.append(
            evaluate_series(
                region_id=region_id,
                provider=provider,
                day=day,
                count=int(item["count"]),
                expected=float(item["expected"]),
                history=_as_history(item.get("history")),
            )
        )
    return anomalies


def run(event: dict[str, Any] | None) -> dict[str, Any]:
    payload = event or {}
    day = parse_iso_date(payload["date"]) if payload.get("date") else yesterday_utc()
    window = trailing_window_days()
    series = payload.get("series")
    if series is None:
        # TODO(Detect): load the trailing window from DailyCounts.
        logger.info("TODO load DailyCounts for %s (window=%s)", day.isoformat(), window)
        series = {}
    if not isinstance(series, dict):
        raise ValueError("series must be an object")
    anomalies = score_series(day.isoformat(), series)
    return {
        "date": day.isoformat(),
        "windowDays": window,
        "evaluated": len(anomalies),
        "flagged": sum(1 for row in anomalies if row["flagged"]),
        "anomalies": anomalies,
        "mode": "stub" if stub_mode() else "aws",
    }


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return run(event)
