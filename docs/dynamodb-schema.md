# DynamoDB schema

Five on-demand tables. Attribute names below are the names in
`infra/template.yaml`. There is no GSI: every read in the MVP is a GetItem
or a Query on the primary key, except the region list, which is a Scan of a
four-row table.

Numbers are DynamoDB `N`. Write them with `decimal.Decimal` when the boto3
calls land; float round-trips are a common source of failed updates.

## Regions

Owned by Detect. Read by every part.

| | |
| --- | --- |
| Partition key | `regionId` (S) |
| Sort key | none |

| Attribute | Type | Notes |
| --- | --- | --- |
| `regionId` | S | `baltic`, `black-sea`, `north-atlantic`, `north-pacific`, or `custom-...` |
| `name` | S | |
| `minLat`, `maxLat`, `minLon`, `maxLon` | N | Inclusive box. No antimeridian crossing. |
| `type` | S | `hotspot`, `control`, or `custom` |
| `areaKm2` | N | Spherical-rectangle approximation used to scale the baseline |

Access: GetItem by id. Scan for `GET /regions`. Seed the four rows from
`python scripts/seed_regions.py` (print-only today; PutItem is a Detect TODO).

## DailyCounts

Written by Collect. Ratio updated by Detect. Read by Detect for the API and
the z-score window.

| | |
| --- | --- |
| Partition key | `pk` (S) = `{regionId}#{provider}` |
| Sort key | `date` (S) = `YYYY-MM-DD` |

| Attribute | Type | Written by |
| --- | --- | --- |
| `count` | N | Collect, via PutItem |
| `expected` | N | Collect, placeholder baseline; Detect replaces the rate |
| `ratio` | N | Detect (`count / expected`) |

Access: Query `pk = :pk AND date BETWEEN :from AND :to` for one timeseries
and for the trailing z-score window (suggested 30 days, minimum 7).

PutItem is the idempotency rule. Re-processing a day replaces the item.

Example key: `pk = baltic#planetiq`, `date = 2026-10-04`.

## Anomalies

Detect creates the row. Alert & Show fills GPSJam fields, risk, summary,
and `alerted`.

| | |
| --- | --- |
| Partition key | `date` (S) |
| Sort key | `sk` (S) = `{regionId}#{provider}` |

| Attribute | Type | Written by |
| --- | --- | --- |
| `regionId`, `provider` | S | Detect |
| `count`, `expected`, `ratio` | N | Detect |
| `z` | N or null | Detect. Null when the window has fewer than 7 days. |
| `flagged` | BOOL | Detect |
| `gpsjamOverlap` | N | Alert & Show. Fraction in `[0, 1]`. |
| `correlation` | N or null | Alert & Show |
| `streakDays` | N | Alert & Show |
| `risk` | S | `Low`, `Medium`, or `High` |
| `summary` | S | Placeholder sentence, or Bedrock when enabled |
| `alerted` | BOOL | True after an email is sent for this ongoing event |

Access: Query `date = :day` for `GET /hotspots` and for the Cross-checker.
GetItem `date` + `sk` to see whether this event was already alerted.

## Jobs

Detect creates the job on `POST /analyses`. Collect increments progress.

| | |
| --- | --- |
| Partition key | `jobId` (S) |
| Sort key | none |

| Attribute | Type | Notes |
| --- | --- | --- |
| `from`, `to` | S | Inclusive UTC dates |
| `providers` | L of S | |
| `status` | S | `queued`, `running`, `done`, `failed` |
| `filesTotal`, `filesDone` | N | Reader adds one to `filesDone` per ticket that carries this `jobId` |
| `created` | S | ISO-8601 timestamp. TODO when the PutItem lands. |

Access: GetItem for `GET /analyses/{id}`. Finding an overlapping running job
is a Scan. The table stays tiny (one row per backfill), so a status GSI is
optional and not in the template.

## Subscriptions

Owned by Alert & Show.

| | |
| --- | --- |
| Partition key | `subscriptionId` (S) |
| Sort key | none |

| Attribute | Type | Notes |
| --- | --- | --- |
| `email` | S | |
| `regionIds` | L of S | Empty means "not stored"; omitted in the request means all seed regions |
| `minRisk` | S | Default `High` |
| `confirmed` | BOOL | False until the subscriber accepts the SNS confirmation email |
| `snsSubscriptionArn` | S | TODO: store the ARN returned by `sns.subscribe` |

## How email filtering works

There is one SNS topic, `alerts`. A message published to it is delivered to
every confirmed subscription. Per-subscriber `regionIds` and `minRisk` need
an SNS filter policy on each subscription (message attributes `regionId` and
`risk`) so a Baltic-only subscriber does not receive a Black Sea email.

Until that policy is set, the Cross-checker publishes only `High` alerts and
the demo topic receives each of them once. `should_notify` in
`gnssiw.risk` is the rule the filter should implement, including the
`alerted` flag that blocks a second email for the same ongoing event.

## Related objects that are not DynamoDB

| Store | Location |
| --- | --- |
| Cleaned profiles | `s3://<profiles>/profiles/provider=<p>/date=<d>/part-0.parquet` |
| GPSJam cache | `s3://<profiles>/gpsjam/date=<d>/h3_4.csv` |
| Demo site | `s3://<website>/` once static hosting is turned on (`alert-show/web/`) |
| Ingest queue | one ticket per file; 3 receives, then the DLQ |
| Alert topic | one `High` alert per ongoing event |
