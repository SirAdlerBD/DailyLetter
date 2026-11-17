"""Notifications: at the times a user chose, a fresh letter and one calm message about it.

`dailyletter notify` runs every 15 minutes. For each user it checks whether one of their
times has come (and not been sent yet today), makes a fresh letter, and sends its first
lines to every phone that subscribed.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import crypto, db, decide, pipeline, webpush
from .config import Settings

CATCH_UP = timedelta(minutes=45)   # a server that was down for a moment still sends, but not hours late
BODY_LENGTH = 300
TIME = re.compile(r"^([01]?\d|2[0-3])[:u.h]([0-5]\d)$")


def parse_times(value) -> list[str]:
    """'7u30, 21:00' or ['07:30'] -> ['07:30', '21:00']. Anything unreadable raises ValueError."""
    parts = value if isinstance(value, list) else re.split(r"[,\s;]+", str(value or ""))
    times = []
    for part in parts:
        part = str(part).strip().lower()
        if not part:
            continue
        match = TIME.match(part)
        if not match:
            raise ValueError(f"{part!r} is geen tijdstip")
        times.append(f"{int(match[1]):02d}:{match[2]}")
    return sorted(set(times))


def due_slots(now: datetime, times: list[str], already: set[str]) -> list[str]:
    due = []
    for slot in times:
        hour, minute = map(int, slot.split(":"))
        moment = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if moment <= now < moment + CATCH_UP and slot not in already:
            due.append(slot)
    return due


def message(payload: dict) -> dict:
    """The greeting as title, the next lines as text. Amounts are never in the lines."""
    lines = [line["text"] for line in payload.get("lines", [])]
    title = lines[0].rstrip(".") if lines else "DailyLetter"
    body = " ".join(lines[1:4])
    if len(body) > BODY_LENGTH:
        body = body[: BODY_LENGTH - 1].rsplit(" ", 1)[0] + "…"
    return {"title": title, "body": body or "Je briefje staat klaar.", "url": "/", "tag": f"briefje-{payload.get('date', '')}"}


def subscriptions(conn: sqlite3.Connection, settings: Settings, user_id: int) -> list[webpush.Subscription]:
    subs = []
    for row in db.list_push(conn, user_id):
        try:
            data = crypto.decrypt(settings.secret_key, row["secret_enc"])
        except crypto.SecretKeyError:
            db.delete_push(conn, user_id, row["key"])   # unreadable with this key: the phone subscribes again
            continue
        subs.append(webpush.Subscription.from_browser(json.loads(data)))
    return subs


def send_to_user(conn: sqlite3.Connection, settings: Settings, user: sqlite3.Row, payload: dict,
                 transport: httpx.BaseTransport | None = None) -> tuple[int, list[str]]:
    """Send to every phone of this user. Returns (how many arrived, errors)."""
    sent, errors = 0, []
    for sub in subscriptions(conn, settings, user["id"]):
        try:
            webpush.send(sub, payload, settings.vapid_private, settings.vapid_contact, transport=transport)
        except webpush.SubscriptionGone:
            db.delete_push(conn, user["id"], sub.key)
            continue
        except Exception as exc:  # one phone failing must not stop the others
            error = f"{type(exc).__name__}: {exc}"
            db.push_result(conn, sub.key, error)
            errors.append(error)
            continue
        db.push_result(conn, sub.key, None)
        sent += 1
    return sent, errors


def notify_user(conn: sqlite3.Connection, settings: Settings, user: sqlite3.Row, now: datetime | None = None,
                force: bool = False, transport: httpx.BaseTransport | None = None) -> tuple[int, list[str]]:
    if not db.list_push(conn, user["id"]):
        return 0, []
    tz = ZoneInfo(user["timezone"])
    now = (now or datetime.now(tz)).astimezone(tz)
    today = now.date().isoformat()
    times = parse_times(db.get_setting(conn, user["id"], "notify_times", decide.DEFAULTS["notify_times"]))
    due = due_slots(now, times, db.sent_slots(conn, user["id"], today))
    if not due and not force:
        return 0, []

    try:
        letter = pipeline.run_for_user(conn, settings, user, now=now)   # fresh, so the watch synced at 7u counts
    except Exception:
        letter = db.latest_briefing(conn, user["id"], today)
    if letter is None:
        return 0, ["geen briefje"]
    sent, errors = send_to_user(conn, settings, user, message(letter), transport)
    if sent:
        for slot in due:
            db.mark_sent(conn, user["id"], today, slot)
    return sent, errors
