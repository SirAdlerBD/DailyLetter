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
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from .. import crypto, db, pipeline
from ..config import Settings, get_settings
from ..sources import agenda_ical
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

    return app
