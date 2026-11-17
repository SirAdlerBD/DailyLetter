from datetime import date, timedelta

import pytest

from dailyletter import crypto, db, decide_sport, pipeline
from dailyletter.decide_sport import EASY_RUN, LONG_RUN, REST, SHORT_RUN, STRENGTH, UNKNOWN, decide_sport as decide
from dailyletter.sources.base import FRESH, SourceResult
from dailyletter.sources.garmin_mcp import dump_secret, facts_from_tools

from .conftest import at

TODAY = date(2026, 11, 16)  # a Monday
PREFS = dict(decide_sport.DEFAULTS)


def act(days_ago, type_="running", km=6.0, hard=0, minutes=35, time="07:00"):
    return {"date": (TODAY - timedelta(days=days_ago)).isoformat(), "time": time, "type": type_, "name": None,
            "distance_km": km if type_ in ("running", "cycling") else None, "duration_min": minutes,
            "hard_min": hard, "load": 60}


# Three easy runs of 6,5 km a week for four weeks, none in the last two days: a calm starting point.
CALM = [act(d, km=6.5) for d in (28, 26, 24, 21, 19, 17, 14, 12, 10, 7, 5, 3)]


def facts(sleep=(7.5, 82), hrv="BALANCED", rhr=(49, 48.0), battery=80, ratio=1.0, acts=CALM,
          zone2=(140, 154), day=TODAY):
    return {
        "date": day.isoformat(),
        "sleep": {"hours": sleep[0], "score": sleep[1]} if sleep else None,
        "hrv": {"last_night": 62, "status": hrv, "baseline_low": 55, "baseline_high": 70} if hrv else None,
        "resting_hr": {"today": rhr[0], "avg_7d": rhr[1]} if rhr else None,
        "body_battery_high": battery,
        "load": {"acute_7d": 300, "chronic_weekly": 280, "ratio": ratio},
        "zone2": list(zone2) if zone2 else None,
        "activities": acts,
    }


def run(f, hour=7, prefs=PREFS):
    return decide(SourceResult("garmin", FRESH, facts=f, fetched_at="x"), at(hour, 40), prefs)


# --- readiness --------------------------------------------------------------

def test_green_gives_an_easy_run_of_your_usual_distance():
    d = run(facts())
    assert (d.readiness, d.session, d.km) == ("green", EASY_RUN, 6.5)


@pytest.mark.parametrize("change, key", [
    ({"sleep": (5.3, 70)}, "sleep_short"),
    ({"hrv": "LOW"}, "hrv_off"),
    ({"rhr": (55, 49.0)}, "rhr_high"),
    ({"ratio": 1.6}, "load_spike"),
])
def test_one_red_signal_means_rest(change, key):
    d = run(facts(**change))
    assert (d.readiness, d.session) == ("red", REST)
    assert d.reasons[0].key == key


def test_a_hard_session_yesterday_makes_today_easy_and_shorter():
    d = run(facts(acts=CALM + [act(1, "tennis", hard=25, minutes=90)]))
    assert (d.readiness, d.session, d.km) == ("yellow", SHORT_RUN, 4.5)
    assert d.reasons[0].key == "hard_recent"


def test_two_weak_signals_make_it_yellow_one_does_not():
    assert run(facts(battery=40)).readiness == "green"
    assert run(facts(battery=40, sleep=(6.5, 75))).readiness == "yellow"


def test_without_sleep_or_hrv_there_is_no_advice():
    d = run(facts(sleep=None, hrv=None))
    assert (d.readiness, d.session) == (UNKNOWN, None)


# --- training pattern ---------------------------------------------------------

def test_never_three_impact_days_in_a_row():
    pattern = CALM + [act(2, "tennis", minutes=60), act(1)]
    d = run(facts(acts=pattern))
    assert (d.session, d.reasons[-1].key) == (STRENGTH, "impact_streak")

    with_strength = pattern + [act(4, "strength_training"), act(6, "strength_training")]
    assert run(facts(acts=with_strength)).session == REST


def test_a_rest_day_after_six_days_of_training():
    six = [act(i, "cycling", km=20) if i % 2 else act(i, "strength_training") for i in range(1, 7)]
    d = run(facts(acts=[act(10), act(12)] + six))
    assert (d.session, d.reasons[-1].key) == (REST, "no_rest_day")


def test_a_full_running_week_switches_to_strength():
    heavy = [act(d) for d in (20, 16, 12, 9)] + [act(d, km=8.0) for d in (6, 4, 2)]
    d = run(facts(acts=heavy))
    assert (d.session, d.reasons[-1].key) == (STRENGTH, "week_full")


def test_the_week_budget_keeps_a_normal_week_running():
    d = run(facts())
    assert d.run_km_7d == 13.0  # the runs 3 and 5 days ago
    assert d.run_km_week_avg == 19.5


def test_long_run_day_adds_at_most_two_km_or_ten_percent():
    prefs = {**PREFS, "long_run_day": "monday"}
    d = run(facts(acts=CALM + [act(6, km=8.85)]), prefs=prefs)
    assert (d.session, d.km) == (LONG_RUN, 9.5)


def test_data_from_another_day_gives_no_advice():
    d = run(facts(day=TODAY - timedelta(days=1)))
    assert d.fresh_today is False and d.session is None


# --- sentences --------------------------------------------------------------

class FakeGarmin:
    name = "garmin"
    needs_connection = True

    def __init__(self, f):
        self.f = f

    def fetch(self, secret, window):
        return self.f


def letter(conn, settings, user, f, hour=7, minute=40, prefs=None):
    db.set_connection(conn, user["id"], "garmin", crypto.encrypt(settings.secret_key, dump_secret("", "t" * 40)))
    for key, value in (prefs or {}).items():
        db.set_setting(conn, user["id"], key, value)
    payload = pipeline.run_for_user(conn, settings, user, now=at(hour, minute), sources=[FakeGarmin(f)])
    return {line["id"]: line["text"] for line in payload["lines"]}, payload


def test_morning_letter_has_energy_and_advice(conn, settings, user):
    lines, payload = letter(conn, settings, user, facts())
    assert lines["energy"] == "Goed geslapen: 7u30, batterij op 80."
    assert lines["sport"] == "Rustige run: 6,5 km in zone 2 (140–154 slagen)."
    panel = payload["details"]["sport"]
    assert panel["label"] == "Groen licht"
    assert [t["k"] for t in panel["tiles"]] == ["Slaap", "HRV", "Rusthartslag", "Body Battery", "Belasting"]
    assert [w["day"] for w in panel["week"]] == ["di", "wo", "do", "vr", "za", "zo", "ma"]
    assert panel["week"][-1]["today"] is True


def test_rest_and_strength_sentences_say_why(conn, settings, user):
    lines, _ = letter(conn, settings, user, facts(sleep=(5.3, 60)))
    assert lines["energy"] == "Korte nacht: 5u18, batterij op 80."
    assert lines["sport"] == "Rustdag. Je sliep maar 5u18."

    lines, _ = letter(conn, settings, user, facts(acts=CALM + [act(2, "tennis"), act(1)]))
    assert lines["sport"] == "Kracht vandaag, geen lopen. Je had al 3 dagen op rij impact."

    lines, _ = letter(conn, settings, user, facts(acts=CALM + [act(1, "tennis", hard=25, minutes=90)]))
    assert lines["sport"] == "Rustig en korter: 4,5 km in zone 2 (140–154 slagen). Gisteren was zwaar."


def test_unknown_and_stale_sentences(conn, settings, user):
    lines, _ = letter(conn, settings, user, facts(sleep=None, hrv=None))
    assert lines["sport"].startswith("Nog geen slaapdata van vannacht.")
    assert "energy" not in lines

    lines, _ = letter(conn, settings, user, facts(day=TODAY - timedelta(days=1)))
    assert lines["sport"].startswith("Je Garmin-data kon niet ververst worden.")


def test_later_in_the_day(conn, settings, user):
    lines, _ = letter(conn, settings, user, facts(), hour=12, minute=0)
    assert lines["sport"] == "Je training staat nog open: een rustige run van 6,5 km."
    assert "energy" not in lines

    done = facts(acts=CALM + [act(0, km=8.2, time="12:30")])
    lines, _ = letter(conn, settings, user, done, hour=16, minute=30)
    assert lines["sport"] == "Je training van vandaag zit erop: 8,2 km gelopen."
    lines, _ = letter(conn, settings, user, done, hour=21, minute=0)
    assert lines["sport"] == "Vandaag: 8,2 km gelopen."


def test_without_a_garmin_connection_nothing_about_sport_appears(conn, settings, user):
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeGarmin(facts())])
    ids = [line["id"] for line in payload["lines"]]
    assert "sport" not in ids and "energy" not in ids
    assert payload["sources"]["garmin"] == "missing"


# --- mapping the Garmin MCP tools ---------------------------------------------

SNAPSHOT = {
    "date": "2026-11-16",
    "sleep": {"hours": 7.5, "score": 82, "quality": "GOOD", "deepMin": 90, "remMin": 120},
    "hrv": {"date": "2026-11-16", "lastNightAvg": 62, "weeklyAvg": 60, "status": "BALANCED",
            "baseline": {"balancedLow": 55, "balancedUpper": 70}},
    "restingHR": {"today": 49, "avg7d": 48.9, "delta": 0.1},
    "bodyBatteryHigh": 85,
    "load": {"acute7d": 120, "chronicWeeklyAvg28d": 110, "acuteChronicRatio": 1.09, "zone": "optimal"},
    "flags": [],
}
ACTIVITIES = {"activities": [
    {"id": 2, "type": "tennis", "start": "2026-11-15 18:00", "durationMin": 90, "hrZonesMin": [10, 30, 25, 20, 5]},
    {"id": 1, "type": "running", "start": "2026-11-14 07:00", "distanceKm": 10, "durationMin": 50,
     "hrZonesMin": [10, 30, 10, 0, 0], "trainingLoad": 120},
]}
PROFILE = {"heartRateZones": [
    {"sport": "DEFAULT", "zoneFloors": [120, 140, 155, 170, 180]},
    {"sport": "RUNNING", "zoneFloors": [118, 138, 152, 168, 178]},
]}


def test_facts_from_the_garmin_mcp_tools():
    f = facts_from_tools("2026-11-16", SNAPSHOT, ACTIVITIES, PROFILE)
    assert f["sleep"] == {"hours": 7.5, "score": 82}
    assert f["hrv"] == {"last_night": 62, "status": "BALANCED", "baseline_low": 55, "baseline_high": 70}
    assert f["resting_hr"] == {"today": 49, "avg_7d": 48.9}
    assert f["load"]["ratio"] == 1.09
    assert f["zone2"] == [138, 151]
    assert [a["type"] for a in f["activities"]] == ["running", "tennis"]
    assert f["activities"][1]["hard_min"] == 25
    assert f["activities"][0]["date"] == "2026-11-14"


def test_garmin_secret_needs_a_token_and_a_safe_address():
    assert '"url": "http://127.0.0.1:3001/mcp"' in dump_secret("", "x" * 40)
    with pytest.raises(ValueError):
        dump_secret("", "  ")
    with pytest.raises(ValueError):
        dump_secret("http://garmin.example/mcp", "x" * 40)


def test_the_panel_does_not_repeat_the_reason_in_its_headline(conn, settings, user):
    _, payload = letter(conn, settings, user, facts(acts=CALM + [act(1, "tennis", hard=25, minutes=90)]))
    panel = payload["details"]["sport"]
    assert panel["headline"].endswith("Gisteren was zwaar.")
    assert panel["reasons"] == []

    _, payload = letter(conn, settings, user, facts(sleep=(5.3, 50), battery=40))
    reasons = payload["details"]["sport"]["reasons"]
    assert "Je sliep maar 5u18." not in reasons


def test_the_plan_week_target_lifts_a_low_four_week_average():
    # Little running in the last weeks: about 7 km a week, already 9 km in the last 6 days.
    low = [act(d, km=6.0) for d in (25, 18, 11)] + [act(5, km=4.5), act(3, km=4.5)]
    assert run(facts(acts=low)).session == STRENGTH

    d = run(facts(acts=low), prefs={**PREFS, "week_km_target": 20})
    assert (d.session, d.km) == (EASY_RUN, 6.0)
