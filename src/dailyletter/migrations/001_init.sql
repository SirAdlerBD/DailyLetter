-- Fase 0 en 1. Elke tabel met persoonlijke inhoud verwijst naar een gebruiker.

CREATE TABLE users (
    id           INTEGER PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    display_name TEXT NOT NULL,
    timezone     TEXT NOT NULL,
    locale       TEXT NOT NULL DEFAULT 'nl',
    created_at   TEXT NOT NULL
);

-- Persoonlijke koppelingen. `secret_enc` is versleuteld met DAILYLETTER_SECRET_KEY.
CREATE TABLE connections (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,
    secret_enc TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (user_id, source)
);

-- Voorkeuren per gebruiker. `value` is JSON.
CREATE TABLE settings (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key     TEXT NOT NULL,
    value   TEXT NOT NULL,
    PRIMARY KEY (user_id, key)
);

-- Het ruwe antwoord per bron en per ophaalmoment.
CREATE TABLE snapshots (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    source     TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    payload    TEXT,
    error      TEXT
);
CREATE INDEX snapshots_latest ON snapshots (user_id, source, fetched_at);

CREATE TABLE briefings (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    version    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    writer     TEXT NOT NULL,
    fallback   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    UNIQUE (user_id, date, version)
);

-- Alles wat in het balkje getypt wordt. `kind` wordt later door het model ingevuld.
CREATE TABLE inbox (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    text       TEXT NOT NULL,
    kind       TEXT,
    processed  INTEGER NOT NULL DEFAULT 0
);
