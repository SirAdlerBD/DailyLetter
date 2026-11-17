"""Web Push, small and without extra libraries: encrypt a message for one browser and send it.

Two standards do the work:
- RFC 8291: the message is encrypted for the browser (aes128gcm), so the push service of
  Apple or Google only carries it and cannot read it.
- RFC 8292 (VAPID): the server signs each request with its own key, so a push service knows
  the messages come from the server the browser subscribed to.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Only the push services of the big browsers. The server never posts to any other address.
PUSH_HOSTS = ("web.push.apple.com", "fcm.googleapis.com", "updates.push.services.mozilla.com",
              "notify.windows.com")
RECORD_SIZE = 4096
TTL_SECONDS = 4 * 3600   # a morning message that arrives in the afternoon is no use


class PushError(RuntimeError):
    pass


class SubscriptionGone(PushError):
    """The browser unsubscribed or the app was removed: forget this subscription."""


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def unb64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --- keys ---------------------------------------------------------------------------

def generate_vapid_key() -> str:
    """A new private key, as the 32-byte number in base64url (one line in .env)."""
    key = ec.generate_private_key(ec.SECP256R1())
    return b64url(key.private_numbers().private_value.to_bytes(32, "big"))


def _private_key(private_b64: str) -> ec.EllipticCurvePrivateKey:
    try:
        return ec.derive_private_key(int.from_bytes(unb64url(private_b64), "big"), ec.SECP256R1())
    except Exception as exc:
        raise PushError("DAILYLETTER_VAPID_PRIVATE is geen geldige sleutel.") from exc


def _raw_public(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def vapid_public_key(private_b64: str) -> str:
    """What the browser needs to subscribe: the public half, base64url."""
    return b64url(_raw_public(_private_key(private_b64).public_key()))


# --- subscriptions ------------------------------------------------------------------

@dataclass(frozen=True)
class Subscription:
    endpoint: str
    p256dh: str
    auth: str

    @classmethod
    def from_browser(cls, data: dict) -> "Subscription":
        """Check what the browser sent: a known push service and keys of the right size."""
        endpoint = str(data.get("endpoint") or "")
        keys = data.get("keys") or {}
        parts = urlsplit(endpoint)
        host = parts.hostname or ""
        if parts.scheme != "https" or not any(host == h or host.endswith("." + h) for h in PUSH_HOSTS):
            raise PushError("onbekende pushdienst")
        try:
            if len(unb64url(keys["p256dh"])) != 65 or len(unb64url(keys["auth"])) != 16:
                raise ValueError
        except (KeyError, ValueError, TypeError) as exc:
            raise PushError("ongeldige sleutels") from exc
        return cls(endpoint, keys["p256dh"], keys["auth"])

    def to_json(self) -> str:
        return json.dumps({"endpoint": self.endpoint, "keys": {"p256dh": self.p256dh, "auth": self.auth}})

    @property
    def key(self) -> str:
        """A stable name for the subscription that does not reveal the address."""
        return hashlib.sha256(self.endpoint.encode()).hexdigest()


# --- RFC 8291: encryption -----------------------------------------------------------

def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    return hmac.new(prk, info + b"\x01", hashlib.sha256).digest()[:length]


def encrypt(message: bytes, p256dh: str, auth: str, *, _server_key=None, _salt=None) -> bytes:
    ua_public = unb64url(p256dh)
    auth_secret = unb64url(auth)
    server_key = _server_key or ec.generate_private_key(ec.SECP256R1())
    as_public = _raw_public(server_key.public_key())
    shared = server_key.exchange(ec.ECDH(), ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_public))

    ikm = _hkdf(auth_secret, shared, b"WebPush: info\x00" + ua_public + as_public, 32)
    salt = _salt or os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    if len(message) > RECORD_SIZE - 17 - 86:
        raise PushError("bericht te lang")
    ciphertext = AESGCM(cek).encrypt(nonce, message + b"\x02", None)
    return salt + struct.pack("!IB", RECORD_SIZE, len(as_public)) + as_public + ciphertext


# --- RFC 8292: VAPID ----------------------------------------------------------------

def vapid_header(endpoint: str, private_b64: str, contact: str, now: float | None = None) -> str:
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}", "exp": int((now or time.time()) + 12 * 3600), "sub": contact}
    header = b64url(json.dumps({"typ": "JWT", "alg": "ES256"}, separators=(",", ":")).encode())
    body = b64url(json.dumps(claims, separators=(",", ":")).encode())
    key = _private_key(private_b64)
    r, s = decode_dss_signature(key.sign(f"{header}.{body}".encode(), ec.ECDSA(hashes.SHA256())))
    token = f"{header}.{body}.{b64url(r.to_bytes(32, 'big') + s.to_bytes(32, 'big'))}"
    return f"vapid t={token}, k={vapid_public_key(private_b64)}"


# --- sending ------------------------------------------------------------------------

def send(sub: Subscription, payload: dict, private_b64: str, contact: str,
         transport: httpx.BaseTransport | None = None, timeout: float = 10.0) -> None:
    if not private_b64 or not contact:
        raise PushError("Meldingen zijn nog niet ingesteld: maak sleutels met `dailyletter gen-vapid`.")
    body = encrypt(json.dumps(payload, ensure_ascii=False).encode(), sub.p256dh, sub.auth)
    headers = {
        "Authorization": vapid_header(sub.endpoint, private_b64, contact),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": str(TTL_SECONDS),
        "Urgency": "normal",
    }
    with httpx.Client(timeout=timeout, transport=transport) as client:
        response = client.post(sub.endpoint, content=body, headers=headers)
    if response.status_code in (404, 410):
        raise SubscriptionGone(str(response.status_code))
    if response.status_code >= 400:
        # The reason (for example BadJwtToken) helps; the address of the subscription stays out.
        raise PushError(f"{response.status_code} {response.text[:120]}")
