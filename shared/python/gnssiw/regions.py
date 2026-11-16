"""Watched regions.

The four boxes below are approximate placeholders so every teammate tags
profiles the same way. Tighten them against a coastline before quoting
October 2026 ratios. Areas use a spherical-rectangle approximation, which is
enough to scale a latitude-band baseline and is not a survey area.
"""

import math

from gnssiw.models import BoundingBox, Region

EARTH_RADIUS_KM = 6371.0


def approximate_area_km2(bbox: BoundingBox) -> float:
    """Area of a lat/lon rectangle on a sphere, in square kilometres."""
    lat1 = math.radians(bbox.min_lat)
    lat2 = math.radians(bbox.max_lat)
    delta_lon = math.radians(bbox.max_lon - bbox.min_lon)
    return abs(EARTH_RADIUS_KM**2 * delta_lon * (math.sin(lat2) - math.sin(lat1)))


def _region(region_id: str, name: str, type_: str, box: BoundingBox) -> Region:
    return Region(
        region_id=region_id,
        name=name,
        bbox=box,
        type=type_,
        area_km2=approximate_area_km2(box),
    )


# Order is the order ``GET /regions`` returns in stub mode.
SEED_REGIONS: tuple[Region, ...] = (
    _region(
        "baltic",
        "Baltic Sea",
        "hotspot",
        BoundingBox(min_lat=53.0, max_lat=66.0, min_lon=9.0, max_lon=30.5),
    ),
    _region(
        "black-sea",
        "Black Sea",
        "hotspot",
        BoundingBox(min_lat=40.5, max_lat=47.5, min_lon=27.0, max_lon=42.0),
    ),
    _region(
        "north-atlantic",
        "North Atlantic (control)",
        "control",
        BoundingBox(min_lat=35.0, max_lat=48.0, min_lon=-45.0, max_lon=-20.0),
    ),
    _region(
        "north-pacific",
        "North Pacific (control)",
        "control",
        BoundingBox(min_lat=30.0, max_lat=45.0, min_lon=150.0, max_lon=175.0),
    ),
)


def region_by_id(region_id: str, regions: tuple[Region, ...] = SEED_REGIONS) -> Region | None:
    for region in regions:
        if region.region_id == region_id:
            return region
    return None


def boxes_overlap(left: BoundingBox, right: BoundingBox) -> bool:
    separated = (
        left.max_lat < right.min_lat
        or right.max_lat < left.min_lat
        or left.max_lon < right.min_lon
        or right.max_lon < left.min_lon
    )
    return not separated
