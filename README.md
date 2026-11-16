# Dagbriefje

Eén rustige pagina die je op elk moment van de dag opent en die in een paar zinnen zegt wat er speelt.
Een batchjob maakt het briefje, een web-app toont het.

## Wat werkt nu

Fase 0 en het eerste deel van fase 1 uit het conceptueel ontwerp:

- Database met gebruikers, versleutelde koppelingen, instellingen, briefjes en je invoer.
- Batchjob: verzamelen, beslissen, schrijven, controleren, bewaren.
- Eén echte bron: je agenda, via een geheim iCal-adres.
- Vier versies per dag (ochtend, middag, vooravond, avond), in vaste sjabloonzinnen.
- Valt een bron uit, dan gebruikt het briefje het laatste goede antwoord en zegt het dat erbij.
- Pagina met het briefje, een detailpaneel voor je agenda, het invulbalkje en een instellingenpagina.

Nog niet: Garmin, Saxo, nieuws, het taalmodel, taken, timer, eten, de avondvraag.

## Installeren op de server

```bash
git clone https://github.com/SirAdlerBD/DailyLetter ~/dagbriefje && cd ~/dagbriefje
python3 -m venv .venv
.venv/bin/pip install .

cp .env.example .env
.venv/bin/dagbriefje gen-key        # plak de uitkomst in .env bij DAGBRIEFJE_SECRET_KEY
chmod 600 .env

.venv/bin/dagbriefje init
.venv/bin/dagbriefje user add cedric --display-name Cedric
.venv/bin/dagbriefje serve          # test: http://127.0.0.1:8321
```

Bewaar `DAGBRIEFJE_SECRET_KEY` ook ergens veilig buiten de server.
Zonder die sleutel zijn de bewaarde koppelingen niet meer te lezen.

### Alleen bereikbaar voor jouw toestellen

De web-app luistert alleen op de server zelf. Tailscale zet ze door naar je eigen toestellen, met HTTPS:

```bash
tailscale serve --bg 8321
```

Open daarna het adres dat Tailscale toont op je gsm en zet de pagina op je beginscherm.
Werkt het commando anders bij jouw versie, kijk dan in `tailscale serve --help`.

### Altijd aan, vier keer per dag

```bash
mkdir -p ~/.config/systemd/user
cp deploy/dagbriefje-*.service deploy/dagbriefje-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dagbriefje-web.service dagbriefje-run.timer
loginctl enable-linger "$USER"      # blijft draaien als je uitlogt
```

## Je agenda koppelen

Open de pagina, tik onderaan op Instellingen en plak het geheime iCal-adres van je agenda.
In Google Calendar staat het bij Instellingen, je agenda, "Geheim adres in iCal-indeling".
Het adres wordt versleuteld bewaard en daarna nergens meer getoond.

Het kan ook vanaf de server, zonder dat het adres in je shell-geschiedenis komt:

```bash
.venv/bin/dagbriefje connect cedric agenda
```

## Handige commando's

```bash
.venv/bin/dagbriefje run --show                    # maak nu een briefje en toon de zinnen
.venv/bin/dagbriefje run --version evening --show  # een bepaalde versie
journalctl --user -u dagbriefje-run.service        # wat de batchjob deed
```

## Waar staat wat

| Wat | Waar |
| --- | --- |
| Instellingen en sleutels van de installatie | `.env` (nooit in git) |
| Persoonlijke koppelingen | tabel `connections`, versleuteld |
| Voorkeuren per gebruiker | tabel `settings` |
| Alles wat van een gebruiker is | de database, elke rij met `user_id` |
| Zinnen van het briefje | `src/dagbriefje/texts_nl.py` |
| Regels en hun standaardwaarden | `src/dagbriefje/decide.py` |

In de code staat niets persoonlijks. Een nieuwe bron is een klasse in `src/dagbriefje/sources/`
die dezelfde feiten teruggeeft; de rest van het briefje verandert daar niet door.

## Ontwikkelen

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```
