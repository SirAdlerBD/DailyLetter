"""Step 2 of the pipeline: fixed rules turn facts into decisions. No language model here."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .sources.base import FRESH, MISSING, SourceResult

# Defaults for per-user settings. A user overrides any of them in the `settings` table.
DEFAULTS = {
    "version_until": {"morning": "12:00", "midday": "16:00", "afternoon": "20:30"},
    "day_end": "18:00",
    "min_free_block_minutes": 30,
    "busy_from_meetings": 4,
    "notify_times": ["07:30"],        # when a notification goes out (only to phones that subscribed)
}

VERSIONS = ("morning", "midday", "afternoon", "evening")


def _clock(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def version_for(now: datetime, version_until: dict[str, str]) -> str:
    for name in ("morning", "midday", "afternoon"):
        if now.time() < _clock(version_until[name]):
            return name
    return "evening"


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str | None
    calendar: str | None = None

    @classmethod
    def from_fact(cls, fact: dict) -> "Event":
        return cls(
            title=fact["title"],
            start=datetime.fromisoformat(fact["start"]),
            end=datetime.fromisoformat(fact["end"]),
            all_day=fact["all_day"],
            location=fact.get("location"),
            calendar=fact.get("calendar"),
        )


@dataclass
class AgendaDecision:
    status: str
    fetched_at: str | None = None
    today: list[Event] = field(default_factory=list)        # timed events, in order
    all_day_today: list[Event] = field(default_factory=list)
    tomorrow: list[Event] = field(default_factory=list)     # timed events, in order
    next_event: Event | None = None                         # first one still to start today
    minutes_to_next: int | None = None
    remaining: list[Event] = field(default_factory=list)    # not finished yet today
    last_end: datetime | None = None
    free_block: tuple[datetime, datetime] | None = None
    busy: bool = False
    failed_calendars: list[str] = field(default_factory=list)  # names that could not be refreshed now

    @property
    def available(self) -> bool:
        return self.status != MISSING


def decide_agenda(result: SourceResult, now: datetime, prefs: dict) -> AgendaDecision:
    if result.facts is None:
        return AgendaDecision(status=result.status)

    today_all = [Event.from_fact(f) for f in result.facts.get("today", [])]
    tomorrow_all = [Event.from_fact(f) for f in result.facts.get("tomorrow", [])]
    today = [e for e in today_all if not e.all_day]
    decision = AgendaDecision(
        status=result.status,
        fetched_at=result.fetched_at,
        today=today,
        all_day_today=[e for e in today_all if e.all_day],
        tomorrow=[e for e in tomorrow_all if not e.all_day],
        # Only for a fresh answer: a stale one already says the whole agenda is old.
        failed_calendars=list(result.facts.get("failed", [])) if result.status == FRESH else [],
    )

    upcoming = [e for e in today if e.start > now]
    if upcoming:
        decision.next_event = upcoming[0]
        decision.minutes_to_next = int((upcoming[0].start - now).total_seconds() // 60)
    decision.remaining = [e for e in today if e.end > now]
    if decision.remaining:
        decision.last_end = max(e.end for e in decision.remaining)
    decision.busy = len(today) >= prefs["busy_from_meetings"]
    decision.free_block = _longest_free_block(decision.remaining, now, prefs)
    return decision


def _longest_free_block(
    remaining: list[Event], now: datetime, prefs: dict
) -> tuple[datetime, datetime] | None:
    day_end = datetime.combine(now.date(), _clock(prefs["day_end"]), tzinfo=now.tzinfo)
    if now >= day_end:
        return None
    best: tuple[datetime, datetime] | None = None
    cursor = now
    for event in sorted(remaining, key=lambda e: e.start):
        gap_end = min(event.start, day_end)
        if gap_end > cursor and (best is None or gap_end - cursor > best[1] - best[0]):
            best = (cursor, gap_end)
        cursor = max(cursor, event.end)
        if cursor >= day_end:
            break
    if cursor < day_end and (best is None or day_end - cursor > best[1] - best[0]):
        best = (cursor, day_end)
    if best is None or best[1] - best[0] < timedelta(minutes=prefs["min_free_block_minutes"]):
        return None
    return best
