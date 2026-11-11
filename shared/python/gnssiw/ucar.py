"""UCAR CDAAC near-real-time level-2 layout (Part 1 · Collect).

Public HTTPS directory, confirmed against the CDAAC index::

    https://data.cosmic.ucar.edu/gnss-ro/{mission}/nrt/level2/{YYYY}/{DDD}/

``mission`` is ``planetiq/noaa``, ``spire/noaa``, or ``cosmic2``. ``DDD`` is
the day of year. Each directory holds that day's level-2 products (atmPrf and
wetPf2 netCDF, plus BUFR). The Planner's real job is to list the directory
and enqueue one ticket per file. Until that listing exists, the stub enqueues
a single ticket whose URL is the directory itself.
"""

from datetime import date

from gnssiw.models import PROVIDERS, SqsTicket

UCAR_LEVEL2_ROOT = "https://data.cosmic.ucar.edu/gnss-ro"

# Path segment under ``gnss-ro/``. COSMIC-2 has no ``/noaa`` component.
PROVIDER_PATH: dict[str, str] = {
    "planetiq": "planetiq/noaa",
    "spire": "spire/noaa",
    "cosmic2": "cosmic2",
}


def day_of_year(day: date) -> str:
    """Three-digit day of year, ``001`` through ``366``."""
    return f"{day.timetuple().tm_yday:03d}"


def level2_prefix(provider: str, day: date) -> str:
    """HTTPS prefix of one provider's level-2 directory for ``day``."""
    try:
        mission = PROVIDER_PATH[provider]
    except KeyError as exc:
        raise ValueError(f"unknown provider: {provider!r}") from exc
    return f"{UCAR_LEVEL2_ROOT}/{mission}/nrt/level2/{day.year}/{day_of_year(day)}/"


def placeholder_tickets(
    day: date,
    providers: list[str] | tuple[str, ...] = PROVIDERS,
    job_id: str | None = None,
) -> list[SqsTicket]:
    """One ticket per provider, URL = that day's directory.

    TODO(Collect): replace this with one ticket per file after listing the
    directory. Keep the :class:`~gnssiw.models.SqsTicket` shape; only ``url``
    changes from a directory to a file.
    """
    unknown = [provider for provider in providers if provider not in PROVIDER_PATH]
    if unknown:
        raise ValueError(f"unknown providers: {unknown}")
    return [
        SqsTicket(
            provider=provider,
            date=day.isoformat(),
            url=level2_prefix(provider, day),
            job_id=job_id,
        )
        for provider in providers
    ]
