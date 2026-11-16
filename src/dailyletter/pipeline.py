"""The batch job: collect, decide, write, check, store."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from . import compose, db, decide
from .config import Settings
from .sources import DEFAULT_SOURCES, Source, Window, collect


def user_prefs(conn: sqlite3.Connection, user_id: int) -> dict:
    """Defaults, overridden by whatever this user has set."""
    return {key: db.get_setting(conn, user_id, key, default) for key, default in decide.DEFAULTS.items()}


def run_for_user(
    conn: sqlite3.Connection,
    settings: Settings,
    user: sqlite3.Row,
    now: datetime | None = None,
    version: str | None = None,
    sources: list[Source] | None = None,
) -> dict:
    tz = ZoneInfo(user["timezone"])
    now = (now or datetime.now(tz)).astimezone(tz)
    prefs = user_prefs(conn, user["id"])
    version = version or decide.version_for(now, prefs["version_until"])
    if version not in decide.VERSIONS:
        raise ValueError(f"unknown version {version!r}")

    results = collect(conn, settings.secret_key, user["id"], sources or DEFAULT_SOURCES, Window(now, tz))
    agenda = decide.decide_agenda(results["agenda"], now, prefs)

    payload = compose.write_from_templates(version, now, user["display_name"], agenda, prefs)
    compose.validate(payload)
    db.save_briefing(conn, user["id"], payload["date"], version, payload, writer="template", fallback=False)
    return payload
