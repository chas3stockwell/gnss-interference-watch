# Data contracts

Agree on these shapes first. The three parts can be built and tested in
parallel as long as the JSON on each handoff stays as written here. The
Python types in `shared/python/gnssiw/` match this file; change both together.

Dates are UTC calendar days, `YYYY-MM-DD`. Providers are `planetiq`, `spire`,
and `cosmic2`.

## SQS ticket (Collect, also enqueued for a backfill)

One message per level-2 file. The skeleton still emits one message per
provider per day, and the URL is the CDAAC directory, until the Planner
lists that directory.

```json
{
  "provider": "spire",
  "date": "2026-10-04",
  "url": "https://data.cosmic.ucar.edu/gnss-ro/spire/noaa/nrt/level2/2026/277/",
  "jobId": "optional"
}
```

`jobId` is omitted on the daily timer run and set when `POST /analyses`
asked for the day.

UCAR prefixes (public HTTPS):

| Provider | Directory |
| --- | --- |
| `planetiq` | `https://data.cosmic.ucar.edu/gnss-ro/planetiq/noaa/nrt/level2/{YYYY}/{DDD}/` |
| `spire` | `https://data.cosmic.ucar.edu/gnss-ro/spire/noaa/nrt/level2/{YYYY}/{DDD}/` |
| `cosmic2` | `https://data.cosmic.ucar.edu/gnss-ro/cosmic2/nrt/level2/{YYYY}/{DDD}/` |

`DDD` is the day of year, three digits. A day directory holds `atmPrf` and
`wetPf2` netCDF profiles and BUFR products.

## Profile row (Parquet)

S3 key, overwritten on retry:

```text
profiles/provider=planetiq/date=2026-10-04/part-0.parquet
```

Columns: `lat`, `lon`, `time`, `lowest_height_km`, `quality`, `region_id`,
`source_file`. `region_id` is null when the profile is outside every watched
region. Those rows stay in the file and are excluded from `DailyCounts`.

## DailyCounts row (Collect → Detect)

```json
{
  "pk": "baltic#spire",
  "date": "2026-10-04",
  "count": 28,
  "expected": 278.0
}
```

`pk` is `{regionId}#{provider}`. The Reader writes this with **PutItem**. A
second run of the same day replaces `count` and `expected`; it does not add
to them. `expected` is the placeholder latitude-band baseline in
`gnssiw.detection.expected_profiles` until Detect replaces the rate.

The Detector writes `ratio` (`count / expected`) back onto the same item.

## Anomaly row (Detect → Alert & Show)

DynamoDB key: partition `date`, sort `sk` = `{regionId}#{provider}`.

Detect fills `ratio`, `z`, and `flagged`. Alert & Show fills the rest.
`z` is null when fewer than 7 prior days exist. A null `z` is not flagged.

```json
{
  "date": "2026-10-04",
  "sk": "baltic#planetiq",
  "regionId": "baltic",
  "provider": "planetiq",
  "count": 35,
  "expected": 251.0,
  "ratio": 0.139,
  "z": -4.2,
  "flagged": true,
  "gpsjamOverlap": 0.42,
  "correlation": 0.8,
  "streakDays": 5,
  "risk": "High",
  "summary": "Baltic Sea profiles are at 0.14× the expected rate and GPSJam high-overlap is 42%. Risk is High.",
  "alerted": true
}
```

Step Functions passes the Detector's return value straight to the
Cross-checker. The Cross-checker scores rows with `flagged: true`. It reads
optional maps on that same event:

```json
{
  "gpsjamOverlap": {"baltic": 0.42},
  "correlation": {"baltic": 0.8},
  "streakDays": {"baltic#planetiq": 5}
}
```

Until GPSJam is downloaded, missing overlap is `0`, which cannot score
`High`. That is deliberate: a provider outage alone must not email anyone.

## Risk rule

| Risk | Rule |
| --- | --- |
| High | ratio < 0.5, z ≤ −2, GPSJam overlap ≥ 0.10, and the streak is at least 2 days |
| Medium | a strong drop without that agreement, or a moderate drop (ratio < 0.75, z ≤ −1.5) that GPSJam does agree with |
| Low | every other row |

The shared topic emails `High` only. `alerted: true` suppresses a second
email for the same ongoing event.

## GPSJam file

Confirm the header and the site's terms before the scheduled job downloads it.

* Manifest: `https://gpsjam.org/data/manifest.csv`
* Day file: `https://gpsjam.org/data/YYYY-MM-DD-h3_4.csv`
* Header: `hex,count_good_aircraft,count_bad_aircraft`
* Cells are H3 resolution 4.
* Bad-aircraft fraction: `(count_bad_aircraft - 1) / (count_good_aircraft + count_bad_aircraft)`.
* High is above 10%, medium is 2% through 10%, low is below 2%.

Overlap is the fraction of a region's cells that are high. Cache the CSV at
`gpsjam/date=YYYY-MM-DD/h3_4.csv` in the profiles bucket.

## Regions

Seed boxes live in `gnssiw.regions` and `alert-show/web/regions.json`. They
are approximate and do not overlap. Custom boxes from `POST /regions` use
the same inclusive lat/lon test and cannot cross the antimeridian.

| id | type | box (minLat, maxLat, minLon, maxLon) |
| --- | --- | --- |
| `baltic` | hotspot | 53, 66, 9, 30.5 |
| `black-sea` | hotspot | 40.5, 47.5, 27, 42 |
| `north-atlantic` | control | 35, 48, -45, -20 |
| `north-pacific` | control | 30, 45, 150, 175 |

## Jobs

`POST /analyses` returns 202 with a `jobId`. A second job whose dates overlap
a `queued` or `running` job returns 409. Ranges are inclusive and capped at
120 days. The Reader increments `filesDone` when `jobId` is on the ticket.
