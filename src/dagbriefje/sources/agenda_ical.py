"""Agenda from a private iCal address (Google Calendar, Outlook, anything that exports .ics).

Facts returned:
    {"today": [event, ...], "tomorrow": [event, ...]}
    event = {"title", "start", "end", "all_day", "location"}   (ISO strings, user's time zone)
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import icalendar
import recurring_ical_events

from .base import Window


class InvalidCalendarUrl(ValueError):
    pass


def normalize_url(url: str) -> str:
    """Accept webcal:// and https:// only. Plain http would send the secret address in the clear."""
    url = url.strip()
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    if not url.lower().startswith("https://"):
        raise InvalidCalendarUrl("Het iCal-adres moet met https:// of webcal:// beginnen.")
    return url


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


def parse_ics(text: str, tz: ZoneInfo, today: date) -> dict:
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
        }
        # An event counts for every day it overlaps. A zero-length one counts on its own day.
        if _overlaps(start, end, day_start, tomorrow_start):
            days["today"].append(event)
        if _overlaps(start, end, tomorrow_start, window_end):
            days["tomorrow"].append(event)

    for events in days.values():
        events.sort(key=lambda e: (e["start"], e["end"], e["title"]))
    return days


class IcalAgendaSource:
    name = "agenda"
    needs_connection = True

    def __init__(self, timeout: float = 10.0) -> None:
        self.timeout = timeout

    def fetch(self, secret: str | None, window: Window) -> dict:
        url = normalize_url(secret or "")
        response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        response.raise_for_status()
        return parse_ics(response.text, window.tz, window.now.date())
