"""Installation settings, read from the environment (and a local .env file).

Nothing personal lives here: per-user data sits in the database.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env_file(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines into os.environ without overriding what is already set."""
    file = Path(path)
    if not file.is_file():
        return
    for raw in file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key.strip(), value)


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    secret_key: str
    timezone: str
    host: str
    port: int
    openai_api_key: str
    openai_model: str
    vapid_private: str = ""     # for notifications; make one with: dailyletter gen-vapid
    vapid_contact: str = ""     # mailto: or https: address the push services can reach you on

    @property
    def db_path(self) -> Path:
        return self.data_dir / "dailyletter.sqlite3"


def get_settings() -> Settings:
    load_env_file(os.environ.get("DAILYLETTER_ENV_FILE", ".env"))
    return Settings(
        data_dir=Path(os.environ.get("DAILYLETTER_DATA_DIR", "./data")).expanduser(),
        secret_key=os.environ.get("DAILYLETTER_SECRET_KEY", ""),
        timezone=os.environ.get("DAILYLETTER_TIMEZONE", "Europe/Brussels"),
        host=os.environ.get("DAILYLETTER_HOST", "127.0.0.1"),
        port=int(os.environ.get("DAILYLETTER_PORT", "8321")),
        openai_api_key=os.environ.get("OPENAI_API_KEY", ""),
        openai_model=os.environ.get("OPENAI_MODEL", ""),
        vapid_private=os.environ.get("DAILYLETTER_VAPID_PRIVATE", ""),
        vapid_contact=os.environ.get("DAILYLETTER_VAPID_CONTACT", ""),
    )
