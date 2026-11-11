"""Reader Lambda (Part 1 · Collect).

SQS trigger, batch size 1. Each record body is one
:class:`gnssiw.models.SqsTicket`. This function is the parallel-ingest
operation: download, decode, tag a region, write Parquet, upsert counts.

Return value (SQS reads only ``batchItemFailures``)::

    {
      "batchItemFailures": [{"itemIdentifier": "<messageId>"}, ...],
      "processed": [{"provider", "date", "parquetKey", "counts", "profiles"}, ...]
    }

A failed record is reported in ``batchItemFailures``. SQS retries it, and
after 3 receives the message moves to the dead-letter queue. Other records
in the batch are not failed with it.

Idempotency: Parquet is written to a deterministic key (overwrite), and
DailyCounts is a PutItem on ``(pk, date)`` — a re-run replaces the count
and does not add to it. :func:`upsert_counts` is that rule.

TODO(Collect):
- Download ``ticket.url``. If it is still a directory prefix, list it; the
  Planner should already have turned it into one file URL.
- Decode netCDF (``atmPrf`` / ``wetPf2``) and BUFR. The libraries are large,
  so the production function is the container image in ``Dockerfile``.
- Drop retrievals that did not converge, once the quality flag is confirmed
  in the CDAAC format notes.
- ``put_object`` the Parquet and ``put_item`` each DailyCounts row.
- If ``jobId`` is set, add one to ``Jobs.filesDone`` (conditional update).
"""

import json
import logging
from typing import Any

from gnssiw.detection import expected_profiles
from gnssiw.keys import daily_counts_pk, parquet_key
from gnssiw.models import PROFILE_COLUMNS, SqsTicket
from gnssiw.regions import SEED_REGIONS, Region, region_by_id
from gnssiw.runtime import stub_mode

logger = logging.getLogger(__name__)


def tag_profile(
    profile: dict[str, Any],
    regions: tuple[Region, ...] = SEED_REGIONS,
) -> dict[str, Any]:
    """Copy ``profile`` and set ``region_id`` to the first box that contains it.

    TODO(Collect): load custom regions from the Regions table and pass them
    in ``regions``. The first match wins; the seed boxes do not overlap.
    """
    if "lat" not in profile or "lon" not in profile:
        raise ValueError("profile needs lat and lon")
    tagged = dict(profile)
    region_id = None
    for region in regions:
        if region.bbox.contains(float(profile["lat"]), float(profile["lon"])):
            region_id = region.region_id
            break
    tagged["region_id"] = region_id
    return tagged


def aggregate_counts(
    profiles: list[dict[str, Any]],
    *,
    provider: str,
    day: str,
) -> list[dict[str, Any]]:
    """Count tagged profiles per region. Profiles outside every box are skipped."""
    totals: dict[str, int] = {}
    for profile in profiles:
        region_id = profile.get("region_id")
        if not region_id:
            continue
        key = daily_counts_pk(str(region_id), provider)
        totals[key] = totals.get(key, 0) + 1
    rows = []
    for key in sorted(totals):
        region_id, _provider = key.split("#", 1)
        rows.append(
            {
                "pk": key,
                "date": day,
                "count": totals[key],
                "provider": provider,
                "regionId": region_id,
            }
        )
    return rows


def with_expected(
    rows: list[dict[str, Any]],
    regions: tuple[Region, ...] = SEED_REGIONS,
) -> list[dict[str, Any]]:
    """Attach the placeholder expected count from the shared baseline helper.

    The latitude-band baseline itself is a Detect TODO
    (:func:`gnssiw.detection.expected_profiles`). Writing ``expected`` here
    keeps the DailyCounts handoff (``pk``, ``date``, ``count``, ``expected``)
    complete for Part 2.
    """
    enriched = []
    for row in rows:
        region = region_by_id(row["regionId"], regions)
        if region is None:
            raise ValueError(f"unknown region on a count row: {row['regionId']!r}")
        enriched.append(
            {
                **row,
                "expected": expected_profiles(row["provider"], region.area_km2),
            }
        )
    return enriched


def upsert_counts(
    table: dict[tuple[str, str], dict[str, Any]],
    rows: list[dict[str, Any]],
) -> None:
    """PutItem semantics. The new row replaces ``(pk, date)``; it is not added."""
    for row in rows:
        table[(row["pk"], row["date"])] = dict(row)


def decode_ticket(ticket: SqsTicket) -> list[dict[str, Any]]:
    """Download and decode one ticket.

    TODO(Collect): return one dict per profile with the keys in
    :data:`gnssiw.models.PROFILE_COLUMNS` except ``region_id``, which
    :func:`tag_profile` fills in. Returns an empty list in the skeleton so
    the handler can be invoked end to end.
    """
    logger.info("TODO decode %s (%s)", ticket.url, ", ".join(PROFILE_COLUMNS))
    return []


def persist(
    ticket: SqsTicket,
    profiles: list[dict[str, Any]],
    counts: dict[tuple[str, str], dict[str, Any]],
) -> None:
    """Write Parquet and DailyCounts.

    TODO(Collect): implement against ``PROFILES_BUCKET`` and
    ``DAILY_COUNTS_TABLE``. ``parquet_key`` is the object key to overwrite.
    """
    raise NotImplementedError(
        "S3/DynamoDB persist is not implemented "
        f"({ticket.provider} {ticket.date}, {len(profiles)} profiles, {len(counts)} counts)"
    )


def process_ticket(
    ticket: SqsTicket,
    *,
    profiles: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Tag, count, and (outside stub mode) store one ticket.

    Tests pass ``profiles`` to exercise tagging without a download.
    """
    decoded = decode_ticket(ticket) if profiles is None else profiles
    tagged = [tag_profile(profile) for profile in decoded]
    rows = with_expected(aggregate_counts(tagged, provider=ticket.provider, day=ticket.date))
    stored: dict[tuple[str, str], dict[str, Any]] = {}
    upsert_counts(stored, rows)
    result = {
        "provider": ticket.provider,
        "date": ticket.date,
        "parquetKey": parquet_key(ticket.provider, ticket.date),
        "profiles": len(tagged),
        "counts": list(stored.values()),
        "jobId": ticket.job_id,
    }
    if not stub_mode():
        persist(ticket, tagged, stored)
    return result


def handle_sqs(event: dict[str, Any]) -> dict[str, Any]:
    failures = []
    processed = []
    for record in event.get("Records") or []:
        message_id = str(record.get("messageId", ""))
        try:
            body = json.loads(record["body"])
            ticket = SqsTicket.from_message(body)
            processed.append(process_ticket(ticket))
        except Exception:  # noqa: BLE001 - SQS retries any failure, then the DLQ
            logger.exception("ticket failed: %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures, "processed": processed}


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    return handle_sqs(event or {})
