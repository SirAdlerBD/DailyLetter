"""Portfolio facts into decisions: how it moved, what stands out. No language model, no advice to trade."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .sources.base import MISSING, SourceResult

DEFAULTS = {
    "portfolio_mover_pct": 3.0,          # a position moving at least this much gets named
    "portfolio_concentration_pct": 20.0,  # the largest single stock gets mentioned above this weight
}

# Funds already spread their risk; their weight is not a concentration worth flagging.
SPREAD_TYPES = {"Etf", "Etc", "Etn", "MutualFund", "Fund"}


@dataclass
class Holding:
    name: str
    symbol: str | None
    asset_type: str | None
    value: float | None
    weight_pct: float | None
    day_pct: float | None
    pl_pct: float | None
    pl_value: float | None


@dataclass
class PortfolioDecision:
    status: str
    error: str | None = None
    fresh_today: bool = False
    currency: str | None = None
    total_value: float | None = None
    cash: float | None = None
    open_orders: int | None = None
    holdings: list[Holding] = field(default_factory=list)   # largest first
    day_pct: float | None = None
    week_pct: float | None = None
    ytd_pct: float | None = None
    movers: list[Holding] = field(default_factory=list)      # biggest absolute move first
    concentrated: list[Holding] = field(default_factory=list)

    @property
    def available(self) -> bool:
        return self.status != MISSING

    @property
    def login_expired(self) -> bool:
        return bool(self.error and "AUTHENTICATION REQUIRED" in self.error)


def _return_since(twr: list[list], since: date) -> float | None:
    """Time-weighted return in percent from the last point on or before `since` to the latest point."""
    if len(twr) < 2:
        return None
    before = [v for d, v in twr if date.fromisoformat(d) <= since]
    start = before[-1] if before else None
    if start is None:
        return None
    last = twr[-1][1]
    return ((1 + last) / (1 + start) - 1) * 100


def decide_portfolio(result: SourceResult, now: datetime, prefs: dict) -> PortfolioDecision:
    decision = PortfolioDecision(status=result.status, error=result.error)
    facts = result.facts
    if facts is None:
        return decision

    today = now.date()
    decision.fresh_today = facts.get("date") == today.isoformat()
    decision.currency = facts.get("currency")
    decision.total_value = facts.get("total_value")
    decision.cash = facts.get("cash")
    decision.open_orders = facts.get("open_orders")

    positions = [p for p in facts.get("positions", []) if p.get("value")]
    invested = sum(p["value"] for p in positions)
    holdings = [
        Holding(
            name=p["name"], symbol=p.get("symbol"), asset_type=p.get("asset_type"), value=p["value"],
            weight_pct=p["value"] / invested * 100 if invested else None,
            day_pct=p.get("day_pct"), pl_pct=p.get("pl_pct"), pl_value=p.get("pl_value"),
        )
        for p in positions
    ]
    decision.holdings = sorted(holdings, key=lambda h: h.value or 0, reverse=True)

    priced = [h for h in holdings if h.day_pct is not None]
    priced_value = sum(h.value for h in priced)
    if priced_value:
        decision.day_pct = sum(h.value * h.day_pct for h in priced) / priced_value

    twr = facts.get("twr") or []
    decision.week_pct = _return_since(twr, today - timedelta(days=7))
    decision.ytd_pct = _return_since(twr, date(today.year, 1, 1) - timedelta(days=1))

    threshold = prefs["portfolio_mover_pct"]
    decision.movers = sorted((h for h in priced if abs(h.day_pct) >= threshold), key=lambda h: -abs(h.day_pct))
    # Only the largest single stock, and only when it is really large: one calm remark, not a list.
    stocks = [h for h in decision.holdings if h.asset_type not in SPREAD_TYPES and h.weight_pct]
    if stocks and stocks[0].weight_pct >= prefs["portfolio_concentration_pct"]:
        decision.concentrated = [stocks[0]]
    return decision


def last_session_word(today: date) -> str:
    """Before the markets open, the latest move is from the last trading day."""
    return {0: "vrijdag", 6: "vrijdag"}.get(today.weekday(), "gisteren")
