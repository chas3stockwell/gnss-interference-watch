"""Planner tickets, Reader tagging, and the idempotent count write."""

import json
from datetime import date

import pytest

from gnssiw.detection import expected_profiles
from gnssiw.models import SqsTicket
from gnssiw.regions import SEED_REGIONS, boxes_overlap, region_by_id
from gnssiw.ucar import level2_prefix

ROOT_EVENTS = __import__("pathlib").Path(__file__).resolve().parents[1] / "events"


def test_level2_prefixes_match_cdaac_layout():
    october = date(2026, 10, 4)
    assert level2_prefix("planetiq", october).endswith("/planetiq/noaa/nrt/level2/2026/277/")
    assert level2_prefix("spire", october).endswith("/spire/noaa/nrt/level2/2026/277/")
    # 2024 is a leap year: 1 March is day 061.
    assert level2_prefix("cosmic2", date(2024, 3, 1)).endswith("/cosmic2/nrt/level2/2024/061/")


def test_planner_emits_one_ticket_per_provider(planner):
    plan = planner.build_plan({"date": "2026-10-04", "jobId": "job-demo"})
    assert [ticket["provider"] for ticket in plan["tickets"]] == ["planetiq", "spire", "cosmic2"]
    assert plan["tickets"][0]["url"].startswith("https://")
    assert plan["tickets"][0]["jobId"] == "job-demo"
    roundtrip = SqsTicket.from_message(plan["tickets"][1])
    assert roundtrip.provider == "spire"
    assert roundtrip.date == "2026-10-04"


def test_daily_ticket_omits_job_id(planner):
    plan = planner.build_plan({"date": "2026-10-04"})
    assert "jobId" not in plan["tickets"][0]


def test_unknown_provider_is_rejected(planner):
    with pytest.raises(ValueError, match="unknown provider"):
        planner.build_plan({"date": "2026-10-04", "providers": ["gps"]})


def test_missing_date_is_yesterday(planner, monkeypatch):
    monkeypatch.setattr(planner, "yesterday_utc", lambda: date(2026, 10, 3))
    assert planner.build_plan({})["date"] == "2026-10-03"


def test_stub_handler_does_not_touch_sqs(planner):
    result = planner.handler({"date": "2026-10-04"}, None)
    assert result["mode"] == "stub"
    assert result["enqueued"] == 0
    assert len(result["tickets"]) == 3


def test_live_enqueue_is_still_a_todo(planner, monkeypatch):
    monkeypatch.setenv("GNSSIW_STUB", "0")
    with pytest.raises(NotImplementedError):
        planner.handler({"date": "2026-10-04"}, None)


def test_seed_boxes_do_not_overlap_and_cover_the_sample_points():
    boxes = [region.bbox for region in SEED_REGIONS]
    for index, left in enumerate(boxes):
        for right in boxes[index + 1 :]:
            assert not boxes_overlap(left, right)
    assert region_by_id("baltic").bbox.contains(58.5, 20.0)
    assert region_by_id("black-sea").bbox.contains(43.5, 34.0)
    assert region_by_id("north-atlantic").bbox.contains(40.0, -30.0)
    assert region_by_id("north-pacific").bbox.contains(38.0, 165.0)
    assert region_by_id("baltic").bbox.contains(53.0, 20.0)


def _profiles():
    return [
        {"lat": 58.5, "lon": 20.0, "time": "2026-10-04T00:00:00Z", "source_file": "a.nc"},
        {"lat": 59.0, "lon": 21.0, "time": "2026-10-04T01:00:00Z", "source_file": "b.nc"},
        {"lat": 36.0, "lon": 18.0, "time": "2026-10-04T02:00:00Z", "source_file": "c.nc"},
    ]


def test_reader_tags_regions_and_skips_outsiders(reader):
    ticket = SqsTicket(
        provider="planetiq",
        date="2026-10-04",
        url="https://data.cosmic.ucar.edu/gnss-ro/planetiq/noaa/nrt/level2/2026/277/",
        job_id="job-demo",
    )
    result = reader.process_ticket(ticket, profiles=_profiles())
    assert result["parquetKey"] == "profiles/provider=planetiq/date=2026-10-04/part-0.parquet"
    assert result["profiles"] == 3
    assert result["counts"][0]["pk"] == "baltic#planetiq"
    assert result["counts"][0]["count"] == 2
    baltic = region_by_id("baltic")
    assert result["counts"][0]["expected"] == pytest.approx(
        expected_profiles("planetiq", baltic.area_km2)
    )
    # A second pass of the same profiles still reports 2, not 4.
    again = reader.process_ticket(ticket, profiles=_profiles())
    assert again["counts"][0]["count"] == 2


def test_rerun_replaces_a_daily_count(reader):
    table = {}
    row = {"pk": "baltic#planetiq", "date": "2026-10-04", "count": 10, "expected": 5.0}
    reader.upsert_counts(table, [row])
    reader.upsert_counts(table, [{**row, "count": 4}])
    assert table[("baltic#planetiq", "2026-10-04")]["count"] == 4


def test_bad_ticket_is_a_batch_failure_and_a_good_one_is_not(reader):
    event = {
        "Records": [
            {"messageId": "bad", "body": "{"},
            {
                "messageId": "good",
                "body": json.dumps(
                    {
                        "provider": "cosmic2",
                        "date": "2026-10-04",
                        "url": "https://data.cosmic.ucar.edu/gnss-ro/cosmic2/nrt/level2/2026/277/file.nc",
                    }
                ),
            },
        ]
    }
    result = reader.handle_sqs(event)
    assert result["batchItemFailures"] == [{"itemIdentifier": "bad"}]
    assert result["processed"][0]["provider"] == "cosmic2"
    assert result["processed"][0]["counts"] == []


def test_live_reader_fails_the_message_until_persist_exists(reader, monkeypatch):
    monkeypatch.setenv("GNSSIW_STUB", "0")
    event = json.loads((ROOT_EVENTS / "reader-sqs.json").read_text(encoding="utf-8"))
    result = reader.handle_sqs(event)
    assert result["batchItemFailures"] == [{"itemIdentifier": "example-1"}]
    assert result["processed"] == []


def test_sample_planner_event(planner):
    event = json.loads((ROOT_EVENTS / "planner.json").read_text(encoding="utf-8"))
    result = planner.handler(event, None)
    assert result["jobId"] == "job-demo"
    assert result["tickets"][0]["url"].endswith("/2026/277/")
