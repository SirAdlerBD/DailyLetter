# Werkafspraken voor AI-assistenten

Lees dit eerst, daarna [docs/PLAN.md](docs/PLAN.md) (wat er is en wat er komt) en
[docs/INTEGRATIES.md](docs/INTEGRATIES.md) (koppelingen, instellingen, poorten). De
[README](README.md) is de handleiding voor de gebruiker.

## Waar je begint

1. `python -m venv .venv` en `.venv/bin/pip install -e ".[dev]"` (Windows: `.venv\Scripts\pip`).
2. `python -m pytest`: alles moet slagen voor je iets verandert.
3. Kies de eerstvolgende open stap in `docs/PLAN.md` §4, of vraag de gebruiker welke.
4. Vraag de open vragen uit §5 die die stap tegenhouden, voor je bouwt.

## Harde regels

- **De repo is publiek.** Nooit iets persoonlijks in code, tests, docs of commits: geen namen van posities,
  bedragen, gezondheidsgegevens, e-mailadressen, IP-adressen, iCal-adressen, tokens of sleutels.
  Persoonlijke dingen staan in de database of in `.env` op de server.
- **Niets hardcoden.** Drempels, tijden, adressen en doelen zijn instellingen (`DEFAULTS` in `decide*.py`,
  tabel `settings`) of koppelingen (tabel `connections`, versleuteld).
- **Alleen lezen.** Nooit een tool toevoegen die handelt of iets wijzigt bij Saxo, Garmin of de agenda.
  `ALLOWED_TOOLS` in `sources/saxo_mcp.py` blijft een lijst met leestools.
- **De code beslist, het model schrijft.** Cijfers en beslissingen komen uit `decide*.py`. Het taalmodel krijgt
  nooit bedragen, rekeningnummers of foto's, en elk getal in zijn tekst moet in de feiten staan.
- **Geheimen nooit in de chat.** Vraag de gebruiker nooit een token, sleutel of iCal-adres te plakken. Geheimen
  gaan via `--from-env`, een verborgen invoer, of de instellingenpagina.
- **Een bron die faalt, mag het briefje niet tegenhouden.** Elke bron heeft `fresh`, `stale` of `missing`,
  en valt terug op het laatste goede antwoord.
- **Rustig.** Elke nieuwe functie vervangt iets of zit achter een tik. Zie de spelregels in PLAN.md §1.

## Werken met de gebruiker

- Taal: Nederlands voor de gebruiker, de pagina en de docs. Code, namen en commentaar in het Engels.
  Alle zinnen van het briefje staan in `src/dailyletter/texts_nl.py`.
- De gebruiker leert de terminal: **leg bij elk commando uit wat het doet**, kort.
- Ontwikkelen gebeurt lokaal (Windows, VS Code), dan `git push`. Op de server alleen
  `~/DailyLetter/deploy/update.sh`. Pas nooit bestanden aan in die map op de server: dan faalt de update.
- Commitberichten in het Nederlands, kort, met wat er voor de gebruiker verandert.
- Schrijf bij elke stap tests en werk de README bij als er voor de gebruiker iets verandert. Werk
  `docs/PLAN.md` (§3 en §4) en `docs/INTEGRATIES.md` bij als er iets af is of bijkomt.

## Waar wat staat

| Wat | Waar |
| --- | --- |
| Batchjob: verzamelen, beslissen, schrijven, bewaren | `src/dailyletter/pipeline.py` |
| Bronnen | `src/dailyletter/sources/` (één klasse per bron, contract in `sources/base.py`) |
| Regels | `decide.py` (agenda), `decide_sport.py`, `decide_portfolio.py`, `decide_news.py` |
| Zinnen en panelen | `compose.py`, `texts_nl.py` |
| Database en migraties | `db.py`, `migrations/*.sql` (nooit een bestaande migratie wijzigen, altijd een nieuwe) |
| Web-app | `web/app.py`, `web/templates/`, `web/static/` |
| Meldingen | `webpush.py`, `notify.py`, `web/static/sw.js` |
| Server | `deploy/` |
