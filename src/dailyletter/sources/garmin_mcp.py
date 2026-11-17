"""Fitness facts from your own Garmin MCP server (github.com/SirAdlerBD/Garmin-MCP).

The stored secret is JSON: {"url": "http://127.0.0.1:3001/mcp", "token": "<MCP_ACCESS_TOKEN>"}.

Facts returned (provider-neutral, so another watch can fill the same shape later):
    {
      "date": "YYYY-MM-DD",
      "sleep": {"hours", "score"} | None,
      "hrv": {"last_night", "status", "baseline_low", "baseline_high"} | None,
      "resting_hr": {"today", "avg_7d"} | None,
      "body_battery_high": int | None,
      "load": {"acute_7d", "chronic_weekly", "ratio"} | None,
      "zone2": [low_bpm, high_bpm] | None,
      "activities": [{"date", "time", "type", "name", "distance_km", "duration_min", "hard_min", "load"}]  oldest first
    }
"""

from __future__ import annotations

import json
from datetime import timedelta

from .base import Window
from .mcp_client import McpClient, McpError, McpToolError, check_url

DEFAULT_URL = "http://127.0.0.1:3001/mcp"
HISTORY_DAYS = 28


def dump_secret(url: str, token: str) -> str:
    token = token.strip()
    if not token:
        raise ValueError("Het toegangstoken is leeg.")
    return json.dumps({"url": check_url(url or DEFAULT_URL), "token": token})


def _sleep(snapshot: dict) -> dict | None:
    sleep = snapshot.get("sleep") or {}
    if sleep.get("hours") is None:
        return None
    return {"hours": sleep["hours"], "score": sleep.get("score")}


def _hrv(snapshot: dict) -> dict | None:
    hrv = snapshot.get("hrv") or {}
    if hrv.get("lastNightAvg") is None and hrv.get("status") is None:
        return None
    baseline = hrv.get("baseline") or {}
    return {
        "last_night": hrv.get("lastNightAvg"),
        "status": hrv.get("status"),
        "baseline_low": baseline.get("balancedLow"),
        "baseline_high": baseline.get("balancedUpper"),
    }


def _resting_hr(snapshot: dict) -> dict | None:
    rhr = snapshot.get("restingHR") or {}
    if rhr.get("today") is None:
        return None
    return {"today": rhr["today"], "avg_7d": rhr.get("avg7d")}


def _load(snapshot: dict) -> dict | None:
    load = snapshot.get("load") or {}
    if not load:
        return None
    return {
        "acute_7d": load.get("acute7d"),
        "chronic_weekly": load.get("chronicWeeklyAvg28d"),
        "ratio": load.get("acuteChronicRatio"),
    }


def _zone2(profile: dict | None) -> list[int] | None:
    """Zone 2 heart rate from the running zones, or the default ones."""
    zones = (profile or {}).get("heartRateZones") or []
    by_sport = {str(z.get("sport", "")).upper(): z for z in zones}
    chosen = by_sport.get("RUNNING") or by_sport.get("DEFAULT") or (zones[0] if zones else None)
    floors = (chosen or {}).get("zoneFloors") or []
    if len(floors) < 3 or floors[1] is None or floors[2] is None:
        return None
    return [int(floors[1]), int(floors[2]) - 1]


def _activity(a: dict) -> dict:
    start = str(a.get("start") or "")
    zones = a.get("hrZonesMin") or []
    return {
        "date": start[:10],
        "time": start[11:16] or None,
        "type": a.get("type") or "unknown",
        "name": a.get("name"),
        "distance_km": a.get("distanceKm"),
        "duration_min": a.get("durationMin"),
        "hard_min": sum(z or 0 for z in zones[3:5]) if len(zones) >= 5 else None,
        "load": a.get("trainingLoad"),
    }


def facts_from_tools(day: str, snapshot: dict, activities: dict, profile: dict | None) -> dict:
    acts = [_activity(a) for a in activities.get("activities", [])]
    acts.sort(key=lambda a: (a["date"], a["time"] or ""))
    return {
        "date": day,
        "sleep": _sleep(snapshot),
        "hrv": _hrv(snapshot),
        "resting_hr": _resting_hr(snapshot),
        "body_battery_high": snapshot.get("bodyBatteryHigh"),
        "load": _load(snapshot),
        "zone2": _zone2(profile),
        "activities": acts,
    }


class GarminMcpSource:
    name = "garmin"
    needs_connection = True

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def fetch(self, secret: str | None, window: Window) -> dict:
        config = json.loads(secret or "{}")
        today = window.now.date()
        start = (today - timedelta(days=HISTORY_DAYS - 1)).isoformat()
        with McpClient(config.get("url", DEFAULT_URL), config.get("token", ""), timeout=self.timeout) as mcp:
            snapshot = mcp.call("get_recovery_snapshot", {"date": today.isoformat()})
            activities = mcp.call("list_activities", {"start": start, "end": today.isoformat(), "limit": 300})
            try:
                profile = mcp.call("get_profile", {})
            except (McpError, McpToolError):
                profile = None  # only needed for heart-rate zones; the advice works without
        return facts_from_tools(today.isoformat(), snapshot, activities, profile)
