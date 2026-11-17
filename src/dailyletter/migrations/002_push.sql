-- Meldingen. Een abonnement is per toestel; `secret_enc` (adres en sleutels) is versleuteld.
CREATE TABLE push_subscriptions (
    id           INTEGER PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key          TEXT NOT NULL UNIQUE,
    secret_enc   TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    last_ok_at   TEXT,
    last_error   TEXT
);

-- Welke melding vandaag al vertrok, zodat een tijdstip nooit twee keer meldt.
CREATE TABLE notifications_sent (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date    TEXT NOT NULL,
    slot    TEXT NOT NULL,
    sent_at TEXT NOT NULL,
    PRIMARY KEY (user_id, date, slot)
);
