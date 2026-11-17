from datetime import date

import pytest

from dailyletter import crypto, db, decide_portfolio, pipeline
from dailyletter.decide_portfolio import decide_portfolio as decide, last_session_word
from dailyletter.sources.base import FRESH, STALE, SourceResult, Window
from dailyletter.sources.garmin_mcp import dump_secret
from dailyletter.sources.saxo_mcp import ALLOWED_TOOLS, SaxoMcpSource, ToolNotAllowed, facts_from_tools, history_start

from .conftest import TZ, at

PREFS = dict(decide_portfolio.DEFAULTS)

# Shaped like Saxo's OpenAPI answers, as the Saxo MCP passes them through.
BALANCES = {"Currency": "EUR", "TotalValue": 48320.4, "CashBalance": 3380.0, "OrdersCount": 1,
            "NonMarginPositionsValue": 44940.4, "OpenPositionsCount": 4}


def net(symbol, name, asset_type, value, day, opened, pl):
    return {
        "NetPositionId": f"{symbol}__x",
        "NetPositionBase": {"AssetType": asset_type, "Uic": hash(symbol) % 10000, "Amount": 10},
        "NetPositionView": {"MarketValueInBaseCurrency": value, "InstrumentPriceDayPercentChange": day,
                            "MarketValueOpenInBaseCurrency": opened, "ProfitLossOnTradeInBaseCurrency": pl,
                            "CurrentPrice": 1.0, "AverageOpenPrice": 1.0},
        "DisplayAndFormat": {"Symbol": symbol, "Description": name, "Currency": "EUR"},
    }


POSITIONS = {"count": 4, "positions": [
    net("IWDA:xams", "iShares Core MSCI World", "Etf", 20000.0, 0.2, 17000.0, 3000.0),
    net("NVDA:xnas", "NVIDIA Corp.", "Stock", 9000.0, -4.1, 5500.0, 3500.0),
    net("ASML:xams", "ASML Holding", "Stock", 7000.0, -1.8, 6400.0, 600.0),
    net("KBC:xbru", "KBC Groep", "Stock", 8940.4, -1.2, 7300.0, 1640.4),
]}

HISTORY = {
    "Balance": {"AccountValue": [{"Date": "2026-11-09T00:00:00Z", "Value": 47000.0}]},
    "TimeWeighted": {"Accumulated": [
        {"Date": "2025-12-31T00:00:00Z", "Value": 0.0},
        {"Date": "2026-11-09T00:00:00Z", "Value": 0.090},
        {"Date": "2026-11-13T00:00:00Z", "Value": 0.102},
        {"Date": "2026-11-16T00:00:00Z", "Value": 0.098},
    ]},
}


def facts(day="2026-11-16"):
    return facts_from_tools(day, BALANCES, POSITIONS, HISTORY)


def run(f=None, hour=7, status=FRESH, error=None):
    return decide(SourceResult("saxo", status, facts=f or facts(), error=error), at(hour, 40), PREFS)


def test_facts_from_saxo_answers():
    f = facts()
    assert (f["currency"], f["total_value"], f["cash"], f["open_orders"]) == ("EUR", 48320.4, 3380.0, 1)
    nvda = f["positions"][1]
    assert (nvda["name"], nvda["symbol"], nvda["asset_type"], nvda["day_pct"]) == ("NVIDIA Corp.", "NVDA:xnas", "Stock", -4.1)
    assert nvda["pl_pct"] == pytest.approx(3500 / 5500 * 100)
    assert f["twr"][0] == ["2025-12-31", 0.0]


def test_returns_movers_and_concentration():
    d = run()
    assert d.day_pct == pytest.approx((20000 * 0.2 + 9000 * -4.1 + 7000 * -1.8 + 8940.4 * -1.2) / 44940.4)
    assert d.week_pct == pytest.approx((1.098 / 1.090 - 1) * 100)
    assert d.ytd_pct == pytest.approx(9.8)
    assert [h.name for h in d.movers] == ["NVIDIA Corp."]
    # The world ETF is the biggest holding, but a fund is not a concentration risk;
    # of the stocks only the largest is named, and only above 20%.
    assert [h.name for h in d.concentrated] == ["NVIDIA Corp."]
    assert d.holdings[0].weight_pct == pytest.approx(20000 / 44940.4 * 100)


def test_last_trading_day_word():
    assert last_session_word(date(2026, 11, 16)) == "vrijdag"   # Monday
    assert last_session_word(date(2026, 11, 17)) == "gisteren"  # Tuesday
    assert last_session_word(date(2026, 11, 22)) == "vrijdag"   # Sunday


def test_missing_returns_are_left_out_not_guessed():
    bare = facts_from_tools("2026-11-16", BALANCES, {"positions": []}, None)
    d = run(bare)
    assert (d.day_pct, d.week_pct, d.ytd_pct, d.holdings) == (None, None, None, [])


def test_history_reaches_back_to_new_year_and_one_week():
    assert history_start(date(2026, 11, 16)) == date(2025, 12, 31)
    assert history_start(date(2027, 1, 3)) == date(2026, 12, 26)


# --- the tool whitelist -------------------------------------------------------

class FakeMcp:
    calls = []

    def __init__(self, url, token, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        pass

    def call(self, tool, arguments=None):
        FakeMcp.calls.append(tool)
        return {"get_balances": BALANCES, "get_positions": POSITIONS, "get_account_history": HISTORY}[tool]


def test_only_read_tools_are_called(monkeypatch):
    from dailyletter.sources import saxo_mcp
    FakeMcp.calls = []
    monkeypatch.setattr(saxo_mcp, "McpClient", FakeMcp)
    f = SaxoMcpSource().fetch(dump_secret("", "t" * 40), Window(at(7, 40), TZ))
    assert set(FakeMcp.calls) <= ALLOWED_TOOLS
    assert f["total_value"] == 48320.4
    assert not any("order" in tool or "trade" in tool for tool in ALLOWED_TOOLS)
    assert ToolNotAllowed


# --- sentences --------------------------------------------------------------

class FakeSaxo:
    name = "saxo"
    needs_connection = True

    def __init__(self, f=None, fail=None):
        self.f, self.fail = f, fail

    def fetch(self, secret, window):
        if self.fail:
            raise RuntimeError(self.fail)
        return self.f or facts(window.now.date().isoformat())


def letter(conn, settings, user, source, hour=7, minute=40, day=16):
    db.set_connection(conn, user["id"], "saxo", crypto.encrypt(settings.secret_key, dump_secret("", "t" * 40)))
    payload = pipeline.run_for_user(conn, settings, user, now=at(hour, minute, day=day), sources=[source])
    return {line["id"]: line for line in payload["lines"]}, payload


def test_morning_and_evening_lines(conn, settings, user):
    lines, payload = letter(conn, settings, user, FakeSaxo())
    assert lines["portfolio"]["text"] == (
        "Je portefeuille: vrijdag −1,3%, deze week +0,7%. NVIDIA Corp. bewoog het meest: −4,1%."
    )
    assert lines["portfolio"]["detail"] == "portfolio"
    panel = payload["details"]["portfolio"]
    assert panel["total"] == "€ 48.320" and panel["cash"] == "€ 3.380" and panel["orders"] == 1
    assert [r["k"] for r in panel["returns"]] == ["Vrijdag", "Deze week", "Dit jaar"]
    assert panel["insights"] == ["NVIDIA Corp. is 20% van je portefeuille."]
    assert panel["positions"][0]["weight"] == "45%"

    lines, _ = letter(conn, settings, user, FakeSaxo(), hour=12, minute=0)
    assert "portfolio" not in lines
    lines, _ = letter(conn, settings, user, FakeSaxo(), hour=21, minute=0)
    assert lines["portfolio"]["text"].startswith("Je portefeuille vandaag: −1,3%.")


def test_an_expired_saxo_login_says_so(conn, settings, user):
    letter(conn, settings, user, FakeSaxo())  # a good answer first, so the next one falls back to it
    lines, payload = letter(conn, settings, user, FakeSaxo(fail="AUTHENTICATION REQUIRED: run npm run login"), day=17)
    assert payload["sources"]["saxo"] == "stale"
    assert lines["portfolio"]["text"].startswith("Je Saxo-login is verlopen.")


def test_old_data_is_named_as_old(conn, settings, user):
    letter(conn, settings, user, FakeSaxo())
    lines, _ = letter(conn, settings, user, FakeSaxo(fail="ConnectError"), day=17)
    assert lines["portfolio"]["text"] == "Je Saxo-gegevens konden niet ververst worden."


def test_without_saxo_nothing_about_money_appears(conn, settings, user):
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeSaxo()])
    assert "portfolio" not in [line["id"] for line in payload["lines"]]
    assert "portfolio" not in payload["details"]
