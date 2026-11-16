from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from dagbriefje import crypto, db
from dagbriefje.config import Settings

TZ = ZoneInfo("Europe/Brussels")

SAMPLE_ICS = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//test//dagbriefje//NL
BEGIN:VEVENT
UID:intake@test
SUMMARY:Intake RPA-traject
DTSTART;TZID=Europe/Brussels:20261116T133000
DTEND;TZID=Europe/Brussels:20261116T141500
LOCATION:Teams
END:VEVENT
BEGIN:VEVENT
UID:stuurgroep@test
SUMMARY:Stuurgroep testautomatisatie
DTSTART:20261116T160000Z
DTEND:20261116T173000Z
END:VEVENT
BEGIN:VEVENT
UID:verjaardag@test
SUMMARY:Verjaardag mama
DTSTART;VALUE=DATE:20261116
DTEND;VALUE=DATE:20261117
END:VEVENT
BEGIN:VEVENT
UID:geannuleerd@test
SUMMARY:Geannuleerde call
STATUS:CANCELLED
DTSTART;TZID=Europe/Brussels:20261116T100000
DTEND;TZID=Europe/Brussels:20261116T103000
END:VEVENT
BEGIN:VEVENT
UID:standup@test
SUMMARY:Wekelijkse sync
DTSTART;TZID=Europe/Brussels:20261103T090000
DTEND;TZID=Europe/Brussels:20261103T093000
RRULE:FREQ=WEEKLY;BYDAY=TU
END:VEVENT
BEGIN:VEVENT
UID:volgendeweek@test
SUMMARY:Iets volgende week
DTSTART;TZID=Europe/Brussels:20261123T090000
DTEND;TZID=Europe/Brussels:20261123T100000
END:VEVENT
END:VCALENDAR
"""


def at(hour: int, minute: int = 0, day: int = 16) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=TZ)


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path,
        secret_key=crypto.generate_key(),
        timezone="Europe/Brussels",
        host="127.0.0.1",
        port=8321,
        openai_api_key="",
        openai_model="",
    )


@pytest.fixture
def conn(settings):
    connection = db.connect(settings.db_path)
    db.migrate(connection)
    yield connection
    connection.close()


@pytest.fixture
def user(conn):
    db.add_user(conn, "cedric", "Cedric", "Europe/Brussels")
    return db.get_user(conn, "cedric")
