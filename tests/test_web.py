import pytest
from fastapi.testclient import TestClient

from dailyletter import crypto, db, pipeline
from dailyletter.web.app import create_app

class TodayAgenda:
    """One meeting on whatever day the test runs, so the page always has something to show."""

    name = "agenda"
    needs_connection = True

    def fetch(self, secret, window):
        start = window.now.replace(hour=13, minute=30, second=0, microsecond=0)
        end = start.replace(hour=14, minute=15)
        event = {"title": "Intake RPA-traject", "start": start.isoformat(), "end": end.isoformat(),
                 "all_day": False, "location": "Teams"}
        return {"today": [event], "tomorrow": []}


@pytest.fixture
def client(settings, conn, user, monkeypatch):
    monkeypatch.delenv("DAILYLETTER_USER", raising=False)
    # The web app triggers the pipeline; keep it off the network.
    monkeypatch.setattr(pipeline, "DEFAULT_SOURCES", [TodayAgenda()])
    return TestClient(create_app(settings), follow_redirects=False)


def test_empty_state_before_the_first_briefing(client):
    page = client.get("/")
    assert page.status_code == 200
    assert "Er is vandaag nog geen briefje." in page.text


def test_refresh_makes_a_briefing_and_the_page_shows_it(client):
    assert client.post("/refresh").status_code == 303
    page = client.get("/")
    assert "Cedric." in page.text
    assert "Je agenda is nog niet gekoppeld." in page.text


def test_inbox_stores_what_you_type(client, conn, user):
    assert client.post("/inbox", data={"text": "  minder beursnieuws  "}).status_code == 303
    rows = conn.execute("SELECT text, user_id FROM inbox").fetchall()
    assert [(r["text"], r["user_id"]) for r in rows] == [("minder beursnieuws", user["id"])]
    assert client.post("/inbox", data={"text": "   "}).status_code == 422


def test_connecting_the_agenda_encrypts_the_address(client, conn, user, settings):
    response = client.post("/instellingen/agenda", data={"url": "webcal://example.com/secret.ics"})
    assert response.headers["location"] == "/instellingen?m=agenda"
    stored = db.get_connection(conn, user["id"], "agenda")
    assert crypto.decrypt(settings.secret_key, stored) == "https://example.com/secret.ics"

    settings_page = client.get("/instellingen").text
    assert "Gekoppeld." in settings_page
    assert "example.com/secret" not in settings_page
    assert "Intake RPA-traject" in client.get("/").text


def test_a_bad_address_is_refused(client, conn, user):
    response = client.post("/instellingen/agenda", data={"url": "http://example.com/a.ics"})
    assert response.headers["location"] == "/instellingen?e=url"
    assert db.get_connection(conn, user["id"], "agenda") is None


def test_posts_from_another_site_are_refused(client, conn):
    response = client.post("/inbox", data={"text": "hallo"}, headers={"sec-fetch-site": "cross-site"})
    assert response.status_code == 403
    response = client.post("/inbox", data={"text": "hallo"}, headers={"origin": "https://evil.example"})
    assert response.status_code == 403
    assert conn.execute("SELECT count(*) AS n FROM inbox").fetchone()["n"] == 0


def test_page_text_is_escaped(client, conn, user, settings):
    payload = pipeline.run_for_user(conn, settings, user)
    payload["lines"].append({"id": "x", "text": "<script>alert(1)</script>", "detail": None})
    db.save_briefing(conn, user["id"], payload["date"], payload["version"], payload, "template", False)
    assert "<script>alert(1)</script>" not in client.get("/").text
