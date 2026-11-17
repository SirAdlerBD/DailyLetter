"""Step 4 without a model: decisions become sentences from fixed templates.

This is the writer for phase 1 and stays as the fallback once a language model writes.
The detail panels are always built here, from facts, never by a model.
"""

from __future__ import annotations

from datetime import datetime

from . import texts_nl as nl
from .decide import AgendaDecision, Event
from .sources.base import STALE

FAR_MINUTES = 90
ALLOWED_DETAILS = {None, "agenda", "settings"}
MAX_LINES = 8
MAX_LINE_LENGTH = 240


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


def write_from_templates(
    version: str, now: datetime, display_name: str, agenda: AgendaDecision, prefs: dict
) -> dict:
    lines = [_line("greeting", nl.GREETING[version].format(name=display_name))]

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

    details = {}
    if agenda.available:
        details["agenda"] = {
            "today": [_event_view(e) for e in agenda.all_day_today + agenda.today],
            "tomorrow": [_event_view(e) for e in agenda.tomorrow],
        }

    return {
        "version": version,
        "date": now.date().isoformat(),
        "date_label": nl.long_date(now),
        "generated_at": now.isoformat(timespec="minutes"),
        "generated_label": nl.clock(now),
        "lines": lines,
        "details": details,
        "sources": {"agenda": agenda.status},
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
