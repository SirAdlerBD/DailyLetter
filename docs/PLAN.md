# DailyLetter: het plan

Dit is het volledige plan: wat DailyLetter is, wat er al werkt, wat er nog komt in kleine stappen, en welke
vragen nog open staan. Het is geschreven zodat iemand (of een ander AI-model) na `git clone` meteen verder kan.

Afhankelijkheden, koppelingen, poorten en instellingen staan apart in [INTEGRATIES.md](INTEGRATIES.md).
Installeren en dagelijks gebruik staan in de [README](../README.md). Werkafspraken voor een AI-assistent staan
in [AGENTS.md](../AGENTS.md).

Laatst bijgewerkt: 18 november 2026.

---

## 1. Het idee

DailyLetter is één rustige pagina die je op elk moment van de dag opent en die in een paar zinnen zegt wat er
speelt en waar je op focust. Het is een briefje, geen dashboard: korte tekst, en alles wat meer is zit achter
een tik.

Het ontwerp is bewust prikkelarm: weinig keuzes, geen schuldgevoel, één ding per moment. "Rustig" wint
altijd van "volledig".

### Spelregels

Elke keuze wordt hieraan getoetst.

1. **Eén scherm, weinig tekst.** Zinnen, geen grafieken of kolommen. Details openen pas na een tik.
2. **Niets nieuws krijgt een eigen blok.** Een nieuwe functie vervangt iets of zit achter een tik.
3. **Per moment vraagt de pagina één ding.** 's Ochtends starten aan het ene ding, 's avonds één zin.
4. **Geen schuldgevoel.** Geen achterstand, geen rode cijfers, geen reeksen die je kunt breken.
5. **Hoe drukker de dag, hoe korter het briefje.** Een volle agenda en weinig energie geven drie zinnen.
6. **Het leeft mee met de klok.** 's Ochtends energie en focus, na 16u eten, na 21u terugblikken.
7. **De code beslist, het taalmodel schrijft.** Cijfers en beslissingen komen uit vaste regels.
8. **Alleen lezen.** Het briefje handelt nooit op de broker en wijzigt niets in Garmin of de agenda.
9. **Niets hardcoden.** Alles wat van een persoon is, staat in de database of `.env`, nooit in de code.
   Zo kan dezelfde code later voor andere mensen draaien.
10. **Zo goed als gratis.** Alles draait op een gratis server; alleen het taalmodel kost straks een paar euro.

### Vier versies per dag

| Versie | Klaar om | Wat het briefje zegt | Wat het vraagt |
| --- | --- | --- | --- |
| Ochtend | 6u30 | Energie, tijd tot de eerste afspraak, sport, portefeuille en nieuws, quote, vraag en les van de dag | Starten aan het ene ding |
| Middag | 12u00 | Wat er nog komt, of het ene ding af is, eventueel bijgestuurde sport | Niets |
| Vooravond | 16u30 | Wat er vanavond op het weekmenu staat, met een voorstel om te wisselen als het niet past | Niets |
| Avond | 21u00 | Korte terugblik, blik op morgen | Eén zin of foto: wat was leuk vandaag? |

Onderaan elke versie: de horizon met langetermijndoelen en één invulbalkje voor een taak, idee of feedback.
Op zondag komt het weekmenu voor de komende week erbij, met de boodschappenlijst.

### Achter elke zin een detailpaneel

| Je tikt op | Je krijgt | Status |
| --- | --- | --- |
| Agenda | De afspraken van vandaag en morgen, per agenda | Werkt |
| Sport | De sessie, de redenen, herstel, je week, kilometers | Werkt (zonder VO2max en weg naar het loopdoel) |
| Portefeuille | Waarde (standaard verborgen), rendement dag, week en jaar, posities met gewicht | Werkt (zonder index) |
| Nieuws | Koppen per positie en per feed, met link | Werkt |
| Energie | Slaap, slaapscore, rusthartslag, HRV, 7 nachten | Deels: zit nu in het sportpaneel |
| Een positie | Koers van 3 maanden, rendement, nieuws, volgende cijfers, je aankoopnotitie | Nog niet |
| Quote | Waarom ze vandaag past, wie het zei | Nog niet |
| Vraag van de dag | Wat er gebeurde, je aankoopnotitie, een vak voor je antwoord | Nog niet |
| Les van de dag | Een les van 2 minuten binnen een weekthema, met één quizvraag | Nog niet |
| Het ene ding | Kleine stappen, een focustimer, de rest van je taken | Nog niet |
| Een gerecht | Recept met hoeveelheden, wisselen met een andere dag | Nog niet |
| Horizon | Mijlpalen en de volgende kleine stap per doel | Nog niet |

---

## 2. Architectuur

Twee kleine programma's op één server doen al het werk. De batchjob leest de bronnen; de web-app leest alleen
de database. Daardoor opent de pagina meteen, ook als een bron traag is of uitligt.

```
                ┌──────────── server (Oracle Always Free, Ubuntu) ─────────────┐
 Garmin-MCP ──┐ │                                                               │
 Saxo-MCP ────┤ │  batchjob (systemd-timer 4x/dag)          web-app (FastAPI)  │
 iCal ────────┼─┼─▶ verzamelen → beslissen → schrijven ─▶ SQLite ─▶ pagina ────┼──▶ Tailscale ──▶ gsm / pc
 RSS ─────────┘ │     → controleren → bewaren                 │      /api/briefje┼──▶ Scriptable-widget
                │                                             └─▶ notify-timer ─┼──▶ Web Push (Apple/Google) ──▶ melding
                └───────────────────────────────────────────────────────────────┘
```

### Hoe een briefje gemaakt wordt

1. **Verzamelen.** Elke bron wordt apart opgehaald, met een tijdslimiet. Het ruwe antwoord wordt bewaard in
   `snapshots`. Faalt een bron, dan telt het laatste goede antwoord, met status `stale`.
2. **Beslissen (code).** Vaste regels bepalen het sportadvies, de tijd tot de eerste afspraak, wat er opvalt
   in de portefeuille en welk nieuws telt. Bestanden: `decide*.py`.
3. **Kiezen (model, fase 2).** Het model kiest welke nieuwsartikels echt relevant zijn en welke quote past.
4. **Schrijven.** Nu: vaste sjabloonzinnen in `compose.py` + `texts_nl.py`. Vanaf fase 2 schrijft het model de
   zinnen uit de feiten en beslissingen, met de feedback van de laatste 14 dagen.
5. **Controleren (code).** Klopt de structuur, staat elk getal in de feiten, is het kort genoeg? Zo niet, dan
   terug naar de sjabloonzinnen.
6. **Bewaren.** Het briefje gaat als JSON in `briefings`. De pagina toont altijd het recentste.

Een briefje is een lijst regels. Elke regel heeft een `id`, een `text` en optioneel een `detail` (het paneel
erachter). De panelen worden door code gebouwd uit de feiten, nooit door het model.

### Bronnen zijn inplugbaar

Elke bron is een klasse in `src/dailyletter/sources/` met `name`, `needs_connection` en
`fetch(secret, window) -> dict`. Ze levert een vaste soort feiten. Garmin kan later Strava worden en Saxo een
andere broker, zonder dat de rest verandert. Wie een bron niet koppelt, krijgt gewoon die zin niet.

Elke bron heeft een status: `fresh`, `stale` of `missing`. Het briefje zegt het eerlijk als iets oud is.

---

## 3. Wat er nu werkt

Stand op 18 november 2026, commit `ea62387`. 125 tests slagen.

| Onderdeel | Wat het doet | Bestanden |
| --- | --- | --- |
| Fundament | SQLite met migraties, gebruikers, versleutelde koppelingen (Fernet), instellingen per gebruiker, batchjob, web-app, systemd-units, `deploy/update.sh` | `db.py`, `crypto.py`, `config.py`, `pipeline.py`, `cli.py`, `deploy/` |
| Agenda | Meerdere iCal-agenda's per gebruiker, samengevoegd zonder dubbels; tijd tot de eerste afspraak, langste vrije blok, drukke dag | `sources/agenda_ical.py`, `decide.py` |
| Sport | Herstel uit Garmin, rood/geel/groen, patroonregels, weekbudget, lange-rundag, weekdoel | `sources/garmin_mcp.py`, `decide_sport.py` |
| Portefeuille | Saxo LIVE, alleen leestools; dag-, week- en jaarrendement (tijdgewogen), grootste beweger, concentratie; bedragen verborgen tot een tik | `sources/saxo_mcp.py`, `decide_portfolio.py` |
| Nieuws | Eigen RSS-feeds (De Tijd), optioneel Google News per positie; recent, relevant, geen dubbels | `sources/news_rss.py`, `decide_news.py` |
| MCP-client | Eigen minimale Streamable HTTP-client, token alleen in de header, http alleen naar localhost | `sources/mcp_client.py` |
| Pagina | Briefje, detailpanelen, invulbalkje (bewaart alleen), instellingenpagina, avondthema | `web/` |
| Op de gsm | Installeerbaar op het beginscherm, pushmeldingen op vaste tijden, Scriptable-widget | `webpush.py`, `notify.py`, `web/static/sw.js`, `web/static/widget-scriptable.js` |

**Nog niet bevestigd op het echte toestel:** de meldingen en de widget zijn gebouwd en getest met
gesimuleerde toestellen, maar nog niet op de iPhone van de gebruiker.

---

## 4. Wat er nog komt, in kleine stappen

Elke stap is klein genoeg voor één sessie en eindigt met iets wat werkt. Schrijf bij elke stap tests, draai
`python -m pytest`, en werk de README bij als er iets verandert voor de gebruiker.

### Fase 1b: onderhoud (eerst)

- [ ] **1. Nachtelijke kopie.** Een commando `dailyletter backup` dat de database kopieert met de
      backup-API van SQLite (`conn.backup`), naar `data/backups/`, en de laatste 14 kopieën houdt. Een timer
      `dailyletter-backup.timer` om 3u. *Klaar als:* er elke ochtend een kopie van vannacht staat.
      Waar de tweede kopie buiten de server heen gaat, is een open vraag (zie §5).
- [ ] **2. Oude snapshots opruimen.** In dezelfde nachtelijke job: snapshots ouder dan 30 dagen weg, behalve
      het laatste goede antwoord per bron. *Klaar als:* de database niet blijft groeien.
- [ ] **3. Saxo-cijfers controleren.** De gebruiker vergelijkt het rendement van gisteren, deze week en dit
      jaar met de Saxo-app. Wijkt het af, kijk dan eerst naar `decide_portfolio._return_since` en naar
      `InstrumentPriceDayPercentChange` (wordt dat voor beursopening al gereset?).
- [ ] **4. Meldingen en widget op de iPhone testen.** Zie de README. Fouten staan in
      `push_subscriptions.last_error` en in de uitvoer van `dailyletter notify --test`.

### Fase 2: het model schrijft

Het moeilijkste deel: de toon vraagt een paar weken bijsturen. Daarom komt het vroeg.

- [ ] **1. Modelclient.** `llm.py`: één functie die de OpenAI-API aanroept met `httpx` (geen SDK nodig), met
      gestructureerde JSON-uitvoer, een tijdslimiet en `OPENAI_MODEL` uit `.env`. Zonder sleutel: geen
      oproep. *Klaar als:* een test met een nep-transport een geldig antwoord teruggeeft.
- [ ] **2. Feiten voor het model.** Een functie die van de beslissingen een compact JSON-object maakt.
      **Nooit bedragen, rekeningnummers of foto's**, alleen percentages, namen en woorden.
      *Klaar als:* een test bewijst dat er geen enkel bedrag in zit.
- [ ] **3. De schrijfopdracht.** Toonregels (kort, rustig, geen uitroeptekens, geen schuldgevoel), de feiten,
      de toegestane `detail`-waarden, de maximale lengte, en de feedback van de laatste 14 dagen.
- [ ] **4. Controle en terugval.** Structuur klopt, elk getal in de tekst staat in de feiten, hoogstens
      `MAX_LINES` regels, elke `detail` is toegestaan. Anders: het sjabloonbriefje. Bewaar in `briefings`
      welk model schreef (`writer`) en of de terugval gebruikt werd (`fallback`).
      *Klaar als:* een kapot of verzonnen antwoord altijd een sjabloonbriefje oplevert.
- [ ] **5. Het balkje sorteren.** Wat de gebruiker typt, wordt `taak`, `idee` of `feedback` (`inbox.kind`).
      Feedback gaat mee in de schrijfopdracht. Een voorkeur die blijft terugkomen, wordt een vaste instelling
      (nieuwe tabel `feedback`).
- [ ] **6. Nieuws kiezen.** Het model bevestigt welke kandidaten uit `decide_news` echt relevant zijn en
      schrijft in één zin waarom. Hooguit twee per briefje.

### Fase 3: beleggen afronden

- [ ] **1. Vergelijkingsindex.** Rendement tegenover een index (open vraag welke, en uit welke bron).
      Via Saxo betekent dat `get_chart_data` toevoegen aan `ALLOWED_TOOLS`, wat nog steeds een leestool is.
- [ ] **2. Paneel per positie.** Koers van 3 maanden (Saxo `get_chart_data`), rendement, nieuws,
      volgende kwartaalcijfers, aankoopnotitie (nieuwe tabel `position_notes`).
- [ ] **3. Vraag van de dag.** Alleen als een positie meer dan 3% beweegt of er cijfers aankomen. Anders geen
      vraag. Het antwoord wordt bewaard bij de positie.
- [ ] **4. Les van de dag.** Tabel `lessons` (week, volgorde, titel, inhoud, quizvraag), gedeeld door alle
      gebruikers. Per week één thema met vijf lessen, vooraf geschreven en nagekeken door de gebruiker.
      Het model past alleen het voorbeeld aan op de eigen posities. Inhoud als bestanden in `content/lessons/`
      en een commando om ze in te laden.
- [ ] **5. Quote.** Tabel `quotes` met echte, nagekeken quotes, auteur en trefwoorden. Het model kiest, maar
      verzint er nooit een.

### Fase 4: doen

- [ ] **1. Taken.** Tabel `tasks`: tekst, status, eerste stap, hoe vaak doorgeschoven, op welke dag het "het
      ene ding" was. Komen binnen via het balkje.
- [ ] **2. Het ene ding.** Het systeem stelt elke ochtend één taak voor; met één tik kies je een andere.
      Voor een grote taak stelt het model een eerste stap van 5 minuten voor.
- [ ] **3. Doorschuiven zonder schuld.** Wat blijft liggen, schuift stil door. Na drie keer komt één keer de
      vraag "Nog belangrijk?".
- [ ] **4. Focustimer.** Volledig in de browser: 10, 25 of 45 minuten. Alleen "gestart" en "afgewerkt" worden
      bewaard (tabel `focus_sessions`). Geen reeksen tellen.
- [ ] **5. Horizon.** Tabel `goals`: naam, soort, start, doel, voortgang. Onderaan het briefje, met de
      volgende kleine stap per doel.

### Fase 5: avond en eten

- [ ] **1. Wat was leuk.** De avondversie vraagt één zin of een foto. Tabel `entries`. Foto's als bestand in
      een map per gebruiker (grootte beperken, EXIF-locatie verwijderen), nooit naar het taalmodel.
- [ ] **2. Weekoverzicht.** Zondagavond toont het briefje de week. Nooit een reeks.
- [ ] **3. Gerechten.** Tabel `recipes`: naam, minuten, kenmerken, ingrediënten, stappen, laatst gegeten.
      De gebruiker levert zijn eigen gerechten aan (open vraag).
- [ ] **4. Weekmenu.** Op zondag een voorstel uit de eigen gerechten: snel op dagen met een late afspraak,
      uitgebreider op vrije avonden, meer koolhydraten na een lange run. Wisselen kan; één boodschappenlijst.
      Tabel `meal_plans`.
- [ ] **5. Vooravond.** Om 16u30 het gerecht van vanavond. Past het niet meer bij de agenda, dan het voorstel
      om twee dagen te wisselen.

### Kleinere wensen die al eens ter sprake kwamen

- Sport: een zelfmelding van pijn of een blessure die boven elke andere sportregel gaat. Hoe de
  gebruiker dat meldt, is nog open.
- Sport: VO2max-trend en de weg naar het loopdoel in het sportpaneel.
- Sport: een trainingsplan dat zelf meegroeit, in plaats van `week_km_target` met de hand aan te passen.
- Een echte iOS-app is bewust uitgesteld (zie §6). De widget en meldingen dekken dat nu.

---

## 5. Open vragen

Wie verder bouwt, vraagt deze eerst aan de gebruiker. Niets hiervan houdt de volgende stap tegen, behalve waar
het erbij staat.

| # | Vraag | Voorstel | Houdt tegen |
| --- | --- | --- | --- |
| 1 | Kloppen de Saxo-rendementen met de Saxo-app? | Gebruiker vergelijkt één dag | Niets, maar wel vóór fase 3 |
| 2 | Welke vergelijkingsindex, uit welke bron? | MSCI World, via de koers van een wereld-ETF in Saxo | Fase 3, stap 1 |
| 3 | Waar gaat de nachtelijke kopie heen buiten de server? | Oracle Object Storage (gratis 20 GB) of de eigen pc via `rsync` | Fase 1b, stap 1 (deel 2) |
| 4 | Welk OpenAI-model, en welke maandlimiet? | Het kleinste recente model, limiet € 5 per maand in het OpenAI-account | Fase 2 |
| 5 | Welke eigen gerechten? | Een lijst van ongeveer 10 namen, details volgen | Fase 5 |
| 6 | Waar komen de datums van kwartaalcijfers vandaan? | FMP (als het abonnement het toelaat) of Saxo | Fase 3, stap 2 en 3 |
| 7 | Hoe meldt de gebruiker pijn of een blessure? | Een knop in het sportpaneel die 3 dagen geldt | Sportwens |
| 8 | Ook een melding 's avonds? | Standaard alleen 7u30; zelf in te stellen | Niets |
| 9 | Wat met nieuws achter de betaalmuur? | Alleen kop en intro tonen, nooit het artikel ophalen | Fase 2, stap 6 |
| 10 | Meer gebruikers ooit? | Pas na aanmelden, officiële API's en GDPR (zie §6) | Niets nu |

---

## 6. Bewust buiten beeld

- **Een publieke versie.** Daarvoor zijn nodig: echte accounts in plaats van Tailscale, officiële koppelingen
  (de eigen MCP's werken alleen voor de eigenaar), GDPR (gezondheids- en financiële data), en kosten per
  gebruiker. De code is er wel op voorbereid: elke tabel heeft een `user_id`, alles persoonlijks staat in de
  database. Google News per positie mag dan niet zonder meer: Google staat die feeds alleen toe voor
  persoonlijk, niet-commercieel gebruik.
- **Een native iOS-app.** Kan via sideloaden (vervalt elke 7 dagen) of de Apple Developer Program (€ 99 per
  jaar). Uitgesteld: de web-app op het beginscherm, meldingen en de widget geven bijna hetzelfde, gratis.
- **Automatisch uitrollen (CI/CD).** De gebruiker werkt lokaal in VS Code en zet de server zelf bij met
  `deploy/update.sh`.
- **Handelen.** Nooit. DailyLetter gebruikt alleen leestools.

---

## 7. Beslissingen tot nu toe

| Beslissing | Waarom |
| --- | --- |
| Eigen repo, los van andere projecten | Het briefje staat op zichzelf |
| Python, FastAPI, SQLite, systemd | Klein, geen beheer, draait op een gratis server |
| Toegang alleen via Tailscale | Geen publiek adres, dus niets om te kraken |
| Garmin en Saxo via de eigen MCP-servers | De login staat op één plek, bestaande code wordt hergebruikt |
| Agenda via geheime iCal-adressen, meerdere per gebruiker | Werkt met Google en Outlook, geen OAuth nodig |
| Nieuws via RSS: De Tijd + optioneel Google News per positie | Gratis, geen account; betaalde API's waren te beperkt |
| Taalmodel: OpenAI, met eigen sleutel | Keuze van de gebruiker; zonder sleutel werken de sjablonen |
| Het systeem stelt "het ene ding" voor, de gebruiker kan wisselen | Minder keuzes 's ochtends |
| Gerechten uit een eigen lijst, als weekmenu | Boodschappen blijven makkelijk |
| Lessen vooraf geschreven, door de gebruiker nagekeken | Geen verzonnen leerstof |
| Melding om 7u30, met de eerste regels van het briefje | Eén rustige melding per dag |
| Web-app + meldingen + Scriptable-widget in plaats van een iOS-app | Gratis, één codebasis |
| Geen CI/CD | Lokaal ontwikkelen, met de hand uitrollen |

---

## 8. Kosten

| Onderdeel | Per maand |
| --- | --- |
| Server (Oracle Always Free), opslag, HTTPS via Tailscale | € 0 |
| Garmin, Saxo, agenda, RSS, Google News | € 0 |
| Meldingen (Web Push via Apple en Google) | € 0 |
| Widget (Scriptable) | € 0 |
| Taalmodel, ongeveer 8 oproepen per dag (fase 2) | Een paar euro; zet een maandlimiet in het OpenAI-account |
