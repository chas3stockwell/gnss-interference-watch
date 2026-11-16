# GNSS Interference Watch

A serverless AWS service that flags likely GNSS jamming and spoofing regions
from public data. Each day it collects GPS radio-occultation profiles
published by UCAR (PlanetIQ, Spire, and COSMIC-2), compares regional counts
with each provider's baseline, cross-checks flagged regions against
[GPSJam](https://gpsjam.org/) airplane reports, and can email subscribers.
A Leaflet map is the demo client.

This is a Northwestern CS 310 skeleton. The handlers return the agreed
shapes and the pure scoring rules are tested. Calls to UCAR, GPSJam,
DynamoDB, S3, SQS, SNS, and Bedrock are marked `TODO` and stay off while
`GNSSIW_STUB=1` (the deploy default).

The course's three non-trivial server operations, one per teammate:

1. **Collect** — parallel ingest. Fan out one SQS ticket per UCAR file, decode netCDF/BUFR, and tag each profile with a region.
2. **Detect** — anomaly detection. Density ratio against a latitude-band baseline, plus a rolling z-score.
3. **Alert & Show** — fusion. GPSJam overlap and correlation, a Low/Medium/High risk score, and an email alert.

## Architecture

![Architecture diagram](docs/architecture.svg)

A PNG of the same diagram is in `docs/architecture.png`.

Steps 1–7 run every day. EventBridge starts the Planner, which enqueues one
ticket per file. Readers pull the queue (three failures go to the
dead-letter queue), write Parquet to S3, and upsert `DailyCounts`. Later,
Step Functions runs the Detector and then the Cross-checker. The
Cross-checker publishes to SNS when a region scores High.

Steps A and B run when someone uses the site. API Gateway fronts two
Lambdas: Detect serves regions, timeseries, and backfill jobs; Alert & Show
serves hotspots and subscriptions. `POST /analyses` reuses the ingest queue
to backfill a range such as October 2026.

| Color | Part | Folder |
| --- | --- | --- |
| Blue | Collect | `collect/` |
| Yellow | Detect | `detect/` |
| Green | Alert & Show | `alert-show/` |

Dashed boxes in the diagram (Bedrock, SageMaker) are optional. SageMaker is
not in the template.

## Repository layout

```text
collect/planner/            EventBridge -> list the day's UCAR files
collect/reader/             SQS -> decode, tag, Parquet, DailyCounts
                            Dockerfile is the container image for real decoding
detect/detector/            Step Functions state 1: ratio and z-score
detect/request_handler/     GET/POST /regions, /regions/{id}/timeseries, /analyses
alert-show/cross_checker/   Step Functions state 2: GPSJam fusion and alerts
alert-show/api_handler/     GET /hotspots, POST /subscriptions
alert-show/web/             Leaflet map (illustrative October colors until the API is set)
shared/python/gnssiw/       Keys, regions, scoring, GPSJam and UCAR URL helpers
infra/template.yaml         SAM template (queue, DLQ, tables, functions, API, state machine)
docs/                       Diagram, OpenAPI, DynamoDB schema, handoff contracts
events/                     Sample payloads for sam local invoke
scripts/seed_regions.py     Print the four seed regions
tests/                      Unit tests, plus a check that the template matches the OpenAPI spec
```

Handoff JSON is specified in [docs/data-contracts.md](docs/data-contracts.md).
Change that file and `shared/python/gnssiw/` together. The API is
[docs/openapi.yaml](docs/openapi.yaml). Table keys and attributes are
[docs/dynamodb-schema.md](docs/dynamodb-schema.md). The Canvas proposal
draft is [docs/milestone-1-proposal.md](docs/milestone-1-proposal.md).

## Local setup

Python 3.12.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
ruff check .
ruff format --check .
```

`make test` and `make lint` run the same checks.

Map (the page loads `regions.json`, so open it through a local server):

```bash
cd alert-show/web
python3 -m http.server 8080
```

Open <http://localhost:8080>. Drag the October 2026 slider: the Baltic and
Black Sea turn red after 4 October, and the two control regions stay green.
Those colors are an illustrative pattern, not measurements. Paste the
deployed `ApiBaseUrl` into `window.GNSSIW_API_BASE` in `index.html` when
`GET /hotspots` returns real rows.

Invoke a stub handler after `sam build`:

```bash
sam local invoke PlannerFunction -t infra/template.yaml -e events/planner.json
sam local invoke ReaderFunction -t infra/template.yaml -e events/reader-sqs.json
sam local invoke DetectorFunction -t infra/template.yaml -e events/detector.json
sam local invoke CrossCheckerFunction -t infra/template.yaml -e events/cross-checker.json
sam local invoke RequestHandlerFunction -t infra/template.yaml -e events/api-get-regions.json
```

`sam local invoke` needs Docker. The unit tests cover the same events
without it.

Print the seed regions (this does not call AWS):

```bash
python scripts/seed_regions.py
```

## Deploy

Install the [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
and configure the course AWS credentials. Pick one region and keep it.
`samconfig.toml.example` assumes `us-east-1`.

Set an AWS budget alarm before the first deploy. A stub stack should stay
inside the free tier; Bedrock and a long backfill are the pieces that can
spend money.

```bash
sam build -t infra/template.yaml
sam deploy -t infra/template.yaml --guided
```

Accept the defaults, including `StubMode=1`. `--guided` writes
`samconfig.toml`, which is gitignored because it records the region and
bucket. You can start from `samconfig.toml.example` instead.

Useful outputs:

| Output | Use |
| --- | --- |
| `ApiBaseUrl` | Paste into `alert-show/web/index.html` as `GNSSIW_API_BASE` |
| `IngestQueueUrl` / `IngestDlqUrl` | Watch tickets drain, and confirm a bad file reaches the DLQ |
| `ProfilesBucketName` | Parquet and the GPSJam cache |
| `WebsiteBucketName` | Sync `alert-show/web/` here once static hosting is enabled |
| `AnalysisStateMachineArn` | The daily Detect → Cross-check run |

The website bucket is private. Turn on static website hosting or CloudFront
when the demo should be public, then `aws s3 sync alert-show/web s3://<WebsiteBucketName>/`.

Schedules, in UTC: the Planner at 12:00, and the state machine at 13:30.
Both default the date to yesterday, because UCAR publishes a day after it
closes. The gap assumes the queue has drained; gating the Detector on an
empty queue is still a TODO.

`AlertEmail` subscribes one address at deploy time. AWS sends a confirmation
link that has to be accepted. Further subscribers go through
`POST /subscriptions` once that TODO calls `sns.subscribe`.

### Switching the Reader to a container image

Real netCDF and BUFR libraries are large, so the production Reader should be
the image in `collect/reader/Dockerfile` (build context is the repo root).
The template uses a zip so the first `sam build` does not need Docker.
When the decoder lands, build the image, push it to ECR, and change
`ReaderFunction` to `PackageType: Image` with:

```yaml
Metadata:
  Dockerfile: collect/reader/Dockerfile
  DockerContext: ..
  DockerTag: gnssiw-reader
```

Drop `CodeUri` and the zip `Handler` on that function. The image's `CMD`
is already `handler.handler`.

Flip `StubMode` to `0` only after the `enqueue`, `persist`, and publish
TODOs exist. Until then a live invocation raises `NotImplementedError`, and
the Reader reports that as an SQS batch failure so the message retries and
then lands in the DLQ.

## API

| Verb and path | Success | Also | Owner |
| --- | --- | --- | --- |
| `GET /regions` | 200 | | Detect |
| `POST /regions` | 201 | 400 invalid box | Detect |
| `GET /regions/{id}/timeseries` | 200 | 400 bad query, 404 | Detect |
| `POST /analyses` | 202 | 400 bad range, 409 overlapping job | Detect |
| `GET /analyses/{id}` | 200 | 404 | Detect |
| `GET /hotspots` | 200 | 400 bad date | Alert & Show |
| `POST /subscriptions` | 201 | 400 | Alert & Show |

`POST /analyses` caps a range at 120 days. Query `provider` is `planetiq`,
`spire`, or `cosmic2`. Timeseries points stay empty until DailyCounts is
queried. Hotspots stay empty until Anomalies is queried. Status codes are
what the tests lock in.

## Scoring rules in the skeleton

These are placeholders to tune on real October 2026 data. They live in
`shared/python/gnssiw/` so the Lambdas and the tests share one definition.

- **Density ratio** = count / expected. 1.0 is a normal day.
- **Expected count** scales a per-provider rate by region area. The rates in
  `PLACEHOLDER_PROFILES_PER_10K_KM2` are not a climatology. Replace them
  before comparing a ratio to the research figures (Baltic about 0.10–0.14×,
  controls about 1×). The Detector test feeds 35 and 251 in as inputs; it
  does not claim the placeholder rate produces 251.
- **Z-score** is the sample z-score of today's ratio against a trailing
  window that excludes today. The suggested window is 30 days. Fewer than 7
  days and `z` is null, and a null `z` is not flagged. A backfill that
  starts on 1 October cannot flag the first week unless September is
  included in the window.
- **Flag** when ratio < 0.5 and z ≤ −2.
- **Risk** is High only when the drop is strong, GPSJam overlap is at least
  0.10, and the streak is at least 2 days. A provider outage with no GPSJam
  agreement stays Medium and does not email. The topic sends High only, and
  `alerted` blocks a second email for the same ongoing event.

GPSJam files, as published in late 2026: `https://gpsjam.org/data/YYYY-MM-DD-h3_4.csv`
with header `hex,count_good_aircraft,count_bad_aircraft` (H3 resolution 4).
Confirm the header and the site's terms before the scheduled download.
`gnssiw.gpsjam` implements their bad-aircraft fraction,
`(bad - 1) / (good + bad)`, and the 2% / 10% color cutoffs.

UCAR level-2 directories:

```text
https://data.cosmic.ucar.edu/gnss-ro/planetiq/noaa/nrt/level2/{YYYY}/{DDD}/
https://data.cosmic.ucar.edu/gnss-ro/spire/noaa/nrt/level2/{YYYY}/{DDD}/
https://data.cosmic.ucar.edu/gnss-ro/cosmic2/nrt/level2/{YYYY}/{DDD}/
```

`DDD` is the day of year. Each directory holds that day's `atmPrf`, `wetPf2`,
and BUFR files. The stub enqueues the directory URL; the real Planner lists
it and enqueues one ticket per file.

Seed boxes (approximate, non-overlapping) are `baltic`, `black-sea`,
`north-atlantic`, and `north-pacific`. Tighten them against a coastline
before quoting October ratios. `alert-show/web/regions.json` is checked
against `gnssiw.regions` in the tests.

## Checklists

Milestone 1 is due **Friday, November 20, 2026, 11:59 pm CST**. Milestone 2
is due **Wednesday, December 2, 2026, 11:59 pm CST**, with no late
submission. One teammate submits the Canvas proposal, the video, the 2–3
page description, and the source zip. The zip's install note is `readme.txt`.

### Whole team, before Milestone 1

- [ ] Confirm [docs/data-contracts.md](docs/data-contracts.md), including region boxes and the DailyCounts PutItem rule.
- [ ] Create the AWS account, pick a region, and set a budget alarm.
- [ ] `sam deploy` this skeleton with `StubMode=1`.
- [ ] Paste [docs/milestone-1-proposal.md](docs/milestone-1-proposal.md) into Canvas and click Submit.

### Part 1 · Collect

Milestone 1:

- [ ] `sam local invoke` the Planner with `events/planner.json` and see one ticket per provider.
- [ ] The ingest queue and the dead-letter queue exist, `maxReceiveCount` 3.
- [ ] A stub Reader invocation of `events/reader-sqs.json` succeeds.

Milestone 2, done when:

- [ ] The daily timer runs with nobody starting it.
- [ ] One ticket per level-2 file appears in SQS (the directory listing TODO).
- [ ] A bad file lands in the dead-letter queue instead of stopping the batch.
- [ ] Parquet for one full day is in S3 under `profiles/provider=.../date=.../part-0.parquet`.
- [ ] Counts for the Baltic, the Black Sea, and both controls are in `DailyCounts`.
- [ ] Re-running a day replaces the count. `upsert_counts` is that rule; the DynamoDB call has to be PutItem on `(pk, date)`.

### Part 2 · Detect

Milestone 1:

- [ ] Detector on `events/detector.json`: Baltic flagged, North Atlantic not.
- [ ] `GET /regions` returns the four seed regions. Load them into the Regions table (`scripts/seed_regions.py` currently only prints).
- [ ] One Step Functions execution completes both states in stub mode.

Milestone 2, done when:

- [ ] The latitude-band baseline replaces `PLACEHOLDER_PROFILES_PER_10K_KM2`, and October ratios land near the research figures.
- [ ] Z-scores are stored. The trailing window reaches back before 1 October so the first demo week can flag.
- [ ] Step Functions runs the Detector every day.
- [ ] The API returns the status codes in the table above, including 404 for an unknown region and 409 for an overlapping job.
- [ ] `POST /analyses` invokes the Planner once per day with `jobId`, and `GET /analyses/{id}` reports `filesDone` / `filesTotal` as the Reader updates the job.

### Part 3 · Alert & Show

Milestone 1:

- [ ] Cross-checker on `events/cross-checker.json` returns one High notification. Publishing it is still the SNS TODO.
- [ ] The local map loads, the slider moves, hotspots go red, controls stay green.
- [ ] `POST /subscriptions` returns 201 with `confirmed: false`.

Milestone 2, done when:

- [ ] A day's GPSJam CSV is downloaded, cached, and matched to our regions (H3 centroid against the box).
- [ ] Every flagged anomaly has a risk score, overlap, and summary.
- [ ] A test subscriber receives an email for a known event, such as the Baltic in October 2026, after accepting the SNS confirmation.
- [ ] The same ongoing event does not send a second email (`alerted`).
- [ ] The map is served from S3, colors follow the live ratio, and the slider still works.
- [ ] Optional: `ENABLE_BEDROCK=1` replaces the placeholder summary with two sentences, and a model error falls back to the placeholder.

### Course artifacts for Milestone 2

- [ ] 5–10 minute video. Every member speaks. Start from the diagram, then the demo in the project write-up: backfill October, move the slider, open the Baltic, show an alert, and `curl` the API including one 404.
- [ ] 2–3 page description PDF: the diagram, the API (verbs, parameters, bodies, status codes), and the DynamoDB schema. `docs/openapi.yaml` and `docs/dynamodb-schema.md` are the source for that section.
- [ ] Zip of this tree, including `readme.txt`, the Dockerfile, and the template. Leave out `.venv`, `.aws-sam`, and `samconfig.toml`.
