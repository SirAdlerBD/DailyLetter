"""The batch job: collect, decide, write, check, store."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from . import compose, db, decide, decide_news, decide_portfolio, decide_sport
from .config import Settings
from .sources import DEFAULT_SOURCES, Source, SourceResult, Window, collect
from .sources.base import MISSING
from .sources.news_rss import NewsSource, load_feeds

ALL_DEFAULTS = {**decide.DEFAULTS, **decide_sport.DEFAULTS, **decide_portfolio.DEFAULTS, **decide_news.DEFAULTS}


def user_prefs(conn: sqlite3.Connection, user_id: int) -> dict:
    """Defaults, overridden by whatever this user has set."""
    return {key: db.get_setting(conn, user_id, key, default) for key, default in ALL_DEFAULTS.items()}


def run_for_user(
    conn: sqlite3.Connection,
    settings: Settings,
    user: sqlite3.Row,
    now: datetime | None = None,
    version: str | None = None,
    sources: list[Source] | None = None,
    news_source=None,
) -> dict:
    tz = ZoneInfo(user["timezone"])
    now = (now or datetime.now(tz)).astimezone(tz)
    prefs = user_prefs(conn, user["id"])
    version = version or decide.version_for(now, prefs["version_until"])
    if version not in decide.VERSIONS:
        raise ValueError(f"unknown version {version!r}")

    results = collect(conn, settings.secret_key, user["id"], sources or DEFAULT_SOURCES, Window(now, tz))
    missing = lambda name: results.get(name) or SourceResult(name, MISSING)  # noqa: E731
    agenda = decide.decide_agenda(missing("agenda"), now, prefs)
    sport = decide_sport.decide_sport(missing("garmin"), now, prefs)
    portfolio = decide_portfolio.decide_portfolio(missing("saxo"), now, prefs)

    # News comes second: what to search for depends on what is in the portfolio.
    news_source = news_source or news_source_for(prefs, portfolio)
    if news_source is not None:
        results.update(collect(conn, settings.secret_key, user["id"], [news_source], Window(now, tz)))
    news = decide_news.decide_news(missing("news"), now, prefs, portfolio)

    payload = compose.write_from_templates(version, now, user["display_name"], agenda, prefs, sport, portfolio, news)
    compose.validate(payload)
    db.save_briefing(conn, user["id"], payload["date"], version, payload, writer="template", fallback=False)
    return payload


def news_source_for(prefs: dict, portfolio: decide_portfolio.PortfolioDecision) -> NewsSource | None:
    """The user's feeds plus a search per position; nothing to fetch means no news source."""
    feeds = load_feeds(prefs["news_feeds"])
    searches = decide_news.searches_for(portfolio, prefs)
    if not feeds and not searches:
        return None
    return NewsSource(feeds, searches, edition=prefs["news_edition"])
