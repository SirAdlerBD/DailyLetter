from datetime import date

from dailyletter import decide
from dailyletter.sources.agenda_ical import parse_ics
from dailyletter.sources.base import FRESH, MISSING, SourceResult

from .conftest import SAMPLE_ICS, TZ, at


def agenda_at(now):
    facts = parse_ics(SAMPLE_ICS, TZ, date(2026, 11, 16))
    return decide.decide_agenda(SourceResult("agenda", FRESH, facts=facts), now, decide.DEFAULTS)


def test_version_follows_the_clock():
    until = decide.DEFAULTS["version_until"]
    assert decide.version_for(at(6, 30), until) == "morning"
    assert decide.version_for(at(12, 0), until) == "midday"
    assert decide.version_for(at(16, 30), until) == "afternoon"
    assert decide.version_for(at(21, 0), until) == "evening"


def test_morning_sees_first_meeting_and_time_until_it():
    agenda = agenda_at(at(7, 40))
    assert agenda.next_event.title == "Intake RPA-traject"
    assert agenda.minutes_to_next == 350
    assert len(agenda.remaining) == 2
    assert [e.title for e in agenda.all_day_today] == ["Verjaardag mama"]


def test_free_block_runs_until_first_meeting_in_the_morning():
    agenda = agenda_at(at(7, 40))
    assert agenda.free_block == (at(7, 40), at(13, 30))


def test_free_block_is_the_longest_gap_and_stops_at_day_end():
    agenda = agenda_at(at(13, 0))
    # 13:00-13:30 (30 min) against 14:15-17:00 (2h45): the second wins.
    assert agenda.free_block == (at(14, 15), at(17, 0))


def test_no_free_block_after_the_working_day():
    assert agenda_at(at(18, 30)).free_block is None


def test_during_the_last_meeting_nothing_is_upcoming_but_one_remains():
    agenda = agenda_at(at(17, 30))
    assert agenda.next_event is None
    assert [e.title for e in agenda.remaining] == ["Stuurgroep testautomatisatie"]


def test_missing_source_gives_an_unavailable_agenda():
    agenda = decide.decide_agenda(SourceResult("agenda", MISSING), at(7, 40), decide.DEFAULTS)
    assert agenda.available is False
