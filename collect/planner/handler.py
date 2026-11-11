"""Planner Lambda (Part 1 · Collect).

EventBridge calls this once a day. ``POST /analyses`` calls it once per date
when someone asks for a backfill, passing ``jobId`` so the Reader can update
that job's progress.

Input (every field optional)::

    {
      "date": "YYYY-MM-DD",             # default: yesterday UTC
      "providers": ["planetiq", "spire", "cosmic2"],
      "jobId": "..."                    # present on a backfill
    }

Output::

    {
      "date": "YYYY-MM-DD",
      "tickets": [{"provider", "date", "url", "jobId"?}, ...],
      "enqueued": <int>,
      "mode": "stub" | "sqs"
    }

The stub emits one ticket per provider whose ``url`` is the CDAAC day
directory. The real planner lists that directory and emits one ticket per
level-2 file (atmPrf, wetPf2, BUFR).

TODO(Collect):
- List ``level2_prefix`` over HTTPS and enqueue one SQS message per file.
- Send those messages when ``GNSSIW_STUB=0`` (see :func:`enqueue`).
- Leave a bad listing as a Lambda error so EventBridge retry / the alarm
  can see it. A bad *file* is the Reader's problem, and lands in the DLQ.
"""

import logging
import os
from typing import Any

from gnssiw.dates import parse_iso_date, yesterday_utc
from gnssiw.models import PROVIDERS
from gnssiw.runtime import stub_mode
from gnssiw.ucar import placeholder_tickets

logger = logging.getLogger(__name__)


def resolve_providers(event: dict[str, Any]) -> list[str]:
    requested = event.get("providers") or list(PROVIDERS)
    if not isinstance(requested, list) or not requested:
        raise ValueError("providers must be a non-empty list")
    unknown = [provider for provider in requested if provider not in PROVIDERS]
    if unknown:
        raise ValueError(f"unknown providers: {unknown}")
    return list(requested)


def build_plan(event: dict[str, Any] | None) -> dict[str, Any]:
    payload = event or {}
    if payload.get("date"):
        day = parse_iso_date(payload["date"])
    else:
        day = yesterday_utc()
    providers = resolve_providers(payload)
    job_id = payload.get("jobId")
    if job_id is not None and not isinstance(job_id, str):
        raise ValueError("jobId must be a string")
    tickets = placeholder_tickets(day, providers, job_id=job_id)
    return {
        "date": day.isoformat(),
        "providers": providers,
        "jobId": job_id,
        "tickets": [ticket.to_message() for ticket in tickets],
    }


def enqueue(tickets: list[dict[str, str]]) -> int:
    """Put one SQS message per ticket.

    TODO(Collect): ``boto3.client("sqs").send_message`` to ``QUEUE_URL``,
    using ``provider`` + ``date`` + ``url`` as a deduplication id if the
    queue is ever switched to FIFO. The standard queue relies on the Reader's
    PutItem overwrite for idempotency instead.
    """
    queue_url = os.environ.get("QUEUE_URL", "")
    raise NotImplementedError(
        f"SQS enqueue is not implemented ({len(tickets)} tickets, queue={queue_url!r})"
    )


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context  # Lambda supplies this; the stub does not use it.
    plan = build_plan(event)
    if stub_mode():
        logger.info("stub planner: %s tickets for %s", len(plan["tickets"]), plan["date"])
        plan["enqueued"] = 0
        plan["mode"] = "stub"
        return plan
    plan["enqueued"] = enqueue(plan["tickets"])
    plan["mode"] = "sqs"
    return plan
