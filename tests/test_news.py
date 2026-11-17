from argparse import Namespace
from datetime import timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from dailyletter import cli, db, decide_news, pipeline
from dailyletter.decide_news import decide_news as decide, news_since, searches_for
from dailyletter.decide_portfolio import Holding, PortfolioDecision
from dailyletter.sources import news_rss
from dailyletter.sources.base import FRESH, SourceResult, Window
from dailyletter.sources.news_rss import (
    InvalidFeedUrl, NewsSource, NewsUnreachable, TooManyFeeds, add_feed, google_news_url, parse_feed,
    remove_feed, search_term,
)
from dailyletter.web.app import create_app

from .conftest import TZ, at
from .test_portfolio import FakeSaxo

PREFS = {**pipeline.ALL_DEFAULTS}


def rss(*items, title="De Tijd"):
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link><pubDate>{when}</pubDate>"
        f"{f'<source url=\"https://x\">{src}</source>' if src else ''}"
        f"<description>&lt;p&gt;Intro bij {t}&lt;/p&gt;</description></item>"
        for t, link, when, src in items
    )
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>{title}</title>{body}</channel></rss>'.encode()


def when(hours_ago: float, base=None) -> str:
    moment = (base or at(7, 40)) - timedelta(hours=hours_ago)
    return moment.astimezone(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


# --- parsing --------------------------------------------------------------------------

def test_rss_items_become_plain_headlines():
    items = parse_feed(rss(
        ("NVIDIA zakt na kwartaalcijfers - Reuters", "https://news.example/a", when(2), "Reuters"),
        ("Gevaarlijke link", "javascript:alert(1)", when(3), None),
    ), "De Tijd")
    first, second = items
    assert first["title"] == "NVIDIA zakt na kwartaalcijfers"   # ' - Reuters' is the source, not the title
    assert first["source"] == "Reuters"
    assert first["summary"] == "Intro bij NVIDIA zakt na kwartaalcijfers - Reuters"
    assert first["published"] == "2026-11-16T04:40+00:00"
    assert second["link"] is None and second["source"] == "De Tijd"


def test_atom_feeds_work_too():
    atom = b"""<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">
      <entry><title>Bel20 hoger</title><link href="https://tijd.example/bel20"/>
      <updated>2026-11-16T06:00:00Z</updated><summary>Kort</summary></entry></feed>"""
    [item] = parse_feed(atom, "Markten")
    assert (item["title"], item["link"], item["published"], item["source"]) == (
        "Bel20 hoger", "https://tijd.example/bel20", "2026-11-16T06:00+00:00", "Markten")


def test_xml_bombs_are_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE r [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><rss><channel></channel></rss>'
    with pytest.raises(Exception):
        parse_feed(bomb, "x")


@pytest.mark.parametrize("name, term", [
    ("NVIDIA Corp.", "NVIDIA"),
    ("ASML Holding N.V.", "ASML"),
    ("KBC Groep", "KBC"),
    ("Alphabet Inc. Class A", "Alphabet"),
    ("Coca-Cola Co", "Coca-Cola"),
    ("Siemens Energy AG", "Siemens Energy"),
    ("AB InBev SA/NV", "AB InBev"),
])
def test_search_terms_drop_legal_forms(name, term):
    assert search_term(name) == term


def test_google_news_url_uses_the_edition():
    url = google_news_url("KBC", "BE:nl")
    assert url.startswith("https://news.google.com/rss/search?q=%22KBC%22+when%3A3d&")
    assert "hl=nl" in url and "gl=BE" in url and "ceid=BE%3Anl" in url


def test_feed_list_rules():
    feeds = add_feed([], "De Tijd", "https://feeds.example/tijd.xml")
    feeds = add_feed(feeds, "de tijd", "https://feeds.example/nieuw.xml")   # same name: new address
    assert feeds == [{"label": "de tijd", "url": "https://feeds.example/nieuw.xml"}]
    assert remove_feed(feeds, "De Tijd") == []
    with pytest.raises(InvalidFeedUrl):
        add_feed([], "x", "file:///etc/passwd")
    full = [{"label": str(i), "url": "https://f.example"} for i in range(news_rss.MAX_FEEDS)]
    with pytest.raises(TooManyFeeds):
        add_feed(full, "nog één", "https://f.example/x")


# --- fetching -------------------------------------------------------------------------

def transport(routes):
    def handler(request):
        for part, answer in routes.items():
            if part in str(request.url):
                return answer() if callable(answer) else httpx.Response(200, content=answer)
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def test_one_broken_feed_does_not_hide_the_rest():
    source = NewsSource(
        feeds=[{"label": "De Tijd", "url": "https://tijd.example/rss"}, {"label": "Kapot", "url": "https://kapot.example"}],
        searches=[{"name": "NVIDIA Corp.", "symbol": "NVDA:xnas", "term": "NVIDIA"}],
        transport=transport({
            "tijd.example": rss(("Bel20 hoger", "https://tijd.example/1", when(1), None)),
            "kapot.example": lambda: httpx.Response(403),
            "news.google.com": rss(("NVIDIA zakt - Reuters", "https://n.example/1", when(2), "Reuters")),
        }),
    )
    facts = source.fetch(None, Window(at(7, 40), TZ))
    assert [f["label"] for f in facts["feeds"]] == ["De Tijd"]
    assert facts["positions"][0]["items"][0]["title"] == "NVIDIA zakt"
    assert facts["failed"] == ["Kapot"]    # the label, never the address


def test_nothing_reachable_raises_so_the_last_good_news_is_used():
    source = NewsSource([{"label": "Kapot", "url": "https://kapot.example"}], [],
                        transport=transport({"kapot.example": lambda: httpx.Response(500)}))
    with pytest.raises(NewsUnreachable):
        source.fetch(None, Window(at(7, 40), TZ))


def test_a_huge_feed_is_refused(monkeypatch):
    monkeypatch.setattr(news_rss, "MAX_BYTES", 100)
    source = NewsSource([{"label": "Groot", "url": "https://groot.example"}], [],
                        transport=transport({"groot.example": b"x" * 500}))
    with pytest.raises(NewsUnreachable):
        source.fetch(None, Window(at(7, 40), TZ))


# --- deciding -------------------------------------------------------------------------

def holding(name, day, asset="Stock", symbol=None):
    return Holding(name, symbol, asset, 1000.0, 10.0, day, None, None)


NVDA = holding("NVIDIA Corp.", -4.1, symbol="NVDA:xnas")
KBC = holding("KBC Groep", -1.2)
WORLD = holding("iShares Core MSCI World", 0.2, asset="Etf")
PF = PortfolioDecision(status=FRESH, holdings=[WORLD, KBC, NVDA], movers=[NVDA])


def test_searches_mover_first_and_never_funds():
    assert searches_for(PF, PREFS) == []                      # off by default: Google's terms are personal use only
    on = {**PREFS, "news_position_search": True}
    assert [s["term"] for s in searches_for(PF, on)] == ["NVIDIA", "KBC"]
    assert len(searches_for(PF, {**on, "news_max_positions": 1})) == 1


def test_news_window_reaches_back_to_friday_on_monday():
    assert news_since(at(7, 40, day=16)) == at(7, 40, day=13)     # Monday
    assert news_since(at(7, 40, day=17)) == at(7, 40, day=16)     # Tuesday


def facts(day=17):
    base = at(7, 40, day=day)
    return {
        "date": base.date().isoformat(),
        "feeds": [{"label": "De Tijd", "items": [
            {"title": "Bel20 sluit hoger", "link": "https://t/1", "source": "De Tijd", "published": None, "summary": "Intro"},
            {"title": "Oud nieuws", "link": "https://t/2", "source": "De Tijd",
             "published": (base - timedelta(days=3)).isoformat(), "summary": ""},
            {"title": "NVIDIA zakt na cijfers", "link": "https://t/3", "source": "De Tijd",
             "published": (base - timedelta(hours=3)).isoformat(), "summary": ""},
        ]}],
        "positions": [
            {"name": "NVIDIA Corp.", "symbol": "NVDA:xnas", "term": "NVIDIA", "items": [
                {"title": "NVIDIA zakt na cijfers", "link": "https://n/1", "source": "Reuters",
                 "published": (base - timedelta(hours=2)).isoformat()},
                {"title": "Chipsector onder druk", "link": "https://n/2", "source": "Bloomberg",   # does not name NVIDIA
                 "published": (base - timedelta(hours=1)).isoformat()},
            ]},
            {"name": "KBC Groep", "symbol": None, "term": "KBC", "items": []},
        ],
        "failed": [],
    }


def test_decide_keeps_recent_relevant_and_unique_news():
    d = decide(SourceResult("news", FRESH, facts=facts()), at(7, 40, day=17), PREFS, PF)
    assert [p.name for p in d.positions] == ["NVIDIA Corp."]
    assert [i.title for i in d.positions[0].items] == ["NVIDIA zakt na cijfers"]
    # The same story already sits under NVIDIA, the three-day-old one is gone.
    assert [i.title for i in d.general[0][1]] == ["Bel20 sluit hoger"]
    assert d.top.title == "Bel20 sluit hoger"
    assert d.mover.name == "NVIDIA Corp." and d.mover.move == -4.1


# --- in the letter --------------------------------------------------------------------

class FakeNews:
    name = "news"
    needs_connection = False

    def fetch(self, secret, window):
        return facts(window.now.day)


def letter(conn, settings, user, hour=7, minute=40, day=17):
    from dailyletter import crypto
    from dailyletter.sources.garmin_mcp import dump_secret
    db.set_connection(conn, user["id"], "saxo", crypto.encrypt(settings.secret_key, dump_secret("", "t" * 40)))
    payload = pipeline.run_for_user(conn, settings, user, now=at(hour, minute, day=day),
                                    sources=[FakeSaxo()], news_source=FakeNews())
    return [line["id"] for line in payload["lines"]], {line["id"]: line for line in payload["lines"]}, payload


def test_morning_names_the_news_under_the_mover(conn, settings, user):
    ids, lines, payload = letter(conn, settings, user)
    assert ids[ids.index("portfolio") + 1] == "news_mover"
    assert lines["news_mover"]["text"] == "Nieuws over NVIDIA Corp.: NVIDIA zakt na cijfers."
    assert lines["news"]["text"] == "In De Tijd: Bel20 sluit hoger."
    panel = payload["details"]["news"]
    assert panel["positions"][0]["name"] == "NVIDIA Corp." and panel["positions"][0]["move"] == "−4,1%"
    assert panel["general"][0]["items"][0]["link"] == "https://t/1"
    assert payload["sources"]["news"] == "fresh"


def test_evening_stays_quiet_and_midday_has_only_the_top_story(conn, settings, user):
    ids, _, _ = letter(conn, settings, user, hour=21, minute=0)
    assert "news" not in ids and "news_mover" in ids
    ids, _, _ = letter(conn, settings, user, hour=12, minute=0)
    assert "news" in ids and "news_mover" not in ids


def test_without_feeds_or_search_there_is_no_news(conn, settings, user):
    payload = pipeline.run_for_user(conn, settings, user, now=at(7, 40), sources=[FakeSaxo()])
    assert "news" not in payload["details"] and payload["sources"]["news"] == "missing"


def test_the_page_never_overflows(conn, settings, user):
    ids, _, payload = letter(conn, settings, user)
    assert len(payload["lines"]) <= 10


# --- settings: web and command line -----------------------------------------------------

@pytest.fixture
def client(settings, conn, user, monkeypatch):
    monkeypatch.delenv("DAILYLETTER_USER", raising=False)
    monkeypatch.setattr(pipeline, "DEFAULT_SOURCES", [])
    monkeypatch.setattr(pipeline, "news_source_for", lambda prefs, pf: None)
    return TestClient(create_app(settings), follow_redirects=False)


def test_add_and_remove_a_feed_on_the_settings_page(client, conn, user, monkeypatch):
    monkeypatch.setattr(news_rss, "check_feed", lambda url, label: [])
    answer = client.post("/instellingen/nieuws", data={"label": "De Tijd", "url": "https://feeds.example/tijd.xml"})
    assert answer.headers["location"] == "/instellingen?m=nieuws"
    assert db.get_setting(conn, user["id"], "news_feeds") == [{"label": "De Tijd", "url": "https://feeds.example/tijd.xml"}]
    page = client.get("/instellingen").text
    assert "De Tijd" in page and "feeds.example" not in page
    client.post("/instellingen/nieuws/verwijder", data={"index": "0"})
    assert db.get_setting(conn, user["id"], "news_feeds") == []


def test_an_unreadable_feed_is_not_saved(client, conn, user, monkeypatch):
    def broken(url, label):
        raise NewsUnreachable("nee")
    monkeypatch.setattr(news_rss, "check_feed", broken)
    answer = client.post("/instellingen/nieuws", data={"label": "X", "url": "https://kapot.example"})
    assert answer.headers["location"] == "/instellingen?e=feed_read"
    assert client.post("/instellingen/nieuws", data={"url": "ftp://x"}).headers["location"] == "/instellingen?e=feed_url"
    assert db.get_setting(conn, user["id"], "news_feeds", []) == []


def test_position_search_toggle(client, conn, user):
    client.post("/instellingen/nieuws/posities", data={"aan": "1"})
    assert db.get_setting(conn, user["id"], "news_position_search") is True
    assert "Zet uit" in client.get("/instellingen").text
    client.post("/instellingen/nieuws/posities", data={"aan": "0"})
    assert db.get_setting(conn, user["id"], "news_position_search") is False


def test_news_command(settings, conn, user, monkeypatch, capsys):
    monkeypatch.setattr(news_rss, "check_feed", lambda url, label: [{"title": "Bel20 hoger"}])
    args = lambda action, label=None, url=None: Namespace(user="cedric", action=action, label=label, url=url)  # noqa: E731
    assert cli.cmd_news(args("add", "De Tijd", "https://feeds.example/tijd.xml"), settings) == 0
    assert 'De eerste kop: "Bel20 hoger"' in capsys.readouterr().out
    assert cli.cmd_news(args("list"), settings) == 0
    assert "De Tijd: https://feeds.example/tijd.xml" in capsys.readouterr().out
    assert cli.cmd_news(args("remove", "De Tijd"), settings) == 0
    assert cli.cmd_news(args("remove", "De Tijd"), settings) == 1
