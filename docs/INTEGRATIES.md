# DailyLetter: afhankelijkheden en integraties

Alles waar DailyLetter op steunt: software, externe diensten, koppelingen, poorten, instellingen en bestanden.
Wat het briefje doet en wat er nog komt, staat in [PLAN.md](PLAN.md).

Laatst bijgewerkt: 18 november 2026.

---

## 1. Overzicht

| Integratie | Soort | Status | Kost | Account nodig | Code |
| --- | --- | --- | --- | --- | --- |
| Garmin-MCP | Eigen MCP-server, lokaal | In gebruik | € 0 | Garmin Connect | `sources/garmin_mcp.py` |
| Saxo-MCP (LIVE) | Eigen MCP-server, lokaal | In gebruik | € 0 | Saxo Bank | `sources/saxo_mcp.py` |
| iCal-agenda's | Geheim iCal-adres (Google, Outlook) | In gebruik | € 0 | Google of Microsoft | `sources/agenda_ical.py` |
| De Tijd | RSS-feeds | In gebruik | € 0 | Nee | `sources/news_rss.py` |
| Google News | RSS-zoekfeed per positie | Optioneel, standaard uit | € 0 | Nee | `sources/news_rss.py` |
| Web Push | Apple, Google, Mozilla, Microsoft | In gebruik | € 0 | Nee | `webpush.py`, `notify.py` |
| Scriptable | iOS-app voor de widget | In gebruik | € 0 | Nee | `web/static/widget-scriptable.js` |
| Tailscale | Privénetwerk met HTTPS | In gebruik | € 0 (persoonlijk) | Tailscale | — (op de server) |
| Google Fonts | Lettertypes Newsreader en Inter | In gebruik | € 0 | Nee | `web/templates/*.html` |
| OpenAI | Taalmodel | Gepland (fase 2) | Een paar euro per maand | OpenAI-API | — |
| FMP | Financiële data | Optioneel, niet gebruikt | Volgens abonnement | FMP | — |

---

## 2. Software

### Runtime

| Wat | Versie | Waarvoor |
| --- | --- | --- |
| Python | 3.11 of nieuwer (ontwikkeld op 3.13) | Alles |
| `python3-venv` | — | De virtuele omgeving `.venv` |
| systemd (gebruikersmodus) | — | Web-app en timers; `loginctl enable-linger` zodat ze blijven draaien |
| Tailscale | Recent | Toegang tot de pagina, HTTPS via `tailscale serve` |
| Node.js en pm2 | — | Niet voor DailyLetter zelf, wel voor de Garmin- en Saxo-MCP's op dezelfde server |
| Git | — | Code ophalen met `deploy/update.sh` |

### Python-pakketten (`pyproject.toml`)

| Pakket | Waarvoor |
| --- | --- |
| `fastapi` | De web-app |
| `uvicorn[standard]` | De webserver onder FastAPI |
| `jinja2` | HTML-sjablonen van de pagina en de instellingen |
| `python-multipart` | Formulieren (invulbalkje, instellingen) |
| `httpx` | Alle uitgaande verzoeken: iCal, MCP, RSS, Web Push |
| `icalendar` | iCal-bestanden lezen |
| `recurring-ical-events` | Herhalende afspraken uitrollen |
| `cryptography` | Versleuteling van koppelingen (Fernet), en ECDH, AES-GCM en ES256 voor Web Push |
| `defusedxml` | RSS veilig lezen (geen XML-bommen of externe entiteiten) |
| `pytest` (dev) | Tests |

Er is bewust geen OpenAI-SDK, geen `pywebpush` en geen MCP-SDK: de stukjes die nodig zijn, zijn klein en
zelf geschreven, met tests. Zo blijft de lijst kort en draait het overal.

### Frontend

Geen build-stap, geen framework. Gewone HTML, CSS en JavaScript in `src/dailyletter/web/static/`.
De enige externe aanvraag van de pagina is Google Fonts. Wie dat niet wil, zet de lettertypes in `static/`.

---

## 3. Koppelingen in detail

### Garmin-MCP

De eigen [Garmin-MCP](https://github.com/SirAdlerBD/Garmin-MCP) draait op dezelfde server, onder pm2.

| | |
| --- | --- |
| Adres | `http://127.0.0.1:<poort>/mcp`, Streamable HTTP. Standaard in de code: poort 3001; op de huidige server is het **3002** |
| Inloggen | `Authorization: Bearer <MCP_ACCESS_TOKEN>`, uit het `.env` van de Garmin-MCP |
| Koppelen | `dailyletter connect <gebruiker> garmin --from-env ~/garmin-mcp/.env --url http://127.0.0.1:3002/mcp` |
| Test bij koppelen | `get_sync_status` |
| Tools die gebruikt worden | `get_recovery_snapshot {date}`, `list_activities {start, end, limit: 300}` (28 dagen), `get_profile {}` (optioneel, voor zone 2) |
| Feiten | `{date, sleep{hours,score}, hrv{last_night,status,baseline_low,baseline_high}, resting_hr{today,avg_7d}, body_battery_high, load{acute_7d,chronic_weekly,ratio}, zone2, activities[…]}` |
| Valkuilen | Geen officiële Training Readiness: herstel is een eigen berekening van de MCP. Niet gesynchroniseerd = de data van gisteren; dan geeft het briefje geen sportadvies. Een verlopen Garmin-sleutel geeft `AUTHENTICATION REQUIRED` |

### Saxo-MCP (LIVE)

De eigen [Saxo-MCP](https://github.com/SirAdlerBD/saxo-mcp), LIVE-omgeving, op dezelfde server.

| | |
| --- | --- |
| Adres | `http://127.0.0.1:3001/mcp` (de LIVE-server; check met `pm2 ls` en `sudo ss -tlnp`) |
| Inloggen | Bearer-token uit `~/saxo-mcp-live/.env` |
| Koppelen | `dailyletter connect <gebruiker> saxo --from-env ~/saxo-mcp-live/.env --url http://127.0.0.1:3001/mcp` |
| Test bij koppelen | `get_balances {wholeClient: true}` |
| Toegelaten tools | **Alleen** `get_balances`, `get_positions`, `get_account_history` (`ALLOWED_TOOLS`). Elke andere tool wordt geweigerd voor het verzoek vertrekt. De Saxo-MCP blokkeert handelen bovendien zelf |
| Aanroepen | `get_balances {wholeClient: true}`; `get_positions {view: "net", wholeClient: true}`; `get_account_history {report: "timeseries", wholeClient: true, fromDate, toDate}` |
| Velden (Saxo OpenAPI) | `NetPositionBase.AssetType`; `NetPositionView.MarketValueInBaseCurrency` (of `ExposureInBaseCurrency`), `InstrumentPriceDayPercentChange` (in procent), `MarketValueOpenInBaseCurrency`, `ProfitLossOnTradeInBaseCurrency`; `DisplayAndFormat.Symbol`, `.Description`; rendement uit `TimeWeighted.Accumulated` |
| Feiten | `{date, currency, total_value, cash, open_orders, positions[{symbol,name,asset_type,value,day_pct,pl_value,pl_pct}], twr[[date, fractie]]}` |
| Valkuilen | De Saxo-login verloopt af en toe: het briefje zegt dat, en je logt opnieuw in zoals bij je Saxo-MCP (`npm run login`). Port 3001 is LIVE, niet SIM |

### Eigen MCP-client

`sources/mcp_client.py` spreekt Streamable HTTP (JSON-RPC over POST, antwoorden als JSON of SSE),
protocolversie `2025-03-26`, met de headers `Mcp-Session-Id` en `MCP-Protocol-Version`. Het token gaat alleen
in de header, nooit in een URL of foutmelding. `http://` mag alleen naar `127.0.0.1`, `localhost` of `::1`;
naar buiten alleen `https://`. Voor lokale adressen negeert de client proxy-instellingen (`trust_env=False`).

### iCal-agenda's

| | |
| --- | --- |
| Wat | Eén of meer geheime iCal-adressen per gebruiker, met een naam (bijvoorbeeld Privé en Werk), hoogstens 10 |
| Waar bewaard | Tabel `connections`, bron `agenda`, versleuteld als JSON-lijst `[{label, url}]` |
| Toevoegen | Instellingenpagina, of `dailyletter connect <gebruiker> agenda` |
| Google Calendar | Instellingen, je agenda, "Geheim adres in iCal-indeling" |
| Outlook | Instellingen, Agenda, Gedeelde agenda's, "Een agenda publiceren", ICS-link. Op een werkaccount kan IT het uitschakelen |
| Veiligheid | Het adres is een geheim: wie het heeft, leest je agenda. Het staat nooit in logs of foutmeldingen, alleen de naam van een agenda die faalde |

### Nieuws: RSS

Feeds zijn instellingen per gebruiker (`news_feeds`), geen geheimen. Toevoegen via de instellingenpagina of
`dailyletter news <gebruiker> add "Naam" <adres>`; het adres wordt eerst één keer gelezen.

**De Tijd.** Officiële RSS, gratis, titel en intro (het artikel zelf zit achter de betaalmuur). Het patroon is
`https://www.tijd.be/rss/<naam>.xml`, maar niet elke naam volgt de rubriek:

| Rubriek | Feed | Werkt |
| --- | --- | --- |
| Nieuws (top) | `nieuws.xml` | Ja |
| Markten Live | `markten_live.xml` | Ja |
| Mijn Geld | `netto.xml` | Ja (volgens de gebruiker) |
| Politiek | `politiek.xml`, `politiek_belgie.xml` | Ja (volgens de gebruiker) |
| Fondsen | `fondsen.xml` | Ja |
| Opinie | `opinie.xml` | Ja |
| Ondernemen per sector | `ondernemen_<sector>.xml`, bijvoorbeeld `ondernemen_banken.xml` | Ja |
| — | `top_stories.xml`, `mijn_geld.xml`, `politiek_economie_belgie.xml` | Nee: `{"error":"No RSS feed found"}` |

De overzichtspagina `https://www.tijd.be/rss` geeft vanaf een datacenter (zoals Oracle Cloud) "403 Bot
detection". De feeds zelf werken wel. Die blokkade niet omzeilen: zoek feednamen op in een gewone browser.

**Google News per positie.** Optioneel (`news_position_search`). Per aandeel (geen fondsen) één zoekfeed:
`https://news.google.com/rss/search?q="<naam>" when:3d&hl=nl&gl=BE&ceid=BE:nl` (editie uit `news_edition`).
De zoekterm is de naam zonder rechtsvorm ("Voorbeeld Holding N.V." wordt "Voorbeeld"). **Voorwaarden:** Google staat de feed
alleen toe "within a personal feed reader for personal, non-commercial use". Daarom staat het standaard uit en
mag het in een publieke versie niet zomaar aan.

**Grenzen in de code:** hoogstens 10 feeds, 2 MB per feed, 40 berichten per feed, alleen `http(s)`-links.

**Bekeken en niet gekozen:** Finnhub (gratis, maar bedrijfsnieuws alleen voor Noord-Amerikaanse bedrijven),
Marketaux (gratis, maar 3 artikels per aanvraag), FMP (onduidelijk of nieuws per aandeel in het gratis plan
zit), Alpha Vantage, GDELT. Finnhub kan later een derde bron worden voor Amerikaanse aandelen.

### Meldingen: Web Push

| | |
| --- | --- |
| Standaarden | RFC 8291 (versleuteling, `aes128gcm`) en RFC 8292 (VAPID, ES256). Zelf geschreven in `webpush.py`, getest tegen het officiële voorbeeld uit RFC 8291 |
| Sleutel | `DAILYLETTER_VAPID_PRIVATE` en `DAILYLETTER_VAPID_CONTACT` (mailto of https) in `.env`. Maken met `dailyletter gen-vapid --contact mailto:…` |
| Pushdiensten | Alleen `web.push.apple.com`, `fcm.googleapis.com`, `updates.push.services.mozilla.com`, `*.notify.windows.com`. Andere adressen worden geweigerd |
| Abonnementen | Tabel `push_subscriptions`, versleuteld, één per toestel. Een `404` of `410` van de pushdienst verwijdert het abonnement |
| Wanneer | `dailyletter notify` elk kwartier (`dailyletter-notify.timer`). Om de tijden in `notify_times` maakt het een vers briefje en stuurt het de begroeting en de volgende 3 regels. Hoogstens 45 minuten te laat, één keer per tijdstip (`notifications_sent`) |
| iPhone | Alleen voor een web-app op het beginscherm (iOS 16.4 of nieuwer), geopend vanaf het beginscherm. HTTPS is verplicht: dat geeft Tailscale |
| Privacy | De inhoud is versleuteld voor het toestel; Apple en Google kunnen ze niet lezen. Bedragen staan nooit in de regels |
| Service worker | `/sw.js`, geserveerd vanaf de root. Bewaart niets in de cache |

### Widget: Scriptable

De gratis iOS-app [Scriptable](https://scriptable.app) draait `web/static/widget-scriptable.js`. De
instellingenpagina vult het eigen adres in (`location.origin`) en biedt de code aan om te kopiëren. De widget
leest `GET /api/briefje` (JSON, `Cache-Control: no-store`). De gsm moet de server kunnen bereiken: Tailscale aan,
of "VPN On Demand" in de Tailscale-app. Wanneer de widget ververst, beslist iOS.

### Tailscale

De web-app luistert alleen op `127.0.0.1:8321`. `tailscale serve --bg 8321` zet ze door naar de eigen toestellen,
met HTTPS op een `*.ts.net`-adres. Er is geen publiek adres en geen inlogscherm. Wie in het tailnet zit, ziet
alles: dat is de enige toegangscontrole, en de reden dat de app nooit publiek mag staan.

### OpenAI (gepland, fase 2)

`OPENAI_API_KEY` en `OPENAI_MODEL` in `.env`. Zonder sleutel schrijft het briefje in sjabloonzinnen. Het model
krijgt nooit bedragen, rekeningnummers of foto's, alleen percentages, namen en beslissingen. Zet een
maandlimiet in het OpenAI-account.

### FMP (optioneel)

Niet in gebruik. Kandidaat voor datums van kwartaalcijfers en indexkoersen (fase 3). Hangt af van wat het
abonnement toelaat.

---

## 4. Poorten en processen op de server

| Wat | Adres | Beheerd door |
| --- | --- | --- |
| DailyLetter web-app | `127.0.0.1:8321` | `dailyletter-web.service` |
| Saxo-MCP LIVE | `127.0.0.1:3001` | pm2 (`saxo-mcp-live-http`) |
| Garmin-MCP | `127.0.0.1:3002` | pm2 (`garmin-mcp-http`), `HTTP_PORT=3002` in zijn `.env` |
| Tailscale | `https://<server>.<tailnet>.ts.net` → 8321 | `tailscale serve` |

### systemd-units (`deploy/`, gebruikersmodus)

| Unit | Wanneer | Doet |
| --- | --- | --- |
| `dailyletter-web.service` | Altijd | `dailyletter serve` |
| `dailyletter-run.timer` | 6u30, 12u00, 16u30, 21u00 (Europe/Brussels) | `dailyletter run` voor alle gebruikers |
| `dailyletter-notify.timer` | Elk kwartier | `dailyletter notify` |

De tijden van `dailyletter-run.timer` gelden voor de hele installatie. Bij meer gebruikers in andere tijdzones
moet dat per gebruiker worden, zoals de meldingen al werken.

`deploy/update.sh` haalt de code op (`git pull --ff-only`), installeert, werkt de database bij, kopieert de units,
zet de timers aan en herstart de web-app. Pas daarom nooit bestanden aan in de map op de server.

---

## 5. Instellingen

### Installatie (`.env`, nooit in git, `chmod 600`)

| Variabele | Standaard | Betekenis |
| --- | --- | --- |
| `DAILYLETTER_DATA_DIR` | `./data` | Map voor de database (en later foto's) |
| `DAILYLETTER_SECRET_KEY` | — (verplicht) | Fernet-sleutel voor koppelingen en abonnementen. Maken met `dailyletter gen-key`. Kwijt = alle koppelingen opnieuw maken |
| `DAILYLETTER_TIMEZONE` | `Europe/Brussels` | Tijdzone voor nieuwe gebruikers |
| `DAILYLETTER_HOST` / `DAILYLETTER_PORT` | `127.0.0.1` / `8321` | Waar de web-app luistert |
| `DAILYLETTER_USER` | — | Welke gebruiker de web-app toont als er meer dan één is |
| `DAILYLETTER_ENV_FILE` | `.env` | Welk bestand `gen-vapid` bijwerkt |
| `DAILYLETTER_VAPID_PRIVATE` / `_CONTACT` | — | Meldingen |
| `OPENAI_API_KEY` / `OPENAI_MODEL` | — | Taalmodel (fase 2) |

### Per gebruiker (tabel `settings`, JSON-waarden)

Tonen of wijzigen met `dailyletter settings <gebruiker> [sleutel [waarde]]`. De standaardwaarden staan in de
`DEFAULTS` van `decide.py`, `decide_sport.py`, `decide_portfolio.py` en `decide_news.py`.

| Sleutel | Standaard | Betekenis |
| --- | --- | --- |
| `version_until` | ochtend tot 12:00, middag tot 16:00, vooravond tot 20:30 | Wanneer een versie eindigt |
| `day_end` | `18:00` | Einde van de werkdag, voor het vrije blok |
| `min_free_block_minutes` | `30` | Kortste vrije blok dat telt |
| `busy_from_meetings` | `4` | Vanaf hoeveel afspraken een dag druk is |
| `notify_times` | `["07:30"]` | Tijdstippen voor een melding |
| `long_run_day` | geen | Dag voor de lange run |
| `max_week_increase` | `0.1` | Hoeveel het looptotaal per week mag stijgen |
| `week_km_target` | geen | Weekdoel uit het trainingsplan |
| `min_run_km` / `default_run_km` | `4.0` / `5.0` | Kortste voorgestelde run / afstand zonder geschiedenis |
| `portfolio_mover_pct` | `3.0` | Vanaf welke dagbeweging een positie genoemd wordt |
| `portfolio_concentration_pct` | `20.0` | Vanaf welk gewicht het grootste losse aandeel vermeld wordt |
| `news_feeds` | `[]` | `[{label, url}]`; de eerste feed geeft de topkop |
| `news_position_search` | `false` | Google News per positie |
| `news_edition` | `BE:nl` | Google News-editie |
| `news_max_positions` | `8` | Hoeveel posities nieuws krijgen |
| `news_general_count` / `news_per_position` | `3` / `2` | Koppen per feed / per positie in het paneel |

---

## 6. Database (SQLite, `data/dailyletter.sqlite3`)

Migraties staan in `src/dailyletter/migrations/` en lopen met `dailyletter init`.

| Tabel | Bevat |
| --- | --- |
| `users` | Naam, weergavenaam, tijdzone, taal |
| `connections` | Per gebruiker en bron de versleutelde toegang (iCal-adressen, MCP-adres en token) |
| `settings` | Voorkeuren per gebruiker, als JSON |
| `snapshots` | Ruwe feiten per bron per ophaalmoment, met `ok` en `error` |
| `briefings` | Eén briefje per gebruiker, datum en versie, als JSON; `writer` en `fallback` |
| `inbox` | Wat in het invulbalkje getypt werd; `kind` en `processed` voor fase 2 |
| `push_subscriptions` | Versleutelde pushabonnementen, met laatste succes en fout |
| `notifications_sent` | Welke melding vandaag al vertrok |

Gepland (zie PLAN.md): `tasks`, `goals`, `entries`, `feedback`, `focus_sessions`, `recipes`, `meal_plans`,
`lessons`, `quotes`, `position_notes`.

---

## 7. Commando's en webroutes

### `dailyletter …`

| Commando | Doet |
| --- | --- |
| `init` | Database maken of bijwerken |
| `gen-key` | Sleutel voor `DAILYLETTER_SECRET_KEY` |
| `gen-vapid --contact …` | Sleutel voor meldingen, meteen in `.env` |
| `user add <naam> --display-name …` / `user rename` | Gebruikers |
| `connect <gebruiker> agenda\|garmin\|saxo [--from-env F] [--url U]` | Koppeling testen en versleuteld bewaren |
| `settings <gebruiker> [sleutel [waarde]]` | Instellingen |
| `news <gebruiker> [list\|add\|remove\|test]` | Nieuwsfeeds |
| `run [--user] [--version] [--show]` | Een briefje maken |
| `notify [--user] [--test]` | Meldingen die nu aan de beurt zijn, of een test |
| `serve` | De web-app |

### Webroutes

| Route | Doet |
| --- | --- |
| `GET /` | Het briefje |
| `GET /instellingen` | Instellingen |
| `POST /inbox` | Invulbalkje |
| `POST /refresh` | Nu een briefje maken |
| `POST /instellingen/agenda`, `/instellingen/agenda/verwijder` | Agenda's |
| `POST /instellingen/nieuws`, `/nieuws/verwijder`, `/nieuws/posities` | Nieuws |
| `POST /instellingen/meldingen/tijden` | Tijdstippen voor meldingen |
| `POST /meldingen/abonneer`, `/meldingen/uitschrijven`, `/meldingen/test` | Pushabonnementen (JSON) |
| `GET /api/briefje` | Het briefje als regels, voor de widget |
| `GET /sw.js` | Service worker |
| `GET /healthz` | Controle |

Elke `POST` van een andere website wordt geweigerd (`Origin` en `Sec-Fetch-Site`). Er is geen login: Tailscale is
de toegangscontrole.
