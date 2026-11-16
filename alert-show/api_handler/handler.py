"""Alert API Lambda (Part 3 · Alert & Show). API Gateway REST proxy.

Routes:

* ``GET /hotspots?date=YYYY-MM-DD`` — flagged regions for that UTC day.
  ``date`` defaults to yesterday, which is the latest closed day.
* ``POST /subscriptions`` — ``{email, regionIds?, minRisk?}``. SNS sends the
  confirmation email once subscribe is implemented; the row records the
  filter the Cross-checker should honor.

Status codes match ``docs/openapi.yaml``.

TODO(Alert & Show):
- ``GET /hotspots``: query Anomalies pk = date. Return one object per flagged
  region/provider with ratio, z, gpsjamOverlap, risk, summary.
- ``POST /subscriptions``: put_item Subscriptions, then ``sns.subscribe``
  (protocol email) on ``ALERT_TOPIC_ARN``. Leave ``confirmed`` false until
  the subscriber clicks the SNS link.
- Apply ``regionIds`` and ``minRisk`` as an SNS subscription filter policy
  so a Baltic-only subscriber does not get a Black Sea email.
"""

import logging
import re
import uuid
from typing import Any

from gnssiw.dates import parse_iso_date, yesterday_utc
from gnssiw.models import RISK_LEVELS
from gnssiw.regions import SEED_REGIONS, region_by_id
from gnssiw.responses import BodyError, parse_body, query_params, response

logger = logging.getLogger(__name__)

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def route(
    event: dict[str, Any],
    *,
    hotspots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """``hotspots`` lets tests supply the rows a DynamoDB query would return."""
    method = str(event.get("httpMethod") or "").upper()
    resource = str(event.get("resource") or event.get("path") or "")
    try:
        if method == "GET" and resource == "/hotspots":
            return _get_hotspots(event, hotspots)
        if method == "POST" and resource == "/subscriptions":
            return _post_subscription(event)
    except BodyError as exc:
        return response(400, {"message": str(exc)})
    return response(404, {"message": "not found"})


def _get_hotspots(
    event: dict[str, Any],
    hotspots: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    query = query_params(event)
    if "date" in query and query["date"]:
        try:
            day = parse_iso_date(query["date"])
        except ValueError as exc:
            raise BodyError(str(exc)) from exc
    else:
        day = yesterday_utc()
    rows = [] if hotspots is None else list(hotspots)
    # TODO(Alert & Show): replace ``rows`` with the Anomalies query result.
    logger.info("TODO query anomalies for %s", day.isoformat())
    return response(200, {"date": day.isoformat(), "hotspots": rows})


def _post_subscription(event: dict[str, Any]) -> dict[str, Any]:
    body = parse_body(event)
    email = body.get("email")
    if not isinstance(email, str) or _EMAIL.fullmatch(email.strip()) is None:
        raise BodyError("email is invalid")
    min_risk = body.get("minRisk", "High")
    if min_risk not in RISK_LEVELS:
        raise BodyError("minRisk must be Low, Medium, or High")
    if "regionIds" in body and body["regionIds"] is not None:
        region_ids = body["regionIds"]
        if not isinstance(region_ids, list) or not region_ids:
            raise BodyError("regionIds must be a non-empty list")
        unknown = [
            region_id
            for region_id in region_ids
            if not isinstance(region_id, str) or region_by_id(region_id) is None
        ]
        if unknown:
            raise BodyError(f"unknown regions: {unknown}")
        chosen = list(region_ids)
    else:
        chosen = [region.region_id for region in SEED_REGIONS]
    created = {
        "subscriptionId": f"sub-{uuid.uuid4().hex[:12]}",
        "email": email.strip(),
        "regionIds": chosen,
        "minRisk": min_risk,
        "confirmed": False,
    }
    # TODO(Alert & Show): put_item + sns.subscribe. confirmed stays false
    # until the subscriber accepts the SNS confirmation email.
    logger.info("TODO subscribe %s", created["subscriptionId"])
    return response(201, created)


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    try:
        return route(event or {})
    except Exception:  # noqa: BLE001 - API Gateway gets a JSON 500, not a crash
        logger.exception("request failed")
        return response(500, {"message": "internal error"})
