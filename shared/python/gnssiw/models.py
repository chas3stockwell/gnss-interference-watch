"""Handoff shapes from ``docs/data-contracts.md``.

These types are the agreement that lets Collect, Detect, and Alert & Show
build in parallel. Field names match the JSON on the wire.
"""

from dataclasses import dataclass

from gnssiw.dates import parse_iso_date

PROVIDERS: tuple[str, ...] = ("planetiq", "spire", "cosmic2")
RISK_LEVELS: tuple[str, ...] = ("Low", "Medium", "High")
REGION_TYPES: tuple[str, ...] = ("hotspot", "control", "custom")
JOB_STATUSES: tuple[str, ...] = ("queued", "running", "done", "failed")

# Columns of one cleaned profile row in the Parquet files under
# ``profiles/provider=.../date=.../``. ``region_id`` is null when the profile
# falls outside every watched region.
PROFILE_COLUMNS: tuple[str, ...] = (
    "lat",
    "lon",
    "time",
    "lowest_height_km",
    "quality",
    "region_id",
    "source_file",
)


@dataclass(frozen=True)
class BoundingBox:
    """Inclusive latitude/longitude box. The MVP does not cross the antimeridian."""

    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float

    def validate(self) -> None:
        if not (-90.0 <= self.min_lat <= 90.0 and -90.0 <= self.max_lat <= 90.0):
            raise ValueError("latitude must be between -90 and 90")
        if not (-180.0 <= self.min_lon <= 180.0 and -180.0 <= self.max_lon <= 180.0):
            raise ValueError("longitude must be between -180 and 180")
        if self.min_lat >= self.max_lat:
            raise ValueError("minLat must be less than maxLat")
        if self.min_lon >= self.max_lon:
            raise ValueError("minLon must be less than maxLon")

    def contains(self, lat: float, lon: float) -> bool:
        return self.min_lat <= lat <= self.max_lat and self.min_lon <= lon <= self.max_lon


@dataclass(frozen=True)
class Region:
    region_id: str
    name: str
    bbox: BoundingBox
    type: str
    area_km2: float

    def __post_init__(self) -> None:
        if self.type not in REGION_TYPES:
            raise ValueError(f"unknown region type: {self.type!r}")
        self.bbox.validate()
        if self.area_km2 <= 0:
            raise ValueError("area_km2 must be positive")

    def to_api(self) -> dict[str, object]:
        """JSON object returned by ``GET /regions`` and ``POST /regions``."""
        return {
            "id": self.region_id,
            "name": self.name,
            "minLat": self.bbox.min_lat,
            "maxLat": self.bbox.max_lat,
            "minLon": self.bbox.min_lon,
            "maxLon": self.bbox.max_lon,
            "type": self.type,
            "areaKm2": round(self.area_km2, 1),
        }


@dataclass(frozen=True)
class SqsTicket:
    """One ingest ticket. One file (or, in the stub, one day-directory) per message.

    Wire JSON::

        {"provider": "spire", "date": "2026-10-04", "url": "https://...", "jobId": "optional"}
    """

    provider: str
    date: str
    url: str
    job_id: str | None = None

    def to_message(self) -> dict[str, str]:
        body = {"provider": self.provider, "date": self.date, "url": self.url}
        if self.job_id:
            body["jobId"] = self.job_id
        return body

    @classmethod
    def from_message(cls, body: object) -> "SqsTicket":
        if not isinstance(body, dict):
            raise ValueError("ticket must be a JSON object")
        provider = body.get("provider")
        if provider not in PROVIDERS:
            raise ValueError(f"unknown provider: {provider!r}")
        day = parse_iso_date(body.get("date"))
        url = body.get("url")
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError("url must be an https URL")
        job_id = body.get("jobId")
        if job_id is not None and (not isinstance(job_id, str) or not job_id):
            raise ValueError("jobId must be a non-empty string")
        return cls(provider=provider, date=day.isoformat(), url=url, job_id=job_id)
