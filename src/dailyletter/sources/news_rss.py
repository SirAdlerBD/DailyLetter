"""News from RSS feeds: the feeds a user chose, plus one news search per position.

Only headlines, a short intro and a link are kept. Which ones matter is decided later,
in decide_news.py; this file only fetches and normalizes.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode, urlsplit

import httpx
from defusedxml import ElementTree

from .base import Window

MAX_FEEDS = 10
MAX_LABEL_LENGTH = 40
MAX_BYTES = 2_000_000          # a feed larger than this is not a feed we want
MAX_ITEMS_PER_FEED = 40
SUMMARY_LENGTH = 280
USER_AGENT = "DailyLetter/0.1 (persoonlijke feedlezer)"
GOOGLE_NEWS = "https://news.google.com/rss/search"

ATOM = "{http://www.w3.org/2005/Atom}"

# Legal forms and share classes say nothing about the company; searching with them misses news.
NAME_NOISE = re.compile(
    r"\b(n\.?v\.?|s\.?a\.?|s\.?e\.?|a\.?g\.?|plc|inc\.?|incorporated|corp\.?|corporation|co\.?|ltd\.?"
    r"|holdings?|group|groep|class [a-c]|cl\.? [a-c]|adr|reg\.?|registered|shares?|aandelen)(?=\W|$)",
    re.IGNORECASE,
)


class InvalidFeedUrl(ValueError):
    pass


class TooManyFeeds(ValueError):
    pass


class NewsUnreachable(RuntimeError):
    pass


# --- the user's list of feeds (stored as a setting: they are not secrets) -----------------

def normalize_feed_url(url: str) -> str:
    url = (url or "").strip()
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc or " " in url or len(url) > 2000:
        raise InvalidFeedUrl("een feedadres begint met https://")
    return url


def load_feeds(value) -> list[dict]:
    """The setting as stored, cleaned: a list of {label, url}."""
    feeds = []
    for item in value or []:
        if isinstance(item, dict) and item.get("url"):
            feeds.append({"label": str(item.get("label") or "Nieuws")[:MAX_LABEL_LENGTH], "url": item["url"]})
    return feeds


def add_feed(feeds: list[dict], label: str, url: str) -> list[dict]:
    """Add a feed; a label that already exists gets the new address."""
    url = normalize_feed_url(url)
    label = (label or "").strip()[:MAX_LABEL_LENGTH] or urlsplit(url).netloc
    kept = [f for f in feeds if f["label"].lower() != label.lower()]
    if len(kept) >= MAX_FEEDS:
        raise TooManyFeeds(f"hoogstens {MAX_FEEDS} feeds")
    return kept + [{"label": label, "url": url}]


def remove_feed(feeds: list[dict], label: str) -> list[dict]:
    return [f for f in feeds if f["label"].lower() != (label or "").strip().lower()]


# --- searching news about a position ----------------------------------------------------

def search_term(name: str) -> str:
    """'NVIDIA Corp.' -> 'NVIDIA', 'ASML Holding N.V.' -> 'ASML', 'KBC Groep' -> 'KBC'."""
    cleaned = NAME_NOISE.sub(" ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-/&")
    return cleaned or (name or "").strip()


def google_news_url(term: str, edition: str, days: int = 3) -> str:
    """A Google News search feed. `edition` is country:language, for example BE:nl."""
    country, _, language = edition.partition(":")
    query = f'"{term}" when:{days}d'
    return f"{GOOGLE_NEWS}?{urlencode({'q': query, 'hl': language or 'nl', 'gl': country or 'BE', 'ceid': edition})}"


# --- parsing ----------------------------------------------------------------------------

def _text(node, path: str) -> str:
    found = node.find(path)
    return (found.text or "").strip() if found is not None and found.text else ""


def _plain(fragment: str) -> str:
    """HTML in a feed intro becomes plain text, cut to a calm length."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > SUMMARY_LENGTH:
        text = text[: SUMMARY_LENGTH - 1].rsplit(" ", 1)[0] + "…"
    return text


def _when(value: str) -> str | None:
    if not value:
        return None
    try:
        moment = parsedate_to_datetime(value)          # RSS: 'Tue, 17 Nov 2026 07:12:00 GMT'
    except (TypeError, ValueError):
        try:
            moment = datetime.fromisoformat(value.replace("Z", "+00:00"))   # Atom
        except ValueError:
            return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc).isoformat(timespec="minutes")


def _safe_link(link: str) -> str | None:
    return link if urlsplit(link).scheme in ("http", "https") else None


def parse_feed(content: bytes | str, label: str, with_summary: bool = True) -> list[dict]:
    """RSS 2.0 or Atom into a list of {title, link, source, published, summary}."""
    root = ElementTree.fromstring(content)
    items = []
    if root.tag == f"{ATOM}feed":
        for entry in root.findall(f"{ATOM}entry")[:MAX_ITEMS_PER_FEED]:
            link = entry.find(f"{ATOM}link")
            items.append({
                "title": _text(entry, f"{ATOM}title"),
                "link": _safe_link(link.get("href", "") if link is not None else ""),
                "source": label,
                "published": _when(_text(entry, f"{ATOM}published") or _text(entry, f"{ATOM}updated")),
                "summary": _plain(_text(entry, f"{ATOM}summary")) if with_summary else "",
            })
    else:
        for item in root.findall("./channel/item")[:MAX_ITEMS_PER_FEED]:
            title = html.unescape(_text(item, "title"))
            source = _text(item, "source") or label
            # Google News writes 'Headline - Publisher'; the publisher is already in <source>.
            if source != label and title.endswith(f" - {source}"):
                title = title[: -len(source) - 3]
            items.append({
                "title": title,
                "link": _safe_link(_text(item, "link")),
                "source": source,
                "published": _when(_text(item, "pubDate")),
                "summary": _plain(_text(item, "description")) if with_summary else "",
            })
    return [i for i in items if i["title"]]


# --- fetching ---------------------------------------------------------------------------

class NewsSource:
    """Not a personal connection: feed addresses and search terms come with the source."""

    name = "news"
    needs_connection = False

    def __init__(self, feeds: list[dict], searches: list[dict], edition: str = "BE:nl",
                 timeout: float = 10.0, transport: httpx.BaseTransport | None = None):
        self.feeds = feeds
        self.searches = searches      # [{name, symbol, term}]
        self.edition = edition
        self.timeout = timeout
        self.transport = transport

    def _get(self, client: httpx.Client, url: str) -> bytes:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            body = b""
            for chunk in response.iter_bytes():
                body += chunk
                if len(body) > MAX_BYTES:
                    raise NewsUnreachable("feed te groot")
        return body

    def fetch(self, secret: str | None, window: Window) -> dict:
        feeds, positions, failed = [], [], []
        attempts = 0
        with httpx.Client(timeout=self.timeout, follow_redirects=True, transport=self.transport,
                          headers={"User-Agent": USER_AGENT}) as client:
            for feed in self.feeds:
                attempts += 1
                try:
                    items = parse_feed(self._get(client, feed["url"]), feed["label"])
                except Exception:   # one broken feed must not hide the others; its address stays out of errors
                    failed.append(feed["label"])
                    continue
                feeds.append({"label": feed["label"], "items": items})
            for search in self.searches:
                attempts += 1
                try:
                    url = google_news_url(search["term"], self.edition)
                    items = parse_feed(self._get(client, url), "Google News", with_summary=False)
                except Exception:
                    failed.append(search["name"])
                    continue
                positions.append({**search, "items": items})
        if attempts and not feeds and not positions:
            raise NewsUnreachable(f"geen enkele nieuwsbron bereikbaar ({len(failed)} geprobeerd)")
        return {"date": window.now.date().isoformat(), "feeds": feeds, "positions": positions, "failed": failed}


def check_feed(url: str, label: str, timeout: float = 10.0) -> list[dict]:
    """Read one feed now; raises when it is not a readable feed. Used before saving an address."""
    with httpx.Client(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}) as client:
        source = NewsSource([], [])
        return parse_feed(source._get(client, normalize_feed_url(url)), label)
