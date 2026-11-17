"""Step 4 without a model: decisions become sentences from fixed templates.

This is the writer for phase 1 and stays as the fallback once a language model writes.
The detail panels are always built here, from facts, never by a model.
"""

from __future__ import annotations

from datetime import datetime

from . import texts_nl as nl
from .decide import AgendaDecision, Event
from .decide_sport import (
    EASY_RUN, LONG_RUN, RED, REST, SHORT_RUN, STRENGTH, UNKNOWN, Activity, Reason, SportDecision,
)
from .sources.base import STALE

FAR_MINUTES = 90
ALLOWED_DETAILS = {None, "agenda", "sport", "settings"}
MAX_LINES = 10
MAX_LINE_LENGTH = 240
NOTE_COMPUTED = "Herstel en belasting zijn berekend door je Garmin-MCP, niet door Garmins eigen Training Readiness."


def _line(line_id: str, text: str, detail: str | None = None) -> dict:
    return {"id": line_id, "text": text, "detail": detail}


def _event_view(event: Event) -> dict:
    return {
        "title": event.title,
        "start": None if event.all_day else nl.clock(event.start),
        "end": None if event.all_day else nl.clock(event.end),
        "all_day": event.all_day,
        "location": event.location,
        "calendar": event.calendar,
    }


def _morning(agenda: AgendaDecision, now: datetime) -> list[dict]:
    lines: list[dict] = []
    if not agenda.today:
        lines.append(_line("agenda", nl.T["agenda.empty_today"], "agenda"))
    elif agenda.next_event is not None:
        first = agenda.next_event is agenda.today[0]
        far = agenda.minutes_to_next >= FAR_MINUTES
        key = f"agenda.{'first' if first else 'next'}_{'far' if far else 'near'}"
        lines.append(_line("agenda", nl.T[key].format(
            duration=nl.duration(agenda.minutes_to_next), title=agenda.next_event.title), "agenda"))
        if len(agenda.today) >= 2:
            lines.append(_line("agenda_count", nl.T["agenda.count_today"].format(
                count=len(agenda.today), end=nl.clock(max(e.end for e in agenda.today))), "agenda"))
    elif agenda.remaining:
        current = agenda.remaining[0]
        lines.append(_line("agenda", nl.T["agenda.now"].format(
            title=current.title, end=nl.clock(current.end)), "agenda"))
    else:
        lines.append(_line("agenda", nl.T["agenda.done"], "agenda"))
    if agenda.all_day_today and not agenda.busy:
        titles = ", ".join(e.title for e in agenda.all_day_today[:2])
        lines.append(_line("agenda_all_day", nl.T["agenda.all_day"].format(titles=titles), "agenda"))
    return lines


def _daytime(agenda: AgendaDecision, with_free_block: bool) -> list[dict]:
    lines: list[dict] = []
    if not agenda.remaining:
        key = "agenda.done" if agenda.today else "agenda.rest_empty"
        return [_line("agenda", nl.T[key], "agenda")]
    if len(agenda.remaining) == 1:
        only = agenda.remaining[0]
        lines.append(_line("agenda", nl.T["agenda.remaining_one"].format(
            title=only.title, end=nl.clock(only.end)), "agenda"))
    else:
        lines.append(_line("agenda", nl.T["agenda.remaining_many"].format(
            count=len(agenda.remaining), end=nl.clock(agenda.last_end)), "agenda"))
    if with_free_block and agenda.free_block and not agenda.busy:
        start, end = agenda.free_block
        lines.append(_line("agenda_free", nl.T["agenda.free_block"].format(
            start=nl.clock(start), end=nl.clock(end)), "agenda"))
    return lines


def _evening(agenda: AgendaDecision, busy_from: int) -> list[dict]:
    if not agenda.tomorrow:
        return [_line("agenda", nl.T["agenda.tomorrow_empty"], "agenda")]
    first = agenda.tomorrow[0]
    lines = [_line("agenda", nl.T["agenda.tomorrow_first"].format(
        title=first.title, start=nl.clock(first.start)), "agenda")]
    if len(agenda.tomorrow) >= busy_from:
        lines.append(_line("agenda_count", nl.T["agenda.tomorrow_busy"].format(
            count=len(agenda.tomorrow)), "agenda"))
    return lines


# --- sport ------------------------------------------------------------------

def _why(reason: Reason) -> str:
    params = dict(reason.params)
    if reason.key == "hard_recent":
        return nl.T[f"why.hard_recent_{params['days_ago']}"]
    if reason.key == "sleep_short":
        params["hours"] = nl.hours_minutes(params["hours"])
    if reason.key == "week_full":
        params["km"] = nl.number(params["km"])
    if reason.key == "long_run_day":
        params["longest"] = nl.number(params["longest"])
    return nl.T[f"why.{reason.key}"].format(**params)


def _reasons(sport: SportDecision) -> list[Reason]:
    return [r for r in sport.reasons if r.key not in ("no_sleep_data", "stale")]


def _main_reason(sport: SportDecision) -> Reason | None:
    """Recovery decides first; otherwise the training pattern that changed the plan."""
    reasons = _reasons(sport)
    if not reasons:
        return None
    if sport.readiness == RED or sport.session not in (REST, STRENGTH):
        return reasons[0]
    return reasons[-1]


def _hr(sport: SportDecision) -> str:
    zone2 = sport.facts.get("zone2")
    return nl.T["sport.hr"].format(low=zone2[0], high=zone2[1]) if zone2 else ""


def _summary(activities: list[Activity]) -> str:
    parts = []
    for a in activities:
        if a.group == "running" and a.distance_km:
            parts.append(f"{nl.number(a.distance_km)} km gelopen")
        elif a.group == "cycling" and a.distance_km:
            parts.append(f"{nl.number(a.distance_km)} km gefietst")
        elif a.duration_min:
            parts.append(f"{nl.activity_label(a.type, a.group).lower()}, {a.duration_min} minuten")
        else:
            parts.append(nl.activity_label(a.type, a.group).lower())
    return " en ".join(parts)


def _advice(sport: SportDecision) -> str | None:
    """The morning sentence: what kind of day it is for training."""
    if sport.readiness == UNKNOWN:
        return None
    reason = _main_reason(sport)
    why = _why(reason) if reason else ""
    km = nl.number(sport.km) if sport.km is not None else ""
    if sport.session == REST:
        return nl.T["sport.rest"].format(why=why)
    if sport.session == STRENGTH:
        return nl.T["sport.strength"].format(why=why)
    if sport.session == EASY_RUN:
        return nl.T["sport.easy_run"].format(km=km, hr=_hr(sport))
    if sport.session == SHORT_RUN:
        return nl.T["sport.short_run"].format(km=km, hr=_hr(sport), why=why)
    if sport.session == LONG_RUN:
        return nl.T["sport.long_run"].format(km=km, hr=_hr(sport))
    return None


def _sport_lines(version: str, sport: SportDecision) -> list[dict]:
    if not sport.available:
        return []
    if not sport.fresh_today:
        return [_line("sport", nl.T["sport.stale"], "sport")] if version == "morning" else []
    if sport.done_today:
        key = {"morning": "sport.done_morning", "evening": "sport.done_evening"}.get(version, "sport.done_day")
        return [_line("sport", nl.T[key].format(summary=_summary(sport.done_today)), "sport")]
    if version == "morning":
        text = _advice(sport) or nl.T["sport.unknown"]
        return [_line("sport", text, "sport")]
    if version in ("midday", "afternoon") and sport.session in (EASY_RUN, SHORT_RUN, LONG_RUN, STRENGTH):
        km = nl.number(sport.km) if sport.km is not None else ""
        session = nl.T[f"session.{sport.session}"].format(km=km)
        return [_line("sport", nl.T["sport.open_day"].format(session=session), "sport")]
    return []


def _energy_line(sport: SportDecision) -> dict | None:
    sleep = sport.facts.get("sleep")
    if not sport.fresh_today or not sleep:
        return None
    battery = sport.facts.get("body_battery_high")
    if sleep["hours"] < 6:
        kind = "short"
    elif sleep["hours"] >= 7 and (sleep.get("score") is None or sleep["score"] >= 70):
        kind = "good"
    else:
        kind = "plain"
    key = f"energy.{kind}" + ("" if battery is not None else "_nobattery")
    return _line("energy", nl.T[key].format(sleep=nl.hours_minutes(sleep["hours"]), battery=battery), "sport")


def _sport_details(sport: SportDecision, now: datetime) -> dict:
    facts = sport.facts
    tiles = []
    if facts.get("sleep"):
        sleep = facts["sleep"]
        tiles.append({"k": "Slaap", "v": nl.hours_minutes(sleep["hours"]),
                      "s": f"score {sleep['score']}" if sleep.get("score") is not None else ""})
    if facts.get("hrv") and facts["hrv"].get("last_night") is not None:
        hrv = facts["hrv"]
        tiles.append({"k": "HRV", "v": f"{hrv['last_night']} ms",
                      "s": nl.HRV_STATUS.get(hrv.get("status") or "", (hrv.get("status") or "").lower())})
    if facts.get("resting_hr"):
        rhr = facts["resting_hr"]
        avg = rhr.get("avg_7d")
        tiles.append({"k": "Rusthartslag", "v": str(rhr["today"]),
                      "s": f"gemiddeld {nl.number(avg)}" if avg is not None else ""})
    if facts.get("body_battery_high") is not None:
        tiles.append({"k": "Body Battery", "v": str(facts["body_battery_high"]), "s": "hoogste vandaag"})
    load = facts.get("load") or {}
    if load.get("ratio") is not None:
        tiles.append({"k": "Belasting", "v": nl.number(load["ratio"], 2), "s": "deze week tegenover je gemiddelde"})

    week = []
    for day, activities in sport.week:
        items = []
        for a in activities:
            label = nl.activity_label(a.type, a.group)
            if a.distance_km and a.group in ("running", "cycling"):
                label += f" {nl.number(a.distance_km)} km"
            items.append(label)
        week.append({"day": nl.DAYS_SHORT[day.weekday()], "today": day == now.date(), "items": items})

    in_headline = None
    if sport.done_today:
        headline = nl.T["sport.done_morning"].format(summary=_summary(sport.done_today))
    elif not sport.fresh_today:
        headline = nl.T["sport.stale"]
    else:
        headline = _advice(sport) or nl.T["sport.unknown"]
        if sport.session in (REST, STRENGTH, SHORT_RUN):
            in_headline = _main_reason(sport)

    return {
        "readiness": sport.readiness,
        "label": nl.READINESS_LABEL[sport.readiness],
        "headline": headline,
        # The reason already in the headline is not repeated underneath.
        "reasons": [_why(r) + "." for r in _reasons(sport) if r is not in_headline],
        "tiles": tiles,
        "week": week,
        "run_km_week": nl.number(sum(a.distance_km or 0 for _, acts in sport.week for a in acts if a.group == "running")),
        "run_km_avg": nl.number(sport.run_km_week_avg),
        "run_km_target": nl.number(float(sport.week_km_target)) if sport.week_km_target else None,
        "note": NOTE_COMPUTED,
    }


def write_from_templates(
    version: str,
    now: datetime,
    display_name: str,
    agenda: AgendaDecision,
    prefs: dict,
    sport: SportDecision | None = None,
) -> dict:
    sport = sport or SportDecision(status="missing")
    lines = [_line("greeting", nl.GREETING[version].format(name=display_name))]

    if version == "morning":
        energy = _energy_line(sport)
        if energy:
            lines.append(energy)

    if not agenda.available:
        lines.append(_line("agenda", nl.T["agenda.missing"], "settings"))
    else:
        if version == "morning":
            lines += _morning(agenda, now)
        elif version in ("midday", "afternoon"):
            lines += _daytime(agenda, with_free_block=version == "midday")
        else:
            lines += _evening(agenda, prefs["busy_from_meetings"])
        if agenda.status == STALE and agenda.fetched_at:
            fetched = datetime.fromisoformat(agenda.fetched_at).astimezone(now.tzinfo)
            lines.append(_line("agenda_stale", nl.T["agenda.stale"].format(
                when=nl.short_when(fetched, now)), "agenda"))
        if agenda.failed_calendars:
            lines.append(_line("agenda_partial", nl.T["agenda.partial"].format(
                names=nl.join_names(agenda.failed_calendars)), "settings"))

    lines += _sport_lines(version, sport)

    details = {}
    if agenda.available:
        details["agenda"] = {
            "today": [_event_view(e) for e in agenda.all_day_today + agenda.today],
            "tomorrow": [_event_view(e) for e in agenda.tomorrow],
        }
    if sport.available and sport.facts:
        details["sport"] = _sport_details(sport, now)

    return {
        "version": version,
        "date": now.date().isoformat(),
        "date_label": nl.long_date(now),
        "generated_at": now.isoformat(timespec="minutes"),
        "generated_label": nl.clock(now),
        "lines": lines,
        "details": details,
        "sources": {"agenda": agenda.status, "garmin": sport.status},
    }


def validate(payload: dict) -> None:
    """Step 5: refuse a briefing that the page cannot show properly."""
    lines = payload.get("lines")
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError("a briefing needs between 1 and %d lines" % MAX_LINES)
    for line in lines:
        text = line.get("text", "")
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_LINE_LENGTH:
            raise ValueError(f"line {line.get('id')!r} is empty or too long")
        if line.get("detail") not in ALLOWED_DETAILS:
            raise ValueError(f"line {line.get('id')!r} points to an unknown detail panel")
        if line["detail"] not in (None, "settings") and line["detail"] not in payload.get("details", {}):
            raise ValueError(f"line {line.get('id')!r} points to a detail panel without content")
