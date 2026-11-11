"""GPSJam classification, risk scores, and the alert API."""

import json
from datetime import date
from pathlib import Path

import pytest

from gnssiw.gpsjam import (
    daily_csv_url,
    gpsjam_level,
    overlap_fraction,
    parse_gpsjam_csv,
)
from gnssiw.risk import assign_risk, pearson, should_notify
from tests.api_helpers import api_event, response_body

ROOT = Path(__file__).resolve().parents[1]
HISTORY = [1.0, 1.05, 0.98, 1.1, 0.95, 1.02, 0.97, 1.08, 1.0, 0.99, 1.04, 0.96, 1.01, 1.03]


def test_gpsjam_levels_follow_the_published_cutoffs():
    assert gpsjam_level(0, 10) == "high"
    assert gpsjam_level(80, 20) == "high"
    # (11 - 1) / 100 = 0.10, and high starts strictly above 10%.
    assert gpsjam_level(89, 11) == "medium"
    assert gpsjam_level(98, 2) == "low"
    assert gpsjam_level(0, 0) == "low"
    assert overlap_fraction(["high", "low", "high", "medium"]) == pytest.approx(0.5)
    assert overlap_fraction([]) == 0.0


def test_parse_gpsjam_csv_and_url():
    rows = parse_gpsjam_csv("hex,count_good_aircraft,count_bad_aircraft\nabc,0,10\ndef,98,2\n")
    assert [row["level"] for row in rows] == ["high", "low"]
    assert daily_csv_url(date(2026, 10, 4)).endswith("/2026-10-04-h3_4.csv")
    with pytest.raises(ValueError):
        parse_gpsjam_csv("lat,lon\n1,2\n")


def test_pearson_correlation():
    assert pearson([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)
    assert pearson([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert pearson([1, 2], [1, 2]) is None
    assert pearson([1, 1, 1], [1, 2, 3]) is None


def test_high_risk_needs_gpsjam_agreement_and_a_streak():
    assert assign_risk(ratio=0.14, z_score=-3.0, gpsjam_overlap=0.4, streak_days=2) == "High"
    assert assign_risk(ratio=0.14, z_score=-3.0, gpsjam_overlap=0.4, streak_days=1) == "Medium"
    # A provider outage: the profiles vanished, but airplanes did not agree.
    assert assign_risk(ratio=0.14, z_score=-3.0, gpsjam_overlap=0.0, streak_days=10) == "Medium"
    assert assign_risk(ratio=1.05, z_score=0.2, gpsjam_overlap=0.0, streak_days=0) == "Low"
    assert assign_risk(ratio=0.6, z_score=-1.6, gpsjam_overlap=0.2, streak_days=1) == "Medium"
    with pytest.raises(ValueError):
        assign_risk(ratio=0.1, z_score=-3.0, gpsjam_overlap=1.2, streak_days=2)


def test_should_notify_suppresses_a_repeat_and_respects_the_bar():
    assert should_notify(risk="High", min_risk="High", already_alerted=False) is True
    assert should_notify(risk="High", min_risk="High", already_alerted=True) is False
    assert should_notify(risk="Medium", min_risk="High", already_alerted=False) is False
    assert should_notify(risk="High", min_risk="Medium", already_alerted=False) is True


def _detected(detector):
    return detector.run(
        {
            "date": "2026-10-04",
            "series": {
                "baltic#planetiq": {"count": 35, "expected": 251, "history": HISTORY},
                "north-atlantic#planetiq": {"count": 105, "expected": 100, "history": HISTORY},
            },
        }
    )


def test_cross_checker_alerts_once_for_an_ongoing_high_event(detector, cross_checker):
    detected = _detected(detector)
    detected["gpsjamOverlap"] = {"baltic": 0.42}
    detected["streakDays"] = {"baltic#planetiq": 5}
    fused = cross_checker.run(detected)
    assert [row["regionId"] for row in fused["results"]] == ["baltic"]
    assert fused["results"][0]["risk"] == "High"
    assert fused["results"][0]["alerted"] is True
    assert "Baltic Sea" in fused["results"][0]["summary"]
    assert len(fused["notifications"]) == 1

    again = cross_checker.run({**detected, "anomalies": fused["results"]})
    assert again["notifications"] == []
    assert again["results"][0]["alerted"] is True


def test_cross_checker_does_not_email_a_drop_gpsjam_did_not_confirm(detector, cross_checker):
    detected = _detected(detector)
    detected["gpsjamOverlap"] = {"baltic": 0.0}
    fused = cross_checker.run(detected)
    assert fused["results"][0]["risk"] == "Medium"
    assert fused["notifications"] == []


def test_sample_cross_checker_event(cross_checker):
    event = json.loads((ROOT / "events" / "cross-checker.json").read_text(encoding="utf-8"))
    result = cross_checker.run(event)
    assert result["notifications"][0]["risk"] == "High"


def test_hotspots_and_subscriptions(alert_api, monkeypatch):
    monkeypatch.setattr(alert_api, "yesterday_utc", lambda: date(2026, 11, 10))
    latest = alert_api.route(api_event("GET", "/hotspots"))
    assert latest["statusCode"] == 200
    assert response_body(latest)["date"] == "2026-11-10"
    assert response_body(latest)["hotspots"] == []

    bad_date = alert_api.route(api_event("GET", "/hotspots", query={"date": "10/04/2026"}))
    assert bad_date["statusCode"] == 400

    supplied = alert_api.route(
        api_event("GET", "/hotspots", query={"date": "2026-10-04"}),
        hotspots=[{"regionId": "baltic", "risk": "High"}],
    )
    assert response_body(supplied)["hotspots"][0]["regionId"] == "baltic"

    created = alert_api.route(
        api_event(
            "POST", "/subscriptions", body={"email": "pilot@example.com", "regionIds": ["baltic"]}
        )
    )
    assert created["statusCode"] == 201
    body = response_body(created)
    assert body["confirmed"] is False
    assert body["minRisk"] == "High"
    assert body["regionIds"] == ["baltic"]
    assert body["subscriptionId"].startswith("sub-")

    assert (
        alert_api.route(api_event("POST", "/subscriptions", body={"email": "nope"})).get(
            "statusCode"
        )
        == 400
    )
    assert (
        alert_api.route(
            api_event(
                "POST",
                "/subscriptions",
                body={"email": "pilot@example.com", "minRisk": "high"},
            )
        )["statusCode"]
        == 400
    )
    assert (
        alert_api.route(
            api_event(
                "POST",
                "/subscriptions",
                body={"email": "pilot@example.com", "regionIds": ["atlantis"]},
            )
        )["statusCode"]
        == 400
    )


def test_alert_handler_hides_unexpected_errors(alert_api, monkeypatch):
    def explode(event, **kwargs):
        del event, kwargs
        raise RuntimeError("boom")

    monkeypatch.setattr(alert_api, "route", explode)
    result = alert_api.handler({}, None)
    assert result["statusCode"] == 500
