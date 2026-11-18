# DailyLetter

Eén rustige pagina die je op elk moment van de dag opent en die in een paar zinnen zegt wat er speelt.
Een batchjob maakt het briefje, een web-app toont het.

## Wat werkt nu

- Database met gebruikers, versleutelde koppelingen, instellingen, briefjes en je invoer.
- Batchjob: verzamelen, beslissen, schrijven, controleren, bewaren. Vier versies per dag, in vaste sjabloonzinnen.
- Bronnen: je agenda's (iCal), Garmin (slaap, herstel, trainingen), Saxo (portefeuille, alleen lezen) en nieuws (RSS).
- Valt een bron uit, dan gebruikt het briefje het laatste goede antwoord en zegt het dat erbij.
- Pagina met het briefje, detailpanelen, het invulbalkje en een instellingenpagina.
- Op je gsm: op het beginscherm, met meldingen en een widget.

Nog niet: de vraag en les van de dag, het taalmodel, taken, timer, eten, de avondvraag.

Het volledige plan, met de volgende stappen en de open vragen, staat in [docs/PLAN.md](docs/PLAN.md).
Alle afhankelijkheden en koppelingen staan in [docs/INTEGRATIES.md](docs/INTEGRATIES.md). Verder bouwen
met een AI-assistent? Laat die eerst [AGENTS.md](AGENTS.md) lezen.

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
.venv/bin/dailyletter connect cedric garmin --from-env ~/garmin-mcp/.env
```

Dat leest het `MCP_ACCESS_TOKEN` rechtstreeks uit het `.env`-bestand van je Garmin-MCP, zonder dat
je het hoeft te kopiëren. Het adres is standaard `http://127.0.0.1:3001/mcp`; een andere poort geef
je mee met `--url`. Het commando test de verbinding eerst en bewaart het token pas als die werkt,
versleuteld. Zonder `--from-env` vraagt het om het adres en het token.

Het sportadvies volgt vaste regels in `src/dailyletter/decide_sport.py`:

- **Rust** bij minder dan 6 uur slaap, een HRV die niet in balans is, een rusthartslag 5 of meer
  boven je 7-daags gemiddelde, of een belasting die piekt (verhouding boven 1,5).
- **Rustig en korter** bij een oplopende belasting (1,3 tot 1,5), twee zwakke signalen tegelijk,
  of een zware sessie in de laatste twee dagen.
- Daarna het patroon: nooit drie dagen op rij impact (lopen, tennis, padel), een rustdag na zes
  trainingsdagen, en je looptotaal per week hooguit 10% boven je gemiddelde van de laatste vier weken,
  of tot je weekdoel uit `week_km_target` als dat hoger ligt.
- Zonder slaapdata van vannacht geeft het briefje geen advies, maar vraagt het om te synchroniseren.

## Saxo koppelen

DailyLetter leest je portefeuille uit je eigen [Saxo-MCP](https://github.com/SirAdlerBD/saxo-mcp),
de LIVE-versie die op dezelfde server draait. Het mag daarvan alleen `get_balances`, `get_positions`
en `get_account_history` aanroepen; elke andere tool wordt geweigerd voor ze vertrekt. Je Saxo-MCP
blokkeert handelen bovendien zelf.

```bash
.venv/bin/dailyletter connect cedric saxo --from-env ~/saxo-mcp-live/.env --url http://127.0.0.1:3001/mcp
```

Kijk met `pm2 ls` en `sudo ss -tlnp` welke poort je LIVE-server gebruikt.

Wat het briefje toont:

- 's Ochtends: hoe je portefeuille bewoog op de laatste beursdag en deze week, plus de positie die
  het meest bewoog als dat minstens 3% was. 's Avonds: de beweging van vandaag.
- Het paneel: de waarde (verborgen tot je op het oog tikt), je rendement van de laatste beursdag,
  deze week en dit jaar (tijdgewogen, dus stortingen tellen niet mee), je posities met hun gewicht,
  en je grootste losse aandeel als dat boven 20% zit. Fondsen tellen daar niet mee.
- Verloopt je Saxo-login, dan zegt het briefje dat. Log dan opnieuw in zoals bij je Saxo-MCP.

## Nieuws

Twee soorten bronnen, allebei gratis en zonder account:

- **Je eigen RSS-feeds**, bijvoorbeeld van De Tijd. Toevoegen kan op de instellingenpagina of hier:

  ```bash
  .venv/bin/dailyletter news cedric add "De Tijd" https://…   # leest de feed eerst, bewaart pas als die werkt
  .venv/bin/dailyletter news cedric                          # toon je feeds
  .venv/bin/dailyletter news cedric test                     # lees ze nu allemaal één keer
  .venv/bin/dailyletter news cedric remove "De Tijd"
  ```

- **Nieuws per positie** uit Google News, voor de aandelen in je Saxo-portefeuille (fondsen niet).
  Standaard uit, omdat Google die feeds alleen toestaat voor persoonlijk, niet-commercieel gebruik.
  Aanzetten kan op de instellingenpagina of met `dailyletter settings cedric news_position_search true`.

Wat het briefje toont: de topkop van je eerste feed ('s ochtends en overdag, niet 's avonds), en
nieuws over de positie die het meest bewoog, vlak onder de zin over je portefeuille. Alleen nieuws
van de laatste 24 uur telt (op maandag sinds vrijdag), een kop over een positie moet die positie
bij naam noemen, en hetzelfde verhaal komt nooit twee keer. In het paneel staan per bron een paar
koppen met een link naar het artikel.

## Op je gsm: app, meldingen en widget

**Als app.** Open het Tailscale-adres in Safari, tik op Deel en dan "Zet op beginscherm". Het briefje
opent daarna schermvullend, met een eigen icoon.

**Meldingen.** Eén keer op de server:

```bash
.venv/bin/dailyletter gen-vapid --contact mailto:jij@voorbeeld.be
systemctl --user restart dailyletter-web
```

Dat maakt de sleutel waarmee de server zijn meldingen ondertekent en zet ze in `.env`. Het contactadres
krijgen Apple en Google te zien, voor als er iets misloopt. Open daarna het briefje *vanaf je beginscherm*,
ga naar Instellingen en tik op "Zet meldingen aan". Op een iPhone werkt dat alleen vanaf het beginscherm.

Om de tijden in `notify_times` (standaard 7u30) maakt het briefje zich opnieuw en stuurt het de eerste
regels als melding. De timer `dailyletter-notify.timer` kijkt daarvoor elk kwartier. De melding is
versleuteld voor je toestel: Apple en Google brengen ze alleen over en kunnen ze niet lezen.

```bash
.venv/bin/dailyletter notify --test      # stuur nu een testmelding
```

**Widget.** Installeer de gratis app Scriptable. Kopieer op de instellingenpagina de code bij "Widget op
je beginscherm", maak in Scriptable een nieuw script en plak ze erin. Houd dan je beginscherm ingedrukt,
voeg een Scriptable-widget toe en kies dat script. De widget haalt je briefje rechtstreeks van je server,
dus Tailscale moet aanstaan: zet in de Tailscale-app "VPN On Demand" aan.

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
| `week_km_target` | geen | Je looptotaal deze week volgens je trainingsplan. Het briefje mikt nooit lager, ook als je vier-wekengemiddelde lager ligt |
| `min_run_km` | `4.0` | Korter dan dit stelt het briefje geen run voor |
| `default_run_km` | `5.0` | Afstand zolang er nog geen loopgeschiedenis is |
| `portfolio_mover_pct` | `3.0` | Vanaf welke dagbeweging (in %) een positie genoemd wordt |
| `portfolio_concentration_pct` | `20.0` | Vanaf welk gewicht (in %) je grootste losse aandeel vermeld wordt |
| `news_position_search` | `false` | Nieuws per positie uit Google News |
| `news_edition` | `BE:nl` | Welke Google News-editie: land:taal |
| `news_max_positions` | `8` | Voor hoeveel posities er nieuws gezocht wordt |
| `news_general_count` | `3` | Koppen per feed in het paneel |
| `news_per_position` | `2` | Koppen per positie in het paneel |
| `notify_times` | `["07:30"]` | Wanneer er een melding komt. Ook in te stellen op de instellingenpagina |
| `version_until` | 12u, 16u, 20u30 | Wanneer ochtend, middag en vooravond eindigen |

## Bijwerken op de server

```bash
~/DailyLetter/deploy/update.sh
```

Haalt de nieuwe code op, installeert ze in `.venv`, werkt de database bij en herstart de web-app.
Is er niets nieuws, dan doet het niets; `--force` installeert toch opnieuw.

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

## Ontwikkelen op je eigen pc (Windows)

Eenmalig, in PowerShell, met Git, Python 3.11 of nieuwer en VS Code geïnstalleerd:

```powershell
git clone https://github.com/SirAdlerBD/DailyLetter $HOME\code\DailyLetter
cd $HOME\code\DailyLetter
py -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
copy .env.example .env      # zet er een eigen DAILYLETTER_SECRET_KEY in (gen-key)
.venv\Scripts\dailyletter init
.venv\Scripts\dailyletter user add cedric --display-name Cedric
code .
```

`-e` installeert in bewerkbare modus: wat je in `src` wijzigt, werkt meteen, zonder opnieuw te installeren.
Je lokale database staat in `data/` en heeft niets met die op de server te maken.

Daarna, elke keer:

```powershell
git pull                                  # eerst ophalen wat er intussen veranderde
.venv\Scripts\python -m pytest            # tests
.venv\Scripts\dailyletter serve           # bekijk het op http://127.0.0.1:8321
```

Committen en pushen kan in VS Code via Source Control (Ctrl+Shift+G). Daarna op de server:
`~/DailyLetter/deploy/update.sh`.
