"""Dutch sentences for the template writer (and the fallback once a model writes).

All user-facing wording lives here, so another language is another file like this one.
"""

from __future__ import annotations

from datetime import datetime

MONTHS = ["januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus",
          "september", "oktober", "november", "december"]
WEEKDAYS = ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"]

GREETING = {
    "morning": "Goeiemorgen {name}.",
    "midday": "Goeiemiddag {name}.",
    "afternoon": "Goeienamiddag {name}.",
    "evening": "Goeienavond {name}.",
}

T = {
    "agenda.missing": "Je agenda is nog niet gekoppeld. Plak je iCal-adres bij de instellingen.",
    "agenda.stale": "Je agenda kon niet ververst worden. Dit is de versie van {when}.",
    "agenda.partial": "Je agenda {names} kon niet gelezen worden. Wat erin staat, ontbreekt hier.",
    "agenda.empty_today": "Vandaag staat er niets in je agenda. De dag is van jou.",
    "agenda.first_far": "Je eerste afspraak is pas over {duration}. Tot dan is je agenda vrij.",
    "agenda.next_far": "Je volgende afspraak is pas over {duration}. Tot dan is je agenda vrij.",
    "agenda.first_near": "Je eerste afspraak begint over {duration}: {title}.",
    "agenda.next_near": "Je volgende afspraak begint over {duration}: {title}.",
    "agenda.now": "Je zit nu in {title}, tot {end}.",
    "agenda.count_today": "Vandaag {count} afspraken, de laatste eindigt om {end}.",
    "agenda.all_day": "Ook vandaag: {titles}.",
    "agenda.done": "Je afspraken van vandaag zitten erop.",
    "agenda.rest_empty": "Je agenda is leeg voor de rest van de dag.",
    "agenda.remaining_one": "Nog één afspraak vandaag: {title}, tot {end}.",
    "agenda.remaining_many": "Nog {count} afspraken vandaag, de laatste eindigt om {end}.",
    "agenda.free_block": "Je langste vrije blok loopt van {start} tot {end}.",
    "agenda.tomorrow_empty": "Morgen staat er niets in je agenda.",
    "agenda.tomorrow_first": "Morgen begint met {title} om {start}.",
    "agenda.tomorrow_busy": "Het wordt een volle dag: {count} afspraken.",

    # Energy (morning)
    "energy.good": "Goed geslapen: {sleep}, batterij op {battery}.",
    "energy.short": "Korte nacht: {sleep}, batterij op {battery}.",
    "energy.plain": "Je sliep {sleep}, batterij op {battery}.",
    "energy.good_nobattery": "Goed geslapen: {sleep}.",
    "energy.short_nobattery": "Korte nacht: {sleep}.",
    "energy.plain_nobattery": "Je sliep {sleep}.",

    # Sport: the one line in the letter
    "sport.unknown": "Nog geen slaapdata van vannacht. Synchroniseer je horloge, dan volgt je sportadvies.",
    "sport.stale": "Je Garmin-data kon niet ververst worden. Kijk of je horloge gesynchroniseerd is.",
    "sport.rest": "Rustdag. {why}.",
    "sport.strength": "Kracht vandaag, geen lopen. {why}.",
    "sport.easy_run": "Rustige run: {km} km in zone 2{hr}.",
    "sport.short_run": "Rustig en korter: {km} km in zone 2{hr}. {why}.",
    "sport.long_run": "Lange run vandaag: {km} km, rustig in zone 2{hr}.",
    "sport.done_morning": "Al getraind vandaag: {summary}.",
    "sport.done_day": "Je training van vandaag zit erop: {summary}.",
    "sport.open_day": "Je training staat nog open: {session}.",
    "sport.done_evening": "Vandaag: {summary}.",
    "sport.hr": " ({low}–{high} slagen)",

    # Sport: why (first one goes in the sentence, all of them in the detail panel)
    "why.sleep_short": "Je sliep maar {hours}",
    "why.hrv_off": "Je HRV is niet in balans",
    "why.rhr_high": "Je rusthartslag ligt {delta} slagen boven je gemiddelde",
    "why.load_spike": "Je belasting ligt veel hoger dan je gewend bent",
    "why.load_high": "Je belasting loopt op",
    "why.weak_signals": "Je herstel is niet top",
    "why.hard_recent_1": "Gisteren was zwaar",
    "why.hard_recent_2": "Eergisteren was zwaar",
    "why.hard_recent_0": "Je trainde vandaag al zwaar",
    "why.no_rest_day": "Je trainde {days} dagen op rij",
    "why.impact_streak": "Je had al {days} dagen op rij impact",
    "why.week_full": "Je liep al {km} km deze week",
    "why.long_run_day": "Je langste run van de laatste vier weken was {longest} km",

    # Portfolio
    "portfolio.morning": "Je portefeuille: {when} {day}, deze week {week}.",
    "portfolio.morning_day": "Je portefeuille: {when} {day}.",
    "portfolio.morning_week": "Je portefeuille: deze week {week}.",
    "portfolio.evening": "Je portefeuille vandaag: {day}.",
    "portfolio.mover": " {name} bewoog het meest: {move}.",
    "portfolio.stale": "Je Saxo-gegevens konden niet ververst worden.",
    "portfolio.login": "Je Saxo-login is verlopen. Log opnieuw in op de server, dan komt je portefeuille terug.",
    "portfolio.concentrated": "{name} is {weight} van je portefeuille.",
    "portfolio.note": "Alleen lezen: DailyLetter kan niets kopen of verkopen. Bedragen blijven verborgen tot je op het oog tikt.",

    # News
    "news.top": "In {source}: {title}",
    "news.mover": "Nieuws over {name}: {title}",
    "news.failed": "Niet gelezen: {names}.",
    "news.note": "Koppen uit je nieuwsfeeds en, als je dat aanzette, uit Google News per positie. Tik op een kop om het artikel te openen.",

    # Sport: short names for the session, used midday
    "session.easy_run": "een rustige run van {km} km",
    "session.short_run": "een korte rustige run van {km} km",
    "session.long_run": "je lange run van {km} km",
    "session.strength": "kracht, geen lopen",
}

READINESS_LABEL = {"green": "Groen licht", "yellow": "Rustig aan", "red": "Rust", "unknown": "Nog onbekend"}
HRV_STATUS = {"BALANCED": "in balans", "UNBALANCED": "niet in balans", "LOW": "laag", "POOR": "slecht"}
DAYS_SHORT = ["ma", "di", "wo", "do", "vr", "za", "zo"]
GROUP_LABEL = {"running": "Run", "racket": "Racket", "strength": "Kracht", "cycling": "Fiets",
               "swimming": "Zwem", "walking": "Wandel", "other": "Sport"}
TYPE_LABEL = {"tennis": "Tennis", "padel": "Padel", "squash": "Squash", "badminton": "Badminton"}


def number(value: float, digits: int = 1) -> str:
    """8.5 -> '8,5', 8.0 -> '8', 1.08 (digits=2) -> '1,08'."""
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


CURRENCY_SIGN = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def signed_pct(value: float, digits: int = 1) -> str:
    """0.42 -> '+0,4%', -4.1 -> '−4,1%' (a real minus sign), 0.0 -> '0,0%'."""
    text = f"{abs(value):.{digits}f}".replace(".", ",")
    if round(value, digits) > 0:
        return f"+{text}%"
    if round(value, digits) < 0:
        return f"−{text}%"
    return f"{text}%"


def pct(value: float) -> str:
    """42.4 -> '42%'."""
    return f"{round(value):d}%"


def money(value: float, currency: str | None) -> str:
    """48320.4 -> '€ 48.320'."""
    whole = f"{round(value):,d}".replace(",", ".")
    return f"{CURRENCY_SIGN.get(currency or '', currency or '')} {whole}".strip()


def hours_minutes(hours: float) -> str:
    """7.5 -> '7u30', 6.0 -> '6u'."""
    total = round(hours * 60)
    h, m = divmod(total, 60)
    return f"{h}u{m:02d}" if m else f"{h}u"


def activity_label(activity_type: str, group: str) -> str:
    for key, label in TYPE_LABEL.items():
        if key in activity_type:
            return label
    return GROUP_LABEL.get(group, "Sport")


def join_names(names: list[str]) -> str:
    """['Werk'] -> '“Werk”', ['Werk', 'Sport'] -> '“Werk” en “Sport”'."""
    quoted = [f"“{name}”" for name in names]
    if len(quoted) <= 1:
        return "".join(quoted)
    return ", ".join(quoted[:-1]) + " en " + quoted[-1]


def clock(moment: datetime) -> str:
    """13:30 -> '13u30', 9:00 -> '9u'."""
    return f"{moment.hour}u{moment.minute:02d}" if moment.minute else f"{moment.hour}u"


def duration(minutes: int) -> str:
    """50 -> '50 minuten', 60 -> '1 uur', 350 -> '5u50'."""
    if minutes < 60:
        return "1 minuut" if minutes == 1 else f"{minutes} minuten"
    hours, rest = divmod(minutes, 60)
    return f"{hours}u{rest:02d}" if rest else f"{hours} uur"


def long_date(moment: datetime) -> str:
    """'maandag 16 november'."""
    return f"{WEEKDAYS[moment.weekday()]} {moment.day} {MONTHS[moment.month - 1]}"


def short_when(moment: datetime, now: datetime) -> str:
    """'6u30' for today, '15 november, 21u' for another day."""
    if moment.date() == now.date():
        return clock(moment)
    return f"{moment.day} {MONTHS[moment.month - 1]}, {clock(moment)}"


HEADLINE_LENGTH = 150


def headline(title: str) -> str:
    """A feed title as the end of a sentence: cut to a calm length, closed with a period."""
    text = " ".join(title.split())
    if len(text) > HEADLINE_LENGTH:
        text = text[: HEADLINE_LENGTH - 1].rsplit(" ", 1)[0] + "…"
    return text if text[-1] in ".?!…\"”’'" else text + "."
