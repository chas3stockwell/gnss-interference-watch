"""Density ratio and rolling z-score (Part 2 · Detect).

A region is flagged only when today's ratio is low **and** the drop is unusual
for that region. Thresholds are placeholders to tune on real October 2026
counts. They live here so the Detector Lambda and the tests share one rule.

"Expected" profiles come from that provider's normal rate at the region's
latitude, scaled by area. The rates below are stand-ins so the formula has a
home; replace them with a latitude-band climatology before comparing to the
research numbers (Baltic ~0.10–0.14×, controls ~1×).
"""

# Profiles per 10,000 km² per day. Not a measurement.
PLACEHOLDER_PROFILES_PER_10K_KM2: dict[str, float] = {
    "planetiq": 0.15,
    "spire": 0.18,
    "cosmic2": 0.12,
}

# Trailing window passed to ``rolling_zscore``, excluding today.
SUGGESTED_WINDOW_DAYS = 30
# Fewer history points than this and the z-score is undefined.
MIN_HISTORY_DAYS = 7

# Flag when the ratio is strictly below this AND the z-score is at or below
# ``Z_FLAG``. A ratio of 1.0 is a normal day.
RATIO_FLAG = 0.5
Z_FLAG = -2.0


def density_ratio(count: int, expected: float) -> float:
    """Profiles received divided by profiles expected. 1.0 is a normal day."""
    if isinstance(count, bool) or not isinstance(count, int):
        raise ValueError("count must be an integer")
    if count < 0:
        raise ValueError("count must be >= 0")
    if expected <= 0:
        raise ValueError("expected must be > 0")
    return count / expected


def expected_profiles(
    provider: str,
    area_km2: float,
    rate_per_10k_km2: float | None = None,
) -> float:
    """Placeholder expected-count for one region, provider, and day.

    TODO(Detect): ``rate_per_10k_km2`` should be the provider's own normal
    rate in this latitude band, not ``PLACEHOLDER_PROFILES_PER_10K_KM2``.
    """
    if area_km2 <= 0:
        raise ValueError("area_km2 must be > 0")
    if rate_per_10k_km2 is None:
        try:
            rate_per_10k_km2 = PLACEHOLDER_PROFILES_PER_10K_KM2[provider]
        except KeyError as exc:
            raise ValueError(f"unknown provider: {provider!r}") from exc
    if rate_per_10k_km2 <= 0:
        raise ValueError("rate must be > 0")
    return rate_per_10k_km2 * (area_km2 / 10_000.0)


def rolling_zscore(today_ratio: float, history: list[float]) -> float | None:
    """Sample z-score of ``today_ratio`` against a trailing window.

    ``history`` is prior days only (do not include today). Returns ``None``
    when the window is shorter than :data:`MIN_HISTORY_DAYS`, and when the
    window has zero variance but today differs from it — a z-score is
    undefined if every recent day was identical and today is not. Returns
    ``0.0`` when today equals a zero-variance window.
    """
    if len(history) < MIN_HISTORY_DAYS:
        return None
    count = len(history)
    mean = sum(history) / count
    variance = sum((value - mean) ** 2 for value in history) / (count - 1)
    if variance == 0:
        return 0.0 if today_ratio == mean else None
    return (today_ratio - mean) / variance**0.5


def is_flagged(
    ratio: float,
    z_score: float | None,
    *,
    ratio_max: float = RATIO_FLAG,
    z_max: float = Z_FLAG,
) -> bool:
    """True when the drop is both large and unusual.

    A missing z-score does not flag. Backfilling October therefore needs a
    prior window (start the job in September, or accept that the first
    ``MIN_HISTORY_DAYS`` cannot flag).
    """
    if z_score is None:
        return False
    return ratio < ratio_max and z_score <= z_max
