"""Command line: set up the installation, run the batch job, start the web app."""

from __future__ import annotations

import argparse
import getpass
import json
import sys

from . import crypto, db, pipeline
from .config import get_settings
from .decide import VERSIONS
from .sources import agenda_ical, garmin_mcp
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
    if args.source == "garmin":
        url = input(f"Adres van je Garmin-MCP [{garmin_mcp.DEFAULT_URL}]: ").strip() or garmin_mcp.DEFAULT_URL
        token = getpass.getpass("MCP_ACCESS_TOKEN van je Garmin-MCP (wordt niet getoond): ").strip()
        try:
            secret = garmin_mcp.dump_secret(url, token)
            # Try it before saving, so a typo shows now and not tomorrow morning.
            with McpClient(url, token) as mcp:
                mcp.call("get_sync_status")
        except (ValueError, McpError, McpToolError) as exc:
            print(f"Niet bewaard: {exc}", file=sys.stderr)
            return 1
        db.set_connection(conn, user["id"], "garmin", crypto.encrypt(settings.secret_key, secret))
        print(f"Garmin gekoppeld voor {args.user!r}. De verbinding werkt.")
        return 0
    return 1


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
    connect.add_argument("source", choices=["agenda", "garmin"])
    connect.set_defaults(func=cmd_connect)

    prefs = sub.add_parser("settings", help="toon of verander de instellingen van een gebruiker")
    prefs.add_argument("user")
    prefs.add_argument("key", nargs="?", help="bijvoorbeeld long_run_day")
    prefs.add_argument("value", nargs="?", help="de nieuwe waarde; leeg laten zet de standaard terug")
    prefs.set_defaults(func=cmd_settings)

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
