import json
from datetime import date, datetime

import httpx
import pytest

from dailyletter.sources import agenda_ical
from dailyletter.sources.agenda_ical import (
    AgendaUnreachable,
    IcalAgendaSource,
    InvalidCalendarUrl,
    TooManyCalendars,
    add_calendar,
    dump_calendars,
    load_calendars,
    normalize_url,
    parse_ics,
    remove_calendar,
)
from dailyletter.sources.base import Window

from .conftest import SAMPLE_ICS, TZ

WORK_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//werk//NL
BEGIN:VEVENT
UID:werk-1@test
SUMMARY:Klantdemo
DTSTART;TZID=Europe/Brussels:20261116T100000
DTEND;TZID=Europe/Brussels:20261116T110000
END:VEVENT
BEGIN:VEVENT
UID:dubbel@test
SUMMARY:Intake RPA-traject
DTSTART;TZID=Europe/Brussels:20261116T133000
DTEND;TZID=Europe/Brussels:20261116T141500
END:VEVENT
END:VCALENDAR
"""


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


# --- the stored list of calendars -------------------------------------------

def test_an_address_saved_before_names_existed_still_loads():
    assert load_calendars("https://example.com/old.ics") == [{"label": "Agenda", "url": "https://example.com/old.ics"}]
    assert load_calendars(None) == []


def test_calendars_round_trip_through_the_stored_text():
    calendars = [{"label": "Privé", "url": "https://a.example/p.ics"}, {"label": "Werk", "url": "https://b.example/w.ics"}]
    assert load_calendars(dump_calendars(calendars)) == calendars


def test_add_calendar_adds_replaces_by_name_and_names_an_unnamed_one():
    calendars = add_calendar([], " Privé ", "webcal://a.example/p.ics")
    assert calendars == [{"label": "Privé", "url": "https://a.example/p.ics"}]

    calendars = add_calendar(calendars, "Werk", "https://b.example/w.ics")
    assert [c["label"] for c in calendars] == ["Privé", "Werk"]

    calendars = add_calendar(calendars, "werk", "https://b.example/nieuw.ics")
    assert calendars[1] == {"label": "werk", "url": "https://b.example/nieuw.ics"}
    assert len(calendars) == 2

    calendars = add_calendar(calendars, "   ", "https://c.example/c.ics")
    assert calendars[2]["label"] == "Agenda 3"


def test_add_calendar_refuses_a_bad_address_and_too_many():
    with pytest.raises(InvalidCalendarUrl):
        add_calendar([], "Werk", "http://b.example/w.ics")
    full = [{"label": f"A{i}", "url": f"https://x.example/{i}.ics"} for i in range(agenda_ical.MAX_CALENDARS)]
    with pytest.raises(TooManyCalendars):
        add_calendar(full, "Nog een", "https://x.example/extra.ics")


def test_remove_calendar_by_position():
    calendars = [{"label": "Privé", "url": "u1"}, {"label": "Werk", "url": "u2"}]
    assert remove_calendar(calendars, 0) == [{"label": "Werk", "url": "u2"}]
    assert remove_calendar(calendars, 5) == calendars


# --- fetching several calendars ---------------------------------------------

def fake_get(responses):
    """Answer each address with its .ics text, or raise for an address mapped to an exception."""

    def get(url, **kwargs):
        answer = responses[url]
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(200, text=answer, request=httpx.Request("GET", url))

    return get


WINDOW = Window(datetime(2026, 11, 16, 7, 40, tzinfo=TZ), TZ)
TWO = dump_calendars([
    {"label": "Privé", "url": "https://a.example/secret-prive.ics"},
    {"label": "Werk", "url": "https://b.example/secret-werk.ics"},
])


def test_two_calendars_merge_into_one_day_without_doubles(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({
        "https://a.example/secret-prive.ics": SAMPLE_ICS,
        "https://b.example/secret-werk.ics": WORK_ICS,
    }))
    facts = IcalAgendaSource().fetch(TWO, WINDOW)
    assert [(e["title"], e["calendar"]) for e in facts["today"]] == [
        ("Verjaardag mama", "Privé"),
        ("Klantdemo", "Werk"),
        ("Intake RPA-traject", "Privé"),
        ("Stuurgroep testautomatisatie", "Privé"),
    ]
    assert facts["failed"] == []


def test_one_calendar_down_still_gives_the_other(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({
        "https://a.example/secret-prive.ics": SAMPLE_ICS,
        "https://b.example/secret-werk.ics": httpx.ConnectError("boom https://b.example/secret-werk.ics"),
    }))
    facts = IcalAgendaSource().fetch(TWO, WINDOW)
    assert facts["failed"] == ["Werk"]
    assert "Klantdemo" not in [e["title"] for e in facts["today"]]
    assert "Intake RPA-traject" in [e["title"] for e in facts["today"]]


def test_when_all_fail_the_error_names_calendars_but_never_their_addresses(monkeypatch):
    error = httpx.ConnectError("could not reach https://a.example/secret-prive.ics")
    monkeypatch.setattr(httpx, "get", fake_get({
        "https://a.example/secret-prive.ics": error,
        "https://b.example/secret-werk.ics": httpx.ReadTimeout("timeout https://b.example/secret-werk.ics"),
    }))
    with pytest.raises(AgendaUnreachable) as caught:
        IcalAgendaSource().fetch(TWO, WINDOW)
    message = str(caught.value)
    assert "Privé" in message and "Werk" in message
    assert "secret" not in message and "example" not in message


def test_a_bad_stored_address_counts_as_a_failed_calendar(monkeypatch):
    monkeypatch.setattr(httpx, "get", fake_get({"https://a.example/secret-prive.ics": SAMPLE_ICS}))
    stored = json.dumps([
        {"label": "Privé", "url": "https://a.example/secret-prive.ics"},
        {"label": "Oud", "url": "http://insecure.example/x.ics"},
    ])
    assert IcalAgendaSource().fetch(stored, WINDOW)["failed"] == ["Oud"]
