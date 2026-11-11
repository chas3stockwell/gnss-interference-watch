"""DynamoDB key formats and the S3 layout. See ``docs/data-contracts.md``."""


def daily_counts_pk(region_id: str, provider: str) -> str:
    """Partition key for DailyCounts: ``baltic#spire``."""
    if not region_id or not provider or "#" in region_id or "#" in provider:
        raise ValueError("region id and provider must be non-empty and must not contain '#'")
    return f"{region_id}#{provider}"


def split_daily_counts_pk(pk: str) -> tuple[str, str]:
    region_id, separator, provider = pk.partition("#")
    if separator != "#" or not region_id or not provider or "#" in provider:
        raise ValueError(f"bad DailyCounts pk: {pk!r}")
    return region_id, provider


def anomaly_sk(region_id: str, provider: str) -> str:
    """Sort key for Anomalies. Same ``region#provider`` spelling as DailyCounts."""
    return daily_counts_pk(region_id, provider)


def parquet_key(provider: str, day: str, part: int = 0) -> str:
    """Object key of the cleaned profiles for one provider and day.

    The key is deterministic. The Reader overwrites it, so a retry replaces
    the previous object instead of adding a second copy.
    """
    if part < 0:
        raise ValueError("part must be >= 0")
    return f"profiles/provider={provider}/date={day}/part-{part}.parquet"


def gpsjam_cache_key(day: str) -> str:
    """Where the Cross-checker caches that day's GPSJam CSV."""
    return f"gpsjam/date={day}/h3_4.csv"
