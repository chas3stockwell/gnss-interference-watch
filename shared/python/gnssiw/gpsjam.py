"""GPSJam daily-file helpers (Part 3).

GPSJam publishes one CSV per UTC day. The format below matches the public
files as of November 2026; confirm the header and the terms of use before
the scheduled job starts downloading them.

* Manifest (latest date): ``https://gpsjam.org/data/manifest.csv``
* Daily cells: ``https://gpsjam.org/data/YYYY-MM-DD-h3_4.csv``
* Header: ``hex,count_good_aircraft,count_bad_aircraft``
* Cells are H3 resolution 4.

GPSJam's own bad-aircraft percent (FAQ) is
``100 * (count_bad_aircraft - 1) / (count_good_aircraft + count_bad_aircraft)``.
A cell is **high** above 10%, **medium** from 2% through 10%, and **low**
below 2%. Overlap for a region is the fraction of its cells that are high.
Resolving an H3 hex to a lat/lon (so it can be tested against a bounding box)
is still TODO; this module parses and classifies rows only.
"""

import csv
import io
from datetime import date

GPSJAM_DATA_ROOT = "https://gpsjam.org/data"
HIGH_FRACTION = 0.10
MEDIUM_FRACTION = 0.02


def daily_csv_url(day: date) -> str:
    return f"{GPSJAM_DATA_ROOT}/{day.isoformat()}-h3_4.csv"


def manifest_url() -> str:
    return f"{GPSJAM_DATA_ROOT}/manifest.csv"


def bad_fraction(good: int, bad: int) -> float | None:
    """GPSJam's denoised bad-aircraft fraction, or ``None`` if nobody flew the cell."""
    if good < 0 or bad < 0:
        raise ValueError("aircraft counts must be >= 0")
    total = good + bad
    if total == 0:
        return None
    return (bad - 1) / total


def gpsjam_level(good: int, bad: int) -> str:
    """``low``, ``medium``, or ``high`` using GPSJam's published cutoffs."""
    fraction = bad_fraction(good, bad)
    if fraction is None or fraction < MEDIUM_FRACTION:
        return "low"
    if fraction > HIGH_FRACTION:
        return "high"
    return "medium"


def parse_gpsjam_csv(text: str) -> list[dict[str, object]]:
    """Parse a daily CSV into ``{hex, good, bad, level}`` rows."""
    reader = csv.DictReader(io.StringIO(text.strip()))
    fields = reader.fieldnames or []
    required = {"hex", "count_good_aircraft", "count_bad_aircraft"}
    if not required.issubset(set(fields)):
        raise ValueError(f"unexpected GPSJam CSV header: {fields!r}")
    rows: list[dict[str, object]] = []
    for raw in reader:
        good = int(raw["count_good_aircraft"])
        bad = int(raw["count_bad_aircraft"])
        rows.append(
            {
                "hex": raw["hex"],
                "good": good,
                "bad": bad,
                "level": gpsjam_level(good, bad),
            }
        )
    return rows


def overlap_fraction(levels: list[str]) -> float:
    """Fraction of cells marked ``high``. No cells means no agreement (0.0)."""
    if not levels:
        return 0.0
    unknown = [level for level in levels if level not in {"low", "medium", "high"}]
    if unknown:
        raise ValueError(f"unknown GPSJam levels: {unknown}")
    return sum(1 for level in levels if level == "high") / len(levels)
