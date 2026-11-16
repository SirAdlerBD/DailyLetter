from datetime import date

import pytest

from dailyletter.sources.agenda_ical import InvalidCalendarUrl, normalize_url, parse_ics

from .conftest import SAMPLE_ICS, TZ


def test_today_holds_timed_and_all_day_events_in_local_time():
    facts = parse_ics(SAMPLE_ICS, TZ, date(2026, 11, 16))
    titles = [e["title"] for e in facts["today"]]
    assert titles == ["Verjaardag mama", "Intake RPA-traject", "Stuurgroep testautomatisatie"]

    intake = facts["today"][1]
    assert intake["start"] == "2026-11-16T13:30:00+01:00"
    assert intake["location"] == "Teams"
    assert facts["today"][0]["all_day"] is True

    # 16:00 UTC is 17:00 in Brussels in November.
    assert facts["today"][2]["start"] == "2026-11-16T17:00:00+01:00"


def test_cancelled_events_are_left_out():
    facts = parse_ics(SAMPLE_ICS, TZ, date(2026, 11, 16))
    assert "Geannuleerde call" not in [e["title"] for e in facts["today"]]


def test_recurring_event_lands_on_tomorrow():
    facts = parse_ics(SAMPLE_ICS, TZ, date(2026, 11, 16))
    assert [e["title"] for e in facts["tomorrow"]] == ["Wekelijkse sync"]
    assert facts["tomorrow"][0]["start"] == "2026-11-17T09:00:00+01:00"


def test_all_day_event_does_not_spill_into_tomorrow():
    facts = parse_ics(SAMPLE_ICS, TZ, date(2026, 11, 16))
    assert "Verjaardag mama" not in [e["title"] for e in facts["tomorrow"]]


def test_url_must_be_https_or_webcal():
    assert normalize_url(" webcal://example.com/a.ics ") == "https://example.com/a.ics"
    assert normalize_url("https://example.com/a.ics") == "https://example.com/a.ics"
    with pytest.raises(InvalidCalendarUrl):
        normalize_url("http://example.com/a.ics")
    with pytest.raises(InvalidCalendarUrl):
        normalize_url("file:///etc/passwd")
