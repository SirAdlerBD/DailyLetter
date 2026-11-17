"""Portfolio facts from your own Saxo MCP server (github.com/SirAdlerBD/saxo-mcp), LIVE account.

Read-only twice over: the Saxo MCP blocks trading itself, and this source may only call the
three tools in ALLOWED_TOOLS. Nothing here can place, change or cancel an order.

The stored secret is JSON: {"url": "http://127.0.0.1:3001/mcp", "token": "<MCP_ACCESS_TOKEN>"}.

Facts returned:
    {
      "date": "YYYY-MM-DD",
      "currency": "EUR",
      "total_value", "cash": float | None,
      "open_orders": int | None,
      "positions": [{"symbol", "name", "asset_type", "value", "day_pct", "pl_value", "pl_pct"}],
      "twr": [["YYYY-MM-DD", accumulated time-weighted return as a fraction], ...]
    }
Field names follow Saxo's OpenAPI: /port/v1/balances, /port/v1/netpositions (NetPositionView)
and /hist/v4/performance/timeseries (TimeWeighted.Accumulated).
"""

from __future__ import annotations

import json
from datetime import date, timedelta

from .base import Window
from .mcp_client import McpClient, McpToolError

DEFAULT_URL = "http://127.0.0.1:3001/mcp"
ALLOWED_TOOLS = frozenset({"get_balances", "get_positions", "get_account_history"})


class ToolNotAllowed(RuntimeError):
    pass


def _num(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _position(item: dict) -> dict:
    base = item.get("NetPositionBase") or item.get("PositionBase") or {}
    view = item.get("NetPositionView") or item.get("PositionView") or {}
    fmt = item.get("DisplayAndFormat") or {}
    value = _num(view.get("MarketValueInBaseCurrency"))
    if value is None:
        value = _num(view.get("ExposureInBaseCurrency"))
    opened = _num(view.get("MarketValueOpenInBaseCurrency"))
    pl = _num(view.get("ProfitLossOnTradeInBaseCurrency"))
    return {
        "symbol": fmt.get("Symbol"),
        "name": fmt.get("Description") or fmt.get("Symbol") or str(base.get("Uic", "?")),
        "asset_type": base.get("AssetType"),
        "value": abs(value) if value is not None else None,
        # Saxo gives this one in percent already: 1.2 means +1.2% since the previous close.
        "day_pct": _num(view.get("InstrumentPriceDayPercentChange")),
        "pl_value": pl,
        "pl_pct": pl / abs(opened) * 100 if pl is not None and opened else None,
    }


def _twr(history: dict | None) -> list[list]:
    points = ((history or {}).get("TimeWeighted") or {}).get("Accumulated") or []
    series = [[str(p.get("Date", ""))[:10], _num(p.get("Value"))] for p in points]
    return [p for p in series if p[0] and p[1] is not None]


def facts_from_tools(day: str, balances: dict, positions: dict, history: dict | None) -> dict:
    return {
        "date": day,
        "currency": balances.get("Currency"),
        "total_value": _num(balances.get("TotalValue")),
        "cash": _num(balances.get("CashBalance")),
        "open_orders": balances.get("OrdersCount") if isinstance(balances.get("OrdersCount"), int) else None,
        "positions": [_position(p) for p in positions.get("positions", [])],
        "twr": _twr(history),
    }


def history_start(today: date) -> date:
    """Far enough back for this year's return and for last week's, whichever is earlier."""
    return min(date(today.year, 1, 1) - timedelta(days=1), today - timedelta(days=8))


class SaxoMcpSource:
    name = "saxo"
    needs_connection = True

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout

    def fetch(self, secret: str | None, window: Window) -> dict:
        config = json.loads(secret or "{}")
        today = window.now.date()
        with McpClient(config.get("url", DEFAULT_URL), config.get("token", ""), timeout=self.timeout) as mcp:

            def call(tool: str, arguments: dict):
                if tool not in ALLOWED_TOOLS:
                    raise ToolNotAllowed(f"DailyLetter roept {tool} nooit aan")
                return mcp.call(tool, arguments)

            balances = call("get_balances", {"wholeClient": True})
            positions = call("get_positions", {"view": "net", "wholeClient": True})
            try:
                history = call("get_account_history", {
                    "report": "timeseries", "wholeClient": True,
                    "fromDate": history_start(today).isoformat(), "toDate": today.isoformat(),
                })
            except McpToolError:
                history = None  # returns are a bonus; positions and value still work without them
        return facts_from_tools(today.isoformat(), balances, positions, history)
