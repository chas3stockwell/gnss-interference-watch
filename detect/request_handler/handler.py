"""Request-handler Lambda (Part 2 · Detect). API Gateway REST proxy.

Routes owned by Detect:

* ``GET /regions``
* ``POST /regions``
* ``GET /regions/{id}/timeseries``
* ``POST /analyses``
* ``GET /analyses/{id}``

``/hotspots`` and ``/subscriptions`` are the Alert & Show function. Status
codes match ``docs/openapi.yaml``.

Stub mode serves the four seed regions from :mod:`gnssiw.regions` and keeps
jobs only for the length of the call. Pass ``jobs=`` into :func:`route` from
tests to simulate a running backfill (HTTP 409).

TODO(Detect):
- Read and write the Regions, DailyCounts, Anomalies, and Jobs tables.
- ``POST /analyses``: PutItem a queued job, then invoke the Planner once per
  day with that ``jobId`` (the Planner enqueues the file tickets).
- ``GET /analyses/{id}``: read the job. The Reader increments ``filesDone``.
- ``GET /regions/{id}/timeseries``: query DailyCounts for ``pk = id#provider``
  and the date range, and attach the Detector's z-score.
- Reject a second job whose date range overlaps a queued or running job.
"""

import logging
import re
import uuid
from datetime import date
from typing import Any

from gnssiw.dates import inclusive_days, parse_iso_date, ranges_overlap
from gnssiw.models import PROVIDERS, BoundingBox, Region
from gnssiw.regions import SEED_REGIONS, approximate_area_km2, region_by_id
from gnssiw.responses import BodyError, parse_body, query_params, response

logger = logging.getLogger(__name__)

# A typo that asks for a decade of backfill would enqueue a large download.
# October 2026 is 31 days; 120 leaves room for a season of warmup.
MAX_ANALYSIS_DAYS = 120
_SLUG = re.compile(r"[^a-z0-9]+")


def route(
    event: dict[str, Any],
    *,
    regions: list[Region] | None = None,
    jobs: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    region_list = list(SEED_REGIONS if regions is None else regions)
    job_list = [dict(job) for job in (jobs or [])]
    method = str(event.get("httpMethod") or "").upper()
    resource = str(event.get("resource") or event.get("path") or "")
    try:
        if method == "GET" and resource == "/regions":
            return _get_regions(region_list)
        if method == "POST" and resource == "/regions":
            return _post_region(event, region_list)
        if method == "GET" and resource == "/regions/{id}/timeseries":
            return _get_timeseries(event, region_list)
        if method == "POST" and resource == "/analyses":
            return _post_analysis(event, job_list)
        if method == "GET" and resource == "/analyses/{id}":
            return _get_analysis(event, job_list)
    except BodyError as exc:
        return response(400, {"message": str(exc)})
    return response(404, {"message": "not found"})


def _get_regions(regions: list[Region]) -> dict[str, Any]:
    return response(200, {"regions": [region.to_api() for region in regions]})


def _require_float(body: dict[str, Any], field: str) -> float:
    if field not in body:
        raise BodyError(f"{field} is required")
    try:
        return float(body[field])
    except (TypeError, ValueError) as exc:
        raise BodyError(f"{field} must be a number") from exc


def _post_region(event: dict[str, Any], regions: list[Region]) -> dict[str, Any]:
    body = parse_body(event)
    name = body.get("name")
    if not isinstance(name, str) or not name.strip():
        raise BodyError("name is required")
    box = BoundingBox(
        min_lat=_require_float(body, "minLat"),
        max_lat=_require_float(body, "maxLat"),
        min_lon=_require_float(body, "minLon"),
        max_lon=_require_float(body, "maxLon"),
    )
    try:
        box.validate()
    except ValueError as exc:
        raise BodyError(str(exc)) from exc
    slug = _SLUG.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise BodyError("name is required")
    region_id = f"custom-{slug}"
    if any(region.region_id == region_id for region in regions):
        raise BodyError(f"region already exists: {region_id}")
    # TODO(Detect): decide whether a custom box may overlap a seed region.
    # The Reader tags the first match, so an overlap would hide one of them.
    created = Region(
        region_id=region_id,
        name=name.strip(),
        bbox=box,
        type="custom",
        area_km2=approximate_area_km2(box),
    )
    # TODO(Detect): put_item into the Regions table. The object above is the
    # response either way; persistence must use the same id.
    logger.info("TODO persist region %s", created.region_id)
    return response(201, created.to_api())


def _path_id(event: dict[str, Any]) -> str:
    params = event.get("pathParameters") or {}
    region_id = params.get("id")
    if not isinstance(region_id, str) or not region_id:
        raise BodyError("id is required")
    return region_id


def _get_timeseries(event: dict[str, Any], regions: list[Region]) -> dict[str, Any]:
    region_id = _path_id(event)
    if region_by_id(region_id, tuple(regions)) is None:
        return response(404, {"message": f"region not found: {region_id}"})
    query = query_params(event)
    if not query.get("provider") or not query.get("from") or not query.get("to"):
        raise BodyError("provider, from, and to are required")
    provider = query["provider"]
    if provider not in PROVIDERS:
        raise BodyError("provider must be one of planetiq, spire, cosmic2")
    try:
        start = parse_iso_date(query["from"])
        end = parse_iso_date(query["to"])
        inclusive_days(start, end)
    except ValueError as exc:
        raise BodyError(str(exc)) from exc
    # TODO(Detect): query DailyCounts pk = f"{region_id}#{provider}", SK between
    # start and end. Each point is {date, count, expected, ratio, z}.
    return response(
        200,
        {
            "regionId": region_id,
            "provider": provider,
            "from": start.isoformat(),
            "to": end.isoformat(),
            "points": [],
        },
    )


def _parse_range(body: dict[str, Any]) -> tuple[date, date]:
    try:
        start = parse_iso_date(body.get("from"))
        end = parse_iso_date(body.get("to"))
    except ValueError as exc:
        raise BodyError(str(exc)) from exc
    try:
        span = inclusive_days(start, end)
    except ValueError as exc:
        raise BodyError(str(exc)) from exc
    if span > MAX_ANALYSIS_DAYS:
        raise BodyError(f"date range must be {MAX_ANALYSIS_DAYS} days or fewer")
    return start, end


def _providers(body: dict[str, Any]) -> list[str]:
    requested = body.get("providers", list(PROVIDERS))
    if not isinstance(requested, list) or not requested:
        raise BodyError("providers must be a non-empty list")
    unknown = [provider for provider in requested if provider not in PROVIDERS]
    if unknown:
        raise BodyError(f"unknown providers: {unknown}")
    return list(requested)


def _overlapping_job(
    jobs: list[dict[str, Any]],
    start: date,
    end: date,
) -> dict[str, Any] | None:
    for job in jobs:
        if job.get("status") not in ("queued", "running"):
            continue
        job_start = parse_iso_date(job["from"])
        job_end = parse_iso_date(job["to"])
        if ranges_overlap(start, end, job_start, job_end):
            return job
    return None


def _post_analysis(event: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    body = parse_body(event)
    start, end = _parse_range(body)
    providers = _providers(body)
    conflict = _overlapping_job(jobs, start, end)
    if conflict is not None:
        return response(
            409,
            {
                "message": "an overlapping analysis is already running",
                "jobId": conflict["jobId"],
            },
        )
    job = {
        "jobId": f"job-{uuid.uuid4().hex[:12]}",
        "status": "queued",
        "from": start.isoformat(),
        "to": end.isoformat(),
        "providers": providers,
        "filesDone": 0,
        "filesTotal": 0,
    }
    # TODO(Detect): put_item Jobs, then lambda.invoke PlannerFunction once per
    # day with {"date", "providers", "jobId"}. filesTotal is filled in once
    # the Planner reports how many tickets it enqueued.
    logger.info("TODO start analysis %s (%s..%s)", job["jobId"], job["from"], job["to"])
    return response(202, job)


def _get_analysis(event: dict[str, Any], jobs: list[dict[str, Any]]) -> dict[str, Any]:
    job_id = _path_id(event)
    match = next((job for job in jobs if job.get("jobId") == job_id), None)
    if match is None:
        return response(404, {"message": f"job not found: {job_id}"})
    return response(
        200,
        {
            "jobId": match["jobId"],
            "status": match["status"],
            "from": match["from"],
            "to": match["to"],
            "filesDone": match.get("filesDone", 0),
            "filesTotal": match.get("filesTotal", 0),
        },
    )


def handler(event: dict[str, Any] | None, context: object) -> dict[str, Any]:
    del context
    try:
        return route(event or {})
    except Exception:  # noqa: BLE001 - API Gateway gets a JSON 500, not a crash
        logger.exception("request failed")
        return response(500, {"message": "internal error"})
