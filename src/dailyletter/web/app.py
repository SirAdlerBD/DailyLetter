"""The web app: one page that shows the latest briefing and stores what you type.

It only reads the database. Sources are fetched by the batch job, so the page opens at once.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import crypto, db, decide, notify, pipeline, texts_nl, webpush
from ..config import Settings, get_settings
from ..sources import agenda_ical, news_rss
from ..sources.agenda_ical import InvalidCalendarUrl, TooManyCalendars

HERE = Path(__file__).parent
MAX_INBOX_LENGTH = 2000


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="DailyLetter", docs_url=None, redoc_url=None, openapi_url=None)
    templates = Jinja2Templates(directory=HERE / "templates")
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    startup = db.connect(settings.db_path)
    db.migrate(startup)
    startup.close()

    def get_conn():
        conn = db.connect(settings.db_path)
        try:
            yield conn
        finally:
            conn.close()

    def current_user(conn: sqlite3.Connection = Depends(get_conn)) -> sqlite3.Row:
        """Who is looking. Today: the one user of this installation.

        This is the single place to change when real accounts arrive.
        """
        name = os.environ.get("DAILYLETTER_USER")
        if name:
            user = db.get_user(conn, name)
        else:
            users = db.list_users(conn)
            user = users[0] if len(users) == 1 else None
        if user is None:
            raise HTTPException(
                503, "Er is nog geen gebruiker. Maak er een met: dailyletter user add <naam>"
            )
        return user

    @app.middleware("http")
    async def same_site_posts_only(request: Request, call_next):
        """Refuse a form posted from another website (there is no login to protect us)."""
        if request.method == "POST":
            fetch_site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            cross_site = fetch_site not in (None, "same-origin", "none")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                cross_site = True
            if cross_site:
                return JSONResponse({"detail": "cross-site request refused"}, status_code=403)
        return await call_next(request)

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/", response_class=HTMLResponse)
    def briefje(request: Request, conn=Depends(get_conn), user=Depends(current_user)):
        now = datetime.now(ZoneInfo(user["timezone"]))
        briefing = db.latest_briefing(conn, user["id"], now.date().isoformat())
        return templates.TemplateResponse(
            request, "briefje.html", {"briefing": briefing, "user": user, "saved": request.query_params.get("saved")}
        )

    @app.post("/inbox")
    def inbox(request: Request, text: str = Form(...), conn=Depends(get_conn), user=Depends(current_user)):
        text = text.strip()
        if not text:
            raise HTTPException(422, "Leeg bericht.")
        if len(text) > MAX_INBOX_LENGTH:
            raise HTTPException(422, "Te lang.")
        db.add_inbox(conn, user["id"], text)
        if "application/json" in request.headers.get("accept", ""):
            return {"ok": True}
        return RedirectResponse("/?saved=1", status_code=303)

    @app.post("/refresh")
    def refresh(conn=Depends(get_conn), user=Depends(current_user)):
        """Make a briefing right now, for example just after connecting the agenda."""
        pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/", status_code=303)

    def read_calendars(conn: sqlite3.Connection, user_id: int) -> list[dict]:
        token = db.get_connection(conn, user_id, "agenda")
        if token is None:
            return []
        return agenda_ical.load_calendars(crypto.decrypt(settings.secret_key, token))

    def write_calendars(conn: sqlite3.Connection, user_id: int, calendars: list[dict]) -> None:
        if not calendars:
            db.delete_connection(conn, user_id, "agenda")
            return
        token = crypto.encrypt(settings.secret_key, agenda_ical.dump_calendars(calendars))
        db.set_connection(conn, user_id, "agenda", token)

    @app.get("/instellingen", response_class=HTMLResponse)
    def settings_page(request: Request, conn=Depends(get_conn), user=Depends(current_user)):
        error = request.query_params.get("e")
        try:
            calendars = read_calendars(conn, user["id"])
        except crypto.SecretKeyError:
            calendars, error = [], "unreadable"
        return templates.TemplateResponse(
            request,
            "instellingen.html",
            {
                "user": user,
                # Names only. The addresses are secrets and never go back to the browser.
                "calendars": [c["label"] for c in calendars],
                "garmin_connected": db.get_connection(conn, user["id"], "garmin") is not None,
                "saxo_connected": db.get_connection(conn, user["id"], "saxo") is not None,
                "feeds": [f["label"] for f in news_rss.load_feeds(db.get_setting(conn, user["id"], "news_feeds", []))],
                "position_search": db.get_setting(conn, user["id"], "news_position_search", False),
                "max_feeds": news_rss.MAX_FEEDS,
                "push_key": vapid_public(),
                "push_devices": len(db.list_push(conn, user["id"])),
                "notify_times": ", ".join(notify.parse_times(
                    db.get_setting(conn, user["id"], "notify_times", decide.DEFAULTS["notify_times"]))),
                "user_name": user["name"],
                "max_calendars": agenda_ical.MAX_CALENDARS,
                "message": request.query_params.get("m"),
                "error": error,
            },
        )

    @app.post("/instellingen/agenda")
    def add_agenda(
        url: str = Form(...), label: str = Form(""), conn=Depends(get_conn), user=Depends(current_user)
    ):
        try:
            calendars = agenda_ical.add_calendar(read_calendars(conn, user["id"]), label, url)
            write_calendars(conn, user["id"], calendars)
        except InvalidCalendarUrl:
            return RedirectResponse("/instellingen?e=url", status_code=303)
        except TooManyCalendars:
            return RedirectResponse("/instellingen?e=max", status_code=303)
        except crypto.SecretKeyError:
            return RedirectResponse("/instellingen?e=key", status_code=303)
        pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/instellingen?m=agenda", status_code=303)

    @app.post("/instellingen/agenda/verwijder")
    def remove_agenda(index: int = Form(...), conn=Depends(get_conn), user=Depends(current_user)):
        try:
            calendars = read_calendars(conn, user["id"])
        except crypto.SecretKeyError:
            # Unreadable with this key: the only way forward is to start over.
            calendars = []
        write_calendars(conn, user["id"], agenda_ical.remove_calendar(calendars, index))
        if calendars:
            pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/instellingen?m=verwijderd", status_code=303)

    def vapid_public() -> str | None:
        if not settings.vapid_private:
            return None
        try:
            return webpush.vapid_public_key(settings.vapid_private)
        except webpush.PushError:
            return None

    @app.get("/sw.js")
    def service_worker():
        # Served from the root, so it may handle the whole app.
        return FileResponse(HERE / "static" / "sw.js", media_type="application/javascript",
                            headers={"Cache-Control": "no-cache"})

    @app.get("/api/briefje")
    def api_briefje(conn=Depends(get_conn), user=Depends(current_user)):
        """The letter as plain lines, for the home-screen widget."""
        now = datetime.now(ZoneInfo(user["timezone"]))
        letter = db.latest_briefing(conn, user["id"], now.date().isoformat())
        body = {
            "date_label": letter["date_label"] if letter else texts_nl.long_date(now),
            "generated_label": letter["generated_label"] if letter else "",
            "version": letter["version"] if letter else None,
            "lines": [line["text"] for line in letter["lines"][1:]] if letter else [],
        }
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.post("/meldingen/abonneer")
    async def subscribe(request: Request, conn=Depends(get_conn), user=Depends(current_user)):
        try:
            sub = webpush.Subscription.from_browser(await request.json())
            db.save_push(conn, user["id"], sub.key, crypto.encrypt(settings.secret_key, sub.to_json()))
        except (webpush.PushError, ValueError, crypto.SecretKeyError) as exc:
            raise HTTPException(422, str(exc))
        return {"ok": True}

    @app.post("/meldingen/uitschrijven")
    async def unsubscribe(request: Request, conn=Depends(get_conn), user=Depends(current_user)):
        data = await request.json()
        endpoint = str(data.get("endpoint") or "")
        db.delete_push(conn, user["id"], webpush.Subscription(endpoint, "", "").key)
        return {"ok": True}

    @app.post("/meldingen/test")
    def test_notification(conn=Depends(get_conn), user=Depends(current_user)):
        payload = {"title": "Testmelding", "body": "Meldingen werken. Je briefje meldt zich voortaan hier.",
                   "url": "/", "tag": "test"}
        sent, errors = notify.send_to_user(conn, settings, user, payload)
        return {"sent": sent, "error": errors[0] if errors and not sent else None}

    @app.post("/instellingen/meldingen/tijden")
    def notify_times(tijden: str = Form(""), conn=Depends(get_conn), user=Depends(current_user)):
        try:
            times = notify.parse_times(tijden)
        except ValueError:
            return RedirectResponse("/instellingen?e=tijden", status_code=303)
        db.set_setting(conn, user["id"], "notify_times", times)
        return RedirectResponse("/instellingen?m=tijden", status_code=303)

    def read_feeds(conn: sqlite3.Connection, user_id: int) -> list[dict]:
        return news_rss.load_feeds(db.get_setting(conn, user_id, "news_feeds", []))

    @app.post("/instellingen/nieuws")
    def add_news(url: str = Form(...), label: str = Form(""), conn=Depends(get_conn), user=Depends(current_user)):
        try:
            feeds = news_rss.add_feed(read_feeds(conn, user["id"]), label, url)
        except news_rss.InvalidFeedUrl:
            return RedirectResponse("/instellingen?e=feed_url", status_code=303)
        except news_rss.TooManyFeeds:
            return RedirectResponse("/instellingen?e=feed_max", status_code=303)
        try:
            news_rss.check_feed(url, label)
        except Exception:  # not a readable feed: tell the user, keep nothing
            return RedirectResponse("/instellingen?e=feed_read", status_code=303)
        db.set_setting(conn, user["id"], "news_feeds", feeds)
        pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/instellingen?m=nieuws", status_code=303)

    @app.post("/instellingen/nieuws/verwijder")
    def remove_news(index: int = Form(...), conn=Depends(get_conn), user=Depends(current_user)):
        feeds = read_feeds(conn, user["id"])
        if 0 <= index < len(feeds):
            db.set_setting(conn, user["id"], "news_feeds", feeds[:index] + feeds[index + 1:])
            pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/instellingen?m=nieuws_weg", status_code=303)

    @app.post("/instellingen/nieuws/posities")
    def toggle_position_news(aan: str = Form(...), conn=Depends(get_conn), user=Depends(current_user)):
        db.set_setting(conn, user["id"], "news_position_search", aan == "1")
        pipeline.run_for_user(conn, settings, user)
        return RedirectResponse("/instellingen?m=nieuws", status_code=303)

    return app
