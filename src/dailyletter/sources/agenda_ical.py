"""Agenda from one or more private iCal addresses (Google Calendar, Outlook, anything that exports .ics).

The stored secret is a JSON list of calendars, each with a name and an address:
    [{"label": "Privé", "url": "https://..."}, {"label": "Werk", "url": "https://..."}]
An address saved before calendars had names (a bare URL) still works: it becomes "Agenda".

Facts returned:
    {"today": [event, ...], "tomorrow": [event, ...], "failed": [label, ...]}
    event = {"title", "start", "end", "all_day", "location", "calendar"}   (ISO strings, user's time zone)
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from .base import Window

MAX_CALENDARS = 10
MAX_LABEL_LENGTH = 40
DEFAULT_LABEL = "Agenda"


class InvalidCalendarUrl(ValueError):
    pass


class TooManyCalendars(ValueError):
    pass


class AgendaUnreachable(RuntimeError):
    """Raised when no calendar could be read. The message names calendars, never their addresses."""


def normalize_url(url: str) -> str:
    """Accept webcal:// and https:// only. Plain http would send the secret address in the clear."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.lower().startswith("https://"):
        raise InvalidCalendarUrl("Het iCal-adres moet met https:// of webcal:// beginnen.")
    return url


# --- the stored list of calendars -------------------------------------------

def load_calendars(secret: str | None) -> list[dict]:
    if not secret or not secret.strip():
        return []
    text = secret.strip()
    if not text.startswith("["):
        return [{"label": DEFAULT_LABEL, "url": text}]
    return [{"label": str(c["label"]), "url": str(c["url"])} for c in json.loads(text)]


def dump_calendars(calendars: list[dict]) -> str:
    return json.dumps(calendars, ensure_ascii=False)


def add_calendar(calendars: list[dict], label: str, url: str) -> list[dict]:
    """Add a calendar, or replace the address of one with the same name."""
    url = normalize_url(url)
    label = " ".join(label.split())[:MAX_LABEL_LENGTH] or f"{DEFAULT_LABEL} {len(calendars) + 1}"
    for calendar in calendars:
        if calendar["label"].casefold() == label.casefold():
            return [{"label": label, "url": url} if c is calendar else c for c in calendars]
    if len(calendars) >= MAX_CALENDARS:
        raise TooManyCalendars(f"Je kunt hoogstens {MAX_CALENDARS} agenda's koppelen.")
    return calendars + [{"label": label, "url": url}]


def remove_calendar(calendars: list[dict], index: int) -> list[dict]:
    return [c for i, c in enumerate(calendars) if i != index]


# --- reading .ics -----------------------------------------------------------

def _to_local(value: date | datetime, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Return (aware local datetime, is_all_day)."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=tz), False
        return value.astimezone(tz), False
    return datetime.combine(value, time.min, tzinfo=tz), True


def _overlaps(start: datetime, end: datetime, day_start: datetime, day_end: datetime) -> bool:
    if start == end:
        return day_start <= start < day_end
    return start < day_end and end > day_start


def _sort_key(event: dict) -> tuple:
    return (event["start"], event["end"], event["title"])


def parse_ics(text: str, tz: ZoneInfo, today: date, label: str | None = None) -> dict:
    calendar = icalendar.Calendar.from_ical(text)
    day_start = datetime.combine(today, time.min, tzinfo=tz)
    tomorrow_start = day_start + timedelta(days=1)
    window_end = day_start + timedelta(days=2)

    days: dict[str, list[dict]] = {"today": [], "tomorrow": []}
    for item in recurring_ical_events.of(calendar).between(day_start, window_end):
        if str(item.get("STATUS", "")).upper() == "CANCELLED":
            continue
        start, all_day = _to_local(item["DTSTART"].dt, tz)
        if "DTEND" in item:
            end, _ = _to_local(item["DTEND"].dt, tz)
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(0))
        location = str(item.get("LOCATION", "")).strip() or None
        event = {
            "title": str(item.get("SUMMARY", "")).strip() or "(zonder titel)",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "all_day": all_day,
            "location": location,
            "calendar": label,
        }
        # An event counts for every day it overlaps. A zero-length one counts on its own day.
        if _overlaps(start, end, day_start, tomorrow_start):
            days["today"].append(event)
        if _overlaps(start, end, tomorrow_start, window_end):
            days["tomorrow"].append(event)

    for events in days.values():
        events.sort(key=_sort_key)
    return days


def merge_days(parts: list[dict]) -> dict:
    """Join several calendars into one day. A meeting in two calendars shows once."""
    merged: dict[str, list[dict]] = {"today": [], "tomorrow": []}
    for day in merged:
        seen = set()
        for event in sorted((e for part in parts for e in part[day]), key=_sort_key):
            key = (event["title"].casefold(), event["start"], event["end"], event["all_day"])
            if key not in seen:
                seen.add(key)
                merged[day].append(event)
    return merged


class IcalAgendaSource:
    name = "agenda"
    needs_connection = True

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def _read(self, url: str, window: Window, label: str) -> dict:
        response = httpx.get(normalize_url(url), timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        return parse_ics(response.text, window.tz, window.now.date(), label)

    def fetch(self, secret: str | None, window: Window) -> dict:
        calendars = load_calendars(secret)
        if not calendars:
            raise AgendaUnreachable("geen agenda's gekoppeld")
        parts, failed, reasons = [], [], []
        for calendar in calendars:
            try:
                parts.append(self._read(calendar["url"], window, calendar["label"]))
            except Exception as exc:
                # Only the name and the kind of error: an exception message can hold the secret address.
                failed.append(calendar["label"])
                reasons.append(f"{calendar['label']}: {type(exc).__name__}")
        if not parts:
            raise AgendaUnreachable("geen enkele agenda bereikbaar (" + "; ".join(reasons) + ")")
        facts = merge_days(parts)
        facts["failed"] = failed
        return facts
