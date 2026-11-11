"""Density ratio, z-score, Detector scoring, and the Detect API."""

import statistics
from datetime import date

import pytest

from gnssiw.detection import (
    MIN_HISTORY_DAYS,
    density_ratio,
    expected_profiles,
    is_flagged,
    rolling_zscore,
)
from gnssiw.models import BoundingBox, Region
from tests.api_helpers import api_event, response_body

HISTORY = [1.0, 1.05, 0.98, 1.1, 0.95, 1.02, 0.97, 1.08, 1.0, 0.99, 1.04, 0.96, 1.01, 1.03]


def test_density_ratio_matches_the_october_baltic_inputs():
    assert density_ratio(35, 251) == pytest.approx(35 / 251)
    with pytest.raises(ValueError):
        density_ratio(-1, 10)
    with pytest.raises(ValueError):
        density_ratio(1, 0)
    with pytest.raises(ValueError):
        density_ratio(True, 10)


def test_expected_profiles_scale_with_area():
    assert expected_profiles("spire", 20_000, rate_per_10k_km2=0.2) == pytest.approx(0.4)
    small = expected_profiles("planetiq", 10_000, rate_per_10k_km2=0.15)
    large = expected_profiles("planetiq", 30_000, rate_per_10k_km2=0.15)
    assert large == pytest.approx(small * 3)


def test_rolling_zscore_uses_the_sample_standard_deviation():
    today = 0.14
    expected = (today - statistics.mean(HISTORY)) / statistics.stdev(HISTORY)
    assert rolling_zscore(today, HISTORY) == pytest.approx(expected)
    assert rolling_zscore(today, HISTORY[: MIN_HISTORY_DAYS - 1]) is None
    flat = [1.0] * MIN_HISTORY_DAYS
    assert rolling_zscore(1.0, flat) == 0.0
    assert rolling_zscore(0.2, flat) is None


def test_flag_requires_a_low_ratio_and_an_unusual_drop():
    assert is_flagged(0.49, -2.0) is True
    assert is_flagged(0.5, -3.0) is False
    assert is_flagged(0.1, -1.9) is False
    assert is_flagged(0.1, None) is False


def test_detector_flags_the_baltic_drop_and_not_the_control(detector):
    result = detector.run(
        {
            "date": "2026-10-04",
            "series": {
                "baltic#planetiq": {"count": 35, "expected": 251, "history": HISTORY},
                "north-atlantic#planetiq": {"count": 105, "expected": 100, "history": HISTORY},
            },
        }
    )
    by_region = {row["regionId"]: row for row in result["anomalies"]}
    assert by_region["baltic"]["flagged"] is True
    assert by_region["baltic"]["ratio"] == pytest.approx(35 / 251)
    assert by_region["baltic"]["z"] < -2
    assert by_region["north-atlantic"]["flagged"] is False
    assert result["flagged"] == 1


def test_short_history_is_scored_but_not_flagged(detector):
    result = detector.run(
        {
            "date": "2026-10-04",
            "series": {"baltic#spire": {"count": 1, "expected": 100, "history": [1.0, 1.0]}},
        }
    )
    row = result["anomalies"][0]
    assert row["z"] is None
    assert row["flagged"] is False


def test_window_env_is_honored(detector, monkeypatch):
    monkeypatch.setenv("Z_WINDOW_DAYS", "14")
    assert detector.run({"date": "2026-10-04"})["windowDays"] == 14
    monkeypatch.setenv("Z_WINDOW_DAYS", "3")
    with pytest.raises(ValueError):
        detector.run({"date": "2026-10-04"})


def test_list_regions(request_handler):
    result = request_handler.route(api_event("GET", "/regions"))
    assert result["statusCode"] == 200
    body = response_body(result)
    assert [region["id"] for region in body["regions"]] == [
        "baltic",
        "black-sea",
        "north-atlantic",
        "north-pacific",
    ]


def test_timeseries_status_codes(request_handler):
    missing = request_handler.route(
        api_event("GET", "/regions/{id}/timeseries", path_params={"id": "nope"}, query={})
    )
    assert missing["statusCode"] == 404

    bad_query = request_handler.route(
        api_event("GET", "/regions/{id}/timeseries", path_params={"id": "baltic"})
    )
    assert bad_query["statusCode"] == 400

    bad_provider = request_handler.route(
        api_event(
            "GET",
            "/regions/{id}/timeseries",
            path_params={"id": "baltic"},
            query={"provider": "gps", "from": "2026-10-01", "to": "2026-10-31"},
        )
    )
    assert bad_provider["statusCode"] == 400

    backwards = request_handler.route(
        api_event(
            "GET",
            "/regions/{id}/timeseries",
            path_params={"id": "baltic"},
            query={"provider": "spire", "from": "2026-10-31", "to": "2026-10-01"},
        )
    )
    assert backwards["statusCode"] == 400

    ok = request_handler.route(
        api_event(
            "GET",
            "/regions/{id}/timeseries",
            path_params={"id": "baltic"},
            query={"provider": "spire", "from": "2026-10-01", "to": "2026-10-31"},
        )
    )
    assert ok["statusCode"] == 200
    assert response_body(ok)["points"] == []


def test_create_region_validates_the_box(request_handler):
    created = request_handler.route(
        api_event(
            "POST",
            "/regions",
            body={
                "name": "Gulf of Bothnia",
                "minLat": 60,
                "maxLat": 66,
                "minLon": 16,
                "maxLon": 26,
            },
        )
    )
    assert created["statusCode"] == 201
    assert response_body(created)["id"] == "custom-gulf-of-bothnia"
    assert response_body(created)["type"] == "custom"

    inverted = request_handler.route(
        api_event(
            "POST",
            "/regions",
            body={"name": "Nope", "minLat": 10, "maxLat": 0, "minLon": 0, "maxLon": 1},
        )
    )
    assert inverted["statusCode"] == 400

    duplicate = Region(
        region_id="custom-gulf-of-bothnia",
        name="Gulf of Bothnia",
        bbox=BoundingBox(60, 66, 16, 26),
        type="custom",
        area_km2=1,
    )
    from gnssiw.regions import SEED_REGIONS

    again = request_handler.route(
        api_event(
            "POST",
            "/regions",
            body={
                "name": "Gulf of Bothnia",
                "minLat": 60,
                "maxLat": 66,
                "minLon": 16,
                "maxLon": 26,
            },
        ),
        regions=[*SEED_REGIONS, duplicate],
    )
    assert again["statusCode"] == 400


def test_analyses_accepts_october_and_rejects_a_conflict(request_handler):
    accepted = request_handler.route(
        api_event("POST", "/analyses", body={"from": "2026-10-01", "to": "2026-10-31"})
    )
    assert accepted["statusCode"] == 202
    job = response_body(accepted)
    assert job["status"] == "queued"
    assert job["jobId"].startswith("job-")
    assert job["filesDone"] == 0

    backwards = request_handler.route(
        api_event("POST", "/analyses", body={"from": "2026-10-31", "to": "2026-10-01"})
    )
    assert backwards["statusCode"] == 400

    # 1 Jan through 1 May 2026 is 121 days.
    too_long = request_handler.route(
        api_event("POST", "/analyses", body={"from": "2026-01-01", "to": "2026-05-01"})
    )
    assert too_long["statusCode"] == 400

    running = {
        "jobId": "job-running",
        "status": "running",
        "from": "2026-10-01",
        "to": "2026-10-10",
    }
    conflict = request_handler.route(
        api_event("POST", "/analyses", body={"from": "2026-10-10", "to": "2026-10-12"}),
        jobs=[running],
    )
    assert conflict["statusCode"] == 409
    assert response_body(conflict)["jobId"] == "job-running"

    finished = {**running, "status": "done"}
    after = request_handler.route(
        api_event("POST", "/analyses", body={"from": "2026-10-01", "to": "2026-10-10"}),
        jobs=[finished],
    )
    assert after["statusCode"] == 202

    missing = request_handler.route(
        api_event("GET", "/analyses/{id}", path_params={"id": "job-missing"})
    )
    assert missing["statusCode"] == 404
    found = request_handler.route(
        api_event("GET", "/analyses/{id}", path_params={"id": "job-running"}),
        jobs=[running],
    )
    assert found["statusCode"] == 200
    assert response_body(found)["status"] == "running"


def test_unknown_route_is_404(request_handler):
    result = request_handler.route(api_event("GET", "/hotspots"))
    assert result["statusCode"] == 404


def test_handler_turns_unexpected_errors_into_500(request_handler, monkeypatch):
    def explode(event, **kwargs):
        del event, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(request_handler, "route", explode)
    result = request_handler.handler({}, None)
    assert result["statusCode"] == 500
    assert "boom" not in result["body"]


def test_sample_events_drive_the_detector(detector):
    import json
    from pathlib import Path

    event = json.loads(
        (Path(__file__).resolve().parents[1] / "events" / "detector.json").read_text(
            encoding="utf-8"
        )
    )
    result = detector.run(event)
    assert result["date"] == "2026-10-04"
    assert result["flagged"] == 1


def test_yesterday_helper_used_when_the_schedule_omits_a_date(detector, monkeypatch):
    monkeypatch.setattr(detector, "yesterday_utc", lambda: date(2026, 11, 10))
    assert detector.run({"source": "schedule"})["date"] == "2026-11-10"
