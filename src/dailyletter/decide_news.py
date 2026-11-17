"""News facts into decisions: which few headlines are worth a glance. No language model.

The rules, in short: only recent news; a headline about a position only when its title names
that position; never the same story twice; and a sentence in the letter only for the top story
and for news about the position that moved the most.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .decide_portfolio import SPREAD_TYPES, Holding, PortfolioDecision
from .sources.base import MISSING, SourceResult
from .sources.news_rss import search_term

DEFAULTS = {
    "news_feeds": [],                 # [{"label": "De Tijd", "url": "https://…"}]
    "news_position_search": False,    # search Google News per position (personal use only)
    "news_edition": "BE:nl",          # Google News edition, country:language
    "news_max_positions": 8,          # how many positions get a news search
    "news_general_count": 3,          # headlines per feed in the panel
    "news_per_position": 2,           # headlines per position in the panel
}


@dataclass
class NewsItem:
    title: str
    link: str | None
    source: str
    published: datetime | None
    summary: str = ""


@dataclass
class PositionNews:
    name: str
    symbol: str | None
    move: float | None
    items: list[NewsItem]


@dataclass
class NewsDecision:
    status: str
    error: str | None = None
    general: list[tuple[str, list[NewsItem]]] = field(default_factory=list)   # (feed label, items)
    positions: list[PositionNews] = field(default_factory=list)               # movers first
    top: NewsItem | None = None
    mover: PositionNews | None = None
    failed: list[str] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.status != MISSING and bool(self.general or self.positions)


def searches_for(portfolio: PortfolioDecision, prefs: dict) -> list[dict]:
    """Which positions get a news search: the ones that moved first, then by weight. No funds."""
    if not prefs["news_position_search"]:
        return []
    ordered: list[Holding] = list(portfolio.movers) + [h for h in portfolio.holdings if h not in portfolio.movers]
    searches, seen = [], set()
    for h in ordered:
        if h.asset_type in SPREAD_TYPES or not h.name:
            continue
        term = search_term(h.name)
        if term.lower() in seen:
            continue
        seen.add(term.lower())
        searches.append({"name": h.name, "symbol": h.symbol, "term": term})
        if len(searches) >= prefs["news_max_positions"]:
            break
    return searches


def news_since(now: datetime) -> datetime:
    """Monday's letter still wants Friday evening's news; other days, the last 24 hours."""
    hours = {0: 72, 6: 48}.get(now.weekday(), 24)
    return now - timedelta(hours=hours)


def _key(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", title.lower())[:80]


def _item(raw: dict) -> NewsItem:
    published = datetime.fromisoformat(raw["published"]) if raw.get("published") else None
    return NewsItem(raw["title"], raw.get("link"), raw.get("source") or "", published, raw.get("summary") or "")


def _recent(item: NewsItem, since: datetime, now: datetime) -> bool:
    # A feed without dates keeps its own order; dated items must fall inside the window.
    return item.published is None or since <= item.published <= now + timedelta(minutes=10)


def _names(title: str, term: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(term.lower())}(?!\w)", title.lower()) is not None


def decide_news(result: SourceResult, now: datetime, prefs: dict, portfolio: PortfolioDecision | None = None) -> NewsDecision:
    decision = NewsDecision(status=result.status, error=result.error)
    facts = result.facts
    if facts is None:
        return decision
    decision.failed = list(facts.get("failed") or [])
    since = news_since(now)
    seen: set[str] = set()

    def fresh(items: list[NewsItem]) -> list[NewsItem]:
        kept = []
        for item in items:
            key = _key(item.title)
            if key in seen or not _recent(item, since, now):
                continue
            seen.add(key)
            kept.append(item)
        return kept

    moves = {}
    if portfolio is not None:
        moves = {h.name: h.day_pct for h in portfolio.holdings}
        mover_names = [h.name for h in portfolio.movers]
    else:
        mover_names = []

    # Positions first, so a story about your own stock is shown there and not again in general news.
    for pos in facts.get("positions") or []:
        items = [i for i in (_item(raw) for raw in pos.get("items") or []) if _names(i.title, pos["term"])]
        items.sort(key=lambda i: i.published or since, reverse=True)
        items = fresh(items)[: prefs["news_per_position"]]
        if items:
            decision.positions.append(PositionNews(pos["name"], pos.get("symbol"), moves.get(pos["name"]), items))
    decision.positions.sort(key=lambda p: (p.name not in mover_names, mover_names.index(p.name) if p.name in mover_names else 0))

    for feed in facts.get("feeds") or []:
        items = fresh([_item(raw) for raw in feed.get("items") or []])[: prefs["news_general_count"]]
        if items:
            decision.general.append((feed["label"], items))

    # The top story: the first one of the first feed, in the feed's own order (its editors chose it).
    if decision.general:
        decision.top = decision.general[0][1][0]
    decision.mover = next((p for p in decision.positions if p.name in mover_names), None)
    return decision
