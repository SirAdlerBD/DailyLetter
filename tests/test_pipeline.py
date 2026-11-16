from datetime import date

import pytest

from dailyletter import compose, crypto, db, pipeline
from dailyletter.sources.agenda_ical import parse_ics

from .conftest import SAMPLE_ICS, at


class FakeAgenda:
    """Stands in for the iCal source: same name, same facts, no network."""

    name = "agenda"
    needs_connection = True

    def __init__(self, fail=False):
        self.fail = fail
        self.seen_secret = None

    def fetch(self, secret, window):
        self.seen_secret = secret
        if self.fail:
            raise RuntimeError("calendar unreachable")
        return parse_ics(SAMPLE_ICS, window.tz, window.now.date())


def connect_agenda(conn, settings, user):
    token = crypto.encrypt(settings.secret_key, "https://example.com/secret.ics")
    db.set_connection(conn, user["id"], "agenda", token)


def texts(payload):
    return [line["text"] for line in payload["lines"]]


def test_morning_briefing_from_a_connected_agenda(conn, settings, user):
    connect_agenda(conn, settings, user)
    source = FakeAgenda()
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[source])

    assert source.seen_secret == "https://example.com/secret.ics"
    assert payload["version"] == "morning"
    assert payload["sources"] == {"agenda": "fresh"}
    assert texts(payload) == [
        "Goeiemorgen Cedric.",
        "Je eerste meeting is pas over 5u50. Tot dan is je agenda vrij.",
        "Vandaag 2 meetings, de laatste eindigt om 18u30.",
        "Ook vandaag: Verjaardag mama.",
    ]
    assert payload["details"]["agenda"]["today"][1] == {
        "title": "Intake RPA-traject", "start": "13u30", "end": "14u15", "all_day": False, "location": "Teams",
    }
    assert db.latest_briefing(conn, user["id"], "2026-11-16") == payload


def test_other_versions_of_the_day(conn, settings, user):
    connect_agenda(conn, settings, user)
    midday = pipeline.run_for_user(conn, settings, user, now=at(12, 0), sources=[FakeAgenda()])
    assert texts(midday) == [
        "Goeiemiddag Cedric.",
        "Nog 2 meetings vandaag, de laatste eindigt om 18u30.",
        "Je langste vrije blok loopt van 14u15 tot 17u.",
    ]
    afternoon = pipeline.run_for_user(conn, settings, user, now=at(16, 30), sources=[FakeAgenda()])
    assert texts(afternoon)[1] == "Nog één meeting vandaag: Stuurgroep testautomatisatie, tot 18u30."
    evening = pipeline.run_for_user(conn, settings, user, now=at(21, 0), sources=[FakeAgenda()])
    assert texts(evening) == ["Goeienavond Cedric.", "Morgen begint met Wekelijkse sync om 9u."]


def test_without_a_connection_the_briefing_points_to_settings(conn, settings, user):
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeAgenda()])
    assert payload["sources"] == {"agenda": "missing"}
    assert payload["lines"][1]["detail"] == "settings"
    assert payload["details"] == {}


def test_a_failing_source_falls_back_to_the_last_good_answer(conn, settings, user):
    connect_agenda(conn, settings, user)
    pipeline.run_for_user(conn, settings, user, now=at(6, 30), sources=[FakeAgenda()])
    payload = pipeline.run_for_user(conn, settings, user, now=at(12, 0), sources=[FakeAgenda(fail=True)])

    assert payload["sources"] == {"agenda": "stale"}
    assert texts(payload)[1] == "Nog 2 meetings vandaag, de laatste eindigt om 18u30."
    assert texts(payload)[-1].startswith("Je agenda kon niet ververst worden.")
    failed = conn.execute("SELECT error FROM snapshots WHERE ok = 0").fetchone()
    assert "calendar unreachable" in failed["error"]


def test_a_failing_source_without_history_is_missing(conn, settings, user):
    connect_agenda(conn, settings, user)
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeAgenda(fail=True)])
    assert payload["sources"] == {"agenda": "missing"}


def test_the_secret_is_not_stored_in_plain_text(conn, settings, user):
    connect_agenda(conn, settings, user)
    stored = db.get_connection(conn, user["id"], "agenda")
    assert "example.com" not in stored
    assert crypto.decrypt(settings.secret_key, stored) == "https://example.com/secret.ics"
    with pytest.raises(crypto.SecretKeyError):
        crypto.decrypt(crypto.generate_key(), stored)


def test_per_user_settings_override_the_defaults(conn, settings, user):
    connect_agenda(conn, settings, user)
    db.set_setting(conn, user["id"], "version_until", {"morning": "07:00", "midday": "16:00", "afternoon": "20:30"})
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeAgenda()])
    assert payload["version"] == "midday"


def test_validate_refuses_a_broken_briefing():
    with pytest.raises(ValueError):
        compose.validate({"lines": []})
    with pytest.raises(ValueError):
        compose.validate({"lines": [{"id": "a", "text": "x", "detail": "agenda"}], "details": {}})
    with pytest.raises(ValueError):
        compose.validate({"lines": [{"id": "a", "text": "x" * 300, "detail": None}]})
