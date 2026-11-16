"""Command line: set up the installation, run the batch job, start the web app."""

from __future__ import annotations

import argparse
import getpass
import sys

from . import crypto, db, pipeline
from .config import get_settings
from .decide import VERSIONS
from .sources.agenda_ical import normalize_url


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
        print("Let op: DAGBRIEFJE_SECRET_KEY is nog leeg. Maak een sleutel met: dagbriefje gen-key")
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
    # Asked without echo so the secret never lands in the shell history.
    secret = getpass.getpass(f"Geheim voor {args.source} (wordt niet getoond): ").strip()
    if args.source == "agenda":
        secret = normalize_url(secret)
    db.set_connection(conn, user["id"], args.source, crypto.encrypt(settings.secret_key, secret))
    print(f"Koppeling {args.source!r} bewaard voor {args.user!r}.")
    return 0


def cmd_run(args, settings) -> int:
    conn = _conn(settings)
    users = db.list_users(conn) if args.user is None else [db.get_user(conn, args.user)]
    if not users or users[0] is None:
        print("Geen gebruiker gevonden. Maak er een met: dagbriefje user add <naam>", file=sys.stderr)
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
    parser = argparse.ArgumentParser(prog="dagbriefje", description="Een rustig dagbriefje.")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init", help="maak de database aan of werk ze bij").set_defaults(func=cmd_init)
    sub.add_parser("gen-key", help="maak een sleutel voor DAGBRIEFJE_SECRET_KEY").set_defaults(func=cmd_gen_key)

    user = sub.add_parser("user", help="gebruikers beheren").add_subparsers(dest="user_command", required=True)
    add = user.add_parser("add", help="maak een gebruiker")
    add.add_argument("name")
    add.add_argument("--display-name", help="de naam in de begroeting")
    add.add_argument("--timezone", help="bijvoorbeeld Europe/Brussels")
    add.set_defaults(func=cmd_user_add)

    connect = sub.add_parser("connect", help="bewaar een persoonlijke koppeling, versleuteld")
    connect.add_argument("user")
    connect.add_argument("source", choices=["agenda"])
    connect.set_defaults(func=cmd_connect)

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
