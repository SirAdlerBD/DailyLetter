import base64
import json
from argparse import Namespace

import httpx
import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from fastapi.testclient import TestClient

from dailyletter import cli, crypto, db, notify, pipeline, webpush
from dailyletter.config import Settings
from dailyletter.web.app import create_app
from dailyletter.webpush import Subscription, b64url, encrypt, unb64url

from .conftest import at

# RFC 8291, appendix A: the official example. If this matches, phones can read our messages.
RFC = {
    "plain": b"When I grow up, I want to be a watermelon",
    "as_private": "yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw",
    "ua_public": "BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4",
    "auth": "BTBZMqHH6r4Tts7J_aSIgg",
    "salt": "DGv6ra1nlYgDCS1FRnbzlw",
    "body": "DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8w"
            "EqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN",
}


def test_encryption_matches_the_rfc_example():
    server = ec.derive_private_key(int.from_bytes(unb64url(RFC["as_private"]), "big"), ec.SECP256R1())
    body = encrypt(RFC["plain"], RFC["ua_public"], RFC["auth"], _server_key=server, _salt=unb64url(RFC["salt"]))
    assert b64url(body) == RFC["body"]


def test_vapid_token_is_signed_with_our_key():
    private = webpush.generate_vapid_key()
    header = webpush.vapid_header("https://web.push.apple.com/abc", private, "mailto:test@example.com", now=1000)
    token = header.split("t=")[1].split(",")[0]
    head, claims, signature = token.split(".")
    assert json.loads(unb64url(claims)) == {"aud": "https://web.push.apple.com", "exp": 1000 + 12 * 3600,
                                            "sub": "mailto:test@example.com"}
    public = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), unb64url(webpush.vapid_public_key(private)))
    raw = unb64url(signature)
    der = encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big"))
    public.verify(der, f"{head}.{claims}".encode(), ec.ECDSA(hashes.SHA256()))   # raises if wrong


@pytest.mark.parametrize("endpoint", [
    "http://web.push.apple.com/x",          # not https
    "https://evil.example/x",               # not a push service
    "https://web.push.apple.com.evil.example/x",
])
def test_only_real_push_services_are_accepted(endpoint):
    with pytest.raises(webpush.PushError):
        Subscription.from_browser({"endpoint": endpoint, "keys": {"p256dh": RFC["ua_public"], "auth": RFC["auth"]}})


# --- a phone, simulated ------------------------------------------------------------

class Phone:
    """Has its own keys, like a browser, and decrypts what arrives."""

    def __init__(self, status=201):
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.auth = b"0123456789abcdef"
        self.status = status
        self.received = []
        self.endpoint = "https://web.push.apple.com/QGuQyavXutnMH9n"

    @property
    def subscription(self):
        public = self.key.public_key().public_bytes(
            webpush.serialization.Encoding.X962, webpush.serialization.PublicFormat.UncompressedPoint)
        return {"endpoint": self.endpoint, "keys": {"p256dh": b64url(public), "auth": b64url(self.auth)}}

    def handler(self, request):
        assert request.headers["Content-Encoding"] == "aes128gcm"
        assert request.headers["Authorization"].startswith("vapid t=")
        body = request.content
        salt, keyid = body[:16], body[21:86]
        server = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), keyid)
        shared = self.key.exchange(ec.ECDH(), server)
        ua_public = unb64url(self.subscription["keys"]["p256dh"])
        ikm = webpush._hkdf(self.auth, shared, b"WebPush: info\x00" + ua_public + keyid, 32)
        cek = webpush._hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
        nonce = webpush._hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
        plain = webpush.AESGCM(cek).decrypt(nonce, body[86:], None)
        self.received.append(json.loads(plain[:-1]))
        return httpx.Response(self.status)


@pytest.fixture
def push_settings(settings):
    fields = {k: getattr(settings, k) for k in settings.__dataclass_fields__}
    return Settings(**{**fields, "vapid_private": webpush.generate_vapid_key(), "vapid_contact": "mailto:test@example.com"})


def subscribe(conn, settings, user, phone):
    sub = Subscription.from_browser(phone.subscription)
    db.save_push(conn, user["id"], sub.key, crypto.encrypt(settings.secret_key, sub.to_json()))


class Agenda:
    name = "agenda"
    needs_connection = False

    def fetch(self, secret, window):
        start = window.now.replace(hour=13, minute=30)
        return {"today": [{"title": "Intake", "start": start.isoformat(), "end": start.replace(hour=14).isoformat(),
                           "all_day": False, "location": None}], "tomorrow": []}


def test_parse_times():
    assert notify.parse_times("7u30, 21:00") == ["07:30", "21:00"]
    assert notify.parse_times(["07:30"]) == ["07:30"]
    with pytest.raises(ValueError):
        notify.parse_times("25:00")


def test_due_once_and_not_hours_late():
    assert notify.due_slots(at(7, 30), ["07:30"], set()) == ["07:30"]
    assert notify.due_slots(at(7, 44), ["07:30"], set()) == ["07:30"]
    assert notify.due_slots(at(7, 44), ["07:30"], {"07:30"}) == []
    assert notify.due_slots(at(7, 15), ["07:30"], set()) == []
    assert notify.due_slots(at(10, 0), ["07:30"], set()) == []


def test_the_phone_gets_a_fresh_letter_at_its_time(conn, push_settings, user, monkeypatch):
    monkeypatch.setattr(pipeline, "DEFAULT_SOURCES", [Agenda()])
    phone = Phone()
    subscribe(conn, push_settings, user, phone)
    transport = httpx.MockTransport(phone.handler)

    assert notify.notify_user(conn, push_settings, user, now=at(7, 0), transport=transport) == (0, [])
    assert notify.notify_user(conn, push_settings, user, now=at(7, 30), transport=transport) == (1, [])
    assert phone.received[0]["title"] == "Goeiemorgen Cedric"
    assert phone.received[0]["body"].startswith("Je eerste afspraak is pas over 6 uur.")
    # The next tick, a quarter later, sends nothing again.
    assert notify.notify_user(conn, push_settings, user, now=at(7, 45), transport=transport) == (0, [])
    assert len(phone.received) == 1


def test_a_phone_that_unsubscribed_is_forgotten(conn, push_settings, user, monkeypatch):
    monkeypatch.setattr(pipeline, "DEFAULT_SOURCES", [Agenda()])
    phone = Phone(status=410)
    subscribe(conn, push_settings, user, phone)
    sent, _ = notify.notify_user(conn, push_settings, user, now=at(7, 30), transport=httpx.MockTransport(phone.handler))
    assert sent == 0 and db.list_push(conn, user["id"]) == []


def test_without_a_key_nothing_is_sent_and_it_says_why(conn, settings, user):
    phone = Phone()
    subscribe(conn, settings, user, phone)
    sent, errors = notify.send_to_user(conn, settings, user, {"title": "x"}, httpx.MockTransport(phone.handler))
    assert sent == 0 and "gen-vapid" in errors[0]


# --- web: subscribing, the widget feed ------------------------------------------------

@pytest.fixture
def client(push_settings, conn, user, monkeypatch):
    monkeypatch.delenv("DAILYLETTER_USER", raising=False)
    monkeypatch.setattr(pipeline, "DEFAULT_SOURCES", [Agenda()])
    return TestClient(create_app(push_settings), follow_redirects=False)


def test_subscribe_and_unsubscribe_from_the_settings_page(client, conn, user, push_settings):
    phone = Phone()
    page = client.get("/instellingen").text
    assert f'data-key="{webpush.vapid_public_key(push_settings.vapid_private)}"' in page
    assert client.post("/meldingen/abonneer", json=phone.subscription).json() == {"ok": True}
    [row] = db.list_push(conn, user["id"])
    assert phone.endpoint not in row["secret_enc"]      # stored encrypted
    assert client.post("/meldingen/abonneer", json={"endpoint": "https://evil.example/x"}).status_code == 422
    client.post("/meldingen/uitschrijven", json={"endpoint": phone.endpoint})
    assert db.list_push(conn, user["id"]) == []


def test_times_can_be_changed(client, conn, user):
    assert client.post("/instellingen/meldingen/tijden", data={"tijden": "7u15, 21:00"}).headers["location"] == "/instellingen?m=tijden"
    assert db.get_setting(conn, user["id"], "notify_times") == ["07:15", "21:00"]
    assert client.post("/instellingen/meldingen/tijden", data={"tijden": "straks"}).headers["location"] == "/instellingen?e=tijden"


def test_service_worker_is_served_from_the_root(client):
    answer = client.get("/sw.js")
    assert answer.status_code == 200 and "showNotification" in answer.text
    assert answer.headers["content-type"].startswith("application/javascript")


def test_widget_feed(client):
    empty = client.get("/api/briefje").json()
    assert empty["lines"] == [] and empty["date_label"]
    client.post("/refresh")
    answer = client.get("/api/briefje")
    assert answer.headers["cache-control"] == "no-store"
    lines = answer.json()["lines"]
    assert lines and not lines[0].startswith("Goei")    # the greeting is left out


def test_gen_vapid_writes_into_env(tmp_path, settings, monkeypatch, capsys):
    env = tmp_path / ".env"
    env.write_text("DAILYLETTER_SECRET_KEY=abc\nDAILYLETTER_VAPID_PRIVATE=\n", encoding="utf-8")
    monkeypatch.setenv("DAILYLETTER_ENV_FILE", str(env))
    assert cli.cmd_gen_vapid(Namespace(contact="mailto:jij@voorbeeld.be", force=False), settings) == 0
    text = env.read_text()
    assert text.count("DAILYLETTER_VAPID_PRIVATE=") == 1 and "DAILYLETTER_VAPID_CONTACT=mailto:jij@voorbeeld.be" in text
    assert "DAILYLETTER_SECRET_KEY=abc" in text
    assert oct(env.stat().st_mode)[-3:] == "600"
    assert cli.cmd_gen_vapid(Namespace(contact="niet-goed", force=False), settings) == 1
