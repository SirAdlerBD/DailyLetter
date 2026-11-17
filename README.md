# DailyLetter

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

Nog niet: Saxo, nieuws, het taalmodel, taken, timer, eten, de avondvraag.

## Installeren op de server

Vooraf nodig: Python 3.11 of nieuwer met `python3-venv`, en Tailscale op de server en op je eigen toestellen.

```bash
git clone https://github.com/SirAdlerBD/DailyLetter ~/DailyLetter && cd ~/DailyLetter
python3 -m venv .venv
.venv/bin/pip install .

cp .env.example .env
.venv/bin/dailyletter gen-key        # plak de uitkomst in .env bij DAILYLETTER_SECRET_KEY
chmod 600 .env

.venv/bin/dailyletter init
.venv/bin/dailyletter user add cedric --display-name Cedric
.venv/bin/dailyletter serve          # test: http://127.0.0.1:8321
```

Bewaar `DAILYLETTER_SECRET_KEY` ook ergens veilig buiten de server.
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
cp deploy/dailyletter-*.service deploy/dailyletter-*.timer ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now dailyletter-web.service dailyletter-run.timer
loginctl enable-linger "$USER"      # blijft draaien als je uitlogt
```

## Je agenda's koppelen

Open de pagina, tik onderaan op Instellingen, geef de agenda een naam (bijvoorbeeld Privé of Werk)
en plak het geheime iCal-adres. Herhaal dat voor elke agenda: het briefje voegt ze samen tot één dag,
en een afspraak die in twee agenda's staat, telt maar één keer.

- Google Calendar: Instellingen, je agenda, "Geheim adres in iCal-indeling".
- Outlook: Instellingen, Agenda, Gedeelde agenda's, "Een agenda publiceren", en dan de ICS-link.
  Op een werkaccount kan je IT-afdeling dat uitgeschakeld hebben.

De adressen worden versleuteld bewaard en daarna nergens meer getoond. Kan één agenda niet gelezen
worden, dan toont het briefje de andere en zegt het welke ontbreekt.

Het kan ook vanaf de server, zonder dat het adres in je shell-geschiedenis komt:

```bash
.venv/bin/dailyletter connect cedric agenda
```

## Garmin koppelen

DailyLetter haalt je slaap, herstel en trainingen uit je eigen
[Garmin-MCP](https://github.com/SirAdlerBD/Garmin-MCP), die op dezelfde server draait.
Het gebruikt alleen leestools: `get_recovery_snapshot`, `list_activities` en `get_profile`.

```bash
.venv/bin/dailyletter connect cedric garmin
```

Druk Enter bij het adres als je Garmin-MCP op de standaardpoort draait (`http://127.0.0.1:3001/mcp`),
en plak het `MCP_ACCESS_TOKEN` uit het `.env`-bestand van je Garmin-MCP. Het commando test de
verbinding eerst en bewaart het token pas als die werkt, versleuteld.

Het sportadvies volgt vaste regels in `src/dailyletter/decide_sport.py`:

- **Rust** bij minder dan 6 uur slaap, een HRV die niet in balans is, een rusthartslag 5 of meer
  boven je 7-daags gemiddelde, of een belasting die piekt (verhouding boven 1,5).
- **Rustig en korter** bij een oplopende belasting (1,3 tot 1,5), twee zwakke signalen tegelijk,
  of een zware sessie in de laatste twee dagen.
- Daarna het patroon: nooit drie dagen op rij impact (lopen, tennis, padel), een rustdag na zes
  trainingsdagen, en je looptotaal per week hooguit 10% boven je gemiddelde van de laatste vier weken.
- Zonder slaapdata van vannacht geeft het briefje geen advies, maar vraagt het om te synchroniseren.

## Instellingen per gebruiker

```bash
.venv/bin/dailyletter settings cedric                        # alles tonen
.venv/bin/dailyletter settings cedric long_run_day saturday  # vaste dag voor je lange run
.venv/bin/dailyletter settings cedric long_run_day           # terug naar de standaard
.venv/bin/dailyletter user rename cedric Cedric              # de naam in de begroeting
```

| Instelling | Standaard | Betekenis |
| --- | --- | --- |
| `long_run_day` | geen | Dag voor de lange run: `monday` tot `sunday` |
| `max_week_increase` | `0.1` | Hoeveel je looptotaal per week mag stijgen |
| `min_run_km` | `4.0` | Korter dan dit stelt het briefje geen run voor |
| `default_run_km` | `5.0` | Afstand zolang er nog geen loopgeschiedenis is |
| `version_until` | 12u, 16u, 20u30 | Wanneer ochtend, middag en vooravond eindigen |

## Handige commando's

```bash
.venv/bin/dailyletter run --show                    # maak nu een briefje en toon de zinnen
.venv/bin/dailyletter run --version evening --show  # een bepaalde versie
journalctl --user -u dailyletter-run.service        # wat de batchjob deed
```

## Waar staat wat

| Wat | Waar |
| --- | --- |
| Instellingen en sleutels van de installatie | `.env` (nooit in git) |
| Persoonlijke koppelingen | tabel `connections`, versleuteld |
| Voorkeuren per gebruiker | tabel `settings` |
| Alles wat van een gebruiker is | de database, elke rij met `user_id` |
| Zinnen van het briefje | `src/dailyletter/texts_nl.py` |
| Regels en hun standaardwaarden | `src/dailyletter/decide.py` |

In de code staat niets persoonlijks. Een nieuwe bron is een klasse in `src/dailyletter/sources/`
die dezelfde feiten teruggeeft; de rest van het briefje verandert daar niet door.

## Ontwikkelen

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```
