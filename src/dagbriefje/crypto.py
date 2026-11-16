"""Encryption for personal connections (an iCal address is a secret)."""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class SecretKeyError(RuntimeError):
    pass


def generate_key() -> str:
    return Fernet.generate_key().decode()


def _fernet(secret_key: str) -> Fernet:
    if not secret_key:
        raise SecretKeyError("DAGBRIEFJE_SECRET_KEY is leeg. Maak een sleutel met: dagbriefje gen-key")
    try:
        return Fernet(secret_key.encode())
    except ValueError as exc:
        raise SecretKeyError("DAGBRIEFJE_SECRET_KEY is geen geldige sleutel.") from exc


def encrypt(secret_key: str, plain: str) -> str:
    return _fernet(secret_key).encrypt(plain.encode()).decode()


def decrypt(secret_key: str, token: str) -> str:
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise SecretKeyError("Deze koppeling is met een andere sleutel versleuteld.") from exc
