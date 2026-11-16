"""Cross-checker Lambda (Part 3 · Alert & Show).

Second state in the daily Step Functions run. Input is the Detector output,
plus the GPSJam fields once they are computed::

    {
      "date": "YYYY-MM-DD",
      "anomalies": [ ... detector rows ... ],
      "gpsjamOverlap": {"baltic": 0.42},          # fraction of cells marked high
      "correlation": {"baltic": 0.8},             # optional, region id -> r
      "streakDays": {"baltic#planetiq": 5}       # consecutive flagged days
    }

Only rows with ``flagged: true`` are scored. Output::

    {
      "date": "...",
      "results": [anomaly + gpsjamOverlap, correlation, streakDays, risk, summary, alerted],
      "notifications": [{"regionId", "regionName", "provider", "date", "risk", "summary"}],
      "mode": "stub"
    }

A notification is produced when the risk meets the topic bar (High) and the
row is not already ``alerted``. Publishing that list is the SNS TODO.

TODO(Alert & Show):
- Download ``gpsjam.daily_csv_url(date)`` (cache at ``gpsjam_cache_key``),
  classify each H3 cell, and set ``gpsjamOverlap[regionId]`` from the cells
  whose centroid falls in the region. Missing cells stay at 0, which cannot
  score High.
- Compute :func:`gnssiw.risk.pearson` between the region's recent ratios and its recent
  GPSJam overlap. Store it on the anomaly.
- PutItem the enriched row back to Anomalies.
- Publish ``notifications`` to ``ALERT_TOPIC_ARN`` with message attributes
  ``regionId`` and ``risk``. Skip rows that were already alerted.
- When ``ENABLE_BEDROCK=1`` and risk is High, replace ``summary`` with two
  sentences from Bedrock. On any model error, keep the placeholder summary.
"""

import logging
from typing import Any

from gnssiw.dates import parse_iso_date, yesterday_utc
from gnssiw.keys import anomaly_sk
from gnssiw.regions import region_by_id
from gnssiw.risk import assign_risk, placeholder_summary, should_notify
from gnssiw.runtime import bedrock_enabled, stub_mode

logger = logging.getLogger(__name__)

# The shared topic's bar. Per-subscriber ``minRisk`` / ``regionIds`` are stored
# on Subscriptions and should become an SNS filter policy (see the schema doc).
TOPIC_MIN_RISK = "High"


def _lookup(mapping: dict[str, Any], *keys: str, default: Any) -> Any:
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def enrich(
    anomaly: dict[str, Any],
    *,
    overlap: float,
    correlation: float | None,
    streak_days: int,
) -> dict[str, Any]:
    """Add the Part 3 fields to one flagged anomaly."""
    risk = assign_risk(
        ratio=float(anomaly["ratio"]),
        z_score=None if anomaly.get("z") is None else float(anomaly["z"]),
        gpsjam_overlap=float(overlap),
        streak_days=streak_days,
    )
    region = region_by_id(str(anomaly["regionId"]))
    region_name = region.name if region else str(anomaly["regionId"])
    summary = placeholder_summary(
        region_name=region_name,
        ratio=float(anomaly["ratio"]),
        overlap=float(overlap),
        risk=risk,
    )
    if bedrock_enabled() and risk == "High":
        # TODO(Alert & Show): call Bedrock and replace ``summary`` on success.
        logger.info("TODO Bedrock summary for %s", region_name)
    alerted = bool(anomaly.get("alerted"))
    notify = should_notify(risk=risk, min_risk=TOPIC_MIN_RISK, already_alerted=alerted)
    enriched = {
        **anomaly,
        "sk": anomaly_sk(str(anomaly["regionId"]), str(anomaly["provider"])),
        "gpsjamOverlap": float(overlap),
        "correlation": correlation,
        "streakDays": streak_days,
        "risk": risk,
        "summary": summary,
        "alerted": True if notify else alerted,
    }
    notification = None
    if notify:
        notification = {
            "regionId": anomaly["regionId"],
            "regionName": region_name,
            "provider": anomaly["provider"],
            "date": anomaly["date"],
            "risk": risk,
            "summary": summary,
        }
    return {"row": enriched, "notification": notification}


def run(event: dict[str, Any] | None) -> dict[str, Any]:
    payload = event or {}
    day = parse_iso_date(payload["date"]) if payload.get("date") else yesterday_utc()
    anomalies = payload.get("anomalies") or []
    if not isinstance(anomalies, list):
        raise ValueError("anomalies must be a list")
    overlaps = payload.get("gpsjamOverlap") or {}
    correlations = payload.get("correlation") or {}
    streaks = payload.get("streakDays") or {}
    # TODO(Alert & Show): when gpsjamOverlap is absent, download and compute it
    # instead of defaulting every region to 0.
    if not payload.get("gpsjamOverlap"):
        logger.info("TODO load GPSJam for %s", day.isoformat())

    results = []
    notifications = []
    for anomaly in anomalies:
        if not anomaly.get("flagged"):
            continue
        region_id = str(anomaly["regionId"])
        provider = str(anomaly["provider"])
        sk = anomaly_sk(region_id, provider)
        correlation = _lookup(correlations, region_id, default=None)
        streak = int(_lookup(streaks, sk, region_id, default=1))
        overlap = float(_lookup(overlaps, region_id, default=0.0))
        scored = enrich(
            anomaly,
            overlap=overlap,
            correlation=None if correlation is None else float(correlation),
            streak_days=streak,
        )
        results.append(scored["row"])
        if scored["notification"] is not None:
            notifications.append(scored["notification"])

    if notifications and not stub_mode():
        # TODO(Alert & Show): sns.publish once per notification.
        logger.info("TODO publish %s alert(s)", len(notifications))
    return {
        "date": day.isoformat(),
        "results": results,
        "notifications": notifications,
        "mode": "stub" if stub_mode() else "aws",
    }


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return run(event)
