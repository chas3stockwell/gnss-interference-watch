"""Risk score and the correlation used beside it (Part 3 · Alert & Show).

Fusion rule, in one place so the Cross-checker and the tests cannot drift:

* **High** — strong profile drop, GPSJam agrees, and the drop has lasted at
  least two days. GPSJam agreement is required, so a provider-wide outage
  cannot by itself email subscribers.
* **Medium** — a strong drop without that agreement, or a moderate drop that
  GPSJam does agree with.
* **Low** — everything else, including a quiet control region.

Thresholds are placeholders to tune on October 2026.
"""

from gnssiw.models import RISK_LEVELS

STRONG_RATIO = 0.5
STRONG_Z = -2.0
MODERATE_RATIO = 0.75
MODERATE_Z = -1.5
# GPSJam paints a cell red above 10% bad aircraft. Overlap is the fraction of
# the region's cells that are high, so 0.10 means "10% of the region is red".
MIN_GPSJAM_OVERLAP = 0.10
MIN_STREAK_FOR_HIGH = 2

_RISK_ORDER = {level: index for index, level in enumerate(RISK_LEVELS)}


def pearson(xs: list[float], ys: list[float]) -> float | None:
    """Pearson correlation, or ``None`` when it is undefined.

    Needs at least three paired points. The ``n - 1`` terms of the sample
    formula cancel, so this matches both the sample and population coefficient.
    """
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    count = len(xs)
    mean_x = sum(xs) / count
    mean_y = sum(ys) / count
    numerator = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys, strict=True))
    spread_x = sum((x - mean_x) ** 2 for x in xs) ** 0.5
    spread_y = sum((y - mean_y) ** 2 for y in ys) ** 0.5
    if spread_x == 0 or spread_y == 0:
        return None
    return numerator / (spread_x * spread_y)


def assign_risk(
    *,
    ratio: float,
    z_score: float | None,
    gpsjam_overlap: float,
    streak_days: int,
) -> str:
    """Return ``Low``, ``Medium``, or ``High``."""
    if not 0.0 <= gpsjam_overlap <= 1.0:
        raise ValueError("gpsjam_overlap must be between 0 and 1")
    if isinstance(streak_days, bool) or not isinstance(streak_days, int) or streak_days < 0:
        raise ValueError("streak_days must be an integer >= 0")

    strong = ratio < STRONG_RATIO and z_score is not None and z_score <= STRONG_Z
    moderate = ratio < MODERATE_RATIO and z_score is not None and z_score <= MODERATE_Z
    agrees = gpsjam_overlap >= MIN_GPSJAM_OVERLAP
    if strong and agrees and streak_days >= MIN_STREAK_FOR_HIGH:
        return "High"
    if strong or (moderate and agrees):
        return "Medium"
    return "Low"


def should_notify(*, risk: str, min_risk: str, already_alerted: bool) -> bool:
    """Whether this anomaly should send a new alert.

    ``already_alerted`` stops a second email for the same ongoing event.
    Clearing it when the region returns to Low is a Part 3 TODO, so a later
    separate event can alert again.
    """
    if risk not in _RISK_ORDER:
        raise ValueError(f"unknown risk: {risk!r}")
    if min_risk not in _RISK_ORDER:
        raise ValueError(f"unknown min_risk: {min_risk!r}")
    if already_alerted:
        return False
    return _RISK_ORDER[risk] >= _RISK_ORDER[min_risk]


def placeholder_summary(*, region_name: str, ratio: float, overlap: float, risk: str) -> str:
    """Two-clause summary used until Bedrock is wired (and as its fallback)."""
    return (
        f"{region_name} profiles are at {ratio:.2f}× the expected rate "
        f"and GPSJam high-overlap is {overlap:.0%}. Risk is {risk}."
    )
