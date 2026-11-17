"""Sport advice from fixed rules: first recovery, then the training pattern. No language model here.

The rules follow the coach agreements: injury prevention first, then as much load as is safe.
    red    -> rest: sleep under 6 h, HRV not balanced, resting HR 5+ above its 7-day average,
              or a load spike (acute:chronic above 1.5)
    yellow -> easy and shorter: load ratio 1.3-1.5, two or more weak signals,
              or a hard session in the last two days
    green  -> build safely
Then the pattern: never three impact days in a row, at least one day without training per week,
and the week's running volume at most about 10% above the 4-week average, or up to the week
target from your training plan when that is higher.
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .sources.base import FRESH, MISSING, STALE, SourceResult

DEFAULTS = {
    "long_run_day": None,        # "saturday", "sunday", ... or None for no fixed long run
    "max_week_increase": 0.10,   # running km over the 4-week average
    "week_km_target": None,      # this week's running km from your training plan; never aim lower
    "min_run_km": 4.0,           # shorter than this is not worth suggesting
    "default_run_km": 5.0,       # used when there is no running history yet
}

WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

GROUPS = [
    ("running", re.compile(r"run|treadmill|track")),
    ("racket", re.compile(r"tennis|padel|squash|badminton|pickleball|racket")),
    ("strength", re.compile(r"strength|weight|gym|hiit|fitness_equipment|crossfit")),
    ("cycling", re.compile(r"cycl|bik|ride")),
    ("swimming", re.compile(r"swim")),
    ("walking", re.compile(r"walk|hik")),
]
IMPACT = {"running", "racket"}

RED, YELLOW, GREEN, UNKNOWN = "red", "yellow", "green", "unknown"
REST, STRENGTH, EASY_RUN, SHORT_RUN, LONG_RUN = "rest", "strength", "easy_run", "short_run", "long_run"


def group_of(activity_type: str) -> str:
    for name, pattern in GROUPS:
        if pattern.search(activity_type.lower()):
            return name
    return "other"


def half_km(value: float) -> float:
    return round(value * 2) / 2


@dataclass
class Activity:
    day: date
    time: str | None
    type: str
    group: str
    name: str | None
    distance_km: float | None
    duration_min: int | None
    hard_min: int | None

    @classmethod
    def from_fact(cls, fact: dict) -> "Activity":
        return cls(
            day=date.fromisoformat(fact["date"]),
            time=fact.get("time"),
            type=fact.get("type") or "unknown",
            group=group_of(fact.get("type") or ""),
            name=fact.get("name"),
            distance_km=fact.get("distance_km"),
            duration_min=fact.get("duration_min"),
            hard_min=fact.get("hard_min"),
        )


@dataclass
class Reason:
    key: str
    params: dict = field(default_factory=dict)


@dataclass
class SportDecision:
    status: str
    readiness: str = UNKNOWN
    session: str | None = None
    km: float | None = None
    reasons: list[Reason] = field(default_factory=list)     # why this readiness and session
    done_today: list[Activity] = field(default_factory=list)
    facts: dict = field(default_factory=dict)
    week: list[tuple[date, list[Activity]]] = field(default_factory=list)  # last 7 days, today included
    run_km_7d: float = 0.0
    run_km_week_avg: float = 0.0
    fetched_at: str | None = None
    fresh_today: bool = False
    week_km_target: float | None = None

    @property
    def available(self) -> bool:
        return self.status != MISSING


def _readiness(facts: dict, past: list[Activity], today: date, typical_run: float) -> tuple[str, list[Reason]]:
    sleep, hrv, rhr, load = facts.get("sleep"), facts.get("hrv"), facts.get("resting_hr"), facts.get("load")
    if sleep is None and hrv is None:
        return UNKNOWN, [Reason("no_sleep_data")]

    red: list[Reason] = []
    if sleep and sleep["hours"] < 6:
        red.append(Reason("sleep_short", {"hours": sleep["hours"]}))
    if hrv and hrv.get("status") and hrv["status"] != "BALANCED":
        red.append(Reason("hrv_off", {"status": hrv["status"], "value": hrv.get("last_night")}))
    rhr_delta = None
    if rhr and rhr.get("avg_7d") is not None:
        rhr_delta = rhr["today"] - rhr["avg_7d"]
        if rhr_delta >= 5:
            red.append(Reason("rhr_high", {"delta": round(rhr_delta)}))
    ratio = (load or {}).get("ratio")
    if ratio is not None and ratio > 1.5:
        red.append(Reason("load_spike", {"ratio": ratio}))
    if red:
        return RED, red

    yellow: list[Reason] = []
    if ratio is not None and ratio > 1.3:
        yellow.append(Reason("load_high", {"ratio": ratio}))
    weak = []
    if sleep and sleep.get("score") is not None and sleep["score"] < 60:
        weak.append("sleep_score")
    if sleep and sleep["hours"] < 7:
        weak.append("sleep_hours")
    if facts.get("body_battery_high") is not None and facts["body_battery_high"] < 50:
        weak.append("body_battery")
    if rhr_delta is not None and rhr_delta >= 3:
        weak.append("rhr")
    if len(weak) >= 2:
        yellow.append(Reason("weak_signals", {"signals": weak}))
    long_from = max(12.0, typical_run * 1.3)
    for activity in reversed(past):
        days_ago = (today - activity.day).days
        if days_ago > 2:
            break
        long_run = activity.group == "running" and (activity.distance_km or 0) >= long_from
        if (activity.hard_min or 0) >= 15 or long_run:
            yellow.append(Reason("hard_recent", {"days_ago": days_ago, "group": activity.group, "type": activity.type}))
            break
    if yellow:
        return YELLOW, yellow
    return GREEN, []


def _streak(today: date, past: list[Activity], counts) -> int:
    """Days in a row before today on which `counts` held for at least one activity."""
    by_day: dict[date, list[Activity]] = {}
    for activity in past:
        by_day.setdefault(activity.day, []).append(activity)
    streak, day = 0, today - timedelta(days=1)
    while any(counts(a) for a in by_day.get(day, [])):
        streak += 1
        day -= timedelta(days=1)
    return streak


def decide_sport(result: SourceResult, now: datetime, prefs: dict) -> SportDecision:
    decision = SportDecision(status=result.status, fetched_at=result.fetched_at,
                             week_km_target=prefs.get("week_km_target"))
    if result.facts is None:
        return decision

    facts = result.facts
    today = now.date()
    decision.facts = facts
    decision.fresh_today = facts.get("date") == today.isoformat()
    activities = [Activity.from_fact(f) for f in facts.get("activities", []) if f.get("date")]
    past = [a for a in activities if a.day < today]
    decision.done_today = [a for a in activities if a.day == today]

    # The last 7 days for the detail panel, and running volume against the 4-week average.
    decision.week = [
        (today - timedelta(days=offset), [a for a in activities if a.day == today - timedelta(days=offset)])
        for offset in range(6, -1, -1)
    ]
    runs = [a for a in past if a.group == "running" and a.distance_km]
    # The 6 days before today: together with today's run, that is one week.
    decision.run_km_7d = sum(a.distance_km for a in runs if (today - a.day).days <= 6)
    decision.run_km_week_avg = sum(a.distance_km for a in runs if (today - a.day).days <= 28) / 4

    if not decision.fresh_today:
        # Data from another day says nothing about how you recovered last night.
        decision.reasons = [Reason("stale")]
        return decision

    typical = statistics.median(a.distance_km for a in runs) if runs else prefs["default_run_km"]
    decision.readiness, decision.reasons = _readiness(facts, past, today, typical)
    if decision.readiness == UNKNOWN:
        return decision
    if decision.readiness == RED:
        decision.session = REST
        return decision

    active_streak = _streak(today, past, lambda a: a.group != "walking")
    impact_streak = _streak(today, past, lambda a: a.group in IMPACT)
    strength_7d = sum(1 for a in past if a.group == "strength" and (today - a.day).days <= 7)

    if active_streak >= 6:
        decision.session = REST
        decision.reasons.append(Reason("no_rest_day", {"days": active_streak}))
        return decision
    if impact_streak >= 2:
        decision.session = STRENGTH if strength_7d < 2 else REST
        decision.reasons.append(Reason("impact_streak", {"days": impact_streak}))
        return decision

    # The week may grow about 10% over the 4-week average, but never stays below the plan's target.
    cap = max(
        decision.run_km_week_avg * (1 + prefs["max_week_increase"]),
        prefs["min_run_km"] * 3,
        float(prefs.get("week_km_target") or 0),
    )
    budget = cap - decision.run_km_7d
    long_day = prefs.get("long_run_day")
    longest = max((a.distance_km for a in runs), default=typical)

    if decision.readiness == GREEN and long_day and WEEKDAYS[today.weekday()] == str(long_day).lower():
        decision.session = LONG_RUN
        decision.km = half_km(max(typical, min(longest * 1.1, longest + 2)))
        decision.reasons.append(Reason("long_run_day", {"longest": longest}))
        return decision

    km = typical * (0.7 if decision.readiness == YELLOW else 1.0)
    km = min(km, budget)
    if km < prefs["min_run_km"]:
        decision.session = STRENGTH if strength_7d < 2 else REST
        decision.reasons.append(Reason("week_full", {"km": decision.run_km_7d, "avg": decision.run_km_week_avg}))
        return decision

    decision.session = SHORT_RUN if decision.readiness == YELLOW else EASY_RUN
    decision.km = half_km(km)
    return decision


def is_stale(decision: SportDecision) -> bool:
    return decision.status == STALE or (decision.available and not decision.fresh_today)


__all__ = ["DEFAULTS", "SportDecision", "decide_sport", "group_of", "FRESH"]
