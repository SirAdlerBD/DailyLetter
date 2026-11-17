"""SQLite access: one file, migrations applied in order."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from importlib import resources
from pathlib import Path
from typing import Any


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(db_path: Path | str) -> sqlite3.Connection:
    if str(db_path) != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def migrate(conn: sqlite3.Connection) -> list[str]:
    """Apply every migration that has not run yet. Returns the names applied."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations (name TEXT PRIMARY KEY, applied_at TEXT NOT NULL)"
    )
    done = {row["name"] for row in conn.execute("SELECT name FROM schema_migrations")}
    folder = resources.files("dailyletter") / "migrations"
    applied = []
    for file in sorted(folder.iterdir(), key=lambda f: f.name):
        if not file.name.endswith(".sql") or file.name in done:
            continue
        conn.executescript(file.read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO schema_migrations (name, applied_at) VALUES (?, ?)", (file.name, utcnow())
        )
        conn.commit()
        applied.append(file.name)
    return applied


# --- users -----------------------------------------------------------------

def add_user(conn: sqlite3.Connection, name: str, display_name: str, tz: str) -> int:
    cur = conn.execute(
        "INSERT INTO users (name, display_name, timezone, created_at) VALUES (?, ?, ?, ?)",
        (name, display_name, tz, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def get_user(conn: sqlite3.Connection, name: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()


def list_users(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM users ORDER BY id").fetchall()


# --- settings --------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, user_id: int, key: str, default: Any = None) -> Any:
    row = conn.execute(
        "SELECT value FROM settings WHERE user_id = ? AND key = ?", (user_id, key)
    ).fetchone()
    return json.loads(row["value"]) if row else default


def set_setting(conn: sqlite3.Connection, user_id: int, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO settings (user_id, key, value) VALUES (?, ?, ?) "
        "ON CONFLICT (user_id, key) DO UPDATE SET value = excluded.value",
        (user_id, key, json.dumps(value)),
    )
    conn.commit()


# --- connections -----------------------------------------------------------

def set_connection(conn: sqlite3.Connection, user_id: int, source: str, secret_enc: str) -> None:
    conn.execute(
        "INSERT INTO connections (user_id, source, secret_enc, updated_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (user_id, source) DO UPDATE SET secret_enc = excluded.secret_enc, "
        "updated_at = excluded.updated_at",
        (user_id, source, secret_enc, utcnow()),
    )
    conn.commit()


def get_connection(conn: sqlite3.Connection, user_id: int, source: str) -> str | None:
    row = conn.execute(
        "SELECT secret_enc FROM connections WHERE user_id = ? AND source = ?", (user_id, source)
    ).fetchone()
    return row["secret_enc"] if row else None


def delete_connection(conn: sqlite3.Connection, user_id: int, source: str) -> None:
    conn.execute("DELETE FROM connections WHERE user_id = ? AND source = ?", (user_id, source))
    conn.commit()


# --- snapshots -------------------------------------------------------------

def add_snapshot(
    conn: sqlite3.Connection,
    user_id: int,
    source: str,
    ok: bool,
    payload: dict | None,
    error: str | None,
) -> None:
    conn.execute(
        "INSERT INTO snapshots (user_id, source, fetched_at, ok, payload, error) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, source, utcnow(), int(ok), json.dumps(payload) if payload is not None else None, error),
    )
    conn.commit()


def last_good_snapshot(conn: sqlite3.Connection, user_id: int, source: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM snapshots WHERE user_id = ? AND source = ? AND ok = 1 "
        "ORDER BY fetched_at DESC, id DESC LIMIT 1",
        (user_id, source),
    ).fetchone()


# --- briefings -------------------------------------------------------------

def save_briefing(
    conn: sqlite3.Connection, user_id: int, date: str, version: str, payload: dict, writer: str, fallback: bool
) -> None:
    conn.execute(
        "INSERT INTO briefings (user_id, date, version, payload, writer, fallback, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT (user_id, date, version) DO UPDATE SET payload = excluded.payload, "
        "writer = excluded.writer, fallback = excluded.fallback, created_at = excluded.created_at",
        (user_id, date, version, json.dumps(payload, ensure_ascii=False), writer, int(fallback), utcnow()),
    )
    conn.commit()


def latest_briefing(conn: sqlite3.Connection, user_id: int, date: str) -> dict | None:
    row = conn.execute(
        "SELECT payload FROM briefings WHERE user_id = ? AND date = ? ORDER BY created_at DESC, id DESC LIMIT 1",
        (user_id, date),
    ).fetchone()
    return json.loads(row["payload"]) if row else None


# --- inbox -----------------------------------------------------------------

def add_inbox(conn: sqlite3.Connection, user_id: int, text: str) -> int:
    cur = conn.execute(
        "INSERT INTO inbox (user_id, created_at, text) VALUES (?, ?, ?)", (user_id, utcnow(), text)
    )
    conn.commit()
    return int(cur.lastrowid)


# --- push notifications ----------------------------------------------------

def save_push(conn: sqlite3.Connection, user_id: int, key: str, secret_enc: str) -> None:
    conn.execute(
        "INSERT INTO push_subscriptions (user_id, key, secret_enc, created_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET user_id = excluded.user_id, secret_enc = excluded.secret_enc",
        (user_id, key, secret_enc, utcnow()),
    )
    conn.commit()


def list_push(conn: sqlite3.Connection, user_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM push_subscriptions WHERE user_id = ? ORDER BY id", (user_id,)
    ).fetchall()


def delete_push(conn: sqlite3.Connection, user_id: int, key: str) -> None:
    conn.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND key = ?", (user_id, key))
    conn.commit()


def push_result(conn: sqlite3.Connection, key: str, error: str | None) -> None:
    if error is None:
        conn.execute("UPDATE push_subscriptions SET last_ok_at = ?, last_error = NULL WHERE key = ?", (utcnow(), key))
    else:
        conn.execute("UPDATE push_subscriptions SET last_error = ? WHERE key = ?", (error[:200], key))
    conn.commit()


def sent_slots(conn: sqlite3.Connection, user_id: int, date: str) -> set[str]:
    rows = conn.execute("SELECT slot FROM notifications_sent WHERE user_id = ? AND date = ?", (user_id, date))
    return {row["slot"] for row in rows}


def mark_sent(conn: sqlite3.Connection, user_id: int, date: str, slot: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO notifications_sent (user_id, date, slot, sent_at) VALUES (?, ?, ?, ?)",
        (user_id, date, slot, utcnow()),
    )
    conn.commit()
