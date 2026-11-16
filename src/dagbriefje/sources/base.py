"""Step 1 of the pipeline: fetch every source on its own, never let one failure stop the rest."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from zoneinfo import ZoneInfo

from .. import crypto, db

FRESH = "fresh"
STALE = "stale"
MISSING = "missing"


@dataclass(frozen=True)
class Window:
    """The moment a briefing is made for, in the user's own time zone."""

    now: datetime
    tz: ZoneInfo


class Source(Protocol):
    name: str
    needs_connection: bool

    def fetch(self, secret: str | None, window: Window) -> dict:
        """Return normalized facts. Raise on any failure."""
        ...


@dataclass
class SourceResult:
    source: str
    status: str
    facts: dict | None = None
    fetched_at: str | None = None
    error: str | None = None


def collect(
    conn: sqlite3.Connection, secret_key: str, user_id: int, sources: list[Source], window: Window
) -> dict[str, SourceResult]:
    results: dict[str, SourceResult] = {}
    for source in sources:
        results[source.name] = _collect_one(conn, secret_key, user_id, source, window)
    return results


def _collect_one(
    conn: sqlite3.Connection, secret_key: str, user_id: int, source: Source, window: Window
) -> SourceResult:
    secret = None
    if source.needs_connection:
        token = db.get_connection(conn, user_id, source.name)
        if token is None:
            return SourceResult(source.name, MISSING, error="not connected")
        try:
            secret = crypto.decrypt(secret_key, token)
        except crypto.SecretKeyError as exc:
            return _fallback(conn, user_id, source.name, str(exc))

    try:
        facts = source.fetch(secret, window)
    except Exception as exc:  # a source may fail in any way; the briefing must still be made
        error = f"{type(exc).__name__}: {exc}"
        db.add_snapshot(conn, user_id, source.name, ok=False, payload=None, error=error)
        return _fallback(conn, user_id, source.name, error)

    db.add_snapshot(conn, user_id, source.name, ok=True, payload=facts, error=None)
    return SourceResult(source.name, FRESH, facts=facts, fetched_at=db.utcnow())


def _fallback(conn: sqlite3.Connection, user_id: int, name: str, error: str) -> SourceResult:
    """Use the last good answer and say it is stale; without one the source is missing."""
    last = db.last_good_snapshot(conn, user_id, name)
    if last is None:
        return SourceResult(name, MISSING, error=error)
    return SourceResult(
        name, STALE, facts=json.loads(last["payload"]), fetched_at=last["fetched_at"], error=error
    )
