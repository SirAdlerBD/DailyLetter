"""Command line: set up the installation, run the batch job, start the web app."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys

from . import crypto, db, pipeline
from .config import get_settings
from .decide import VERSIONS
from .sources import agenda_ical, garmin_mcp, saxo_mcp
from .sources.mcp_client import McpClient, McpError, McpToolError


def _conn(settings):
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    return conn


def cmd_init(args, settings) -> int:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = db.connect(settings.db_path)
    applied = db.migrate(conn)
    print(f"Database: {settings.db_path}")
    print("Migraties toegepast: " + (", ".join(applied) if applied else "geen nieuwe"))
    if not settings.secret_key:
        print("Let op: DAILYLETTER_SECRET_KEY is nog leeg. Maak een sleutel met: dailyletter gen-key")
    return 0


def cmd_gen_key(args, settings) -> int:
    print(crypto.generate_key())
    return 0


def cmd_user_add(args, settings) -> int:
    conn = _conn(settings)
    if db.get_user(conn, args.name):
        print(f"Gebruiker {args.name!r} bestaat al.", file=sys.stderr)
        return 1
    db.add_user(conn, args.name, args.display_name or args.name.capitalize(), args.timezone or settings.timezone)
    print(f"Gebruiker {args.name!r} aangemaakt.")
    return 0


def cmd_connect(args, settings) -> int:
    conn = _conn(settings)
    user = db.get_user(conn, args.user)
    if user is None:
        print(f"Gebruiker {args.user!r} bestaat niet.", file=sys.stderr)
        return 1
    if args.source == "agenda":
        label = input("Naam van de agenda, bijvoorbeeld Privé of Werk: ").strip()
        # Asked without echo so the secret never lands in the shell history or on screen.
        url = getpass.getpass("Geheim iCal-adres (wordt niet getoond): ").strip()
        token = db.get_connection(conn, user["id"], "agenda")
        current = agenda_ical.load_calendars(crypto.decrypt(settings.secret_key, token)) if token else []
        calendars = agenda_ical.add_calendar(current, label, url)
        secret = agenda_ical.dump_calendars(calendars)
        db.set_connection(conn, user["id"], "agenda", crypto.encrypt(settings.secret_key, secret))
        names = ", ".join(c["label"] for c in calendars)
        print(f"Agenda bewaard voor {args.user!r}. Gekoppeld: {names}.")
        return 0
    if args.source in MCP_SOURCES:
        label, default_url, check_tool, check_args = MCP_SOURCES[args.source]
        if args.from_env:
            # Read the token straight from the MCP server's own .env: nothing to copy or paste.
            url = args.url or default_url
            try:
                token = read_env_value(args.from_env, "MCP_ACCESS_TOKEN")
            except (OSError, KeyError) as exc:
                print(f"Niet bewaard: {exc}", file=sys.stderr)
                return 1
        else:
            url = args.url or input(f"Adres van je {label}-MCP [{default_url}]: ").strip() or default_url
            token = clean_secret(getpass.getpass(f"MCP_ACCESS_TOKEN van je {label}-MCP (wordt niet getoond): "))
        try:
            secret = garmin_mcp.dump_secret(url, token)
            # Try it before saving, so a wrong port or token shows now and not tomorrow morning.
            with McpClient(url, token) as mcp:
                mcp.call(check_tool, check_args)
        except (ValueError, McpError, McpToolError) as exc:
            print(f"Niet bewaard: {exc}", file=sys.stderr)
            return 1
        db.set_connection(conn, user["id"], args.source, crypto.encrypt(settings.secret_key, secret))
        print(f"{label} gekoppeld voor {args.user!r}. De verbinding werkt.")
        return 0
    return 1


# source -> (name, default address, a read-only tool to test the connection, its arguments)
MCP_SOURCES = {
    "garmin": ("Garmin", garmin_mcp.DEFAULT_URL, "get_sync_status", {}),
    "saxo": ("Saxo", saxo_mcp.DEFAULT_URL, "get_balances", {"wholeClient": True}),
}


def clean_secret(text: str) -> str:
    """Remove what a terminal paste can add around a secret: escape codes, quotes, spaces."""
    text = text.replace("\x1b[200~", "").replace("\x1b[201~", "")
    text = "".join(ch for ch in text if ch.isprintable()).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "\"'":
        text = text[1:-1].strip()
    if "=" in text and text.split("=", 1)[0].strip().isupper():
        text = text.split("=", 1)[1].strip()  # the whole line "MCP_ACCESS_TOKEN=..." was pasted
    return text


def read_env_value(path: str, key: str) -> str:
    """Read one KEY=value from a .env file without printing it."""
    with open(os.path.expanduser(path), encoding="utf-8") as file:
        for line in file:
            name, sep, value = line.strip().partition("=")
            if sep and name.strip() == key:
                value = clean_secret(value.split(" #", 1)[0])
                if value:
                    return value
    raise KeyError(f"{key} staat niet (of leeg) in {path}")


def cmd_user_rename(args, settings) -> int:
    conn = _conn(settings)
    if db.get_user(conn, args.name) is None:
        print(f"Gebruiker {args.name!r} bestaat niet.", file=sys.stderr)
        return 1
    conn.execute("UPDATE users SET display_name = ? WHERE name = ?", (args.display_name, args.name))
    conn.commit()
    print(f"De begroeting gebruikt nu {args.display_name!r}.")
    return 0


def _parse_value(text: str):
    """JSON when it parses (numbers, null, true), otherwise the plain text."""
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def cmd_settings(args, settings) -> int:
    conn = _conn(settings)
    user = db.get_user(conn, args.user)
    if user is None:
        print(f"Gebruiker {args.user!r} bestaat niet.", file=sys.stderr)
        return 1
    if args.key is not None:
        if args.key not in pipeline.ALL_DEFAULTS:
            print(f"Onbekende instelling {args.key!r}. Kies uit: {', '.join(pipeline.ALL_DEFAULTS)}", file=sys.stderr)
            return 1
        if args.value is None:
            conn.execute("DELETE FROM settings WHERE user_id = ? AND key = ?", (user["id"], args.key))
            conn.commit()
            print(f"{args.key} staat terug op de standaardwaarde.")
            return 0
        db.set_setting(conn, user["id"], args.key, _parse_value(args.value))
    for key, value in pipeline.user_prefs(conn, user["id"]).items():
        print(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    return 0


def cmd_news(args, settings) -> int:
    from .sources import news_rss

    conn = _conn(settings)
    user = db.get_user(conn, args.user)
    if user is None:
        print(f"Gebruiker {args.user!r} bestaat niet.", file=sys.stderr)
        return 1
    feeds = news_rss.load_feeds(db.get_setting(conn, user["id"], "news_feeds", []))

    if args.action == "add":
        if not args.label or not args.url:
            print('Gebruik: dailyletter news <gebruiker> add "Naam" https://…', file=sys.stderr)
            return 1
        try:
            items = news_rss.check_feed(args.url, args.label)
        except Exception as exc:
            print(f"Die feed is niet te lezen ({type(exc).__name__}). Er is niets bewaard.", file=sys.stderr)
            return 1
        try:
            feeds = news_rss.add_feed(feeds, args.label, args.url)
        except ValueError as exc:
            print(f"Niet bewaard: {exc}.", file=sys.stderr)
            return 1
        db.set_setting(conn, user["id"], "news_feeds", feeds)
        first = f' De eerste kop: "{items[0]["title"]}".' if items else ""
        print(f"Bewaard: {args.label}, {len(items)} berichten gevonden.{first}")
    elif args.action == "remove":
        kept = news_rss.remove_feed(feeds, args.label or "")
        if len(kept) == len(feeds):
            print(f"Geen feed met de naam {args.label!r}.", file=sys.stderr)
            return 1
        db.set_setting(conn, user["id"], "news_feeds", kept)
        print(f"Verwijderd: {args.label}.")
    elif args.action == "test":
        for feed in feeds:
            try:
                items = news_rss.check_feed(feed["url"], feed["label"])
                print(f"{feed['label']}: {len(items)} berichten" + (f', bv. "{items[0]["title"]}"' if items else ""))
            except Exception as exc:
                print(f"{feed['label']}: niet te lezen ({type(exc).__name__})")
        if not feeds:
            print("Nog geen feeds.")
    else:
        for feed in feeds:
            print(f"{feed['label']}: {feed['url']}")
        if not feeds:
            print("Nog geen feeds.")
        search = db.get_setting(conn, user["id"], "news_position_search", False)
        print(f"Google News per positie: {'aan' if search else 'uit'}")
    return 0


def cmd_run(args, settings) -> int:
    conn = _conn(settings)
    users = db.list_users(conn) if args.user is None else [db.get_user(conn, args.user)]
    if not users or users[0] is None:
        print("Geen gebruiker gevonden. Maak er een met: dailyletter user add <naam>", file=sys.stderr)
        return 1
    failed = 0
    for user in users:
        try:
            payload = pipeline.run_for_user(conn, settings, user, version=args.version)
        except Exception as exc:  # one user's failure must not stop the others
            failed += 1
            print(f"{user['name']}: mislukt ({type(exc).__name__}: {exc})", file=sys.stderr)
            continue
        print(f"{user['name']}: {payload['version']} {payload['date']}, bronnen {payload['sources']}")
        if args.show:
            for line in payload["lines"]:
                print("  " + line["text"])
    return 1 if failed else 0


def cmd_serve(args, settings) -> int:
    import uvicorn

    from .web.app import create_app

    uvicorn.run(create_app(settings), host=settings.host, port=settings.port, log_level="info")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dailyletter", description="Een rustig dagelijks briefje.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="maak de database aan of werk ze bij").set_defaults(func=cmd_init)
    sub.add_parser("gen-key", help="maak een sleutel voor DAILYLETTER_SECRET_KEY").set_defaults(func=cmd_gen_key)

    user = sub.add_parser("user", help="gebruikers beheren").add_subparsers(dest="user_command", required=True)
    add = user.add_parser("add", help="maak een gebruiker")
    add.add_argument("name")
    add.add_argument("--display-name", help="de naam in de begroeting")
    add.add_argument("--timezone", help="bijvoorbeeld Europe/Brussels")
    add.set_defaults(func=cmd_user_add)
    rename = user.add_parser("rename", help="verander de naam in de begroeting")
    rename.add_argument("name")
    rename.add_argument("display_name")
    rename.set_defaults(func=cmd_user_rename)

    connect = sub.add_parser("connect", help="bewaar een persoonlijke koppeling, versleuteld")
    connect.add_argument("user")
    connect.add_argument("source", choices=["agenda", "garmin", "saxo"])
    connect.add_argument("--from-env", metavar="BESTAND",
                         help="garmin of saxo: lees MCP_ACCESS_TOKEN uit dit .env-bestand, bijvoorbeeld ~/garmin-mcp/.env")
    connect.add_argument("--url", help="garmin of saxo: adres van de MCP-server")
    connect.set_defaults(func=cmd_connect)

    prefs = sub.add_parser("settings", help="toon of verander de instellingen van een gebruiker")
    prefs.add_argument("user")
    prefs.add_argument("key", nargs="?", help="bijvoorbeeld long_run_day")
    prefs.add_argument("value", nargs="?", help="de nieuwe waarde; leeg laten zet de standaard terug")
    prefs.set_defaults(func=cmd_settings)

    news = sub.add_parser("news", help="nieuwsfeeds tonen, toevoegen, verwijderen of testen")
    news.add_argument("user")
    news.add_argument("action", nargs="?", choices=["list", "add", "remove", "test"], default="list")
    news.add_argument("label", nargs="?", help='de naam van de feed, bijvoorbeeld "De Tijd"')
    news.add_argument("url", nargs="?", help="add: het adres van de feed")
    news.set_defaults(func=cmd_news)

    run = sub.add_parser("run", help="maak een briefje (de batchjob)")
    run.add_argument("--user", help="alleen deze gebruiker; standaard iedereen")
    run.add_argument("--version", choices=VERSIONS, help="standaard volgens het uur")
    run.add_argument("--show", action="store_true", help="toon de zinnen")
    run.set_defaults(func=cmd_run)

    sub.add_parser("serve", help="start de web-app").set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    return args.func(args, get_settings())


if __name__ == "__main__":
    raise SystemExit(main())
